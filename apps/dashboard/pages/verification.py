"""Verification section (Phase 5) — API-backed only.

Record that an APPROVED recommendation was applied, then verify it against
the counterfactual. Savings, cost and CO2 appear only for a VERIFIED
outcome; every other outcome is shown as-is, including failures.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from apps.dashboard.client import (
    create_intervention,
    get_emission_factors,
    get_interventions,
    get_recommendations,
    get_verification,
    verify_intervention,
)

TZ = ZoneInfo("Asia/Kolkata")
BADGE = {"VERIFIED": "✔ VERIFIED", "NOT_VERIFIED": "✖ NOT VERIFIED",
         "NOT_COMPARABLE": "≠ NOT COMPARABLE", "INSUFFICIENT_DATA": "? INSUFFICIENT DATA"}

st.title("Verification — did the action really save energy?")
st.caption("PROJECTED (model estimate) ≠ MEASURED (telemetry) ≠ VERIFIED (counterfactual "
           "check with uncertainty). All data in this prototype is SIMULATED.")


def _err(d) -> bool:
    if isinstance(d, dict) and "error" in d:
        st.error(d["error"])
        return True
    return False


st.subheader("1. Record an applied intervention")
recs = get_recommendations(status="APPROVED")
if not _err(recs):
    approved = recs.get("recommendations", [])
    if not approved:
        st.info("No APPROVED recommendations. Approve one on the Recommendations page first.")
    else:
        pick = st.selectbox("Approved recommendation", approved,
                            format_func=lambda r: f"{r['machine_id']} — {r['title']}")
        iv_type = st.selectbox("What was done", ["REDUCE_IDLE", "REPAIR", "RESCHEDULE"])
        applied_at = st.text_input("Applied at (ISO, with timezone)",
                                   datetime.now(TZ).replace(microsecond=0).isoformat())
        note = st.text_input("What changed (note)", "")
        if st.button("Record as APPLIED"):
            res = create_intervention({"recommendation_id": pick["id"], "type": iv_type,
                                       "applied_at": applied_at, "parameters": {"note": note},
                                       "idempotency_key": f"dash-{pick['id']}"})
            if not _err(res):
                st.success(f"Recorded intervention {res['intervention']['id']} (APPLIED).")

st.subheader("2. Verify an applied intervention")
ivs = get_interventions(status="APPLIED")
if not _err(ivs):
    applied = ivs.get("interventions", [])
    if not applied:
        st.info("No interventions awaiting verification.")
    else:
        iv = st.selectbox("Applied intervention", applied,
                          format_func=lambda r: f"{r['machine_id']} {r['type']} @ {r['applied_at']}")
        start = datetime.fromisoformat(iv["applied_at"])
        c1, c2 = st.columns(2)
        s_iso = c1.text_input("Measurement start", start.isoformat())
        e_iso = c2.text_input("Measurement end", (start + timedelta(days=3)).isoformat())
        if st.button("Verify against counterfactual"):
            res = verify_intervention(iv["id"], s_iso, e_iso)
            if not _err(res):
                st.success(f"Outcome: {BADGE.get(res['verification']['outcome'])}")

st.subheader("3. Results")
vr = get_verification()
if not _err(vr):
    rows = vr.get("verification", [])
    if not rows:
        st.info("No verification results yet.")
    for v in rows:
        st.markdown(f"#### {BADGE.get(v['outcome'], v['outcome'])} — {v['result_class']}")
        st.write(v["explanation"])
        if v["counterfactual_kwh"] is not None:
            st.dataframe(pd.DataFrame([
                {"quantity": "Counterfactual (no intervention)", "kWh": v["counterfactual_kwh"],
                 "class": "DERIVED / PROJECTED"},
                {"quantity": "Actual (measured)", "kWh": v["actual_kwh"],
                 "class": "MEASURED (SIMULATED telemetry)"},
                {"quantity": "Difference", "kWh": v["saving_kwh"], "class": "DERIVED"},
                {"quantity": f"Uncertainty (±, {v['confidence']:.0%} conf.)",
                 "kWh": v["uncertainty_kwh"], "class": "DERIVED"},
            ]), hide_index=True)
        st.caption(f"Production before/after: {v['production_before_kg_h']} / "
                   f"{v['production_after_kg_h']} kg/h. Usable hours: baseline {v['n_baseline']}, "
                   f"measurement {v['n_post']}. Method: {v['method']}.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Verified saving (kWh)",
                  f"{v['verified_saving_kwh']:.1f}" if v["verified_saving_kwh"] is not None else "—")
        cost, co2 = v.get("cost_impact") or {}, v.get("co2_impact") or {}
        c2.metric("Cost impact (INR)",
                  f"{cost['value_inr']:.0f}" if cost.get("value_inr") is not None else "—")
        c3.metric("Estimated CO2 impact (kg CO2)",
                  f"{co2['value_kg']:.1f}" if co2.get("value_kg") is not None else "—")
        if cost.get("tariff_label"):
            st.caption(f"Cost: {cost['tariff_label']}.")
        if co2.get("factor"):
            f = co2["factor"]
            if co2.get("provisional"):
                st.warning(co2["label"] + ". CO2 only (not CO2e).")
            st.caption(f"CO2 factor {f['value']} {f['unit']} ({f['gas_basis']}), {f['source']} "
                       f"{f['version']}, {f['fiscal_year']}, {f['source_class']} — "
                       f"{co2['status']}. {co2.get('reason', '')}")
        for k, d in (("cost", cost), ("CO2", co2)):
            if d.get("status") in ("NOT_APPLICABLE", "UNAVAILABLE"):
                st.caption(f"{k}: {d['status']} — {d.get('reason', '')}")
        st.divider()

with st.expander("Emission factors on record"):
    ef = get_emission_factors()
    if not _err(ef):
        st.dataframe(pd.DataFrame(ef.get("emission_factors", [])), hide_index=True)
