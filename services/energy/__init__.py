"""Phase 2 energy analytics package (pure functions; DB access lives in routers)."""

from services.energy.aggregate import Interval, build_intervals
from services.energy.anomaly import build_events, l1_flags, mad_zscores, merge_runs
from services.energy.baseline import FitResult, deviation, fit_baseline, predict
from services.energy.sec import SecResult, compute_sec

__all__ = [
    "FitResult",
    "Interval",
    "SecResult",
    "build_events",
    "build_intervals",
    "compute_sec",
    "deviation",
    "fit_baseline",
    "l1_flags",
    "mad_zscores",
    "merge_runs",
    "predict",
]
