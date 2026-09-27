"""Unit tests: Phase-4B recommendation engine (pure, no DB)."""

from services.recommendations.engine import BANNED_PHRASES, generate

WS = "2026-09-19T00:00:00+05:30"
WE = "2026-09-19T06:00:00+05:30"


def _ev(mid="furnace-01", rule="L1_IDLE_WASTE", sev="WARNING", dev=42.0):
    return {"id": f"{rule}-1", "machine_id": mid, "window_start": WS,
            "window_end": WE, "rule_id": rule, "severity": sev,
            "deviation_pct": dev, "status": "OPEN"}


def _health(mid="furnace-01", state="WARNING"):
    return {"machine_id": mid, "window_start": WS, "window_end": WE,
            "model_id": "statistical-v1", "health_score": 40.0,
            "anomaly_score": 8.0, "state": state, "status": "OK",
            "contributions": [{"signal": "vibration_mm_s", "z": 8.0,
                               "pct_change": 50.0, "median": 2.0, "value": 3.0}]}


def _finding_above(metric="non_productive_share", value=0.9, ref=0.2):
    return {"machine_id": "furnace-01", "day": "2026-09-19",
            "findings": [{"metric": metric, "value": value, "unit": "fraction",
                          "reference": ref, "reference_source": "NORMAL median",
                          "evidence": f"{value} vs {ref}",
                          "above_reference": True, "source": "DERIVED"}]}


def _run(mid="furnace-01", status="OPTIMAL", run_id="run-1", cost=True):
    br = {"heating": {"value": 100.0}, "melting": {"value": 400.0},
          "holding": {"value": 60.0}, "idle": {"value": 40.0},
          "reheat": {"value": 0.0}, "intercept": {"value": 20.0},
          "aux": {"value": 0.0}}
    cur = {"energy_kwh": {"value": 700.0}, "peak_kw": {"value": 140.0},
           "cost_inr": {"value": 6000.0} if cost else None,
           "production_kg": {"value": 2250.0}, "energy_by_state_kwh": br}
    rec = {"energy_kwh": {"value": 630.0}, "peak_kw": {"value": 135.0},
           "cost_inr": {"value": 5000.0} if cost else None,
           "production_kg": {"value": 2250.0},
           "energy_by_state_kwh": {**br, "holding": {"value": 30.0},
                                   "idle": {"value": 20.0},
                                   "melting": {"value": 400.0},
                                   "heating": {"value": 100.0}}}
    return {"id": run_id, "machine_id": mid,
            "horizon_start": "2026-09-19T00:00:00+05:30",
            "horizon_end": "2026-09-20T00:00:00+05:30",
            "status": status,
            "metrics": {"current": cur, "recommended": rec},
            "explanation": f"{status}: 6 heats",
            "constraints": {"constraints": {
                "operating_windows": [[0, 96]], "maintenance_windows": [],
                "peak_cap_kw": 150.0,
                "heat": {"min_hold_slots": 1, "max_hold_slots": 3}}}}


REQUIRED = {"title", "machine_id", "severity", "reason", "evidence",
            "constraints_considered", "proposed_action", "confidence",
            "assumptions", "source_module", "source_class", "status",
            "verification_status", "rule_id", "dedup_key"}


def test_fields_complete_for_each_rule():
    recs = generate(
        [_ev(), _ev("compressor-01", "L1_DEVIATION", "CRITICAL", 55.0)],
        [_health("compressor-01")],
        [_finding_above()],
        [_run(), {"id": "run-x", "machine_id": "furnace-01",
                  "horizon_start": WS, "horizon_end": WE, "status": "INFEASIBLE",
                  "metrics": {}, "explanation": "NO FEASIBLE PLAN: operating-hours",
                  "constraints": {"constraints": {}}}],
        "ILLUSTRATIVE (ASSUMPTION)")
    rules = {r["rule_id"] for r in recs}
    assert {"R-IDLE", "R-INSPECT", "R-RESCHEDULE", "R-SEQUENCE",
            "R-PRIORITISE", "R-NOPLAN", "R-PROCESS"} <= rules, rules
    for r in recs:
        assert REQUIRED <= set(r), r["rule_id"]
        assert r["severity"] in ("WARNING", "CRITICAL"), r
        assert r["confidence"] in ("LOW", "MEDIUM", "HIGH") and r["confidence_reason"], r
        assert r["source_class"] in ("DERIVED", "PROJECTED"), r
        assert r["status"] in ("PENDING_REVIEW", "CONFLICT"), r
        assert r["verification_status"] == "NOT_VERIFIED", r
        assert r["evidence"] and r["constraints_considered"] and r["assumptions"], r


