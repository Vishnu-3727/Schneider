"""Generic per-machine-type physics models (NOT foundry-hardcoded).

Physical consistency guarantee: three-phase power is always
    P_kW = sqrt(3) * V * I * PF / 1000
i.e. current is DERIVED from the chosen power setpoint, voltage and PF.
Energy is the running integral of power: E += P * dt / 3600.
All numeric constants below are SIMULATED/ASSUMPTION (see docs/ASSUMPTIONS.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SQRT3 = math.sqrt(3.0)
NOMINAL_VOLTAGE_V = 415.0  # ASSUMPTION: Indian LT 3-phase nominal.


@dataclass
class SimStep:
    voltage_v: float
    current_a: float
    power_kw: float
    reactive_power_kvar: float
    power_factor: float
    energy_kwh: float
    vibration_mm_s: float
    temperature_c: float
    rpm: float | None
    runtime_h: float
    machine_state: str
    production_rate_kg_h: float


def _electrical(power_kw: float, voltage_v: float, pf: float) -> tuple[float, float]:
    current_a = power_kw * 1000.0 / (SQRT3 * voltage_v * pf)
    reactive_kvar = power_kw * math.tan(math.acos(min(max(pf, 0.01), 1.0)))
    return current_a, reactive_kvar


class SimulatedMachine:
    """Base class: integrates energy, tracks runtime. Subclasses pick setpoints."""

    machine_type = "generic"

    def __init__(self, machine_id: str, rated_power_kw: float, rng) -> None:
        self.machine_id = machine_id
        self.rated_power_kw = rated_power_kw
        self.rng = rng
        self.energy_kwh = 0.0
        self.runtime_h = 0.0

    def _finalize(
        self,
        power_kw: float,
        pf: float,
        state: str,
        dt_h: float,
        vibration: float,
        temperature: float,
        rpm: float | None,
        running: bool,
        prod_rate: float,
    ) -> SimStep:
        voltage_v = NOMINAL_VOLTAGE_V + self.rng.normal(0, 3.0)
        current_a, q_kvar = _electrical(power_kw, voltage_v, pf)
        self.energy_kwh += power_kw * dt_h
        if running:
            self.runtime_h += dt_h
        return SimStep(
            voltage_v=round(voltage_v, 2),
            current_a=round(current_a, 2),
            power_kw=round(power_kw, 3),
            reactive_power_kvar=round(q_kvar, 3),
            power_factor=round(pf, 3),
            energy_kwh=round(self.energy_kwh, 5),
            vibration_mm_s=round(vibration, 2),
            temperature_c=round(temperature, 1),
            rpm=rpm,
            runtime_h=round(self.runtime_h, 4),
            machine_state=state,
            production_rate_kg_h=prod_rate,
        )

    def step(self, index: int, dt_h: float) -> SimStep:
        raise NotImplementedError


class SimulatedInductionFurnace(SimulatedMachine):
    """Furnace batch cycle: heating -> melting -> holding -> idle (repeats)."""

    machine_type = "furnace"
    # ASSUMPTION (SIMULATED): state durations in minutes + power fractions of rated.
    CYCLE = [("heating", 20, 0.85), ("melting", 45, 0.95), ("holding", 25, 0.45), ("idle", 30, 0.08)]
    PF = {"heating": 0.80, "melting": 0.85, "holding": 0.75, "idle": 0.60}
    TEMP = {"heating": 1200.0, "melting": 1550.0, "holding": 1500.0, "idle": 600.0}
    PROD_RATE_KG_H = 500.0  # ASSUMPTION (SIMULATED): melt rate during melting.

    def step(self, index: int, dt_h: float) -> SimStep:
        cycle_min = sum(d for _, d, _ in self.CYCLE)
        pos = (index * dt_h * 60.0) % cycle_min
        state, frac = "idle", 0.08
        acc = 0.0
        for s, dur, f in self.CYCLE:
            if pos < acc + dur:
                state, frac = s, f
                break
            acc += dur
        power = self.rated_power_kw * frac * (1 + self.rng.normal(0, 0.01))
        vib = 3.0 if state == "melting" else (1.2 if state == "idle" else 2.0)
        temp = self.TEMP[state] + self.rng.normal(0, 8.0)
        prod = self.PROD_RATE_KG_H if state == "melting" else 0.0
        return self._finalize(power, self.PF[state], state, dt_h, vib, temp, None, state != "idle", prod)


class SimulatedAirCompressor(SimulatedMachine):
    """Load/unload cycling compressor. ASSUMPTION (SIMULATED) duty cycle."""

    machine_type = "compressor"
    LOADED_MIN, UNLOADED_MIN = 6.0, 3.0
    PF = {"running": 0.88, "stopped": 0.70}

    def step(self, index: int, dt_h: float) -> SimStep:
        pos = (index * dt_h * 60.0) % (self.LOADED_MIN + self.UNLOADED_MIN)
        loaded = pos < self.LOADED_MIN
        frac = 0.90 if loaded else 0.25
        power = self.rated_power_kw * frac * (1 + self.rng.normal(0, 0.015))
        vib = (4.5 if loaded else 2.0) + self.rng.normal(0, 0.2)
        temp = 75.0 + self.rng.normal(0, 2.0)
        rpm = 2950.0 + self.rng.normal(0, 10.0)
        return self._finalize(power, self.PF["running"], "running", dt_h, vib, temp, round(rpm, 1), True, 0.0)


class SimulatedCoolingPump(SimulatedMachine):
    """Near-constant-speed pump with slow modulation. ASSUMPTION (SIMULATED)."""

    machine_type = "pump"

    def step(self, index: int, dt_h: float) -> SimStep:
        modulation = 1.0 + 0.05 * math.sin(index * dt_h * 60.0 / 600.0)
        power = self.rated_power_kw * 0.70 * modulation * (1 + self.rng.normal(0, 0.01))
        vib = 1.8 + self.rng.normal(0, 0.15)
        temp = 55.0 + self.rng.normal(0, 1.5)
        rpm = 1450.0 + self.rng.normal(0, 8.0)
        return self._finalize(power, 0.82, "running", dt_h, vib, temp, round(rpm, 1), True, 0.0)


class SimulatedGenericMotor(SimulatedMachine):
    """Fallback for any machine_type without a dedicated model."""

    machine_type = "generic"

    def step(self, index: int, dt_h: float) -> SimStep:
        power = self.rated_power_kw * 0.60 * (1 + self.rng.normal(0, 0.02))
        return self._finalize(
            power, 0.80, "running", dt_h,
            2.5 + self.rng.normal(0, 0.2), 65.0 + self.rng.normal(0, 2.0),
            1450.0, True, 0.0,
        )


MODEL_BY_TYPE: dict[str, type[SimulatedMachine]] = {
    "furnace": SimulatedInductionFurnace,
    "compressor": SimulatedAirCompressor,
    "pump": SimulatedCoolingPump,
    "motor": SimulatedGenericMotor,
    "generic": SimulatedGenericMotor,
}


def make_machine(machine_id: str, machine_type: str, rated_power_kw: float, rng) -> SimulatedMachine:
    cls = MODEL_BY_TYPE.get(machine_type, SimulatedGenericMotor)
    return cls(machine_id, rated_power_kw, rng)
