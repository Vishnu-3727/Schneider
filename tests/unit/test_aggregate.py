"""Unit tests: interval aggregation completeness (BAD rows, coverage floor)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.energy.aggregate import build_intervals

TZ = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def _row(ts, quality="GOOD", energy=None, state="running"):
    return {"ts": ts, "quality": quality, "energy_kwh": energy,
            "machine_state": state, "power_kw": 10.0, "power_factor": 0.85}


def _hour_rows(n=12, quality="GOOD", state="running", e0=0.0):
    return [_row(START + timedelta(minutes=5 * i), quality, e0 + i * 2.0, state)
            for i in range(n)]


def _prod(ws, good=100.0):
    return {"window_start": ws, "quality": "GOOD",
            "qty_good_kg": good, "qty_rejected_kg": 2.0}


def test_complete_interval_math():
    ivs = build_intervals("m1", _hour_rows(), [_prod(START)],
                          START, START + timedelta(hours=1), 3600, 80.0)
    assert len(ivs) == 1 and ivs[0].complete
    assert ivs[0].energy_kwh == 22.0  # max - min of counter
    assert ivs[0].good_production_kg == 100.0
    assert ivs[0].rejected_production_kg == 2.0
    assert ivs[0].hours_by_state["running"] == 1.0


def test_bad_row_marks_incomplete_never_silent():
    rows = _hour_rows()
    rows[5] = _row(rows[5]["ts"], quality="BAD", energy=10.0)
    ivs = build_intervals("m1", rows, [_prod(START)],
                          START, START + timedelta(hours=1), 3600, 80.0)
    assert not ivs[0].complete
    assert any("BAD" in r for r in ivs[0].incomplete_reasons)


def test_low_coverage_marks_incomplete():
    ivs = build_intervals("m1", _hour_rows(n=2), [_prod(START)],
                          START, START + timedelta(hours=1), 3600, 80.0)
    assert not ivs[0].complete
    assert any("coverage" in r for r in ivs[0].incomplete_reasons)


def test_suspect_rows_excluded_but_do_not_fail_interval():
    rows = _hour_rows()
    rows[0]["quality"] = "SUSPECT"  # dropped from math, interval still complete
    ivs = build_intervals("m1", rows, [_prod(START)],
                          START, START + timedelta(hours=1), 3600, 80.0)
    assert ivs[0].complete
    assert ivs[0].n_good == 11
