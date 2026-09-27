"""Phase 3A acceptance (integration, real test DB, through the API).

Fit the energy baseline + health reference on NORMAL history, then run the
scenario window:

    NORMAL                    -> 0 energy events, 0 health WARNING/CRITICAL, 0 insights
    HIGH_LOAD                 -> ENERGY_ONLY insights for the affected machine
    EQUIPMENT_DEGRADATION p=0 -> HEALTH_ONLY, 0 energy events
    EQUIPMENT_DEGRADATION p>0 -> COINCIDENT with both evidences
    HIGH_LOAD + omitted health-> ENERGY_ONLY_HEALTH_UNAVAILABLE, energy 200s

NORMAL runs on seeds 1, 2, 3 (seeded variability must never flag).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)
# 36 h NORMAL history (1.5x the MIN_BASELINE_INTERVALS / HEALTH_MIN_REF
# minima) + 24 h scenario window at 5-minute steps — the Phase-2 cadence
# the energy thresholds were calibrated at. Larger post chunks keep the
# suite fast.
N_NORMAL_H = 36
SCEN_H = 24
STEP_S = 300
POST_CHUNK = 5000

SEEDS_ALL = (1, 2, 3)
ABNORMAL = {"WARNING", "CRITICAL"}


def _post_all(client, path, packets, chunk=2000):
    for i in range(0, len(packets), chunk):
        r = client.post(f"{path}?backfill=true", json={"records": packets[i:i + chunk]})
        assert r.status_code == 200, r.text[:500]


def _prepare(client, scenario, seed=1, energy_penalty=None,
             omit_health=False, magnitude=None):
    kw = {}
    if energy_penalty is not None:
        kw["energy_penalty"] = energy_penalty
    if magnitude is not None:
        kw["magnitude"] = magnitude
    f = SimulatedFactory(DEFAULT_MACHINES, scenario=scenario, hours=N_NORMAL_H + SCEN_H,
                         step_s=STEP_S, seed=seed, end=END,
                         scenario_start_h=N_NORMAL_H, scenario_duration_h=SCEN_H,
                         omit_health_signals=omit_health, **kw)
    tel, prod = f.run()
    _post_all(client, "/telemetry", tel, chunk=POST_CHUNK)
    _post_all(client, "/production", prod, chunk=POST_CHUNK)
    fit_start = (END - timedelta(hours=N_NORMAL_H + SCEN_H)).isoformat()
    fit_end = (END - timedelta(hours=SCEN_H)).isoformat()
    det_start = (END - timedelta(hours=SCEN_H)).isoformat()
    det_end = END.isoformat()

    r = client.post("/energy/baseline/fit", json={"start": fit_start, "end": fit_end})
    assert r.status_code == 200, r.text[:500]
    fits = {x["machine_id"]: x for x in r.json()["fits"]}
    assert all(x["status"] == "OK" for x in fits.values()), fits

    r = client.post("/machine-health/fit", json={"start": fit_start, "end": fit_end})
    assert r.status_code == 200, r.text[:500]
    hfits = {x["machine_id"]: x for x in r.json()["fits"]}

    r = client.post("/energy/anomalies/detect", json={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    det = r.json()

    r = client.post("/machine-health/score", json={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    hscore = r.json()

    events = client.get("/energy/anomalies").json()["anomalies"]
    health = client.get("/machine-health",
                        params={"start": det_start, "end": det_end}).json()["health"]
    insights = client.get("/insights",
                          params={"start": det_start, "end": det_end}).json()["insights"]
    models = client.get("/machine-health/models").json()["models"]
    return {"fits": fits, "hfits": hfits, "det": det, "hscore": hscore,
            "events": events, "health": health, "insights": insights,
            "models": models, "factory": f,
            "det_start": det_start, "det_end": det_end}


def _for_machine(rows, mid):
    return [x for x in rows if x["machine_id"] == mid]


@pytest.mark.parametrize("seed", SEEDS_ALL)
def test_normal_no_events_no_insights(client, seed):
    d = _prepare(client, "NORMAL", seed=seed)
    assert d["det"]["created"] == 0, d["events"]
    assert d["events"] == []
    bad = [h for h in d["health"] if h["state"] in ABNORMAL]
    assert bad == [], [(h["machine_id"], h["window_start"], h["state"]) for h in bad]
    assert d["insights"] == []
    assert all(x["status"] == "OK" for x in d["hfits"].values()), d["hfits"]
    assert any(m["model_id"] == "statistical-v1" and m["available"] for m in d["models"])


def test_energy_anomaly_gives_energy_only(client):
    # IDLE_WASTE (not HIGH_LOAD): powered holding / forced loaded at zero
    # output keeps every equipment signature at a NORMAL operating point,
    # so health stays NORMAL while energy flags. HIGH_LOAD raises current
    # draw, which a per-signal health reference legitimately notices
    # (see docs/ASSUMPTIONS.md A18).
    d = _prepare(client, "IDLE_WASTE")
    assert d["det"]["created"] >= 1, "IDLE_WASTE must raise energy events"
    furn_ins = _for_machine(d["insights"], "furnace-01")
    assert len(furn_ins) >= 1
    assert {i["category"] for i in furn_ins} == {"ENERGY_ONLY"}
    assert {i["category"] for i in d["insights"]} == {"ENERGY_ONLY"}
    assert _for_machine(d["insights"], "pump-01") == []


def test_health_only_anomaly(client):
    d = _prepare(client, "EQUIPMENT_DEGRADATION", energy_penalty=0.0)
    assert d["events"] == [], d["events"]
    furn_h = [h for h in _for_machine(d["health"], "furnace-01") if h["state"] in ABNORMAL]
    assert len(furn_h) >= 1, "degradation must flag health intervals"
    furn_ins = _for_machine(d["insights"], "furnace-01")
    assert len(furn_ins) >= 1
    assert {i["category"] for i in furn_ins} == {"HEALTH_ONLY"}
    assert {i["category"] for i in d["insights"]} == {"HEALTH_ONLY"}
    assert all(i["energy_evidence"] == {} for i in furn_ins)
    assert all(i["health_evidence"]["top_signals"] for i in furn_ins)


def test_combined_anomaly_coincident(client):
    d = _prepare(client, "EQUIPMENT_DEGRADATION", energy_penalty=0.35)
    furn_ev = _for_machine(d["events"], "furnace-01")
    assert len(furn_ev) >= 1, "combined fault must raise energy events"
    coinc = [i for i in _for_machine(d["insights"], "furnace-01")
             if i["category"] == "COINCIDENT"]
    assert len(coinc) >= 1, d["insights"]
    for i in coinc:
        assert i["energy_evidence"].get("rule_id")
        assert i["energy_evidence"].get("deviation_pct", 0) > 0
        assert i["health_evidence"]["top_signals"], "both evidences required"
        assert "coincides with machine-health anomaly" in i["text"]
        assert "correlation, not an established cause" in i["text"]
        assert "inspection recommended" in i["text"]
    assert {i["category"] for i in _for_machine(d["insights"], "furnace-01")} <= {
        "COINCIDENT", "HEALTH_ONLY"}
    assert _for_machine(d["insights"], "pump-01") == []


def test_health_unavailable_energy_still_detected(client):
    d = _prepare(client, "HIGH_LOAD", omit_health=True)
    assert d["det"]["created"] >= 1, "energy must still detect without health data"
    furn_ins = _for_machine(d["insights"], "furnace-01")
    assert len(furn_ins) >= 1
    assert {i["category"] for i in furn_ins} == {"ENERGY_ONLY_HEALTH_UNAVAILABLE"}
    r = client.get("/energy/summary", params={"start": d["det_start"], "end": d["det_end"]})
    assert r.status_code == 200 and r.json()["intervals"]
    assert client.get("/energy/anomalies").status_code == 200
    assert client.get("/dashboard/summary").status_code == 200
