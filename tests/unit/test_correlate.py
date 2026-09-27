"""Unit tests: energy+health correlation categories + banned-words scan."""

import re

from services.machine_health.correlate import BANNED_WORDS, correlate

SANCTIONED = "not an established cause"  # the one approved disclaimer phrase
_BANNED_RE = re.compile(
    r"\bcause\b|\bcaused\b|\bbecause\b|due to|results from", re.IGNORECASE
)


def _ev(mid="furnace-01", ws="2026-09-20T00:00:00+05:30",
        we="2026-09-20T02:00:00+05:30", rule="L1_DEVIATION", dev=25.0):
    return {"machine_id": mid, "window_start": ws, "window_end": we,
            "rule_id": rule, "deviation_pct": dev, "severity": "WARNING",
            "evidence": "test"}


def _h(mid="furnace-01", ws="2026-09-20T01:00:00+05:30",
       we="2026-09-20T02:00:00+05:30", state="CRITICAL", status="OK"):
    return {"machine_id": mid, "window_start": ws, "window_end": we,
            "state": state, "status": status, "anomaly_score": 7.0,
            "health_score": 20.0,
            "contributions": [{"signal": "vibration_mm_s", "z": 7.0,
                               "pct_change": 150.0, "median": 2.0, "value": 5.0,
                               "weight": 0.8}]}


def _scan(texts):
    """Every generated insight text must carry no causation language,
    except the single sanctioned disclaimer phrase in COINCIDENT text."""
    for t in texts:
        cleaned = t.replace(SANCTIONED, "")
        assert not _BANNED_RE.search(cleaned), f"banned wording in: {t!r}"
        for w in BANNED_WORDS:
            assert w not in cleaned.lower() or w == "cause", (w, t)


def test_coincident_category_and_wording():
    out = correlate([_ev()], [_h()])
    assert len(out) == 1 and out[0]["category"] == "COINCIDENT"
    assert "coincides with machine-health anomaly" in out[0]["text"]
    assert "correlation, not an established cause" in out[0]["text"]
    assert "inspection recommended" in out[0]["text"]
    assert out[0]["energy_evidence"]["rule_id"] == "L1_DEVIATION"
    assert out[0]["health_evidence"]["top_signals"], "both evidences required"
    assert "inspect" in out[0]["next_step"].lower()
    _scan([out[0]["text"], out[0]["next_step"]])


def test_energy_only():
    out = correlate([_ev()], [_h(state="NORMAL")])
    assert [i["category"] for i in out] == ["ENERGY_ONLY"]
    _scan([i["text"] for i in out] + [i["next_step"] for i in out])


def test_health_only_merges_runs():
    h1 = _h(ws="2026-09-20T01:00:00+05:30", we="2026-09-20T02:00:00+05:30")
    h2 = _h(ws="2026-09-20T02:00:00+05:30", we="2026-09-20T03:00:00+05:30")
    out = correlate([], [h1, h2])
    assert len(out) == 1 and out[0]["category"] == "HEALTH_ONLY"
    assert out[0]["energy_evidence"] == {}
    assert out[0]["health_evidence"]["top_signals"]
    _scan([i["text"] for i in out] + [i["next_step"] for i in out])


def test_energy_only_health_unavailable():
    out = correlate([_ev()], [_h(status="UNAVAILABLE", state="NORMAL")])
    assert [i["category"] for i in out] == ["ENERGY_ONLY_HEALTH_UNAVAILABLE"]
    out = correlate([_ev()], [])
    assert [i["category"] for i in out] == ["ENERGY_ONLY_HEALTH_UNAVAILABLE"]
    _scan([i["text"] for i in out] + [i["next_step"] for i in out])


def test_banned_words_scan_all_categories():
    out = correlate(
        [_ev(), _ev(mid="compressor-01")],
        [_h(), _h(mid="pump-01", state="WARNING"),
         _h(mid="compressor-01", status="UNAVAILABLE", state="NORMAL")],
    )
    cats = {i["category"] for i in out}
    assert {"COINCIDENT", "HEALTH_ONLY", "ENERGY_ONLY_HEALTH_UNAVAILABLE"} <= cats
    _scan([i["text"] for i in out] + [i["next_step"] for i in out])
