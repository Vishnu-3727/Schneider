"""Phase 5A: counterfactual verification maths, driver choice, lifecycle."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from scipy import stats

from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory
from services.energy.aggregate import build_intervals
from services.energy.baseline import fit_baseline, predict
from services.verification import lifecycle
from services.verification.verify import VerifyConfig, design, savings_uncertainty, verify

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, tzinfo=TZ)
FURNACE = [MachineSpec("furnace-01", "furnace", 150.0)]
BASE_H, POST_H = 24 * 7, 24 * 3


def _intervals(**kw):
    fac = SimulatedFactory(FURNACE, hours=BASE_H + POST_H, step_s=300, seed=1, end=END,
                           chronic_idle_hold_frac=0.6, **kw)
    tel, prod = fac.run()
    for t in tel:
        t["ts"] = datetime.fromisoformat(t["ts"])
        t["quality"] = "GOOD"
    for p in prod:
        p["window_start"] = datetime.fromisoformat(p["window_start"])
        p["quality"] = "GOOD"
    start = END - timedelta(hours=BASE_H + POST_H)
    ivs = build_intervals("furnace-01", tel, prod, start, END, 3600, 80.0)
    cut = END - timedelta(hours=POST_H)
    return [i for i in ivs if i.window_start < cut], [i for i in ivs if i.window_start >= cut]


def _rows(ivs):
    return [{"complete": i.complete, "energy_kwh": i.energy_kwh,
             "good_production_kg": i.good_production_kg} for i in ivs]


def _synthetic(n, slope, intercept, rng, shift=0.0):
    prod = rng.uniform(100, 200, n + 2)
    rows = []
    for k in range(1, n + 1):
        e = intercept + slope * prod[k] + 0.5 * slope * prod[k + 1] + rng.normal(0, 5.0) - shift
        rows.append({"complete": True, "energy_kwh": e, "good_production_kg": float(prod[k])})
    return rows


def test_uncertainty_matches_hand_computation():
    cv, n, n_eff, m, p, e_cf, conf = 0.10, 168, 168.0, 72, 4, 6000.0, 0.90
    t = stats.t.ppf(0.95, 164)
    expected = t * 1.26 * 0.10 * np.sqrt((168 / 168) * (1 + 2 / 168) * (1 / 72)) * 6000.0
    assert savings_uncertainty(cv, n, n_eff, m, p, e_cf, conf) == pytest.approx(expected)
    # Autocorrelation shrinks the effective sample -> wider uncertainty.
    assert savings_uncertainty(cv, n, 84.0, m, p, e_cf, conf) > expected


def test_design_needs_neighbour_production_and_complete_rows():
    rows = [{"complete": True, "energy_kwh": 1.0, "good_production_kg": 1.0} for _ in range(5)]
    rows[2]["complete"] = False
    rows[3]["good_production_kg"] = None
    _, y, total = design(rows)
    # row1 usable (neighbour row2 is incomplete but has production);
    # row2 is incomplete; row3 has no production.
    assert total == 3 and len(y) == 1
    rows2 = [{"complete": True, "energy_kwh": float(k), "good_production_kg": 2.0 * k} for k in range(6)]
    X2, y2, total2 = design(rows2)
    assert total2 == 4 and len(y2) == 4
    assert X2[0].tolist() == [1.0, 0.0, 2.0, 4.0]


def test_outcome_branches_on_synthetic_data():
    rng = np.random.default_rng(0)
    base = _synthetic(168, 2.0, 50.0, rng)
    assert verify(base, _synthetic(72, 2.0, 50.0, rng)).result_class == "NO_EFFECT"
    good = verify(base, _synthetic(72, 2.0, 50.0, rng, shift=30.0))
    assert good.result_class == "SUCCESS" and good.status == "VERIFIED"
    assert good.saving_kwh > good.uncertainty_kwh > 0
    bad = verify(base, _synthetic(72, 2.0, 50.0, rng, shift=-30.0))
    assert bad.result_class == "WORSE" and bad.status == "NOT_VERIFIED"
    assert "INCREASED" in bad.explanation and bad.saving_kwh < 0
    short = verify(base, _synthetic(10, 2.0, 50.0, rng))
    assert short.result_class == "INSUFFICIENT_DATA" and short.saving_kwh is None


def test_not_comparable_suppresses_saving():
    rng = np.random.default_rng(1)
    base = _synthetic(168, 2.0, 50.0, rng)
    post = _synthetic(72, 2.0, 50.0, rng)
    for r in post:
        r["good_production_kg"] *= 1.6
    out = verify(base, post)
    assert out.result_class == "NOT_COMPARABLE" and out.comparable is False
    assert out.saving_kwh is None and out.counterfactual_kwh is None
    assert out.comparability_reasons


def test_unacceptable_baseline_fit_is_insufficient_data():
    rng = np.random.default_rng(2)
    base = [{"complete": True, "energy_kwh": float(rng.uniform(1, 400)),
             "good_production_kg": float(rng.uniform(100, 200))} for _ in range(170)]
    out = verify(base, base[:80], VerifyConfig(g14_cv_max_pct=5.0))
    assert out.result_class == "INSUFFICIENT_DATA" and "G14" in out.explanation


def test_state_hour_drivers_would_erase_a_real_saving():
    """REDUCE_IDLE turns holding into idle. A baseline fed post-period state hours
    predicts the lower energy as 'expected' (no saving); the exogenous-driver
    counterfactual recovers the saving. This is why verify() uses production only."""
    base, post = _intervals(intervention={"type": "REDUCE_IDLE", "start_h": BASE_H,
                                          "effectiveness": 1.0})
    out = verify(_rows(base), _rows(post))
    assert out.result_class == "SUCCESS" and out.saving_kwh > 200.0

    fit = fit_baseline(base, "furnace", ["pump", "compressor"], 24, 0.0)
    state_cf = sum(predict(fit.features, fit.coefficients, fit.intercept,
                           i.hours_by_state, i.good_production_kg)
                   for i in post if i.complete and i.energy_kwh is not None)
    state_actual = sum(i.energy_kwh for i in post if i.complete and i.energy_kwh is not None)
    state_saving = state_cf - state_actual
    assert abs(state_saving) < 0.25 * out.saving_kwh


def test_lifecycle_transitions():
    assert lifecycle.can("PENDING_REVIEW", "APPROVED")
    assert lifecycle.can("APPROVED", "APPLIED")
    assert lifecycle.can("APPLIED", "MEASURED")
    for o in lifecycle.OUTCOMES:
        assert lifecycle.can("MEASURED", o)
    assert not lifecycle.can("PENDING_REVIEW", "APPLIED")
    assert not lifecycle.can("REJECTED", "APPLIED")
    assert not lifecycle.can("APPROVED", "VERIFIED")
    assert not lifecycle.can("VERIFIED", "APPLIED")
    assert lifecycle.allowed("VERIFIED") == ()
