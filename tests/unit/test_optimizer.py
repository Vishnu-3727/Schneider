"""Unit tests: evaluate (hand-computed), validate, scheduler statuses,
reproducibility, no-tariff, max_hold/peak-cap tension, property-style
(20 randomised feasible sets, fixed seeds). Pure, no DB."""

import math
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.optimization.constraints import (
    AuxTask,
    HeatPlan,
    HeatTemplate,
    OptConstraints,
    Schedule,
)
from services.optimization.evaluate import (
    EnergyModel,
    StatePowers,
    TariffPeriod,
    evaluate,
)
from services.optimization.scheduler import plan
from services.optimization.validate import validate

TZ = ZoneInfo("Asia/Kolkata")
HS = datetime(2026, 9, 20, 0, 0, tzinfo=TZ)

EM = EnergyModel(b_prod_kwh_per_kg=0.5, b_heating_kwh_per_h=10.0,
                 b_holding_kwh_per_h=5.0, b_idle_kwh_per_h=2.0,
                 intercept_kwh=6.0, interval_h=6.0)
SP = StatePowers({"heating": 50.0, "melting": 80.0, "holding": 30.0, "idle": 5.0})
TARIFF = [TariffPeriod("cheap", 0.0, 2.0, 10.0),
          TariffPeriod("rest", 2.0, 0.0, 5.0)]


def _small_constraints(**kw):
    heat = HeatTemplate(charge_kg=100.0, heating_slots=1, melting_slots=2,
                        min_hold_slots=1, max_hold_slots=2)
    base = {"n_slots": 24, "slot_min": 30, "horizon_start_iso": HS.isoformat(),
            "n_heats": 2, "heat": heat, "time_limit_s": 5.0}
    base.update(kw)
    return OptConstraints(**base)


def test_evaluate_hand_computed():
    # 1h slots: heat = heating(1) + melting(2) + holding(1), then idle.
    sched = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0)], aux=[],
                     n_slots=6, slot_min=60, horizon_start_iso=HS.isoformat())
    res = evaluate(sched, EM, SP, TARIFF, HS)
    assert res.energy_kwh == pytest.approx(75.0)
    assert res.peak_kw == pytest.approx(80.0)
    assert res.cost_inr == pytest.approx(560.0)
    assert res.cost_status == "ok"
    assert res.production_kg == pytest.approx(100.0)
    assert res.n_heats == 1
    assert res.source == "PROJECTED"
    assert res.slot_states == ["heating", "melting", "melting", "holding",
                               "idle", "idle"]


def test_evaluate_no_tariff_cost_absent_never_invented():
    sched = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0)], aux=[],
                     n_slots=6, slot_min=60, horizon_start_iso=HS.isoformat())
    res = evaluate(sched, EM, SP, None, HS)
    assert res.cost_inr is None
    assert res.cost_status == "unavailable (no tariff)"
    assert res.energy_kwh == pytest.approx(75.0)  # energy unaffected


def test_validate_accepts_good_schedule():
    c = _small_constraints()
    sched = Schedule(
        heats=[HeatPlan(0, 1, 2, 1, 100.0), HeatPlan(6, 1, 2, 2, 100.0)],
        aux=[], n_slots=24, slot_min=30, horizon_start_iso=HS.isoformat())
    assert validate(sched, c, SP.powers_kw) == []


def test_validate_catches_every_group():
    c = _small_constraints(peak_cap_kw=200.0,
                           maintenance_windows=[(20, 22)])
    good = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0),
                           HeatPlan(6, 1, 2, 2, 100.0)],
                    aux=[], n_slots=24, slot_min=30,
                    horizon_start_iso=HS.isoformat())
    assert validate(good, c, SP.powers_kw) == []
    # Overlap.
    bad = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0),
                          HeatPlan(2, 1, 2, 1, 100.0)],
                   aux=[], n_slots=24, slot_min=30,
                   horizon_start_iso=HS.isoformat())
    assert any("overlap" in x for x in validate(bad, c, SP.powers_kw))
    # Holding out of range.
    bad = Schedule(heats=[HeatPlan(0, 1, 2, 5, 100.0),
                          HeatPlan(8, 1, 2, 1, 100.0)],
                   aux=[], n_slots=24, slot_min=30,
                   horizon_start_iso=HS.isoformat())
    assert any("holding" in x for x in validate(bad, c, SP.powers_kw))
    # Maintenance overlap.
    bad = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0),
                          HeatPlan(19, 1, 2, 1, 100.0)],
                   aux=[], n_slots=24, slot_min=30,
                   horizon_start_iso=HS.isoformat())
    assert any("maintenance" in x for x in validate(bad, c, SP.powers_kw))
    # Peak cap exceeded (melting 80 + aux 150 > 200).
    from services.optimization.constraints import AuxPlan
    bad = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0),
                          HeatPlan(6, 1, 2, 1, 100.0)],
                   aux=[AuxPlan("pump", 1, 2, 150.0)],
                   n_slots=24, slot_min=30,
                   horizon_start_iso=HS.isoformat())
    assert any("peak cap" in x for x in validate(bad, c, SP.powers_kw))
    # Wrong heat count.
    bad = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0)],
                   aux=[], n_slots=24, slot_min=30,
                   horizon_start_iso=HS.isoformat())
    assert any("heat count" in x for x in validate(bad, c, SP.powers_kw))


