"""Process efficiency: what consumes energy without useful production? (pure)

Per machine per day, from GOOD telemetry (state samples) and Phase-2
intervals: hours by state, idle/holding hours, non-productive kWh and share,
start/stop count, the gap between consecutive furnace heats, and holding
time per heat vs the configured minimum needed for pouring.

Every finding carries metric, value, reference (the NORMAL median from the
baseline window when available), evidence and source DERIVED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

SOURCE = "DERIVED"

#: States that count as "the machine is energised but producing nothing".
NON_PRODUCTIVE_STATES = ("idle", "holding", "stopped", "shutdown", "auxiliary")


@dataclass
class DayMetrics:
    machine_id: str
    day: str  # ISO date
    hours_by_state: dict[str, float] = field(default_factory=dict)
    idle_hours: float = 0.0
    holding_hours: float = 0.0
    energy_kwh: float | None = None
    non_productive_kwh: float = 0.0
    non_productive_share: float | None = None
    heat_count: int = 0  # furnace heating starts (heats); 0 for other types
    start_count: int = 0  # energised starts (any type)
    median_heat_gap_h: float | None = None
    holding_per_heat_h: float | None = None


@dataclass
class Finding:
    metric: str
    value: float | None
    unit: str
    reference: float | None
    reference_source: str
    evidence: str
    above_reference: bool | None = None
    source: str = SOURCE


def _productive(state: str) -> bool:
    return state not in NON_PRODUCTIVE_STATES


def daily_metrics(
    machine_id: str,
    machine_type: str,
    intervals,
    state_samples: list[tuple[datetime, str]],
    local_tz: str = "Asia/Kolkata",
) -> list[DayMetrics]:
    """Aggregate one DayMetrics per local calendar day.

    intervals: Phase-2 Interval objects (complete ones contribute energy
      and state hours). state_samples: ordered (ts, state) GOOD samples.
      Days are local calendar days in local_tz (DB timestamps arrive in
      UTC; naive .date() would split days at the wrong midnight).
    """
    tz = ZoneInfo(local_tz)
    by_day: dict[str, DayMetrics] = {}

    def _day(key: str) -> DayMetrics:
        if key not in by_day:
            by_day[key] = DayMetrics(machine_id=machine_id, day=key)
        return by_day[key]

    for iv in intervals:
        if not iv.complete:
            continue
        d = _day(iv.window_start.astimezone(tz).date().isoformat())
        for s, h in (iv.hours_by_state or {}).items():
            d.hours_by_state[s] = d.hours_by_state.get(s, 0.0) + float(h or 0.0)
        if iv.energy_kwh is not None:
            d.energy_kwh = (d.energy_kwh or 0.0) + float(iv.energy_kwh)
            if (iv.good_production_kg or 0.0) <= 0:
                d.non_productive_kwh += float(iv.energy_kwh)
    for d in by_day.values():
        d.idle_hours = d.hours_by_state.get("idle", 0.0)
        d.holding_hours = d.hours_by_state.get("holding", 0.0)
        if d.energy_kwh and d.energy_kwh > 0:
            d.non_productive_share = d.non_productive_kwh / d.energy_kwh

    # Transition-level metrics from the ordered state samples.
    starts_by_day: dict[str, list[datetime]] = {}
    heat_starts_by_day: dict[str, list[datetime]] = {}
    prev: str | None = None
    for ts, state in sorted(state_samples, key=lambda x: x[0]):
        key = ts.astimezone(tz).date().isoformat()
        _day(key)  # ensure the day exists even with no complete intervals
        if prev is not None and state != prev:
            if _productive(state) and not _productive(prev):
                starts_by_day.setdefault(key, []).append(ts)
            if machine_type == "furnace" and state == "holding" and prev == "melting":
                pass  # pour boundary, not a start; ignored
            if machine_type == "furnace" and state == "heating" and prev != "heating":
                heat_starts_by_day.setdefault(key, []).append(ts)
        prev = state
    for key, d in by_day.items():
        d.start_count = len(starts_by_day.get(key, []))
        heats = heat_starts_by_day.get(key, [])
        d.heat_count = len(heats)
        if len(heats) >= 2:
            gaps = [
                (b - a).total_seconds() / 3600.0
                for a, b in zip(heats, heats[1:])
            ]
            gaps.sort()
            mid = len(gaps) // 2
            d.median_heat_gap_h = (
                gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
            )
        if machine_type == "furnace" and d.heat_count > 0:
            d.holding_per_heat_h = d.holding_hours / d.heat_count
    return [by_day[k] for k in sorted(by_day)]


def reference_medians(daily: list[DayMetrics]) -> dict[str, float | None]:
    """NORMAL median per metric over reference-window daily values."""

    def _med(vals: list[float]) -> float | None:
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0

    return {
        "idle_hours": _med([d.idle_hours for d in daily]),
        "holding_per_heat_h": _med(
            [d.holding_per_heat_h for d in daily if d.holding_per_heat_h is not None]
        ),
        "non_productive_share": _med(
            [d.non_productive_share for d in daily if d.non_productive_share is not None]
        ),
        "start_count": _med([float(d.start_count) for d in daily]),
        "median_heat_gap_h": _med(
            [d.median_heat_gap_h for d in daily if d.median_heat_gap_h is not None]
        ),
        "heat_count": _med([float(d.heat_count) for d in daily]),
    }


def analyze(
    machine_id: str,
    machine_type: str,
    intervals,
    state_samples: list[tuple[datetime, str]],
    ref_daily: list[DayMetrics] | None,
    min_hold_h: float,
    local_tz: str = "Asia/Kolkata",
) -> list[dict]:
    """Per-day metrics + findings. ref_daily: NORMAL-window daily metrics.

    (None/empty -> findings carry reference None and say so in evidence.)
    """
    ref = reference_medians(ref_daily or [])
    ref_note = (
        "NORMAL median from the baseline window"
        if (ref_daily)
        else "no NORMAL reference available"
    )
    out = []
    for d in daily_metrics(machine_id, machine_type, intervals, state_samples,
                           local_tz):
        if machine_type == "furnace":
            hold_value: float | None = d.holding_per_heat_h
            hold_ref: float | None = min_hold_h
            hold_ref_source = "config PROCESS_MIN_HOLD_H (minimum needed for pouring)"
            hold_unit = "h_per_heat"
        else:
            hold_value = d.holding_hours
            hold_ref = None
            hold_ref_source = ref_note
            hold_unit = "h"
        findings = [
            Finding(
                metric="idle_hours",
                value=round(d.idle_hours, 3),
                unit="h",
                reference=ref["idle_hours"],
                reference_source=ref_note,
                evidence=(
                    f"{d.idle_hours:.2f} h idle on {d.day}"
                    + (f" vs NORMAL median {ref['idle_hours']:.2f} h"
                       if ref["idle_hours"] is not None else " (no NORMAL reference)")
                ),
                above_reference=(
                    d.idle_hours > ref["idle_hours"]
                    if ref["idle_hours"] is not None else None
                ),
            ),
            Finding(
                metric="holding_hours_per_heat",
                value=round(hold_value, 3) if hold_value is not None else None,
                unit=hold_unit,
                reference=hold_ref,
                reference_source=hold_ref_source,
                evidence=(
                    f"{(hold_value or 0.0):.2f} {hold_unit} holding on {d.day}"
                    + (f" vs minimum {hold_ref:.2f} h needed for pouring"
                       if machine_type == "furnace" and hold_ref is not None
                       else (" (no holding observed)" if hold_value is None
                             else f" vs NORMAL median {(hold_ref or 0.0):.2f} h"))
                ),
                above_reference=(
                    hold_value > hold_ref
                    if hold_value is not None and hold_ref is not None else None
                ),
            ),
            Finding(
                metric="non_productive_share",
                value=(round(d.non_productive_share, 4)
                       if d.non_productive_share is not None else None),
                unit="fraction",
                reference=ref["non_productive_share"],
                reference_source=ref_note,
                evidence=(
                    f"{d.non_productive_kwh:.1f} kWh of "
                    f"{(d.energy_kwh or 0.0):.1f} kWh spent with zero good production "
                    f"on {d.day}"
                    + (f" vs NORMAL median share {ref['non_productive_share']:.3f}"
                       if ref["non_productive_share"] is not None
                       else " (no NORMAL reference)")
                ),
                above_reference=(
                    d.non_productive_share > ref["non_productive_share"]
                    if d.non_productive_share is not None
                    and ref["non_productive_share"] is not None else None
                ),
            ),
            Finding(
                metric="start_count",
                value=float(d.start_count),
                unit="count",
                reference=ref["start_count"],
                reference_source=ref_note,
                evidence=(
                    f"{d.start_count} energised start(s) on {d.day}"
                    + (f" vs NORMAL median {ref['start_count']:.1f}"
                       if ref["start_count"] is not None else " (no NORMAL reference)")
                ),
                above_reference=(
                    d.start_count > ref["start_count"]
                    if ref["start_count"] is not None else None
                ),
            ),
            Finding(
                metric="median_heat_gap_h",
                value=(round(d.median_heat_gap_h, 3)
                       if d.median_heat_gap_h is not None else None),
                unit="h",
                reference=ref["median_heat_gap_h"],
                reference_source=ref_note,
                evidence=(
                    f"median {d.median_heat_gap_h:.2f} h between consecutive heats "
                    f"on {d.day}"
                    if d.median_heat_gap_h is not None
                    else f"fewer than 2 heats on {d.day}; gap not computable"
                )
                + (f" vs NORMAL median {ref['median_heat_gap_h']:.2f} h"
                   if ref["median_heat_gap_h"] is not None else " (no NORMAL reference)"),
                above_reference=(
                    d.median_heat_gap_h > ref["median_heat_gap_h"]
                    if d.median_heat_gap_h is not None
                    and ref["median_heat_gap_h"] is not None else None
                ),
            ),
        ]
        out.append({
            "machine_id": d.machine_id,
            "day": d.day,
            "hours_by_state": {k: round(v, 4) for k, v in d.hours_by_state.items()},
            "idle_hours": round(d.idle_hours, 3),
            "holding_hours": round(d.holding_hours, 3),
            "non_productive_kwh": round(d.non_productive_kwh, 3),
            "non_productive_share": d.non_productive_share,
            "heat_count": d.heat_count,
            "start_count": d.start_count,
            "median_heat_gap_h": d.median_heat_gap_h,
            "holding_per_heat_h": d.holding_per_heat_h,
            "findings": [f.__dict__ for f in findings],
            "source": SOURCE,
        })
    return out
