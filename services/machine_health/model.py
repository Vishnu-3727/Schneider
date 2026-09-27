"""Phase 3A machine-health model interface (one small base class).

A `MachineHealthModel` learns a NORMAL reference per machine and scores
fixed time intervals. Interval dicts (the only row type in this module):

    {"window_start": datetime, "window_end": datetime,
     "machine_state": str | None,        # dominant state in the interval
     "vibration_mm_s": float | None,     # interval mean (None = missing)
     "temperature_c": float | None,
     "current_a": float | None,
     "n_rows": int, "complete": bool}

Per-interval result dict:

    {"health_score": float | None,        # 0-100 (None when not scoreable)
     "anomaly_score": float | None,       # max signal |robust z| (None ditto)
     "state": "NORMAL" | "WARNING" | "CRITICAL",
     "status": "OK" | "UNAVAILABLE" | "INSUFFICIENT_HISTORY"
               | "OUT_OF_DOMAIN" | "ERROR",
     "reason": str}

`explain(rows)` returns, per interval, a list of per-signal contributions:

    [{"signal": str, "value": float | None, "median": float | None,
      "z": float | None, "pct_change": float | None, "weight": float}]
"""

from __future__ import annotations

from abc import ABC, abstractmethod

HEALTH_SIGNALS = ("vibration_mm_s", "temperature_c", "current_a")

HEALTH_STATES = ("NORMAL", "WARNING", "CRITICAL")

HEALTH_STATUSES = (
    "OK",
    "UNAVAILABLE",
    "INSUFFICIENT_HISTORY",
    "OUT_OF_DOMAIN",
    "ERROR",
)


class MachineHealthModel(ABC):
    """Abstract health model. Implementations must be pure (no DB, no I/O)."""

    model_id: str = "base"

    @abstractmethod
    def metadata(self) -> dict:
        """Training domain, valid input signals, evidence source class,
        limitations. Shown by GET /machine-health/models."""

    @abstractmethod
    def fit(self, reference_rows: list[dict]) -> dict:
        """Learn the NORMAL reference. Returns JSON-serialisable params
        (stored in machine_health_reference.params)."""

    @abstractmethod
    def predict(self, rows: list[dict]) -> list[dict]:
        """Score intervals -> per-interval result dicts (same order)."""

    def score(self, rows: list[dict]) -> list[dict]:
        """Alias of predict (spec names both)."""
        return self.predict(rows)

    @abstractmethod
    def explain(self, rows: list[dict]) -> list[list[dict]]:
        """Per-signal contributions per interval (same order as rows)."""
