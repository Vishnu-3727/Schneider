-- JouleMitra Phase 4C schema (007_phase4c.sql)
-- Add comparability columns to optimization_run: comparable (bool) and
-- comparability_reason (text). Earlier migrations untouched.

ALTER TABLE optimization_run
    ADD COLUMN IF NOT EXISTS comparable BOOLEAN,
    ADD COLUMN IF NOT EXISTS comparability_reason TEXT;