def test_inspection_gets_null_quantity():
    recs = generate([_ev("furnace-01", "L1_DEVIATION")], [_health()], [], [],
                    "ILLUSTRATIVE (ASSUMPTION)")
    insp = [r for r in recs if r["rule_id"] == "R-INSPECT"]
    assert insp, recs
    for r in insp:
        assert r["expected_effect"] is None, r
    idle = [r for r in recs if r["rule_id"] == "R-IDLE"]
    # L1_DEVIATION alone (no idle rule, no findings) -> no idle rec, no guesses anywhere
    assert idle == []


def test_optimizer_deltas_and_no_tariff_cost_absent():
    recs = generate([], [], [], [_run()], "ILLUSTRATIVE (ASSUMPTION)")
    rs = [r for r in recs if r["rule_id"] == "R-RESCHEDULE"]
    assert len(rs) == 1
    eff = rs[0]["expected_effect"]
    assert eff["projected_kwh_delta"] == -70.0
    assert eff["projected_peak_kw_delta"] == -5.0
    assert eff["projected_cost_inr_delta"] == -1000.0
    assert eff["evidence_class"] == "PROJECTED"
    assert rs[0]["source_class"] == "PROJECTED"
    recs2 = generate([], [], [], [_run(cost=False)], "absent")
    eff2 = [r for r in recs2 if r["rule_id"] == "R-RESCHEDULE"][0]["expected_effect"]
    assert eff2["projected_cost_inr_delta"] is None
    assert eff2["projected_kwh_delta"] == -70.0  # energy still defensible


def test_banned_phrases_scan():
    recs = generate(
        [_ev(), _ev("compressor-01", "L1_DEVIATION", "CRITICAL", 55.0)],
        [_health("compressor-01"), _health("furnace-01", "CRITICAL")],
        [_finding_above()],
        [_run(), _run("furnace-01", "INFEASIBLE", "run-2")],
        "ILLUSTRATIVE (ASSUMPTION)")
    assert recs
    for r in recs:
        blob = " ".join([r["title"], r["reason"], r["proposed_action"],
                         r.get("conflict_note", ""), r.get("confidence_reason", ""),
                         *[str(a) for a in r["assumptions"]]]).lower()
        for phrase in BANNED_PHRASES:
            assert phrase not in blob, (phrase, r["rule_id"], blob[:200])


def test_conflict_flagged_both_reasons_kept():
    recs = generate([_ev("furnace-01", "L1_DEVIATION", "CRITICAL", 60.0)],
                    [_health("furnace-01", "CRITICAL")], [], [_run()],
                    "ILLUSTRATIVE (ASSUMPTION)")
    by_rule = {}
    for r in recs:
        by_rule.setdefault(r["rule_id"], []).append(r)
    assert "R-INSPECT" in by_rule and "R-RESCHEDULE" in by_rule
    flagged = [r for r in recs if r["status"] == "CONFLICT"]
    assert flagged, recs  # critical inspection x optimizer plan -> conflict
    for r in flagged:
        assert r["conflict_with"] and r["conflict_note"], r
        assert "R-INSPECT" in r["conflict_note"] or "inspect" in r["conflict_note"].lower()
    # Nothing silently dropped: both sides still present.
    assert any(r["rule_id"] == "R-INSPECT" for r in flagged)
    assert any(r["rule_id"] in ("R-RESCHEDULE", "R-SEQUENCE") for r in flagged)


def test_no_conflict_for_warning_health():
    recs = generate([_ev("furnace-01", "L1_DEVIATION")], [_health()], [], [_run()],
                    "ILLUSTRATIVE (ASSUMPTION)")
    assert all(r["status"] == "PENDING_REVIEW" for r in recs), recs


