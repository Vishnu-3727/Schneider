"""ONE evaluate(schedule) for every schedule: projected energy, peak, cost,
production (pure).

Energy uses the stored Phase-2 baseline coefficients for the machine
(b_prod kWh/kg carries melting energy; per-state kWh/h for heating /
holding / idle; intercept spread uniformly over the horizon). Peak uses
per-state median powers from NORMAL telemetry (DERIVED). Cost uses the
tariff periods; with no tariff the cost term is absent and reported
unavailable — a price is never invented. Every output number is PROJECTED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from services.optimization.constraints import HeatPlan, Schedule, AuxTask

SOURCE = "PROJECTED"

# Production tolerance for comparability check (fraction, e.g. 0.01 = 1%)
# Read from config at runtime; this is the fallback default.
OPT_COMPARABLE_PROD_TOL = 0.01


@dataclass
class EnergyModel:
    """Furnace baseline energy model (from the stored Phase-2 fit)."""
    b_prod_kwh_per_kg: float
    b_heating_kwh_per_h: float
    b_holding_kwh_per_h: float
    b_idle_kwh_per_h: float
    intercept_kwh: float
    interval_h: float = 1.0
    baseline_id: str = ""


@dataclass
class StatePowers:
    """Per-state median power (kW) from NORMAL telemetry, DERIVED."""
    powers_kw: dict[str, float]


@dataclass
class TariffPeriod:
    name: str
    start_h: float  # hour of day, local, inclusive
    end_h: float  # exclusive; <= start_h wraps past midnight
    energy_inr_per_kwh: float
    demand_inr_per_kw: float | None = None


@dataclass
class EvalResult:
    energy_kwh: float
    peak_kw: float
    cost_inr: float | None
    cost_status: str  # "ok" | "unavailable (no tariff)"
    production_kg: float
    n_heats: int
    slot_states: list[str]
    energy_by_state_kwh: dict[str, float] | None = None
    source: str = SOURCE

    def to_dict(self) -> dict:
        d = {
            "energy_kwh": {"value": self.energy_kwh, "unit": "kWh",
                           "source": self.source},
            "peak_kw": {"value": self.peak_kw, "unit": "kW",
                        "source": self.source},
            "cost_inr": ({"value": self.cost_inr, "unit": "INR",
                           "source": self.source}
                         if self.cost_inr is not None else None),
            "cost_status": self.cost_status,
            "production_kg": {"value": self.production_kg, "unit": "kg",
                              "source": self.source},
            "n_heats": self.n_heats,
        }
        if self.energy_by_state_kwh is not None:
            d["energy_by_state_kwh"] = {
                k: {"value": v, "unit": "kWh", "source": self.source}
                for k, v in self.energy_by_state_kwh.items()
            }
        return d


def rate_at(periods: list[TariffPeriod], tod_h: float) -> float:
    for p in periods:
        if p.start_h <= p.end_h:
            if p.start_h <= tod_h < p.end_h:
                return p.energy_inr_per_kwh
        elif tod_h >= p.start_h or tod_h < p.end_h:
            return p.energy_inr_per_kwh
    raise ValueError(f"tariff periods leave hour {tod_h} uncovered")


def evaluate(
    schedule: Schedule,
    energy_model: EnergyModel,
    state_powers: StatePowers,
    tariff: list[TariffPeriod] | None,
    horizon_start: datetime,
) -> EvalResult:
    slot_h = schedule.slot_min / 60.0
    n = schedule.n_slots
    states = ["idle"] * n
    aux_kw = [0.0] * n
    for h in schedule.heats:
        t = h.start_slot
        for _ in range(h.heating_slots):
            if 0 <= t < n:
                states[t] = "heating"
            t += 1
        for _ in range(h.melting_slots):
            if 0 <= t < n:
                states[t] = "melting"
            t += 1
        for _ in range(h.holding_slots):
            if 0 <= t < n:
                states[t] = "holding"
            t += 1
    for a in schedule.aux:
        for t in range(a.start_slot, a.start_slot + a.duration_slots):
            if 0 <= t < n:
                aux_kw[t] += a.power_kw
    em = energy_model
    intercept_per_slot = em.intercept_kwh * (n * slot_h / em.interval_h) / n if n else 0.0
    # Production-term energy (b_prod * charge) spread over each heat's
    # own melting slots, so per-slot cost follows the tariff correctly.
    melt_energy = [0.0] * n
    for h in schedule.heats:
        if h.melting_slots > 0:
            per_slot = em.b_prod_kwh_per_kg * h.charge_kg / h.melting_slots
            mt = h.start_slot + h.heating_slots
            for t in range(mt, mt + h.melting_slots):
                if 0 <= t < n:
                    melt_energy[t] += per_slot
    slot_energy = []
    slot_power = []
    for t, st in enumerate(states):
        e = intercept_per_slot + aux_kw[t] * slot_h + melt_energy[t]
        if st == "heating":
            e += em.b_heating_kwh_per_h * slot_h
        elif st == "holding":
            e += em.b_holding_kwh_per_h * slot_h
        elif st != "melting":
            e += em.b_idle_kwh_per_h * slot_h
        slot_energy.append(e)
        slot_power.append(state_powers.powers_kw.get(st, 0.0) + aux_kw[t])
    energy = sum(slot_energy)
    peak = max(slot_power) if slot_power else 0.0
    production = sum(h.charge_kg for h in schedule.heats)
    # Energy breakdown by state (PROJECTED): split the heating term into
    # base heating vs cold-gap reheat (HeatPlan.reheat_slots is a subset of
    # heating_slots); melting carries the b_prod production term; idle slots
    # carry the b_idle term; intercept is spread uniformly; aux is extra.
    # Keys sum to the total energy (up to rounding).
    n_heating = sum(1 for st in states if st == "heating")
    n_holding = sum(1 for st in states if st == "holding")
    n_idle = sum(1 for st in states if st == "idle")
    reheat_slots_total = sum(max(0, h.reheat_slots or 0) for h in schedule.heats)
    reheat_slots_total = min(reheat_slots_total, n_heating)
    base_heating_slots = n_heating - reheat_slots_total
    melt_kwh = sum(melt_energy)
    heating_kwh = base_heating_slots * em.b_heating_kwh_per_h * slot_h
    reheat_kwh = reheat_slots_total * em.b_heating_kwh_per_h * slot_h
    holding_kwh = n_holding * em.b_holding_kwh_per_h * slot_h
    idle_kwh = n_idle * em.b_idle_kwh_per_h * slot_h
    intercept_kwh_total = intercept_per_slot * n if n else 0.0
    aux_kwh = sum(a.power_kw * a.duration_slots * slot_h for a in schedule.aux)
    energy_by_state = {
        "heating": heating_kwh,
        "melting": melt_kwh,
        "holding": holding_kwh,
        "idle": idle_kwh,
        "reheat": reheat_kwh,
        "intercept": intercept_kwh_total,
        "aux": aux_kwh,
    }
    if tariff:
        cost = 0.0
        for t, e in enumerate(slot_energy):
            ts = horizon_start + timedelta(minutes=t * schedule.slot_min)
            cost += e * rate_at(tariff, ts.hour + ts.minute / 60.0 + ts.second / 3600.0)
        demand_rates = [p.demand_inr_per_kw for p in tariff
                        if p.demand_inr_per_kw is not None]
        if demand_rates:
            cost += peak * max(demand_rates)
        cost_status = "ok"
    else:
        cost, cost_status = None, "unavailable (no tariff)"
    return EvalResult(energy_kwh=energy, peak_kw=peak, cost_inr=cost,
                      cost_status=cost_status, production_kg=production,
                      n_heats=len(schedule.heats), slot_states=states,
                      energy_by_state_kwh=energy_by_state)


def assign_reheat(
    heats: list[HeatPlan],
    cold_threshold_slots: int,
    reheat_extra_slots: int,
    first_heat_cold: bool = False,
) -> list[HeatPlan]:
    """ONE reheat rule for both schedules (current AND recommended).

    Gap since the previous heat ended > cold threshold -> the next heat
    gets ``reheat_extra_slots`` carved OUT of its observed heating slots.
    The same gap/end semantics as the scheduler and ``validate()``: the
    previous heat's end includes its own (already assigned) reheat, and the
    first heat's gap is measured from slot 0 exactly like the solver model,
    so ``first_heat_cold`` behaves identically on both sides.

    For reconstructed heats (reheat_slots == 0), ``heating_slots`` is the
    OBSERVED total heating (base + any actual reheat). We carve the rule's
    reheat out of this observed total: base = max(0, observed - reheat_extra),
    reheat = min(observed, reheat_extra) if cold else 0. Total heating_slots
    stays UNCHANGED (preserves observed slot occupancy exactly). If observed
    heating is shorter than the rule's reheat, the shortfall is recorded in
    reheat_slots (capped at observed) rather than extending the heat.

    For scheduler-output heats (reheat_slots > 0), ``heating_slots`` already
    includes reheat; we normalise to base = heating - reheat, then re-apply
    the rule identically (idempotent). Returns the heats sorted by start slot
    (in place).
    """
    heats.sort(key=lambda h: h.start_slot)
    prev_end: int | None = None
    for h in heats:
        observed_heating = h.heating_slots
        # Normalise to base heating: if reheat_slots > 0, it was already set
        # (scheduler output or re-application); otherwise observed_heating is
        # the total observed heating from telemetry.
        if (h.reheat_slots or 0) > 0:
            base = max(0, observed_heating - (h.reheat_slots or 0))
        else:
            # First application on reconstructed heats: observed_heating is
            # the total observed heating. The base is what remains after
            # carving out the rule's reheat (capped at observed).
            base = max(0, observed_heating - reheat_extra_slots)
        gap = h.start_slot - (prev_end if prev_end is not None else 0)
        cold = gap > cold_threshold_slots if (
            prev_end is not None or first_heat_cold) else False
        # Reheat is capped at observed heating; shortfall recorded, no extension.
        h.reheat_slots = min(observed_heating, reheat_extra_slots) if cold else 0
        # Total heating slots stays at observed value (preserves occupancy).
        h.heating_slots = observed_heating
        prev_end = (h.start_slot + h.heating_slots + h.melting_slots
                    + h.holding_slots)
    return heats


def slots_to_heats(
    slot_states: list[str],
    charge_kg: float,
    melting_slots: int,
    holding_slots: int,
    heating_slots: int = 1,
    cold_threshold_slots: int | None = None,
    reheat_extra_slots: int = 0,
    first_heat_cold: bool = False,
) -> list[HeatPlan]:
    """Reconstruct heats from a per-slot dominant-state list (telemetry).

    A heat starts at a heating slot following non-heating; it spans the
    contiguous heating/melting/holding run. Runs without a melting phase
    are not heats (skipped). Holding-only runs are not heats either.

    Each heat keeps its own OBSERVED heating/melting/holding slot counts:
    rescheduling moves heats in time but never changes a heat's intrinsic
    phase durations. When ``cold_threshold_slots`` is given, the shared
    :func:`assign_reheat` rule splits each heat's observed heating into
    base heating + reheat identically to the recommended schedule (without
    it, reheat stays 0 for backward compatibility).
    """
    heats: list[HeatPlan] = []
    t = 0
    n = len(slot_states)
    while t < n:
        if slot_states[t] == "heating" and (t == 0 or slot_states[t - 1] != "heating"):
            start = t
            nh = nm = nhold = 0
            while t < n and slot_states[t] == "heating":
                nh += 1
                t += 1
            while t < n and slot_states[t] == "melting":
                nm += 1
                t += 1
            while t < n and slot_states[t] == "holding":
                nhold += 1
                t += 1
            if nm > 0:
                heats.append(HeatPlan(start_slot=start, heating_slots=nh,
                                      melting_slots=nm, holding_slots=nhold,
                                      charge_kg=charge_kg))
        else:
            t += 1
    if cold_threshold_slots is not None:
        assign_reheat(heats, cold_threshold_slots, reheat_extra_slots,
                      first_heat_cold)
    return heats


def comparability(
    current_eval: EvalResult,
    recommended_eval: EvalResult,
    current_schedule: Schedule,
    recommended_schedule: Schedule,
    tol: float | None = None,
) -> tuple[bool, str]:
    """Check if current and recommended schedules are comparable.
    
    Comparable requires:
    1. Same production (within tolerance)
    2. Same auxiliary task set (same aux energy in breakdown)
    
    Returns (comparable: bool, reason: str)
    """
    if tol is None:
        from apps.backend.config import get_settings
        tol = get_settings().OPT_COMPARABLE_PROD_TOL
    cur_prod = current_eval.production_kg
    rec_prod = recommended_eval.production_kg
    if cur_prod == 0:
        return False, "current production is zero"
    prod_diff_pct = abs(rec_prod - cur_prod) / cur_prod
    if prod_diff_pct > tol:
        return False, (
            f"production differs by {prod_diff_pct:.1%} "
            f"(current {cur_prod:.0f} kg vs recommended {rec_prod:.0f} kg)"
        )
    
    cur_aux = current_eval.energy_by_state_kwh.get("aux", 0.0) if current_eval.energy_by_state_kwh else 0.0
    rec_aux = recommended_eval.energy_by_state_kwh.get("aux", 0.0) if recommended_eval.energy_by_state_kwh else 0.0
    if abs(cur_aux - rec_aux) > 1e-6:
        return False, (
            f"auxiliary tasks differ (current aux {cur_aux:.1f} kWh "
            f"vs recommended aux {rec_aux:.1f} kWh)"
        )
    
    return True, "same production and auxiliary tasks"
