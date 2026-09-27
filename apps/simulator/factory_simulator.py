"""Parameterised factory engine (SIMULATED data).

Class names make simulation explicit: SimulatedFactory, SimulatedScenario.
Phase 2 implements IDLE_WASTE, HIGH_LOAD and PRODUCTION_SURGE as in-run
overrides of the machine-model knobs (parameterised by start offset,
duration and magnitude); Phase 3A adds EQUIPMENT_DEGRADATION (gradual
vibration/temperature rise with an optional extra-mechanical-load power
AND current uplift at nominal voltage) plus an omit_health_signals
option. TARIFF_SHIFT and COMBINED_ANOMALY still raise NotImplementedError
(Phase 4+).

Scenario effects are applied BEFORE energy integration: the factory only
sets public override knobs on the machine model (power_scale, idle_scale,
force_state, force_loaded, health_ramp, power_ramp) and then calls
model.step() exactly once, so the cumulative counter stays consistent and
no physics lives in the factory. Ground-truth scenario windows are
exposed via scenario_windows() for tests only — never stored as telemetry.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

import numpy as np

from apps.simulator.machine_models import make_machine


class Scenario(str, Enum):
    NORMAL = "NORMAL"
    IDLE_WASTE = "IDLE_WASTE"
    EQUIPMENT_DEGRADATION = "EQUIPMENT_DEGRADATION"
    HIGH_LOAD = "HIGH_LOAD"
    PRODUCTION_SURGE = "PRODUCTION_SURGE"
    TARIFF_SHIFT = "TARIFF_SHIFT"
    COMBINED_ANOMALY = "COMBINED_ANOMALY"


PHASE3_SCENARIOS = {Scenario.TARIFF_SHIFT, Scenario.COMBINED_ANOMALY}

#: Default power uplift for HIGH_LOAD (fraction). Kept below the ingest spike
#: multiple (1.5x) so scenario rows stay GOOD quality.
DEFAULT_HIGH_LOAD_MAGNITUDE = 0.25

#: Default production uplift for PRODUCTION_SURGE (fraction). The surge is
#: MORE HEATS PER DAY (shorter idle gaps via the furnace idle_scale knob)
#: with the same per-kg melting physics: energy rises through both the extra
#: production and the extra time-based (holding/heating) losses.
DEFAULT_SURGE_MAGNITUDE = 0.30

#: Default EQUIPMENT_DEGRADATION health magnitude (health_ramp reaches this
#: at the end of the window: +5 mm/s vibration, +40 C at unchanged voltage,
#: current and PF) and extra-mechanical-load power uplift fraction
#: (power_ramp reaches this at the end of the window, same useful output;
#: power AND current rise at nominal voltage). energy_penalty = 0 ->
#: HEALTH-ONLY anomaly (energy normal); > 0 -> power/energy rise too
#: (combined).
DEFAULT_DEGRADATION_MAGNITUDE = 1.0
DEFAULT_ENERGY_PENALTY = 0.0

#: Machine types each scenario overrides; other types run NORMAL
#: (pump doubles as an unaffected control in every scenario run).
SCENARIO_SCOPE = {
    Scenario.IDLE_WASTE: ("furnace", "compressor"),
    Scenario.HIGH_LOAD: ("furnace", "compressor"),
    Scenario.PRODUCTION_SURGE: ("furnace",),
    Scenario.EQUIPMENT_DEGRADATION: ("furnace", "compressor"),
}


@dataclass
class MachineSpec:
    machine_id: str
    machine_type: str
    rated_power_kw: float


DEFAULT_MACHINES = [  # mirrors database/seeds/phase1.sql demo instances
    MachineSpec("furnace-01", "furnace", 150.0),
    MachineSpec("compressor-01", "compressor", 30.0),
    MachineSpec("pump-01", "pump", 15.0),
]

REJECT_FRACTION = 0.02  # ASSUMPTION (SIMULATED): 2% of melt is rejected.


class SimulatedFactory:
    """Generates telemetry + hourly production packets for a scenario run."""

    def __init__(
        self,
        machines: list[MachineSpec],
        scenario: Scenario | str = Scenario.NORMAL,
        hours: float = 24.0,
        step_s: int = 60,
        seed: int = 1,
        tz: str = "Asia/Kolkata",
        end: datetime | None = None,
        scenario_start_h: float = 0.0,
        scenario_duration_h: float | None = None,
        magnitude: float | None = None,
        energy_penalty: float | None = None,
        omit_health_signals: bool = False,
    ) -> None:
        self.scenario = Scenario(scenario)
        if self.scenario in PHASE3_SCENARIOS:
            raise NotImplementedError(
                f"Scenario {self.scenario.value} is Phase 4+ work; implemented: "
                "NORMAL, IDLE_WASTE, HIGH_LOAD, PRODUCTION_SURGE, EQUIPMENT_DEGRADATION."
            )
        if magnitude is not None and magnitude < 0:
            raise ValueError("magnitude must be >= 0")
        if energy_penalty is not None and energy_penalty < 0:
            raise ValueError("energy_penalty must be >= 0")
        self.machines = machines
        self.hours = hours
        self.step_s = step_s
        self.seed = seed
        self.tz = ZoneInfo(tz)
        self.end = end or datetime.now(self.tz)
        self.steps = int(hours * 3600 / step_s)
        self.scenario_start_h = scenario_start_h
        self.scenario_duration_h = scenario_duration_h if scenario_duration_h is not None else hours
        # None -> per-scenario default (HIGH_LOAD 0.25, SURGE 0.30, IDLE_WASTE 0.0,
        # EQUIPMENT_DEGRADATION magnitude 1.0, energy_penalty 0.0 = health-only).
        self.magnitude = magnitude
        # Efficiency-loss uplift for EQUIPMENT_DEGRADATION only (fraction of
        # power at the same useful output). 0 -> HEALTH-ONLY (energy normal).
        self.energy_penalty = energy_penalty
        # When True, vibration/temperature/current are emitted as null
        # (emulates health data "unavailable"; energy path unaffected).
        self.omit_health_signals = omit_health_signals
        self._last_start: datetime | None = None

    # -- scenario helpers -------------------------------------------------
    def _in_window(self, elapsed_h: float) -> bool:
        return self.scenario_start_h <= elapsed_h < self.scenario_start_h + self.scenario_duration_h

    def scenario_windows(self) -> dict[str, tuple[str, str]]:
        """Ground-truth injected windows {machine_id: (start_iso, end_iso)} for tests only."""
        if self.scenario == Scenario.NORMAL or self._last_start is None:
            return {}
        ws = self._last_start + timedelta(hours=self.scenario_start_h)
        we = ws + timedelta(hours=self.scenario_duration_h)
        scope = SCENARIO_SCOPE.get(self.scenario, ())
        return {
            spec.machine_id: (ws.isoformat(), we.isoformat())
            for spec in self.machines
            if spec.machine_type in scope
        }

    def _scenario_step(self, model, spec: MachineSpec, index: int, dt_h: float, elapsed_h: float):
        """Set public model knobs, then take exactly one model.step()."""
        self._reset_knobs(model)
        if (
            self.scenario == Scenario.NORMAL
            or not self._in_window(elapsed_h)
            or spec.machine_type not in SCENARIO_SCOPE.get(self.scenario, ())
        ):
            return model.step(index, dt_h), False
        if self.scenario == Scenario.IDLE_WASTE:
            # Powered holding / continuously loaded against no demand
            # (ASSUMPTION SIMULATED); production stays zero via the model.
            if spec.machine_type == "furnace" and hasattr(model, "force_state"):
                model.force_state = "holding"
            elif hasattr(model, "force_loaded"):
                model.force_loaded = True
        elif self.scenario == Scenario.HIGH_LOAD:
            # Same useful output, every power setpoint raised (ASSUMPTION SIMULATED).
            mag = self.magnitude if self.magnitude is not None else DEFAULT_HIGH_LOAD_MAGNITUDE
            model.power_scale = 1.0 + mag
        elif self.scenario == Scenario.PRODUCTION_SURGE:
            # Natural surge: more heats per day (shorter idle gaps), same
            # per-kg melting physics (ASSUMPTION SIMULATED). idle_scale maps
            # the requested production uplift (calibrated: 0.30 -> ~+30 %).
            mag = self.magnitude if self.magnitude is not None else DEFAULT_SURGE_MAGNITUDE
            if hasattr(model, "idle_scale"):
                model.idle_scale = max(0.0, 1.0 - 2.6 * mag)
        elif self.scenario == Scenario.EQUIPMENT_DEGRADATION:
            # Gradual degradation: vibration/temperature rise linearly from
            # the window start to magnitude at the window end; power AND
            # current rise toward energy_penalty at the same useful output
            # (extra mechanical load at nominal voltage, P = sqrt(3)*V*I*PF
            # preserved). energy_penalty = 0 -> HEALTH-ONLY anomaly: the
            # electrical operating point stays NORMAL, only vibration and
            # temperature witness the fault.
            mag = self.magnitude if self.magnitude is not None else DEFAULT_DEGRADATION_MAGNITUDE
            pen = self.energy_penalty if self.energy_penalty is not None else DEFAULT_ENERGY_PENALTY
            progress = (elapsed_h - self.scenario_start_h) / max(self.scenario_duration_h, 1e-9)
            progress = min(1.0, max(0.0, progress))
            if hasattr(model, "health_ramp"):
                model.health_ramp = mag * progress
            if hasattr(model, "power_ramp"):
                model.power_ramp = pen * progress
        else:
            raise AssertionError(f"unhandled scenario {self.scenario}")  # pragma: no cover
        return model.step(index, dt_h), True

    @staticmethod
    def _reset_knobs(model) -> None:
        """Restore NORMAL knobs (idempotent; every model carries power_scale)."""
        model.power_scale = 1.0
        if hasattr(model, "idle_scale"):
            model.idle_scale = 1.0
        if hasattr(model, "force_state"):
            model.force_state = None
        if hasattr(model, "force_loaded"):
            model.force_loaded = None
        if hasattr(model, "health_ramp"):
            model.health_ramp = 0.0
        if hasattr(model, "power_ramp"):
            model.power_ramp = 0.0

    def run(self) -> tuple[list[dict], list[dict]]:
        rng = np.random.default_rng(self.seed)
        start = self.end - timedelta(hours=self.hours)
        self._last_start = start
        dt_h = self.step_s / 3600.0
        telemetry: list[dict] = []
        # per-machine, per-hour production accumulation
        prod_acc: dict[tuple[str, int], dict] = {}
        for spec in self.machines:
            model = make_machine(spec.machine_id, spec.machine_type, spec.rated_power_kw, rng)
            if hasattr(model, "day_phase_h"):
                # Anchor the compressor demand profile to wall-clock time.
                model.day_phase_h = start.hour + start.minute / 60.0 + start.second / 3600.0
            for i in range(self.steps):
                # First-row alignment: ts = start + i*step, so telemetry
                # buckets hold 12 rows spanning 55 min (coverage ~92 %) and
                # the production hour index derived from i matches the
                # telemetry bucket exactly (same step set -> production,
                # state shares and energy all cover the same steps; only the
                # cumulative-counter delta inherently spans one step less).
                ts = start + timedelta(seconds=i * self.step_s)
                elapsed_h = (i * self.step_s) / 3600.0
                s, _ = self._scenario_step(model, spec, i, dt_h, elapsed_h)
                omit = self.omit_health_signals
                telemetry.append(
                    {
                        "machine_id": spec.machine_id,
                        "ts": ts.isoformat(),
                        "voltage_v": s.voltage_v,
                        "current_a": None if omit else s.current_a,
                        "power_kw": s.power_kw,
                        "reactive_power_kvar": s.reactive_power_kvar,
                        "power_factor": s.power_factor,
                        "energy_kwh": s.energy_kwh,
                        "vibration_mm_s": None if omit else s.vibration_mm_s,
                        "temperature_c": None if omit else s.temperature_c,
                        "rpm": s.rpm,
                        "runtime_h": s.runtime_h,
                        "machine_state": s.machine_state,
                        "source": "SIMULATED",
                    }
                )
                hour_idx = int((i * self.step_s) // 3600)
                key = (spec.machine_id, hour_idx)
                acc = prod_acc.setdefault(key, {"qty": 0.0, "run_h": 0.0})
                acc["qty"] += s.production_rate_kg_h * dt_h
                acc["run_h"] += dt_h if s.machine_state not in ("idle", "stopped", "shutdown") else 0.0
        production: list[dict] = []
        for (mid, h), acc in sorted(prod_acc.items()):
            total = round(acc["qty"], 3)
            rejected = round(total * REJECT_FRACTION, 3)
            good = round(total - rejected, 3)
            ws = start + timedelta(hours=h)
            production.append(
                {
                    "machine_id": mid,
                    "window_start": ws.isoformat(),
                    "window_end": (ws + timedelta(hours=1)).isoformat(),
                    "qty_total_kg": total,
                    "qty_good_kg": good,
                    "qty_rejected_kg": rejected,
                    "batch_id": f"SIM-{mid}-h{h:03d}",
                    "operating_time_h": round(acc["run_h"], 4),
                    "source": "SIMULATED",
                }
            )
        return telemetry, production


def write_csv(telemetry: list[dict], production: list[dict], path: str) -> tuple[str, str]:
    """Telemetry -> path; production -> sibling path with _production suffix."""
    import os

    base, ext = os.path.splitext(path)
    prod_path = f"{base}_production{ext or '.csv'}"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(telemetry[0].keys()))
        w.writeheader()
        w.writerows(telemetry)
    with open(prod_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(production[0].keys()))
        w.writeheader()
        w.writerows(production)
    return path, prod_path


def post_to_api(telemetry: list[dict], production: list[dict], api_base: str, chunk: int = 500) -> dict:
    import httpx

    totals = {"telemetry": {"accepted": 0, "suspect": 0, "bad": 0, "duplicate": 0},
              "production": {"accepted": 0, "suspect": 0, "bad": 0, "duplicate": 0}}
    with httpx.Client(base_url=api_base, timeout=60.0) as client:
        for i in range(0, len(telemetry), chunk):
            r = client.post("/telemetry?backfill=true", json={"records": telemetry[i:i + chunk]})
            r.raise_for_status()
            for k, v in r.json().items():
                totals["telemetry"][k] += v
        for i in range(0, len(production), chunk):
            r = client.post("/production?backfill=true", json={"records": production[i:i + chunk]})
            r.raise_for_status()
            for k, v in r.json().items():
                totals["production"][k] += v
    return totals
