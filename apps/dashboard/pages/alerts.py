"""Alerts section (Phase 2) — API-backed only.

Severity shown as text + symbol (never colour-only). Anomaly is energy above
expected baseline for the production achieved — never "failure".
"""

import pandas as pd
import streamlit as st

from apps.dashboard.client import acknowledge_anomaly, get_anomalies

st.title("Alerts — energy anomalies")
st.caption("Derived from SIMULATED data (prototype, requires plant validation).")

SEV_SYMBOL = {"CRITICAL": "⬥ CRITICAL", "WARNING": "▲ WARNING"}

data = get_anomalies()
if isinstance(data, dict) and "error" in data:
    st.error(data["error"])
    st.stop()

rows = data.get("anomalies", [])
if not rows:
    st.info("No anomaly events. Run detection via POST /energy/anomalies/detect first.")
    st.stop()

df = pd.DataFrame(rows)
df["severity_label"] = df["severity"].map(lambda s: SEV_SYMBOL.get(s, s))
st.dataframe(df[["severity_label", "machine_id", "window_start", "window_end",
                 "metric", "rule_id", "score", "deviation_pct", "status"]])

st.subheader("Acknowledge")
for r in rows:
    if r["status"] != "OPEN":
        continue
    c1, c2 = st.columns([5, 1])
    c1.write(f"{SEV_SYMBOL.get(r['severity'], r['severity'])} {r['machine_id']} "
             f"{r['window_start']}..{r['window_end']} ({r['rule_id']})")
    c1.caption(r["evidence"])
    if c2.button("Acknowledge", key=r["id"]):
        res = acknowledge_anomaly(r["id"])
        if isinstance(res, dict) and "error" in res:
            st.error(res["error"])
        else:
            st.success(f"Acknowledged {r['id']}")
            st.rerun()
