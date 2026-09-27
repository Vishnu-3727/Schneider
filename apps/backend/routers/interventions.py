"""Phase 5A: apply an approved recommendation, then verify it against a counterfactual.

POST /interventions                 APPROVED -> APPLIED (idempotent by key)
POST /interventions/{id}/verify     APPLIED -> MEASURED -> outcome (idempotent)
GET  /interventions, GET /verification

Every transition goes through services/verification/lifecycle.py and writes
an audit_event row. Nothing is executed on plant equipment: "applied" records
that a human made the change. Savings exist only as a VERIFIED outcome of
services/verification/verify.py; there is no other path to a saving.
"""

from __future__ import annotations

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.routers.energy import _load_production, _load_telemetry
from apps.backend.routers.optimization import _tariff_periods
from apps.backend.schemas import InterventionCreateRequest, InterventionVerifyRequest
from services.energy.aggregate import build_intervals
from services.verification import lifecycle
from services.verification.impact import EmissionFactor, impacts
from services.verification.verify import VerifyConfig, verify

router = APIRouter()

IV_COLS = ("id", "recommendation_id", "machine_id", "type", "parameters", "applied_at",
           "baseline_start", "baseline_end", "measurement_start", "measurement_end",
           "status", "idempotency_key", "created_at")
VR_COLS = ("id", "intervention_id", "method", "result_class", "outcome", "explanation",
           "counterfactual_kwh", "actual_kwh", "saving_kwh", "saving_pct", "uncertainty_kwh",
           "confidence", "production_before_kg_h", "production_after_kg_h", "comparable",
           "comparability_reasons", "n_baseline", "n_post", "baseline_complete_frac",
           "post_complete_frac", "model", "cost_impact", "co2_impact", "created_at")


def _json(cols, row) -> dict:
    d = dict(zip(cols, row, strict=True))
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif k in ("id", "recommendation_id", "intervention_id") and v is not None:
            d[k] = str(v)
    return d


def _verification_json(d: dict) -> dict:
    """Tag every number with its evidence class; savings only for VERIFIED."""
    d = dict(d)
    d["evidence_classes"] = {"counterfactual_kwh": "DERIVED (baseline model, PROJECTED "
                                                   "for the measurement period)",
                             "actual_kwh": "MEASURED (from SIMULATED telemetry in this prototype)",
                             "saving_kwh": "DERIVED (counterfactual - actual)"}
    d["verified_saving_kwh"] = d["saving_kwh"] if d["outcome"] == "VERIFIED" else None
    return d


def _audit(db: Session, action: str, entity: str, eid: str, detail: dict) -> None:
    db.execute(
        text("INSERT INTO audit_event (action, entity, entity_id, detail_json) "
             "VALUES (:a, :e, :i, CAST(:d AS jsonb))"),
        {"a": action, "e": entity, "i": eid, "d": json.dumps(detail, default=str)},
    )


def _transition(db: Session, rec_id: str, iv_id: str | None, cur: str, target: str,
                note: str = "") -> None:
    if not lifecycle.can(cur, target):
        raise HTTPException(status_code=409, detail=(
            f"Illegal transition {cur} -> {target}; allowed next: "
            f"{list(lifecycle.allowed(cur)) or 'none'}"))
    db.execute(text("UPDATE recommendation SET status = :t WHERE id = CAST(:i AS uuid)"),
               {"t": target, "i": rec_id})
    if iv_id is not None:
        db.execute(text("UPDATE intervention SET status = :t WHERE id = CAST(:i AS uuid)"),
                   {"t": target, "i": iv_id})
    _audit(db, "lifecycle.transition", "recommendation", rec_id,
           {"from": cur, "to": target, "intervention_id": iv_id, "note": note})


def _emission_factors(db: Session) -> list[EmissionFactor]:
    rows = db.execute(text(
        "SELECT id, geography, value_kg_per_kwh, unit, gas_basis, source_name, version, "
        "fiscal_year, effective_from, effective_to, source_class, note FROM emission_factor"
    )).fetchall()
    return [EmissionFactor(*r) for r in rows]


def _get_intervention(db: Session, iv_id: str) -> dict:
    try:
        row = db.execute(text("SELECT " + ", ".join(IV_COLS) + " FROM intervention "
                              "WHERE id = CAST(:i AS uuid)"), {"i": iv_id}).fetchone()
    except Exception:
        db.rollback()
        row = None
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown intervention id: {iv_id}")
    return dict(zip(IV_COLS, row, strict=True))