def test_prioritise_ranks_critical_first():
    recs = generate(
        [_ev("furnace-01", "L1_DEVIATION", "WARNING", 20.0),
         _ev("compressor-01", "L1_DEVIATION", "CRITICAL", 55.0)],
        [], [], [], "absent")
    pri = [r for r in recs if r["rule_id"] == "R-PRIORITISE"]
    assert len(pri) == 1
    assert "compressor-01" in pri[0]["title"]
    assert pri[0]["expected_effect"] is None


def test_infeasible_explanation_surfaced():
    recs = generate([_ev()], [], [],
                    [{"id": "r9", "machine_id": "furnace-01",
                      "horizon_start": WS, "horizon_end": WE,
                      "status": "INFEASIBLE", "metrics": {},
                      "explanation": "NO FEASIBLE PLAN: peak-cap trouble",
                      "constraints": {"constraints": {}}}],
                    "absent")
    nop = [r for r in recs if r["rule_id"] == "R-NOPLAN"]
    assert len(nop) == 1
    assert "NO FEASIBLE PLAN" in nop[0]["reason"]
    assert nop[0]["expected_effect"] is None
    # Remaining sources still produce their rows.
    assert any(r["rule_id"] == "R-IDLE" for r in recs)


def test_health_unavailable_still_generates():
    recs = generate([_ev()], [], [_finding_above()], [_run()], "absent")
    rules = {r["rule_id"] for r in recs}
    assert "R-IDLE" in rules and "R-RESCHEDULE" in rules
    assert "R-INSPECT" not in rules


def _run_diff_prod(mid="furnace-01", status="OPTIMAL", run_id="run-1"):
    """Optimization run where recommended production differs from current."""
    br = {"heating": {"value": 100.0}, "melting": {"value": 400.0},
          "holding": {"value": 60.0}, "idle": {"value": 40.0},
          "reheat": {"value": 0.0}, "intercept": {"value": 20.0},
          "aux": {"value": 0.0}}
    cur = {"energy_kwh": {"value": 700.0}, "peak_kw": {"value": 140.0},
           "cost_inr": {"value": 6000.0},
           "production_kg": {"value": 1500.0}, "energy_by_state_kwh": br}
    rec = {"energy_kwh": {"value": 630.0}, "peak_kw": {"value": 135.0},
           "cost_inr": {"value": 5000.0},
           "production_kg": {"value": 1125.0},  # Different production!
           "energy_by_state_kwh": {**br, "holding": {"value": 30.0},
                                   "idle": {"value": 20.0},
                                   "melting": {"value": 400.0},
                                   "heating": {"value": 100.0}}}
    return {"id": run_id, "machine_id": mid,
            "horizon_start": "2026-09-19T00:00:00+05:30",
            "horizon_end": "2026-09-20T00:00:00+05:30",
            "status": status,
            "metrics": {"current": cur, "recommended": rec},
            "explanation": f"{status}: 6 heats",
            "constraints": {"constraints": {
                "operating_windows": [[0, 96]], "maintenance_windows": [],
                "peak_cap_kw": 150.0,
                "heat": {"min_hold_slots": 1, "max_hold_slots": 3}}}}


def _run_diff_aux(mid="furnace-01", status="OPTIMAL", run_id="run-1"):
    """Optimization run where aux tasks differ."""
    br = {"heating": {"value": 100.0}, "melting": {"value": 400.0},
          "holding": {"value": 60.0}, "idle": {"value": 40.0},
          "reheat": {"value": 0.0}, "intercept": {"value": 20.0},
          "aux": {"value": 0.0}}
    cur = {"energy_kwh": {"value": 700.0}, "peak_kw": {"value": 140.0},
           "cost_inr": {"value": 6000.0},
           "production_kg": {"value": 2250.0}, "energy_by_state_kwh": br}
    rec_br = {**br, "holding": {"value": 30.0},
              "idle": {"value": 20.0},
              "melting": {"value": 400.0},
              "heating": {"value": 100.0},
              "aux": {"value": 50.0}}  # Different aux energy!
    rec = {"energy_kwh": {"value": 680.0}, "peak_kw": {"value": 135.0},
           "cost_inr": {"value": 5000.0},
           "production_kg": {"value": 2250.0}, "energy_by_state_kwh": rec_br}
    return {"id": run_id, "machine_id": mid,
            "horizon_start": "2026-09-19T00:00:00+05:30",
            "horizon_end": "2026-09-20T00:00:00+05:30",
            "status": status,
            "metrics": {"current": cur, "recommended": rec},
            "explanation": f"{status}: 6 heats",
            "constraints": {"constraints": {
                "operating_windows": [[0, 96]], "maintenance_windows": [],
                "peak_cap_kw": 150.0,
                "heat": {"min_hold_slots": 1, "max_hold_slots": 3}}}}


