"""Unit tests: StatisticalHealthModel (robust z, statuses, state conditioning)."""

import pytest

from services.machine_health.statistical import (
    StatisticalHealthModel,
    build_health_intervals,
    robust_z,
    state_bucket,
)


def _iv(state="running", vib=2.0, temp=70.0, cur=40.0, complete=True):
    from datetime import datetime, timezone
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    return {"machine_id": "m", "window_start": now, "window_end": now,
            "machine_state": state, "vibration_mm_s": vib,
            "temperature_c": temp, "current_a": cur,
            "n_rows": 12, "complete": complete}


def _fit(model, n=30, **kw):
    rows = [_iv(**kw) for _ in range(n)]
    return model.fit(rows)


def test_state_buckets():
    assert state_bucket("idle") == "idle"
    assert state_bucket("Melting") == "melting"
    assert state_bucket("running") == "running"
    assert state_bucket(None) == "unknown"


def test_robust_z_known_values():
    assert robust_z(12.0, 10.0, 2.0, 0.0, 1e-9) == pytest.approx(0.6745, rel=1e-6)
    # MAD floor: flat reference never explodes.
    assert abs(robust_z(10.5, 10.0, 0.0, 0.05, 1e-6)) < 1.0


def test_metadata_shape():
    m = StatisticalHealthModel()
    meta = m.metadata()
    assert meta["model_id"] == "statistical-v1"
    assert set(meta["valid_input_signals"]) == {"vibration_mm_s", "temperature_c", "current_a"}
    assert meta["evidence_source_class"] == "DERIVED"
    assert meta["limitations"], "limitations must be documented"


def test_normal_scores_ok():
    m = StatisticalHealthModel()
    _fit(m)
    res = m.score([_iv()])
    assert res[0]["status"] == "OK"
    assert res[0]["state"] == "NORMAL"
    assert 0 <= res[0]["health_score"] <= 100
    assert res[0]["anomaly_score"] is not None


def test_degraded_scores_critical_with_top_signal():
    m = StatisticalHealthModel()
    _fit(m)
    res = m.score([_iv(vib=9.0, temp=120.0, cur=55.0)])
    assert res[0]["status"] == "OK"
    assert res[0]["state"] == "CRITICAL"
    assert res[0]["health_score"] < 50
    expl = m.explain([_iv(vib=9.0, temp=120.0, cur=55.0)])[0]
    assert expl[0]["signal"] == "vibration_mm_s"
    assert sum(c["weight"] for c in expl) == pytest.approx(1.0, abs=1e-6)


def test_missing_signals_unavailable_never_zero():
    m = StatisticalHealthModel()
    _fit(m)
    res = m.score([_iv(vib=None, temp=None, cur=None)])
    assert res[0]["status"] == "UNAVAILABLE"
    assert res[0]["health_score"] is None
    assert res[0]["anomaly_score"] is None
    # Partial missing still scores on present signals, never crashes.
    res = m.score([_iv(vib=None)])
    assert res[0]["status"] == "OK"


def test_insufficient_history():
    m = StatisticalHealthModel()
    _fit(m, n=3)
    res = m.score([_iv()])
    assert res[0]["status"] == "INSUFFICIENT_HISTORY"
    # Unfitted model is the same.
    res = StatisticalHealthModel().score([_iv()])
    assert res[0]["status"] == "INSUFFICIENT_HISTORY"


def test_state_conditioning_and_out_of_domain():
    m = StatisticalHealthModel()
    m.fit([_iv(state="running", vib=2.0, temp=70.0) for _ in range(15)]
          + [_iv(state="idle", vib=1.2, temp=600.0) for _ in range(15)])
    # Idle-typical values are NORMAL under the idle bucket ...
    res = m.score([_iv(state="idle", vib=1.2, temp=600.0)])
    assert (res[0]["status"], res[0]["state"]) == ("OK", "NORMAL")
    # ... but would be anomalous under a running-only reference.
    m2 = StatisticalHealthModel()
    m2.fit([_iv(state="running", vib=2.0, temp=70.0) for _ in range(30)])
    res = m2.score([_iv(state="idle", vib=1.2, temp=600.0)])
    assert res[0]["status"] == "OUT_OF_DOMAIN"


def test_incomplete_interval_unavailable():
    m = StatisticalHealthModel()
    _fit(m)
    res = m.score([_iv(complete=False)])
    assert res[0]["status"] == "UNAVAILABLE"


def test_score_alias_matches_predict():
    m = StatisticalHealthModel()
    _fit(m)
    rows = [_iv(), _iv(vib=9.0)]
    assert m.score(rows) == m.predict(rows)


def test_build_health_intervals_hourly_means():
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    rows = [{"ts": start + timedelta(minutes=5 * i), "quality": "GOOD",
             "machine_state": "running", "vibration_mm_s": 2.0,
             "temperature_c": 70.0, "current_a": 40.0} for i in range(12)]
    ivs = build_health_intervals("m", rows, start, start + timedelta(hours=2),
                                 3600, 80.0)
    assert len(ivs) == 2
    assert ivs[0]["complete"] and ivs[0]["vibration_mm_s"] == pytest.approx(2.0)
    assert ivs[0]["machine_state"] == "running"
    # Missing signals stay None, never zero-filled.
    rows2 = [{**r, "vibration_mm_s": None} for r in rows]
    ivs2 = build_health_intervals("m", rows2, start, start + timedelta(hours=1),
                                  3600, 80.0)
    assert ivs2[0]["vibration_mm_s"] is None
