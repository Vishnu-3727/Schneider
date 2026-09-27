-- JouleMitra Phase 2 schema (002_phase2.sql)
-- EnergyBaseline stores one row per model FIT (machine, version, features,
-- coefficients, training window, metrics). AnomalyEvent stores merged
-- detection events. Phase-1 migration is untouched.

CREATE TABLE IF NOT EXISTS energy_baseline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    model_version TEXT NOT NULL,
    features JSONB NOT NULL DEFAULT '[]',
    coefficients JSONB NOT NULL DEFAULT '{}',
    intercept DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    train_start TIMESTAMPTZ NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    n_intervals INTEGER NOT NULL,
    r2_train DOUBLE PRECISION NULL,
    cv_rmse_pct_train DOUBLE PRECISION NULL,
    nmbe_pct_train DOUBLE PRECISION NULL,
    r2_holdout DOUBLE PRECISION NULL,
    cv_rmse_pct_holdout DOUBLE PRECISION NULL,
    nmbe_pct_holdout DOUBLE PRECISION NULL,
    acceptance TEXT NULL DEFAULT NULL,
    source TEXT NOT NULL DEFAULT 'DERIVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_baseline_machine_created
    ON energy_baseline (machine_id, created_at DESC);

CREATE TABLE IF NOT EXISTS anomaly_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    metric TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    level TEXT NOT NULL,
    score DOUBLE PRECISION NULL,
    severity TEXT NOT NULL,
    expected_kwh DOUBLE PRECISION NULL,
    actual_kwh DOUBLE PRECISION NULL,
    deviation_kwh DOUBLE PRECISION NULL,
    deviation_pct DOUBLE PRECISION NULL,
    evidence TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    source TEXT NOT NULL DEFAULT 'DERIVED',
    dedup_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dedup_key)
);
CREATE INDEX IF NOT EXISTS ix_anomaly_machine_window
    ON anomaly_event (machine_id, window_start, window_end);
CREATE INDEX IF NOT EXISTS ix_anomaly_status ON anomaly_event (status);
