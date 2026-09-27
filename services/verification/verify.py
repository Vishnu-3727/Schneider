"""Counterfactual savings verification (pure, no DB). IPMVP Option C / ISO 50015 style.

Question answered: how much energy WOULD the machine have used in the
measurement (post) period had the intervention NOT been made?

    counterfactual = baseline model fitted on the PRE period, driven by
                     the POST period's exogenous drivers
    saving         = counterfactual - actual (post)

Driver rule (the core of this module): the counterfactual may only use
drivers the intervention cannot change. Here that is hourly good production
at t-1, t and t+1 (a heat's heating hour precedes its melting hour, so
neighbouring production explains the energy of hour t). Machine-state hours
are deliberately NOT drivers: REDUCE_IDLE turns powered holding into idle,
so a model fed post-period state hours would predict the lower energy as
"expected" and erase the very saving being verified.

Uncertainty: ASHRAE Guideline 14 fractional savings uncertainty,
    U = t * 1.26 * CV * sqrt((n / n') * (1 + 2 / n) * (1 / m)) * E_cf
with n baseline points, n' = n (1 - rho) / (1 + rho) the autocorrelation-
corrected count (rho = lag-1 autocorrelation of baseline residuals), m post
points, E_cf the post-period counterfactual total and t the Student-t value
at the configured confidence with n - p degrees of freedom.

Outcomes (result_class -> lifecycle status):
    SUCCESS           saving > U and > 0          -> VERIFIED
    NO_EFFECT         |saving| <= U               -> NOT_VERIFIED
    WORSE             saving < -U                 -> NOT_VERIFIED (energy increased)
    NOT_COMPARABLE    production not comparable   -> NOT_COMPARABLE (no saving)
    INSUFFICIENT_DATA too little/poor data or an
                      unacceptable baseline fit   -> INSUFFICIENT_DATA (no saving)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from services.energy.baseline import g14_label

METHOD = "avoided-energy OLS on hourly production (t-1, t, t+1); ASHRAE G14 FSU"
FEATURES = ["intercept", "prod_prev_kg", "prod_kg", "prod_next_kg"]


@dataclass
class VerifyConfig:
    confidence: float = 0.90
    min_baseline_points: int = 72
    min_post_points: int = 24
    min_complete_frac: float = 0.90
    prod_tol_pct: float = 15.0
    max_extrapolated_frac: float = 0.05
    g14_cv_max_pct: float = 30.0
    g14_nmbe_max_pct: float = 10.0


@dataclass
class VerificationOutcome:
    result_class: str
    status: str
    explanation: str
    method: str = METHOD
    counterfactual_kwh: float | None = None
    actual_kwh: float | None = None
    saving_kwh: float | None = None
    saving_pct: float | None = None
    uncertainty_kwh: float | None = None
    confidence: float | None = None
    production_before_kg_h: float | None = None
    production_after_kg_h: float | None = None
    n_baseline: int = 0
    n_post: int = 0
    baseline_complete_frac: float = 0.0
    post_complete_frac: float = 0.0
    comparable: bool | None = None
    comparability_reasons: list[str] = field(default_factory=list)
    model: dict = field(default_factory=dict)
    # Per usable measurement hour: window_start, counterfactual_kwh, actual_kwh.
    # Filled only when a counterfactual exists (needed for time-of-use cost).
    hourly: list[dict] = field(default_factory=list)


def design(rows: list[dict], with_index: bool = False):
    """Usable (X, y) from time-ordered hourly rows; also the total row count.

    A row is usable when it and both neighbours have production and the row
    itself is complete with an energy value. Rows are dicts with
    complete, energy_kwh, good_production_kg (optionally window_start).
    with_index=True also returns the indices of the usable rows.
    """
    X, y, idx = [], [], []
    for i in range(1, len(rows) - 1):
        prev, cur, nxt = rows[i - 1], rows[i], rows[i + 1]
        prods = [r.get("good_production_kg") for r in (prev, cur, nxt)]
        if (not cur.get("complete") or cur.get("energy_kwh") is None
                or any(p is None for p in prods)):
            continue
        X.append([1.0, *prods])
        y.append(cur["energy_kwh"])
        idx.append(i)
    out = (np.array(X, dtype=float).reshape(-1, 4), np.array(y, dtype=float),
           max(0, len(rows) - 2))
    return (*out, idx) if with_index else out


def _lag1(resid: np.ndarray) -> float:
    if len(resid) < 3 or float(np.std(resid)) == 0.0:
        return 0.0
    return float(np.corrcoef(resid[:-1], resid[1:])[0, 1])


def savings_uncertainty(cv: float, n: int, n_eff: float, m: int, p: int,
                        e_cf_kwh: float, confidence: float) -> float:
    """ASHRAE Guideline 14 absolute savings uncertainty (kWh)."""
    t = float(stats.t.ppf(1.0 - (1.0 - confidence) / 2.0, max(1, n - p)))
    return t * 1.26 * cv * float(np.sqrt((n / n_eff) * (1.0 + 2.0 / n) * (1.0 / m))) * e_cf_kwh


def _no_saving(result_class: str, explanation: str, **kw) -> VerificationOutcome:
    return VerificationOutcome(result_class=result_class, status=result_class,
                               explanation=explanation, **kw)


def verify(baseline_rows: list[dict], post_rows: list[dict],
           cfg: VerifyConfig | None = None) -> VerificationOutcome:
    cfg = cfg or VerifyConfig()
    Xb, yb, nb_total = design(baseline_rows)
    Xp, yp, np_total, p_idx = design(post_rows, with_index=True)
    n, m = len(yb), len(yp)
    b_frac = n / nb_total if nb_total else 0.0
    p_frac = m / np_total if np_total else 0.0
    common = {"n_baseline": n, "n_post": m, "baseline_complete_frac": round(b_frac, 3),
              "post_complete_frac": round(p_frac, 3)}

    # 1. Enough good data on both sides?
    if n < cfg.min_baseline_points or b_frac < cfg.min_complete_frac:
        return _no_saving("INSUFFICIENT_DATA",
                          f"Baseline period has {n} usable hours ({b_frac:.0%} complete); "
                          f"need >= {cfg.min_baseline_points} and >= {cfg.min_complete_frac:.0%}.",
                          **common)
    if m < cfg.min_post_points or p_frac < cfg.min_complete_frac:
        return _no_saving("INSUFFICIENT_DATA",
                          f"Measurement period has {m} usable hours ({p_frac:.0%} complete); "
                          f"need >= {cfg.min_post_points} and >= {cfg.min_complete_frac:.0%}. "
                          "Savings cannot be verified from incomplete measurements.",
                          **common)

    # 2. Baseline model: OLS on exogenous drivers only.
    beta, *_ = np.linalg.lstsq(Xb, yb, rcond=None)
    p = Xb.shape[1]
    resid = yb - Xb @ beta
    ybar = float(np.mean(yb))
    rmse = float(np.sqrt(np.sum(resid ** 2) / max(1, n - p)))
    cv = rmse / ybar if ybar else float("inf")
    nmbe = float(np.sum(resid) / (max(1, n - p) * ybar) * 100.0) if ybar else None
    label = g14_label(cv * 100.0, nmbe, cfg.g14_cv_max_pct, cfg.g14_nmbe_max_pct)
    rho = max(0.0, _lag1(resid))
    n_eff = n * (1.0 - rho) / (1.0 + rho) if rho < 1.0 else 1.0
    model = {"features": FEATURES, "coefficients": [round(float(b), 6) for b in beta],
             "cv_rmse_pct": round(cv * 100.0, 3), "nmbe_pct": round(nmbe, 3) if nmbe is not None else None,
             "g14": label, "lag1_autocorr": round(rho, 4), "n_effective": round(n_eff, 1)}
    common["model"] = model
    if label != "ACCEPTABLE":
        return _no_saving("INSUFFICIENT_DATA",
                          f"Baseline model not acceptable under ASHRAE G14 (CV(RMSE) "
                          f"{cv * 100:.1f} %, NMBE {nmbe:.2f} %); a counterfactual from it "
                          "would not be defensible.", **common)

    # 3. Comparability: no extrapolation beyond the baseline's production.
    prod_b = Xb[:, 2]
    prod_p = Xp[:, 2]
    mean_b, mean_p = float(np.mean(prod_b)), float(np.mean(prod_p))
    common["production_before_kg_h"] = round(mean_b, 3)
    common["production_after_kg_h"] = round(mean_p, 3)
    reasons = []
    if mean_b > 0 and abs(mean_p - mean_b) / mean_b * 100.0 > cfg.prod_tol_pct:
        reasons.append(f"mean production changed {((mean_p - mean_b) / mean_b) * 100:+.1f} % "
                       f"(tolerance ±{cfg.prod_tol_pct:.0f} %)")
    hi = float(np.max(prod_b)) * 1.05
    out_frac = float(np.mean(prod_p > hi)) if m else 0.0
    if out_frac > cfg.max_extrapolated_frac:
        reasons.append(f"{out_frac:.0%} of measurement hours exceed the baseline production "
                       "range (the model would extrapolate)")
    if reasons:
        return _no_saving("NOT_COMPARABLE",
                          "Operating conditions are not comparable: " + "; ".join(reasons)
                          + ". No saving is reported.",
                          comparable=False, comparability_reasons=reasons, **common)

    # 4. Counterfactual, saving, uncertainty.
    cf_h = Xp @ beta
    e_cf = float(np.sum(cf_h))
    e_act = float(np.sum(yp))
    common["hourly"] = [{"window_start": post_rows[i].get("window_start"),
                         "counterfactual_kwh": float(c), "actual_kwh": float(a)}
                        for i, c, a in zip(p_idx, cf_h, yp, strict=True)]
    saving = e_cf - e_act
    u = savings_uncertainty(cv, n, n_eff, m, p, e_cf, cfg.confidence)
    vals = {"counterfactual_kwh": round(e_cf, 3), "actual_kwh": round(e_act, 3),
            "saving_kwh": round(saving, 3),
            "saving_pct": round(saving / e_cf * 100.0, 3) if e_cf else None,
            "uncertainty_kwh": round(u, 3), "confidence": cfg.confidence,
            "comparable": True}
    if saving > u and saving > 0:
        return VerificationOutcome(
            "SUCCESS", "VERIFIED",
            f"Energy {saving:.1f} kWh ({saving / e_cf:.1%}) below the counterfactual; exceeds "
            f"the ±{u:.1f} kWh uncertainty at {cfg.confidence:.0%} confidence.",
            **vals, **common)
    if saving < -u:
        return VerificationOutcome(
            "WORSE", "NOT_VERIFIED",
            f"Energy INCREASED by {-saving:.1f} kWh ({-saving / e_cf:.1%}) versus the "
            f"counterfactual, beyond the ±{u:.1f} kWh uncertainty. The intervention did not "
            "reduce energy.", **vals, **common)
    return VerificationOutcome(
        "NO_EFFECT", "NOT_VERIFIED",
        f"No statistically meaningful change: {saving:+.1f} kWh against the counterfactual is "
        f"within the ±{u:.1f} kWh uncertainty at {cfg.confidence:.0%} confidence.",
        **vals, **common)
