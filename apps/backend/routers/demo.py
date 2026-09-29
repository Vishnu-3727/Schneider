"""Demo-only fault injection. Mounted only when DEMO_MODE is true.

POST /demo/inject rewrites the last few hours of one machine's SIMULATED
data with a simulator scenario (or NORMAL to restore), then reruns anomaly
detection, health scoring and recommendations for that window, so the
console reacts exactly as it would to a real fault. Rows with any other
source are never touched. Monitoring only: nothing here reaches a machine.
"""

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.routers._helpers import fetch_machines
from apps.backend.routers.energy import detect
from apps.backend.routers.machine_health import score
from apps.backend.routers.production import post_production
from apps.backend.routers.recommendations import generate_recommendations
from apps.backend.routers.telemetry import post_telemetry
from apps.backend.schemas import (
    DetectRequest,
    HealthScoreRequest,
    ProductionBatch,
    RecommendationGenerateRequest,
    TelemetryBatch,
)
from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory

router = APIRouter()

# fault -> (machines, simulator scenario)
FAULTS = {
    "air_leak": (["compressor-01"], "IDLE_WASTE"),          # loaded with no demand
    "furnace_holding": (["furnace-01"], "IDLE_WASTE"),      # kept hot, no pour
    "furnace_wear": (["furnace-01"], "EQUIPMENT_DEGRADATION"),
    "restore": (["furnace-01", "compressor-01", "pump-01"], "NORMAL"),
}


class InjectRequest(BaseModel):
    fault: Literal["air_leak", "furnace_holding", "furnace_wear", "restore"]
    hours: int = Field(default=4, ge=2, le=12, description="Window to rewrite, ending now")


def _clear_window(db: Session, mid: str, start: datetime) -> float:
    """Delete SIMULATED rows after `start`; return the meter counter at `start`."""
    row = db.execute(text("SELECT energy_kwh FROM telemetry WHERE machine_id = :m AND ts <= :s "
                          "ORDER BY ts DESC LIMIT 1"), {"m": mid, "s": start}).fetchone()
    params = {"m": mid, "s": start}
    db.execute(text("DELETE FROM telemetry WHERE machine_id = :m AND ts > :s AND source = 'SIMULATED'"), params)
    db.execute(text("DELETE FROM production_record WHERE machine_id = :m AND window_start >= :s "
                    "AND source = 'SIMULATED'"), params)
    db.execute(text("DELETE FROM machine_state WHERE machine_id = :m AND ts_start > :s"), params)
    # Reopen the state row that spans the window start; new readings close it.
    db.execute(text("UPDATE machine_state SET ts_end = NULL WHERE id = (SELECT id FROM machine_state "
                    "WHERE machine_id = :m ORDER BY ts_start DESC LIMIT 1)"), params)
    db.execute(text("DELETE FROM anomaly_event WHERE machine_id = :m AND window_end > :s"), params)
    db.execute(text("DELETE FROM machine_health WHERE machine_id = :m AND window_end > :s"), params)
    db.commit()
    return float(row[0]) if row and row[0] is not None else 0.0


@router.post("/demo/inject")
def inject(body: InjectRequest, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Not found")
    mids, scenario = FAULTS[body.fault]
    end = datetime.now(ZoneInfo(s.TZ)).replace(second=0, microsecond=0)
    start = end - timedelta(hours=body.hours)
    machines = fetch_machines(db, mids)
    posted = {}
    for mid in mids:
        m = machines.get(mid)
        if m is None:
            raise HTTPException(status_code=404, detail=f"Unknown machine {mid}")
        offset = _clear_window(db, mid, start)
        fac = SimulatedFactory([MachineSpec(mid, m["machine_type"], m["rated_power_kw"])],
                               scenario=scenario, hours=body.hours, step_s=300,
                               seed=int(end.timestamp()) % 100000, end=end, tz=s.TZ,
                               scenario_start_h=0.0, scenario_duration_h=float(body.hours))
        tel, prod = fac.run()
        for t in tel:
            t["energy_kwh"] = round(t["energy_kwh"] + offset, 5)
        rt = post_telemetry(TelemetryBatch(records=tel), db, backfill=True)
        rp = post_production(ProductionBatch(records=prod), db, backfill=True)
        posted[mid] = {"telemetry": rt.accepted, "production": rp.accepted}
    win = {"start": start, "end": end}
    det = detect(DetectRequest(**win), db)
    score(HealthScoreRequest(**win), db)
    recs = generate_recommendations(RecommendationGenerateRequest(**win), db)
    events = [e for e in det.get("events", []) if e.get("machine_id") in mids]
    return {"fault": body.fault, "scenario": scenario, "window_start": start.isoformat(),
            "window_end": end.isoformat(), "posted": posted,
            "events": [{"machine_id": e.get("machine_id"), "rule_id": e.get("rule_id"),
                        "deviation_pct": e.get("deviation_pct")} for e in events],
            "recommendations_created": recs.get("created") if isinstance(recs, dict) else None,
            "source": "SIMULATED"}
