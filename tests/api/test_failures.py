"""Failure tests: DB down, corrupt payload, API unreachable."""

from sqlalchemy.exc import OperationalError

from apps.backend import db as dbmod


def _db_down(monkeypatch):
    def boom(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
    monkeypatch.setattr(dbmod, "get_engine", boom)
    monkeypatch.setattr(dbmod, "db_is_up", lambda: False)


def test_db_down_health_and_post_503_no_traceback(client, monkeypatch):
    _db_down(monkeypatch)
    h = client.get("/health/components")
    assert h.status_code == 200
    assert h.json()["database"] == "down"
    assert client.get("/health").status_code == 200

    r = client.post("/telemetry", json={"records": [{
        "machine_id": "furnace-01", "ts": "2026-09-27T12:00:00+05:30",
        "power_kw": 10.0, "source": "SIMULATED"}]})
    assert r.status_code == 503
    assert "detail" in r.json()
    assert "Traceback" not in r.text


def test_corrupt_payload_422(client):
    r = client.post("/telemetry", content=b"{not valid json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_db_down_real_unreachable_postgres(client, monkeypatch):
    """Point the app at an unreachable Postgres; health/post must fail cleanly."""
    import time

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://joulemitra:joulemitra@127.0.0.1:1/joulemitra?connect_timeout=2",
    )
    dbmod.reset_engine()
    try:
        h = client.get("/health/components")
        assert h.status_code == 200
        assert h.json()["database"] == "down"

        t0 = time.monotonic()
        r = client.post("/telemetry", json={"records": [{
            "machine_id": "furnace-01", "ts": "2026-09-27T12:00:00+05:30",
            "power_kw": 10.0, "source": "SIMULATED"}]})
        dt = time.monotonic() - t0
        assert r.status_code == 503
        assert "detail" in r.json()
        assert "Traceback" not in r.text
        assert dt < 10, f"POST /telemetry took {dt:.1f}s with DB down"
    finally:
        dbmod.reset_engine()
