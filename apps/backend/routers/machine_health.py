"""Phase 3A machine-health API: reference fit, interval scoring, listing, models.

All analytics are pure functions in services/machine_health/; this router
does DB I/O and maps results to JSON. A health-model failure (exception)
is caught per machine and persisted/returned as status ERROR — it NEVER
propagates as a 500 traceback, and this router is never imported by the
energy or dashboard routers (a health failure cannot break /energy/* or
/dashboard/summary).
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.routers.energy import _resolve_machines
from apps.backend.schemas import HealthFitRequest, HealthScoreRequest
from services.machine_health import FACTORY_MODEL_ID, REGISTRY, make_model
from services.machine_health.statistical import build_health_intervals

router = APIRouter()


def _thresholds() -> dict:
    s = get_settings()
    return {
        "min_ref_intervals": s.HEALTH_MIN_REF_INTERVALS,
        "min_bucket_rows": s.HEALTH_MIN_BUCKET_ROWS,
        "warn_z": s.HEALTH_WARN_Z,
        "crit_z": s.HEALTH_CRIT_Z,
        "mad_floor_frac": s.HEALTH_MAD_FLOOR_FRAC,
        "mad_epsilon": s.HEALTH_MAD_EPSILON,
    }


def _make_model(model_id: str):
    """Instantiate a registry model: statistical thresholds for the native
    model, local artifact paths for the PBL adapter (each ignores the
    other's kwargs)."""
    from services.machine_health.pbl_adapter import PBLRulAdapter

    if model_id == PBLRulAdapter.model_id:
        s = get_settings()
        return PBLRulAdapter(onnx_path=s.PBL_ONNX_PATH,
                             sensor_vocab_path=s.PBL_SENSOR_VOCAB_PATH)
    return make_model(model_id, **_thresholds())


def _default_model_id() -> str:
    return get_settings().HEALTH_MODEL_ID


def _load_health_telemetry(db: Session, mid: str, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT ts, quality, machine_state, vibration_mm_s, temperature_c, current_a "
            "FROM telemetry WHERE machine_id = :m AND ts >= :start AND ts < :end "
            "ORDER BY ts"
        ),
        {"m": mid, "start": start, "end": end},
    ).fetchall()
    return [
        {"ts": r[0], "quality": r[1], "machine_state": r[2],
         "vibration_mm_s": r[3], "temperature_c": r[4], "current_a": r[5]}
        for r in rows
    ]


def _latest_references(db: Session, model_id: str) -> dict[str, dict]:
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (machine_id) machine_id, id, model_id, params, "
            "train_start, train_end, n_intervals, source, created_at "
            "FROM machine_health_reference WHERE model_id = :mid "
            "ORDER BY machine_id, created_at DESC"
        ),
        {"mid": model_id},
    ).fetchall()
    return {
        r[0]: {"id": str(r[1]), "model_id": r[2], "params": r[3],
               "train_start": r[4], "train_end": r[5],
               "n_intervals": r[6], "source": r[7], "created_at": r[8]}
        for r in rows
    }


def _row_to_json(d: dict) -> dict:
    out = dict(d)
    for k in ("window_start", "window_end", "train_start", "train_end", "created_at"):
        if k in out and out[k] is not None and hasattr(out[k], "isoformat"):
            out[k] = out[k].isoformat()
    if "id" in out and out["id"] is not None:
        out["id"] = str(out["id"])
    return out


