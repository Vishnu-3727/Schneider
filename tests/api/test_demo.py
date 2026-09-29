"""Demo fault injection: absent unless DEMO_MODE; with it, a fault is detected."""

from fastapi.testclient import TestClient

from apps.backend import db as dbmod
from apps.backend.config import get_settings
from apps.backend.main import create_app
from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory


def test_inject_not_mounted_without_demo_mode(client):
    assert client.post("/demo/inject", json={"fault": "air_leak"}).status_code == 404


def test_air_leak_is_detected(client, monkeypatch):
    # NORMAL history up to now, then a baseline, then inject the fault.
    fac = SimulatedFactory(DEFAULT_MACHINES, hours=24 * 3, step_s=300, seed=3)
    tel, prod = fac.run()
    for path, recs in (("/telemetry?backfill=true", tel), ("/production?backfill=true", prod)):
        for i in range(0, len(recs), 1000):
            assert client.post(path, json={"records": recs[i:i + 1000]}).status_code == 200
    first, last = tel[0]["ts"], tel[-1]["ts"]
    assert client.post("/energy/baseline/fit", json={"start": first, "end": last}).status_code == 200

    monkeypatch.setenv("DEMO_MODE", "true")
    dbmod.reset_engine()
    try:
        assert get_settings().DEMO_MODE
        with TestClient(create_app()) as demo:
            r = demo.post("/demo/inject", json={"fault": "air_leak", "hours": 4})
            assert r.status_code == 200, r.text
            out = r.json()
    finally:
        monkeypatch.delenv("DEMO_MODE")
        dbmod.reset_engine()
    assert out["posted"]["compressor-01"]["telemetry"] > 0
    assert any(e["machine_id"] == "compressor-01" for e in out["events"])
