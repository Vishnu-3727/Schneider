"""Unit tests: baseline fit (NNLS), deviation, insufficient history, exclusions."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from services.energy.aggregate import Interval
from services.energy.baseline import deviation, fit_baseline, g14_label, nmbe_pct, predict

TZ = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def _interval(k: int, energy: float, state: str, hours: float, prod_kg: float,
              complete: bool = True) -> Interval:
    ws = T0 + timedelta(hours=k)
    hb = {"running": 0.0, "melting": 0.0, "idle": 0.0, state: hours}
    return Interval(machine_id="m1", window_start=ws, window_end=ws + timedelta(hours=1),
                    complete=complete, energy_kwh=energy, hours_by_state=hb,
                    n_good=12, coverage_pct=95.0, good_production_kg=prod_kg,
                    has_production_record=True)


def _synthetic(n: int = 40) -> list[Interval]:
    """E = 10 + 100*h_running + 0.5*prod_kg exactly (no noise)."""
    out = []
    for k in range(n):
        h = 0.5 + 0.5 * ((k * 37 % 10) / 10.0)
        prod = float((k * 53 % 200) + 10)
        out.append(_interval(k, 10.0 + 100.0 * h + 0.5 * prod, "running", h, prod))
    return out


def test_fit_recovers_known_coefficients():
    res = fit_baseline(_synthetic(), "motor", ["pump"], min_intervals=10, holdout_fraction=0.2)
    assert res.status == "OK"
    assert res.r2_train == pytest.approx(1.0, abs=1e-6)
    assert res.intercept == pytest.approx(10.0, rel=1e-4)
    assert res.coefficients["hours_running"] == pytest.approx(100.0, rel=1e-4)
    assert res.coefficients["good_production_kg"] == pytest.approx(0.5, rel=1e-4)


def test_fit_coefficients_never_negative():
    res = fit_baseline(_synthetic(), "motor", ["pump"], min_intervals=10, holdout_fraction=0.2)
    assert all(v >= 0 for v in res.coefficients.values())
    assert res.intercept >= 0


def test_insufficient_history():
    res = fit_baseline(_synthetic(n=5), "motor", ["pump"], min_intervals=24, holdout_fraction=0.2)
    assert res.status == "INSUFFICIENT_BASELINE_HISTORY"
    assert res.r2_train is None


def test_incomplete_intervals_excluded_from_fit():
    rows = _synthetic(n=40)
    # Poisoned incomplete intervals must not move the fit.
    for k in range(5):
        rows.append(_interval(100 + k, 1e6, "running", 1.0, 0.0, complete=False))
    res = fit_baseline(rows, "motor", ["pump"], min_intervals=10, holdout_fraction=0.2)
    assert res.status == "OK"
    assert res.n_intervals + res.n_holdout == 40
    assert res.r2_train == pytest.approx(1.0, abs=1e-6)


def test_deviation_near_zero_expected_is_null_never_inf():
    d = deviation(50.0, 0.1, epsilon_kwh=0.5)
    assert d.status == "EXPECTED_NEAR_ZERO"
    assert d.deviation_pct is None
    assert d.deviation_kwh == pytest.approx(49.9)
    import math

    assert not math.isinf(d.deviation_kwh) and not math.isnan(d.deviation_kwh)


def test_deviation_normal_case():
    d = deviation(125.0, 100.0, epsilon_kwh=0.5)
    assert d.status == "OK"
    assert d.deviation_kwh == pytest.approx(25.0)
    assert d.deviation_pct == pytest.approx(25.0)


def test_deviation_without_baseline():
    d = deviation(125.0, None, epsilon_kwh=0.5)
    assert d.status == "INSUFFICIENT_BASELINE_HISTORY"
    assert d.deviation_pct is None


def test_predict_uses_production_normalisation():
    # Same state hours, double production -> higher expected (not a global average).
    res = fit_baseline(_synthetic(), "motor", ["pump"], min_intervals=10, holdout_fraction=0.2)
    e1 = predict(res.features, res.coefficients, res.intercept, {"running": 1.0}, 100.0)
    e2 = predict(res.features, res.coefficients, res.intercept, {"running": 1.0}, 200.0)
    assert e2 > e1


def test_nmbe_formula():
    # NMBE = sum(yhat - y) / (n * mean(y)) * 100; +10 % uniform over-prediction.
    assert nmbe_pct(np.array([100.0, 100.0, 100.0]),
                    np.array([110.0, 110.0, 110.0])) == pytest.approx(10.0)
    assert nmbe_pct(np.array([100.0, 200.0]),
                    np.array([90.0, 180.0])) == pytest.approx(-10.0)
    assert nmbe_pct(np.array([100.0, 100.0]),
                    np.array([100.0, 100.0])) == pytest.approx(0.0)
    # Zero-mean target -> None, never inf/NaN.
    assert nmbe_pct(np.array([0.0, 0.0]), np.array([1.0, 2.0])) is None


def test_g14_label_hourly_criteria():
    # ASHRAE Guideline 14 hourly: CV(RMSE) <= 30 % and |NMBE| <= 10 %.
    assert g14_label(6.6, 1.0, 30.0, 10.0) == "ACCEPTABLE"
    assert g14_label(30.0, 10.0, 30.0, 10.0) == "ACCEPTABLE"  # boundaries inclusive
    assert g14_label(30.1, 1.0, 30.0, 10.0) == "NOT_ACCEPTABLE"
    assert g14_label(6.6, -10.5, 30.0, 10.0) == "NOT_ACCEPTABLE"
    assert g14_label(None, 1.0, 30.0, 10.0) == "NOT_ACCEPTABLE"
    assert g14_label(6.6, None, 30.0, 10.0) == "NOT_ACCEPTABLE"


def test_fit_reports_nmbe_and_acceptance():
    res = fit_baseline(_synthetic(), "motor", ["pump"], min_intervals=10, holdout_fraction=0.2)
    assert res.status == "OK"
    assert res.nmbe_pct_holdout == pytest.approx(0.0, abs=1e-6)
    assert res.acceptance == "ACCEPTABLE"
