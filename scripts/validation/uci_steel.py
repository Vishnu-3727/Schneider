"""UCI Steel Industry energy analysis on REAL meter data (MEASURED, external dataset).

Dataset: UCI ML Repository id 851, Steel Industry Energy Consumption — DAEWOO
Steel, Gwangyang, South Korea, 2018, 15-minute meter data, licence CC BY 4.0.
https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption

This is a Korean steel plant, NOT an Indian SME foundry. It is used here only
to show the JouleMitra pipeline works on real meter data. Every figure in the
outputs is labelled MEASURED (external dataset), never SIMULATED.

What it does (no new models — reuses the project's own code):

- Baseline + anomaly: hourly intervals, ``services.energy.baseline``
  (``fit_baseline``/``predict``/``deviation``) and ``services.energy.anomaly``
  (``l1_flags``/``l2_flags``/``build_events``) with the defaults from
  ``apps/backend/config.py``. The dataset has NO production counts, so the
  production-normalised baseline cannot be used. Instead the project's
  non-production path is used: ``machine_type="compressor"`` with
  ``non_production_types=["pump", "compressor"]`` (the exact default of
  ``NON_PRODUCTION_TYPES``), i.e. state-hours-only features, the same approach
  the backend takes for compressor/pump machines. Load_Type maps to states:
  Light_Load -> idle, Medium_Load -> holding, Maximum_Load -> running
  (0.25 h per 15-min record). Fit on the first 8 weeks, detect on the rest.
- Power factor and kVAh: ``kVAh = sqrt(kWh^2 + kVArh_lag^2)`` per 15-min
  interval, the same formula as the console Bill screen
  (``apps/console/console.js`` ``loadBill``). Average PF = sum(kWh)/sum(kVAh).
  Capacitor need ``Q = P*(tan(phi1) - tan(phi2))`` to lift the typical
  (mean-power) PF per Load_Type to 0.95, same as ``loadBill``.
- Idle/light load: energy with ``Load_Type == Light_Load`` during non-working
  hours as a share of the year — the real-data counterpart of energy with no
  output. Non-working is defined here as ``WeekStatus == Weekend`` (any time)
  plus weekdays outside 09:00-18:00 (``NSM < 32400`` or ``NSM >= 64800``);
  a stated assumption, not a dataset field.

Usage (from the repo root)::

    .venv\\Scripts\\python scripts\\validation\\uci_steel.py

Downloads the zip with urllib into ``data/external/uci_steel/`` when the CSV
is missing, prints markdown, writes ``docs/validation/uci_steel.md`` and
``docs/validation/uci_steel_anomalies.csv``.
"""

from __future__ import annotations

import csv
import math
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from services.energy.aggregate import Interval  # noqa: F401 (re-exported for tests)
from services.energy.anomaly import build_events, l1_flags, l2_flags
from services.energy.baseline import deviation, fit_baseline, predict

DATASET_URL = (
    "https://archive.ics.uci.edu/static/public/851/steel+industry+energy+consumption.zip"
)
DATASET_CITATION = (
    "UCI Machine Learning Repository, Steel Industry Energy Consumption "
    "(id 851), DAEWOO Steel, Gwangyang, South Korea, 2018, 15-minute data."
)
DATASET_LICENCE = "CC BY 4.0"
DATA_DIR = REPO / "data" / "external" / "uci_steel"
CSV_NAME = "Steel_industry_data.csv"
MACHINE_ID = "steel-plant-01"

# Thresholds: defaults copied from apps/backend/config.py (do not import the
# backend config here; it reads .env, which this task must not touch).
DEVIATION_WARN_PCT = 15.0
DEVIATION_CRIT_PCT = 30.0
DEVIATION_CONSECUTIVE_N = 2
IDLE_SHARE_THRESHOLD = 0.5
IDLE_CONSECUTIVE_N = 4
RATED_POWER_MULTIPLE = 1.1
PF_MIN_THRESHOLD = 0.6
MAD_THRESHOLD = 4.0
MAD_WINDOW = 24
EXPECTED_EPSILON_KWH = 0.5
MIN_BASELINE_INTERVALS = 24
BASELINE_HOLDOUT_FRACTION = 0.2
G14_CV_MAX_PCT = 30.0
G14_NMBE_MAX_PCT = 10.0
NON_PRODUCTION_TYPES = ["pump", "compressor"]
MACHINE_TYPE = "compressor"  # non-production path: state-hours-only features
FIT_WEEKS = 8
ILLUSTRATIVE_TARIFF_INR_PER_KWH = 7.5

