"""Phase 3B PBL adapter (API + optional ONNX integration).

- GET /machine-health/models lists statistical-v1 (active for factory
  machines) and pbl-rul (availability / out-of-domain status + metadata).
- Scoring factory machines with model_id=pbl-rul yields OUT_OF_DOMAIN rows
  and never a health score or RUL.
- Optional ONNX test: loads a local artifact whose path comes ONLY from the
  PBL_TEST_ONNX_PATH env var (never hard-coded) and checks output
  shape/finiteness on a synthetic in-domain window. Skips with an explicit
  reason when the file or onnxruntime is absent.
"""

import os

import pytest

PBL_TEST_ONNX_ENV = "PBL_TEST_ONNX_PATH"


def test_models_lists_statistical_and_pbl(client):
    models = client.get("/machine-health/models").json()["models"]
    by_id = {m["model_id"]: m for m in models}
    assert {"statistical-v1", "pbl-rul"} <= set(by_id), by_id.keys()

    stat = by_id["statistical-v1"]
    assert stat["available"] is True
    assert stat["active_for_factory_machines"] is True

    pbl = by_id["pbl-rul"]
    assert pbl["active_for_factory_machines"] is False
    assert pbl["factory_status"] in ("OUT_OF_DOMAIN", "UNAVAILABLE"), pbl
    if pbl["factory_status"] == "OUT_OF_DOMAIN":
        assert pbl["available"] is True
        assert "retraining on plant data required" in pbl["factory_reason"]
    else:
        assert pbl["available"] is False
        assert pbl["artifact_status"]["reason"], "UNAVAILABLE needs a reason"
    meta = pbl["metadata"]
    assert "turbofan" in meta["training_domain"]
    assert meta["evidence_source_class"] == "EXTERNAL_REFERENCE"
    assert any("not better than the RF baseline" in lim
               for lim in meta["limitations"]), meta["limitations"]


def test_pbl_scoring_of_factory_machine_is_out_of_domain(client):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    end = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    start = (end - timedelta(hours=2)).isoformat()
    r = client.post("/machine-health/score",
                    json={"start": start, "end": end.isoformat(),
                          "model_id": "pbl-rul"})
    assert r.status_code == 200, r.text[:500]
    rows = client.get("/machine-health",
                      params={"start": start, "end": end.isoformat(),
                              "model_id": "pbl-rul"}).json()["health"]
    assert rows, "OUT_OF_DOMAIN rows must be persisted"
    for h in rows:
        assert h["status"] == "OUT_OF_DOMAIN", h
        assert h["health_score"] is None and h["anomaly_score"] is None, h
        assert "turbofan sensor channels" in h["reason"], h
        assert "retraining on plant data required" in h["reason"], h


def test_pbl_onnx_optional_integration():
    """Load the local ONNX artifact (env-var path only) and score one
    synthetic in-domain window: output shape + finiteness."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        pytest.skip("onnxruntime not installed ([pbl] extra missing)")
    path = os.environ.get(PBL_TEST_ONNX_ENV, "").strip()
    if not path:
        pytest.skip(f"{PBL_TEST_ONNX_ENV} is not set (no local PBL artifact)")
    if not os.path.exists(path):
        pytest.skip(f"PBL artifact not found at {PBL_TEST_ONNX_ENV}={path}")

    import numpy as np

    from services.machine_health.pbl_adapter import (
        PBL_CMAPSS_DOMAIN_ID,
        PBL_IN_DOMAIN_SENSOR_IDS,
        PBLRulAdapter,
    )

    adapter = PBLRulAdapter(onnx_path=path)
    avail = adapter.availability()
    assert avail["status"] == "AVAILABLE", avail
    rng = np.random.default_rng(7)
    window = rng.normal(0, 1, size=(30, len(PBL_IN_DOMAIN_SENSOR_IDS)))
    out = adapter.score_window(window, domain_id=PBL_CMAPSS_DOMAIN_ID)
    assert out["evidence_source_class"] == "EXTERNAL_REFERENCE"
    assert out["window_shape"] == [30, len(PBL_IN_DOMAIN_SENSOR_IDS)]
    assert np.isfinite(out["rul"]), out
    assert len(out["attention"]) == len(PBL_IN_DOMAIN_SENSOR_IDS)
    assert all(np.isfinite(out["attention"])), out
