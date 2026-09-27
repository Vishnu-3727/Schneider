"""Energy section (Phase 2) — API-backed only.

Actual vs expected per machine, deviation, SEC trend, baseline quality
(R2, CV(RMSE), n, training window). All values DERIVED from SIMULATED data.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from apps.dashboard.client import get_baselines, get_energy_summary

st.title("Energy — actual vs expected")
st.caption("Derived from SIMULATED data (prototype, requires plant validation).")

TZ = ZoneInfo("Asia/Kolkata")
now = datetime.now(TZ).replace(microsecond=0)
days = st.selectbox("Reference window", [1, 3, 7], index=2)
start = (now - timedelta(days=days)).isoformat()
end = now.isoformat()

summary = get_energy_summary(start, end)
if isinstance(summary, dict) and "error" in summary:
    st.error(summary["error"])
    st.stop()

rows = summary.get("intervals", [])
if not rows:
    st.warning("No intervals in range. Fit a baseline and ingest simulator data first.")
    st.stop()

df = pd.DataFrame(rows)
df["window_start"] = pd.to_datetime(df["window_start"])

st.subheader("Baseline quality (held-out validation on NORMAL data)")
bl = get_baselines()
if isinstance(bl, dict) and "error" not in bl:
    for b in bl.get("baselines", []):
        r2 = b.get("r2_holdout")
        cv = b.get("cv_rmse_pct_holdout")
        nmbe = b.get("nmbe_pct_holdout")
        st.write(
            f"{b['machine_id']} [{b['model_version']}]: "
            f"R²={r2 if r2 is None else round(r2, 3)} (info only), "
            f"CV(RMSE)={cv if cv is None else round(cv, 1)}%, "
            f"NMBE={nmbe if nmbe is None else round(nmbe, 1)}%, "
            f"G14={b.get('acceptance', 'n/a')}, "
            f"n={b['n_intervals']}, window {b['train_start']} .. {b['train_end']}"
        )

aggs = {a["machine_id"]: a for a in summary.get("aggregates", [])}

for mid, g in df.groupby("machine_id"):
    st.markdown(f"### {mid}")
    g = g.sort_values("window_start")
    fig = px.line(g, x="window_start", y=["actual_kwh", "expected_kwh"],
                  title=f"{mid} actual vs expected (kWh per interval)")
    st.plotly_chart(fig, use_container_width=True)
    c1, c2, c3, c4 = st.columns(4)
    dev = g["deviation_pct"].dropna()
    c1.metric("Mean deviation %", f"{dev.mean():.1f}" if len(dev) else "n/a")
    agg = aggs.get(mid, {})
    wsec = agg.get("window_sec_kwh_per_t")
    wst = agg.get("window_sec_status")
    c2.metric("Window SEC (kWh/t, DERIVED)",
              f"{wsec:.0f}" if wsec is not None else (wst or "n/a"))
    sec_hourly = g[g["sec_status"] == "OK"]["sec_kwh_per_t"].dropna()
    c3.metric("Hourly SEC trend mean (kWh/t, hourly only)",
              f"{sec_hourly.mean():.0f}" if len(sec_hourly) else "n/a")
    incomplete = int((~g["complete"]).sum())
    c4.metric("Incomplete intervals", f"{incomplete} (excluded, never silently dropped)")
    npk = agg.get("non_productive_kwh")
    if npk:
        st.write(f"Window totals: {agg.get('total_actual_kwh', 0):.0f} kWh actual vs "
                 f"{agg.get('total_expected_kwh', 0):.0f} kWh expected "
                 f"({agg.get('aggregate_deviation_pct', 0):+.1f}%), "
                 f"non-productive {npk:.0f} kWh.")
    st.dataframe(g[["window_start", "actual_kwh", "expected_kwh", "deviation_pct",
                    "sec_kwh_per_t", "sec_status", "complete"]])
