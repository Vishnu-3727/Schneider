-- JouleMitra Phase 3A schema (004_phase3.sql)
-- machine_health stores one scored interval per (machine, window, model);
-- machine_health_reference stores each machine's fitted NORMAL reference
-- (params = per-bucket median/MAD JSON). Earlier migrations untouched.

CREATE TABLE IF NOT EXISTS machine_health (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    model_id TEXT NOT NULL,
    health_score DOUBLE PRECISION NULL,
    anomaly_score DOUBLE PRECISION NULL,
    state TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    contributions JSONB NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'DERIVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (machine_id, window_start, window_end, model_id)
);
CREATE INDEX IF NOT EXISTS ix_health_machine_window
    ON machine_health (machine_id, window_start, window_end);
CREATE INDEX IF NOT EXISTS ix_health_state ON machine_health (state);

CREATE TABLE IF NOT EXISTS machine_health_reference (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id TEXT NOT NULL,
    machine_id TEXT NOT NULL REFERENCES machine(id),
    params JSONB NOT NULL DEFAULT '{}',
    train_start TIMESTAMPTZ NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    n_intervals INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'DERIVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_health_ref_machine_created
    ON machine_health_reference (model_id, machine_id, created_at DESC);
