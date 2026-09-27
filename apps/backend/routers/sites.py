"""GET /sites, /machines, /machines/{id}."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.db import get_db

router = APIRouter()


@router.get("/sites")
def list_sites(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, name, location, timezone, industry_type FROM site ORDER BY id")
    ).fetchall()
    return [
        {"id": r[0], "name": r[1], "location": r[2], "timezone": r[3], "industry_type": r[4]}
        for r in rows
    ]


@router.get("/machines")
def list_machines(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, site_id, name, machine_type, rated_power_kw FROM machine ORDER BY id")
    ).fetchall()
    return [
        {"id": r[0], "site_id": r[1], "name": r[2], "machine_type": r[3], "rated_power_kw": r[4]}
        for r in rows
    ]


@router.get("/machines/{machine_id}")
def get_machine(machine_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, site_id, name, machine_type, rated_power_kw FROM machine WHERE id = :m"),
        {"m": machine_id},
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Unknown machine_id: {machine_id}")
    r = rows[0]
    return {"id": r[0], "site_id": r[1], "name": r[2], "machine_type": r[3], "rated_power_kw": r[4]}
