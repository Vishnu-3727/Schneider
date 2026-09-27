"""PBL RUL adapter (JouleMitra clean-room code, written here).

Wraps an EXTERNAL remaining-useful-life ONNX model of the NASA C-MAPSS
turbofan run-to-failure family behind the JouleMitra `MachineHealthModel`
interface. Nothing is copied from the external project: only the
input/output contract below was learned from its edge-inference module
(input names, shapes, dtypes, output names) so this adapter can drive a
locally provided artifact file.

ONNX contract (learned, EXTERNAL_REFERENCE):
    inputs:  x          (batch, sensors, 30) float32  -- normalised window
             mask       (batch, sensors)     bool     -- all True (no padding)
             sensor_ids (batch, sensors)     int64    -- sensor-vocabulary ids
             domain_id  (batch,)             int64    -- dataset domain id
    outputs: rul        (batch, 1)           float32
             attn       (batch, 4, 1, sensors) float32

Domain guard (non-negotiable): the external model was trained on turbofan
sensor channels. JouleMitra factory machines expose vibration_mm_s /
temperature_c / current_a on furnace/compressor/pump types. Those signals
are OUT_OF_DOMAIN for this model, so `predict()` NEVER emits a health
score or an RUL for them -- every interval scores OUT_OF_DOMAIN with a
reason naming the machine type. `score_window()` exists for demonstration
and tests only: it drives a caller-supplied in-domain (turbofan-channel)
window through the ONNX session and checks shape/finiteness.

Availability: onnxruntime is an OPTIONAL `[pbl]` extra, and the artifact
path is empty by default. Empty path, missing file, or missing
onnxruntime -> status UNAVAILABLE with a clear reason. Never a crash:
importing this module never imports onnxruntime.
"""

from __future__ import annotations

import json
import os

from services.machine_health.model import MachineHealthModel

#: Informative C-MAPSS turbofan channel subset (sensor-vocabulary ids) for
#: demonstration/test windows. Channel knowledge learned from the external
#: project's contract (EXTERNAL_REFERENCE); the adapter itself takes caller
#: ids and never depends on these.
PBL_IN_DOMAIN_SENSOR_IDS = (2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 17, 20, 21)

#: Dataset domain id for the C-MAPSS build (learned contract value).
PBL_CMAPSS_DOMAIN_ID = 0

#: Verified benchmark numbers (EXTERNAL_REFERENCE, read from the external
#: project's results/metrics.json and results/baseline_rf.json official-test
#: entries: RMSE 14.5109... and 14.4051... respectively).
PBL_TEST_RMSE = 14.51
PBL_RF_BASELINE_RMSE = 14.41


def _import_ort():
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]
    except ImportError:
        return None
    return ort