DATE_FMT = "%d/%m/%Y %H:%M"

LOAD_TO_STATE = {
    "Light_Load": "idle",
    "Medium_Load": "holding",
    "Maximum_Load": "running",
}

ALL_STATES = [
    "heating",
    "melting",
    "holding",
    "idle",
    "running",
    "stopped",
    "shutdown",
    "auxiliary",
]


def kvah_from_kwh_kvarh(kwh: float, kvarh: float) -> float:
    """Apparent energy per interval (same formula as console loadBill)."""
    return math.sqrt(kwh * kwh + kvarh * kvarh)


def pf_from_kwh_kvah(kwh: float, kvah: float) -> float | None:
    """Power factor kWh/kVAh; None when kVAh is zero."""
    if kvah <= 0:
        return None
    return kwh / kvah


def capacitor_kvar_for_target(p_kw: float, pf_before: float, pf_target: float = 0.95) -> float:
    """Capacitor kVAr to lift pf_before to pf_target: P*(tan(phi1)-tan(phi2))."""
    if p_kw <= 0 or pf_before <= 0 or pf_before >= 1 or pf_target <= 0 or pf_target >= 1:
        return 0.0
    if pf_before >= pf_target:
        return 0.0
    need = p_kw * (math.tan(math.acos(pf_before)) - math.tan(math.acos(pf_target)))
    return max(0.0, need)


def load_type_to_state(load_type: str) -> str:
    """Map UCI Load_Type to a project state-hour bucket."""
    return LOAD_TO_STATE[load_type]


def parse_steel_rows(raw_rows: list[dict]) -> list[dict]:
    """Parse raw CSV dicts (strings) into typed records.

    Expects keys: date, Usage_kWh, Lagging_Current_Reactive.Power_kVarh,
    WeekStatus, NSM, Load_Type. Raises KeyError/ValueError on bad input.
    """
    out = []
    for r in raw_rows:
        out.append(
            {
                # Dataset timestamps are local wall time (Gwangyang, 2018);
                # no UTC offset is published, so they stay naive.
                "dt": datetime.strptime(r["date"], DATE_FMT),  # noqa: DTZ007
                "kwh": float(r["Usage_kWh"]),
                "kvarh_lag": float(r["Lagging_Current_Reactive.Power_kVarh"]),
                "weekstatus": r["WeekStatus"],
                "nsm": int(float(r["NSM"])),
                "load_type": r["Load_Type"],
            }
        )
    return out


def aggregate_hourly(parsed: list[dict]) -> list[dict]:
    """Aggregate 15-min records to hourly buckets for the baseline.

    Each record contributes 0.25 h to its Load_Type state. Returns one dict
    per hour with window_start, energy_kwh, kvarh_lag, kvah, pf, pmax_kw,
    hours_by_state (full 8-state dict), n_quarters.
    """
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for r in parsed:
        hk = r["dt"].replace(minute=0, second=0, microsecond=0)
        buckets[hk].append(r)
    hours = []
    for hk in sorted(buckets):
        rs = buckets[hk]
        energy = sum(r["kwh"] for r in rs)
        kvarh = sum(r["kvarh_lag"] for r in rs)
        kvah = kvah_from_kwh_kvarh(energy, kvarh)
        pf = pf_from_kwh_kvah(energy, kvah)
        powers = [r["kwh"] / 0.25 for r in rs]
        pmax = max(powers) if powers else None
        hbs = {s: 0.0 for s in ALL_STATES}
        for r in rs:
            hbs[load_type_to_state(r["load_type"])] += 0.25
        hours.append(
            {
                "window_start": hk,
                "energy_kwh": energy,
                "kvarh_lag": kvarh,
                "kvah": kvah,
                "pf": pf,
                "pmax_kw": pmax,
                "hours_by_state": hbs,
                "n_quarters": len(rs),
            }
        )
    return hours


def is_non_working(weekstatus: str, nsm: int) -> bool:
    """Stated assumption: Weekend any time, else outside 09:00-18:00."""
    if weekstatus == "Weekend":
        return True
    return nsm < 9 * 3600 or nsm >= 18 * 3600


