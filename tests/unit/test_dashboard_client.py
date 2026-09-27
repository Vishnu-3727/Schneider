"""Unit tests: dashboard client (API-only; never touches the DB)."""

from apps.dashboard import client


def test_client_error_object_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(client, "API_BASE_URL", "http://127.0.0.1:9")
    res = client.get_summary(24)
    assert isinstance(res, dict) and "error" in res
    assert "127.0.0.1" in res["error"]


def test_health_models_insights_error_object_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(client, "API_BASE_URL", "http://127.0.0.1:9")
    for res in (client.get_health_models(),
                client.get_machine_health(machine_id="furnace-01"),
                client.get_insights("2026-09-20T00:00:00+05:30",
                                    "2026-09-21T00:00:00+05:30")):
        assert isinstance(res, dict) and "error" in res, res


def test_health_client_passes_query_params(monkeypatch):
    seen = {}

    def _fake_get(path, params=None, timeout=15.0):
        seen["path"] = path
        seen["params"] = params
        return {"ok": True}

    monkeypatch.setattr(client, "_get", _fake_get)
    assert client.get_health_models() == {"ok": True}
    assert seen["path"] == "/machine-health/models"
    assert client.get_machine_health(machine_id="m1", model_id="pbl-rul") == {"ok": True}
    assert seen["path"] == "/machine-health"
    assert seen["params"]["machine_id"] == "m1"
    assert seen["params"]["model_id"] == "pbl-rul"
    assert client.get_insights("s", "e") == {"ok": True}
    assert seen["path"] == "/insights"
    assert seen["params"] == {"start": "s", "end": "e"}


def test_phase4b_client_error_object_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(client, "API_BASE_URL", "http://127.0.0.1:9")
    for res in (client.get_optimization_schedule(machine_id="furnace-01"),
                client.get_recommendations(),
                client.generate_recommendations("s", "e")):
        assert isinstance(res, dict) and "error" in res, res


def test_phase4b_client_passes_query_params(monkeypatch):
    seen = {}

    def _fake_get(path, params=None, timeout=15.0):
        seen["path"] = path
        seen["params"] = params
        return {"ok": True}

    monkeypatch.setattr(client, "_get", _fake_get)
    assert client.get_optimization_schedule(machine_id="m1") == {"ok": True}
    assert seen["path"] == "/optimization/schedule"
    assert seen["params"] == {"machine_id": "m1"}
    assert client.get_recommendations(status="PENDING_REVIEW") == {"ok": True}
    assert seen["path"] == "/recommendations"
    assert seen["params"] == {"status": "PENDING_REVIEW"}