class PBLRulAdapter(MachineHealthModel):
    """External-RUL adapter. Pure w.r.t. JouleMitra data (no DB); the only
    I/O is loading the caller-provided local ONNX file, lazily."""

    model_id = "pbl-rul"

    def __init__(
        self,
        onnx_path: str | None = None,
        sensor_vocab_path: str | None = None,
        **_ignored,
    ) -> None:
        self.onnx_path = onnx_path if onnx_path is not None else os.environ.get(
            "PBL_ONNX_PATH", "")
        self.sensor_vocab_path = (
            sensor_vocab_path if sensor_vocab_path is not None
            else os.environ.get("PBL_SENSOR_VOCAB_PATH", ""))
        self._session = None
        self._window_len: int | None = None
        self._load_error: str | None = None

    # -- availability --------------------------------------------------
    def availability(self) -> dict:
        """UNAVAILABLE with a clear reason when the path is empty, the file
        is missing, or onnxruntime is not installed. Never raises."""
        if not (self.onnx_path or "").strip():
            return {"status": "UNAVAILABLE",
                    "reason": "PBL_ONNX_PATH is empty (no local PBL artifact "
                              "configured; set it to your own artifact file)"}
        if not os.path.exists(self.onnx_path):
            return {"status": "UNAVAILABLE",
                    "reason": f"PBL artifact not found: {self.onnx_path}"}
        if _import_ort() is None:
            return {"status": "UNAVAILABLE",
                    "reason": "onnxruntime is not installed "
                              "(pip install -e .[pbl] for the PBL extra)"}
        err = self._ensure_session()
        if err is not None:
            return {"status": "UNAVAILABLE", "reason": err}
        return {"status": "AVAILABLE",
                "reason": f"ONNX session ready ({self.onnx_path})"}

    def _ensure_session(self) -> str | None:
        """Load the ONNX session once; return None on success or the reason."""
        if self._session is not None:
            return None
        if self._load_error is not None:
            return self._load_error
        ort = _import_ort()
        if ort is None:  # pragma: no cover - guarded by availability()
            self._load_error = "onnxruntime is not installed"
            return self._load_error
        try:
            self._session = ort.InferenceSession(
                self.onnx_path, providers=["CPUExecutionProvider"])
            shape = self._session.get_inputs()[0].shape
            self._window_len = int(shape[2])
        except Exception as e:  # corrupt/foreign file -> UNAVAILABLE, not a crash
            self._load_error = (
                f"could not load ONNX artifact {self.onnx_path}: "
                f"{type(e).__name__}: {e}")
            self._session = None
            return self._load_error
        return None

    # -- metadata ------------------------------------------------------
    def metadata(self) -> dict:
        avail = self.availability()
        return {
            "model_id": self.model_id,
            "family": "external ONNX remaining-useful-life (turbofan)",
            "training_domain": (
                "NASA C-MAPSS turbofan run-to-failure "
                "(EXTERNAL_REFERENCE)"
            ),
            "valid_input_signals": (
                "C-MAPSS turbofan sensor channels only "
                "(NOT vibration_mm_s / temperature_c / current_a)"
            ),
            "evidence_source_class": "EXTERNAL_REFERENCE",
            "artifact_status": avail,
            "status_for_factory_machines": "OUT_OF_DOMAIN",
            "limitations": [
                ("OUT_OF_DOMAIN for all JouleMitra factory machines "
                 "(furnace/compressor/pump): trained on turbofan sensor "
                 "channels; not validated for factory signals; retraining "
                 "on plant data required."),
                (f"Test RMSE {PBL_TEST_RMSE} (EXTERNAL_REFERENCE) vs "
                 f"random-forest baseline RMSE {PBL_RF_BASELINE_RMSE} "
                 "(EXTERNAL_REFERENCE): not better than the RF baseline "
                 "on this benchmark; not a production-grade predictor."),
                ("score_window() is demonstration/tests only: the caller "
                 "must supply an in-domain window normalised with the "
                 "artifact's own training statistics."),
            ],
        }

    # -- MachineHealthModel interface (domain-guarded) ------------------
    def fit(self, reference_rows: list[dict]) -> dict:
        """Fitting does not apply: the weights live in the external file.
        Returns n_intervals 0 so the API reports INSUFFICIENT_HISTORY."""
        return {"model_id": self.model_id, "fitted": False, "n_intervals": 0,
                "reason": "pbl-rul weights live in the external ONNX artifact; "
                          "reference fitting is not applicable"}

    def _out_of_domain(self, row: dict) -> dict:
        mtype = row.get("machine_type") or "factory-machine"
        return {
            "health_score": None, "anomaly_score": None,
            "state": "NORMAL", "status": "OUT_OF_DOMAIN",
            "reason": (
                f"pbl-rul trained on turbofan sensor channels; not "
                f"validated for {mtype}; retraining on plant data required"
            ),
        }

    def predict(self, rows: list[dict]) -> list[dict]:
        """Factory intervals are always OUT_OF_DOMAIN. NEVER emits a health
        score or an RUL for them, whether or not the artifact loads."""
        return [self._out_of_domain(r) for r in rows]

    def explain(self, rows: list[dict]) -> list[list[dict]]:
        return [[] for _ in rows]

    # -- in-domain demonstration / test entry point ---------------------
    def score_window(
        self,
        window,
        sensor_ids=None,
        domain_id: int = PBL_CMAPSS_DOMAIN_ID,
    ) -> dict:
        """Run one in-domain (turbofan-channel) window through the ONNX
        model. `window`: (L, S) array-like of normalised floats, oldest
        first; `sensor_ids`: S vocabulary ids; `domain_id`: dataset domain.
        Returns {rul, attention, window_shape, evidence_source_class}.
        Raises RuntimeError with a clear reason when UNAVAILABLE, ValueError
        on malformed input (structural checks run before the availability
        gate, so bad input is always rejected). Demonstration and tests
        ONLY -- never call this with factory vibration/temperature/current
        signals."""
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover - numpy is a core dep
            raise RuntimeError("numpy is required for score_window") from e
        arr = np.asarray(window, dtype=np.float64)
        if arr.ndim != 2:
            raise ValueError(f"window must be (L, S), got ndim {arr.ndim}")
        n_len, n_sensors = arr.shape
        if n_sensors < 1:
            raise ValueError("window must have >= 1 sensor channel")
        if not bool(np.all(np.isfinite(arr))):
            raise ValueError("window must be finite (no NaN/inf)")
        sids = (PBL_IN_DOMAIN_SENSOR_IDS[:n_sensors] if sensor_ids is None
                else tuple(int(s) for s in sensor_ids))
        if len(sids) != n_sensors:
            raise ValueError(
                f"{len(sids)} sensor_ids for {n_sensors} window channels")
        avail = self.availability()
        if avail["status"] != "AVAILABLE" or self._session is None:
            raise RuntimeError(f"PBL model UNAVAILABLE: {avail['reason']}")
        if self._window_len is not None and n_len != self._window_len:
            raise ValueError(
                f"window length {n_len} != model window {self._window_len}")
        feeds = {
            "x": np.ascontiguousarray(arr.T[None].astype(np.float32)),
            "mask": np.ones((1, n_sensors), dtype=bool),
            "sensor_ids": np.array([list(sids)], dtype=np.int64),
            "domain_id": np.array([int(domain_id)], dtype=np.int64),
        }
        rul, attn = self._session.run(["rul", "attn"], feeds)
        rul_v = np.asarray(rul, dtype=np.float64)
        attn_v = np.asarray(attn, dtype=np.float64)
        if rul_v.shape != (1, 1) or attn_v.shape[0] != 1 \
                or attn_v.shape[-1] != n_sensors:
            raise RuntimeError(
                f"unexpected ONNX output shapes: rul {rul_v.shape}, "
                f"attn {attn_v.shape}")
        if not (bool(np.all(np.isfinite(rul_v)))
                and bool(np.all(np.isfinite(attn_v)))):
            raise RuntimeError("ONNX model returned non-finite output")
        return {
            "rul": float(rul_v[0, 0]),
            "attention": attn_v[0].mean(axis=(0, 1)).tolist(),
            "window_shape": [n_len, n_sensors],
            "n_sensors": n_sensors,
            "evidence_source_class": "EXTERNAL_REFERENCE",
        }

    def sensor_vocab(self) -> dict:
        """Local sensor-vocabulary file, when configured (supplemental; never
        required for availability). Returns {} when absent/unreadable."""
        path = (self.sensor_vocab_path or "").strip()
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not str(k).startswith("_")}
        except (OSError, ValueError):
            return {}
