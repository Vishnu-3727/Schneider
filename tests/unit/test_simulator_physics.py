"""Unit tests: simulator physics — power formula, energy integral, reproducibility."""

import math

import pytest

from apps.simulator.factory_simulator import DEFAULT_MACHINES, Scenario, SimulatedFactory
from apps.simulator.fault_generator import apply_fault


def packets(seed=1, **kw):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    end = kw.pop("end", datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    f = SimulatedFactory(DEFAULT_MACHINES, hours=2, step_s=60, seed=seed, end=end, **kw)
    return f.run()


def test_power_formula_consistency():
    tel, _ = packets()
    for p in tel:
        expected = math.sqrt(3) * p["voltage_v"] * p["current_a"] * p["power_factor"] / 1000.0
        assert p["power_kw"] == pytest.approx(expected, rel=1e-3), p


def test_energy_monotonic_and_matches_integral():
    tel, _ = packets()
    dt_h = 60 / 3600.0
    by_machine: dict[str, list[dict]] = {}
    for p in tel:
        by_machine.setdefault(p["machine_id"], []).append(p)
    for mid, rows in by_machine.items():
        energies = [r["energy_kwh"] for r in rows]
        assert all(b >= a for a, b in zip(energies, energies[1:])), mid
        integral = sum(r["power_kw"] * dt_h for r in rows)
        # E starts at 0, so E_last must equal the power integral
        # (rel tolerance accounts for 3-decimal power rounding per step).
        assert energies[-1] == pytest.approx(integral, rel=1e-4), mid


def test_reproducible_same_seed():
    t1, p1 = packets(seed=7)
    t2, p2 = packets(seed=7)
    assert t1 == t2 and p1 == p2


def test_different_seed_differs():
    t1, _ = packets(seed=1)
    t2, _ = packets(seed=2)
    assert t1 != t2


def test_all_records_simulated_source():
    tel, prod = packets()
    assert {p["source"] for p in tel} == {"SIMULATED"}
    assert {p["source"] for p in prod} == {"SIMULATED"}


def test_non_normal_scenario_raises():
    with pytest.raises(NotImplementedError, match="Phase 2"):
        SimulatedFactory(DEFAULT_MACHINES, scenario="IDLE_WASTE")
    with pytest.raises(NotImplementedError, match="Phase 2"):
        apply_fault([], Scenario.HIGH_LOAD)
    assert apply_fault([{"a": 1}], Scenario.NORMAL) == [{"a": 1}]
