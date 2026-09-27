"""Phase 4B recommendation engine — pure rules, human-in-the-loop only.

Inputs (plain dicts, datetimes or ISO strings for windows):
  anomaly_events:   open energy AnomalyEvents {id, machine_id, window_start,
                    window_end, rule_id, severity, deviation_pct, ...}
  health_rows:      stored machine_health intervals (any status)
  process_analyses: per-day process-efficiency outputs from
                    services.energy.process_efficiency.analyze
  optimization_runs: optimization_run rows (any status incl. INFEASIBLE)
  tariff_label:     e.g. "ILLUSTRATIVE (ASSUMPTION)" | "plant tariff" | "absent"

Output: recommendation dicts (one per rule firing) with every field the
API/DB row needs. Nothing is executed here; every row is PENDING_REVIEW
(or CONFLICT) with verification_status NOT_VERIFIED — verification is
Phase 5 work.

Wording rule: projected/estimated language only. The BANNED_PHRASES below
(saves/saved/saving/achieved/will save/reduces...) must never appear in
any generated text (a unit test scans every field).
"""

from __future__ import annotations

from datetime import datetime

from services.machine_health.correlate import correlate

SOURCE_DERIVED = "DERIVED"
SOURCE_PROJECTED = "PROJECTED"

#: Words/phrases banned from every recommendation text (fact-stating
#: savings language). Generation avoids all reduc*/sav*/achiev* forms.
BANNED_PHRASES = (
    "saves",
    "saved",
    "saving",
    "savings",
    "achieved",
    "will save",
    "reduces cost by",
    "reduces",
    "reduce",
)

OPTIMIZER_RULES = ("R-RESCHEDULE", "R-SEQUENCE")

SEV_RANK = {"CRITICAL": 3, "WARNING": 2}

# Production tolerance for comparability check (fraction, e.g. 0.01 = 1%)
PRODUCTION_TOLERANCE = 0.01


def _as_dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def _sev_rank(sev: str | None) -> int:
    return SEV_RANK.get((sev or "").upper(), 1)


def _base(machine_id: str, rule_id: str, window_start, window_end) -> dict:
    return {
        "machine_id": machine_id,
        "rule_id": rule_id,
        "window_start": _as_dt(window_start).isoformat() if window_start else None,
        "window_end": _as_dt(window_end).isoformat() if window_end else None,
        "status": "PENDING_REVIEW",
        "verification_status": "NOT_VERIFIED",
        "source_module": f"recommendations.engine:{rule_id}",
        "conflict_with": [],
        "conflict_note": "",
    }


def _dedup(rule_id: str, machine_id: str, ws, we, extra: str = "") -> str:
    return "|".join([rule_id, machine_id, str(ws or ""), str(we or ""), extra])


