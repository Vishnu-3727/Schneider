"""E2E smoke: simulator 24h NORMAL -> POST to API -> DB -> GET /dashboard/summary."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory

TZ = ZoneInfo("Asia/Kolkata")


def _post_all(client, path, packets, chunk=500):
    totals = {"accepted": 0, "suspect": 0, "bad": 0, "duplicate": 0}
    for i in range(0, len(packets), chunk):
        r = client.post(f"{path}?backfill=true", json={"records": packets[i:i + chunk]})
        assert r.status_code == 200, r.text[:500]
        for k, v in r.json().items():
            totals[k] += v
    return totals


def test_e2e_smoke(client):
    end = datetime.now(TZ).replace(microsecond=0)
    factory = SimulatedFactory(DEFAULT_MACHINES, hours=24, step_s=300, seed=1, end=end)
    telemetry, production = factory.run()

    t_tot = _post_all(client, "/telemetry", telemetry)
    p_tot = _post_all(client, "/production", production)

    # NORMAL backfill data is clean: nothing SUSPECT, nothing BAD.
    assert t_tot["suspect"] == 0
    assert t_tot["bad"] == 0
    assert t_tot["accepted"] == len(telemetry)
    assert t_tot["duplicate"] == 0
    got = client.get("/telemetry", params={"limit": 10000}).json()
    assert len(got) == len(telemetry)
    assert p_tot["accepted"] == len(production)

    summary = client.get("/dashboard/summary", params={"hours": 25}).json()
    by_id = {m["machine_id"]: m for m in summary["machines"]}
    assert set(by_id) == {"furnace-01", "compressor-01", "pump-01"}

    for spec in DEFAULT_MACHINES:
        rows = [p for p in telemetry if p["machine_id"] == spec.machine_id]
        expected_delta = rows[-1]["energy_kwh"] - rows[0]["energy_kwh"]
        actual = by_id[spec.machine_id]["energy_kwh"]
        assert actual == pytest.approx(expected_delta, rel=1e-3), spec.machine_id
        assert by_id[spec.machine_id]["source"] == "SIMULATED"
