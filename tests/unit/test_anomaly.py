"""Unit tests: MAD z-scores, L1/L2 rule thresholds, event merging."""

from services.energy.anomaly import build_events, l1_flags, l2_flags, mad_zscores, merge_runs


def _scored(n: int = 6, **kw) -> list[dict]:
    base = {
        "complete": True, "deviation_pct": 0.0, "deviation_kwh": 0.0,
        "hours_by_state": {"running": 1.0}, "good_production_kg": 100.0,
        "power_max_kw": 10.0, "pf_mean": 0.9, "expected_kwh": 100.0, "actual_kwh": 100.0,
    }
    return [dict(base, **kw) for _ in range(n)]


def test_mad_flags_spike():
    resid = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 20.0]
    zs = mad_zscores(resid, window=8)
    assert abs(zs[-1]) > 4.0
    assert all(abs(z) < 4.0 for z in zs[:-1])


def test_mad_flat_window_is_zero_never_inf():
    zs = mad_zscores([5.0] * 10, window=6)
    assert zs == [0.0] * 10
    zs = mad_zscores([1.0, 2.0], window=6)  # too short
    assert zs == [0.0, 0.0]


def test_l1_deviation_needs_n_consecutive():
    rows = _scored(3)
    rows[1]["deviation_pct"] = 20.0  # single interval above warn
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    assert [f for f in flags if f["rule_id"] == "L1_DEVIATION"] == []
    rows[2]["deviation_pct"] = 20.0  # two consecutive -> flag
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    dev = [f for f in flags if f["rule_id"] == "L1_DEVIATION"]
    assert len(dev) == 1 and dev[0]["severity"] == "WARNING"


def test_l1_deviation_critical_above_crit_threshold():
    rows = _scored(2, deviation_pct=35.0)
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    dev = [f for f in flags if f["rule_id"] == "L1_DEVIATION"]
    assert dev and dev[0]["severity"] == "CRITICAL"


def test_l1_incomplete_intervals_never_flagged():
    rows = _scored(3, deviation_pct=50.0)
    for r in rows:
        r["complete"] = False
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    assert flags == []


def test_l1_idle_waste_rule():
    # Sustained powered idleness: zero production + idle share for N
    # consecutive intervals (default persistence 2 here).
    rows = _scored(2)
    for r in rows:
        r["hours_by_state"] = {"idle": 0.8, "holding": 0.2}
        r["good_production_kg"] = 0.0
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6, 2)
    assert [f["rule_id"] for f in flags if f["rule_id"] == "L1_IDLE_WASTE"]
    # A single idle hour is normal batch rhythm -> not waste.
    flags = l1_flags(rows[:1], 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6, 2)
    assert [f for f in flags if f["rule_id"] == "L1_IDLE_WASTE"] == []
    # Producing -> not waste, even when idle-heavy.
    rows = _scored(2)
    for r in rows:
        r["hours_by_state"] = {"idle": 0.8, "holding": 0.2}
        r["good_production_kg"] = 50.0
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6, 2)
    assert [f for f in flags if f["rule_id"] == "L1_IDLE_WASTE"] == []
    # A producing interval breaks the run -> no flag.
    rows = _scored(3)
    for r in rows:
        r["hours_by_state"] = {"idle": 0.8, "holding": 0.2}
        r["good_production_kg"] = 0.0
    rows[1]["good_production_kg"] = 50.0
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6, 3)
    assert [f for f in flags if f["rule_id"] == "L1_IDLE_WASTE"] == []


def test_l1_power_and_pf_thresholds():
    rows = _scored(1)
    rows[0]["power_max_kw"] = 200.0  # > 100 * 1.1
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    assert [f["rule_id"] for f in flags] == ["L1_POWER"]
    rows = _scored(1)
    rows[0]["pf_mean"] = 0.5
    flags = l1_flags(rows, 15.0, 30.0, 2, 0.5, 100.0, 1.1, 0.6)
    assert [f["rule_id"] for f in flags] == ["L1_POWER_FACTOR"]


def test_l2_requires_practical_significance():
    rows = _scored(8)
    resid = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 50.0]
    for r, e in zip(rows, resid, strict=True):
        r["actual_kwh"] = 100.0 + e
        r["expected_kwh"] = 100.0
        r["deviation_pct"] = e
    flags = l2_flags(rows, mad_threshold=4.0, mad_window=8, min_deviation_pct=15.0)
    assert len(flags) == 1 and flags[0]["rule_id"] == "L2_MAD_RESIDUAL"
    # Same shape, but practically insignificant -> no flag.
    resid = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0]
    for r, e in zip(rows, resid, strict=True):
        r["actual_kwh"] = 100.0 + e
        r["deviation_pct"] = e
    flags = l2_flags(rows, mad_threshold=4.0, mad_window=8, min_deviation_pct=15.0)
    assert flags == []


def test_merge_consecutive_flags_into_one_event():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    scored = _scored(5)
    starts = [datetime(2026, 9, 1, h, tzinfo=tz) for h in range(5)]
    ends = [datetime(2026, 9, 1, h + 1, tzinfo=tz) for h in range(5)]
    flags = [
        {"idx": 1, "rule_id": "L1_DEVIATION", "metric": "deviation",
         "severity": "WARNING", "score": 20.0,
         "evidence": "Energy 20.0% above expected baseline for the production achieved."},
        {"idx": 2, "rule_id": "L1_DEVIATION", "metric": "deviation",
         "severity": "CRITICAL", "score": 35.0,
         "evidence": "Energy 35.0% above expected baseline for the production achieved."},
        {"idx": 4, "rule_id": "L1_DEVIATION", "metric": "deviation",
         "severity": "WARNING", "score": 16.0,
         "evidence": "Energy 16.0% above expected baseline for the production achieved."},
    ]
    assert len(merge_runs(flags)) == 2  # {1,2} merged, {4} alone
    events = build_events("m1", scored, starts, ends, flags)
    assert len(events) == 2
    assert events[0]["severity"] == "CRITICAL"  # max of run
    assert events[0]["status"] == "OPEN" and events[0]["source"] == "DERIVED"
    assert events[0]["window_start"] == starts[1] and events[0]["window_end"] == ends[2]
    assert "above expected baseline" in events[0]["evidence"]
    assert "failure" not in events[0]["evidence"].lower()
    # Idempotent re-detect: dedup_key stable for the same run.
    again = build_events("m1", scored, starts, ends, flags)
    assert [e["dedup_key"] for e in again] == [e["dedup_key"] for e in events]