def test_scheduler_feasible_passes_validate():
    c = _small_constraints()
    r = plan(c, EM, SP, None, HS)
    assert r.status in ("OPTIMAL", "FEASIBLE"), r.explanation
    assert validate(r.schedule, c, SP.powers_kw) == []
    assert r.metrics.production_kg == pytest.approx(200.0)


def test_scheduler_infeasible_operating_hours():
    c = _small_constraints(n_heats=5)
    c.operating_windows = [(0, 10)]  # 5 heats x 4 slots = 20 > 10
    r = plan(c, EM, SP, None, HS)
    assert r.status == "INFEASIBLE"
    assert "NO FEASIBLE PLAN" in r.explanation
    assert "operating-hours" in r.explanation
    assert r.schedule is None


def test_scheduler_infeasible_peak_cap():
    c = _small_constraints(n_heats=1, peak_cap_kw=50.0)  # melting needs 80
    r = plan(c, EM, SP, None, HS)
    assert r.status == "INFEASIBLE"
    assert "NO FEASIBLE PLAN" in r.explanation
    assert "peak-cap" in r.explanation


def test_scheduler_infeasible_maintenance():
    c = _small_constraints(n_heats=2, maintenance_windows=[(0, 24)])
    r = plan(c, EM, SP, None, HS)
    assert r.status == "INFEASIBLE"
    assert "maintenance" in r.explanation


def test_scheduler_reproducible():
    c = _small_constraints(n_slots=12, n_heats=1)
    r1 = plan(c, EM, SP, TARIFF, HS)
    r2 = plan(c, EM, SP, TARIFF, HS)
    assert r1.status == r2.status == "OPTIMAL"
    assert r1.schedule.to_dict() == r2.schedule.to_dict()
    assert r1.metrics.energy_kwh == r2.metrics.energy_kwh
    assert r1.metrics.cost_inr == r2.metrics.cost_inr


def test_hard_peak_cap_beats_objective_with_aux():
    # Cheap window is 4 slots; heat needs 4, aux needs 2: together they
    # exceed the cap, so the aux must leave the cheap window even though
    # that raises the objective. Overlap would be cheaper but violates.
    from services.optimization.constraints import AuxPlan
    heat = HeatTemplate(charge_kg=100.0, heating_slots=1, melting_slots=2,
                        min_hold_slots=1, max_hold_slots=1)
    c = OptConstraints(n_slots=16, slot_min=30, horizon_start_iso=HS.isoformat(),
                       n_heats=1, heat=heat, peak_cap_kw=100.0,
                       aux_tasks=[AuxTask("pump", 2, 0, 16, 50.0)],
                       time_limit_s=5.0)
    cheap = [TariffPeriod("cheap", 0.0, 2.0, 1.0), TariffPeriod("rest", 2.0, 0.0, 10.0)]
    r = plan(c, EM, SP, cheap, HS)
    assert r.status in ("OPTIMAL", "FEASIBLE"), r.explanation
    assert validate(r.schedule, c, SP.powers_kw) == []
    got = evaluate(r.schedule, EM, SP, cheap, HS)
    # Cap never exceeded on any slot.
    for t, st in enumerate(got.slot_states):
        assert SP.powers_kw[st] + sum(
            a.power_kw for a in r.schedule.aux
            if a.start_slot <= t < a.end_slot) <= 100.0 + 1e-9
    # The violating overlap is cheaper but invalid.
    overlap = Schedule(heats=[HeatPlan(0, 1, 2, 1, 100.0)],
                       aux=[AuxPlan("pump", 1, 2, 50.0)],
                       n_slots=16, slot_min=30, horizon_start_iso=HS.isoformat())
    assert validate(overlap, c, SP.powers_kw) != []
    assert evaluate(overlap, EM, SP, cheap, HS).cost_inr < got.cost_inr


