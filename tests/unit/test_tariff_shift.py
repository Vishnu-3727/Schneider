"""Unit tests: TARIFF_SHIFT clustering (NORMAL physics, new timing) and
COMBINED_ANOMALY still NotImplementedError. No DB."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.simulator.factory_simulator import (
    DEFAULT_MACHINES,
    SimulatedFactory,
    Scenario,
)

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, 0, 0, tzinfo=TZ)  # midnight: peak window inside the day


def _peak_share(scenario: str, seed: int = 1) -> tuple[float, int]:
    f = SimulatedFactory(DEFAULT_MACHINES, scenario=scenario, hours=24,
                         step_s=300, seed=seed, end=END,
                         tariff_peak_start_h=18.0, tariff_peak_end_h=22.0)
    tel, _ = f.run()
    heats = [t for t in tel if t["machine_id"] == "furnace-01"
             and t["machine_state"] == "heating"]
    in_peak = sum(1 for t in heats
                  if 18 <= datetime.fromisoformat(t["ts"]).hour < 22)
    return (in_peak / len(heats) if heats else 0.0), len(heats)


def test_tariff_shift_clusters_heats_in_peak_window():
    normal_share, _ = _peak_share("NORMAL")
    shift_share, n = _peak_share("TARIFF_SHIFT")
    assert n > 0
    assert shift_share > 2 * normal_share  # clearly clustered, not uniform


def test_tariff_shift_keeps_normal_physics():
    f = SimulatedFactory(DEFAULT_MACHINES, scenario="TARIFF_SHIFT", hours=24,
                         step_s=300, seed=1, end=END)
    tel, prod = f.run()
    assert {p["source"] for p in tel} == {"SIMULATED"}
    states = {t["machine_state"] for t in tel if t["machine_id"] == "furnace-01"}
    assert states <= {"heating", "melting", "holding", "idle"}
    # Same per-heat physics: melting power fraction of rated, charge ~375 kg.
    melts = [t["power_kw"] for t in tel if t["machine_id"] == "furnace-01"
             and t["machine_state"] == "melting"]
    assert melts and sum(melts) / len(melts) == pytest.approx(150.0 * 0.95, rel=0.05)
    qtys = [p["qty_good_kg"] for p in prod if p["machine_id"] == "furnace-01"]
    assert sum(qtys) > 0  # still produces


def test_combined_anomaly_still_not_implemented():
    with pytest.raises(NotImplementedError):
        SimulatedFactory(DEFAULT_MACHINES, scenario="COMBINED_ANOMALY")
    with pytest.raises(NotImplementedError):
        from apps.simulator.fault_generator import apply_fault
        apply_fault([], Scenario.COMBINED_ANOMALY)


def test_tariff_shift_window_reported_for_tests_only():
    f = SimulatedFactory(DEFAULT_MACHINES, scenario="TARIFF_SHIFT", hours=30,
                         step_s=300, seed=1, end=END,
                         scenario_start_h=6.0, scenario_duration_h=24.0)
    f.run()
    assert set(f.scenario_windows()) == {"furnace-01"}
