-- JouleMitra Phase 4B schema (006_phase4b.sql)
-- recommendation stores one human-in-the-loop proposal per (rule, machine,
-- window, inputs): full evidence, constraints, projected-or-null effect,
-- confidence + the rule behind it, assumptions, source class
-- (DERIVED for observations, PROJECTED for optimizer deltas), review
-- status and a verification flag that stays NOT_VERIFIED through Phase 4
-- (verification is Phase 5 work). Idempotent generation via dedup_key.
-- Every acknowledge decision also writes an audit_event row (done by the
-- API, which owns the audit_event table from 001_phase1.sql).

CREATE TABLE IF NOT EXISTS recommendation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT NOT NULL REFERENCES machine(id),
    rule_id TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    evidence JSONB NOT NULL DEFAULT '{}',
    constraints_considered JSONB NOT NULL DEFAULT '[]',
    proposed_action TEXT NOT NULL DEFAULT '',
    expected_effect JSONB NULL,
    confidence TEXT NOT NULL,
    confidence_reason TEXT NOT NULL DEFAULT '',
    assumptions JSONB NOT NULL DEFAULT '[]',
    source_module TEXT NOT NULL DEFAULT '',
    source_class TEXT NOT NULL DEFAULT 'DERIVED',
    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
    verification_status TEXT NOT NULL DEFAULT 'NOT_VERIFIED',
    conflict_with JSONB NOT NULL DEFAULT '[]',
    conflict_note TEXT NOT NULL DEFAULT '',
    window_start TIMESTAMPTZ NULL,
    window_end TIMESTAMPTZ NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    decided_at TIMESTAMPTZ NULL,
    decided_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_recommendation_machine_status
    ON recommendation (machine_id, status);
CREATE INDEX IF NOT EXISTS ix_recommendation_dedup
    ON recommendation (dedup_key);