def test_hard_max_hold_beats_objective_with_reheat():
    # Idle is punitively expensive, holding nearly free: the objective
    # wants to hold through the maintenance split, but max_hold forbids
    # it, so the schedule holds to the cap then idles + reheats.
    em = EnergyModel(0.5, 10.0, 1.0, 100.0, 0.0, 1.0)
    heat = HeatTemplate(charge_kg=100.0, heating_slots=1, melting_slots=2,
                        min_hold_slots=1, max_hold_slots=2)
    c = OptConstraints(n_slots=24, slot_min=30, horizon_start_iso=HS.isoformat(),
                       n_heats=2, heat=heat, maintenance_windows=[(10, 14)],
                       cold_threshold_slots=2, reheat_extra_slots=1,
                       time_limit_s=5.0)
    r = plan(c, em, SP, None, HS)
    assert r.status in ("OPTIMAL", "FEASIBLE"), r.explanation
    assert validate(r.schedule, c, SP.powers_kw) == []
    h0 = r.schedule.heats[0]
    assert h0.holding_slots == 2  # max_hold binds
    h1 = r.schedule.heats[1]
    assert h1.start_slot - h0.end_slot > 2  # cold gap forced by maintenance
    assert h1.heating_slots == 2  # reheat applied
    # Holding through maintenance would use less energy but is invalid.
    cheat = Schedule(
        heats=[HeatPlan(h0.start_slot, 1, 2, h0.holding_slots + 8, 100.0),
               HeatPlan(h0.start_slot + 1 + 2 + h0.holding_slots + 8, 1, 2, 1, 100.0)],
        aux=[], n_slots=24, slot_min=30, horizon_start_iso=HS.isoformat())
    assert validate(cheat, c, SP.powers_kw) != []
    assert evaluate(cheat, em, SP, None, HS).energy_kwh < r.metrics.energy_kwh


def _random_feasible(rng: random.Random):
    for _ in range(10):
        n = rng.choice([12, 18, 24])
        hold_min = rng.choice([1, 2])
        hold_max = hold_min + rng.choice([0, 1, 2])
        heat = HeatTemplate(charge_kg=100.0, heating_slots=1, melting_slots=2,
                            min_hold_slots=hold_min, max_hold_slots=hold_max)
        n_heats = rng.choice([1, 2])
        aux = []
        if rng.random() < 0.5:
            dur = rng.choice([1, 2])
            aux = [AuxTask("flex", dur, 0, n, rng.choice([10.0, 30.0]))]
        cap = None if rng.random() < 0.5 else 200.0
        c = OptConstraints(n_slots=n, slot_min=30,
                           horizon_start_iso=HS.isoformat(), n_heats=n_heats,
                           heat=heat, peak_cap_kw=cap, aux_tasks=aux,
                           cold_threshold_slots=rng.choice([2, 4, 8]),
                           w_energy=1.0, w_peak=rng.choice([0.0, 5.0]),
                           w_cost=rng.choice([0.0, 1.0]),
                           time_limit_s=2.0,
                           random_seed=rng.randrange(1 << 30))
        # Necessary-condition pre-screen keeps the property test on
        # feasible ground (deterministic resampling, no skips).
        need = n_heats * heat.min_heat_slots
        if need <= n and (cap is None or cap >= 80.0):
            return c
    raise AssertionError("could not generate a feasible set")


@pytest.mark.parametrize("seed", range(20))
def test_property_validate_always_passes(seed):
    rng = random.Random(2000 + seed)
    c = _random_feasible(rng)
    tariff = TARIFF if c.w_cost else None
    r = plan(c, EM, SP, tariff, HS)
    assert r.status in ("OPTIMAL", "FEASIBLE"), (seed, r.explanation)
    assert validate(r.schedule, c, SP.powers_kw) == []
    assert r.metrics.production_kg == pytest.approx(c.n_heats * 100.0)


def test_slots_to_heats_roundtrip():
    from services.optimization.evaluate import slots_to_heats
    states = (["idle"] * 2 + ["heating", "melting", "melting", "holding"]
              + ["idle"] * 3 + ["heating", "melting", "holding", "holding"]
              + ["idle"])
    heats = slots_to_heats(states, 100.0, 2, 1)
    assert len(heats) == 2
    assert (heats[0].start_slot, heats[0].heating_slots,
            heats[0].melting_slots, heats[0].holding_slots) == (2, 1, 2, 1)
    assert heats[1].start_slot == 9