def test_non_comparable_different_production():
    """Non-comparable run (different production) -> quantities null, no 'same production' text."""
    recs = generate([], [], [], [_run_diff_prod()], "ILLUSTRATIVE (ASSUMPTION)")
    rs = [r for r in recs if r["rule_id"] == "R-RESCHEDULE"]
    assert len(rs) == 1
    r = rs[0]
    # Quantities should be null
    eff = r["expected_effect"]
    assert eff["projected_kwh_delta"] is None
    assert eff["projected_peak_kw_delta"] is None
    assert eff["projected_cost_inr_delta"] is None
    # Reason should NOT contain "same production"
    assert "same production" not in r["reason"].lower()
    # Reason should contain NOT COMPARABLE
    assert "NOT COMPARABLE" in r["reason"]
    assert "production differs" in r["reason"].lower()
    # Evidence should have comparable=false
    assert r["evidence"]["comparable"] is False
    assert "production differs" in r["evidence"]["comparability_reason"].lower()
    # Should have per-kg projected energy
    assert "current_kwh_per_tonne" in r["evidence"]
    assert "recommended_kwh_per_tonne" in r["evidence"]


def test_non_comparable_different_aux():
    """Non-comparable run (different aux) -> quantities null, no 'same production' text."""
    recs = generate([], [], [], [_run_diff_aux()], "ILLUSTRATIVE (ASSUMPTION)")
    rs = [r for r in recs if r["rule_id"] == "R-RESCHEDULE"]
    assert len(rs) == 1
    r = rs[0]
    eff = r["expected_effect"]
    assert eff["projected_kwh_delta"] is None
    assert eff["projected_peak_kw_delta"] is None
    assert eff["projected_cost_inr_delta"] is None
    assert "same production" not in r["reason"].lower()
    assert "NOT COMPARABLE" in r["reason"]
    assert "auxiliary tasks differ" in r["reason"].lower()
    assert r["evidence"]["comparable"] is False
    assert "auxiliary tasks differ" in r["evidence"]["comparability_reason"].lower()


def test_comparable_run_has_quantities():
    """Comparable run -> quantities present, 'same production' text allowed."""
    recs = generate([], [], [], [_run()], "ILLUSTRATIVE (ASSUMPTION)")
    rs = [r for r in recs if r["rule_id"] == "R-RESCHEDULE"]
    assert len(rs) == 1
    r = rs[0]
    eff = r["expected_effect"]
    assert eff["projected_kwh_delta"] == -70.0
    assert eff["projected_peak_kw_delta"] == -5.0
    assert eff["projected_cost_inr_delta"] == -1000.0
    assert "same production" in r["reason"].lower()
    assert "NOT COMPARABLE" not in r["reason"]
    assert r["evidence"]["comparable"] is True
    assert r["evidence"]["comparability_reason"] == "same production and auxiliary tasks"


def test_sequence_comparable_and_non_comparable():
    """R-SEQUENCE also respects comparability."""
    # Comparable
    recs = generate([], [], [], [_run()], "ILLUSTRATIVE (ASSUMPTION)")
    seq = [r for r in recs if r["rule_id"] == "R-SEQUENCE"]
    assert len(seq) == 1
    assert seq[0]["evidence"]["comparable"] is True
    assert "holding+idle+reheat" in seq[0]["reason"]
    
    # Non-comparable (different production)
    recs2 = generate([], [], [], [_run_diff_prod()], "ILLUSTRATIVE (ASSUMPTION)")
    seq2 = [r for r in recs2 if r["rule_id"] == "R-SEQUENCE"]
    assert len(seq2) == 1
    assert seq2[0]["evidence"]["comparable"] is False
    assert "NOT COMPARABLE" in seq2[0]["reason"]
    assert "holding+idle+reheat" in seq2[0]["reason"]
    assert seq2[0]["expected_effect"]["projected_kwh_delta"] is None
