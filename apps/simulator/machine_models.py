"""Generic per-machine-type physics models (NOT foundry-hardcoded).

Physical consistency guarantee: three-phase power is always
    P_kW = sqrt(3) * V * I * PF / 1000
i.e. current is DERIVED from the chosen power setpoint, voltage and PF.
Energy is the running integral of power: E += P * dt / 3600.
All numeric constants below are SIMULATED/ASSUMPTION (see docs/ASSUMPTIONS.md).

NORMAL variability (seeded, reproducible with the same seed):
- furnace: each heat draws a charge weight ±8 % around nominal; melt
  duration follows charge / melting power plus noise; holding varies
  18–34 min; the idle gap follows a daily production plan (9–12 heats/day
  drawn per day) with a midday lunch idle and a shift-change idle.
- compressor: loaded/unloaded duty follows a time-of-day air-demand profile
  (peak mid-afternoon, trough at night; factory sets day_phase_h so the
  profile tracks wall-clock time).
- pump: steady load with small noise.

Scenario override knobs (public attributes; the factory sets these instead
of re-implementing physics):
- power_scale (all models): multiplies every power setpoint (HIGH_LOAD).
- furnace idle_scale: multiplies every idle gap incl. lunch/shift extras
  (PRODUCTION_SURGE shortens idles -> more heats per day, same per-kg
  melting physics).
- furnace force_state: forces a state with zero production (IDLE_WASTE).
- compressor force_loaded: True forces continuously loaded (IDLE_WASTE).
- health_ramp / power_ramp (all models): gradual EQUIPMENT_DEGRADATION
  effects applied in _finalize before energy integration (vibration /
  temperature rise; optional extra-mechanical-load power AND current
  uplift at nominal voltage for the same output).
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
        # Scenario override knob: multiplies every power setpoint. NORMAL = 1.0.
        self.power_scale = 1.0
        # Degradation knobs (EQUIPMENT_DEGRADATION, set per-step by the
        # factory as ramp values; NORMAL = 0.0). health_ramp scales the
        # vibration / temperature rise; power_ramp scales the efficiency-loss
        # power uplift. Both applied in _finalize BEFORE energy integration.
        self.health_ramp = 0.0
        self.power_ramp = 0.0

    # Degradation effect sizes (ASSUMPTION SIMULATED): vibration +5 mm/s and
    # temperature +40 C at health_ramp 1.0. Voltage always stays at its
    # NORMAL operating point (a supply-side sag is not equipment wear, so
    # the simulator never injects one here); current rises only with power
    # through power_ramp, at unchanged PF (power-factor rules stay silent
    # because PF itself is untouched).
    DEGRAD_VIB_MM_S = 5.0
    DEGRAD_TEMP_C = 40.0

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
        # Degradation applied BEFORE energy integration. health_ramp = 0
        # leaves the electrical operating point untouched (vibration and
        # temperature rise only: a health-only fault keeps energy normal).
        # power_ramp > 0 models extra mechanical load: power AND current
        # rise at nominal voltage with PF held constant. Power consistency
        # P = sqrt(3)*V*I*PF is preserved because current is derived from
        # the degraded power, nominal voltage and unchanged PF below.
        power_kw = power_kw * (1.0 + self.power_ramp)
        vibration = vibration + self.DEGRAD_VIB_MM_S * self.health_ramp
        temperature = temperature + self.DEGRAD_TEMP_C * self.health_ramp
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
    """Furnace batch heats: heating -> melting -> holding -> idle (repeats).

    ASSUMPTION (SIMULATED) power fractions of rated / PF / temps per state;
    nominal charge 375 kg (≈500 kg/h × 45 min melt); melt rate 500 kg/h.
    """

    machine_type = "furnace"
    POWER_FRAC = {"heating": 0.85, "melting": 0.95, "holding": 0.45, "idle": 0.08}
    # Idle PF kept strictly above the L1 power-factor rule threshold (0.6):
    # a resting furnace is not an electrical fault.
    PF = {"heating": 0.80, "melting": 0.85, "holding": 0.75, "idle": 0.62}
    TEMP = {"heating": 1200.0, "melting": 1550.0, "holding": 1500.0, "idle": 600.0}
    NOMINAL_CHARGE_KG = 375.0  # ASSUMPTION (SIMULATED): ~500 kg/h x 45 min.
    MELT_RATE_KG_H = 500.0  # ASSUMPTION (SIMULATED): nominal melt rate.
    PROD_RATE_KG_H = 500.0  # nominal (kept for compatibility; per-heat rate varies).

    def __init__(self, machine_id: str, rated_power_kw: float, rng) -> None:
        super().__init__(machine_id, rated_power_kw, rng)
        # Scenario override knobs (NORMAL: 1.0 / 1.0 / None).
        self.idle_scale = 1.0
        self.force_state: str | None = None
        # Seeded heat schedule: list of (state, start_min, end_min, prod_rate_kg_h).
        self._segments: list[tuple[str, float, float, float]] = []
        self._built_until_min = 0.0
        self._phase = "heating"
        self._day_plans: dict[int, int] = {}
        self._heats_today = 0
        self._shift_extra_pending = False

    def _next_segment(self) -> None:
        """Append one schedule segment using the shared seeded rng."""
        day = int(self._built_until_min // 1440)
        if day not in self._day_plans:
            # ASSUMPTION (SIMULATED): daily production plan, 9-12 heats/day.
            self._day_plans[day] = int(self.rng.integers(9, 13))
            self._heats_today = 0
            self._shift_extra_pending = True
        plan = self._day_plans[day]
        phase = self._phase
        if phase == "heating":
            dur = max(12.0, 20.0 + self.rng.normal(0, 1.5))
            prod = 0.0
        elif phase == "melting":
            # Charge varies ±8 %; duration follows charge / melting power + noise.
            charge = self.NOMINAL_CHARGE_KG * (1.0 + self.rng.uniform(-0.08, 0.08))
            dur = charge / self.MELT_RATE_KG_H * 60.0 * (1.0 + self.rng.normal(0, 0.02))
            dur = max(30.0, dur)
            prod = charge / (dur / 60.0)
        elif phase == "holding":
            # Pouring delay varies heat to heat.
            dur = float(self.rng.uniform(18.0, 34.0))
            prod = 0.0
        else:  # idle: gap sized by the daily plan + lunch/shift extras.
            base = max(8.0, 1440.0 / plan - 91.0)
            sc = self.idle_scale
            dur = base * sc + self.rng.normal(0, 3.0)
            if self._heats_today == plan // 2:
                dur += (30.0 + self.rng.uniform(0, 10.0)) * sc  # lunch idle
            if self._shift_extra_pending:
                dur += 15.0 * sc  # shift-change idle
                self._shift_extra_pending = False
            dur = max(1.0, dur)
            prod = 0.0
        start = self._built_until_min
        end = start + dur
        self._segments.append((phase, start, end, prod))
        self._built_until_min = end
        order = ("heating", "melting", "holding", "idle")
        nxt = order[(order.index(phase) + 1) % 4]
        if phase == "idle":
            self._heats_today += 1
        self._phase = nxt

    def _ensure(self, elapsed_min: float) -> None:
        while self._built_until_min <= elapsed_min:
            self._next_segment()

    def step(self, index: int, dt_h: float) -> SimStep:
        if self.force_state is not None:
            state = self.force_state
            power = self.rated_power_kw * self.POWER_FRAC[state] * (1 + self.rng.normal(0, 0.01))
            temp = self.TEMP[state] + self.rng.normal(0, 8.0)
            vib = 3.0 if state == "melting" else (1.2 if state == "idle" else 2.0)
            return self._finalize(power, self.PF[state], state, dt_h, vib, temp, None,
                                  state != "idle", 0.0)
        elapsed_min = index * dt_h * 60.0
        self._ensure(elapsed_min)
        state, prod = "idle", 0.0
        for s, a, b, p in reversed(self._segments):
            if a <= elapsed_min < b:
                state, prod = s, p
                break
        power = self.rated_power_kw * self.POWER_FRAC[state] * self.power_scale
        power *= 1 + self.rng.normal(0, 0.01)
        vib = 3.0 if state == "melting" else (1.2 if state == "idle" else 2.0)
        temp = self.TEMP[state] + self.rng.normal(0, 8.0)
        return self._finalize(power, self.PF[state], state, dt_h, vib, temp, None,
                              state != "idle", prod)


class SimulatedAirCompressor(SimulatedMachine):
    """Load/unload cycling compressor with a time-of-day air-demand profile.

    ASSUMPTION (SIMULATED): 9-min cycle; loaded share 0.65 ± 0.10 sinusoidal
    over 24 h (peak ~14:00, trough ~02:00). `day_phase_h` anchors elapsed
    time to wall-clock time (set by the factory from the run start).
    """

    machine_type = "compressor"
    CYCLE_MIN = 9.0
    LOADED_MIN, UNLOADED_MIN = 6.0, 3.0  # nominal means (kept for compatibility).
    PF = {"running": 0.88, "stopped": 0.70}

    def __init__(self, machine_id: str, rated_power_kw: float, rng) -> None:
        super().__init__(machine_id, rated_power_kw, rng)
        self.force_loaded: bool | None = None
        self.day_phase_h: float = 0.0

    def step(self, index: int, dt_h: float) -> SimStep:
        elapsed_min = index * dt_h * 60.0
        elapsed_h = index * dt_h
        tod = (elapsed_h + self.day_phase_h) % 24.0
        loaded_frac = 0.65 + 0.10 * math.sin(2.0 * math.pi * (tod - 8.0) / 24.0)
        loaded_min = self.CYCLE_MIN * loaded_frac
        pos = elapsed_min % self.CYCLE_MIN
        if self.force_loaded is True:
            loaded = True
        elif self.force_loaded is False:
            loaded = False
        else:
            loaded = pos < loaded_min
        frac = 0.90 if loaded else 0.25
        power = self.rated_power_kw * frac * self.power_scale * (1 + self.rng.normal(0, 0.015))
        vib = (4.5 if loaded else 2.0) + self.rng.normal(0, 0.2)
        temp = 75.0 + self.rng.normal(0, 2.0)
        rpm = 2950.0 + self.rng.normal(0, 10.0)
        return self._finalize(power, self.PF["running"], "running", dt_h, vib, temp, round(rpm, 1), True, 0.0)


class SimulatedCoolingPump(SimulatedMachine):
    """Steady-load pump with small noise. ASSUMPTION (SIMULATED)."""

    machine_type = "pump"

    def step(self, index: int, dt_h: float) -> SimStep:
        power = self.rated_power_kw * 0.70 * self.power_scale * (1 + self.rng.normal(0, 0.01))
        vib = 1.8 + self.rng.normal(0, 0.15)
        temp = 55.0 + self.rng.normal(0, 1.5)
        rpm = 1450.0 + self.rng.normal(0, 8.0)
        return self._finalize(power, 0.82, "running", dt_h, vib, temp, round(rpm, 1), True, 0.0)


class SimulatedGenericMotor(SimulatedMachine):
    """Fallback for any machine_type without a dedicated model."""

    machine_type = "generic"

    def step(self, index: int, dt_h: float) -> SimStep:
        power = self.rated_power_kw * 0.60 * self.power_scale * (1 + self.rng.normal(0, 0.02))
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
