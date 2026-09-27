"""Equipment section (Phase 3) — API-backed only.

Per machine: health score, state as text + symbol (never colour-only),
vibration / temperature / current trends, top contributing signals, and a
model card (model id, training domain, limitations, evidence class).
All values DERIVED from SIMULATED data unless labelled EXTERNAL_REFERENCE.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from apps.dashboard.client import get_health_models, get_machine_health, get_machines, get_telemetry

st.title("Equipment — machine health")
st.caption("Health values DERIVED from SIMULATED data (prototype, requires plant validation).")

STATE_SYMBOL = {"NORMAL": "● NORMAL", "WARNING": "▲ WARNING", "CRITICAL": "⬥ CRITICAL"}

TZ = ZoneInfo("Asia/Kolkata")
now = datetime.now(TZ).replace(microsecond=0)
days = st.selectbox("Health window", [1, 3, 7], index=2)
start = (now - timedelta(days=days)).isoformat()
end = now.isoformat()

machines = get_machines()
if isinstance(machines, dict) and "error" in machines:
    st.error(machines["error"])
    st.stop()

health = get_machine_health(start_iso=start, end_iso=end)
if isinstance(health, dict) and "error" in health:
    st.error(health["error"])
    st.stop()

models = get_health_models()
if isinstance(models, dict) and "error" in models:
    st.error(models["error"])
    st.stop()

hrows = health.get("health", [])
by_machine: dict[str, list[dict]] = {}
for h in hrows:
    by_machine.setdefault(h["machine_id"], []).append(h)

for m in machines.get("machines", machines if isinstance(machines, list) else []):
    mid = m["machine_id"] if isinstance(m, dict) else m
    st.markdown(f"### {mid}")
    rows = sorted(by_machine.get(mid, []), key=lambda h: h["window_start"])
    if not rows:
        st.info(f"No health intervals for {mid} in range. Run POST /machine-health/score first.")
        continue
    latest = rows[-1]
    c1, c2, c3 = st.columns(3)
    hs = latest["health_score"]
    c1.metric("Health score (DERIVED)",
              f"{hs:.0f}/100" if hs is not None else latest["status"])
    c2.metric("State", STATE_SYMBOL.get(latest["state"], latest["state"]))
    c3.metric("Status", latest["status"])
    st.caption(latest.get("reason", ""))

    contribs = latest.get("contributions") or []
    if contribs:
        st.write("Top contributing signals:")
        st.dataframe(pd.DataFrame(contribs)[["signal", "value", "median", "z",
                                             "pct_change", "weight"]])

    tel = get_telemetry(mid, limit=2000)
    if isinstance(tel, dict) and "error" in tel:
        st.error(tel["error"])
        continue
    if tel:
        df = pd.DataFrame(tel)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.sort_values("ts")
        for sig in ("vibration_mm_s", "temperature_c", "current_a"):
            if sig in df.columns and df[sig].notna().any():
                fig = px.line(df, x="ts", y=sig, title=f"{mid} {sig} trend (SIMULATED)")
                st.plotly_chart(fig, use_container_width=True)

st.subheader("Model cards")
for entry in models.get("models", []):
    meta = entry.get("metadata", {})
    mid = entry.get("model_id", "?")
    with st.expander(f"{mid} — "
                     f"{'available' if entry.get('available') else 'UNAVAILABLE'}; "
                     f"{'scores factory machines' if entry.get('active_for_factory_machines') else 'does NOT score factory machines'}"):
        st.write(f"Training domain: {meta.get('training_domain', 'n/a')}")
        st.write(f"Evidence class: {meta.get('evidence_source_class', 'n/a')}")
        st.write(f"Valid inputs: {meta.get('valid_input_signals', 'n/a')}")
        for lim in meta.get("limitations", []):
            st.write(f"Limitation: {lim}")
        if mid == "pbl-rul":
            st.write(f"Factory status: {entry.get('factory_status', 'n/a')} — "
                     f"{entry.get('factory_reason', '')}")
            art = entry.get("artifact_status", {})
            st.write(f"Artifact: {art.get('status', 'n/a')} — {art.get('reason', '')}")
        if entry.get("error"):
            st.write(f"Error: {entry['error']}")
