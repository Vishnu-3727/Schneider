"""OR-Tools CP-SAT furnace scheduler (deterministic, pure apart from solve).

Plans n_heats furnace heats (+ optional flexible aux tasks) on the slot
grid. Hard constraints (production, operating/maintenance windows, peak
cap, holding limits, non-overlap, cold reheat) are enforced in the model;
the objective minimises w_energy * kWh + w_peak * peak_kW + w_cost * INR
(cost term only with a tariff). Every output is run through the
independent validate(); a violating output raises, never returns.

Determinism: single worker + fixed random_seed + the deterministic
CP-SAT budget (max_deterministic_time, from config) as the primary
budget. The wall-clock max_time_in_seconds is only a safety net (kept
larger); if it is ever hit on a FEASIBLE-but-unproven solve the result
is returned as TIMEOUT, never as a silently machine-load-dependent
FEASIBLE plan.

Status: OPTIMAL | FEASIBLE | INFEASIBLE | TIMEOUT | BASELINE_UNAVAILABLE.
INFEASIBLE carries an explanation naming the conflicting constraint
group(s), found by necessary-condition checks (one group at a time).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from services.optimization.constraints import AuxPlan, OptConstraints, Schedule
from services.optimization.evaluate import (
    EnergyModel,
    EvalResult,
    HeatPlan,
    StatePowers,
    TariffPeriod,
    evaluate,
    rate_at,
)
from services.optimization.validate import validate


@dataclass
class SchedulerResult:
    status: str
    schedule: Schedule | None
    metrics: EvalResult | None
    explanation: str


def _operating_slots(c: OptConstraints) -> int:
    return sum(max(0, we - ws) for ws, we in c.operating_windows)


def _available_slots(c: OptConstraints) -> int:
    total = _operating_slots(c)
    blocked = 0
    for ms, me in c.maintenance_windows:
        for ws, we in c.operating_windows:
            blocked += max(0, min(me, we) - max(ms, ws))
    return total - blocked


def explain_infeasible(
    c: OptConstraints,
    state_powers: StatePowers,
) -> str:
    """Name the conflicting constraint group(s), one group at a time."""
    mins = [c.template_for(h).min_heat_slots for h in range(c.n_heats)]
    total_min = sum(mins)
    groups: list[str] = []
    if total_min > _operating_slots(c):
        groups.append(
            f"operating-hours: required heats x minimum heat duration "
            f"(total minimum {total_min} slots) "
            f"> available operating slots ({_operating_slots(c)})")
    longest_window = max((we - ws) for ws, we in c.operating_windows)
    if mins and max(mins) > longest_window:
        groups.append(
            f"operating-hours: one minimum heat ({max(mins)} slots) does not "
            f"fit in any single operating window (longest {longest_window} slots)")
    if total_min > _available_slots(c):
        groups.append(
            f"maintenance: required heats x minimum heat duration "
            f"(total minimum {total_min} slots) > operating slots outside "
            f"maintenance ({_available_slots(c)})")
    if c.peak_cap_kw is not None:
        phase_p = {k: state_powers.powers_kw.get(k, 0.0)
                   for k in ("heating", "melting", "holding")}
        top = max(phase_p.values())
        if c.peak_cap_kw < top:
            worst = max(phase_p, key=lambda k: phase_p[k])
            groups.append(
                f"peak-cap: cap {c.peak_cap_kw} kW is below a single heat's "
                f"{worst} power ({top:.1f} kW); every heat melts, so no "
                f"schedule can satisfy it")
    for a in c.aux_tasks:
        if a.window_end_slot - a.window_start_slot < a.duration_slots:
            groups.append(
                f"aux-window: task {a.name} needs {a.duration_slots} slots but "
                f"its window [{a.window_start_slot}, {a.window_end_slot}) holds "
                f"{a.window_end_slot - a.window_start_slot}")
    if not groups:
        groups.append(
            "no single group is over-subscribed: the conflict is a combination "
            "(e.g. holding limits x window edges, or aux tasks x peak cap "
            "inside narrow windows)")
    return "NO FEASIBLE PLAN: " + "; ".join(groups)


def plan(
    c: OptConstraints,
    energy_model: EnergyModel,
    state_powers: StatePowers,
    tariff: list[TariffPeriod] | None,
    horizon_start: datetime,
) -> SchedulerResult:
    n = c.n_slots
    if n <= 0:
        return SchedulerResult("INFEASIBLE", None, None,
                               "NO FEASIBLE PLAN: empty horizon")
    for h in range(c.n_heats):
        hh = c.template_for(h)
        if hh.min_hold_slots > hh.max_hold_slots:
            return SchedulerResult(
                "INFEASIBLE", None, None,
                "NO FEASIBLE PLAN: min_hold > max_hold in heat template "
                f"for heat {h}")
    pre = explain_infeasible(c, state_powers)
    if not pre.startswith("NO FEASIBLE PLAN: no single group"):
        # A necessary-condition check fired: provably infeasible, skip solve.
        return SchedulerResult("INFEASIBLE", None, None, pre)
    if c.n_heats == 0 and not c.aux_tasks:
        sched = Schedule(heats=[], aux=[], n_slots=n, slot_min=c.slot_min,
                         horizon_start_iso=c.horizon_start_iso)
        metrics = evaluate(sched, energy_model, state_powers, tariff, horizon_start)
        return SchedulerResult("OPTIMAL", sched, metrics,
                               "OPTIMAL: no heats required; furnace idle")

    slot_h = c.slot_min / 60.0
    m = cp_model.CpModel()
    H = c.n_heats
    # Start-indicator formulation: for each heat, exactly one start slot
    # per phase boundary (heat/melt/hold start + heat end). Per-slot phase
    # activity is a prefix-sum DIFFERENCE (linear equality, no reified
    # comparisons), which gives a tight relaxation and fast solves.
    phases = ("heating", "melting", "holding")
    b_heat: list[list] = []  # heat-start indicators per heat (restricted range)
    b_melt: list[list] = []  # melt-start indicators (full 0..n range)
    b_hold: list[list] = []  # hold-start indicators (full 0..n range)
    b_end: list[list] = []  # heat-end indicators (full 0..n range)
    heat_s, melt_s, hold_s, end_e, cold = [], [], [], [], []
    mins = [c.template_for(h).min_heat_slots for h in range(H)]
    for h in range(H):
        hh = c.template_for(h)
        lo = sum(mins[:h])
        hi = min(n - mins[h], n - sum(mins[h:]))
        if hi < lo:
            return SchedulerResult("INFEASIBLE", None, None,
                                   explain_infeasible(c, state_powers))
        ih = [m.NewBoolVar(f"hs_{h}_{t}") for t in range(lo, hi + 1)]
        im = [m.NewBoolVar(f"ms_{h}_{t}") for t in range(n + 1)]
        io = [m.NewBoolVar(f"ho_{h}_{t}") for t in range(n + 1)]
        ie = [m.NewBoolVar(f"en_{h}_{t}") for t in range(n + 1)]
        m.AddExactlyOne(ih)
        m.AddExactlyOne(im)
        m.AddExactlyOne(io)
        m.AddExactlyOne(ie)
        b_heat.append(ih)
        b_melt.append(im)
        b_hold.append(io)
        b_end.append(ie)
        hs_e = sum(t * b for t, b in zip(range(lo, hi + 1), ih, strict=True))
        ms_e = sum(t * b for t, b in enumerate(im))
        ho_e = sum(t * b for t, b in enumerate(io))
        en_e = sum(t * b for t, b in enumerate(ie))
        heat_s.append(hs_e)
        melt_s.append(ms_e)
        hold_s.append(ho_e)
        end_e.append(en_e)
        cd = m.NewBoolVar(f"cold_{h}")
        cold.append(cd)
        if h == 0 and not c.first_heat_cold:
            m.Add(cd == 0)
        else:
            gap = hs_e - (end_e[h - 1] if h > 0 else 0)
            # cold <=> gap > threshold (whole-slot documented semantics).
            m.Add(gap > c.cold_threshold_slots).OnlyEnforceIf(cd)
            m.Add(gap <= c.cold_threshold_slots).OnlyEnforceIf(cd.Not())
        m.Add(ms_e - hs_e == hh.heating_slots + c.reheat_extra_slots * cd)
        m.Add(ho_e - ms_e == hh.melting_slots)
        m.Add(en_e - ho_e >= hh.min_hold_slots)
        m.Add(en_e - ho_e <= hh.max_hold_slots)
        m.Add(en_e <= n)
        if h > 0:
            m.Add(hs_e >= end_e[h - 1])
        # Each heat sits inside exactly one operating window.
        in_w = [m.NewBoolVar(f"inw_{h}_{w}") for w in range(len(c.operating_windows))]
        for w, (ws, we) in enumerate(c.operating_windows):
            m.Add(hs_e >= ws).OnlyEnforceIf(in_w[w])
            m.Add(en_e <= we).OnlyEnforceIf(in_w[w])
        m.AddExactlyOne(in_w)
        # No overlap with maintenance windows (before or after each one).
        for ms, me in c.maintenance_windows:
            side = m.NewBoolVar(f"mnt_{h}_{ms}")
            m.Add(en_e <= ms).OnlyEnforceIf(side)
            m.Add(hs_e >= me).OnlyEnforceIf(side.Not())

    # Per-slot activity via sparse successor chaining (flow conservation):
    # heating[t] = heating[t-1] + heat_started[t] - melt_started[t].
    # Each row touches 3-4 variables (vs O(N) prefix sums): tight and fast.
    active: dict[tuple[int, int, str], cp_model.IntVar] = {}
    for h in range(H):
        lo = sum(mins[:h])
        prev = {"heating": 0, "melting": 0, "holding": 0}
        for t in range(n):
            # heating inflow = heat start, outflow = melt start, etc.
            inflow = {
                "heating": (b_heat[h][t - lo] if 0 <= t - lo < len(b_heat[h]) else 0,
                            b_melt[h][t] if t <= n else 0),
                "melting": (b_melt[h][t], b_hold[h][t]),
                "holding": (b_hold[h][t], b_end[h][t]),
            }
            for p in phases:
                a = m.NewBoolVar(f"a_{h}_{t}_{p}")
                m.Add(a == prev[p] + inflow[p][0] - inflow[p][1])
                active[(h, t, p)] = a
                prev[p] = a

    # Greedy feasible hint (earliest packing with min holding, skipping
    # maintenance): gives the solver an instant primal bound. Infeasible
    # hints are ignored gracefully; correctness never depends on the hint.
    def _greedy_hint_starts() -> list[int] | None:
        win = sorted(c.operating_windows)
        starts_out: list[int] = []
        cursor = 0
        for hhi in range(H):
            need = mins[hhi]
            placed = None
            for ws, we in win:
                t = max(cursor, ws)
                while t + need <= we:
                    ok = True
                    for ms, me in c.maintenance_windows:
                        if t < me and ms < t + need:
                            t = me
                            ok = False
                            break
                    if ok:
                        placed = t
                        break
                if placed is not None:
                    break
            if placed is None:
                return None
            starts_out.append(placed)
            cursor = placed + need
        return starts_out

    hint = _greedy_hint_starts()
    if hint is not None:
        # Complete assignment hint: every indicator + activity var gets a
        # value, so the solver verifies (instead of searching) first.
        heat_slots = {}
        for h, st in enumerate(hint):
            hhh = c.template_for(h)
            ms = st + hhh.heating_slots
            ho = ms + hhh.melting_slots
            en = st + mins[h]
            heat_slots[h] = (st, ms, ho, en)
            lo = sum(mins[:h])
            for i, b in enumerate(b_heat[h]):
                m.AddHint(b, 1 if lo + i == st else 0)
            for i, b in enumerate(b_melt[h]):
                m.AddHint(b, 1 if i == ms else 0)
            for i, b in enumerate(b_hold[h]):
                m.AddHint(b, 1 if i == ho else 0)
            for i, b in enumerate(b_end[h]):
                m.AddHint(b, 1 if i == en else 0)
            m.AddHint(cold[h], 0)
        for h in range(H):
            st, ms, ho, en = heat_slots[h]
            for t in range(n):
                m.AddHint(active[(h, t, "heating")], 1 if st <= t < ms else 0)
                m.AddHint(active[(h, t, "melting")], 1 if ms <= t < ho else 0)
                m.AddHint(active[(h, t, "holding")], 1 if ho <= t < en else 0)
    # Aux tasks: start-indicator + prefix-sum activity (same trick).
    aux_start: dict[str, cp_model.IntVar] = {}
    aux_active: dict[tuple[str, int], cp_model.IntVar] = {}
    for a in c.aux_tasks:
        lo, hi = a.window_start_slot, a.window_end_slot - a.duration_slots
        if hi < lo:
            return SchedulerResult("INFEASIBLE", None, None,
                                   explain_infeasible(c, state_powers))
        inds = [m.NewBoolVar(f"auxs_{a.name}_{t}") for t in range(lo, hi + 1)]
        m.AddExactlyOne(inds)
        st = sum(t * b for t, b in zip(range(lo, hi + 1), inds, strict=True))
        aux_start[a.name] = st
        prev_b = 0
        for t in range(n):
            start_here = inds[t - lo] if lo <= t <= hi else 0
            stop_here = inds[t - lo - a.duration_slots] \
                if lo <= t - a.duration_slots <= hi else 0
            b = m.NewBoolVar(f"auxa_{a.name}_{t}")
            m.Add(b == prev_b + start_here - stop_here)
            aux_active[(a.name, t)] = b
            prev_b = b
        for ms, me in c.maintenance_windows:
            side = m.NewBoolVar(f"auxmnt_{a.name}_{ms}")
            m.Add(st + a.duration_slots <= ms).OnlyEnforceIf(side)
            m.Add(st >= me).OnlyEnforceIf(side.Not())

    # Per-slot power / energy from the energy model (linear in activity).
    p_kw = {p: state_powers.powers_kw.get(p, 0.0) for p in phases}
    em = energy_model
    melt_slot_e = [em.b_prod_kwh_per_kg * c.template_for(h).charge_kg
                   / max(c.template_for(h).melting_slots, 1) for h in range(H)]
    intercept_slot = em.intercept_kwh * (n * slot_h / em.interval_h) / n if n else 0.0
    peak = m.NewIntVar(0, 10_000_000, "peak_mW")
    SCALE = 1000  # integer milliwatts / milliwatt-hours keep CP-SAT integral
    p_mw = {p: int(round(p_kw[p] * SCALE)) for p in phases}
    heat_mwh = int(round(em.b_heating_kwh_per_h * slot_h * SCALE))
    melt_mwh = [int(round(e * SCALE)) for e in melt_slot_e]
    hold_mwh = int(round(em.b_holding_kwh_per_h * slot_h * SCALE))
    idle_mwh = int(round(em.b_idle_kwh_per_h * slot_h * SCALE))
    icept_mwh = int(round(intercept_slot * SCALE))
    aux_mw = {a.name: int(round(a.power_kw * SCALE)) for a in c.aux_tasks}
    aux_mwh = {a.name: int(round(a.power_kw * slot_h * SCALE)) for a in c.aux_tasks}
    obj_terms = []
    for t in range(n):
        pw_mw = sum(active[(h, t, p)] * p_mw[p] for h in range(H) for p in phases)
        pw_mw += sum(aux_active[(a.name, t)] * aux_mw[a.name] for a in c.aux_tasks)
        m.Add(peak >= pw_mw)
        e_mwh = icept_mwh
        e_mwh += sum(active[(h, t, "heating")] * heat_mwh for h in range(H))
        e_mwh += sum(active[(h, t, "melting")] * melt_mwh[h] for h in range(H))
        e_mwh += sum(active[(h, t, "holding")] * hold_mwh for h in range(H))
        idle_on = m.NewBoolVar(f"idle_{t}")
        any_heat = [active[(h, t, p)] for h in range(H) for p in phases]
        if any_heat:
            m.AddBoolOr(any_heat).OnlyEnforceIf(idle_on.Not())
            m.AddBoolAnd([v.Not() for v in any_heat]).OnlyEnforceIf(idle_on)
        else:
            m.Add(idle_on == 1)
        e_mwh += idle_on * idle_mwh
        e_mwh += sum(aux_active[(a.name, t)] * aux_mwh[a.name]
                     for a in c.aux_tasks)
        obj_terms.append((t, e_mwh))
        # Hard peak cap.
        if c.peak_cap_kw is not None:
            m.Add(pw_mw <= int(round(c.peak_cap_kw * SCALE)))
    # Objective: w_energy*E + w_peak*peak + w_cost*Cost as exact integers.
    # E_raw = milli-kWh, P_raw = milli-kW, C_raw = 1e-4 INR, so the true
    # objective x 1e7 = 10*We*E_raw + 10*Wp*P_raw + Wc*C_raw with
    # Wi = round(w * 1000). Rates are deci-INR (seed tariffs have 1 decimal).
    if min(c.w_energy, c.w_peak, c.w_cost) < 0:
        raise ValueError("objective weights must be >= 0")
    we, wp, wc = (round(c.w_energy * 1000), round(c.w_peak * 1000),
                  round(c.w_cost * 1000))
    obj = 10 * we * sum(e for _, e in obj_terms) + 10 * wp * peak
    if tariff:
        rates_d = []
        for t in range(n):
            ts = horizon_start + timedelta(minutes=t * c.slot_min)
            rates_d.append(
                round(rate_at(tariff, ts.hour + ts.minute / 60.0
                              + ts.second / 3600.0) * 10))
        obj += wc * sum(e * r for (_, e), r in zip(obj_terms, rates_d))
        demand_rates = [p.demand_inr_per_kw for p in tariff
                        if p.demand_inr_per_kw is not None]
        if demand_rates:
            obj += wc * peak * round(max(demand_rates) * 10)
    m.Minimize(obj)

    solver = cp_model.CpSolver()
    # Primary budget: deterministic search effort (machine-load
    # independent, reproducible for identical inputs/config on the same
    # build). Safety net: wall-clock limit, always larger than the
    # deterministic budget (requested wall or deterministic + slack,
    # whichever is larger); hitting it means the result would depend on
    # machine load, so it is a TIMEOUT.
    effective_wall = max(c.time_limit_s, c.deterministic_time + c.wall_slack_s)
    solver.parameters.max_deterministic_time = c.deterministic_time
    solver.parameters.max_time_in_seconds = effective_wall
    solver.parameters.random_seed = c.random_seed
    solver.parameters.num_search_workers = c.num_workers
    import os as _os
    import time as _time
    if _os.environ.get("OPT_LOG_SEARCH"):
        solver.parameters.log_search_progress = True
    _t0 = _time.monotonic()
    status = solver.Solve(m)
    _wall = _time.monotonic() - _t0
    if status == cp_model.OPTIMAL:
        tag = "OPTIMAL"
    elif status == cp_model.FEASIBLE:
        # Safety-net check: a FEASIBLE stop at the wall-clock limit is
        # load-dependent (a faster/slower machine would return a different
        # plan), so it must never be served as a plan.
        if _wall >= effective_wall - 1e-6:
            return SchedulerResult(
                "TIMEOUT", None, None,
                f"solver hit the wall-clock safety net ({effective_wall:.1f}s, "
                f"deterministic budget {c.deterministic_time}); no "
                f"deterministic schedule found")
        tag = "FEASIBLE"
    elif status == cp_model.INFEASIBLE:
        return SchedulerResult("INFEASIBLE", None, None,
                               explain_infeasible(c, state_powers))
    else:  # UNKNOWN / MODEL_INVALID treated as timeout (no solution in budget)
        return SchedulerResult("TIMEOUT", None, None,
                               f"solver returned status {status} within "
                               f"{effective_wall:.1f}s; no schedule found")

    heats = []
    for h in range(H):
        hhh = c.template_for(h)
        st = int(solver.Value(heat_s[h]))
        en = int(solver.Value(end_e[h]))
        ho = int(solver.Value(hold_s[h]))
        is_cold = bool(solver.Value(cold[h]))
        heats.append(HeatPlan(
            start_slot=st,
            heating_slots=hhh.heating_slots + (
                c.reheat_extra_slots if is_cold else 0),
            melting_slots=hhh.melting_slots,
            holding_slots=en - ho,
            charge_kg=hhh.charge_kg,
            reheat_slots=c.reheat_extra_slots if is_cold else 0))
    sched = Schedule(
        heats=sorted(heats, key=lambda x: x.start_slot),
        aux=[AuxPlan(name=a.name, start_slot=int(solver.Value(aux_start[a.name])),
                     duration_slots=a.duration_slots, power_kw=a.power_kw)
             for a in c.aux_tasks],
        n_slots=n, slot_min=c.slot_min, horizon_start_iso=c.horizon_start_iso)
    violations = validate(sched, c, state_powers.powers_kw)
    if violations:
        raise RuntimeError(f"optimizer output violates hard constraints: {violations}")
    metrics = evaluate(sched, energy_model, state_powers, tariff, horizon_start)
    total = metrics.energy_kwh
    expl = (f"{tag}: {H} heats, projected {total:.1f} kWh / peak "
            f"{metrics.peak_kw:.1f} kW"
            + (f" / INR {metrics.cost_inr:.0f}" if metrics.cost_inr is not None
               else " (cost unavailable: no tariff)")
            + f" for {metrics.production_kg:.0f} kg")
    return SchedulerResult(tag, sched, metrics, expl)
