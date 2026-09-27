"""Optimisation section (Phase 4) — API-backed only.

Current vs recommended schedule as a Gantt, a side-by-side table of
projected energy / peak / cost / production, the per-state energy
breakdown, and the solver status with any infeasibility explanation.
Every number is tagged with its evidence class; cost uses the
illustrative tariff until the plant shares its DISCOM order.
"""

from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from apps.dashboard.client import get_machines, get_optimization_schedule

LEGEND = ("PROJECTED (model estimate) ≠ MEASURED (telemetry) ≠ "
          "VERIFIED (Phase 5 before/after check).")

st.title("Optimisation — current vs recommended schedule")
st.caption(f"{LEGEND} Cost uses the illustrative tariff "
           "(ASSUMPTION — replace with the plant DISCOM tariff).")

machines = get_machines()
if isinstance(machines, dict) and "error" in machines:
    st.error(machines["error"])
    st.stop()

ids = [m["id"] if isinstance(m, dict) and "id" in m
       else m.get("machine_id", "") for m in machines]
mid = st.selectbox("Machine", ids)
if not mid:
    st.stop()

run = get_optimization_schedule(machine_id=mid)
if isinstance(run, dict) and "error" in run:
    st.error(run["error"])
    st.stop()
if not run:
    st.info("No optimisation run for this machine yet. Run POST /optimization/run first.")
    st.stop()

st.subheader(f"Status: {run.get('status')} [PROJECTED]")
st.write(run.get("explanation", ""))
if run.get("status") == "INFEASIBLE":
    st.warning("No feasible plan. The explanation above names the conflicting "
               "constraint group(s) — relax one limit with operations, then re-run.")
    st.stop()

# Comparability banner (Phase 4C)
comparable = run.get("comparable")
comparability_reason = run.get("comparability_reason", "")
if comparable is True:
    st.success(f"✅ COMPARABLE: {comparability_reason}")
elif comparable is False:
    st.error(f"❌ NOT COMPARABLE: {comparability_reason}")
    st.caption("Projected deltas are suppressed. Per-kg projected energy (kWh/t) shown below.")


def _gantt_rows(sched: dict, label: str) -> list[dict]:
    if not sched:
        return []
    t0 = datetime.fromisoformat(sched["horizon_start"])
    slot = sched["slot_min"]
    rows = []
    for i, h in enumerate(sched.get("heats", []), start=1):
        t = h["start_slot"]
        for phase in ("heating_slots", "melting_slots", "holding_slots"):
            dur = h.get(phase, 0)
            if dur > 0:
                rows.append({"schedule": label,
                             "task": f"Heat {i} {phase.replace('_slots', '')}",
                             "start": t0 + timedelta(minutes=t * slot),
                             "finish": t0 + timedelta(minutes=(t + dur) * slot)})
                t += dur
    for a in sched.get("aux", []):
        rows.append({"schedule": label, "task": f"aux {a['name']}",
                     "start": t0 + timedelta(minutes=a["start_slot"] * slot),
                     "finish": t0 + timedelta(minutes=a["end_slot"] * slot)})
    return rows


rows = _gantt_rows(run.get("current"), "current") + \
    _gantt_rows(run.get("recommended"), "recommended")
if rows:
    fig = px.timeline(pd.DataFrame(rows), x_start="start", x_end="finish",
                      y="task", color="schedule", title="Schedule Gantt [PROJECTED]")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

metrics = run.get("metrics", {})
cur, rec = metrics.get("current", {}), metrics.get("recommended", {})


def _val(side: dict, key: str):
    v = (side or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _kwh_per_tonne(side: dict) -> float | None:
    e = _val(side, "energy_kwh")
    p = _val(side, "production_kg")
    if e is not None and p is not None and p > 0:
        return round(e / p * 1000, 1)
    return None


# Build comparison table based on comparability
table = []
if comparable is False:
    # Not comparable: show per-kg energy instead of delta
    cur_kwh_t = _kwh_per_tonne(cur)
    rec_kwh_t = _kwh_per_tonne(rec)
    for key, label, unit in (("energy_kwh", "Energy", "kWh"),
                             ("peak_kw", "Peak", "kW"),
                             ("cost_inr", "Cost (illustrative tariff)", "INR"),
                             ("production_kg", "Production", "kg")):
        c, r = _val(cur, key), _val(rec, key)
        table.append({"metric": label, "unit": unit,
                      "current [PROJECTED]": c,
                      "recommended [PROJECTED]": r,
                      "delta (recommended − current) [PROJECTED]": None})
    # Add per-kg rows
    table.append({"metric": "Energy per tonne", "unit": "kWh/t",
                  "current [PROJECTED]": cur_kwh_t,
                  "recommended [PROJECTED]": rec_kwh_t,
                  "delta (recommended − current) [PROJECTED]": None})
else:
    # Comparable: show normal table with deltas
    for key, label, unit in (("energy_kwh", "Energy", "kWh"),
                             ("peak_kw", "Peak", "kW"),
                             ("cost_inr", "Cost (illustrative tariff)", "INR"),
                             ("production_kg", "Production", "kg")):
        c, r = _val(cur, key), _val(rec, key)
        table.append({"metric": label, "unit": unit,
                      "current [PROJECTED]": c,
                      "recommended [PROJECTED]": r,
                      "delta (recommended − current) [PROJECTED]":
                          (r - c) if c is not None and r is not None else None})

st.subheader("Projected energy / peak / cost / production")
st.dataframe(pd.DataFrame(table))

st.subheader("State energy breakdown [PROJECTED]")
br_rows = []
for side, name in ((cur, "current"), (rec, "recommended")):
    br = (side or {}).get("energy_by_state_kwh") or {}
    for state, v in br.items():
        br_rows.append({"schedule": name, "state": state,
                        "kWh [PROJECTED]": v.get("value") if isinstance(v, dict) else v})
if br_rows:
    st.dataframe(pd.DataFrame(br_rows))
else:
    st.info("No per-state breakdown on this run (older run, pre-Phase-4B).")

st.caption(f"Source class: {run.get('source', 'PROJECTED')}. {LEGEND}")
