"""Phase 1 ingestion validation — pure functions, no DB, no I/O.

Each rule returns a quality verdict per record:
  GOOD    — no problems found.
  SUSPECT — usable but questionable (stale, out-of-order, spike).
  BAD     — stored but flagged, never silently accepted (impossible values,
            decreasing cumulative energy, future timestamp).

Duplicates are detected by the API layer via the (machine_id, ts) UNIQUE
constraint; a helper is provided for unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ValidationResult:
    quality: str  # GOOD | SUSPECT | BAD
    reasons: list[str] = field(default_factory=list)


def check_impossible_telemetry(
    voltage_v: float | None,
    current_a: float | None,
    power_kw: float | None,
    power_factor: float | None,
) -> list[str]:
    reasons: list[str] = []
    if voltage_v is not None and voltage_v < 0:
        reasons.append("impossible: voltage_v < 0")
    if current_a is not None and current_a < 0:
        reasons.append("impossible: current_a < 0")
    if power_kw is not None and power_kw < 0:
        reasons.append("impossible: power_kw < 0")
    if power_factor is not None and not (0.0 <= power_factor <= 1.0):
        reasons.append("impossible: power_factor outside 0..1")
    return reasons


def check_future_ts(ts: datetime, now: datetime, clock_skew_s: int) -> list[str]:
    if ts > now + timedelta_seconds(clock_skew_s):
        return [f"BAD: ts in future beyond {clock_skew_s}s clock-skew tolerance"]
    return []


def timedelta_seconds(s: int):
    from datetime import timedelta

    return timedelta(seconds=s)


def check_stale_ts(ts: datetime, now: datetime, stale_after_s: int) -> list[str]:
    if (now - ts).total_seconds() > stale_after_s:
        return [f"SUSPECT: stale ts older than {stale_after_s}s threshold"]
    return []


def check_out_of_order(ts: datetime, last_ts: datetime | None) -> list[str]:
    if last_ts is not None and ts <= last_ts:
        return ["SUSPECT: out-of-order ts vs last stored ts for machine"]
    return []


def check_energy_decreasing(energy_kwh: float | None, last_energy_kwh: float | None) -> list[str]:
    if energy_kwh is not None and last_energy_kwh is not None and energy_kwh < last_energy_kwh:
        return ["BAD: cumulative energy_kwh decreasing"]
    return []


def check_spike(power_kw: float | None, rated_power_kw: float | None, spike_multiple: float) -> list[str]:
    if (
        power_kw is not None
        and rated_power_kw is not None
        and rated_power_kw > 0
        and power_kw > spike_multiple * rated_power_kw
    ):
        return [f"SUSPECT: power spike above {spike_multiple}x rated power"]
    return []


def check_production_impossible(
    qty_total_kg: float, qty_good_kg: float, qty_rejected_kg: float
) -> list[str]:
    reasons: list[str] = []
    for name, val in (
        ("qty_total_kg", qty_total_kg),
        ("qty_good_kg", qty_good_kg),
        ("qty_rejected_kg", qty_rejected_kg),
    ):
        if val < 0:
            reasons.append(f"impossible: {name} < 0")
    if qty_good_kg + qty_rejected_kg > qty_total_kg + 1e-9:
        reasons.append("impossible: qty_good_kg + qty_rejected_kg > qty_total_kg")
    return reasons


def validate_telemetry(
    *,
    ts: datetime,
    now: datetime,
    voltage_v: float | None = None,
    current_a: float | None = None,
    power_kw: float | None = None,
    power_factor: float | None = None,
    energy_kwh: float | None = None,
    last_ts: datetime | None = None,
    last_energy_kwh: float | None = None,
    rated_power_kw: float | None = None,
    stale_after_s: int = 900,
    clock_skew_s: int = 300,
    spike_multiple: float = 1.5,
    skip_stale: bool = False,
) -> ValidationResult:
    bad: list[str] = []
    suspect: list[str] = []
    bad += check_impossible_telemetry(voltage_v, current_a, power_kw, power_factor)
    bad += check_future_ts(ts, now, clock_skew_s)
    bad += check_energy_decreasing(energy_kwh, last_energy_kwh)
    if not skip_stale:
        suspect += check_stale_ts(ts, now, stale_after_s)
    suspect += check_out_of_order(ts, last_ts)
    suspect += check_spike(power_kw, rated_power_kw, spike_multiple)
    if bad:
        return ValidationResult("BAD", bad + suspect)
    if suspect:
        return ValidationResult("SUSPECT", suspect)
    return ValidationResult("GOOD", [])


def validate_production(
    *,
    qty_total_kg: float,
    qty_good_kg: float,
    qty_rejected_kg: float,
) -> ValidationResult:
    reasons = check_production_impossible(qty_total_kg, qty_good_kg, qty_rejected_kg)
    if reasons:
        return ValidationResult("BAD", reasons)
    return ValidationResult("GOOD", [])


def is_duplicate(ts: datetime, machine_id: str, seen: set[tuple[str, datetime]]) -> bool:
    """In-memory duplicate check helper (API enforces via UNIQUE constraint)."""
    return (machine_id, ts) in seen


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