def _result_for(db: Session, iv_id) -> dict | None:
    row = db.execute(text("SELECT " + ", ".join(VR_COLS) + " FROM verification_result "
                          "WHERE intervention_id = CAST(:i AS uuid)"), {"i": str(iv_id)}).fetchone()
    return _verification_json(_json(VR_COLS, row)) if row else None


@router.post("/interventions")
def create_intervention(body: InterventionCreateRequest, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT " + ", ".join(IV_COLS) + " FROM intervention "
                               "WHERE idempotency_key = :k"), {"k": body.idempotency_key}).fetchone()
    if existing is not None:
        d = _json(IV_COLS, existing)
        if d["recommendation_id"] != body.recommendation_id:
            raise HTTPException(status_code=409, detail="idempotency_key already used for "
                                                        "a different recommendation")
        return {"intervention": d, "idempotent_replay": True}
    try:
        rec = db.execute(text("SELECT id, machine_id, status FROM recommendation "
                              "WHERE id = CAST(:i AS uuid)"), {"i": body.recommendation_id}).fetchone()
    except Exception:
        db.rollback()
        rec = None
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation id: {body.recommendation_id}")
    rec_id, mid, status = str(rec[0]), rec[1], rec[2]
    if not lifecycle.can(status, "APPLIED"):
        raise HTTPException(status_code=409, detail=(
            f"Recommendation is {status}; only an APPROVED recommendation can be applied "
            f"(allowed next: {list(lifecycle.allowed(status)) or 'none'})"))
    s = get_settings()
    b_end = body.baseline_end or body.applied_at
    b_start = body.baseline_start or (b_end - timedelta(days=s.VERIFY_BASELINE_DAYS))
    if not b_start < b_end <= body.applied_at:
        raise HTTPException(status_code=422, detail="baseline window must end at or before applied_at")
    row = db.execute(
        text("INSERT INTO intervention (recommendation_id, machine_id, type, parameters, "
             "applied_at, baseline_start, baseline_end, status, idempotency_key) "
             "VALUES (CAST(:r AS uuid), :m, :t, CAST(:p AS jsonb), :a, :bs, :be, 'APPROVED', :k) "
             "RETURNING id"),
        {"r": rec_id, "m": mid, "t": body.type.value, "p": json.dumps(body.parameters),
         "a": body.applied_at, "bs": b_start, "be": b_end, "k": body.idempotency_key},
    ).fetchone()
    iv_id = str(row[0])
    _transition(db, rec_id, iv_id, status, "APPLIED", f"intervention {body.type.value}")
    db.commit()
    return {"intervention": _json(IV_COLS, db.execute(
        text("SELECT " + ", ".join(IV_COLS) + " FROM intervention WHERE id = CAST(:i AS uuid)"),
        {"i": iv_id}).fetchone()), "idempotent_replay": False}


