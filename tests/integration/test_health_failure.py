"""Phase 3A failure isolation: a health-model failure must NEVER break
/energy/* or /dashboard/summary, and /machine-health degrades to ERROR
(no traceback)."""

from datetime import timedelta

from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory
from tests.integration.test_health_scenarios import (
    ABNORMAL,
    END,
    N_NORMAL_H,
    SCEN_H,
    STEP_S,
    _post_all,
)


def _prepare_normal(client):
    f = SimulatedFactory(DEFAULT_MACHINES, scenario="NORMAL", hours=N_NORMAL_H + SCEN_H,
                         step_s=STEP_S, seed=1, end=END,
                         scenario_start_h=N_NORMAL_H, scenario_duration_h=SCEN_H)
    tel, prod = f.run()
    _post_all(client, "/telemetry", tel)
    _post_all(client, "/production", prod)
    fit_start = (END - timedelta(hours=N_NORMAL_H + SCEN_H)).isoformat()
    fit_end = (END - timedelta(hours=SCEN_H)).isoformat()
    det_start = (END - timedelta(hours=SCEN_H)).isoformat()
    det_end = END.isoformat()
    assert client.post("/energy/baseline/fit",
                       json={"start": fit_start, "end": fit_end}).status_code == 200
    assert client.post("/machine-health/fit",
                       json={"start": fit_start, "end": fit_end}).status_code == 200
    return det_start, det_end


def test_energy_and_dashboard_survive_health_model_failure(client, monkeypatch):
    det_start, det_end = _prepare_normal(client)

    from services.machine_health import statistical as statmod

    def _boom(self, rows):
        raise RuntimeError("simulated model failure")

    monkeypatch.setattr(statmod.StatisticalHealthModel, "score", _boom)

    r = client.get("/energy/summary", params={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    r = client.post("/energy/anomalies/detect",
                    json={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    assert client.get("/dashboard/summary").status_code == 200

    # /machine-health degrades to ERROR rows, no traceback, still HTTP 200.
    r = client.post("/machine-health/score",
                    json={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    assert "traceback" not in r.text.lower()
    rows = client.get("/machine-health",
                      params={"start": det_start, "end": det_end}).json()["health"]
    assert rows, "ERROR rows must be persisted"
    assert {x["status"] for x in rows} == {"ERROR"}
    assert not [x for x in rows if x["state"] in ABNORMAL]
    assert "traceback" not in str(rows).lower()


def test_energy_routers_do_not_import_health():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for name in ("apps/backend/routers/energy.py", "apps/backend/routers/dashboard.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "machine_health" not in src, f"{name} must not depend on health"
