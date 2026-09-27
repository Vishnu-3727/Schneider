"""Phase 5A acceptance: approve -> apply -> measure -> verify through the API.

Every outcome here comes from the simulator's physics (chronic powered
holding during idle gaps, a REDUCE_IDLE / REPAIR intervention with
effectiveness, compliance and rebound) and the counterfactual maths — no
outcome label is injected.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from apps.backend import db as dbmod
from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, tzinfo=TZ)
BASE_H, POST_H = 24 * 7, 24 * 3
APPLIED = END - timedelta(hours=POST_H)
FURNACE = [MachineSpec("furnace-01", "furnace", 150.0)]


def _ingest(client, seed=1, **kw):
    fac = SimulatedFactory(FURNACE, hours=BASE_H + POST_H, step_s=300, seed=seed, end=END,
                           chronic_idle_hold_frac=0.6, **kw)
    tel, prod = fac.run()
    for path, recs in (("/telemetry?backfill=true", tel), ("/production?backfill=true", prod)):
        for i in range(0, len(recs), 1000):
            assert client.post(path, json={"records": recs[i:i + 1000]}).status_code == 200


def _recommendation(status="PENDING_REVIEW") -> str:
    with dbmod.get_engine().begin() as c:
        return str(c.execute(text(
            "INSERT INTO recommendation (machine_id, rule_id, title, severity, confidence, "
            "status, dedup_key) VALUES ('furnace-01', 'R-IDLE', "
            "'Avoid unnecessary idle/holding operation on furnace-01', 'WARNING', 'MEDIUM', "
            ":st, :dd) RETURNING id"), {"st": status, "dd": f"test-{uuid.uuid4()}"}).scalar())


def _apply(client, rec_id, iv_type="REDUCE_IDLE", key=None):
    return client.post("/interventions", json={
        "recommendation_id": rec_id, "type": iv_type, "applied_at": APPLIED.isoformat(),
        "idempotency_key": key or f"k-{rec_id}", "parameters": {"note": "test"}})


def _full(client, seed=1, iv_type="REDUCE_IDLE", **kw):
    _ingest(client, seed=seed, **kw)
    rec = _recommendation()
    assert client.post(f"/recommendations/{rec}/acknowledge",
                       json={"decision": "APPROVED"}).json()["status"] == "APPROVED"
    r = _apply(client, rec, iv_type)
    assert r.status_code == 200, r.text
    iv = r.json()["intervention"]
    assert iv["status"] == "APPLIED"
    v = client.post(f"/interventions/{iv['id']}/verify",
                    json={"start": APPLIED.isoformat(), "end": END.isoformat()})
    assert v.status_code == 200, v.text
    return rec, iv, v.json()["verification"]


def _reduce_idle(**kw):
    return {"type": "REDUCE_IDLE", "start_h": BASE_H, **kw}


@pytest.mark.parametrize("seed", [1, 2])
def test_success_reduce_idle_verified(client, seed):
    rec, _, v = _full(client, seed=seed,
                      intervention=_reduce_idle(effectiveness=1.0, rebound=0.15))
    assert v["result_class"] == "SUCCESS" and v["outcome"] == "VERIFIED"
    assert v["saving_kwh"] > v["uncertainty_kwh"] > 0
    assert v["verified_saving_kwh"] == v["saving_kwh"]
    cost, co2 = v["cost_impact"], v["co2_impact"]
    assert cost["status"] == "OK" and cost["value_inr"] > 0
    assert "ILLUSTRATIVE" in cost["tariff_label"] and cost["source_class"] == "ASSUMPTION"
    assert co2["status"] == "LATEST_AVAILABLE"  # 2026 energy, latest CEA factor is FY2024-25
    assert co2["value_kg"] == pytest.approx(v["saving_kwh"] * co2["factor"]["value"], abs=1e-3)
    assert co2["factor"]["version"] == "v21.0" and co2["factor"]["source_class"] == "EXTERNAL_REFERENCE"
    assert co2["provisional"] is True and "not CO2e" in co2["unit"]
    recs = client.get("/recommendations").json()["recommendations"]
    row = next(r for r in recs if r["id"] == rec)
    assert row["status"] == "VERIFIED" and row["verification_status"] == "VERIFIED"


def test_success_repair_verified(client):
    _, _, v = _full(client, iv_type="REPAIR", chronic_energy_penalty=0.15,
                    intervention={"type": "REPAIR", "start_h": BASE_H, "effectiveness": 1.0})
    assert v["result_class"] == "SUCCESS" and v["saving_kwh"] > v["uncertainty_kwh"]


@pytest.mark.parametrize("seed", [1, 2])
def test_no_effect_not_verified(client, seed):
    _, _, v = _full(client, seed=seed, intervention=_reduce_idle(effectiveness=0.0))
    assert v["result_class"] == "NO_EFFECT" and v["outcome"] == "NOT_VERIFIED"
    assert abs(v["saving_kwh"]) <= v["uncertainty_kwh"]
    assert v["verified_saving_kwh"] is None
    assert "no statistically meaningful change" in v["explanation"].lower()


def test_worse_outcome_is_reported_not_hidden(client):
    _, _, v = _full(client, intervention=_reduce_idle(effectiveness=1.0, rebound=1.0))
    assert v["result_class"] == "WORSE" and v["outcome"] == "NOT_VERIFIED"
    assert v["saving_kwh"] < -v["uncertainty_kwh"]
    assert "INCREASED" in v["explanation"] and v["verified_saving_kwh"] is None
    assert v["cost_impact"]["status"] == v["co2_impact"]["status"] == "NOT_APPLICABLE"
    assert v["cost_impact"]["value_inr"] is None and v["co2_impact"]["value_kg"] is None


def test_emission_factors_listed_with_provenance(client):
    fs = client.get("/emission-factors").json()["emission_factors"]
    assert [f["version"] for f in fs] == ["v20.0", "v21.0"]
    for f in fs:
        assert f["unit"] == "kgCO2/kWh" and f["gas_basis"] == "CO2 only"
        assert f["source_class"] == "EXTERNAL_REFERENCE" and f["effective_from"] and f["note"]


def test_not_comparable_production_reports_no_saving(client):
    _, _, v = _full(client, intervention=_reduce_idle(effectiveness=1.0), post_idle_scale=0.1)
    assert v["result_class"] == "NOT_COMPARABLE" and v["outcome"] == "NOT_COMPARABLE"
    assert v["comparable"] is False and v["comparability_reasons"]
    assert v["saving_kwh"] is None and v["counterfactual_kwh"] is None


def test_missing_measurements_insufficient_data(client):
    _, _, v = _full(client, intervention=_reduce_idle(effectiveness=1.0),
                    gap_h=(BASE_H + 20, BASE_H + 40))
    assert v["result_class"] == "INSUFFICIENT_DATA" and v["outcome"] == "INSUFFICIENT_DATA"
    assert v["saving_kwh"] is None


def test_idempotent_apply_and_verify(client):
    rec, iv, v1 = _full(client, intervention=_reduce_idle(effectiveness=1.0, rebound=0.15))
    again = _apply(client, rec)  # same idempotency key
    assert again.status_code == 200 and again.json()["idempotent_replay"] is True
    assert again.json()["intervention"]["id"] == iv["id"]
    v2 = client.post(f"/interventions/{iv['id']}/verify",
                     json={"start": APPLIED.isoformat(), "end": END.isoformat()}).json()
    assert v2["idempotent_replay"] is True and v2["verification"] == v1
    assert len(client.get("/interventions").json()["interventions"]) == 1
    assert len(client.get("/verification").json()["verification"]) == 1
    with dbmod.get_engine().begin() as c:
        moves = c.execute(text("SELECT detail_json->>'to' FROM audit_event WHERE "
                               "action = 'lifecycle.transition' ORDER BY at")).scalars().all()
    assert moves == ["APPLIED", "MEASURED", "VERIFIED"]


def test_illegal_transitions_409(client):
    pending = _recommendation()
    r = _apply(client, pending)
    assert r.status_code == 409 and "APPROVED" in r.json()["detail"]
    rejected = _recommendation()
    client.post(f"/recommendations/{rejected}/acknowledge", json={"decision": "REJECTED"})
    assert _apply(client, rejected).status_code == 409
    approved = _recommendation()
    client.post(f"/recommendations/{approved}/acknowledge", json={"decision": "ACCEPTED"})
    assert _apply(client, approved).status_code == 200  # ACCEPTED is an alias of APPROVED
    assert _apply(client, approved, key="another-key").status_code == 409  # already APPLIED
    assert client.post(f"/recommendations/{approved}/acknowledge",
                       json={"decision": "REJECTED"}).status_code == 409
    bogus = client.post(f"/interventions/{uuid.uuid4()}/verify",
                        json={"start": APPLIED.isoformat(), "end": END.isoformat()})
    assert bogus.status_code == 404
