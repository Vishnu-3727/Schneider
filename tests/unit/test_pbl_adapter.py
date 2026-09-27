"""Unit tests: PBLRulAdapter availability, domain guard, metadata.

The adapter never imports onnxruntime at module import (optional [pbl]
extra) and never emits a health score or RUL for factory machines.
"""

import pytest

from services.machine_health import (
    FACTORY_MODEL_ID,
    REGISTRY,
    PBLRulAdapter,
    StatisticalHealthModel,
    make_model,
)
from services.machine_health.pbl_adapter import (
    PBL_CMAPSS_DOMAIN_ID,
    PBL_IN_DOMAIN_SENSOR_IDS,
    PBL_RF_BASELINE_RMSE,
    PBL_TEST_RMSE,
)


def _iv(machine_type="furnace"):
    from datetime import UTC, datetime
    now = datetime(2026, 9, 20, tzinfo=UTC)
    return {"machine_id": "furnace-01", "machine_type": machine_type,
            "window_start": now, "window_end": now,
            "machine_state": "melting", "vibration_mm_s": 8.0,
            "temperature_c": 1600.0, "current_a": 200.0,
            "n_rows": 12, "complete": True}


def test_registry_lists_both_models_and_factory_model_is_statistical():
    assert set(REGISTRY) == {"statistical-v1", "pbl-rul"}
    assert FACTORY_MODEL_ID == StatisticalHealthModel.model_id == "statistical-v1"
    assert isinstance(make_model("pbl-rul"), PBLRulAdapter)


def test_empty_path_is_unavailable_with_reason():
    a = PBLRulAdapter(onnx_path="")
    avail = a.availability()
    assert avail["status"] == "UNAVAILABLE"
    assert "PBL_ONNX_PATH" in avail["reason"]


def test_missing_file_is_unavailable_with_reason():
    a = PBLRulAdapter(onnx_path="/nonexistent/dir/unify_rul.onnx")
    avail = a.availability()
    assert avail["status"] == "UNAVAILABLE"
    assert "not found" in avail["reason"]


def test_factory_machine_is_out_of_domain_and_never_scored():
    a = PBLRulAdapter(onnx_path="")  # artifact state must not matter
    for mtype in ("furnace", "compressor", "pump"):
        res = a.predict([_iv(machine_type=mtype)])[0]
        assert res["status"] == "OUT_OF_DOMAIN", mtype
        assert res["health_score"] is None, mtype
        assert res["anomaly_score"] is None, mtype
        assert "turbofan sensor channels" in res["reason"], mtype
        assert mtype in res["reason"], mtype
        assert "retraining on plant data required" in res["reason"], mtype
    assert a.explain([_iv()]) == [[]]
    # Degraded-looking factory signals still never score, even with a path set.
    b = PBLRulAdapter(onnx_path="/nonexistent/dir/unify_rul.onnx")
    res = b.predict([_iv()])[0]
    assert res["status"] == "OUT_OF_DOMAIN"
    assert res["health_score"] is None


def test_metadata_training_domain_and_rmse_limitation():
    a = PBLRulAdapter(onnx_path="")
    meta = a.metadata()
    assert meta["model_id"] == "pbl-rul"
    assert "C-MAPSS" in meta["training_domain"] and "turbofan" in meta["training_domain"]
    assert meta["evidence_source_class"] == "EXTERNAL_REFERENCE"
    assert meta["status_for_factory_machines"] == "OUT_OF_DOMAIN"
    text = " ".join(meta["limitations"])
    assert str(PBL_TEST_RMSE) in text and str(PBL_RF_BASELINE_RMSE) in text
    assert "not better than the RF baseline" in text
    assert "not a production-grade predictor" in text
    assert "EXTERNAL_REFERENCE" in text or meta["evidence_source_class"] == "EXTERNAL_REFERENCE"
    # Verified file values (results/metrics.json vs results/baseline_rf.json).
    assert PBL_TEST_RMSE == 14.51 and PBL_RF_BASELINE_RMSE == 14.41


def test_fit_never_enables_scoring():
    a = PBLRulAdapter(onnx_path="")
    params = a.fit([_iv()])
    assert params.get("n_intervals", 0) == 0
    assert a.predict([_iv()])[0]["status"] == "OUT_OF_DOMAIN"


def test_score_window_unavailable_raises_clear_error():
    a = PBLRulAdapter(onnx_path="")
    with pytest.raises(RuntimeError, match="UNAVAILABLE"):
        a.score_window([[0.0] * 3] * 30, sensor_ids=[2, 3, 4])


def test_score_window_rejects_malformed_input():
    a = PBLRulAdapter(onnx_path="/nonexistent/dir/unify_rul.onnx")
    with pytest.raises(ValueError, match=r"\(L, S\)"):
        a.score_window([0.0] * 30)  # 1-D, not a window
    with pytest.raises(ValueError, match="finite"):
        a.score_window([[float("nan")] * 3] * 30)
    with pytest.raises(ValueError, match="sensor_ids"):
        a.score_window([[0.0] * 3] * 30, sensor_ids=[2, 3])


def test_in_domain_sensor_ids_and_domain_documented():
    assert len(PBL_IN_DOMAIN_SENSOR_IDS) == 15
    assert PBL_CMAPSS_DOMAIN_ID == 0
