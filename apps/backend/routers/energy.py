"""Phase 2 energy API: baseline fit, energy summary, anomaly detect/list/ack.

All analytics are pure functions in services/energy/; this router does DB I/O
(load telemetry/production/machines/baselines, persist fits/events) and maps
results to JSON. DB down -> 503 via get_db (Phase-1 behaviour); invalid
windows -> 422 via Pydantic; unknown machine -> 404.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.routers._helpers import fetch_machines
from apps.backend.schemas import BaselineFitRequest, DetectRequest
from services.energy.aggregate import build_intervals
from services.energy.anomaly import build_events, l1_flags, l2_flags
from services.energy.baseline import deviation, features_for_machine_type, fit_baseline, predict
from services.energy.sec import compute_sec

router = APIRouter()


def _non_prod_types() -> list[str]:
    raw = get_settings().NON_PRODUCTION_TYPES or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


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


def _latest_baselines(db: Session) -> dict[str, dict]:
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (machine_id) machine_id, id, model_version, features, "
            "coefficients, intercept, train_start, train_end, n_intervals, r2_train, "
            "cv_rmse_pct_train, nmbe_pct_train, r2_holdout, cv_rmse_pct_holdout, "
            "nmbe_pct_holdout, acceptance, source, created_at "
            "FROM energy_baseline ORDER BY machine_id, created_at DESC"
        )
    ).fetchall()
    out = {}
    for r in rows:
        out[r[0]] = {
            "id": str(r[1]), "machine_id": r[0], "model_version": r[2], "features": r[3],
            "coefficients": r[4], "intercept": r[5], "train_start": r[6], "train_end": r[7],
            "n_intervals": r[8], "r2_train": r[9], "cv_rmse_pct_train": r[10],
            "nmbe_pct_train": r[11], "r2_holdout": r[12],
            "cv_rmse_pct_holdout": r[13], "nmbe_pct_holdout": r[14],
            "acceptance": r[15], "source": r[16],
            "created_at": r[17],
        }
    return out


def _score_intervals(db: Session, mid: str, mtype: str, start: datetime, end: datetime,
                     baseline: dict | None) -> list[dict]:
    """Build intervals and attach expected/deviation/SEC (pure scoring, no writes)."""
    s = get_settings()
    non_prod = _non_prod_types()
    intervals = build_intervals(
        mid, _load_telemetry(db, mid, start, end), _load_production(db, mid, start, end),
        start, end, s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT,
    )
    feats = baseline["features"] if baseline else features_for_machine_type(mtype, non_prod)
    coefs = baseline["coefficients"] if baseline else {}
    intercept = baseline["intercept"] if baseline else 0.0
    scored = []
    for iv in intervals:
        if baseline and iv.complete and iv.energy_kwh is not None:
            exp = predict(feats, coefs, intercept, iv.hours_by_state, iv.good_production_kg)
            dev = deviation(iv.energy_kwh, exp, s.EXPECTED_EPSILON_KWH)
            expected, dev_kwh, dev_pct, dev_status = (
                dev.expected_kwh, dev.deviation_kwh, dev.deviation_pct, dev.status)
        else:
            expected, dev_kwh, dev_pct = None, None, None
            dev_status = "INSUFFICIENT_BASELINE_HISTORY" if not baseline else (
                "OK" if not iv.complete else "INSUFFICIENT_BASELINE_HISTORY")
            if baseline and not iv.complete:
                dev_status = "INCOMPLETE_INTERVAL"
        sec = compute_sec(iv.energy_kwh, iv.good_production_kg, iv.has_production_record,
                          mtype, non_prod, iv.complete)
        scored.append({
            "machine_id": mid,
            "window_start": iv.window_start, "window_end": iv.window_end,
            "complete": iv.complete, "incomplete_reasons": iv.incomplete_reasons,
            "coverage_pct": iv.coverage_pct,
            "actual_kwh": iv.energy_kwh, "expected_kwh": expected,
            "deviation_kwh": dev_kwh, "deviation_pct": dev_pct,
            "deviation_status": dev_status,
            "hours_by_state": iv.hours_by_state,
            "good_production_kg": iv.good_production_kg,
            "power_max_kw": iv.power_max_kw, "pf_mean": iv.pf_mean,
            "sec_kwh_per_t": sec.sec_kwh_per_t, "sec_status": sec.status,
            "non_productive_kwh": sec.non_productive_kwh,
        })
    return scored


def _resolve_machines(db: Session, machine_id: str | None) -> dict[str, dict]:
    if machine_id is not None:
        machines = fetch_machines(db, [machine_id])
        if machine_id not in machines:
            raise HTTPException(status_code=404, detail=f"Unknown machine_id: {machine_id}")
        return machines
    rows = db.execute(text("SELECT id, site_id, name, machine_type, rated_power_kw FROM machine")).fetchall()
    return {r[0]: {"site_id": r[1], "name": r[2], "machine_type": r[3], "rated_power_kw": r[4]} for r in rows}


def _jsonable(scored: list[dict]) -> list[dict]:
    out = []
    for s in scored:
        row = dict(s)
        row["window_start"] = s["window_start"].isoformat()
        row["window_end"] = s["window_end"].isoformat()
        out.append(row)
    return out


@router.post("/energy/baseline/fit")
def fit(body: BaselineFitRequest, db: Session = Depends(get_db)):
    s = get_settings()
    non_prod = _non_prod_types()
    machines = _resolve_machines(db, body.machine_id)
    results = []
    for mid, m in machines.items():
        intervals = build_intervals(
            mid, _load_telemetry(db, mid, body.start, body.end),
            _load_production(db, mid, body.start, body.end),
            body.start, body.end, s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT,
        )
        res = fit_baseline(intervals, m["machine_type"], non_prod,
                           s.MIN_BASELINE_INTERVALS, s.BASELINE_HOLDOUT_FRACTION,
                           s.G14_CV_MAX_PCT, s.G14_NMBE_MAX_PCT)
        if res.status != "OK":
            results.append({"machine_id": mid, "status": res.status,
                            "n_intervals": res.n_intervals})
            continue
        row = db.execute(
            text(
                "INSERT INTO energy_baseline (machine_id, model_version, features, "
                "coefficients, intercept, train_start, train_end, n_intervals, "
                "r2_train, cv_rmse_pct_train, nmbe_pct_train, r2_holdout, "
                "cv_rmse_pct_holdout, nmbe_pct_holdout, acceptance, source) "
                "VALUES (:m, :v, CAST(:f AS jsonb), CAST(:c AS jsonb), :b, :ts, :te, "
                ":n, :r2, :cv, :nmbe, :r2h, :cvh, :nmbeh, :acc, 'DERIVED') "
                "RETURNING id, created_at"
            ),
            {"m": mid, "v": s.BASELINE_MODEL_VERSION, "f": json.dumps(res.features),
             "c": json.dumps(res.coefficients), "b": res.intercept,
             "ts": body.start, "te": body.end, "n": res.n_intervals,
             "r2": res.r2_train, "cv": res.cv_rmse_pct_train,
             "nmbe": res.nmbe_pct_train,
             "r2h": res.r2_holdout, "cvh": res.cv_rmse_pct_holdout,
             "nmbeh": res.nmbe_pct_holdout, "acc": res.acceptance},
        ).fetchone()
        results.append({
            "machine_id": mid, "status": "OK", "baseline_id": str(row[0]),
            "model_version": s.BASELINE_MODEL_VERSION, "features": res.features,
            "coefficients": res.coefficients, "intercept": res.intercept,
            "clipped": res.clipped, "n_intervals": res.n_intervals,
            "n_holdout": res.n_holdout, "r2_train": res.r2_train,
            "cv_rmse_pct_train": res.cv_rmse_pct_train,
            "nmbe_pct_train": res.nmbe_pct_train,
            "r2_holdout": res.r2_holdout,
            "cv_rmse_pct_holdout": res.cv_rmse_pct_holdout,
            "nmbe_pct_holdout": res.nmbe_pct_holdout,
            "acceptance": res.acceptance,
            "train_start": body.start.isoformat(), "train_end": body.end.isoformat(),
            "source": "DERIVED", "created_at": row[1].isoformat(),
        })
    db.commit()
    return {"fits": results}


@router.get("/energy/baseline")
def get_baselines(db: Session = Depends(get_db)):
    bl = _latest_baselines(db)
    out = []
    for b in bl.values():
        row = dict(b)
        row["train_start"] = b["train_start"].isoformat()
        row["train_end"] = b["train_end"].isoformat()
        row["created_at"] = b["created_at"].isoformat()
        out.append(row)
    return {"baselines": out}


@router.get("/energy/summary")
def energy_summary(start: datetime, end: datetime,
                   machine_id: str | None = Query(default=None),
                   db: Session = Depends(get_db)):
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start/end must be timezone-aware")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    machines = _resolve_machines(db, machine_id)
    baselines = _latest_baselines(db)
    s = get_settings()
    non_prod = _non_prod_types()
    out = []
    aggregates = []
    for mid, m in machines.items():
        scored = _score_intervals(db, mid, m["machine_type"], start, end,
                                  baselines.get(mid))
        out.extend(_jsonable(scored))
        aggregates.append(_window_aggregate(mid, m["machine_type"], scored, non_prod,
                                            s.EXPECTED_EPSILON_KWH,
                                            start.isoformat(), end.isoformat()))
    return {"intervals": out, "aggregates": aggregates}


def _window_aggregate(mid: str, mtype: str, scored: list[dict],
                      non_prod: list[str], epsilon_kwh: float,
                      start_iso: str, end_iso: str) -> dict:
    """Per-machine window aggregate next to the intervals.

    Day/window SEC is total energy / total good production over the window
    (via compute_sec), never the mean of hourly SEC values. Only complete
    intervals contribute (incomplete ones are counted, never silently
    dropped). Aggregate deviation % is (sum actual - sum expected) /
    sum expected over complete intervals with non-null expected.
    """
    comp = [x for x in scored if x["complete"]]
    act_vals = [x["actual_kwh"] for x in comp if x["actual_kwh"] is not None]
    exp_vals = [x["expected_kwh"] for x in comp if x["expected_kwh"] is not None]
    tot_act = sum(act_vals) if act_vals else None
    tot_exp = sum(exp_vals) if exp_vals else None
    if tot_exp is not None and tot_act is not None and tot_exp > epsilon_kwh:
        agg_dev_pct = (tot_act - tot_exp) / tot_exp * 100.0
    else:
        agg_dev_pct = None
    prod_vals = [x["good_production_kg"] for x in comp
                 if x["good_production_kg"] is not None]
    tot_prod = sum(prod_vals) if prod_vals else None
    has_prod_record = bool(prod_vals)
    sec = compute_sec(tot_act, tot_prod, has_prod_record,
                      mtype, non_prod, bool(comp))
    nonprod = sum(x["non_productive_kwh"] or 0.0 for x in comp)
    return {
        "machine_id": mid,
        "window_start": start_iso,
        "window_end": end_iso,
        "n_intervals": len(scored),
        "n_complete": len(comp),
        "total_actual_kwh": tot_act,
        "total_expected_kwh": tot_exp,
        "aggregate_deviation_pct": agg_dev_pct,
        "total_good_production_kg": tot_prod,
        "window_sec_kwh_per_t": sec.sec_kwh_per_t,
        "window_sec_status": sec.status,
        "non_productive_kwh": nonprod,
    }


@router.post("/energy/anomalies/detect")
def detect(body: DetectRequest, db: Session = Depends(get_db)):
    s = get_settings()
    machines = _resolve_machines(db, body.machine_id)
    baselines = _latest_baselines(db)
    created, existing = 0, 0
    events_out = []
    for mid, m in machines.items():
        bl = baselines.get(mid)
        if bl is None:
            continue  # no baseline -> INSUFFICIENT_BASELINE_HISTORY, nothing to score
        scored = _score_intervals(db, mid, m["machine_type"], body.start, body.end, bl)
        flags = l1_flags(
            scored, s.DEVIATION_WARN_PCT, s.DEVIATION_CRIT_PCT, s.DEVIATION_CONSECUTIVE_N,
            s.IDLE_SHARE_THRESHOLD, float(m["rated_power_kw"] or 0),
            s.RATED_POWER_MULTIPLE, s.PF_MIN_THRESHOLD, s.IDLE_CONSECUTIVE_N,
        )
        flags += l2_flags(scored, s.MAD_THRESHOLD, s.MAD_WINDOW, s.DEVIATION_WARN_PCT)
        starts = [x["window_start"] for x in scored]
        ends = [x["window_end"] for x in scored]
        for ev in build_events(mid, scored, starts, ends, flags):
            r = db.execute(
                text(
                    "INSERT INTO anomaly_event (machine_id, window_start, window_end, metric, "
                    "rule_id, level, score, severity, expected_kwh, actual_kwh, deviation_kwh, "
                    "deviation_pct, evidence, status, source, dedup_key) VALUES (:m, :ws, :we, "
                    ":metric, :rule, :level, :score, :sev, :exp, :act, :dev, :devpct, :ev, "
                    "'OPEN', 'DERIVED', :dd) ON CONFLICT (dedup_key) DO NOTHING RETURNING id"
                ),
                {"m": ev["machine_id"], "ws": ev["window_start"], "we": ev["window_end"],
                 "metric": ev["metric"], "rule": ev["rule_id"], "level": ev["level"],
                 "score": ev["score"], "sev": ev["severity"], "exp": ev["expected_kwh"],
                 "act": ev["actual_kwh"], "dev": ev["deviation_kwh"],
                 "devpct": ev["deviation_pct"], "ev": ev["evidence"], "dd": ev["dedup_key"]},
            ).fetchone()
            if r is None:
                existing += 1
            else:
                created += 1
                ev["id"] = str(r[0])
                ev["window_start"] = ev["window_start"].isoformat()
                ev["window_end"] = ev["window_end"].isoformat()
                events_out.append(ev)
    db.commit()
    return {"created": created, "already_existing": existing, "events": events_out}


@router.get("/energy/anomalies")
def list_anomalies(machine_id: str | None = Query(default=None),
                   status: str | None = Query(default=None),
                   db: Session = Depends(get_db)):
    q = ("SELECT id, machine_id, window_start, window_end, metric, rule_id, level, score, "
         "severity, expected_kwh, actual_kwh, deviation_kwh, deviation_pct, evidence, "
         "status, source, created_at FROM anomaly_event")
    conds, params = [], {}
    if machine_id:
        conds.append("machine_id = :m")
        params["m"] = machine_id
    if status:
        conds.append("status = :st")
        params["st"] = status
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY window_start DESC"
    rows = db.execute(text(q), params).fetchall()
    cols = ["id", "machine_id", "window_start", "window_end", "metric", "rule_id", "level",
            "score", "severity", "expected_kwh", "actual_kwh", "deviation_kwh",
            "deviation_pct", "evidence", "status", "source", "created_at"]
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        d["id"] = str(d["id"])
        d["window_start"] = d["window_start"].isoformat()
        d["window_end"] = d["window_end"].isoformat()
        d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return {"anomalies": out}


@router.post("/energy/anomalies/{event_id}/acknowledge")
def acknowledge(event_id: str, db: Session = Depends(get_db)):
    r = db.execute(
        text("UPDATE anomaly_event SET status = 'ACKNOWLEDGED' WHERE id = CAST(:i AS uuid) "
             "RETURNING id"),
        {"i": event_id},
    ).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Unknown anomaly_event id: {event_id}")
    db.commit()
    return {"id": str(r[0]), "status": "ACKNOWLEDGED"}
