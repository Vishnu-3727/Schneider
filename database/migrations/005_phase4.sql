-- JouleMitra Phase 4A schema (005_phase4.sql)
-- Tariff stores time-of-use energy/demand prices AS DATA (never in code).
-- The seed row is ILLUSTRATIVE (source_class='ASSUMPTION'); replace with the
-- plant's DISCOM tariff order. Earlier migrations untouched.
--
-- optimization_run stores one optimizer invocation: inputs hash,
-- constraints, status, current vs recommended schedules, metrics and
-- explanation. Every output number derived from a run is PROJECTED.

CREATE TABLE IF NOT EXISTS tariff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id TEXT NOT NULL REFERENCES site(id),
    period_name TEXT NOT NULL,
    start_local TIME NOT NULL,
    end_local TIME NOT NULL,
    energy_inr_per_kwh DOUBLE PRECISION NOT NULL,
    demand_inr_per_kw DOUBLE PRECISION NULL,
    valid_from DATE NOT NULL,
    source_class TEXT NOT NULL DEFAULT 'ASSUMPTION',
    reference_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, period_name, valid_from)
);
CREATE INDEX IF NOT EXISTS ix_tariff_site_valid
    ON tariff (site_id, valid_from);

CREATE TABLE IF NOT EXISTS optimization_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    horizon_start TIMESTAMPTZ NOT NULL,
    horizon_end TIMESTAMPTZ NOT NULL,
    inputs_hash TEXT NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    current_schedule JSONB NULL,
    recommended_schedule JSONB NULL,
    metrics JSONB NOT NULL DEFAULT '{}',
    explanation TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'PROJECTED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_optrun_machine_created
    ON optimization_run (machine_id, created_at DESC);
