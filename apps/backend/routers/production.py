"""POST /production (batch) + GET /production."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.db import get_db
from apps.backend.routers._helpers import audit, fetch_machines
from apps.backend.schemas import IngestResult, ProductionBatch
from services.ingestion.validate import validate_production

router = APIRouter()


@router.post("/production", response_model=IngestResult)
def post_production(
    batch: ProductionBatch,
    db: Session = Depends(get_db),
    backfill: bool = Query(default=False),
):
    records = batch.records
    if not records:
        return IngestResult(accepted=0, suspect=0, bad=0, duplicate=0)

    ids = sorted({r.machine_id for r in records})
    machines = fetch_machines(db, ids)
    unknown = [m for m in ids if m not in machines]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown machine_id(s): {', '.join(unknown)}")

    accepted = bad = 0
    for r in records:
        verdict = validate_production(
            qty_total_kg=r.qty_total_kg,
            qty_good_kg=r.qty_good_kg,
            qty_rejected_kg=r.qty_rejected_kg,
        )
        db.execute(
            text(
                "INSERT INTO production_record (machine_id, window_start, window_end, "
                "qty_total_kg, qty_good_kg, qty_rejected_kg, batch_id, operating_time_h, "
                "source, quality, quality_reasons) VALUES (:m, :ws, :we, :tot, :good, "
                ":rej, :b, :op, :src, :qual, CAST(:reasons AS jsonb))"
            ),
            {
                "m": r.machine_id,
                "ws": r.window_start,
                "we": r.window_end,
                "tot": r.qty_total_kg,
                "good": r.qty_good_kg,
                "rej": r.qty_rejected_kg,
                "b": r.batch_id,
                "op": r.operating_time_h,
                "src": r.source.value,
                "qual": verdict.quality,
                "reasons": json.dumps(verdict.reasons),
            },
        )
        if verdict.quality == "GOOD":
            accepted += 1
        else:
            bad += 1

    audit(db, "ingest", "production", "batch", {"accepted": accepted, "bad": bad})
    if backfill:
        # Production validation has no stale check, so backfill changes no verdicts;
        # the flag exists for symmetry and the backfill is recorded for audit.
        starts = sorted(r.window_start for r in records)
        ends = sorted(r.window_end for r in records)
        audit(db, "backfill", "production", "batch",
              {"machine_ids": ids,
               "row_count": len(records),
               "start": starts[0].isoformat(),
               "end": ends[-1].isoformat()})
    db.commit()
    return IngestResult(accepted=accepted, suspect=0, bad=bad, duplicate=0)


@router.get("/production")
def get_production(
    machine_id: str | None = Query(default=None),
    limit: int = Query(default=1000, le=10000),
    db: Session = Depends(get_db),
):
    q = ("SELECT machine_id, window_start, window_end, qty_total_kg, qty_good_kg, "
         "qty_rejected_kg, batch_id, operating_time_h, source, quality, quality_reasons "
         "FROM production_record")
    params: dict = {}
    if machine_id:
        q += " WHERE machine_id = :m"
        params["m"] = machine_id
    q += " ORDER BY window_start DESC LIMIT :lim"
    params["lim"] = limit
    rows = db.execute(text(q), params).fetchall()
    cols = ["machine_id", "window_start", "window_end", "qty_total_kg", "qty_good_kg",
            "qty_rejected_kg", "batch_id", "operating_time_h", "source", "quality",
            "quality_reasons"]
    return [dict(zip(cols, r, strict=True)) for r in rows]