@router.post("/machine-health/fit")
def fit(body: HealthFitRequest, db: Session = Depends(get_db)):
    s = get_settings()
    model_id = body.model_id or _default_model_id()
    try:
        _make_model(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    machines = _resolve_machines(db, body.machine_id)
    results = []
    for mid in machines:
        intervals = build_health_intervals(
            mid, _load_health_telemetry(db, mid, body.start, body.end),
            body.start, body.end, s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT,
        )
        try:
            model = _make_model(model_id)
            params = model.fit(intervals)
            n = int(params.get("n_intervals", 0))
        except Exception as e:  # failure -> ERROR, never a traceback
            results.append({"machine_id": mid, "model_id": model_id,
                            "status": "ERROR", "reason": f"{type(e).__name__}: {e}"})
            continue
        if n < s.HEALTH_MIN_REF_INTERVALS:
            results.append({"machine_id": mid, "model_id": model_id,
                            "status": "INSUFFICIENT_HISTORY", "n_intervals": n,
                            "need": s.HEALTH_MIN_REF_INTERVALS})
            continue
        row = db.execute(
            text(
                "INSERT INTO machine_health_reference (model_id, machine_id, params, "
                "train_start, train_end, n_intervals, source) "
                "VALUES (:mid, :m, CAST(:p AS jsonb), :ts, :te, :n, 'DERIVED') "
                "RETURNING id, created_at"
            ),
            {"mid": model_id, "m": mid, "p": json.dumps(params),
             "ts": body.start, "te": body.end, "n": n},
        ).fetchone()
        results.append({"machine_id": mid, "model_id": model_id, "status": "OK",
                        "reference_id": str(row[0]), "n_intervals": n,
                        "train_start": body.start.isoformat(),
                        "train_end": body.end.isoformat(),
                        "source": "DERIVED", "created_at": row[1].isoformat()})
    db.commit()
    return {"fits": results}


@router.post("/machine-health/score")
def score(body: HealthScoreRequest, db: Session = Depends(get_db)):
    s = get_settings()
    model_id = body.model_id or _default_model_id()
    try:
        _make_model(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    machines = _resolve_machines(db, body.machine_id)
    refs = _latest_references(db, model_id)
    created, existing = 0, 0
    summary = []
    for mid in machines:
        intervals = build_health_intervals(
            mid, _load_health_telemetry(db, mid, body.start, body.end),
            body.start, body.end, s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT,
        )
        if model_id != FACTORY_MODEL_ID:
            # Non-factory model (pbl-rul): factory machines are OUT_OF_DOMAIN
            # by construction -- the adapter never emits scores for them.
            # Scoring factory machines always uses statistical-v1.
            adapter = _make_model(model_id)
            mtype = machines[mid].get("machine_type", "factory-machine")
            for iv in intervals:
                iv["machine_type"] = mtype
            try:
                results = adapter.predict(intervals)
                contribs = adapter.explain(intervals)
            except Exception as e:  # failure -> ERROR rows, never a traceback
                results = [{"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "ERROR",
                            "reason": f"{type(e).__name__}: {e}"} for _ in intervals]
                contribs = [[] for _ in intervals]
        else:
            ref = refs.get(mid)
            if ref is None:
                # No fitted reference: not a model failure, just nothing to
                # score against -> INSUFFICIENT_HISTORY rows (stored, idempotent).
                results = [{"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "INSUFFICIENT_HISTORY",
                            "reason": f"no fitted reference for machine {mid} model "
                                      f"{model_id}; POST /machine-health/fit first"}
                           for _ in intervals]
                contribs = [[] for _ in intervals]
            else:
                try:
                    from services.machine_health.statistical import StatisticalHealthModel
                    model = StatisticalHealthModel.from_params(ref["params"], **_thresholds())
                    # score() (not predict) so a failure in either entry point is
                    # exercised the same way; exceptions -> ERROR rows below.
                    results = model.score(intervals)
                    contribs = model.explain(intervals)
                except Exception as e:  # failure -> ERROR rows, never a traceback
                    results = [{"health_score": None, "anomaly_score": None,
                                "state": "NORMAL", "status": "ERROR",
                                "reason": f"{type(e).__name__}: {e}"} for _ in intervals]
                    contribs = [[] for _ in intervals]
        n_warn = n_crit = 0
        for iv, res, contrib in zip(intervals, results, contribs, strict=True):
            if res["state"] == "WARNING":
                n_warn += 1
            elif res["state"] == "CRITICAL":
                n_crit += 1
            r = db.execute(
                text(
                    "INSERT INTO machine_health (machine_id, window_start, window_end, "
                    "model_id, health_score, anomaly_score, state, status, reason, "
                    "contributions, source) VALUES (:m, :ws, :we, :mid, :hs, :an, "
                    ":st, :ss, :re, CAST(:c AS jsonb), 'DERIVED') "
                    "ON CONFLICT (machine_id, window_start, window_end, model_id) "
                    "DO NOTHING RETURNING id"
                ),
                {"m": mid, "ws": iv["window_start"], "we": iv["window_end"],
                 "mid": model_id, "hs": res["health_score"], "an": res["anomaly_score"],
                 "st": res["state"], "ss": res["status"], "re": res["reason"],
                 "c": json.dumps(contrib)},
            ).fetchone()
            if r is None:
                existing += 1
            else:
                created += 1
        summary.append({"machine_id": mid, "model_id": model_id,
                        "n_intervals": len(intervals),
                        "n_warning": n_warn, "n_critical": n_crit})
    db.commit()
    return {"created": created, "already_existing": existing, "results": summary}


@router.get("/machine-health")
def list_health(machine_id: str | None = Query(default=None),
                start: datetime | None = Query(default=None),
                end: datetime | None = Query(default=None),
                model_id: str | None = Query(default=None),
                db: Session = Depends(get_db)):
    q = ("SELECT id, machine_id, window_start, window_end, model_id, health_score, "
         "anomaly_score, state, status, reason, contributions, source, created_at "
         "FROM machine_health")
    conds, params = [], {}
    if machine_id:
        conds.append("machine_id = :m")
        params["m"] = machine_id
    if model_id:
        conds.append("model_id = :mid")
        params["mid"] = model_id
    if start:
        conds.append("window_start >= :st")
        params["st"] = start
    if end:
        conds.append("window_start < :en")
        params["en"] = end
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY window_start"
    rows = db.execute(text(q), params).fetchall()
    cols = ["id", "machine_id", "window_start", "window_end", "model_id",
            "health_score", "anomaly_score", "state", "status", "reason",
            "contributions", "source", "created_at"]
    return {"health": [_row_to_json(dict(zip(cols, r, strict=True))) for r in rows]}


@router.get("/machine-health/models")
def list_models(db: Session = Depends(get_db)):
    from services.machine_health.pbl_adapter import PBLRulAdapter

    out = []
    for mid in REGISTRY:
        try:
            model = _make_model(mid)
            meta = model.metadata()
            error = None
        except Exception as e:  # never a traceback; model reports unavailable
            model, meta, error = None, {}, f"{type(e).__name__}: {e}"
        if mid == PBLRulAdapter.model_id:
            # External adapter: availability = artifact loadable; factory
            # machines are OUT_OF_DOMAIN regardless (it never scores them).
            avail = model.availability() if model is not None else {
                "status": "UNAVAILABLE", "reason": error or "unknown error"}
            factory_status = ("OUT_OF_DOMAIN" if avail["status"] == "AVAILABLE"
                              else "UNAVAILABLE")
            entry = {"model_id": mid, "metadata": meta,
                     "available": avail["status"] == "AVAILABLE",
                     "active_for_factory_machines": False,
                     "factory_status": factory_status,
                     "factory_reason": (
                         "pbl-rul trained on turbofan sensor channels; not "
                         "validated for furnace/compressor/pump; retraining "
                         "on plant data required" if factory_status == "OUT_OF_DOMAIN"
                         else avail["reason"]),
                     "artifact_status": avail,
                     "machines_with_reference": []}
        else:
            available = error is None
            rows = db.execute(
                text("SELECT DISTINCT machine_id FROM machine_health_reference "
                     "WHERE model_id = :m"),
                {"m": mid},
            ).fetchall() if available else []
            entry = {"model_id": mid, "metadata": meta, "available": available,
                     "active_for_factory_machines": (mid == FACTORY_MODEL_ID),
                     "machines_with_reference": sorted(r[0] for r in rows)}
        if error:
            entry["error"] = error
        out.append(entry)
    return {"models": out}