def _num(metrics: dict | None, side: str, key: str):
    try:
        return float(metrics[side][key]["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _breakdown(metrics: dict | None, side: str) -> dict:
    try:
        return {k: float(v["value"]) for k, v in metrics[side]["energy_by_state_kwh"].items()}
    except (KeyError, TypeError, AttributeError, ValueError):
        return {}


def _check_comparability(m: dict) -> tuple[bool, str]:
    """Check if current and recommended schedules are comparable.
    
    Uses the stored comparable/comparability_reason from the optimization_run
    if available (new rows). Falls back to computing from metrics for old rows.
    
    Comparable requires:
    1. Same production (within PRODUCTION_TOLERANCE)
    2. Same auxiliary tasks (same aux energy in breakdown)
    
    Returns (comparable: bool, reason: str)
    """
    # Use stored flag if available (new rows from Phase 4C)
    if "comparable" in m and m["comparable"] is not None:
        return bool(m["comparable"]), m.get("comparability_reason", "same production and auxiliary tasks")
    
    # Fallback: compute from metrics (old rows pre-Phase 4C)
    cur_prod = _num(m, "current", "production_kg")
    rec_prod = _num(m, "recommended", "production_kg")
    if cur_prod is None or rec_prod is None:
        return False, "production data missing"
    if cur_prod == 0:
        return False, "current production is zero"
    prod_diff_pct = abs(rec_prod - cur_prod) / cur_prod
    if prod_diff_pct > PRODUCTION_TOLERANCE:
        return False, f"production differs by {prod_diff_pct:.1%} (current {cur_prod:.0f} kg vs recommended {rec_prod:.0f} kg)"
    
    cur_b = _breakdown(m, "current")
    rec_b = _breakdown(m, "recommended")
    cur_aux = cur_b.get("aux", 0.0)
    rec_aux = rec_b.get("aux", 0.0)
    if abs(cur_aux - rec_aux) > 1e-6:
        return False, f"auxiliary tasks differ (current aux {cur_aux:.1f} kWh vs recommended aux {rec_aux:.1f} kWh)"
    
    return True, "same production and auxiliary tasks"


def generate(
    anomaly_events: list[dict],
    health_rows: list[dict],
    process_analyses: list[dict],
    optimization_runs: list[dict],
    tariff_label: str = "absent",
) -> list[dict]:
    """Fire pure rules over the inputs; return recommendation dicts."""
    recs: list[dict] = []
    insights = correlate(anomaly_events, health_rows)
    by_machine: dict[str, dict] = {}
    for e in anomaly_events:
        by_machine.setdefault(e.get("machine_id"), {"events": [], "findings": [], "runs": []})
        by_machine[e.get("machine_id")]["events"].append(e)
    for a in process_analyses or []:
        by_machine.setdefault(a.get("machine_id"), {"events": [], "findings": [], "runs": []})
        by_machine[a.get("machine_id")]["findings"].append(a)
    for r in optimization_runs or []:
        by_machine.setdefault(r.get("machine_id"), {"events": [], "findings": [], "runs": []})
        by_machine[r.get("machine_id")]["runs"].append(r)

    for mid, bundle in sorted(by_machine.items()):
        recs.extend(_rule_idle(mid, bundle))
        recs.extend(_rule_inspect(mid, bundle, insights))
        recs.extend(_rule_process(mid, insights))
        recs.extend(_rule_optimizer(mid, bundle, tariff_label))
        recs.extend(_rule_noplan(mid, bundle))
    recs.extend(_rule_prioritise(by_machine, insights))
    _apply_conflicts(recs)
    recs.sort(key=lambda r: (r["machine_id"], r["rule_id"], r["dedup_key"]))
    return recs


# --- R-IDLE: avoid unnecessary idle/holding operation -----------------------

IDLE_FINDING_METRICS = ("idle_hours", "non_productive_share", "holding_hours_per_heat")


def _rule_idle(mid: str, bundle: dict) -> list[dict]:
    idle_events = [e for e in bundle["events"] if e.get("rule_id") == "L1_IDLE_WASTE"]
    above = [
        (day.get("day"), f)
        for day in bundle["findings"]
        for f in (day.get("findings") or [])
        if f.get("metric") in IDLE_FINDING_METRICS and f.get("above_reference") is True
    ]
    if not idle_events and not above:
        return []
    sev = "WARNING"
    for e in idle_events:
        if _sev_rank(e.get("severity")) > _sev_rank(sev):
            sev = str(e.get("severity")).upper()
    parts = []
    ev_ids = [str(e.get("id") or e.get("dedup_key") or "?") for e in idle_events]
    key_numbers = []
    for e in idle_events:
        if e.get("deviation_pct") is not None:
            key_numbers.append(f"deviation {e.get('deviation_pct')}%")
    for day, f in above:
        parts.append(f"{f.get('metric')} {f.get('value')} {f.get('unit')} on {day} "
                     f"(reference {f.get('reference')})")
        key_numbers.append(f"{f.get('metric')}={f.get('value')}")
    reason = ("Furnace energised without useful production. "
              + ("; ".join(parts) if parts else "idle-waste anomaly open") + ". "
              + (f"Open idle-waste anomalies: {len(idle_events)}. " if idle_events else ""))
    if len(idle_events) > 0 and len(above) > 0:
        confidence, conf_rule = "HIGH", "anomaly event + process finding agree"
    elif idle_events and any(_sev_rank(e.get("severity")) >= 3 for e in idle_events):
        confidence, conf_rule = "MEDIUM", "single CRITICAL idle-waste anomaly"
    elif len(above) >= 2:
        confidence, conf_rule = "MEDIUM", "two process findings above reference"
    else:
        confidence, conf_rule = "LOW", "single source above reference"
    rec = _base(mid, "R-IDLE",
                min((_as_dt(e["window_start"]) for e in idle_events), default=None) if idle_events else None,
                max((_as_dt(e["window_end"]) for e in idle_events), default=None) if idle_events else None)
    rec.update({
        "title": f"Avoid unnecessary idle/holding operation on {mid}",
        "severity": sev,
        "reason": reason.strip(),
        "evidence": {"anomaly_ids": ev_ids,
                     "process_findings": [f"{d}:{f.get('metric')}" for d, f in above],
                     "key_numbers": key_numbers},
        "constraints_considered": ["operating windows (production plan must still be met)",
                                   "human approval required; nothing is executed automatically"],
        "proposed_action": (f"Review the operating plan for {mid} and power down or "
                            "reassign idle/holding stretches with no planned pour; "
                            "estimated effect is not quantified here — hold for Phase 5 check."),
        "expected_effect": None,
        "confidence": confidence,
        "confidence_reason": conf_rule,
        "assumptions": ["idle stretches are genuinely unneeded (operator to confirm)"],
        "source_class": SOURCE_DERIVED,
        "dedup_key": _dedup("R-IDLE", mid,
                            rec["window_start"], rec["window_end"],
                            "+".join(sorted(ev_ids)) + "+" + "+".join(
                                f"{d}:{f.get('metric')}" for d, f in above)),
    })
    return [rec]


# --- R-INSPECT: inspect equipment (HEALTH_ONLY / COINCIDENT) -----------------

def _rule_inspect(mid: str, bundle: dict, insights: list[dict]) -> list[dict]:
    mine = [i for i in insights
            if i.get("machine_id") == mid and i.get("category") in ("HEALTH_ONLY", "COINCIDENT")]
    out = []
    for ins in mine:
        he = ins.get("health_evidence") or {}
        ee = ins.get("energy_evidence") or {}
        states = he.get("states") or []
        sev = "CRITICAL" if "CRITICAL" in states else "WARNING"
        top = ", ".join(s.get("signal", "?") for s in (he.get("top_signals") or [])[:3]) or "health signals"
        if ins["category"] == "COINCIDENT":
            reason = (f"Energy anomaly coincides with machine-health anomaly ({top}). "
                      "This is a correlation, not an established cause; inspection recommended.")
            conf, conf_rule = ("HIGH", "energy + health anomalies coincide") if sev == "CRITICAL" \
                else ("MEDIUM", "energy + health anomalies coincide")
        else:
            reason = (f"Machine-health anomaly on {mid} ({top}) with energy "
                      "within its expected range. No energy anomaly overlaps this "
                      "window; inspection recommended.")
            conf, conf_rule = "MEDIUM", "health anomaly alone, energy normal"
        rec = _base(mid, "R-INSPECT", ins.get("window_start"), ins.get("window_end"))
        rec.update({
            "title": f"Inspect {mid} ({top})",
            "severity": sev,
            "reason": reason,
            "evidence": {"insight_category": ins["category"],
                         "energy_evidence": ee, "health_evidence": he,
                         "key_numbers": [f"deviation {ee.get('deviation_pct')}%"]
                         if ee.get("deviation_pct") is not None else []},
            "constraints_considered": ["inspection window must suit operations",
                                       "human approval required; nothing is executed automatically"],
            "proposed_action": (f"Inspect {mid} for wear, fouling or sensor drift "
                                f"({top}); compare the health signals against energy "
                                "before scheduling maintenance."),
            "expected_effect": None,
            "confidence": conf,
            "confidence_reason": conf_rule,
            "assumptions": ["sensors reporting correctly (operator to confirm)"],
            "source_class": SOURCE_DERIVED,
            "dedup_key": _dedup("R-INSPECT", mid, ins.get("window_start"),
                                ins.get("window_end"), ins["category"] + "+" + top),
        })
        out.append(rec)
    return out


# --- R-PROCESS: review process/scheduling (ENERGY_ONLY) -------------------------

def _rule_process(mid: str, insights: list[dict]) -> list[dict]:
    out = []
    for ins in [i for i in insights
                if i.get("machine_id") == mid
                and i.get("category") in ("ENERGY_ONLY",
                                          "ENERGY_ONLY_HEALTH_UNAVAILABLE")]:
        ee = ins.get("energy_evidence") or {}
        sev = str(ee.get("severity") or "WARNING").upper()
        if sev not in ("WARNING", "CRITICAL"):
            sev = "WARNING"
        conf = ("MEDIUM", "sustained energy deviation above expected") if sev == "CRITICAL" \
            else ("LOW", "single energy deviation, health unavailable or normal")
        rec = _base(mid, "R-PROCESS", ins.get("window_start"), ins.get("window_end"))
        rec.update({
            "title": f"Review process and scheduling around {mid}",
            "severity": sev,
            "reason": (f"Energy above expected baseline for the production "
                       f"recorded ({ee.get('rule_id')}, deviation "
                       f"{ee.get('deviation_pct')}%) with no overlapping "
                       "machine-health anomaly. "
                       + ("Health data is missing, so a joint assessment is "
                          "not possible. " if ins["category"] == "ENERGY_ONLY_HEALTH_UNAVAILABLE"
                          else "Health signals stayed within NORMAL range. ")),
            "evidence": {"insight_category": ins["category"],
                         "energy_evidence": ee,
                         "key_numbers": ([f"deviation {ee.get('deviation_pct')}%"]
                                         if ee.get("deviation_pct") is not None else [])},
            "constraints_considered": ["production plan for the window",
                                       "human approval required; nothing is executed automatically"],
            "proposed_action": (f"Review load, idle time and scheduling around {mid}; "
                                "inspect the machine if energy stays above expected. "
                                "Estimated effect is not quantified here."),
            "expected_effect": None,
            "confidence": conf[0],
            "confidence_reason": conf[1],
            "assumptions": ["baseline still represents normal operation"],
            "source_class": SOURCE_DERIVED,
            "dedup_key": _dedup("R-PROCESS", mid, ins.get("window_start"),
                                ins.get("window_end"), ins["category"]),
        })
        out.append(rec)
    return out


# --- R-RESCHEDULE + R-SEQUENCE: optimizer-backed ------------------------------

def _run_metrics(run: dict) -> dict | None:
    m = run.get("metrics") or {}
    if not m.get("current") or not m.get("recommended"):
        return None
    return m


def _rule_optimizer(mid: str, bundle: dict, tariff_label: str) -> list[dict]:
    out = []
    for run in bundle["runs"]:
        if run.get("status") not in ("OPTIMAL", "FEASIBLE"):
            continue
        m = _run_metrics(run)
        if m is None:
            continue
        cur_e, rec_e = _num(m, "current", "energy_kwh"), _num(m, "recommended", "energy_kwh")
        cur_p, rec_p = _num(m, "current", "peak_kw"), _num(m, "recommended", "peak_kw")
        cur_c, rec_c = _num(m, "current", "cost_inr"), _num(m, "recommended", "cost_inr")
        if cur_e is None or rec_e is None:
            continue
        
        # Check comparability
        comparable, comparability_reason = _check_comparability(m)
        
        cur_prod = _num(m, "current", "production_kg")
        rec_prod = _num(m, "recommended", "production_kg")
        cur_b, rec_b = _breakdown(m, "current"), _breakdown(m, "recommended")
        
        conf = "HIGH" if run.get("status") == "OPTIMAL" else "MEDIUM"
        conf_rule = ("solver proved optimality" if run.get("status") == "OPTIMAL"
                     else "solver returned a feasible (unproven) plan")
        constraints = _constraints_considered(run)
        
        # Per-kg projected energy (kWh/t) for both sides when available
        cur_kwh_per_t = None
        rec_kwh_per_t = None
        if cur_prod and cur_prod > 0:
            cur_kwh_per_t = round(cur_e / cur_prod * 1000, 1)
        if rec_prod and rec_prod > 0:
            rec_kwh_per_t = round(rec_e / rec_prod * 1000, 1)
        
        # Build base evidence with comparability info
        base_evidence = {
            "optimization_run_id": run.get("id"),
            "tariff": tariff_label,
            "comparable": comparable,
            "comparability_reason": comparability_reason,
        }
        if cur_kwh_per_t is not None:
            base_evidence["current_kwh_per_tonne"] = cur_kwh_per_t
        if rec_kwh_per_t is not None:
            base_evidence["recommended_kwh_per_tonne"] = rec_kwh_per_t
        
        # R-RESCHEDULE: cheaper / lower-load placement.
        cheaper = (rec_c is not None and cur_c is not None and rec_c < cur_c)
        lighter = rec_e < cur_e
        if cheaper or lighter:
            if comparable:
                eff = {"projected_kwh_delta": round(rec_e - cur_e, 3),
                       "projected_peak_kw_delta": (round(rec_p - cur_p, 3)
                                                   if rec_p is not None and cur_p is not None else None),
                       "projected_cost_inr_delta": (round(rec_c - cur_c, 2)
                                                    if rec_c is not None and cur_c is not None else None),
                       "evidence_class": "PROJECTED"}
                if eff["projected_cost_inr_delta"] is None:
                    cost_note = "cost unavailable: no tariff on record; no price invented"
                else:
                    cost_note = (f"tariff {tariff_label}; illustrative estimate, "
                                 "requires plant validation")
                reason = (f"Projected schedule uses {rec_e:.0f} kWh vs current "
                          f"{cur_e:.0f} kWh"
                          + (f" and projected INR {rec_c:.0f} vs INR {cur_c:.0f}"
                             if rec_c is not None and cur_c is not None else "")
                          + f" for the same production (run {run.get('id')}).")
                key_numbers = [f"current {cur_e:.1f} kWh",
                               f"recommended {rec_e:.1f} kWh"]
                if rec_c is not None:
                    key_numbers += [f"current INR {cur_c:.0f}",
                                    f"recommended INR {rec_c:.0f}"]
                source_class = SOURCE_PROJECTED
            else:
                # Not comparable: quantities null, no "same production" claim
                eff = {"projected_kwh_delta": None,
                       "projected_peak_kw_delta": None,
                       "projected_cost_inr_delta": None,
                       "evidence_class": "PROJECTED"}
                cost_note = "schedules not comparable"
                reason = (f"NOT COMPARABLE: {comparability_reason}. "
                          f"Projected schedule uses {rec_e:.0f} kWh vs current "
                          f"{cur_e:.0f} kWh (run {run.get('id')}). "
                          f"Effect not quantified.")
                key_numbers = [f"current {cur_e:.1f} kWh (PROJECTED)",
                               f"recommended {rec_e:.1f} kWh (PROJECTED)"]
                if cur_kwh_per_t is not None:
                    key_numbers.append(f"current {cur_kwh_per_t:.1f} kWh/t (PROJECTED)")
                if rec_kwh_per_t is not None:
                    key_numbers.append(f"recommended {rec_kwh_per_t:.1f} kWh/t (PROJECTED)")
                source_class = SOURCE_PROJECTED
            
            rec = _base(mid, "R-RESCHEDULE", run.get("horizon_start"), run.get("horizon_end"))
            rec.update({
                "title": f"Reschedule flexible heats on {mid} to lower-tariff periods",
                "severity": "WARNING",
                "reason": reason,
                "evidence": {**base_evidence, "key_numbers": key_numbers},
                "constraints_considered": constraints,
                "proposed_action": (f"Shift flexible heats per run {run.get('id')} "
                                     "after operator review; projected figures only, "
                                     "hold for Phase 5 check."),
                "expected_effect": eff,
                "confidence": conf,
                "confidence_reason": conf_rule,
                "assumptions": [f"tariff {tariff_label}; {cost_note}",
                                "baseline coefficients still represent the furnace",
                                "deltas are alternative views of one projected plan; do not add across rows"],
                "source_class": source_class,
                "dedup_key": _dedup("R-RESCHEDULE", mid, run.get("horizon_start"),
                                     run.get("horizon_end"), str(run.get("id"))),
            })
            out.append(rec)
        
        # R-SEQUENCE: cut holding/idle/reheat gaps (breakdown-backed when available).
        # After fairness fix, holding is fixed and real gap effect is reheat avoided.
        gap_above = any(
            f.get("metric") in ("holding_hours_per_heat", "median_heat_gap_h")
            and f.get("above_reference") is True
            for day in bundle["findings"] for f in (day.get("findings") or []))
        if cur_b and rec_b:
            cur_gap = cur_b.get("holding", 0.0) + cur_b.get("idle", 0.0) + cur_b.get("reheat", 0.0)
            rec_gap = rec_b.get("holding", 0.0) + rec_b.get("idle", 0.0) + rec_b.get("reheat", 0.0)
            gap_delta = rec_gap - cur_gap
        else:
            gap_delta = None
        
        if (gap_delta is not None and gap_delta < 0) or (gap_delta is None and gap_above):
            if comparable and gap_delta is not None:
                eff = {"projected_kwh_delta": round(gap_delta, 3),
                       "projected_peak_kw_delta": None,
                       "projected_cost_inr_delta": None,
                       "evidence_class": "PROJECTED"}
                conf_reason = conf_rule
                source_class = SOURCE_PROJECTED
                reason = (f"Projected holding+idle+reheat energy {rec_gap:.1f} kWh vs "
                          f"current {cur_gap:.1f} kWh (run {run.get('id')}).")
                key_numbers = [f"current gap {cur_gap:.1f} kWh (holding+idle+reheat)",
                               f"recommended gap {rec_gap:.1f} kWh (holding+idle+reheat)"]
            else:
                # Not comparable: all quantities null, effect not quantified
                eff = {"projected_kwh_delta": None,
                       "projected_peak_kw_delta": None,
                       "projected_cost_inr_delta": None,
                       "evidence_class": "PROJECTED"} if gap_delta is not None else None
                conf_reason = conf_rule if gap_delta is not None else "process finding above reference, no projected quantity"
                source_class = SOURCE_PROJECTED if eff else SOURCE_DERIVED
                if comparable:
                    reason = (f"Projected holding+idle+reheat energy {rec_gap:.1f} kWh vs "
                              f"current {cur_gap:.1f} kWh (run {run.get('id')}).")
                else:
                    reason = (f"NOT COMPARABLE: {comparability_reason}. "
                              f"Projected holding+idle+reheat energy {rec_gap:.1f} kWh vs "
                              f"current {cur_gap:.1f} kWh (run {run.get('id')}). "
                              f"Effect not quantified.")
                key_numbers = ([f"current gap {cur_gap:.1f} kWh (holding+idle+reheat)",
                                f"recommended gap {rec_gap:.1f} kWh (holding+idle+reheat)"]
                               if gap_delta is not None else [])
            
            rec = _base(mid, "R-SEQUENCE", run.get("horizon_start"), run.get("horizon_end"))
            rec.update({
                "title": f"Adjust heat sequence on {mid} to cut holding/idle/reheat gaps",
                "severity": "WARNING",
                "reason": reason,
                "evidence": {**base_evidence, "key_numbers": key_numbers,
                             "current_breakdown": cur_b, "recommended_breakdown": rec_b},
                "constraints_considered": constraints,
                "proposed_action": (f"Tighten heat sequencing per run {run.get('id')} "
                                     "after operator review; projected figures only, "
                                     "hold for Phase 5 check."),
                "expected_effect": eff,
                "confidence": conf,
                "confidence_reason": conf_reason,
                "assumptions": ["minimum holding for pouring still respected (hard constraint)",
                                "deltas are alternative views of one projected plan; do not add across rows"],
                "source_class": source_class,
                "dedup_key": _dedup("R-SEQUENCE", mid, run.get("horizon_start"),
                                     run.get("horizon_end"), str(run.get("id"))),
            })
            out.append(rec)
    return out


def _constraints_considered(run: dict) -> list[str]:
    c = ((run.get("constraints") or {}).get("constraints")) or {}
    names = []
    if c.get("operating_windows"):
        names.append(f"operating windows {c['operating_windows']}")
    if c.get("maintenance_windows"):
        names.append(f"maintenance {c['maintenance_windows']}")
    if c.get("peak_cap_kw") is not None:
        names.append(f"peak cap {c['peak_cap_kw']} kW")
    heat = c.get("heat") or {}
    if heat:
        names.append(f"holding bounds [{heat.get('min_hold_slots')}, "
                     f"{heat.get('max_hold_slots')}] slots")
    names.append("human approval required; nothing is executed automatically")
    return names


# --- R-NOPLAN: surface an INFEASIBLE explanation -------------------------------

def _rule_noplan(mid: str, bundle: dict) -> list[dict]:
    out = []
    for run in bundle["runs"]:
        if run.get("status") != "INFEASIBLE":
            continue
        rec = _base(mid, "R-NOPLAN", run.get("horizon_start"), run.get("horizon_end"))
        rec.update({
            "title": f"No feasible rescheduling plan for {mid}",
            "severity": "WARNING",
            "reason": (f"Optimizer reports INFEASIBLE for run {run.get('id')}: "
                       f"{run.get('explanation') or 'no explanation recorded'}."),
            "evidence": {"optimization_run_id": run.get("id"),
                         "key_numbers": [],
                         "explanation": run.get("explanation")},
            "constraints_considered": _constraints_considered(run),
            "proposed_action": ("Relax one conflicting limit (hours, peak cap, "
                                "maintenance overlap) with operations, then re-run; "
                                "no projected figures exist for an infeasible plan."),
            "expected_effect": None,
            "confidence": "MEDIUM",
            "confidence_reason": "solver explanation names the conflicting group",
            "assumptions": ["limits as currently recorded"],
            "source_class": SOURCE_DERIVED,
            "dedup_key": _dedup("R-NOPLAN", mid, run.get("horizon_start"),
                                run.get("horizon_end"), str(run.get("id"))),
        })
        out.append(rec)
    return out


# --- R-PRIORITISE: severity ranking across machines ----------------------------

def _rule_prioritise(by_machine: dict, insights: list[dict]) -> list[dict]:
    scored = []
    for mid, bundle in by_machine.items():
        open_ev = [e for e in bundle["events"] if e.get("status", "OPEN") == "OPEN"]
        if not open_ev and not any(i.get("machine_id") == mid for i in insights):
            continue
        best = 0
        detail = []
        for e in open_ev:
            r = _sev_rank(e.get("severity"))
            dev = abs(e.get("deviation_pct") or 0)
            best = max(best, r)
            detail.append(f"{e.get('rule_id')}/{e.get('severity')}/{dev}%")
        mine = [i for i in insights if i.get("machine_id") == mid]
        for i in mine:
            states = (i.get("health_evidence") or {}).get("states") or []
            if "CRITICAL" in states:
                best = max(best, 3)
            elif "WARNING" in states:
                best = max(best, 2)
            detail.append(f"{i.get('category')}")
        if open_ev or mine:
            scored.append((mid, best, detail))
    if len(scored) < 2:
        return []
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[0][0]
    ranking = [f"{m} (rank {r})" for m, r, _ in scored]
    rec = _base(top, "R-PRIORITISE", None, None)
    rec.update({
        "title": f"Prioritise inspection of {top}",
        "severity": "WARNING",
        "reason": ("Multiple machines show open anomalies or health insights; "
                   f"severity ranking: {'; '.join(ranking)}. {top} ranks first."),
        "evidence": {"ranking": [{"machine_id": m, "rank": r, "detail": d}
                                 for m, r, d in scored],
                     "key_numbers": ranking},
        "constraints_considered": ["maintenance crew availability (operator input)",
                                   "human approval required; nothing is executed automatically"],
        "proposed_action": (f"Inspect {top} first, then work down the ranking; "
                            "estimated effect is not quantified here."),
        "expected_effect": None,
        "confidence": "MEDIUM",
        "confidence_reason": "severity ranking across machines",
        "assumptions": ["severity ordering reflects operational priority (manager to confirm)"],
        "source_class": SOURCE_DERIVED,
        "dedup_key": _dedup("R-PRIORITISE", top, None, None, "+".join(ranking)),
    })
    return [rec]


# --- conflicts: optimizer action x critical inspection, same machine ----------

def _windows_overlap(a: dict, b: dict) -> bool:
    if not a.get("window_start") or not a.get("window_end"):
        return True  # unbounded (e.g. prioritisation) overlaps by construction
    if not b.get("window_start") or not b.get("window_end"):
        return True
    try:
        return (_as_dt(a["window_start"]) < _as_dt(b["window_end"])
                and _as_dt(a["window_end"]) > _as_dt(b["window_start"]))
    except ValueError:
        return True


def _apply_conflicts(recs: list[dict]) -> None:
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            if a["machine_id"] != b["machine_id"]:
                continue
            pair = {a["rule_id"], b["rule_id"]}
            opt_side = pair & set(OPTIMIZER_RULES)
            if not opt_side or "R-INSPECT" not in pair:
                continue
            insp = a if a["rule_id"] == "R-INSPECT" else b
            opt = b if insp is a else a
            if insp.get("severity") != "CRITICAL":
                continue
            if not _windows_overlap(a, b):
                continue
            for row, other in ((a, b), (b, a)):
                row["status"] = "CONFLICT"
                if other["dedup_key"] not in row["conflict_with"]:
                    row["conflict_with"].append(other["dedup_key"])
                row["conflict_note"] = (
                    f"Equipment condition on {row['machine_id']} is uncertain "
                    f"({insp['rule_id']}: {insp['reason']}) while a rescheduling "
                    f"action is proposed ({opt['rule_id']}: {opt['reason']}). "
                    "Both rows are kept; review the inspection outcome before "
                    "accepting the rescheduling plan.")
