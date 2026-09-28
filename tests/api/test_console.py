"""Console serving tests: /console/ page + vendored plotly JS (same origin, no CDN)."""


def test_console_index_serves(client):
    r = client.get("/console/")
    assert r.status_code == 200
    assert "JouleMitra" in r.text


def test_console_vendor_plotly_serves(client):
    r = client.get("/console-vendor/plotly.min.js")
    assert r.status_code == 200
    assert len(r.content) > 0
