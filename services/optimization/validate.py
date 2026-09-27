"""Independent hard-constraint checker (pure, no OR-Tools).

Written independently of the solver: it re-derives every hard constraint
from the schedule + constraints and returns a list of violation strings
([] = valid). The scheduler runs this on every output; a violating output
is a bug and is raised, never returned.
"""

from __future__ import annotations

from services.optimization.constraints import OptConstraints, Schedule


def validate(
    schedule: Schedule,
    constraints: OptConstraints,
    state_powers_kw: dict[str, float] | None = None,
) -> list[str]:
    v: list[str] = []
    c = constraints
    n = c.n_slots
    if schedule.n_slots != n:
        v.append(f"schedule n_slots {schedule.n_slots} != constraints {n}")
    heats = sorted(schedule.heats, key=lambda h: h.start_slot)
    if len(heats) != c.n_heats:
        v.append(f"heat count {len(heats)} != required {c.n_heats}")
    for i, h in enumerate(heats):
        hh = c.template_for(i) if len(heats) == c.n_heats else c.heat
        if h.start_slot < 0 or h.end_slot > n:
            v.append(f"heat {i}: [{h.start_slot}, {h.end_slot}) outside horizon [0, {n})")
        if h.melting_slots != hh.melting_slots:
            v.append(f"heat {i}: melting {h.melting_slots} != template {hh.melting_slots}")
        if not (hh.min_hold_slots <= h.holding_slots <= hh.max_hold_slots):
            v.append(
                f"heat {i}: holding {h.holding_slots} outside "
                f"[{hh.min_hold_slots}, {hh.max_hold_slots}]")
        gap = h.start_slot - (heats[i - 1].end_slot if i > 0 else 0)
        cold = gap > c.cold_threshold_slots if (i > 0 or c.first_heat_cold) else False
        want_heat = hh.heating_slots + (c.reheat_extra_slots if cold else 0)
        if i == 0 and not c.first_heat_cold:
            want_heat = hh.heating_slots
        want_reheat = (c.reheat_extra_slots if cold else 0)
        if i == 0 and not c.first_heat_cold:
            want_reheat = 0
        if (h.reheat_slots or 0) != want_reheat:
            v.append(
                f"heat {i}: reheat {h.reheat_slots} != {want_reheat} "
                f"(gap {gap}, cold={cold})")
        if h.heating_slots != want_heat:
            v.append(
                f"heat {i}: heating {h.heating_slots} != {want_heat} "
                f"(gap {gap}, cold={cold})")
        if i > 0 and h.start_slot < heats[i - 1].end_slot:
            v.append(f"heat {i}: overlaps heat {i - 1}")
        if not any(ws <= h.start_slot and h.end_slot <= we
                   for ws, we in c.operating_windows):
            v.append(f"heat {i}: [{h.start_slot}, {h.end_slot}) not inside one "
                     f"operating window {c.operating_windows}")
        for ms, me in c.maintenance_windows:
            if h.start_slot < me and ms < h.end_slot:
                v.append(f"heat {i}: overlaps maintenance [{ms}, {me})")
    for a in schedule.aux:
        match = next((t for t in c.aux_tasks if t.name == a.name), None)
        if match is None:
            v.append(f"aux {a.name}: not in constraints")
            continue
        if a.duration_slots != match.duration_slots:
            v.append(f"aux {a.name}: duration {a.duration_slots} != {match.duration_slots}")
        if not (match.window_start_slot <= a.start_slot
                and a.end_slot <= match.window_end_slot):
            v.append(f"aux {a.name}: [{a.start_slot}, {a.end_slot}) outside "
                     f"window [{match.window_start_slot}, {match.window_end_slot})")
        for ms, me in c.maintenance_windows:
            if a.start_slot < me and ms < a.end_slot:
                v.append(f"aux {a.name}: overlaps maintenance [{ms}, {me})")
    if c.peak_cap_kw is not None:
        if state_powers_kw is None:
            v.append("peak cap set but no state powers supplied to check it")
        else:
            power = [0.0] * n
            for h in heats:
                t = h.start_slot
                for _ in range(h.heating_slots):
                    if 0 <= t < n:
                        power[t] = max(power[t], state_powers_kw.get("heating", 0.0))
                    t += 1
                for _ in range(h.melting_slots):
                    if 0 <= t < n:
                        power[t] = max(power[t], state_powers_kw.get("melting", 0.0))
                    t += 1
                for _ in range(h.holding_slots):
                    if 0 <= t < n:
                        power[t] = max(power[t], state_powers_kw.get("holding", 0.0))
                    t += 1
            for a in schedule.aux:
                for t in range(a.start_slot, a.end_slot):
                    if 0 <= t < n:
                        power[t] += a.power_kw
            over = [(t, p) for t, p in enumerate(power) if p > c.peak_cap_kw + 1e-9]
            if over:
                worst = max(over, key=lambda x: x[1])
                v.append(f"peak cap {c.peak_cap_kw} kW exceeded at slot {worst[0]} "
                         f"({worst[1]:.1f} kW); {len(over)} slot(s) over cap")
    return v
