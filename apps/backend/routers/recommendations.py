"""POST /recommendations/generate + GET /recommendations + acknowledge (Phase 4B).

Human-in-the-loop decision support only: generation is idempotent pure
rules over open AnomalyEvents, Phase-3 health rows (correlated on read),
process-efficiency findings and the latest overlapping optimization_run
per machine (any status — INFEASIBLE explanations are surfaced, never
hidden). Health-model or optimizer gaps never block the remaining
sources. Acknowledge writes an audit_event row per decision; an approved
recommendation stays NOT_VERIFIED until an intervention is applied and
verified (apps/backend/routers/interventions.py, Phase 5).
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.schemas import (
    RecommendationAcknowledgeRequest,
    RecommendationGenerateRequest,
)
from services.energy.aggregate import build_intervals
from services.energy.process_efficiency import analyze, daily_metrics
from services.recommendations.engine import generate
from services.verification import lifecycle

router = APIRouter()

RECOMMENDABLE = (
    "id", "machine_id", "rule_id", "title", "severity", "reason", "evidence",
    "constraints_considered", "proposed_action", "expected_effect",
    "confidence", "confidence_reason", "assumptions", "source_module",
    "source_class", "status", "verification_status", "conflict_with",
    "conflict_note", "window_start", "window_end", "dedup_key",
    "decided_at", "decided_note", "created_at",
)


def _rec_to_json(row) -> dict:
    d = dict(zip(RECOMMENDABLE, row, strict=True))
    d["id"] = str(d["id"])
    for k in ("window_start", "window_end", "decided_at", "created_at"):
        d[k] = d[k].isoformat() if d[k] is not None else None
    return d


def _open_anomalies(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, machine_id, window_start, window_end, metric, rule_id, level, "
            "score, severity, expected_kwh, actual_kwh, deviation_kwh, deviation_pct, "
            "evidence, status, source, created_at FROM anomaly_event "
            "WHERE status = 'OPEN' AND window_start < :en AND window_end > :st "
            "ORDER BY window_start"
        ),
        {"st": start, "en": end},
    ).fetchall()
    cols = ["id", "machine_id", "window_start", "window_end", "metric", "rule_id",
            "level", "score", "severity", "expected_kwh", "actual_kwh",
            "deviation_kwh", "deviation_pct", "evidence", "status", "source",
            "created_at"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _health_rows(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT machine_id, window_start, window_end, model_id, health_score, "
            "anomaly_score, state, status, reason, contributions "
            "FROM machine_health WHERE window_start < :en AND window_end > :st "
            "ORDER BY window_start"
        ),
        {"st": start, "en": end},
    ).fetchall()
    cols = ["machine_id", "window_start", "window_end", "model_id", "health_score",
            "anomaly_score", "state", "status", "reason", "contributions"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _latest_runs(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, machine_id, horizon_start, horizon_end, inputs_hash, "
            "constraints, status, current_schedule, recommended_schedule, "
            "metrics, explanation, source, created_at FROM optimization_run "
            "WHERE horizon_start < :en AND horizon_end > :st "
            "ORDER BY created_at DESC"
        ),
        {"st": start, "en": end},
    ).fetchall()
    cols = ["id", "machine_id", "horizon_start", "horizon_end", "inputs_hash",
            "constraints", "status", "current_schedule", "recommended_schedule",
            "metrics", "explanation", "source", "created_at"]
    seen: set[str] = set()
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        if d["machine_id"] in seen:
            continue
        seen.add(d["machine_id"])
        d["id"] = str(d["id"])
        d["horizon_start"] = d["horizon_start"].isoformat()
        d["horizon_end"] = d["horizon_end"].isoformat()
        d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


def _tariff_label(db: Session) -> str:
    rows = db.execute(text("SELECT DISTINCT source_class FROM tariff")).fetchall()
    if not rows:
        return "absent"
    classes = {r[0] for r in rows}
    if classes == {"ASSUMPTION"}:
        return "ILLUSTRATIVE (ASSUMPTION)"
    return "plant tariff"


def _process_analyses(db: Session, start: datetime, end: datetime) -> list[dict]:
    s = get_settings()
    mrows = db.execute(
        text("SELECT id, machine_type FROM machine")).fetchall()
    out = []
    for mid, mtype in mrows:
        tel = db.execute(
            text(
                "SELECT ts, quality, energy_kwh, machine_state, power_kw, power_factor "
                "FROM telemetry WHERE machine_id = :m AND ts >= :start AND ts < :end "
                "ORDER BY ts"
            ),
            {"m": mid, "start": start, "end": end},
        ).fetchall()
        tel_d = [{"ts": r[0], "quality": r[1], "energy_kwh": r[2],
                  "machine_state": r[3], "power_kw": r[4], "power_factor": r[5]}
                 for r in tel]
        prod = db.execute(
            text(
                "SELECT window_start, quality, qty_good_kg, qty_rejected_kg "
                "FROM production_record WHERE machine_id = :m "
                "AND window_start >= :start AND window_start < :end ORDER BY window_start"
            ),
            {"m": mid, "start": start, "end": end},
        ).fetchall()
        prod_d = [{"window_start": r[0], "quality": r[1],
                   "qty_good_kg": r[2], "qty_rejected_kg": r[3]} for r in prod]
        intervals = build_intervals(mid, tel_d, prod_d, start, end,
                                    s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT)
        samples = [(r["ts"], r["machine_state"]) for r in tel_d
                   if r["quality"] == "GOOD" and r["machine_state"]]
        ref = db.execute(
            text("SELECT train_start, train_end FROM energy_baseline "
                 "WHERE machine_id = :m ORDER BY created_at DESC LIMIT 1"),
            {"m": mid},
        ).fetchone()
        ref_daily = None
        if ref is not None:
            rs, re = ref[0], ref[1]
            rtel = db.execute(
                text(
                    "SELECT ts, quality, energy_kwh, machine_state, power_kw, power_factor "
                    "FROM telemetry WHERE machine_id = :m AND ts >= :start AND ts < :end "
                    "ORDER BY ts"
                ),
                {"m": mid, "start": rs, "end": re},
            ).fetchall()
            rtel_d = [{"ts": r[0], "quality": r[1], "energy_kwh": r[2],
                       "machine_state": r[3], "power_kw": r[4], "power_factor": r[5]}
                      for r in rtel]
            rprod = db.execute(
                text(
                    "SELECT window_start, quality, qty_good_kg, qty_rejected_kg "
                    "FROM production_record WHERE machine_id = :m "
                    "AND window_start >= :start AND window_start < :end ORDER BY window_start"
                ),
                {"m": mid, "start": rs, "end": re},
            ).fetchall()
            rprod_d = [{"window_start": r[0], "quality": r[1],
                        "qty_good_kg": r[2], "qty_rejected_kg": r[3]} for r in rprod]
            ref_intervals = build_intervals(mid, rtel_d, rprod_d, rs, re,
                                            s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT)
            ref_samples = [(r["ts"], r["machine_state"]) for r in rtel_d
                           if r["quality"] == "GOOD" and r["machine_state"]]
            ref_daily = daily_metrics(mid, mtype, ref_intervals, ref_samples, s.TZ)
        out.extend(analyze(mid, mtype, intervals, samples, ref_daily,
                           s.PROCESS_MIN_HOLD_H, s.TZ))
    return out


@router.post("/recommendations/generate")
def generate_recommendations(body: RecommendationGenerateRequest,
                             db: Session = Depends(get_db)):
    anomalies = _open_anomalies(db, body.start, body.end)
    health = _health_rows(db, body.start, body.end)
    analyses = _process_analyses(db, body.start, body.end)
    runs = _latest_runs(db, body.start, body.end)
    label = _tariff_label(db)
    candidates = generate(anomalies, health, analyses, runs, label)
    created, existing = 0, 0
    for rec in candidates:
        r = db.execute(
            text(
                "INSERT INTO recommendation (machine_id, rule_id, title, severity, reason, "
                "evidence, constraints_considered, proposed_action, expected_effect, "
                "confidence, confidence_reason, assumptions, source_module, source_class, "
                "status, verification_status, conflict_with, conflict_note, "
                "window_start, window_end, dedup_key) "
                "VALUES (:m, :rule, :title, :sev, :reason, CAST(:ev AS jsonb), "
                "CAST(:cc AS jsonb), :pa, CAST(:ee AS jsonb), :conf, :confr, "
                "CAST(:asm AS jsonb), :sm, :sc, :st, :vs, CAST(:cw AS jsonb), :cn, "
                ":ws, :we, :dd) ON CONFLICT (dedup_key) DO NOTHING RETURNING id"
            ),
            {"m": rec["machine_id"], "rule": rec["rule_id"], "title": rec["title"],
             "sev": rec["severity"], "reason": rec["reason"],
             "ev": json.dumps(rec["evidence"]), "cc": json.dumps(rec["constraints_considered"]),
             "pa": rec["proposed_action"],
             "ee": json.dumps(rec["expected_effect"]) if rec["expected_effect"] is not None else None,
             "conf": rec["confidence"], "confr": rec.get("confidence_reason", ""),
             "asm": json.dumps(rec["assumptions"]), "sm": rec["source_module"],
             "sc": rec["source_class"], "st": rec["status"], "vs": rec["verification_status"],
             "cw": json.dumps(rec["conflict_with"]), "cn": rec.get("conflict_note", ""),
             "ws": rec["window_start"], "we": rec["window_end"], "dd": rec["dedup_key"]},
        ).fetchone()
        if r is None:
            existing += 1
        else:
            created += 1
        if rec["conflict_with"]:
            db.execute(
                text(
                    "UPDATE recommendation SET status = 'CONFLICT', "
                    "conflict_with = CAST(:cw AS jsonb), conflict_note = :cn "
                    "WHERE dedup_key = :dd AND status IN ('PENDING_REVIEW', 'CONFLICT')"
                ),
                {"cw": json.dumps(rec["conflict_with"]), "cn": rec.get("conflict_note", ""),
                 "dd": rec["dedup_key"]},
            )
    db.commit()
    rows = db.execute(
        text("SELECT " + ", ".join(RECOMMENDABLE) + " FROM recommendation "
             "WHERE dedup_key = ANY(:dds) ORDER BY machine_id, rule_id"),
        {"dds": [c["dedup_key"] for c in candidates]},
    ).fetchall() if candidates else []
    return {"created": created, "already_existing": existing,
            "recommendations": [_rec_to_json(r) for r in rows]}


@router.get("/recommendations")
def list_recommendations(machine_id: str | None = Query(default=None),
                         status: str | None = Query(default=None),
                         db: Session = Depends(get_db)):
    q = "SELECT " + ", ".join(RECOMMENDABLE) + " FROM recommendation"
    conds, params = [], {}
    if machine_id:
        conds.append("machine_id = :m")
        params["m"] = machine_id
    if status:
        conds.append("status = :st")
        params["st"] = status
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY created_at DESC"
    rows = db.execute(text(q), params).fetchall()
    return {"recommendations": [_rec_to_json(r) for r in rows]}


@router.post("/recommendations/{rec_id}/acknowledge")
def acknowledge(rec_id: str, body: RecommendationAcknowledgeRequest,
                db: Session = Depends(get_db)):
    try:
        uuid_cast = "CAST(:i AS uuid)"
        row = db.execute(
            text("SELECT " + ", ".join(RECOMMENDABLE) + " FROM recommendation "
                 f"WHERE id = {uuid_cast}"),
            {"i": rec_id},
        ).fetchone()
    except Exception:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation id: {rec_id}")
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation id: {rec_id}")
    d = dict(zip(RECOMMENDABLE, row, strict=True))
    if not lifecycle.can(d["status"], body.decision):
        raise HTTPException(
            status_code=409,
            detail=(f"Recommendation already decided or past review: status {d['status']}; "
                    f"allowed next: {list(lifecycle.allowed(d['status'])) or 'none'}"))
    updated = db.execute(
        text(
            "UPDATE recommendation SET status = :st, decided_at = now(), "
            "decided_note = :note WHERE id = CAST(:i AS uuid) RETURNING "
            + ", ".join(RECOMMENDABLE)
        ),
        {"st": body.decision, "note": body.note, "i": rec_id},
    ).fetchone()
    db.execute(
        text(
            "INSERT INTO audit_event (action, entity, entity_id, detail_json) "
            "VALUES ('recommendation.acknowledge', 'recommendation', :eid, "
            "CAST(:det AS jsonb))"
        ),
        {"eid": str(d["id"]),
         "det": json.dumps({"decision": body.decision, "note": body.note,
                            "previous_status": d["status"]})},
    )
    db.commit()
    return _rec_to_json(updated)
