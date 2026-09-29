"""Unit tests for scripts/validation/uci_steel.py (no download, no network).

3-row inline sample only; checks parsing, kVAh/PF math (console formula)
and the Load_Type -> state mapping with hourly aggregation.
"""

import math

from scripts.validation.uci_steel import (
    aggregate_hourly,
    capacitor_kvar_for_target,
    is_non_working,
    kvah_from_kwh_kvarh,
    load_type_to_state,
    parse_steel_rows,
    pf_from_kwh_kvah,
)

SAMPLE = [
    {
        "date": "01/01/2018 00:15",
        "Usage_kWh": "3.17",
        "Lagging_Current_Reactive.Power_kVarh": "2.95",
        "WeekStatus": "Weekday",
        "NSM": "900",
        "Load_Type": "Light_Load",
    },
    {
        "date": "01/01/2018 00:30",
        "Usage_kWh": "4.00",
        "Lagging_Current_Reactive.Power_kVarh": "4.46",
        "WeekStatus": "Weekday",
        "NSM": "1800",
        "Load_Type": "Light_Load",
    },
    {
        "date": "01/01/2018 00:45",
        "Usage_kWh": "10.00",
        "Lagging_Current_Reactive.Power_kVarh": "3.00",
        "WeekStatus": "Weekday",
        "NSM": "2700",
        "Load_Type": "Medium_Load",
    },
]


def test_kvah_matches_console_formula():
    assert kvah_from_kwh_kvarh(3.0, 4.0) == math.sqrt(9.0 + 16.0)
    assert kvah_from_kwh_kvarh(0.0, 0.0) == 0.0


def test_pf_roundtrip():
    kvah = kvah_from_kwh_kvarh(3.17, 2.95)
    pf = pf_from_kwh_kvah(3.17, kvah)
    assert pf == 3.17 / kvah
    assert pf_from_kwh_kvah(1.0, 0.0) is None


def test_capacitor_zero_when_already_good():
    assert capacitor_kvar_for_target(100.0, 0.97, 0.95) == 0.0
    need = capacitor_kvar_for_target(100.0, 0.80, 0.95)
    expected = 100.0 * (math.tan(math.acos(0.80)) - math.tan(math.acos(0.95)))
    assert need == abs(expected - 0.0) or abs(need - expected) < 1e-9


def test_parse_and_hourly_aggregation():
    parsed = parse_steel_rows(SAMPLE)
    assert len(parsed) == 3
    assert parsed[0]["kwh"] == 3.17
    assert parsed[0]["kvarh_lag"] == 2.95
    assert parsed[0]["nsm"] == 900
    assert load_type_to_state("Light_Load") == "idle"
    assert load_type_to_state("Medium_Load") == "holding"
    assert load_type_to_state("Maximum_Load") == "running"

    hours = aggregate_hourly(parsed)
    assert len(hours) == 1
    h = hours[0]
    assert h["energy_kwh"] == 3.17 + 4.00 + 10.00
    assert h["kvarh_lag"] == 2.95 + 4.46 + 3.00
    assert h["kvah"] == kvah_from_kwh_kvarh(h["energy_kwh"], h["kvarh_lag"])
    assert h["pf"] == pf_from_kwh_kvah(h["energy_kwh"], h["kvah"])
    assert h["hours_by_state"]["idle"] == 0.5
    assert h["hours_by_state"]["holding"] == 0.25
    assert h["n_quarters"] == 3


def test_is_non_working_definition():
    assert is_non_working("Weekend", 12 * 3600) is True
    assert is_non_working("Weekday", 2 * 3600) is True
    assert is_non_working("Weekday", 12 * 3600) is False
