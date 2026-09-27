"""Unit tests: process-efficiency findings (pure, no DB)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.energy.aggregate import Interval
from services.energy.process_efficiency import analyze, daily_metrics, reference_medians

TZ = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 9, 18, 0, 0, tzinfo=TZ)


def _iv(k: int, energy: float, hb: dict, prod: float) -> Interval:
    ws = T0 + timedelta(hours=k)
    return Interval(machine_id="furnace-01", window_start=ws,
                    window_end=ws + timedelta(hours=1), complete=True,
                    energy_kwh=energy, hours_by_state=dict(hb), n_good=12,
                    coverage_pct=95.0, good_production_kg=prod,
                    has_production_record=True)


def _samples(*states, start=T0, step_min=10):
    """(ts, state) samples cycling through the given states."""
    return [(start + timedelta(minutes=i * step_min), s)
            for i, s in enumerate(states)]


def _ref_daily():
    # NORMAL reference: 2 days, ~2 h idle, 1 heat/day... built by hand.
    d1 = {"idle_hours": 2.0, "holding_per_heat_h": 0.4,
          "non_productive_share": 0.10, "start_count": 9.0,
          "median_heat_gap_h": 2.2, "heat_count": 9.0}
    d2 = {"idle_hours": 2.4, "holding_per_heat_h": 0.5,
          "non_productive_share": 0.12, "start_count": 10.0,
          "median_heat_gap_h": 2.0, "heat_count": 10.0}
    from services.energy.process_efficiency import DayMetrics
    return [DayMetrics(machine_id="furnace-01", day="2026-09-10", **_m(d1)),
            DayMetrics(machine_id="furnace-01", day="2026-09-11", **_m(d2))]


def _m(d):
    return {"idle_hours": d["idle_hours"],
            "holding_hours": d["holding_per_heat_h"] * d["heat_count"],
            "non_productive_share": d["non_productive_share"],
            "heat_count": int(d["heat_count"]), "start_count": int(d["start_count"]),
            "median_heat_gap_h": d["median_heat_gap_h"],
            "holding_per_heat_h": d["holding_per_heat_h"]}


def test_reference_medians():
    ref = reference_medians(_ref_daily())
    assert ref["idle_hours"] == 2.2
    assert ref["heat_count"] == 9.5
    assert ref["median_heat_gap_h"] == 2.1


def test_idle_day_flagged_above_reference():
    ivs = [_iv(k, 100.0,
               {"heating": 0.1, "melting": 0.2, "holding": 0.1, "idle": 0.6},
               0.0) for k in range(6)]
    samples = _samples("idle", "idle", "heating", "melting", "holding", "idle")
    out = analyze("furnace-01", "furnace", ivs, samples, _ref_daily(), min_hold_h=0.25)
    assert len(out) == 1
    day = out[0]
    assert day["source"] == "DERIVED"
    by_metric = {f["metric"]: f for f in day["findings"]}
    assert set(by_metric) == {"idle_hours", "holding_hours_per_heat",
                              "non_productive_share", "start_count",
                              "median_heat_gap_h"}
    idle = by_metric["idle_hours"]
    assert idle["value"] == 3.6
    assert idle["reference"] == 2.2
    assert idle["above_reference"] is True
    assert idle["source"] == "DERIVED"
    assert "NORMAL median" in idle["evidence"]
    nps = by_metric["non_productive_share"]
    assert nps["value"] == 1.0  # zero production all day
    hold = by_metric["holding_hours_per_heat"]
    assert hold["reference"] == 0.25  # configured pouring minimum
    assert "pouring" in hold["evidence"]


def test_heat_gap_and_starts_from_samples():
    ivs = [_iv(k, 120.0, {"heating": 0.3, "melting": 0.5, "holding": 0.1,
                          "idle": 0.1}, 300.0) for k in range(6)]
    states = (["idle"] * 3 + ["heating"] * 2 + ["melting"] * 4 + ["holding"] * 2
              + ["idle"] * 6 + ["heating"] * 2 + ["melting"] * 4 + ["holding"] * 2
              + ["idle"] * 4)
    samples = _samples(*states)
    out = analyze("furnace-01", "furnace", ivs, samples, _ref_daily(), min_hold_h=0.25)
    day = out[0]
    assert day["heat_count"] == 2
    assert day["start_count"] == 2
    gap = next(f for f in day["findings"] if f["metric"] == "median_heat_gap_h")
    assert gap["value"] is not None and gap["value"] > 0


def test_no_reference_findings_carry_none():
    ivs = [_iv(0, 100.0, {"idle": 1.0}, 0.0)]
    out = analyze("furnace-01", "furnace", ivs, _samples("idle", "idle"), None,
                  min_hold_h=0.25)
    idle = next(f for f in out[0]["findings"] if f["metric"] == "idle_hours")
    assert idle["reference"] is None
    assert idle["above_reference"] is None
    assert "no NORMAL reference" in idle["evidence"]


def test_non_furnace_holding_uses_hours():
    ivs = [_iv(0, 50.0, {"running": 1.0}, 0.0)]
    out = analyze("pump-01", "pump", ivs, _samples("running", "running"),
                  _ref_daily(), min_hold_h=0.25)
    hold = next(f for f in out[0]["findings"] if f["metric"] == "holding_hours_per_heat")
    assert hold["unit"] == "h"
    assert out[0]["heat_count"] == 0


def test_daily_metrics_groups_days_and_shares():
    ivs = [_iv(k, 100.0, {"idle": 1.0}, 0.0) for k in range(3)]
    ivs += [_iv(24 + k, 200.0, {"melting": 0.8, "idle": 0.2}, 300.0)
            for k in range(2)]
    daily = daily_metrics("furnace-01", "furnace", ivs, [])
    assert [d.day for d in daily] == ["2026-09-18", "2026-09-19"]
    assert daily[0].non_productive_share == 1.0
    assert daily[1].non_productive_share == 0.0
