"""Insights section (Phase 3) — API-backed only.

Energy + health correlation: category, machine, window, correlation text,
energy evidence, health evidence. Correlation is a diagnostic clue, never
an established cause.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from apps.dashboard.client import get_insights

st.title("Insights — energy + health correlation")
st.caption("DERIVED from SIMULATED data (prototype, requires plant validation). "
           "Correlation is not an established cause.")

CAT_SYMBOL = {"ENERGY_ONLY": "● ENERGY_ONLY",
              "HEALTH_ONLY": "▲ HEALTH_ONLY",
              "COINCIDENT": "⬥ COINCIDENT",
              "ENERGY_ONLY_HEALTH_UNAVAILABLE": "○ ENERGY_ONLY_HEALTH_UNAVAILABLE"}

TZ = ZoneInfo("Asia/Kolkata")
now = datetime.now(TZ).replace(microsecond=0)
days = st.selectbox("Insights window", [1, 3, 7], index=2)
start = (now - timedelta(days=days)).isoformat()
end = now.isoformat()

data = get_insights(start, end)
if isinstance(data, dict) and "error" in data:
    st.error(data["error"])
    st.stop()

rows = data.get("insights", [])
if not rows:
    st.info("No insights in range. Fit baselines/references and run detection + scoring first.")
    st.stop()

df = pd.DataFrame([{"category": CAT_SYMBOL.get(r["category"], r["category"]),
                    "machine": r["machine_id"],
                    "window_start": r["window_start"],
                    "window_end": r["window_end"],
                    "text": r["text"],
                    "next_step": r.get("next_step", "")} for r in rows])
st.dataframe(df)

for r in rows:
    st.markdown(f"### {CAT_SYMBOL.get(r['category'], r['category'])} — {r['machine_id']}")
    st.write(f"Window: {r['window_start']} .. {r['window_end']}")
    st.write(r["text"])
    st.write(f"Next step: {r.get('next_step', '')}")
    ee = r.get("energy_evidence") or {}
    he = r.get("health_evidence") or {}
    if ee:
        st.write(f"Energy evidence: rule {ee.get('rule_id')}, "
                 f"severity {ee.get('severity')}, "
                 f"deviation {ee.get('deviation_pct')}% "
                 f"(window {ee.get('window_start')} .. {ee.get('window_end')})")
    else:
        st.write("Energy evidence: none (energy within its expected range).")
    top = he.get("top_signals") or []
    if top:
        st.write("Health evidence "
                 f"({he.get('n_intervals', 0)} interval(s), states {he.get('states', [])}):")
        st.dataframe(pd.DataFrame(top))
    else:
        st.write(f"Health evidence: none "
                 f"({he.get('n_intervals', 0)} overlapping interval(s), "
                 f"states {he.get('states', [])}).")
