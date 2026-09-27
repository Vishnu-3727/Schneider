"""Unit test: dashboard client returns an error object when the API is down."""

from apps.dashboard import client


def test_client_error_object_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(client, "API_BASE_URL", "http://127.0.0.1:9")
    res = client.get_summary(24)
    assert isinstance(res, dict) and "error" in res
    assert "127.0.0.1" in res["error"]
