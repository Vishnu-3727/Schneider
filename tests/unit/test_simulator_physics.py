"""Unit tests: simulator physics — power formula, energy integral, reproducibility."""

import math
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo

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
    # Phase 2: IDLE_WASTE/HIGH_LOAD/PRODUCTION_SURGE are implemented in the
    # factory; Phase 3A adds EQUIPMENT_DEGRADATION; Phase 4A adds
    # TARIFF_SHIFT; only COMBINED_ANOMALY still raises NotImplementedError.
    with pytest.raises(NotImplementedError, match="future work"):
        SimulatedFactory(DEFAULT_MACHINES, scenario="COMBINED_ANOMALY")
    with pytest.raises(NotImplementedError, match="future work"):
        apply_fault([], Scenario.COMBINED_ANOMALY)
    with pytest.raises(NotImplementedError, match="SimulatedFactory"):
        apply_fault([], Scenario.HIGH_LOAD)
    assert apply_fault([{"a": 1}], Scenario.NORMAL) == [{"a": 1}]
    # EQUIPMENT_DEGRADATION runs in-run and stays physically consistent.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    f = SimulatedFactory(DEFAULT_MACHINES, scenario="EQUIPMENT_DEGRADATION", hours=6,
                         step_s=60, seed=1,
                         end=datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
                         scenario_start_h=2.0, scenario_duration_h=4.0,
                         magnitude=1.0, energy_penalty=0.3)
    tel, _ = f.run()
    assert tel, "degradation run must emit telemetry"
    for p in tel:
        if p["current_a"] is None:
            continue
        expected = math.sqrt(3) * p["voltage_v"] * p["current_a"] * p["power_factor"] / 1000.0
        assert p["power_kw"] == pytest.approx(expected, rel=1e-3), p


def test_degradation_health_only_keeps_electrical_normal():
    """B1: energy_penalty = 0 -> vibration/temperature rise, but voltage,
    current and power stay at their NORMAL operating points (no supply-side
    sag artefact). Same seed => identical noise, so electrical channels
    must match a NORMAL run step-for-step inside the window."""
    end = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    def _run(scenario, **extra):
        f = SimulatedFactory(DEFAULT_MACHINES, hours=6, step_s=60, seed=1, end=end,
                             scenario_start_h=2.0, scenario_duration_h=4.0,
                             magnitude=1.0, scenario=scenario, **extra)
        return f.run()[0]

    tel_n = _run("NORMAL")
    tel_d = _run("EQUIPMENT_DEGRADATION", energy_penalty=0.0)
    assert len(tel_n) == len(tel_d)
    n_window = int(4.0 * 3600 / 60)
    start_idx = int(2.0 * 3600 / 60)
    for mid in ("furnace-01", "compressor-01"):
        nrows = [p for p in tel_n if p["machine_id"] == mid]
        drows = [p for p in tel_d if p["machine_id"] == mid]
        win_n = nrows[start_idx:start_idx + n_window]
        win_d = drows[start_idx:start_idx + n_window]
        for pn, pd in zip(win_n, win_d):
            assert pd["power_kw"] == pytest.approx(pn["power_kw"], rel=1e-9), (mid, pn, pd)
            assert pd["current_a"] == pytest.approx(pn["current_a"], rel=1e-9), (mid, pn, pd)
            assert pd["voltage_v"] == pytest.approx(pn["voltage_v"], rel=1e-9), (mid, pn, pd)
        vib_uplift = statistics.mean(p["vibration_mm_s"] for p in win_d) - \
            statistics.mean(p["vibration_mm_s"] for p in win_n)
        temp_uplift = statistics.mean(p["temperature_c"] for p in win_d) - \
            statistics.mean(p["temperature_c"] for p in win_n)
        assert vib_uplift > 1.0, (mid, vib_uplift)
        assert temp_uplift > 5.0, (mid, temp_uplift)


def test_degradation_energy_penalty_raises_power_and_current_at_nominal_voltage():
    """B1: energy_penalty > 0 -> extra mechanical load: power AND current
    rise at nominal voltage, P = sqrt(3)*V*I*PF still holds exactly."""
    end = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    def _run(scenario, **extra):
        f = SimulatedFactory(DEFAULT_MACHINES, hours=6, step_s=60, seed=1, end=end,
                             scenario_start_h=2.0, scenario_duration_h=4.0,
                             magnitude=1.0, scenario=scenario, **extra)
        return f.run()[0]

    tel_n = _run("NORMAL")
    tel_d = _run("EQUIPMENT_DEGRADATION", energy_penalty=0.3)
    n_window = int(4.0 * 3600 / 60)
    start_idx = int(2.0 * 3600 / 60)
    for mid in ("furnace-01", "compressor-01"):
        nrows = [p for p in tel_n if p["machine_id"] == mid]
        drows = [p for p in tel_d if p["machine_id"] == mid]
        win_n = nrows[start_idx:start_idx + n_window]
        win_d = drows[start_idx:start_idx + n_window]
        mean_pn = statistics.mean(p["power_kw"] for p in win_n)
        mean_pd = statistics.mean(p["power_kw"] for p in win_d)
        mean_in = statistics.mean(p["current_a"] for p in win_n)
        mean_id = statistics.mean(p["current_a"] for p in win_d)
        assert mean_pd > mean_pn * 1.05, (mid, mean_pn, mean_pd)
        assert mean_id > mean_in * 1.05, (mid, mean_in, mean_id)
        # Nominal voltage: no sag (mean within a few V of 415).
        mean_v = statistics.mean(p["voltage_v"] for p in win_d)
        assert abs(mean_v - 415.0) < 5.0, (mid, mean_v)
        for p in win_d:
            expected = math.sqrt(3) * p["voltage_v"] * p["current_a"] * p["power_factor"] / 1000.0
            assert p["power_kw"] == pytest.approx(expected, rel=1e-3), (mid, p)


def test_phase2_scenarios_run_and_stay_monotonic():
    import math

    from datetime import datetime
    from zoneinfo import ZoneInfo
    end = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    for sc in ("IDLE_WASTE", "HIGH_LOAD", "PRODUCTION_SURGE"):
        f = SimulatedFactory(DEFAULT_MACHINES, scenario=sc, hours=48, step_s=60,
                             seed=1, end=end, scenario_start_h=24, scenario_duration_h=24)
        tel, prod = f.run()
        assert f.scenario_windows()  # ground truth for tests only
        by_machine: dict[str, list[dict]] = {}
        for p in tel:
            by_machine.setdefault(p["machine_id"], []).append(p)
        for mid, rows in by_machine.items():
            energies = [r["energy_kwh"] for r in rows]
            assert all(b >= a for a, b in zip(energies, energies[1:])), (sc, mid)
            for p in rows:
                expected = math.sqrt(3) * p["voltage_v"] * p["current_a"] * p["power_factor"] / 1000.0
                assert p["power_kw"] == pytest.approx(expected, rel=1e-3), (sc, mid)
