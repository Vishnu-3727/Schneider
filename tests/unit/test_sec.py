"""Unit tests: SEC statuses (one per status) + rejected-production exclusion."""

from services.energy.sec import compute_sec


def test_sec_ok():
    r = compute_sec(100.0, 200.0, True, "furnace", ["pump"], True)
    assert r.status == "OK"
    assert r.sec_kwh_per_t == 500.0  # 100 kWh / 0.2 t


def test_sec_no_production_reports_non_productive():
    r = compute_sec(50.0, 0.0, True, "furnace", ["pump"], True)
    assert r.status == "NO_PRODUCTION"
    assert r.sec_kwh_per_t is None
    assert r.non_productive_kwh == 50.0


def test_sec_missing_production():
    r = compute_sec(50.0, None, False, "furnace", ["pump"], True)
    assert r.status == "MISSING_PRODUCTION"
    assert r.sec_kwh_per_t is None


def test_sec_incomplete_data():
    r = compute_sec(50.0, 200.0, True, "furnace", ["pump"], False)
    assert r.status == "INCOMPLETE_DATA"
    assert r.sec_kwh_per_t is None


def test_sec_not_applicable_for_non_production_type():
    r = compute_sec(50.0, 0.0, True, "pump", ["pump"], True)
    assert r.status == "NOT_APPLICABLE"
    assert r.sec_kwh_per_t is None


def test_sec_rejected_excluded_from_denominator():
    # 200 kg good + 50 kg rejected -> denominator is 200 kg only.
    r = compute_sec(100.0, 200.0, True, "furnace", ["pump"], True)
    assert r.sec_kwh_per_t == 500.0


def test_sec_compressor_not_applicable_by_default():
    # Compressor is auxiliary with no production records (config default
    # NON_PRODUCTION_TYPES=pump,compressor) -> NOT_APPLICABLE, never
    # NO_PRODUCTION.
    r = compute_sec(50.0, 0.0, True, "compressor", ["pump", "compressor"], True)
    assert r.status == "NOT_APPLICABLE"
    assert r.sec_kwh_per_t is None
    r = compute_sec(50.0, None, False, "compressor", ["pump", "compressor"], True)
    assert r.status == "NOT_APPLICABLE"


def test_window_aggregate_sec_equals_totals_ratio():
    # Window SEC must be total energy / total good production, not the mean
    # of hourly SEC values.
    from apps.backend.routers.energy import _window_aggregate

    scored = [
        {"complete": True, "actual_kwh": 100.0, "expected_kwh": 95.0,
         "good_production_kg": 100.0, "non_productive_kwh": None},
        {"complete": True, "actual_kwh": 300.0, "expected_kwh": 290.0,
         "good_production_kg": 900.0, "non_productive_kwh": None},
        {"complete": False, "actual_kwh": 999.0, "expected_kwh": None,
         "good_production_kg": 999.0, "non_productive_kwh": None},
    ]
    agg = _window_aggregate("furnace-01", "furnace", scored, ["pump", "compressor"],
                            0.5, "2026-09-19T12:00:00+05:30", "2026-09-20T12:00:00+05:30")
    # (100 + 300) kWh / 1.0 t = 400 kWh/t (incomplete 999 excluded).
    assert agg["window_sec_kwh_per_t"] == 400.0
    assert agg["window_sec_status"] == "OK"
    assert agg["total_actual_kwh"] == 400.0
    assert agg["total_expected_kwh"] == 385.0
    assert agg["aggregate_deviation_pct"] == (400.0 - 385.0) / 385.0 * 100.0
    # Mean of hourly SEC (1000 and 333) would be ~667: must NOT equal that.
    assert agg["window_sec_kwh_per_t"] != (1000.0 + 333.333) / 2
