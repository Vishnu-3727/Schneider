"""Energy + health correlation (pure, no DB).

For each machine and time window, energy AnomalyEvents are joined with
health WARNING/CRITICAL intervals by time overlap:

    ENERGY_ONLY                   energy event, health NORMAL around it
    HEALTH_ONLY                   health WARNING/CRITICAL, no energy event
    COINCIDENT                    overlap of both (correlation, never causation)
    ENERGY_ONLY_HEALTH_UNAVAILABLE energy event while health data is missing

Wording rule: COINCIDENT text is exactly
    'Energy anomaly coincides with machine-health anomaly (<signals>).
     This is a correlation, not an established cause; inspection recommended.'
The words cause/caused/because/due to/results from MUST NEVER appear in any
insight text (a unit test scans every generated text for them).

Inputs are plain dicts with ISO or datetime window_start/window_end:
  energy_events: {machine_id, window_start, window_end, rule_id,
                  deviation_pct, severity, evidence}
  health_rows:   {machine_id, window_start, window_end, state, status,
                  anomaly_score, health_score, contributions}
Output insights: {category, machine_id, window_start, window_end,
  energy_evidence, health_evidence, text, next_step}.
"""

from __future__ import annotations

from datetime import datetime

CATEGORIES = (
    "ENERGY_ONLY",
    "HEALTH_ONLY",
    "COINCIDENT",
    "ENERGY_ONLY_HEALTH_UNAVAILABLE",
)

#: Words/phrases banned from every insight text (causation language).
BANNED_WORDS = ("cause", "caused", "because", "due to", "results from")

ABNORMAL_HEALTH = frozenset({"WARNING", "CRITICAL"})


def _as_dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return _as_dt(a_start) < _as_dt(b_end) and _as_dt(a_end) > _as_dt(b_start)


def _signal_names(contribs) -> list[str]:
    names = []
    for c in contribs or []:
        s = c.get("signal") if isinstance(c, dict) else None
        if s and s not in names:
            names.append(s)
    return names


def _health_evidence(rows: list[dict]) -> dict:
    """Top contributing signals across the given abnormal health rows."""
    best: dict[str, dict] = {}
    for r in rows:
        for c in r.get("contributions") or []:
            if not isinstance(c, dict) or "signal" not in c:
                continue
            s = c["signal"]
            prev = best.get(s)
            z = abs(c.get("z") or 0)
            if prev is None or z > abs(prev.get("z") or 0):
                best[s] = c
    top = sorted(best.values(), key=lambda c: abs(c.get("z") or 0), reverse=True)[:3]
    states = sorted({r.get("state") for r in rows if r.get("state")})
    return {
        "n_intervals": len(rows),
        "states": states,
        "top_signals": [
            {"signal": c.get("signal"), "z": c.get("z"),
             "pct_change": c.get("pct_change"), "median": c.get("median"),
             "value": c.get("value")}
            for c in top
        ],
    }


