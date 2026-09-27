-- JouleMitra Phase 5A schema (008_phase5.sql)
-- Explicit lifecycle: recommendation.status moves
-- PENDING_REVIEW/CONFLICT -> APPROVED | REJECTED -> APPLIED -> MEASURED ->
-- VERIFIED | NOT_VERIFIED | NOT_COMPARABLE | INSUFFICIENT_DATA
-- (enforced in services/verification/lifecycle.py). Phase 4 stored an
-- approval as ACCEPTED; it is renamed APPROVED here.
-- intervention: one applied action per recommendation, idempotent by key.
-- verification_result: one counterfactual verification per intervention.

UPDATE recommendation SET status = 'APPROVED' WHERE status = 'ACCEPTED';

CREATE TABLE IF NOT EXISTS intervention (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id UUID NOT NULL UNIQUE REFERENCES recommendation(id),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    type TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}',
    applied_at TIMESTAMPTZ NOT NULL,
    baseline_start TIMESTAMPTZ NOT NULL,
    baseline_end TIMESTAMPTZ NOT NULL,
    measurement_start TIMESTAMPTZ NULL,
    measurement_end TIMESTAMPTZ NULL,
    status TEXT NOT NULL DEFAULT 'APPLIED',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verification_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intervention_id UUID NOT NULL UNIQUE REFERENCES intervention(id),
    method TEXT NOT NULL,
    result_class TEXT NOT NULL,
    outcome TEXT NOT NULL,
    explanation TEXT NOT NULL,
    counterfactual_kwh DOUBLE PRECISION NULL,
    actual_kwh DOUBLE PRECISION NULL,
    saving_kwh DOUBLE PRECISION NULL,
    saving_pct DOUBLE PRECISION NULL,
    uncertainty_kwh DOUBLE PRECISION NULL,
    confidence DOUBLE PRECISION NULL,
    production_before_kg_h DOUBLE PRECISION NULL,
    production_after_kg_h DOUBLE PRECISION NULL,
    comparable BOOLEAN NULL,
    comparability_reasons JSONB NOT NULL DEFAULT '[]',
    n_baseline INTEGER NOT NULL DEFAULT 0,
    n_post INTEGER NOT NULL DEFAULT 0,
    baseline_complete_frac DOUBLE PRECISION NOT NULL DEFAULT 0,
    post_complete_frac DOUBLE PRECISION NOT NULL DEFAULT 0,
    model JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
