"""JouleMitra Phase 1 dashboard (Streamlit + Plotly), API-backed only.

Phase 1 scope: per-machine energy (kWh), power (kW) trend, production (kg),
machine state, Source: SIMULATED label, quality counts. No SEC/cost/CO2e.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from apps.dashboard.client import get_machines, get_summary, get_telemetry

st.set_page_config(page_title="JouleMitra (Phase 1)", layout="wide")
st.title("JouleMitra — Phase 1 Overview")
st.caption("All values below come from the backend API. Source: SIMULATED (prototype data).")

hours = st.selectbox("Window (hours)", [1, 6, 24, 168], index=2)

summary = get_summary(hours)
if isinstance(summary, dict) and "error" in summary:
    st.error(summary["error"])
    st.stop()

machines = get_machines()
if isinstance(machines, dict) and "error" in machines:
    st.error(machines["error"])
    st.stop()

rows = summary.get("machines", [])
if not rows:
    st.warning("No machines found. Seed the database and run the simulator first.")
    st.stop()

st.subheader("Per-machine summary")
st.dataframe(
    pd.DataFrame([
        {
            "machine": m["machine_id"],
            "type": m["machine_type"],
            "energy_kwh": round(m["energy_kwh"], 2),
            "latest_power_kw": m["latest_power_kw"],
            "production_good_kg": round(m["production_good_kg"], 1),
            "latest_state": m["latest_state"],
            "source": m["source"],
            "quality": m["quality_counts"],
        }
        for m in rows
    ])
)

for m in rows:
    st.markdown(f"### {m['machine_id']} — Source: {m['source']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Energy (kWh)", f"{m['energy_kwh']:.1f}")
    c2.metric("Latest power (kW)", f"{m['latest_power_kw']}")
    c3.metric("Production good (kg)", f"{m['production_good_kg']:.1f}")
    c4.metric("State", f"{m['latest_state']}")
    st.caption(f"Quality counts: {m['quality_counts']} (rows: {m['telemetry_rows']})")

    tel = get_telemetry(m["machine_id"], limit=2000)
    if isinstance(tel, dict) and "error" in tel:
        st.error(tel["error"])
        continue
    if tel:
        df = pd.DataFrame(tel)
        df["ts"] = pd.to_datetime(df["ts"])
        fig = px.line(df.sort_values("ts"), x="ts", y="power_kw",
                      title=f"{m['machine_id']} power (kW) trend")
        st.plotly_chart(fig, use_container_width=True)
