"""Parameterised NORMAL-scenario factory engine (SIMULATED data).

Class names make simulation explicit: SimulatedFactory, SimulatedScenario.
Only NORMAL is implemented in Phase 1; other Scenario members raise
NotImplementedError with a Phase 2+ message.
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
    ) -> None:
        self.scenario = Scenario(scenario)
        if self.scenario != Scenario.NORMAL:
            raise NotImplementedError(
                f"Scenario {self.scenario.value} is Phase 2+ work; only NORMAL is implemented in Phase 1."
            )
        self.machines = machines
        self.hours = hours
        self.step_s = step_s
        self.seed = seed
        self.tz = ZoneInfo(tz)
        self.end = end or datetime.now(self.tz)
        self.steps = int(hours * 3600 / step_s)

    def run(self) -> tuple[list[dict], list[dict]]:
        rng = np.random.default_rng(self.seed)
        start = self.end - timedelta(hours=self.hours)
        dt_h = self.step_s / 3600.0
        telemetry: list[dict] = []
        # per-machine, per-hour production accumulation
        prod_acc: dict[tuple[str, int], dict] = {}
        for spec in self.machines:
            model = make_machine(spec.machine_id, spec.machine_type, spec.rated_power_kw, rng)
            for i in range(self.steps):
                ts = start + timedelta(seconds=(i + 1) * self.step_s)
                s = model.step(i, dt_h)
                telemetry.append(
                    {
                        "machine_id": spec.machine_id,
                        "ts": ts.isoformat(),
                        "voltage_v": s.voltage_v,
                        "current_a": s.current_a,
                        "power_kw": s.power_kw,
                        "reactive_power_kvar": s.reactive_power_kvar,
                        "power_factor": s.power_factor,
                        "energy_kwh": s.energy_kwh,
                        "vibration_mm_s": s.vibration_mm_s,
                        "temperature_c": s.temperature_c,
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
