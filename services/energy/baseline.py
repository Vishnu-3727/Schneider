"""Production-normalised expected-energy baseline (pure, no DB, no magic numbers).

Model (interpretable multivariable linear, non-negative least squares via scipy):

    E_expected = b0 + b_prod * good_production_kg + b_hold * hours_holding
                 + b_idle * hours_idle            (furnace / production types)
    E_expected = b0 + SUM_state b_state * hours_in_state   (non-production types)

Feature set is configured per machine type:
  - furnace (production machine): good_production_kg + hours_heating +
    hours_holding + hours_idle. Melting energy is carried by the production
    term (energy = fixed + variable x production, ISO 50006 style); heating,
    holding and idle hours capture time-based losses. Melting hours are
    deliberately EXCLUDED: the simulator's near-constant melt rate makes
    melting-hours and production near-perfectly collinear, so including both
    lets the fit split one physical effect arbitrarily across two
    coefficients (predictions exact on-manifold, coefficients meaningless,
    off-manifold extrapolation fragile). Heating hours are kept: heating is
    a fixed ~20 min per heat while melt duration varies with charge weight,
    so hourly heating hours and production are only moderately correlated
    and the fit identifies both (verified: NNLS recovers b_heat near the
    true heating power). Dropping the melting-hour column removes the
    collinearity by construction.
  - compressor / pump (non-production types, from config NON_PRODUCTION_TYPES):
    state hours only. The simulator provides no extra load/throughput variable,
    so no load feature exists; see docs/ML_MODELS.md. If one appears later it
    is appended as an extra non-negative feature column.

Physical sensibility: per-state energy coefficients and the production
coefficient must be >= 0 (a machine state cannot consume negative energy).
The fit uses non-negative least squares (scipy.optimize.nnls) so the
non-negativity is imposed JOINTLY during optimisation — not by clipping
afterwards (post-hoc clipping of one coefficient in a collinear set such as
melting-hours vs production silently destroys predictions; verified during
Phase-2 development: lstsq+clip gave R²_train = -1.9 on NORMAL furnace data).
The intercept is also constrained >= 0 (fixed auxiliary load / meter offset
cannot be negative). Features whose fitted coefficient sits at the 0 bound
while active in training are reported in `clipped` for transparency.

Only NORMAL, complete intervals may be fitted/scored (callers filter).
Too little history -> status INSUFFICIENT_BASELINE_HISTORY, no numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import nnls


@dataclass
class FitResult:
    status: str  # OK | INSUFFICIENT_BASELINE_HISTORY
    features: list[str] = field(default_factory=list)
    coefficients: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    clipped: list[str] = field(default_factory=list)
    n_intervals: int = 0
    n_holdout: int = 0
    r2_train: float | None = None
    cv_rmse_pct_train: float | None = None
    nmbe_pct_train: float | None = None
    r2_holdout: float | None = None
    cv_rmse_pct_holdout: float | None = None
    nmbe_pct_holdout: float | None = None
    acceptance: str | None = None  # ACCEPTABLE | NOT_ACCEPTABLE (ASHRAE G14 hourly)


def features_for_machine_type(machine_type: str, non_production_types: list[str]) -> list[str]:
    """Ordered feature names. State set is fixed (union of simulator states)."""
    states = ["heating", "melting", "holding", "idle", "running", "stopped", "shutdown", "auxiliary"]
    if machine_type == "furnace":
        # ISO 50006 style: production carries melting energy; heating,
        # holding and idle hours capture time-based losses. Excludes
        # melting hours only (collinear with production — see docstring).
        return ["good_production_kg", "hours_heating", "hours_holding", "hours_idle"]
    feats = [f"hours_{s}" for s in states]
    if machine_type not in non_production_types:
        feats.append("good_production_kg")
    return feats


def _row_vector(features: list[str], hours_by_state: dict, good_production_kg: float | None) -> list[float]:
    row = []
    for f in features:
        if f.startswith("hours_"):
            row.append(float(hours_by_state.get(f[len("hours_"):], 0.0)))
        elif f == "good_production_kg":
            row.append(float(good_production_kg or 0.0))
        else:  # future load/throughput variable: carried in hours_by_state dict
            row.append(float(hours_by_state.get(f, 0.0)))
    return row


def _r2(y: np.ndarray, yhat: np.ndarray) -> float | None:
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 0:
        return None
    ss_res = float(np.sum((y - yhat) ** 2))
    return 1.0 - ss_res / ss_tot


def _cv_rmse_pct(y: np.ndarray, yhat: np.ndarray) -> float | None:
    mean = float(np.mean(y))
    if mean <= 0:
        return None
    rmse = float(np.sqrt(np.mean((y - yhat) ** 2)))
    return rmse / mean * 100.0


def nmbe_pct(y: np.ndarray, yhat: np.ndarray) -> float | None:
    """Normalised mean bias error (%): sum(yhat - y) / (n * mean(y)) * 100.

    Positive = model over-predicts on average. Returns None when mean(y) <= 0
    (never inf/NaN). R² is reported for information only; acceptance uses
    ASHRAE Guideline 14 hourly criteria (see g14_label).
    """
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    if y.size == 0:
        return None
    mean = float(np.mean(y))
    if mean <= 0:
        return None
    return float(np.sum(yhat - y) / (y.size * mean) * 100.0)


def g14_label(cv_rmse: float | None, nmbe: float | None,
              cv_max_pct: float, nmbe_max_pct: float) -> str:
    """ASHRAE Guideline 14 hourly acceptance: CV(RMSE) <= max and |NMBE| <= max.

    R² is NOT part of the decision (it is meaningless when the target
    variance is near zero, e.g. the near-constant pump load). Missing
    metrics -> NOT_ACCEPTABLE (cannot demonstrate acceptance).
    """
    if cv_rmse is None or nmbe is None:
        return "NOT_ACCEPTABLE"
    if cv_rmse <= cv_max_pct and abs(nmbe) <= nmbe_max_pct:
        return "ACCEPTABLE"
    return "NOT_ACCEPTABLE"


def fit_baseline(
    intervals: list,
    machine_type: str,
    non_production_types: list[str],
    min_intervals: int,
    holdout_fraction: float,
    cv_max_pct: float = 30.0,
    nmbe_max_pct: float = 10.0,
) -> FitResult:
    """Fit on complete intervals with usable energy. Time-ordered tail holdout.

    `intervals` must already be NORMAL-only; each item needs .energy_kwh,
    .hours_by_state, .good_production_kg, .complete. Incomplete intervals and
    intervals with energy_kwh None are excluded (never silently: caller counts
    them; n_intervals reports only fitted rows).
    """
    feats = features_for_machine_type(machine_type, non_production_types)
    rows = [iv for iv in intervals if iv.complete and iv.energy_kwh is not None]
    if len(rows) < min_intervals:
        return FitResult(status="INSUFFICIENT_BASELINE_HISTORY", features=feats, n_intervals=len(rows))
    rows = sorted(rows, key=lambda iv: iv.window_start)
    X = np.array([_row_vector(feats, iv.hours_by_state, iv.good_production_kg) for iv in rows])
    y = np.array([float(iv.energy_kwh) for iv in rows])
    n = len(rows)
    n_hold = int(n * holdout_fraction)
    # Holdout needs >= 1 row and >= 1 train row beyond feature count; else train-only.
    if n_hold >= 1 and (n - n_hold) >= max(2, X.shape[1] + 1):
        Xtr, Xho, ytr, yho = X[: n - n_hold], X[n - n_hold :], y[: n - n_hold], y[n - n_hold :]
    else:
        Xtr, Xho, ytr, yho = X, None, y, None
    A = np.column_stack([np.ones(len(Xtr)), Xtr])
    coef, _rnorm = nnls(A, ytr)
    intercept = float(coef[0])
    coefs = {f: float(c) for f, c in zip(feats, coef[1:], strict=True)}
    active = set(np.nonzero(Xtr.sum(axis=0))[0])
    clipped = [f for j, f in enumerate(feats) if coefs[f] <= 0 and j in active]
    pred_tr = intercept + sum(coefs[f] * Xtr[:, j] for j, f in enumerate(feats))
    r2_tr, cv_tr = _r2(ytr, pred_tr), _cv_rmse_pct(ytr, pred_tr)
    nmbe_tr = nmbe_pct(ytr, pred_tr)
    r2_ho, cv_ho, nmbe_ho = None, None, None
    if Xho is not None:
        pred_ho = intercept + sum(coefs[f] * Xho[:, j] for j, f in enumerate(feats))
        r2_ho, cv_ho = _r2(yho, pred_ho), _cv_rmse_pct(yho, pred_ho)
        nmbe_ho = nmbe_pct(yho, pred_ho)
    acceptance = g14_label(cv_ho if Xho is not None else cv_tr,
                           nmbe_ho if Xho is not None else nmbe_tr,
                           cv_max_pct, nmbe_max_pct)
    return FitResult(
        status="OK",
        features=feats,
        coefficients=coefs,
        intercept=intercept,
        clipped=clipped,
        n_intervals=len(Xtr),
        n_holdout=len(Xho) if Xho is not None else 0,
        r2_train=r2_tr,
        cv_rmse_pct_train=cv_tr,
        nmbe_pct_train=nmbe_tr,
        r2_holdout=r2_ho,
        cv_rmse_pct_holdout=cv_ho,
        nmbe_pct_holdout=nmbe_ho,
        acceptance=acceptance,
    )


def predict(
    features: list[str],
    coefficients: dict[str, float],
    intercept: float,
    hours_by_state: dict,
    good_production_kg: float | None,
) -> float:
    row = _row_vector(features, hours_by_state, good_production_kg)
    return float(intercept + sum(coefficients[f] * v for f, v in zip(features, row, strict=True)))


@dataclass
class DeviationResult:
    expected_kwh: float | None
    deviation_kwh: float | None
    deviation_pct: float | None
    status: str  # OK | EXPECTED_NEAR_ZERO | INSUFFICIENT_BASELINE_HISTORY


def deviation(actual_kwh: float | None, expected_kwh: float | None, epsilon_kwh: float) -> DeviationResult:
    """deviation = actual - expected. expected <= eps -> pct null, never inf/NaN."""
    if expected_kwh is None:
        return DeviationResult(None, None, None, "INSUFFICIENT_BASELINE_HISTORY")
    if actual_kwh is None:
        return DeviationResult(expected_kwh, None, None, "INSUFFICIENT_BASELINE_HISTORY")
    dev = actual_kwh - expected_kwh
    if expected_kwh <= epsilon_kwh:
        return DeviationResult(expected_kwh, dev, None, "EXPECTED_NEAR_ZERO")
    return DeviationResult(expected_kwh, dev, dev / expected_kwh * 100.0, "OK")
