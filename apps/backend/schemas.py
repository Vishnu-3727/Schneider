"""Phase 1 Pydantic schemas — units in field names, tz-aware ts, source tags."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Source(str, Enum):
    MEASURED = "MEASURED"
    SIMULATED = "SIMULATED"
    DERIVED = "DERIVED"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
    PROJECTED = "PROJECTED"
    ASSUMPTION = "ASSUMPTION"


class MachineStateEnum(str, Enum):
    HEATING = "heating"
    MELTING = "melting"
    HOLDING = "holding"
    IDLE = "idle"
    SHUTDOWN = "shutdown"
    AUXILIARY = "auxiliary"
    RUNNING = "running"
    STOPPED = "stopped"


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("ts must be timezone-aware (e.g. 2026-01-01T00:00:00+05:30)")
    return v


class TelemetryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    ts: datetime = Field(description="Timezone-aware timestamp")
    voltage_v: float | None = None
    current_a: float | None = None
    power_kw: float | None = None
    reactive_power_kvar: float | None = None
    power_factor: float | None = None
    energy_kwh: float | None = Field(default=None, description="Cumulative counter, kWh")
    vibration_mm_s: float | None = None
    temperature_c: float | None = None
    rpm: float | None = None
    runtime_h: float | None = None
    machine_state: MachineStateEnum | None = None
    source: Source

    _tz = field_validator("ts")(_require_tz_aware)


class TelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[TelemetryRecord]


class ProductionRecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    window_start: datetime
    window_end: datetime
    qty_total_kg: float
    qty_good_kg: float
    qty_rejected_kg: float
    batch_id: str = ""
    operating_time_h: float = 0.0
    source: Source

    _tz_start = field_validator("window_start")(_require_tz_aware)
    _tz_end = field_validator("window_end")(_require_tz_aware)


class ProductionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[ProductionRecordIn]


class IngestResult(BaseModel):
    accepted: int
    suspect: int
    bad: int
    duplicate: int


def _require_end_after_start(v: datetime, info) -> datetime:
    start = (info.data or {}).get("start")
    if start is not None and v <= start:
        raise ValueError("end must be after start")
    return v


class BaselineFitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str | None = Field(default=None, description="Fit one machine; omit for all")
    start: datetime = Field(description="Timezone-aware reference-window start (NORMAL history)")
    end: datetime = Field(description="Timezone-aware reference-window end")

    _tz_start = field_validator("start")(_require_tz_aware)
    _tz_end = field_validator("end")(_require_tz_aware)
    _order = field_validator("end")(_require_end_after_start)


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime = Field(description="Timezone-aware scoring-window start")
    end: datetime = Field(description="Timezone-aware scoring-window end")
    machine_id: str | None = Field(default=None, description="Score one machine; omit for all")

    _tz_start = field_validator("start")(_require_tz_aware)
    _tz_end = field_validator("end")(_require_tz_aware)
    _order = field_validator("end")(_require_end_after_start)


class HealthFitRequest(BaseModel):
    """Fit a machine-health reference on NORMAL history (per machine)."""

    model_config = ConfigDict(extra="forbid")

    machine_id: str | None = Field(default=None, description="Fit one machine; omit for all")
    model_id: str | None = Field(default=None, description="Health model id; omit for default")
    start: datetime = Field(description="Timezone-aware reference-window start (NORMAL history)")
    end: datetime = Field(description="Timezone-aware reference-window end")

    _tz_start = field_validator("start")(_require_tz_aware)
    _tz_end = field_validator("end")(_require_tz_aware)
    _order = field_validator("end")(_require_end_after_start)


class HealthScoreRequest(BaseModel):
    """Score (and persist, idempotently) machine-health intervals."""

    model_config = ConfigDict(extra="forbid")

    start: datetime = Field(description="Timezone-aware scoring-window start")
    end: datetime = Field(description="Timezone-aware scoring-window end")
    machine_id: str | None = Field(default=None, description="Score one machine; omit for all")
    model_id: str | None = Field(default=None, description="Health model id; omit for default")

    _tz_start = field_validator("start")(_require_tz_aware)
    _tz_end = field_validator("end")(_require_tz_aware)
    _order = field_validator("end")(_require_end_after_start)


class AuxTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    duration_h: float = Field(description="Fixed task duration, hours")
    window_start_h: float = Field(description="Earliest start, hours since horizon start")
    window_end_h: float = Field(description="Latest end, hours since horizon start")
    power_kw: float


class OptimizationConstraintsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_kg: float | None = Field(default=None, description="Required good production, kg")
    required_heats: int | None = Field(default=None, description="Required heat count")
    peak_cap_kw: float | None = None
    operating_windows_h: list[list[float]] | None = Field(
        default=None, description="Allowed [[start_h, end_h]] hours since horizon start")
    maintenance_windows_h: list[list[float]] | None = Field(
        default=None, description="Unavailable [[start_h, end_h]] hours since horizon start")
    aux_tasks: list[AuxTaskIn] = Field(default_factory=list)
    slot_min: int | None = None
    horizon_h: float | None = None
    w_energy: float | None = None
    w_peak: float | None = None
    w_cost: float | None = None
    time_limit_s: float | None = None
    deterministic_time_s: float | None = Field(
        default=None, description="Deterministic CP-SAT budget (primary); wall time_limit_s stays the safety net")
    random_seed: int | None = None


class OptimizationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    date: str | None = Field(default=None, description="Horizon date YYYY-MM-DD (site tz)")
    start: datetime | None = Field(default=None, description="Timezone-aware horizon start")
    end: datetime | None = Field(default=None, description="Timezone-aware horizon end")
    constraints: OptimizationConstraintsIn = Field(default_factory=OptimizationConstraintsIn)


class RecommendationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime = Field(description="Timezone-aware window start")
    end: datetime = Field(description="Timezone-aware window end")

    _tz_start = field_validator("start")(_require_tz_aware)
    _tz_end = field_validator("end")(_require_tz_aware)
    _order = field_validator("end")(_require_end_after_start)


class RecommendationAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="ACCEPTED or REJECTED")
    note: str = Field(default="", description="Reviewer note")

    @field_validator("decision")
    @classmethod
    def _decision(cls, v: str) -> str:
        if v not in ("ACCEPTED", "REJECTED"):
            raise ValueError("decision must be ACCEPTED or REJECTED")
        return v
