"""GET /insights — energy + health correlation, computed on read (no writes).

Loads energy AnomalyEvents and stored machine_health intervals overlapping
[start, end) and joins them with the pure services/machine_health/correlate
function. This router never invokes a health model, so a model failure
cannot break it; it only reads DERIVED rows.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.db import get_db
from services.machine_health.correlate import correlate

router = APIRouter()


@router.get("/insights")
def get_insights(start: datetime, end: datetime, db: Session = Depends(get_db)):
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start/end must be timezone-aware")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    erows = db.execute(
        text(
            "SELECT machine_id, window_start, window_end, metric, rule_id, level, score, "
            "severity, expected_kwh, actual_kwh, deviation_kwh, deviation_pct, evidence, "
            "status, source, created_at FROM anomaly_event "
            "WHERE window_start < :en AND window_end > :st "
            "ORDER BY window_start"
        ),
        {"st": start, "en": end},
    ).fetchall()
    ecols = ["machine_id", "window_start", "window_end", "metric", "rule_id", "level",
             "score", "severity", "expected_kwh", "actual_kwh", "deviation_kwh",
             "deviation_pct", "evidence", "status", "source", "created_at"]
    events = []
    for r in erows:
        d = dict(zip(ecols, r, strict=True))
        d["window_start"] = d["window_start"].isoformat()
        d["window_end"] = d["window_end"].isoformat()
        d["created_at"] = d["created_at"].isoformat()
        events.append(d)
    hrows = db.execute(
        text(
            "SELECT machine_id, window_start, window_end, model_id, health_score, "
            "anomaly_score, state, status, reason, contributions "
            "FROM machine_health WHERE window_start < :en AND window_end > :st "
            "ORDER BY window_start"
        ),
        {"st": start, "en": end},
    ).fetchall()
    hcols = ["machine_id", "window_start", "window_end", "model_id", "health_score",
             "anomaly_score", "state", "status", "reason", "contributions"]
    health = []
    for r in hrows:
        d = dict(zip(hcols, r, strict=True))
        d["window_start"] = d["window_start"].isoformat()
        d["window_end"] = d["window_end"].isoformat()
        health.append(d)
    return {"insights": correlate(events, health)}