@router.post("/interventions/{iv_id}/verify")
def verify_intervention(iv_id: str, body: InterventionVerifyRequest, db: Session = Depends(get_db)):
    iv = _get_intervention(db, iv_id)
    prior = _result_for(db, iv["id"])
    if prior is not None:
        return {"verification": prior, "idempotent_replay": True}
    rec_id = str(iv["recommendation_id"])
    if iv["status"] != "APPLIED":
        raise HTTPException(status_code=409, detail=(
            f"Intervention is {iv['status']}; only an APPLIED intervention can be verified"))
    if body.start < iv["applied_at"]:
        raise HTTPException(status_code=422, detail="measurement window must start at or after applied_at")
    s = get_settings()
    mid = iv["machine_id"]

    def rows(start, end):
        ivs = build_intervals(mid, _load_telemetry(db, mid, start, end),
                              _load_production(db, mid, start, end), start, end,
                              s.ENERGY_INTERVAL_S, s.MIN_COVERAGE_PCT)
        return [{"complete": i.complete, "energy_kwh": i.energy_kwh,
                 "good_production_kg": i.good_production_kg, "window_start": i.window_start}
                for i in ivs]

    cfg = VerifyConfig(confidence=s.VERIFY_CONFIDENCE,
                       min_baseline_points=s.VERIFY_MIN_BASELINE_POINTS,
                       min_post_points=s.VERIFY_MIN_POST_POINTS,
                       min_complete_frac=s.VERIFY_MIN_COMPLETE_FRAC,
                       prod_tol_pct=s.VERIFY_PROD_TOL_PCT,
                       max_extrapolated_frac=s.VERIFY_MAX_EXTRAPOLATED_FRAC,
                       g14_cv_max_pct=s.G14_CV_MAX_PCT, g14_nmbe_max_pct=s.G14_NMBE_MAX_PCT)
    out = verify(rows(iv["baseline_start"], iv["baseline_end"]), rows(body.start, body.end), cfg)
    site = db.execute(text("SELECT site_id FROM machine WHERE id = :m"), {"m": mid}).scalar()
    periods, info = _tariff_periods(db, site, body.end)
    illustrative = bool(info) and all(i["source_class"] == "ASSUMPTION" for i in info)
    cost, co2 = impacts(out.status, out.saving_kwh, out.hourly, periods, illustrative,
                        _emission_factors(db), body.end.astimezone(ZoneInfo(s.TZ)).date(), s.TZ)
    db.execute(text("UPDATE intervention SET measurement_start = :s, measurement_end = :e "
                    "WHERE id = CAST(:i AS uuid)"), {"s": body.start, "e": body.end, "i": str(iv["id"])})
    _transition(db, rec_id, str(iv["id"]), "APPLIED", "MEASURED",
                f"measurement window {body.start.isoformat()} .. {body.end.isoformat()}")
    _transition(db, rec_id, str(iv["id"]), "MEASURED", out.status, out.result_class)
    db.execute(text("UPDATE recommendation SET verification_status = :v WHERE id = CAST(:i AS uuid)"),
               {"v": out.status, "i": rec_id})
    db.execute(
        text("INSERT INTO verification_result (intervention_id, method, result_class, outcome, "
             "explanation, counterfactual_kwh, actual_kwh, saving_kwh, saving_pct, uncertainty_kwh, "
             "confidence, production_before_kg_h, production_after_kg_h, comparable, "
             "comparability_reasons, n_baseline, n_post, baseline_complete_frac, "
             "post_complete_frac, model, cost_impact, co2_impact) VALUES (CAST(:iv AS uuid), :me, :rc, :oc, :ex, :cf, :ac, "
             ":sv, :sp, :u, :cl, :pb, :pa, :cm, CAST(:cr AS jsonb), :nb, :npo, :bf, :pf, "
             "CAST(:mo AS jsonb), CAST(:ci AS jsonb), CAST(:co AS jsonb))"),
        {"iv": str(iv["id"]), "me": out.method, "rc": out.result_class, "oc": out.status,
         "ex": out.explanation, "cf": out.counterfactual_kwh, "ac": out.actual_kwh,
         "sv": out.saving_kwh, "sp": out.saving_pct, "u": out.uncertainty_kwh,
         "cl": out.confidence, "pb": out.production_before_kg_h, "pa": out.production_after_kg_h,
         "cm": out.comparable, "cr": json.dumps(out.comparability_reasons), "nb": out.n_baseline,
         "npo": out.n_post, "bf": out.baseline_complete_frac, "pf": out.post_complete_frac,
         "mo": json.dumps(out.model), "ci": json.dumps(cost), "co": json.dumps(co2)},
    )
    db.commit()
    return {"verification": _result_for(db, iv["id"]), "idempotent_replay": False}


@router.get("/interventions")
def list_interventions(status: str | None = Query(default=None), db: Session = Depends(get_db)):
    q = "SELECT " + ", ".join(IV_COLS) + " FROM intervention"
    params = {}
    if status:
        q += " WHERE status = :st"
        params["st"] = status
    rows = db.execute(text(q + " ORDER BY created_at DESC"), params).fetchall()
    return {"interventions": [_json(IV_COLS, r) for r in rows]}


@router.get("/verification")
def list_verification(intervention_id: str | None = Query(default=None),
                      db: Session = Depends(get_db)):
    if intervention_id:
        r = _result_for(db, _get_intervention(db, intervention_id)["id"])
        return {"verification": [r] if r else []}
    rows = db.execute(text("SELECT " + ", ".join(VR_COLS) + " FROM verification_result "
                           "ORDER BY created_at DESC")).fetchall()
    return {"verification": [_verification_json(_json(VR_COLS, r)) for r in rows]}


@router.get("/emission-factors")
def list_emission_factors(db: Session = Depends(get_db)):
    """Emission factors with full provenance (value, unit, gas basis, source, version,
    fiscal year, effective period, source class)."""
    out = []
    for f in _emission_factors(db):
        d = dict(f.__dict__)
        d["effective_from"] = f.effective_from.isoformat()
        d["effective_to"] = f.effective_to.isoformat() if f.effective_to else None
        out.append(d)
    return {"emission_factors": sorted(out, key=lambda d: d["effective_from"])}