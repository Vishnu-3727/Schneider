"""POST /optimization/run + GET /optimization/schedule (Phase 4A).

Flow: load machine + latest ACCEPTABLE baseline (else BASELINE_UNAVAILABLE,
persisted) -> per-state median powers from the NORMAL train window
(DERIVED) -> tariff periods for the site (missing -> cost term omitted,
never invented) -> reconstruct the current schedule from telemetry ->
CP-SAT plan -> independent validate() (violations raise: bug) ->
evaluate() BOTH schedules with the same function -> persist
optimization_run (PROJECTED) and return it.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date as date_cls
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.schemas import OptimizationRunRequest
from services.optimization.constraints import (
    AuxTask,
    HeatTemplate,
    OptConstraints,
    Schedule,
    templates_from_heats,
)
from services.optimization.evaluate import (
    EnergyModel,
    StatePowers,
    TariffPeriod,
    evaluate,
    slots_to_heats,
    comparability,
)
from services.optimization.scheduler import plan

router = APIRouter()

FURNACE_FEATURES = ("good_production_kg", "hours_heating", "hours_holding", "hours_idle")
HEAT_STATES = ("heating", "melting", "holding", "idle")


def _slots(hours: float, slot_min: int, round_fn=round) -> int:
    return max(1, int(round_fn(hours * 60.0 / slot_min)))


def _resolve_horizon(body: OptimizationRunRequest, tz: ZoneInfo):
    s = get_settings()
    if body.date is not None and (body.start is not None or body.end is not None):
        raise HTTPException(status_code=422, detail="give either date or start/end, not both")
    horizon_h = body.constraints.horizon_h or s.OPT_HORIZON_H
    if body.date is not None:
        try:
            d = date_cls.fromisoformat(body.date)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
        start = datetime(d.year, d.month, d.day, tzinfo=tz)
        return start, start + timedelta(hours=horizon_h)
    if body.start is None or body.end is None:
        raise HTTPException(status_code=422, detail="give either date or start+end")
    for v in (body.start, body.end):
        if v.tzinfo is None:
            raise HTTPException(status_code=422, detail="start/end must be timezone-aware")
    if body.end <= body.start:
        raise HTTPException(status_code=422, detail="end must be after start")
    # Site-local horizon: tariff mapping and heat timing are local-time.
    return body.start.astimezone(tz), body.end.astimezone(tz)


def _latest_acceptable_baseline(db: Session, mid: str) -> dict | None:
    r = db.execute(
        text(
            "SELECT id, features, coefficients, intercept, train_start, train_end, "
            "acceptance FROM energy_baseline WHERE machine_id = :m "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"m": mid},
    ).fetchone()
    if r is None:
        return None
    bl = {"id": str(r[0]), "features": r[1], "coefficients": r[2],
          "intercept": float(r[3]), "train_start": r[4], "train_end": r[5],
          "acceptance": r[6]}
    if bl["acceptance"] != "ACCEPTABLE":
        return None
    if tuple(bl["features"]) != FURNACE_FEATURES:
        return None
    return bl


def _state_median_powers(db: Session, mid: str, start: datetime, end: datetime):
    rows = db.execute(
        text(
            "SELECT machine_state, power_kw FROM telemetry WHERE machine_id = :m "
            "AND ts >= :start AND ts < :end AND quality = 'GOOD' "
            "AND power_kw IS NOT NULL AND machine_state IS NOT NULL"
        ),
        {"m": mid, "start": start, "end": end},
    ).fetchall()
    by_state: dict[str, list[float]] = {}
    for st, pw in rows:
        by_state.setdefault(st, []).append(float(pw))
    medians = {st: median(v) for st, v in by_state.items() if v}
    if any(st not in medians for st in HEAT_STATES):
        return None
    return medians


def _tariff_periods(db: Session, site_id: str, horizon_end: datetime):
    rows = db.execute(
        text(
            "SELECT period_name, start_local, end_local, energy_inr_per_kwh, "
            "demand_inr_per_kw, valid_from, source_class FROM tariff "
            "WHERE site_id = :s AND valid_from <= CAST(:h AS date) "
            "ORDER BY valid_from DESC, start_local"
        ),
        {"s": site_id, "h": horizon_end},
    ).fetchall()
    if not rows:
        return None, []
    latest = rows[0][5]
    periods = []
    for r in rows:
        if r[5] != latest:
            break
        periods.append(TariffPeriod(
            name=r[0],
            start_h=r[1].hour + r[1].minute / 60.0,
            end_h=r[2].hour + r[2].minute / 60.0,
            energy_inr_per_kwh=float(r[3]),
            demand_inr_per_kw=float(r[4]) if r[4] is not None else None))
    info = [{"period": r[0], "rate": float(r[3]), "source_class": r[6],
             "start_h": r[1].hour + r[1].minute / 60.0,
             "end_h": r[2].hour + r[2].minute / 60.0} for r in rows
            if r[5] == latest]
    return periods, info


def _dominant_slot_states(db: Session, mid: str, start: datetime,
                          n_slots: int, slot_min: int) -> list[str]:
    rows = db.execute(
        text(
            "SELECT ts, machine_state FROM telemetry WHERE machine_id = :m "
            "AND ts >= :start AND ts < :end AND quality = 'GOOD' "
            "AND machine_state IS NOT NULL ORDER BY ts"
        ),
        {"m": mid, "start": start,
         "end": start + timedelta(minutes=n_slots * slot_min)},
    ).fetchall()
    buckets: list[dict[str, int]] = [{} for _ in range(n_slots)]
    for ts, st in rows:
        k = int((ts - start).total_seconds() // 60 // slot_min)
        if 0 <= k < n_slots:
            buckets[k][st] = buckets[k].get(st, 0) + 1
    return [max(b, key=b.get) if b else "idle" for b in buckets]


def _inputs_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _persist(db: Session, machine_id: str, start: datetime, end: datetime,
             inputs_hash: str, constraints_d: dict, status: str,
             current: Schedule | None, recommended: Schedule | None,
             metrics: dict, explanation: str,
             comparable: bool | None = None, comparability_reason: str | None = None) -> dict:
    r = db.execute(
        text(
            "INSERT INTO optimization_run (machine_id, horizon_start, horizon_end, "
            "inputs_hash, constraints, status, current_schedule, recommended_schedule, "
            "metrics, explanation, source, comparable, comparability_reason) VALUES (:m, :hs, :he, :hh, "
            "CAST(:c AS jsonb), :st, CAST(:cur AS jsonb), CAST(:rec AS jsonb), "
            "CAST(:met AS jsonb), :ex, 'PROJECTED', :cmp, :cmr) RETURNING id, created_at"
        ),
        {"m": machine_id, "hs": start, "he": end, "hh": inputs_hash,
         "c": json.dumps(constraints_d),
         "st": status,
         "cur": json.dumps(current.to_dict() if current else None),
         "rec": json.dumps(recommended.to_dict() if recommended else None),
         "met": json.dumps(metrics), "ex": explanation,
         "cmp": comparable, "cmr": comparability_reason},
    ).fetchone()
    db.commit()
    return {"id": str(r[0]), "created_at": r[1].isoformat()}


def _run_to_json(row) -> dict:
    cols = ["id", "machine_id", "horizon_start", "horizon_end", "inputs_hash",
            "constraints", "status", "current_schedule", "recommended_schedule",
            "metrics", "explanation", "source", "created_at", "comparable", "comparability_reason"]
    d = dict(zip(cols, row, strict=True))
    d["id"] = str(d["id"])
    d["horizon_start"] = d["horizon_start"].isoformat()
    d["horizon_end"] = d["horizon_end"].isoformat()
    d["created_at"] = d["created_at"].isoformat()
    return d


@router.post("/optimization/run")
def run_optimization(body: OptimizationRunRequest, db: Session = Depends(get_db)):
    s = get_settings()
    tz = ZoneInfo(s.TZ)
    mrow = db.execute(
        text("SELECT id, site_id, machine_type, rated_power_kw FROM machine WHERE id = :m"),
        {"m": body.machine_id},
    ).fetchone()
    if mrow is None:
        raise HTTPException(status_code=404, detail=f"Unknown machine_id: {body.machine_id}")
    site_id = mrow[1]
    start, end = _resolve_horizon(body, tz)
    horizon_h = (end - start).total_seconds() / 3600.0
    slot_min = body.constraints.slot_min or s.OPT_SLOT_MIN
    n_slots = max(1, int(round(horizon_h * 60.0 / slot_min)))

    bl = _latest_acceptable_baseline(db, body.machine_id)
    template = HeatTemplate(
        charge_kg=s.OPT_HEAT_CHARGE_KG,
        heating_slots=_slots(s.OPT_HEATING_H, slot_min),
        melting_slots=_slots(s.OPT_HEAT_CHARGE_KG / s.OPT_MELT_RATE_KG_H, slot_min),
        min_hold_slots=_slots(s.OPT_HOLD_MIN_H, slot_min,
                              lambda x: math.ceil(x - 1e-9)),
        max_hold_slots=_slots(s.OPT_HOLD_MAX_H, slot_min,
                              lambda x: math.floor(x + 1e-9)),
    )
    constraints_d = {"machine_id": body.machine_id,
                     "horizon_start": start.isoformat(), "horizon_end": end.isoformat(),
                     "overrides": body.constraints.model_dump()}
    if bl is None:
        meta = _persist(db, body.machine_id, start, end,
                        _inputs_hash(constraints_d), constraints_d,
                        "BASELINE_UNAVAILABLE", None, None, {},
                        "NO PLAN: no ACCEPTABLE furnace energy baseline for this "
                        "machine (fit one on NORMAL history first); never falling "
                        "back to made-up coefficients")
        return {"status": "BASELINE_UNAVAILABLE", **meta,
                "explanation": "NO PLAN: no ACCEPTABLE furnace energy baseline",
                "current": None, "recommended": None, "metrics": {}}
    coefs = bl["coefficients"]
    em = EnergyModel(
        b_prod_kwh_per_kg=float(coefs["good_production_kg"]),
        b_heating_kwh_per_h=float(coefs["hours_heating"]),
        b_holding_kwh_per_h=float(coefs["hours_holding"]),
        b_idle_kwh_per_h=float(coefs["hours_idle"]),
        intercept_kwh=bl["intercept"],
        interval_h=s.ENERGY_INTERVAL_S / 3600.0,
        baseline_id=bl["id"])
    medians = _state_median_powers(db, body.machine_id, bl["train_start"], bl["train_end"])
    if medians is None:
        meta = _persist(db, body.machine_id, start, end,
                        _inputs_hash(constraints_d), constraints_d,
                        "BASELINE_UNAVAILABLE", None, None, {},
                        "NO PLAN: per-state power medians unavailable from NORMAL "
                        "telemetry (need heating/melting/holding/idle samples)")
        return {"status": "BASELINE_UNAVAILABLE", **meta,
                "explanation": "NO PLAN: per-state power medians unavailable",
                "current": None, "recommended": None, "metrics": {}}
    sp = StatePowers({k: medians[k] for k in HEAT_STATES})
    tariff, tariff_info = _tariff_periods(db, site_id, end)

    # Fair comparison: the optimizer moves heats in time but must NOT change
    # a heat's intrinsic phase durations. The current schedule keeps each
    # heat's OBSERVED heating/melting/holding counts, the shared reheat rule
    # splits base heating + reheat, and the recommended schedule re-uses
    # those same per-heat durations (holding fixed: the model has no
    # schedule-induced-waiting representation inside holding).
    cold_threshold_slots = max(1, int(round(s.OPT_COLD_THRESHOLD_H * 60.0 / slot_min)))
    reheat_extra_slots = _slots(s.OPT_REHEAT_EXTRA_H, slot_min)
    slot_states = _dominant_slot_states(db, body.machine_id, start, n_slots, slot_min)
    cur_heats = slots_to_heats(
        slot_states, template.charge_kg,
        template.melting_slots, template.min_hold_slots,
        cold_threshold_slots=cold_threshold_slots,
        reheat_extra_slots=reheat_extra_slots)
    current = Schedule(heats=cur_heats, aux=[], n_slots=n_slots, slot_min=slot_min,
                       horizon_start_iso=start.isoformat())
    cur_metrics = evaluate(current, em, sp, tariff, start)

    # Required production: explicit override, else the day's own heat count
    # (re-optimise the same heats; deriving n_heats from rounded kg could
    # silently add/drop a heat vs what was reconstructed).
    prow = db.execute(
        text(
            "SELECT COALESCE(SUM(qty_good_kg), 0) FROM production_record "
            "WHERE machine_id = :m AND window_start >= :st AND window_start < :en "
            "AND quality = 'GOOD'"
        ),
        {"m": body.machine_id, "st": start, "en": end},
    ).fetchone()
    produced_kg = float(prow[0] or 0.0)
    explicit_override = (body.constraints.required_kg is not None
                         or body.constraints.required_heats is not None)
    req_kg = body.constraints.required_kg
    if req_kg is None and body.constraints.required_heats is not None:
        req_kg = body.constraints.required_heats * template.charge_kg
    if req_kg is None and explicit_override:
        req_kg = produced_kg
    if req_kg is None:
        n_heats = len(cur_heats)
        req_kg = n_heats * template.charge_kg
    else:
        n_heats = max(0, math.ceil(req_kg / template.charge_kg - 1e-9))
    # Same intrinsic durations on both sides whenever the heat count matches
    # the reconstructed day (the normal re-optimise case); nominal template
    # otherwise (e.g. an explicit required_heats override plans new heats).
    heat_templates = (templates_from_heats(cur_heats)
                      if (n_heats == len(cur_heats) and n_heats > 0) else None)

    def _to_slots(windows, default):
        if windows is None:
            return default
        out = []
        for ws_h, we_h in windows:
            ws = max(0, min(n_slots, int(round(ws_h * 60.0 / slot_min))))
            we = max(0, min(n_slots, int(round(we_h * 60.0 / slot_min))))
            if we > ws:
                out.append((ws, we))
        return out or default

    aux_tasks = []
    for a in body.constraints.aux_tasks:
        dur = max(1, int(round(a.duration_h * 60.0 / slot_min)))
        ws = max(0, min(n_slots, int(round(a.window_start_h * 60.0 / slot_min))))
        we = max(0, min(n_slots, int(round(a.window_end_h * 60.0 / slot_min))))
        aux_tasks.append(AuxTask(name=a.name, duration_slots=dur,
                                 window_start_slot=ws, window_end_slot=we,
                                 power_kw=a.power_kw))
    c = OptConstraints(
        n_slots=n_slots, slot_min=slot_min, horizon_start_iso=start.isoformat(),
        n_heats=n_heats, heat=template,
        heat_templates=heat_templates,
        operating_windows=_to_slots(body.constraints.operating_windows_h,
                                    [(0, n_slots)]),
        maintenance_windows=_to_slots(body.constraints.maintenance_windows_h, []),
        peak_cap_kw=body.constraints.peak_cap_kw,
        cold_threshold_slots=cold_threshold_slots,
        reheat_extra_slots=reheat_extra_slots,
        aux_tasks=aux_tasks,
        w_energy=(body.constraints.w_energy
                  if body.constraints.w_energy is not None else s.OPT_W_ENERGY_KWH),
        w_peak=(body.constraints.w_peak
                if body.constraints.w_peak is not None else s.OPT_W_PEAK_KW),
        w_cost=(body.constraints.w_cost
                if body.constraints.w_cost is not None else s.OPT_W_COST_INR),
        time_limit_s=(body.constraints.time_limit_s
                      if body.constraints.time_limit_s is not None
                      else s.OPT_TIME_LIMIT_S),
        deterministic_time=(body.constraints.deterministic_time_s
                            if body.constraints.deterministic_time_s is not None
                            else s.OPT_DETERMINISTIC_TIME),
        wall_slack_s=s.OPT_WALL_SLACK_S,
        random_seed=(body.constraints.random_seed
                     if body.constraints.random_seed is not None
                     else s.OPT_RANDOM_SEED),
        num_workers=s.OPT_NUM_WORKERS)
    constraints_d["constraints"] = c.to_dict()
    constraints_d["baseline_id"] = bl["id"]
    constraints_d["tariff"] = tariff_info
    constraints_d["required_kg"] = req_kg
    ihash = _inputs_hash(constraints_d)

    result = plan(c, em, sp, tariff, start)
    if result.status in ("OPTIMAL", "FEASIBLE") and result.schedule is not None:
        rec_metrics = result.metrics
        metrics = {"current": cur_metrics.to_dict(),
                   "recommended": rec_metrics.to_dict(),
                   "tariff_periods": tariff_info,
                   "cost_status": rec_metrics.cost_status}
        # Compute comparability
        comp, comp_reason = comparability(cur_metrics, rec_metrics, current, result.schedule)
        meta = _persist(db, body.machine_id, start, end, ihash, constraints_d,
                        result.status, current, result.schedule, metrics,
                        result.explanation, comp, comp_reason)
        return {"status": result.status, **meta, "explanation": result.explanation,
                "constraints": constraints_d,
                "current": current.to_dict(), "recommended": result.schedule.to_dict(),
                "metrics": metrics, "comparable": comp, "comparability_reason": comp_reason}
    metrics = {"current": cur_metrics.to_dict(), "recommended": None,
               "tariff_periods": tariff_info}
    meta = _persist(db, body.machine_id, start, end, ihash, constraints_d,
                    result.status, current, None, metrics, result.explanation,
                    None, None)
    return {"status": result.status, **meta, "explanation": result.explanation,
            "constraints": constraints_d,
            "current": current.to_dict(), "recommended": None, "metrics": metrics,
            "comparable": None, "comparability_reason": None}


@router.get("/optimization/schedule")
def get_schedule(id: str | None = Query(default=None),
                 machine_id: str | None = Query(default=None),
                 db: Session = Depends(get_db)):
    if id is not None:
        row = db.execute(
            text(
                "SELECT id, machine_id, horizon_start, horizon_end, inputs_hash, "
                "constraints, status, current_schedule, recommended_schedule, "
                "metrics, explanation, source, created_at, comparable, comparability_reason "
                "FROM optimization_run WHERE id = CAST(:i AS uuid)"
            ),
            {"i": id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown optimization_run id: {id}")
        return _run_to_json(row)
    if machine_id is None:
        raise HTTPException(status_code=422, detail="give id or machine_id")
    row = db.execute(
        text(
            "SELECT id, machine_id, horizon_start, horizon_end, inputs_hash, "
            "constraints, status, current_schedule, recommended_schedule, "
            "metrics, explanation, source, created_at, comparable, comparability_reason "
            "FROM optimization_run WHERE machine_id = :m ORDER BY created_at DESC LIMIT 1"
        ),
        {"m": machine_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No optimization run for {machine_id}")
    return _run_to_json(row)
