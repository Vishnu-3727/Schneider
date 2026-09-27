"""Overview section (spec §10) — API-backed only, Phase 1 fields."""

import pandas as pd
import streamlit as st

from apps.dashboard.client import get_summary

st.title("Overview")
st.caption("Source: SIMULATED — prototype data, requires plant validation.")

summary = get_summary(24)
if isinstance(summary, dict) and "error" in summary:
    st.error(summary["error"])
    st.stop()

rows = summary.get("machines", [])
total_energy = sum(m["energy_kwh"] for m in rows)
total_prod = sum(m["production_good_kg"] for m in rows)
c1, c2 = st.columns(2)
c1.metric("Energy today (kWh, SIMULATED)", f"{total_energy:.1f}")
c2.metric("Production today (kg good, SIMULATED)", f"{total_prod:.1f}")
st.dataframe(pd.DataFrame(rows))
