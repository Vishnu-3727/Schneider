"""Optimizer data model: heat template, constraints, schedules (pure).

One Schedule covers a horizon of N slots (slot_min minutes each) starting
at horizon_start. Each heat = heating phase + melting phase (fixed charge)
+ holding before pour, with min_hold <= holding <= max_hold (hard,
metallurgical). Heats on one furnace never overlap; between heats the
furnace is idle. A gap longer than the cold threshold adds reheat extra
time to the next heat (documented simplification, ASSUMPTIONS A21).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HeatTemplate:
    charge_kg: float
    heating_slots: int
    melting_slots: int
    min_hold_slots: int
    max_hold_slots: int

    @property
    def min_heat_slots(self) -> int:
        return self.heating_slots + self.melting_slots + self.min_hold_slots


@dataclass
class AuxTask:
    """Flexible auxiliary task (e.g. pump/compressor job) of fixed duration
    movable within [window_start_slot, window_end_slot)."""
    name: str
    duration_slots: int
    window_start_slot: int
    window_end_slot: int
    power_kw: float


@dataclass
class OptConstraints:
    n_slots: int
    slot_min: int
    horizon_start_iso: str
    n_heats: int
    heat: HeatTemplate
    operating_windows: list[tuple[int, int]] = field(default_factory=list)
    maintenance_windows: list[tuple[int, int]] = field(default_factory=list)
    peak_cap_kw: float | None = None
    cold_threshold_slots: int = 8
    reheat_extra_slots: int = 1
    first_heat_cold: bool = False
    # Fair-day mode: one template per heat (intrinsic durations observed on
    # the day being re-optimised). When set (length == n_heats), heat i uses
    # heat_templates[i] and the shared ``heat`` is only a fallback shape.
    # Fixed holding (min_hold == max_hold == observed) is deliberate: the
    # constraint model has no representation of schedule-induced waiting
    # inside holding, so holding is NOT shortened below the observed value.
    heat_templates: list[HeatTemplate] | None = None
    aux_tasks: list[AuxTask] = field(default_factory=list)
    w_energy: float = 1.0
    w_peak: float = 10.0
    w_cost: float = 1.0
    time_limit_s: float = 10.0
    deterministic_time: float = 5.0
    wall_slack_s: float = 10.0
    random_seed: int = 42
    num_workers: int = 1

    def __post_init__(self) -> None:
        if not self.operating_windows:
            self.operating_windows = [(0, self.n_slots)]
        if self.heat_templates is not None and len(self.heat_templates) != self.n_heats:
            raise ValueError(
                f"heat_templates length {len(self.heat_templates)} != n_heats {self.n_heats}")

    def template_for(self, i: int) -> HeatTemplate:
        """Intrinsic durations for heat i (per-heat observed or shared nominal)."""
        if self.heat_templates is not None:
            return self.heat_templates[i]
        return self.heat

    def to_dict(self) -> dict:
        return {
            "n_slots": self.n_slots,
            "slot_min": self.slot_min,
            "horizon_start": self.horizon_start_iso,
            "n_heats": self.n_heats,
            "heat": {
                "charge_kg": self.heat.charge_kg,
                "heating_slots": self.heat.heating_slots,
                "melting_slots": self.heat.melting_slots,
                "min_hold_slots": self.heat.min_hold_slots,
                "max_hold_slots": self.heat.max_hold_slots,
            },
            "heat_templates": (
                None if self.heat_templates is None else [
                    {"charge_kg": h.charge_kg, "heating_slots": h.heating_slots,
                     "melting_slots": h.melting_slots,
                     "min_hold_slots": h.min_hold_slots,
                     "max_hold_slots": h.max_hold_slots}
                    for h in self.heat_templates]),
            "operating_windows": [list(w) for w in self.operating_windows],
            "maintenance_windows": [list(w) for w in self.maintenance_windows],
            "peak_cap_kw": self.peak_cap_kw,
            "cold_threshold_slots": self.cold_threshold_slots,
            "reheat_extra_slots": self.reheat_extra_slots,
            "first_heat_cold": self.first_heat_cold,
            "aux_tasks": [a.__dict__ for a in self.aux_tasks],
            "weights": {"energy": self.w_energy, "peak": self.w_peak,
                        "cost": self.w_cost},
            "solver": {"time_limit_s": self.time_limit_s,
                        "deterministic_time": self.deterministic_time,
                        "wall_slack_s": self.wall_slack_s,
                        "effective_wall_s": max(self.time_limit_s,
                                                self.deterministic_time + self.wall_slack_s),
                        "random_seed": self.random_seed,
                        "num_workers": self.num_workers},
        }


@dataclass
class HeatPlan:
    start_slot: int
    heating_slots: int
    melting_slots: int
    holding_slots: int
    charge_kg: float
    reheat_slots: int = 0  # subset of heating_slots added by the cold-gap rule

    @property
    def end_slot(self) -> int:
        return self.start_slot + self.heating_slots + self.melting_slots + self.holding_slots


@dataclass
class AuxPlan:
    name: str
    start_slot: int
    duration_slots: int
    power_kw: float

    @property
    def end_slot(self) -> int:
        return self.start_slot + self.duration_slots


@dataclass
class Schedule:
    heats: list[HeatPlan] = field(default_factory=list)
    aux: list[AuxPlan] = field(default_factory=list)
    n_slots: int = 0
    slot_min: int = 15
    horizon_start_iso: str = ""

    def to_dict(self) -> dict:
        return {
            "n_slots": self.n_slots,
            "slot_min": self.slot_min,
            "horizon_start": self.horizon_start_iso,
            "heats": [h.__dict__ for h in self.heats],
            "aux": [a.__dict__ for a in self.aux],
        }

    @staticmethod
    def from_dict(d: dict) -> Schedule:
        return Schedule(
            heats=[HeatPlan(**h) for h in d.get("heats", [])],
            aux=[AuxPlan(**a) for a in d.get("aux", [])],
            n_slots=d.get("n_slots", 0),
            slot_min=d.get("slot_min", 15),
            horizon_start_iso=d.get("horizon_start", ""),
        )


def templates_from_heats(heats: list[HeatPlan]) -> list[HeatTemplate]:
    """Per-heat templates preserving each heat's intrinsic durations.

    Takes heats in start order (e.g. reconstructed current heats AFTER the
    shared reheat rule has split base heating + reheat): base heating =
    heating minus reheat, melting and holding fixed (min_hold == max_hold
    == observed — holding is never shortened, see ``heat_templates``).
    """
    ordered = sorted(heats, key=lambda h: h.start_slot)
    return [HeatTemplate(
        charge_kg=h.charge_kg,
        heating_slots=max(0, h.heating_slots - (h.reheat_slots or 0)),
        melting_slots=h.melting_slots,
        min_hold_slots=h.holding_slots,
        max_hold_slots=h.holding_slots) for h in ordered]
