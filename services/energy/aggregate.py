"""Fixed-interval aggregation over stored telemetry + production (pure, no DB).

One Interval per (machine, window). Built from GOOD telemetry rows only:
energy_kwh is the delta of the cumulative counter, state hours are allocated
proportionally, production is joined on window_start.

An interval is marked INCOMPLETE (never silently dropped) when:
  - it contains any BAD-quality telemetry row, or
  - duration coverage of GOOD rows is below the configured minimum, or
  - energy cannot be computed (< 2 GOOD rows with a cumulative counter).
Incomplete intervals are excluded from baseline fitting and anomaly scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Interval:
    machine_id: str
    window_start: datetime
    window_end: datetime
    complete: bool
    incomplete_reasons: list[str] = field(default_factory=list)
    energy_kwh: float | None = None
    hours_by_state: dict[str, float] = field(default_factory=dict)
    n_good: int = 0
    n_bad: int = 0
    coverage_pct: float = 0.0
    good_production_kg: float | None = None
    rejected_production_kg: float = 0.0
    has_production_record: bool = False
    power_max_kw: float | None = None
    power_mean_kw: float | None = None
    pf_mean: float | None = None


def _bucket_index(ts: datetime, anchor: datetime, interval_s: int) -> int:
    return int((ts - anchor).total_seconds() // interval_s)


def build_intervals(
    machine_id: str,
    telemetry_rows: list[dict],
    production_rows: list[dict],
    start: datetime,
    end: datetime,
    interval_s: int,
    min_coverage_pct: float,
) -> list[Interval]:
    """Bucket rows into fixed windows [start + k*interval_s, ...).

    telemetry_rows: dicts with ts, quality, energy_kwh, machine_state,
      power_kw, power_factor. production_rows: dicts with window_start,
      quality, qty_good_kg, qty_rejected_kg. All datetimes tz-aware.
    """
    n = max(0, int((end - start).total_seconds() // interval_s))
    buckets: list[list[dict]] = [[] for _ in range(n)]
    bad_in_bucket = [0] * n
    for r in telemetry_rows:
        ts = r["ts"]
        if not (start <= ts < end):
            continue
        k = _bucket_index(ts, start, interval_s)
        if 0 <= k < n:
            if r.get("quality") == "BAD":
                bad_in_bucket[k] += 1
            elif r.get("quality") == "GOOD":
                buckets[k].append(r)
            # SUSPECT rows are excluded from the math but do not fail the interval.

    prod_by_bucket: dict[int, list[dict]] = {}
    for p in production_rows:
        ws = p["window_start"]
        if not (start <= ws < end):
            continue
        k = _bucket_index(ws, start, interval_s)
        if 0 <= k < n and p.get("quality") == "GOOD":
            prod_by_bucket.setdefault(k, []).append(p)

    out: list[Interval] = []
    interval_h = interval_s / 3600.0
    for k in range(n):
        ws = start + timedelta(seconds=k * interval_s)
        we = ws + timedelta(seconds=interval_s)
        rows = sorted(buckets[k], key=lambda r: r["ts"])
        iv = Interval(machine_id=machine_id, window_start=ws, window_end=we,
                      complete=True, n_bad=bad_in_bucket[k])
        reasons: list[str] = []
        if bad_in_bucket[k] > 0:
            reasons.append(f"contains {bad_in_bucket[k]} BAD-quality row(s)")
        iv.n_good = len(rows)
        if rows:
            span_s = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() if len(rows) > 1 else 0.0
            iv.coverage_pct = round(min(100.0, span_s / interval_s * 100.0), 2)
        if iv.coverage_pct < min_coverage_pct:
            reasons.append(
                f"coverage {iv.coverage_pct}% below minimum {min_coverage_pct}%"
            )
        energies = [r["energy_kwh"] for r in rows if r.get("energy_kwh") is not None]
        if len(energies) >= 2:
            iv.energy_kwh = max(energies) - min(energies)
        else:
            reasons.append("cumulative energy counter unavailable (< 2 GOOD readings)")
        if rows:
            counts: dict[str, int] = {}
            for r in rows:
                st = r.get("machine_state") or "unknown"
                counts[st] = counts.get(st, 0) + 1
            iv.hours_by_state = {s: round(c / len(rows) * interval_h, 4) for s, c in counts.items()}
            powers = [r["power_kw"] for r in rows if r.get("power_kw") is not None]
            if powers:
                iv.power_max_kw = max(powers)
                iv.power_mean_kw = sum(powers) / len(powers)
            pfs = [r["power_factor"] for r in rows if r.get("power_factor") is not None]
            if pfs:
                iv.pf_mean = sum(pfs) / len(pfs)
        prods = prod_by_bucket.get(k, [])
        if prods:
            iv.has_production_record = True
            iv.good_production_kg = sum(p["qty_good_kg"] for p in prods)
            iv.rejected_production_kg = sum(p["qty_rejected_kg"] for p in prods)
        if reasons:
            iv.complete = False
            iv.incomplete_reasons = reasons
        out.append(iv)
    return out