def correlate(
    energy_events: list[dict],
    health_rows: list[dict],
) -> list[dict]:
    """Join energy events with health intervals by overlap (pure)."""
    insights: list[dict] = []
    machines = sorted(
        {e.get("machine_id") for e in energy_events}
        | {h.get("machine_id") for h in health_rows if h.get("state") in ABNORMAL_HEALTH}
    )
    for mid in machines:
        evs = [e for e in energy_events if e.get("machine_id") == mid]
        hrows = [h for h in health_rows if h.get("machine_id") == mid]
        abnormal = [h for h in hrows if h.get("state") in ABNORMAL_HEALTH
                    and h.get("status") == "OK"]
        matched_health: set[int] = set()

        for e in evs:
            over = [h for h in abnormal
                    if _overlaps(e["window_start"], e["window_end"],
                                 h["window_start"], h["window_end"])]
            for h in over:
                matched_health.add(id(h))
            e_ev = {
                "rule_id": e.get("rule_id"),
                "severity": e.get("severity"),
                "deviation_pct": e.get("deviation_pct"),
                "window_start": str(e.get("window_start")),
                "window_end": str(e.get("window_end")),
            }
            if over:
                h_ev = _health_evidence(over)
                signals = ", ".join(s for s in _signal_names(
                    [c for h in over for c in (h.get("contributions") or [])])[:3]) or "health signals"
                ws = min(_as_dt(e["window_start"]),
                         min(_as_dt(h["window_start"]) for h in over))
                we = max(_as_dt(e["window_end"]),
                         max(_as_dt(h["window_end"]) for h in over))
                insights.append({
                    "category": "COINCIDENT",
                    "machine_id": mid,
                    "window_start": ws.isoformat(), "window_end": we.isoformat(),
                    "energy_evidence": e_ev,
                    "health_evidence": h_ev,
                    "text": (
                        f"Energy anomaly coincides with machine-health anomaly "
                        f"({signals}). This is a correlation, not an established "
                        f"cause; inspection recommended."
                    ),
                    "next_step": (
                        f"Inspect {mid} for wear, fouling or sensor drift; "
                        f"compare energy deviation "
                        f"({e.get('deviation_pct')}) against the health signals "
                        f"above before scheduling maintenance."
                    ),
                })
            else:
                window_health = [
                    h for h in hrows
                    if _overlaps(e["window_start"], e["window_end"],
                                 h["window_start"], h["window_end"])
                ]
                ok_rows = [h for h in window_health if h.get("status") == "OK"]
                if not ok_rows:
                    # No usable health record here: rows missing entirely,
                    # or all non-OK (UNAVAILABLE / INSUFFICIENT_HISTORY /
                    # OUT_OF_DOMAIN / ERROR). Joint assessment is impossible.
                    n_missing = len(window_health)
                    insights.append({
                        "category": "ENERGY_ONLY_HEALTH_UNAVAILABLE",
                        "machine_id": mid,
                        "window_start": str(e.get("window_start")),
                        "window_end": str(e.get("window_end")),
                        "energy_evidence": e_ev,
                        "health_evidence": {"n_intervals": n_missing,
                                            "states": [], "top_signals": []},
                        "text": (
                            f"Energy anomaly on {mid} with no matching "
                            f"machine-health record ({n_missing} overlapping "
                            f"interval(s) unavailable). Health data is missing, "
                            f"so a joint assessment is not possible; inspection "
                            f"recommended."
                        ),
                        "next_step": (
                            f"Check the health sensors (vibration, temperature, "
                            f"current) on {mid}, then inspect the machine."
                        ),
                    })
                else:
                    insights.append({
                        "category": "ENERGY_ONLY",
                        "machine_id": mid,
                        "window_start": str(e.get("window_start")),
                        "window_end": str(e.get("window_end")),
                        "energy_evidence": e_ev,
                        "health_evidence": {"n_intervals": 0, "states": ["NORMAL"],
                                            "top_signals": []},
                        "text": (
                            f"Energy anomaly on {mid} while machine-health "
                            f"signals stayed within their NORMAL range. No "
                            f"health anomaly overlaps this window; inspection "
                            f"recommended if the deviation persists."
                        ),
                        "next_step": (
                            f"Review process and scheduling around {mid} "
                            f"(idle time, load changes); inspect the machine "
                            f"if energy stays above expected."
                        ),
                    })

        # HEALTH_ONLY: merge consecutive abnormal intervals with no energy overlap.
        unmatched = [h for h in abnormal if id(h) not in matched_health]
        unmatched.sort(key=lambda h: _as_dt(h["window_start"]))
        run: list[dict] = []
        for h in unmatched:
            if run and _as_dt(h["window_start"]) <= _as_dt(run[-1]["window_end"]):
                run.append(h)
            else:
                if run:
                    insights.append(_health_only_insight(mid, run))
                run = [h]
        if run:
            insights.append(_health_only_insight(mid, run))
    return insights


def _health_only_insight(mid: str, run: list[dict]) -> dict:
    h_ev = _health_evidence(run)
    signals = ", ".join(s for s in _signal_names(
        [c for h in run for c in (h.get("contributions") or [])])[:3]) or "health signals"
    return {
        "category": "HEALTH_ONLY",
        "machine_id": mid,
        "window_start": str(min(h["window_start"] for h in run)),
        "window_end": str(max(h["window_end"] for h in run)),
        "energy_evidence": {},
        "health_evidence": h_ev,
        "text": (
            f"Machine-health anomaly on {mid} ({signals}) with energy "
            f"within its expected range. No energy anomaly overlaps this "
            f"window; inspection recommended."
        ),
        "next_step": (
            f"Inspect {mid} for early wear (vibration, temperature, current "
            f"trend); energy use is normal so no process change is indicated."
        ),
    }
