"""Specific Energy Consumption: SEC = energy_kwh / good production (kWh/t).

Never returns inf or NaN: every non-computable case carries an explicit
status. Rejected production is excluded from the denominator (good kg only).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SecResult:
    sec_kwh_per_t: float | None
    status: str  # OK | NO_PRODUCTION | MISSING_PRODUCTION | INCOMPLETE_DATA | NOT_APPLICABLE
    non_productive_kwh: float | None = None


def compute_sec(
    energy_kwh: float | None,
    good_production_kg: float | None,
    has_production_record: bool,
    machine_type: str,
    non_production_types: tuple[str, ...] | list[str],
    interval_complete: bool,
) -> SecResult:
    """All thresholds come from config; this function takes plain values."""
    if machine_type in non_production_types:
        return SecResult(sec_kwh_per_t=None, status="NOT_APPLICABLE")
    if not interval_complete:
        return SecResult(sec_kwh_per_t=None, status="INCOMPLETE_DATA")
    if not has_production_record or good_production_kg is None:
        return SecResult(sec_kwh_per_t=None, status="MISSING_PRODUCTION")
    if energy_kwh is None:
        return SecResult(sec_kwh_per_t=None, status="INCOMPLETE_DATA")
    if good_production_kg <= 0:
        if energy_kwh > 0:
            # Energy was spent with zero useful output: report it, never divide.
            return SecResult(sec_kwh_per_t=None, status="NO_PRODUCTION",
                             non_productive_kwh=energy_kwh)
        return SecResult(sec_kwh_per_t=None, status="NO_PRODUCTION",
                         non_productive_kwh=0.0)
    good_t = good_production_kg / 1000.0
    return SecResult(sec_kwh_per_t=energy_kwh / good_t, status="OK")
