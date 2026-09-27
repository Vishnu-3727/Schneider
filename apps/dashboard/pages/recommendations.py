"""Recommendations section (Phase 4B) — API-backed only.

Every field of each recommendation, with Accept / Reject buttons.
Human-in-the-loop only: accepting a recommendation never executes
anything and never marks it verified (verification is Phase 5 work).
"""

import streamlit as st

from apps.dashboard.client import (
    acknowledge_recommendation,
    get_recommendations,
)

LEGEND = ("PROJECTED (model estimate) ≠ MEASURED (telemetry) ≠ "
          "VERIFIED (Phase 5 before/after check).")

st.title("Recommendations — human review")
st.caption(f"{LEGEND} Nothing here is executed; an accepted row stays "
           "NOT_VERIFIED until a Phase 5 before/after check.")

status_filter = st.selectbox("Status", ["PENDING_REVIEW", "CONFLICT",
                                        "ACCEPTED", "REJECTED", "ALL"], index=0)

data = get_recommendations(status=None if status_filter == "ALL" else status_filter)
if isinstance(data, dict) and "error" in data:
    st.error(data["error"])
    st.stop()

rows = data.get("recommendations", [])
if not rows:
    st.info("No recommendations. Run POST /recommendations/generate first.")
    st.stop()

for r in rows:
    st.markdown(f"### {r['title']} — {r['status']} [{r['source_class']}]")
    st.write(f"Machine/process: {r['machine_id']} · Severity: {r['severity']} · "
             f"Confidence: {r['confidence']} ({r.get('confidence_reason', '')})")
    st.write(f"Reason: {r['reason']}")
    st.write(f"Proposed action: {r['proposed_action']}")
    eff = r.get("expected_effect")
    if eff:
        st.write(f"Expected effect [PROJECTED]: Δenergy {eff.get('projected_kwh_delta')} kWh, "
                 f"Δpeak {eff.get('projected_peak_kw_delta')} kW, "
                 f"Δcost {eff.get('projected_cost_inr_delta')} INR "
                 "(illustrative tariff; requires plant validation).")
    else:
        st.write("Expected effect: not quantified [no defensible quantity].")
    st.write(f"Evidence: {r.get('evidence')}")
    st.write(f"Constraints considered: {r.get('constraints_considered')}")
    st.write(f"Assumptions: {r.get('assumptions')}")
    st.write(f"Source: {r.get('source_module')} [{r.get('source_class')}] · "
             f"Verification: {r.get('verification_status')}")
    if r.get("status") == "CONFLICT":
        st.warning(f"Conflict: {r.get('conflict_note')} "
                   f"(with {r.get('conflict_with')}). Both rows are kept.")
    if r.get("status") in ("PENDING_REVIEW", "CONFLICT"):
        c1, c2 = st.columns(2)
        if c1.button("Accept", key=f"acc-{r['id']}"):
            res = acknowledge_recommendation(r["id"], "ACCEPTED", "accepted from dashboard")
            if "error" in res:
                st.error(res["error"])
            else:
                st.success(f"Accepted {r['id']} — still {res.get('verification_status')}.")
                st.rerun()
        if c2.button("Reject", key=f"rej-{r['id']}"):
            res = acknowledge_recommendation(r["id"], "REJECTED", "rejected from dashboard")
            if "error" in res:
                st.error(res["error"])
            else:
                st.success(f"Rejected {r['id']}.")
                st.rerun()
    else:
        st.caption(f"Decided: {r['status']} at {r.get('decided_at')} — {r.get('decided_note')}")

st.caption(LEGEND)
