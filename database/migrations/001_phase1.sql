-- JouleMitra Phase 1 schema (001_phase1.sql)
-- Plain Postgres 16. Timescale-compatible: timestamptz everywhere,
-- (machine_id, ts) indexes. No TimescaleDB extension (owner decision).
-- Phase-1 tables only: Site, Machine, Sensor, Telemetry, ProductionRecord,
-- MachineState, User, AuditEvent.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS site (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    industry_type TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS machine (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(id),
    name TEXT NOT NULL,
    machine_type TEXT NOT NULL,
    rated_power_kw DOUBLE PRECISION NOT NULL,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sensor (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL REFERENCES machine(id),
    channel TEXT NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    last_seen_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS telemetry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    ts TIMESTAMPTZ NOT NULL,
    voltage_v DOUBLE PRECISION NULL,
    current_a DOUBLE PRECISION NULL,
    power_kw DOUBLE PRECISION NULL,
    reactive_power_kvar DOUBLE PRECISION NULL,
    power_factor DOUBLE PRECISION NULL,
    energy_kwh DOUBLE PRECISION NULL,
    vibration_mm_s DOUBLE PRECISION NULL,
    temperature_c DOUBLE PRECISION NULL,
    rpm DOUBLE PRECISION NULL,
    runtime_h DOUBLE PRECISION NULL,
    machine_state TEXT NULL,
    source TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'GOOD',
    quality_reasons JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (machine_id, ts)
);
CREATE INDEX IF NOT EXISTS ix_telemetry_machine_ts ON telemetry (machine_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_telemetry_ts ON telemetry (ts DESC);

CREATE TABLE IF NOT EXISTS production_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    qty_total_kg DOUBLE PRECISION NOT NULL,
    qty_good_kg DOUBLE PRECISION NOT NULL,
    qty_rejected_kg DOUBLE PRECISION NOT NULL,
    batch_id TEXT NOT NULL DEFAULT '',
    operating_time_h DOUBLE PRECISION NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'GOOD',
    quality_reasons JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_production_machine_window ON production_record (machine_id, window_start, window_end);

CREATE TABLE IF NOT EXISTS machine_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    state TEXT NOT NULL,
    ts_start TIMESTAMPTZ NOT NULL,
    ts_end TIMESTAMPTZ NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_machine_state_machine_start ON machine_state (machine_id, ts_start DESC);

CREATE TABLE IF NOT EXISTS "user" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NULL REFERENCES "user"(id),
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail_json JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_event (at DESC);
