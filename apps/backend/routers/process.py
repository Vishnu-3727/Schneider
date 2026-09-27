"""GET /process/efficiency — process-inefficiency findings (DERIVED).

Pure analytics live in services/energy/process_efficiency.py; this router
does DB I/O (telemetry/production/machines/baselines) and maps results to
JSON. Reference medians come from the latest baseline train window (NORMAL
history); with no baseline the findings carry reference None.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from services.energy.aggregate import build_intervals
from services.energy.process_efficiency import analyze, daily_metrics

router = APIRouter()


def _load_telemetry(db: Session, mid: str, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT ts, quality, energy_kwh, machine_state, power_kw, power_factor "
            "FROM telemetry WHERE machine_id = :m AND ts >= :start AND ts < :end "
            "ORDER BY ts"
        ),
        {"m": mid, "start": start, "end": end},
    ).fetchall()
    return [
        {"ts": r[0], "quality": r[1], "energy_kwh": r[2], "machine_state": r[3],
         "power_kw": r[4], "power_factor": r[5]}
        for r in rows
    ]


def _load_production(db: Session, mid: str, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT window_start, quality, qty_good_kg, qty_rejected_kg "
            "FROM production_record WHERE machine_id = :m "
            "AND window_start >= :start AND window_start < :end ORDER BY window_start"
        ),
        {"m": mid, "start": start, "end": end},
    ).fetchall()
    return [
        {"window_start": r[0], "quality": r[1], "qty_good_kg": r[2], "qty_rejected_kg": r[3]}
        for r in rows
    ]


def _latest_train_window(db: Session, mid: str):
    r = db.execute(
        text(
            "SELECT train_start, train_end FROM energy_baseline "
            "WHERE machine_id = :m ORDER BY created_at DESC LIMIT 1"
        ),
        {"m": mid},
    ).fetchone()
    return (r[0], r[1]) if r else (None, None)


@router.get("/process/efficiency")
def process_efficiency(start: datetime, end: datetime,
                       machine_id: str | None = Query(default=None),
                       db: Session = Depends(get_db)):
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start/end must be timezone-aware")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    s = get_settings()
    if machine_id is not None:
        rows = db.execute(
            text("SELECT id, site_id, name, machine_type, rated_power_kw "
                 "FROM machine WHERE id = :m"),
            {"m": machine_id},
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail=f"Unknown machine_id: {machine_id}")
    else:
        rows = db.execute(
            text("SELECT id, site_id, name, machine_type, rated_power_kw FROM machine")
        ).fetchall()
    machines = {r[0]: {"machine_type": r[3]} for r in rows}
    out = []
    for mid, m in machines.items():
        tel = _load_telemetry(db, mid, start, end)
        prod = _load_production(db, mid, start, end)
        intervals = build_intervals(mid, tel, prod, start, end,
                                    s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT)
        samples = [(r["ts"], r["machine_state"]) for r in tel
                   if r["quality"] == "GOOD" and r["machine_state"]]
        ref_start, ref_end = _latest_train_window(db, mid)
        ref_daily = None
        if ref_start is not None and ref_end is not None:
            ref_intervals = build_intervals(
                mid, _load_telemetry(db, mid, ref_start, ref_end),
                _load_production(db, mid, ref_start, ref_end),
                ref_start, ref_end, s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT)
            ref_tel = _load_telemetry(db, mid, ref_start, ref_end)
            ref_samples = [(r["ts"], r["machine_state"]) for r in ref_tel
                           if r["quality"] == "GOOD" and r["machine_state"]]
            ref_daily = daily_metrics(mid, m["machine_type"], ref_intervals, ref_samples,
                                        s.TZ)
        out.extend(analyze(mid, m["machine_type"], intervals, samples,
                           ref_daily, s.PROCESS_MIN_HOLD_H, s.TZ))
    return {"results": out}
