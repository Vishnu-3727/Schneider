"""API tests: ingestion happy path + invalid/missing/malformed/duplicate/edge cases."""

from datetime import UTC, datetime, timedelta

NOW = datetime.now(UTC).replace(microsecond=0)


def rec(machine="furnace-01", **over):
    base = {
        "machine_id": machine,
        "ts": (NOW - timedelta(minutes=5)).isoformat(),
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


def prod_rec(**over):
    base = {
        "machine_id": "furnace-01",
        "window_start": (NOW - timedelta(hours=2)).isoformat(),
        "window_end": (NOW - timedelta(hours=1)).isoformat(),
        "qty_total_kg": 500.0,
        "qty_good_kg": 490.0,
        "qty_rejected_kg": 10.0,
        "batch_id": "B1",
        "operating_time_h": 1.0,
        "source": "SIMULATED",
    }
    base.update(over)
    return base


def test_valid_batch(client):
    r = client.post("/telemetry", json={"records": [
        rec(),
        rec("compressor-01", machine_state="running", power_kw=20.0, current_a=32.0,
            energy_kwh=5.0, temperature_c=75.0),
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 2 and body["duplicate"] == 0 and body["bad"] == 0


def test_missing_field_422(client):
    bad = rec()
    del bad["ts"]
    r = client.post("/telemetry", json={"records": [bad]})
    assert r.status_code == 422


def test_malformed_type_422(client):
    r = client.post("/telemetry", json={"records": [rec(power_kw="lots")]})
    assert r.status_code == 422


def test_extra_field_422(client):
    r = client.post("/telemetry", json={"records": [rec(cost_inr=5.0)]})
    assert r.status_code == 422


def test_naive_ts_422(client):
    r = client.post("/telemetry", json={"records": [rec(ts="2026-09-27T12:00:00")]})
    assert r.status_code == 422


def test_unknown_machine_404(client):
    r = client.post("/telemetry", json={"records": [rec(machine="nope-99")]})
    assert r.status_code in (404, 422)
    assert "nope-99" in r.text


def test_duplicate_batch_idempotent(client):
    body = {"records": [rec()]}
    r1 = client.post("/telemetry", json=body)
    assert r1.status_code == 200
    r2 = client.post("/telemetry", json=body)
    assert r2.status_code == 200
    assert r2.json()["duplicate"] == 1 and r2.json()["accepted"] == 0
    got = client.get("/telemetry", params={"machine_id": "furnace-01"})
    assert len(got.json()) == 1


def test_zero_production_accepted(client):
    zero = prod_rec(qty_total_kg=0, qty_good_kg=0, qty_rejected_kg=0)
    r = client.post("/production", json={"records": [zero]})
    assert r.status_code == 200
    assert r.json()["accepted"] == 1


def test_negative_values_flagged_bad_but_stored(client):
    r = client.post("/telemetry", json={"records": [rec(power_kw=-10.0)]})
    assert r.status_code == 200
    assert r.json()["bad"] == 1
    got = client.get("/telemetry", params={"machine_id": "furnace-01"}).json()
    assert len(got) == 1 and got[0]["quality"] == "BAD"


def test_out_of_order_flagged_suspect(client):
    # energy omitted so the decreasing-counter rule cannot fire; only order matters.
    newer = rec(ts=(NOW - timedelta(minutes=2)).isoformat(), energy_kwh=None)
    older = rec(ts=(NOW - timedelta(minutes=5)).isoformat(), energy_kwh=None)
    r1 = client.post("/telemetry", json={"records": [newer]})
    assert r1.json()["accepted"] == 1
    r2 = client.post("/telemetry", json={"records": [older]})
    assert r2.status_code == 200
    assert r2.json()["suspect"] == 1


def test_sites_and_machines(client):
    assert client.get("/sites").status_code == 200
    machines = client.get("/machines").json()
    assert {m["id"] for m in machines} == {"furnace-01", "compressor-01", "pump-01"}
    assert client.get("/machines/furnace-01").status_code == 200
    assert client.get("/machines/nope").status_code == 404


def test_production_bad_totals_stored_flagged(client):
    bad = prod_rec(qty_total_kg=100, qty_good_kg=90, qty_rejected_kg=20)
    r = client.post("/production", json={"records": [bad]})
    assert r.status_code == 200 and r.json()["bad"] == 1
