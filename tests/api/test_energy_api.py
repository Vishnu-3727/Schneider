"""API tests: energy endpoints — invalid windows, unknown machines, ack flow."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.backend import db as dbmod

TZ = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)
END = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)


def test_fit_invalid_window_422(client):
    r = client.post("/energy/baseline/fit",
                    json={"start": END.isoformat(), "end": START.isoformat()})
    assert r.status_code == 422


def test_fit_unknown_machine_404(client):
    r = client.post("/energy/baseline/fit",
                    json={"machine_id": "nope-01", "start": START.isoformat(),
                          "end": END.isoformat()})
    assert r.status_code == 404


def test_fit_insufficient_history_status(client):
    r = client.post("/energy/baseline/fit",
                    json={"start": START.isoformat(), "end": END.isoformat()})
    assert r.status_code == 200
    by_id = {x["machine_id"]: x for x in r.json()["fits"]}
    assert set(by_id) == {"furnace-01", "compressor-01", "pump-01"}
    assert all(x["status"] == "INSUFFICIENT_BASELINE_HISTORY" for x in by_id.values())


def test_summary_unknown_machine_404(client):
    r = client.get("/energy/summary", params={"start": START.isoformat(),
                                              "end": END.isoformat(),
                                              "machine_id": "nope-01"})
    assert r.status_code == 404


def test_detect_unknown_machine_404(client):
    r = client.post("/energy/anomalies/detect",
                    json={"start": START.isoformat(), "end": END.isoformat(),
                          "machine_id": "nope-01"})
    assert r.status_code == 404


def test_acknowledge_missing_id_404(client):
    r = client.post(f"/energy/anomalies/{uuid.uuid4()}/acknowledge")
    assert r.status_code == 404


def _insert_open_event() -> str:
    eng = dbmod.get_engine()
    eid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO anomaly_event (id, machine_id, window_start, window_end, "
                "metric, rule_id, level, score, severity, evidence, status, source, "
                "dedup_key) VALUES (CAST(:i AS uuid), 'furnace-01', :ws, :we, 'deviation', "
                "'L1_DEVIATION', 'L1_rule', 20.0, 'WARNING', 'test', 'OPEN', 'DERIVED', :dd)"
            ),
            {"i": eid, "ws": START, "we": START + timedelta(hours=2), "dd": f"test-{eid}"},
        )
    return eid


def test_acknowledge_happy_path(client):
    eid = _insert_open_event()
    r = client.post(f"/energy/anomalies/{eid}/acknowledge")
    assert r.status_code == 200
    assert r.json()["status"] == "ACKNOWLEDGED"
    open_evs = client.get("/energy/anomalies", params={"status": "OPEN"}).json()["anomalies"]
    assert all(e["id"] != eid for e in open_evs)


def test_dashboard_summary_has_sec_and_alerts(client):
    r = client.get("/dashboard/summary", params={"hours": 25})
    assert r.status_code == 200
    for m in r.json()["machines"]:
        assert "sec_status" in m and "open_alerts" in m
