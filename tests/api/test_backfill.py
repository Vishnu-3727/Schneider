"""Backfill flag tests: stale skipped, all other rules intact, audit row written."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from apps.backend import db as dbmod

NOW = datetime.now(UTC).replace(microsecond=0)
OLD = NOW - timedelta(hours=24)


def rec(machine="furnace-01", **over):
    base = {
        "machine_id": machine,
        "ts": OLD.isoformat(),
        "voltage_v": 415.0,
        "current_a": 180.0,
        "power_kw": 110.0,
        "reactive_power_kvar": 60.0,
        "power_factor": 0.85,
        "energy_kwh": 100.0,
        "vibration_mm_s": 2.0,
        "temperature_c": 1500.0,
        "runtime_h": 5.0,
        "machine_state": "melting",
        "source": "SIMULATED",
    }
    base.update(over)
    return base


def _backfill_audits(entity):
    eng = dbmod.get_engine()
    with eng.connect() as conn:
        return conn.execute(
            text("SELECT action, entity, detail_json FROM audit_event "
                 "WHERE action = 'backfill' AND entity = :e"),
            {"e": entity},
        ).fetchall()


def test_backfill_skips_stale_but_still_flags_bad(client):
    r = client.post("/telemetry?backfill=true", json={"records": [
        rec(energy_kwh=100.0),
        rec(ts=(OLD + timedelta(seconds=60)).isoformat(), energy_kwh=101.0, power_kw=-5.0),
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suspect"] == 0
    assert body["accepted"] == 1
    assert body["bad"] == 1


def test_old_timestamp_suspect_without_backfill(client):
    r = client.post("/telemetry", json={"records": [rec()]})
    assert r.status_code == 200, r.text
    assert r.json()["suspect"] == 1


def test_backfill_writes_audit_event(client):
    n_before = len(_backfill_audits("telemetry"))
    r = client.post("/telemetry?backfill=true", json={"records": [rec()]})
    assert r.status_code == 200, r.text
    rows = _backfill_audits("telemetry")
    assert len(rows) == n_before + 1
    detail = rows[-1][2]
    assert detail["machine_ids"] == ["furnace-01"]
    assert detail["row_count"] == 1
    assert "start" in detail and "end" in detail


def test_production_backfill_writes_audit_event(client):
    n_before = len(_backfill_audits("production"))
    body = {"records": [{
        "machine_id": "furnace-01",
        "window_start": (NOW - timedelta(hours=2)).isoformat(),
        "window_end": (NOW - timedelta(hours=1)).isoformat(),
        "qty_total_kg": 500.0,
        "qty_good_kg": 490.0,
        "qty_rejected_kg": 10.0,
        "batch_id": "B1",
        "operating_time_h": 1.0,
        "source": "SIMULATED",
    }]}
    r = client.post("/production?backfill=true", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1
    rows = _backfill_audits("production")
    assert len(rows) == n_before + 1
    detail = rows[-1][2]
    assert detail["machine_ids"] == ["furnace-01"]
    assert detail["row_count"] == 1
    assert "start" in detail and "end" in detail