def test_fairness_same_starts_identical_energy_and_breakdown():
    """Current vs recommended with the same starts must score identically.

    Regression test for the apples-vs-oranges comparison (observed vs
    idealised durations, asymmetric reheat): any non-zero delta here means
    the two representations differ.
    """
    from services.optimization.constraints import templates_from_heats
    from services.optimization.evaluate import slots_to_heats
    # Observed heats differ from any single nominal template (longer
    # heating on heat 0, longer melting on heat 1) with a cold gap.
    states = (["heating"] * 2 + ["melting"] * 2 + ["holding"]
              + ["idle"] * 10
              + ["heating"] + ["melting"] * 3 + ["holding"] * 2
              + ["idle"] * 4)
    n = len(states)
    cur_heats = slots_to_heats(states, 100.0, 2, 1,
                               cold_threshold_slots=8,
                               reheat_extra_slots=1)
    assert len(cur_heats) == 2
    assert cur_heats[0].heating_slots == 2  # observed, not nominal
    assert cur_heats[1].melting_slots == 3  # observed, not nominal
    assert cur_heats[1].reheat_slots == 1  # cold-gap rule fired on current
    current = Schedule(heats=cur_heats, aux=[], n_slots=n, slot_min=60,
                       horizon_start_iso=HS.isoformat())
    cur = evaluate(current, EM, SP, TARIFF, HS)
    # Recommended: the same heats through the optimizer representation,
    # unchanged (same starts, same intrinsic durations, same reheat rule).
    # Templates capture base heating (observed - reheat). Recommended heats
    # use base heating + same reheat (since starts and gaps are identical).
    templates = templates_from_heats(cur_heats)
    rec_heats = [HeatPlan(start_slot=h.start_slot,
                          heating_slots=t.heating_slots + (h.reheat_slots or 0),
                          melting_slots=t.melting_slots,
                          holding_slots=t.min_hold_slots,
                          charge_kg=t.charge_kg,
                          reheat_slots=h.reheat_slots or 0)
                 for h, t in zip(cur_heats, templates, strict=True)]
    recommended = Schedule(heats=rec_heats, aux=[], n_slots=n, slot_min=60,
                           horizon_start_iso=HS.isoformat())
    c = OptConstraints(
        n_slots=n, slot_min=60, horizon_start_iso=HS.isoformat(),
        n_heats=2, heat=HeatTemplate(100.0, 1, 2, 1, 2),
        heat_templates=templates, cold_threshold_slots=8,
        reheat_extra_slots=1, time_limit_s=2.0)
    assert validate(recommended, c, SP.powers_kw) == []
    rec = evaluate(recommended, EM, SP, TARIFF, HS)
    assert rec.energy_kwh == pytest.approx(cur.energy_kwh)
    assert rec.cost_inr == pytest.approx(cur.cost_inr)
    assert rec.peak_kw == pytest.approx(cur.peak_kw)
    assert rec.energy_by_state_kwh.keys() == cur.energy_by_state_kwh.keys()
    for k in cur.energy_by_state_kwh:
        assert rec.energy_by_state_kwh[k] == pytest.approx(
            cur.energy_by_state_kwh[k]), k


def test_tight_windows_no_move_zero_delta():
    """A day where no heat can move must project ~0 energy/cost delta."""
    heat = HeatTemplate(charge_kg=100.0, heating_slots=1, melting_slots=2,
                        min_hold_slots=1, max_hold_slots=1)
    c = OptConstraints(n_slots=8, slot_min=60, horizon_start_iso=HS.isoformat(),
                       n_heats=2, heat=heat,
                       operating_windows=[(0, 8)],
                       cold_threshold_slots=8, reheat_extra_slots=1,
                       time_limit_s=5.0)
    current = Schedule(
        heats=[HeatPlan(0, 1, 2, 1, 100.0), HeatPlan(4, 1, 2, 1, 100.0)],
        aux=[], n_slots=8, slot_min=60, horizon_start_iso=HS.isoformat())
    cur = evaluate(current, EM, SP, TARIFF, HS)
    r = plan(c, EM, SP, TARIFF, HS)
    assert r.status in ("OPTIMAL", "FEASIBLE"), r.explanation
    assert validate(r.schedule, c, SP.powers_kw) == []
    assert r.metrics.energy_kwh == pytest.approx(cur.energy_kwh, abs=1e-6)
    assert r.metrics.cost_inr == pytest.approx(cur.cost_inr, abs=1e-6)
