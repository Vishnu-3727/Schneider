"""Phase 5B: cost and CO2 impact of a verified saving (tariff periods, factor provenance)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from services.optimization.evaluate import TariffPeriod
from services.verification.impact import (
    EmissionFactor,
    co2_impact,
    cost_impact,
    impacts,
    select_factor,
)

TZ = "Asia/Kolkata"
IST = ZoneInfo(TZ)
TOU = [TariffPeriod("off_peak", 22.0, 6.0, 6.0), TariffPeriod("normal", 6.0, 18.0, 8.0),
       TariffPeriod("peak", 18.0, 22.0, 10.0)]
F20 = EmissionFactor("v20", "India", 0.727, "kgCO2/kWh", "CO2 only", "CEA", "v20.0", "FY2023-24",
                     date(2023, 4, 1), date(2024, 3, 31), "EXTERNAL_REFERENCE")
F21 = EmissionFactor("v21", "India", 0.710, "kgCO2/kWh", "CO2 only", "CEA", "v21.0", "FY2024-25",
                     date(2024, 4, 1), date(2025, 3, 31), "EXTERNAL_REFERENCE")
F21_UNCONFIRMED = EmissionFactor("v21u", "India", 0.710, "kgCO2/kWh", "CO2 only", "CEA", "v21.0",
                                 "FY2024-25", date(2024, 4, 1), date(2025, 3, 31),
                                 "EXTERNAL_REFERENCE", "confirm against the CEA user guide table")


def _h(hour, cf, act, minute=0):
    return {"window_start": datetime(2026, 9, 19, hour, minute, tzinfo=IST),
            "counterfactual_kwh": cf, "actual_kwh": act}


def test_cost_uses_the_period_covering_each_hour():
    out = cost_impact([_h(3, 10, 5), _h(12, 10, 5), _h(19, 10, 5)], TOU, TZ, illustrative=True)
    assert out["status"] == "OK"
    assert out["value_inr"] == pytest.approx(5 * 6 + 5 * 8 + 5 * 10)


def test_cost_boundaries_start_inclusive_end_exclusive():
    # 18:00 belongs to peak (start inclusive); 06:00 to normal; 22:00 to off-peak.
    assert cost_impact([_h(18, 1, 0)], TOU, TZ, True)["value_inr"] == 10.0
    assert cost_impact([_h(6, 1, 0)], TOU, TZ, True)["value_inr"] == 8.0
    assert cost_impact([_h(22, 1, 0)], TOU, TZ, True)["value_inr"] == 6.0
    assert cost_impact([_h(17, 1, 0, minute=59)], TOU, TZ, True)["value_inr"] == 8.0


def test_cost_uses_local_time_not_utc():
    utc_19_ist = datetime(2026, 9, 19, 13, 30, tzinfo=ZoneInfo("UTC"))  # 19:00 IST -> peak
    out = cost_impact([{"window_start": utc_19_ist, "counterfactual_kwh": 1.0,
                        "actual_kwh": 0.0}], TOU, TZ, True)
    assert out["value_inr"] == 10.0


def test_cost_missing_or_incomplete_tariff_is_unavailable():
    assert cost_impact([_h(3, 10, 5)], None, TZ, True)["status"] == "UNAVAILABLE"
    assert cost_impact([_h(3, 10, 5)], [], TZ, True)["value_inr"] is None
    partial = [TariffPeriod("day", 6.0, 18.0, 8.0)]
    out = cost_impact([_h(3, 10, 5)], partial, TZ, True)
    assert out["status"] == "UNAVAILABLE" and "incomplete" in out["reason"]


def test_cost_labels_illustrative_tariff():
    ill = cost_impact([_h(3, 10, 5)], TOU, TZ, illustrative=True)
    assert "ILLUSTRATIVE" in ill["tariff_label"] and ill["source_class"] == "ASSUMPTION"
    real = cost_impact([_h(3, 10, 5)], TOU, TZ, illustrative=False)
    assert "ILLUSTRATIVE" not in real["tariff_label"]


def test_factor_selection_by_effective_period_and_version():
    assert select_factor([F20, F21], date(2023, 10, 1)) == (F20, "EFFECTIVE")
    assert select_factor([F20, F21], date(2024, 4, 1)) == (F21, "EFFECTIVE")
    f, st = select_factor([F20, F21], date(2026, 9, 19))
    assert f is F21 and st == "LATEST_AVAILABLE"
    assert select_factor([F21], date(2023, 1, 1)) == (None, "UNAVAILABLE")


def test_co2_units_and_provenance():
    out = co2_impact(1000.0, [F20, F21], date(2024, 6, 1))
    assert out["value_kg"] == pytest.approx(710.0)  # 1000 kWh x 0.710 kgCO2/kWh
    fac = out["factor"]
    assert fac["unit"] == "kgCO2/kWh" and fac["version"] == "v21.0"
    assert fac["fiscal_year"] == "FY2024-25" and fac["source_class"] == "EXTERNAL_REFERENCE"
    assert fac["gas_basis"] == "CO2 only" and "not CO2e" in out["unit"]


def test_co2_flags_provisional_factor_and_never_claims_co2e():
    out = co2_impact(1000.0, [F21_UNCONFIRMED], date(2024, 6, 1))
    assert out["provisional"] is True and "not for external accounting" in out["label"]
    assert "reported as CO2e" not in out["unit"]
    assert co2_impact(1000.0, [F21], date(2024, 6, 1))["provisional"] is False
    late = co2_impact(1000.0, [F20, F21], date(2026, 9, 19))
    assert late["status"] == "LATEST_AVAILABLE" and "latest available" in late["reason"]


def test_co2_missing_factor_is_unavailable():
    out = co2_impact(1000.0, [], date(2026, 9, 19))
    assert out["status"] == "UNAVAILABLE" and out["value_kg"] is None


def test_only_verified_savings_are_converted():
    for status in ("NOT_VERIFIED", "NOT_COMPARABLE", "INSUFFICIENT_DATA"):
        cost, co2 = impacts(status, 500.0, [_h(3, 10, 5)], TOU, True, [F21], date(2024, 6, 1), TZ)
        assert cost["status"] == co2["status"] == "NOT_APPLICABLE"
        assert cost["value_inr"] is None and co2["value_kg"] is None
    cost, co2 = impacts("VERIFIED", 5.0, [_h(3, 10, 5)], TOU, True, [F21], date(2024, 6, 1), TZ)
    assert cost["value_inr"] == 30.0 and co2["value_kg"] == pytest.approx(3.55)
