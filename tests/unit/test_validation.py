"""Unit tests: every BAD/SUSPECT validation rule, duplicates, naive ts."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.backend.schemas import TelemetryRecord
from services.ingestion.validate import (
    is_duplicate,
    validate_production,
    validate_telemetry,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def ts_ok():
    return NOW - timedelta(seconds=60)


def test_good_record():
    r = validate_telemetry(ts=ts_ok(), now=NOW, voltage_v=415, current_a=100, power_kw=50,
                           power_factor=0.85, energy_kwh=10.0)
    assert r.quality == "GOOD" and r.reasons == []


def test_bad_negative_power():
    r = validate_telemetry(ts=ts_ok(), now=NOW, power_kw=-5)
    assert r.quality == "BAD" and any("power_kw" in x for x in r.reasons)


def test_bad_negative_current():
    r = validate_telemetry(ts=ts_ok(), now=NOW, current_a=-1)
    assert r.quality == "BAD"


def test_bad_negative_voltage():
    r = validate_telemetry(ts=ts_ok(), now=NOW, voltage_v=-1)
    assert r.quality == "BAD"


@pytest.mark.parametrize("pf", [-0.1, 1.5])
def test_bad_power_factor(pf):
    r = validate_telemetry(ts=ts_ok(), now=NOW, power_factor=pf)
    assert r.quality == "BAD" and any("power_factor" in x for x in r.reasons)


def test_bad_energy_decreasing():
    r = validate_telemetry(ts=ts_ok(), now=NOW, energy_kwh=9.0, last_energy_kwh=10.0)
    assert r.quality == "BAD" and any("decreasing" in x for x in r.reasons)


def test_bad_future_ts():
    r = validate_telemetry(ts=NOW + timedelta(seconds=3600), now=NOW, clock_skew_s=300)
    assert r.quality == "BAD" and any("future" in x for x in r.reasons)


def test_bad_production_totals():
    r = validate_production(qty_total_kg=100, qty_good_kg=90, qty_rejected_kg=20)
    assert r.quality == "BAD"


def test_suspect_stale():
    r = validate_telemetry(ts=NOW - timedelta(seconds=3600), now=NOW, stale_after_s=900)
    assert r.quality == "SUSPECT" and any("stale" in x for x in r.reasons)


def test_suspect_out_of_order():
    last = ts_ok()
    r = validate_telemetry(ts=last - timedelta(seconds=60), now=NOW, last_ts=last)
    assert r.quality == "SUSPECT" and any("out-of-order" in x for x in r.reasons)


def test_suspect_spike():
    r = validate_telemetry(ts=ts_ok(), now=NOW, power_kw=300, rated_power_kw=150, spike_multiple=1.5)
    assert r.quality == "SUSPECT" and any("spike" in x for x in r.reasons)


def test_no_spike_below_threshold():
    r = validate_telemetry(ts=ts_ok(), now=NOW, power_kw=140, rated_power_kw=150, spike_multiple=1.5)
    assert r.quality == "GOOD"


def test_duplicate_helper():
    t = ts_ok()
    seen = {("m1", t)}
    assert is_duplicate(t, "m1", seen) is True
    assert is_duplicate(t, "m2", seen) is False


def test_naive_ts_rejected_by_schema():
    with pytest.raises(Exception):
        TelemetryRecord(machine_id="furnace-01", ts="2026-09-27T12:00:00",
                        power_kw=10.0, source="SIMULATED")


def test_extra_field_forbidden():
    with pytest.raises(Exception):
        TelemetryRecord(machine_id="furnace-01", ts="2026-09-27T12:00:00+05:30",
                        power_kw=10.0, source="SIMULATED", cost_inr=5.0)
