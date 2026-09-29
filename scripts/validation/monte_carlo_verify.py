"""Monte Carlo validation of the savings verification (SIMULATED data only).

Proves ``services.verification.verify.verify`` gets the outcome right (not luck)
by simulating many plants whose TRUE saving is known via paired runs with
common random numbers: for each seed the SAME plant is simulated twice with
the same seed -- once with the intervention, once with a NO-OP intervention
(same type, start_h and compliance, but ``effectiveness=0.0`` and
``rebound=0.0``; same ``post_idle_scale`` in both runs). The NO-OP draws the
same random numbers as the real fix (``_plan_idle_hold`` draws one
``rng.random()`` per idle gap whenever ``idle_hold_frac_fixed`` is set), so
the two runs differ only by the physics of the fix. Effectiveness maps to
``idle_hold_frac_fixed = chronic * (1 - effectiveness)``
(``factory_simulator._apply_practice``), so effectiveness 0 leaves holding
unchanged. Before the applied time the two runs are identical; the script
asserts the pre-period energies match per pair, and for the no_effect
scenario the post-period energies match too (TRUE saving exactly 0). ::

    TRUE saving = energy(NO-OP post) - energy(intervention post)

Setup mirrors ``scripts/demo/run_demo.py``: one furnace (``furnace-01``,
200 kW), ``chronic_idle_hold_frac=0.6``, 7-day baseline + 3-day measurement at
``step_s=300``. Intervals are built with
``services.energy.aggregate.build_intervals`` and ``verify`` is called WITHOUT
the database, exactly like ``tests/unit/test_verification.py``.

Usage (from the repo root)::

    .venv\\Scripts\\python scripts\\validation\\monte_carlo_verify.py --n 100 --seed0 1
    .venv\\Scripts\\python scripts\\validation\\monte_carlo_verify.py --n 3 --seed0 1

Flags:

    --n       seeds per scenario (default 100)
    --seed0   first seed; seeds are ``seed0 .. seed0+n-1`` (default 1)
    --scenarios  subset of scenario names to run (default: all five)

Outputs (written by the script itself):

    docs/validation/monte_carlo_verify.csv  one row per run
    docs/validation/monte_carlo_verify.md   tables + one plain paragraph per scenario

``main()`` returns a dict with keys ``n``, ``seed0``, ``scenarios``,
``rows``, ``pre_equal_all`` and ``runtime_s`` for programmatic use (and for
``tests/unit/test_monte_carlo_smoke.py``).

Each row carries a ``paired`` flag: True when the intervention and control
runs started every heat at identical times (same sampled heat-start list),
i.e. the rebound did not shift any segment boundary across a sampling step
and the two runs stayed the same random realisation. Summary metrics are
reported both over all pairs and over paired pairs only; nothing is
dropped.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory
from services.energy.aggregate import build_intervals
from services.verification.verify import verify

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, tzinfo=TZ)
BASE_H, POST_H = 24 * 7, 24 * 3
MACHINE = "furnace-01"
RATED_KW = 200.0

# Scenario name -> simulator kwargs for the intervention run. The paired
# control run uses a NO-OP intervention (same type/start_h/compliance, but
# effectiveness=0.0 and rebound=0.0) with the same post_idle_scale in both
# runs, so both runs draw identical random numbers (common random numbers)
# and TRUE saving isolates the physics of the fix.
SCENARIOS: dict[str, dict] = {
    "no_effect": {
        "intervention": {"type": "REDUCE_IDLE", "start_h": BASE_H, "effectiveness": 0.0},
        "post_idle_scale": None,
        "blurb": "effectiveness 0.0: nothing changes, TRUE saving is ~0.",
    },
    "partial": {
        "intervention": {"type": "REDUCE_IDLE", "start_h": BASE_H,
                         "effectiveness": 0.5, "compliance": 0.6},
        "post_idle_scale": None,
        "blurb": "effectiveness 0.5, compliance 0.6: a real but small improvement.",
    },
    "full": {
        "intervention": {"type": "REDUCE_IDLE", "start_h": BASE_H,
                         "effectiveness": 1.0, "rebound": 0.15},
        "post_idle_scale": None,
        "blurb": "effectiveness 1.0, rebound 0.15: holding waste removed, some reheat.",
    },
    "worse": {
        "intervention": {"type": "REDUCE_IDLE", "start_h": BASE_H,
                         "effectiveness": 1.0, "rebound": 1.0},
        "post_idle_scale": None,
        "blurb": "effectiveness 1.0, rebound 1.0: reheat outweighs the fix, energy goes UP.",
    },
    "production_shift": {
        "intervention": {"type": "REDUCE_IDLE", "start_h": BASE_H, "effectiveness": 1.0},
        "post_idle_scale": 0.1,
        "blurb": "effectiveness 1.0 but production shifts after the change; must be refused.",
    },
}

OUTCOMES = ("VERIFIED", "NOT_VERIFIED", "NOT_COMPARABLE", "INSUFFICIENT_DATA")
RESULT_CLASSES = ("SUCCESS", "NO_EFFECT", "WORSE", "NOT_COMPARABLE", "INSUFFICIENT_DATA")


def _intervals(tel, prod):
    """Hourly intervals for the whole run, split into (baseline, post)."""
    for t in tel:
        t["ts"] = datetime.fromisoformat(t["ts"])
        t["quality"] = "GOOD"
    for p in prod:
        p["window_start"] = datetime.fromisoformat(p["window_start"])
        p["quality"] = "GOOD"
    start = END - timedelta(hours=BASE_H + POST_H)
    ivs = build_intervals(MACHINE, tel, prod, start, END, 3600, 80.0)
    cut = END - timedelta(hours=POST_H)
    return [i for i in ivs if i.window_start < cut], [i for i in ivs if i.window_start >= cut]


def _rows(ivs):
    return [{"complete": i.complete, "energy_kwh": i.energy_kwh,
             "good_production_kg": i.good_production_kg} for i in ivs]


def _esum(ivs):
    return float(sum(i.energy_kwh for i in ivs if i.energy_kwh is not None))


def _heat_starts(tel):
    """Sampled heat-start timestamps: steps entering the heating state."""
    return [t["ts"] for i, t in enumerate(tel)
            if t["machine_state"] == "heating"
            and (i == 0 or tel[i - 1]["machine_state"] != "heating")]


def _control_intervention(cfg: dict) -> dict:
    """NO-OP twin of the scenario intervention: same RNG consumption, no physics."""
    iv = cfg["intervention"]
    return {
        "type": iv["type"],
        "start_h": iv["start_h"],
        "effectiveness": 0.0,
        "compliance": float(iv.get("compliance", 1.0)),
        "rebound": 0.0,
    }


def run_pair(seed: int, cfg: dict, scenario: str | None = None) -> dict:
    """One paired plant: same seed with the intervention and with a NO-OP.

    Common random numbers: the control run carries the same ``intervention``
    type/start_h/compliance (``effectiveness=0.0``, ``rebound=0.0``) and the
    same ``post_idle_scale`` as the intervention run, so both runs draw
    identical random numbers and differ only by the physics of the fix
    (``idle_hold_frac_fixed = chronic * (1 - effectiveness)``: effectiveness
    0 leaves holding unchanged, rebound 0 leaves reheat at zero).
    Asserts per pair that the pre-period energies are identical, and for the
    no_effect scenario that the post-period energies are identical too
    (TRUE saving exactly 0). If either assertion fails the streams have
    diverged and the run stops instead of working around it.
    """
    spec = [MachineSpec(MACHINE, "furnace", RATED_KW)]
    total_h = BASE_H + POST_H

    iv_kw: dict = {"chronic_idle_hold_frac": 0.6,
                   "intervention": cfg["intervention"]}
    if cfg["post_idle_scale"] is not None:
        iv_kw["post_idle_scale"] = cfg["post_idle_scale"]
    fac_iv = SimulatedFactory(spec, hours=total_h, step_s=300, seed=seed, end=END,
                              **iv_kw)
    tel_iv, prod_iv = fac_iv.run()
    ctrl_kw: dict = {"chronic_idle_hold_frac": 0.6,
                     "intervention": _control_intervention(cfg)}
    if cfg["post_idle_scale"] is not None:
        ctrl_kw["post_idle_scale"] = cfg["post_idle_scale"]
    fac_ctrl = SimulatedFactory(spec, hours=total_h, step_s=300, seed=seed, end=END,
                                **ctrl_kw)
    tel_ctrl, prod_ctrl = fac_ctrl.run()

    base_iv, post_iv = _intervals(tel_iv, prod_iv)
    base_ctrl, post_ctrl = _intervals(tel_ctrl, prod_ctrl)

    # Pre-period paired-run equality: identical draws until the intervention
    # starts, so the pre-period energies must match.
    pre_iv, pre_ctrl = _esum(base_iv), _esum(base_ctrl)
    pre_equal = abs(pre_iv - pre_ctrl) < 1e-6
    assert pre_equal, (
        f"seed {seed}: pre-period energies differ "
        f"(intervention {pre_iv:.6f} vs control {pre_ctrl:.6f}); "
        "the random streams diverged before the intervention started."
    )

    true_saving = _esum(post_ctrl) - _esum(post_iv)
    if scenario is None:
        scenario = ("no_effect" if cfg["intervention"].get("effectiveness", 1.0) == 0.0
                    and cfg["intervention"].get("rebound", 0.0) == 0.0
                    and cfg.get("post_idle_scale") is None else None)
    if scenario == "no_effect":
        post_iv_e, post_ctrl_e = _esum(post_iv), _esum(post_ctrl)
        assert abs(true_saving) < 1e-6, (
            f"seed {seed}: no_effect post-period energies differ "
            f"(intervention {post_iv_e:.6f} vs control {post_ctrl_e:.6f}, "
            f"TRUE {true_saving:.6f}); the random streams diverged after "
            "the applied time despite the NO-OP control."
        )
    out = verify(_rows(base_iv), _rows(post_iv))

    reported = out.saving_kwh  # None when NOT_COMPARABLE / INSUFFICIENT_DATA
    unc = out.uncertainty_kwh
    covered = None
    if reported is not None and unc is not None:
        covered = bool(abs(true_saving - reported) <= unc)
    # Paired check: identical heat-start times in both runs. Rebound moves
    # the idle->heating boundary earlier (machine_models: idle gap shortened
    # by the pending reheat, next heating lengthened by the same amount), so
    # a shifted boundary can cross a sampling step and unpair the runs (see
    # module docstring). Identical heat starts mean the shift never did.
    paired = _heat_starts(tel_iv) == _heat_starts(tel_ctrl)
    return {
        "seed": seed,
        "paired": paired,
        "true_saving_kwh": round(true_saving, 3),
        "reported_saving_kwh": reported,
        "uncertainty_kwh": unc,
        "counterfactual_kwh": out.counterfactual_kwh,
        "actual_kwh": out.actual_kwh,
        "outcome": out.status,
        "result_class": out.result_class,
        "covered": covered,
        "abs_error_kwh": (round(abs(reported - true_saving), 3)
                          if reported is not None else None),
        "pre_equal": pre_equal,
    }


def summarise(name: str, rows: list[dict]) -> dict:
    outcome_counts = {o: sum(1 for r in rows if r["outcome"] == o) for o in OUTCOMES}
    class_counts = {c: sum(1 for r in rows if r["result_class"] == c) for c in RESULT_CLASSES}
    n = len(rows)
    neg = [r for r in rows if r["true_saving_kwh"] <= 0]
    n_neg_ver = sum(1 for r in neg if r["outcome"] == "VERIFIED")
    false_claim = (n_neg_ver / len(neg) if neg else None)
    comp = [r for r in rows if r["reported_saving_kwh"] is not None]
    coverage = (sum(1 for r in comp if r["covered"]) / len(comp) if comp else None)
    rep = [r["reported_saving_kwh"] for r in comp]
    err = [r["abs_error_kwh"] for r in comp]
    # Paired-only cuts: same metrics over pairs whose heat starts match.
    # Unpaired pairs are different random realisations (rebound shifted a
    # segment boundary), so their TRUE/coverage numbers are realisation
    # noise, not measurements of verify. Both cuts are reported; nothing
    # is dropped.
    paired_rows = [r for r in rows if r["paired"]]
    pneg = [r for r in paired_rows if r["true_saving_kwh"] <= 0]
    pneg_ver = sum(1 for r in pneg if r["outcome"] == "VERIFIED")
    pcomp = [r for r in paired_rows if r["reported_saving_kwh"] is not None]
    return {
        "scenario": name,
        "n": n,
        "n_paired": len(paired_rows),
        "outcome_counts": outcome_counts,
        "result_class_counts": class_counts,
        "verified": outcome_counts["VERIFIED"],
        "false_claim_rate": false_claim,
        "n_true_le0": len(neg),
        "n_verified_when_nonpositive": n_neg_ver,
        "false_claim_rate_paired": (pneg_ver / len(pneg) if pneg else None),
        "n_true_le0_paired": len(pneg),
        "n_verified_when_nonpositive_paired": pneg_ver,
        "detection_rate": outcome_counts["VERIFIED"] / n if n else None,
        "coverage": coverage,
        "n_comparable": len(comp),
        "coverage_paired": (sum(1 for r in pcomp if r["covered"]) / len(pcomp)
                            if pcomp else None),
        "n_comparable_paired": len(pcomp),
        "mean_true_kwh": sum(r["true_saving_kwh"] for r in rows) / n if n else None,
        "mean_reported_kwh": sum(rep) / len(rep) if rep else None,
        "mean_abs_error_kwh": sum(err) / len(err) if err else None,
    }


def _fmt(x, nd=1):
    if x is None:
        return "n/a"
    return f"{x:,.{nd}f}" if isinstance(x, (int, float)) else str(x)


def _pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def summary_table(summaries: list[dict]) -> str:
    head = ("| scenario | N | paired | VERIFIED | NOT_VERIFIED | NOT_COMPARABLE | INSUFFICIENT_DATA | "
            "false-claim all | false-claim paired | coverage all | coverage paired | "
            "mean TRUE kWh | mean reported kWh | mean |error| kWh |")
    sep = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [head, sep]
    for s in summaries:
        o = s["outcome_counts"]
        lines.append(
            f"| {s['scenario']} | {s['n']} | {s['n_paired']} | {o['VERIFIED']} | {o['NOT_VERIFIED']} | "
            f"{o['NOT_COMPARABLE']} | {o['INSUFFICIENT_DATA']} | "
            f"{_pct(s['false_claim_rate'])} | {_pct(s['false_claim_rate_paired'])} | "
            f"{_pct(s['coverage'])} | {_pct(s['coverage_paired'])} | "
            f"{_fmt(s['mean_true_kwh'])} | {_fmt(s['mean_reported_kwh'])} | "
            f"{_fmt(s['mean_abs_error_kwh'])} |"
        )
    return "\n".join(lines)


PARAGRAPHS = {
    "no_effect": ("Nothing was changed (NO-OP control: effectiveness 0), so the TRUE saving is "
                  "exactly 0 and "
                  "any VERIFIED outcome would be a false claim. The false-claim rate "
                  "says how often the 90 % uncertainty band cried wolf on identical "
                  "plants; a small single-digit rate is the expected price of a 90 % "
                  "confidence level, while anything near or above 10 % would mean the "
                  "uncertainty is understated."),
    "partial": ("The fix is real but small (effectiveness 0.5, compliance 0.6), so whether "
                "3 days of data can prove it depends on how much idle waste that week's "
                "seed happened to contain: waste-rich weeks verify, the rest honestly "
                "return NO_EFFECT with the saving inside the uncertainty band. That "
                "borderline split is the expected answer, not a miss -- a longer "
                "measurement window would narrow the uncertainty."),
    "full": ("The full fix (effectiveness 1.0, rebound 0.15) saves several hundred kWh, "
             "well above the uncertainty, so the detection rate -- the share VERIFIED "
             "-- should be at or near 100 %. Anything much lower would mean real "
             "savings are being missed. Most pairs here are unpaired (rebound moves "
             "heat starts, so the runs are different realisations): the all-pairs "
             "coverage mixes in realisation noise and only the paired-only cut "
             "measures the uncertainty band itself."),
    "worse": ("Reheat outweighs the fix (rebound 1.0), so TRUE saving is negative and "
              "verification must report WORSE / NOT_VERIFIED, never VERIFIED. The "
              "false-claim rate here is the share VERIFIED among runs where energy "
              "went up; it must be zero, and the WORSE label shows the increase is "
              "reported, not hidden. Most pairs here are unpaired (rebound moves "
              "heat starts, so the runs are different realisations): the all-pairs "
              "coverage mixes in realisation noise and only the paired-only cut "
              "measures the uncertainty band itself."),
    "production_shift": ("Production shifts after the change (post_idle_scale 0.1), so "
                         "the post period is not comparable to the baseline and every "
                         "run must be refused as NOT_COMPARABLE with no saving reported "
                         "-- even though a TRUE intervention effect exists. Any "
                         "VERIFIED outcome here would be a saving claimed under "
                         "non-comparable conditions, which the method forbids."),
}


def write_csv(path: Path, scenario_names: list[str], all_rows: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["scenario", "seed", "paired", "true_saving_kwh", "reported_saving_kwh",
              "uncertainty_kwh", "counterfactual_kwh", "actual_kwh", "outcome",
              "result_class", "covered", "abs_error_kwh", "pre_equal"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for name in scenario_names:
            for r in all_rows[name]:
                w.writerow({"scenario": name, **r})


def write_md(path: Path, command: str, summaries: list[dict], runtime_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Monte Carlo validation of savings verification (SIMULATED data)",
        "",
        (
            "Paired runs: for each seed the SAME plant is simulated twice with the same "
            "seed -- once with the intervention, once with a NO-OP intervention "
            "(common random numbers). "
            "TRUE saving = energy(NO-OP post) - energy(intervention post). "
            f"Setup: furnace-01 (200 kW), chronic idle holding 60 %, 7-day baseline + "
            f"3-day measurement, step 300 s. Command: `{command}`. "
            f"Runtime {runtime_s:.0f} s. All data SIMULATED; says nothing about real plant "
            "performance. Thresholds were NOT tuned to these numbers."
        ),
        "",
        "## Summary",
        "",
        summary_table(summaries),
        "",
        ("false-claim = share VERIFIED among runs with TRUE saving <= 0; coverage = "
         "share of comparable runs (a saving was reported) where TRUE saving lies "
         "within reported saving +/- uncertainty (stated confidence 90 %); "
         "means over comparable runs for reported/error. "
         "Each metric is shown over all pairs and over paired pairs only "
         "(identical heat-start times in both runs); unpaired pairs are "
         "different random realisations, not measurements of verify."),
        "",
    ]
    for s in summaries:
        o = s["outcome_counts"]
        c = s["result_class_counts"]
        lines += [
            f"## {s['scenario']} (N={s['n']}, paired={s['n_paired']})",
            "",
            (f"Outcomes: VERIFIED {o['VERIFIED']}, NOT_VERIFIED {o['NOT_VERIFIED']}, "
             f"NOT_COMPARABLE {o['NOT_COMPARABLE']}, "
             f"INSUFFICIENT_DATA {o['INSUFFICIENT_DATA']}. Result classes: "
             + ", ".join(f"{k} {v}" for k, v in c.items()) + ". "
             f"False-claim {_pct(s['false_claim_rate'])} "
             f"({s['n_verified_when_nonpositive']}/{s['n_true_le0']} VERIFIED among "
             f"runs with TRUE saving <= 0); paired-only "
             f"{_pct(s['false_claim_rate_paired'])} "
             f"({s['n_verified_when_nonpositive_paired']}/{s['n_true_le0_paired']}); "
             f"coverage {_pct(s['coverage'])} (n={s['n_comparable']} comparable); "
             f"paired-only {_pct(s['coverage_paired'])} "
             f"(n={s['n_comparable_paired']} comparable); mean TRUE "
             f"{_fmt(s['mean_true_kwh'])} kWh, mean reported "
             f"{_fmt(s['mean_reported_kwh'])} kWh, mean |error| "
             f"{_fmt(s['mean_abs_error_kwh'])} kWh."),
            "",
            PARAGRAPHS[s["scenario"]],
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(n: int = 100, seed0: int = 1, scenarios: list[str] | None = None,
         out_csv: str | Path | None = None,
         out_md: str | Path | None = None) -> dict:
    """Run the Monte Carlo and write the CSV + markdown report.

    Returns a dict with keys ``n``, ``seed0``, ``scenarios`` (per-scenario
    metric dicts), ``rows`` (per-run dicts by scenario), ``pre_equal_all``
    and ``runtime_s``.
    """
    t0 = time.time()
    names = scenarios or list(SCENARIOS)
    unknown = [s for s in names if s not in SCENARIOS]
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}; choose from {list(SCENARIOS)}")
    all_rows: dict[str, list[dict]] = {}
    for name in names:
        cfg = SCENARIOS[name]
        rows = []
        for k in range(n):
            rows.append(run_pair(seed0 + k, cfg, scenario=name))
        all_rows[name] = rows
    summaries = [summarise(name, all_rows[name]) for name in names]
    runtime_s = time.time() - t0

    command = f"python scripts/validation/monte_carlo_verify.py --n {n} --seed0 {seed0}"
    csv_path = Path(out_csv) if out_csv else REPO / "docs/validation/monte_carlo_verify.csv"
    md_path = Path(out_md) if out_md else REPO / "docs/validation/monte_carlo_verify.md"
    write_csv(csv_path, names, all_rows)
    write_md(md_path, command, summaries, runtime_s)

    print(summary_table(summaries))
    print(f"\npre-period paired-run equality held for all "
          f"{sum(len(r) for r in all_rows.values())} pairs; runtime {runtime_s:.0f} s.")
    print(f"wrote {csv_path} and {md_path}")
    return {"n": n, "seed0": seed0, "scenarios": {s["scenario"]: s for s in summaries},
            "rows": all_rows, "pre_equal_all": True, "runtime_s": runtime_s}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--scenarios", nargs="*", default=None)
    a = ap.parse_args()
    main(n=a.n, seed0=a.seed0, scenarios=a.scenarios)