def ensure_dataset() -> Path:
    """Download + extract the UCI zip when the CSV is missing; return CSV path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / CSV_NAME
    if csv_path.exists():
        return csv_path
    zip_path = DATA_DIR / "steel_industry_energy_consumption.zip"
    urllib.request.urlretrieve(DATASET_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(DATA_DIR)
    if not csv_path.exists():
        found = sorted(DATA_DIR.glob("*.csv"))
        if not found:
            raise FileNotFoundError(f"CSV not found after extracting {zip_path}")
        found[0].rename(csv_path)
    return csv_path


def _fmt(x: float | None, nd: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.{nd}f}"


def run_analysis(csv_path: Path | None = None) -> dict:
    """Run the full analysis; write md + anomalies CSV; return results dict."""
    path = csv_path or ensure_dataset()
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw = list(csv.DictReader(f))
    parsed = parse_steel_rows(raw)

    # --- Annual kVAh/PF (per 15-min interval, console formula) ---
    annual_kwh = sum(r["kwh"] for r in parsed)
    annual_kvah = sum(kvah_from_kwh_kvarh(r["kwh"], r["kvarh_lag"]) for r in parsed)
    annual_pf = annual_kwh / annual_kvah if annual_kvah else None
    gap_kwh = annual_kvah - annual_kwh
    gap_inr = gap_kwh * ILLUSTRATIVE_TARIFF_INR_PER_KWH

    # --- Typical power per Load_Type (mean-power, console style) ---
    cap_rows = []
    for lt in ("Light_Load", "Medium_Load", "Maximum_Load"):
        sub = [r for r in parsed if r["load_type"] == lt]
        p_mean = sum(r["kwh"] for r in sub) / len(sub) / 0.25
        q_mean = sum(r["kvarh_lag"] for r in sub) / len(sub) / 0.25
        pf_typ = p_mean / math.sqrt(p_mean * p_mean + q_mean * q_mean)
        need = capacitor_kvar_for_target(p_mean, pf_typ, 0.95)
        cap_rows.append(
            {
                "load_type": lt,
                "n": len(sub),
                "p_kw": p_mean,
                "q_kvar": q_mean,
                "pf": pf_typ,
                "need_kvar": need,
            }
        )

    # --- Idle/light load during non-working hours ---
    idle_kwh = sum(r["kwh"] for r in parsed if r["load_type"] == "Light_Load" and is_non_working(
        r["weekstatus"], r["nsm"]))
    idle_share = idle_kwh / annual_kwh * 100.0 if annual_kwh else None

    # --- Hourly baseline + anomaly (project services, non-production path) ---
    hours = aggregate_hourly(parsed)
    n_fit = FIT_WEEKS * 7 * 24
    fit_hours = hours[:n_fit]
    test_hours = hours[n_fit:]

    class _IV:
        __slots__ = (
            "complete",
            "energy_kwh",
            "good_production_kg",
            "hours_by_state",
            "window_start",
        )

        def __init__(self, h: dict):
            self.window_start = h["window_start"]
            self.complete = True
            self.energy_kwh = h["energy_kwh"]
            self.hours_by_state = h["hours_by_state"]
            self.good_production_kg = None

    fit_intervals = [_IV(h) for h in fit_hours]
    res = fit_baseline(
        fit_intervals,  # type: ignore[arg-type]
        MACHINE_TYPE,
        NON_PRODUCTION_TYPES,
        MIN_BASELINE_INTERVALS,
        BASELINE_HOLDOUT_FRACTION,
        G14_CV_MAX_PCT,
        G14_NMBE_MAX_PCT,
    )

    scored = []
    for h in test_hours:
        exp = predict(res.features, res.coefficients, res.intercept,
                      h["hours_by_state"], None)
        dev = deviation(h["energy_kwh"], exp, EXPECTED_EPSILON_KWH)
        scored.append(
            {
                "complete": True,
                "actual_kwh": h["energy_kwh"],
                "expected_kwh": dev.expected_kwh,
                "deviation_kwh": dev.deviation_kwh,
                "deviation_pct": dev.deviation_pct,
                "hours_by_state": h["hours_by_state"],
                "good_production_kg": None,
                "power_max_kw": h["pmax_kw"],
                "pf_mean": h["pf"],
            }
        )
    # No rated power in the dataset, so the L1_POWER rule is disabled
    # (rated_power_kw=0 never fires); all other rules use config defaults.
    flags = l1_flags(
        scored,
        DEVIATION_WARN_PCT,
        DEVIATION_CRIT_PCT,
        DEVIATION_CONSECUTIVE_N,
        IDLE_SHARE_THRESHOLD,
        0.0,
        RATED_POWER_MULTIPLE,
        PF_MIN_THRESHOLD,
        IDLE_CONSECUTIVE_N,
    )
    flags += l2_flags(scored, MAD_THRESHOLD, MAD_WINDOW, DEVIATION_WARN_PCT)
    starts = [h["window_start"] for h in test_hours]
    events = build_events(MACHINE_ID, scored, starts, starts, flags)

    by_rule: dict[str, int] = defaultdict(int)
    for ev in events:
        by_rule[ev["rule_id"]] += 1
    top5 = sorted(events, key=lambda e: abs(e["deviation_pct"] or 0.0),
                  reverse=True)[:5]

    # --- Write anomalies CSV ---
    out_csv = REPO / "docs" / "validation" / "uci_steel_anomalies.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "machine_id",
                "window_start",
                "window_end",
                "rule_id",
                "severity",
                "expected_kwh",
                "actual_kwh",
                "deviation_pct",
            ],
        )
        w.writeheader()
        for ev in sorted(events, key=lambda e: str(e["window_start"])):
            w.writerow(
                {
                    "machine_id": ev["machine_id"],
                    "window_start": ev["window_start"].isoformat()
                    if hasattr(ev["window_start"], "isoformat")
                    else ev["window_start"],
                    "window_end": ev["window_end"].isoformat()
                    if hasattr(ev["window_end"], "isoformat")
                    else ev["window_end"],
                    "rule_id": ev["rule_id"],
                    "severity": ev["severity"],
                    "expected_kwh": ev["expected_kwh"],
                    "actual_kwh": ev["actual_kwh"],
                    "deviation_pct": ev["deviation_pct"],
                }
            )

    # --- Markdown report ---
    fit_end = fit_hours[-1]["window_start"] if fit_hours else None
    test_start = test_hours[0]["window_start"] if test_hours else None
    test_end = test_hours[-1]["window_start"] if test_hours else None
    lines = [
        "# UCI Steel Industry — real meter data (external dataset; MEASURED readings + DERIVED calculations)",
        "",
        (
            "Raw meter readings are MEASURED from an external dataset, never "
            "SIMULATED. Anything computed from them with a method or "
            "assumption is DERIVED. MEASURED here means only: annual kWh, "
            "kVAh sum, per-interval power factor, and energy by Load_Type. "
            "DERIVED means: average power factor, the kVAh-billing gap, the "
            "capacitor kVAr, the rupee figure (illustrative tariff), the "
            "non-working-hours share (stated working-hours assumption), the "
            "baseline, and every anomaly count. Dataset: "
        ),
        "",
        f"- Citation: {DATASET_CITATION}",
        "- Licence: CC BY 4.0.",
        "- Source: "
        + "https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption",
        "- Plant: DAEWOO Steel, Gwangyang, South Korea, year 2018, 15-minute "
        + "meter readings (35,040 rows = 8,760 hourly intervals).",
        "- This is a Korean steel plant, NOT an Indian SME foundry. It is used "
        + "only to show the JouleMitra pipeline runs end to end on real meter data.",
        "",
        (
            "Solid results first: power factor, the kVAh gap, capacitor "
            "sizing, and the light-load-outside-hours share. The baseline "
            "and anomaly counts below are DERIVED and are NOT a detection "
            "result — see the caveat above the counts table."
        ),
        "",
        "## Annual energy and power factor (external dataset; MEASURED + DERIVED)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Annual kWh (MEASURED) | {_fmt(annual_kwh, 0)} |",
        f"| Annual kVAh sum (MEASURED) | {_fmt(annual_kvah, 0)} |",
        f"| Average PF = kWh/kVAh (DERIVED) | {annual_pf:.3f} |" if annual_pf else "| Average PF (DERIVED) | n/a |",
        f"| kVAh-billing gap (DERIVED) | {_fmt(gap_kwh, 0)} kWh |",
        f"| Gap at illustrative Rs 7.5/kWh (DERIVED, illustrative tariff) | Rs {_fmt(gap_inr, 0)} |",
        "",
        (
            "The plant metered about 959,637 kWh (MEASURED) and about "
            "1,087,756 kVAh in total (MEASURED), so the average power factor "
            "is about 0.882 (DERIVED) and the kVAh-billing gap is about "
            "128,119 kWh (DERIVED), roughly Rs 960,893 at the illustrative "
            "Rs 7.5/kWh tariff (DERIVED, illustrative only, not a real tariff order)."
        ),
        "",
        "## Capacitor need per load type (DERIVED, external dataset)",
        "",
        "| Load_Type (MEASURED dataset field) | N (15-min) (MEASURED) | Typical P kW (DERIVED) | Typical Q kVAr (DERIVED) | "
        + "Typical PF (DERIVED) | kVAr to 0.95 (DERIVED) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for c in cap_rows:
        lines.append(
            f"| {c['load_type']} | {c['n']:,} | {_fmt(c['p_kw'])} "
            f"| {_fmt(c['q_kvar'])} | {c['pf']:.3f} | {_fmt(c['need_kvar'])} |"
        )
    lines += [
        "",
        (
            "Typical means mean power over 15-minute intervals of that "
            "Load_Type (DERIVED), the same mean-power method as the console "
            "Bill screen. "
            "Light-load power factor is the worst (about 0.776, needing about "
            "16.7 kVAr), Maximum-load needs about 26.8 kVAr despite a better "
            "power factor (about 0.915) because its absolute reactive power is "
            "larger, and Medium-load needs about 7.1 kVAr (power factor about "
            "0.936). All kVAr figures are DERIVED."
        ),
        "",
        "## Idle / light load in non-working hours (DERIVED, external dataset; stated assumption)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Light_Load during non-working hours (DERIVED) | {_fmt(idle_kwh, 0)} kWh |",
        f"| Share of annual kWh (DERIVED) | {idle_share:.1f} % |" if idle_share else "| Share (DERIVED) | n/a |",
        "",
        (
            "Non-working is a stated assumption, not a dataset field: "
            "WeekStatus == Weekend at any time, plus weekdays outside "
            "09:00-18:00 (NSM < 32400 or NSM >= 64800). About 135,387 kWh "
            "(DERIVED), "
            "about 14.1 % of the year (DERIVED), is Light_Load energy inside those "
            "hours — the real-data counterpart of energy spent with no "
            "output. Change the working-hours assumption and this share moves."
        ),
        "",
        "## Baseline and anomaly detection (DERIVED, external dataset)",
        "",
        (
            "Method: hourly intervals with the project's own services "
            "(services.energy.baseline fit_baseline/predict/deviation and "
            "services.energy.anomaly l1_flags/l2_flags/build_events) using "
            "the defaults from apps/backend/config.py. The dataset has no "
            "production counts, so the production-normalised baseline cannot "
            "be used; instead the non-production path is used, exactly as the "
            "backend does for compressor/pump machines: machine_type "
            '"compressor" with non_production_types ["pump", "compressor"] '
            "(the NON_PRODUCTION_TYPES default), i.e. state-hours-only "
            "features. Load_Type maps to states Light->idle, Medium->holding, "
            "Maximum->running (0.25 h per 15-min record). No rated power is "
            "published, so the L1_POWER rule is disabled (rated 0 never "
            "fires); every other rule uses the config defaults."
        ),
        "",
        f"- Fit window (MEASURED intervals): first {FIT_WEEKS} weeks "
        f"({len(fit_hours)} hourly intervals"
        + (f", ending {fit_end.isoformat()}" if fit_end else "")
        + ").",
        f"- Detect window (MEASURED intervals): rest of the year ({len(test_hours)} hourly intervals"
        + (f", {test_start.isoformat()} to {test_end.isoformat()}" if test_start else "")
        + ").",
        (
            f"- Baseline fit (DERIVED): {res.status}; features {res.features}; "
            f"intercept {_fmt(res.intercept)}; CV(RMSE) holdout "
            f"{_fmt(res.cv_rmse_pct_holdout)} %; NMBE holdout {_fmt(res.nmbe_pct_holdout)} %; "
            f"acceptance {res.acceptance} (ASHRAE G14 hourly)."
        ),
        "",
        (
            "What this proves is only that the pipeline ran end to end on "
            "real meter data. The anomaly counts below are NOT a detection "
            "result, for three reasons: (1) the baseline failed its own "
            "quality check — G14 NOT_ACCEPTABLE with CV(RMSE) 67.3 %; "
            "(2) L1_IDLE_WASTE fires nightly only because this dataset has "
            "no production counts, so every sustained Light_Load stretch "
            "looks like energy with no output; (3) the largest events are "
            "all 08:00 shift starts, which the state-hours-only baseline "
            "cannot model. Lesson: for plants without production data the "
            "baseline needs a time-of-day / shift driver — listed as future "
            "work below. Counts are kept for transparency, not as findings."
        ),
        "",
        "| Rule (DERIVED) | Events (DERIVED, NOT a finding) |",
        "|---|---:|",
    ]
    for rule in ("L1_DEVIATION", "L1_IDLE_WASTE", "L1_POWER_FACTOR",
                 "L2_MAD_RESIDUAL", "L1_POWER"):
        lines.append(f"| {rule} | {by_rule.get(rule, 0)} |")
    lines += [
        f"| Total (DERIVED, NOT a finding) | {len(events)} |",
        "",
        (
            "Why the baseline fails: energy varies widely inside a Load_Type "
            "— for example Light_Load nights are usually about 10-15 kWh per "
            "hour but transition hours labelled Light_Load reach hundreds of "
            "kWh, and Maximum_Load labels sometimes coincide with single-digit "
            "kWh. That is the same limitation the project documents for the "
            "compressor: without a production or demand driver the baseline "
            "detects level shifts but cannot tell legitimate demand growth "
            "from waste."
        ),
        "",
        "### 5 largest anomaly events by |deviation| (DERIVED, NOT a finding; external dataset)",
        "",
        "| # | Start (DERIVED) | Rule (DERIVED) | Actual kWh (MEASURED) | Expected kWh (DERIVED) | Deviation % (DERIVED) |",
        "|---|---|---|---:|---:|---:|",
    ]
    for i, ev in enumerate(top5, 1):
        ws = ev["window_start"].isoformat() if hasattr(ev["window_start"], "isoformat") else ev["window_start"]
        lines.append(
            f"| {i} | {ws} | {ev['rule_id']} | {_fmt(ev['actual_kwh'])} "
            f"| {_fmt(ev['expected_kwh'])} | {ev['deviation_pct']:+.1f} % |"
        )
    lines += [
        "",
        (
            "The largest deviations are all Light-labelled 08:00 morning "
            "shift starts consuming several hundred kWh against an expected "
            "few dozen — the Load_Type label says light while the meter "
            "says heavy. These are DERIVED artefacts of a state-hours-only "
            "baseline with no time-of-day driver, not confirmed waste. "
            "Under-consumption (Maximum label with "
            "single-digit kWh) never flags by design: only excess energy is "
            "waste."
        ),
        "",
        (
            "Future work: add a time-of-day / shift driver to the baseline "
            "for plants without production data, so shift starts are "
            "expected instead of anomalous."
        ),
        "",
        "Per-event rows: `docs/validation/uci_steel_anomalies.csv`.",
        "",
    ]
    md = "\n".join(lines)
    out_md = REPO / "docs" / "validation" / "uci_steel.md"
    out_md.write_text(md, encoding="utf-8")

    return {
        "annual_kwh": annual_kwh,
        "annual_kvah": annual_kvah,
        "annual_pf": annual_pf,
        "gap_kwh": gap_kwh,
        "gap_inr": gap_inr,
        "cap_rows": cap_rows,
        "idle_kwh": idle_kwh,
        "idle_share": idle_share,
        "baseline_status": res.status,
        "baseline_acceptance": res.acceptance,
        "n_fit": len(fit_hours),
        "n_test": len(test_hours),
        "events_by_rule": dict(by_rule),
        "n_events": len(events),
        "top5": top5,
        "markdown": md,
    }


def main() -> dict:
    """Download (if missing), analyse, print markdown, write outputs."""
    result = run_analysis()
    print(result["markdown"])
    print(f"\nwrote {REPO / 'docs' / 'validation' / 'uci_steel.md'} and "
          f"{REPO / 'docs' / 'validation' / 'uci_steel_anomalies.csv'}")
    return result


if __name__ == "__main__":
    main()
