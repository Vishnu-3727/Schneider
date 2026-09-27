"""API tests: recommendations generate/list/acknowledge (real test DB)."""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

TZ = ZoneInfo("Asia/Kolkata")
WS = datetime(2026, 9, 19, 0, 0, tzinfo=TZ).isoformat()
WE = datetime(2026, 9, 20, 0, 0, tzinfo=TZ).isoformat()


def _anomaly(client, mid="furnace-01", rule="L1_IDLE_WASTE", sev="WARNING",
             dev=42.0, status="OPEN", dd=None):
    from apps.backend import db as dbmod

    eng = dbmod.get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO anomaly_event (machine_id, window_start, window_end, metric, "
                "rule_id, level, score, severity, expected_kwh, actual_kwh, deviation_kwh, "
                "deviation_pct, evidence, status, source, dedup_key) VALUES "
                "(:m, CAST(:ws AS timestamptz), CAST(:we AS timestamptz), 'idle_energy', "
                ":rule, 'L1', 1.0, :sev, 100.0, 142.0, 42.0, :dev, 'idle waste', "
                ":st, 'DERIVED', :dd)"
            ),
            {"m": mid, "ws": WS, "we": WE, "rule": rule, "sev": sev,
             "dev": dev, "st": status, "dd": dd or f"api-{rule}-{mid}-{dev}-{uuid.uuid4().hex[:6]}"},
        )


def _health(client, mid="furnace-01", state="WARNING"):
    from apps.backend import db as dbmod

    eng = dbmod.get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO machine_health (machine_id, window_start, window_end, model_id, "
                "health_score, anomaly_score, state, status, reason, contributions) VALUES "
                "(:m, CAST(:ws AS timestamptz), CAST(:we AS timestamptz), 'statistical-v1', "
                "40.0, 8.0, :st, 'OK', 'test', CAST(:c AS jsonb))"
            ),
            {"m": mid, "ws": WS, "we": WE, "st": state,
             "c": json.dumps([{"signal": "vibration_mm_s", "z": 8.0}])},
        )


def _optrun(client, mid="furnace-01", status="INFEASIBLE", rid="run-api-1"):
    from apps.backend import db as dbmod

    eng = dbmod.get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO optimization_run (machine_id, horizon_start, horizon_end, "
                "inputs_hash, constraints, status, current_schedule, recommended_schedule, "
                "metrics, explanation, source) VALUES (:m, CAST(:ws AS timestamptz), "
                "CAST(:we AS timestamptz), 'h', CAST(:c AS jsonb), :st, NULL, NULL, "
                "CAST(:met AS jsonb), :ex, 'PROJECTED')"
            ),
            {"m": mid, "ws": WS, "we": WE,
             "c": json.dumps({"constraints": {}}), "st": status,
             "met": json.dumps({}),
             "ex": "NO FEASIBLE PLAN: operating-hours: required heats x minimum "
                   "heat duration (6 x 4 slots = 24) > available operating slots (8)"},
        )


def _gen(client):
    r = client.post("/recommendations/generate", json={"start": WS, "end": WE})
    assert r.status_code == 200, r.text[:500]
    return r.json()


def test_generate_idempotent_and_lists(client):
    _anomaly(client)
    first = _gen(client)
    assert first["created"] >= 1
    n = len(first["recommendations"])
    assert n >= 1
    second = _gen(client)
    assert second["created"] == 0
    assert second["already_existing"] == first["created"] + first["already_existing"]
    g = client.get("/recommendations")
    assert g.status_code == 200
    assert len(g.json()["recommendations"]) == n
    rec = first["recommendations"][0]
    for key in ("title", "machine_id", "severity", "reason", "evidence",
                "constraints_considered", "proposed_action", "confidence",
                "assumptions", "source_module", "source_class", "status",
                "verification_status", "created_at"):
        assert key in rec, key
    assert rec["verification_status"] == "NOT_VERIFIED"
    assert rec["created_at"]


def test_acknowledge_accept_stays_not_verified_and_audit(client):
    _anomaly(client)
    rec = _gen(client)["recommendations"][0]
    r = client.post(f"/recommendations/{rec['id']}/acknowledge",
                    json={"decision": "ACCEPTED", "note": "reviewed"})
    assert r.status_code == 200, r.text[:500]
    assert r.json()["status"] == "ACCEPTED"
    assert r.json()["verification_status"] == "NOT_VERIFIED"
    # Second decision -> 409.
    r2 = client.post(f"/recommendations/{rec['id']}/acknowledge",
                     json={"decision": "REJECTED", "note": "x"})
    assert r2.status_code == 409
    # Audit row written.
    from apps.backend import db as dbmod

    with dbmod.get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT action, entity FROM audit_event "
                 "WHERE entity_id = :e"),
            {"e": rec["id"]}).fetchall()
    assert rows and rows[0][0] == "recommendation.acknowledge"


def test_acknowledge_404_unknown_id(client):
    r = client.post(f"/recommendations/{uuid.uuid4()}/acknowledge",
                    json={"decision": "ACCEPTED", "note": ""})
    assert r.status_code == 404
    r = client.post("/recommendations/not-a-uuid/acknowledge",
                    json={"decision": "ACCEPTED", "note": ""})
    assert r.status_code == 404


def test_health_unavailable_still_generates(client):
    _anomaly(client, rule="L1_DEVIATION", dev=55.0)
    body = _gen(client)
    assert len(body["recommendations"]) >= 1  # from the remaining sources


def test_infeasible_optimizer_surfaced(client):
    _anomaly(client)
    _optrun(client)
    body = _gen(client)
    rules = {r["rule_id"] for r in body["recommendations"]}
    assert "R-NOPLAN" in rules, rules
    nop = [r for r in body["recommendations"] if r["rule_id"] == "R-NOPLAN"][0]
    assert "NO FEASIBLE PLAN" in nop["reason"]
    assert "R-IDLE" in rules  # remaining sources still produce rows


def test_coincident_health_inspect_and_conflict_path(client):
    _anomaly(client, rule="L1_DEVIATION", dev=60.0)
    _health(client, state="CRITICAL")
    body = _gen(client)
    rules = {r["rule_id"] for r in body["recommendations"]}
    assert "R-INSPECT" in rules, rules
    insp = [r for r in body["recommendations"] if r["rule_id"] == "R-INSPECT"][0]
    assert insp["expected_effect"] is None
    assert "correlation, not an established cause" in insp["reason"]
