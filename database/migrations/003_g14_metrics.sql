-- JouleMitra Phase 2 follow-up (003_g14_metrics.sql)
-- Adds NMBE % + ASHRAE G14 acceptance to energy_baseline. Fresh databases
-- already get these columns from 002_phase2.sql; this ALTER covers databases
-- where 002 was applied before the columns existed. Idempotent.
ALTER TABLE IF EXISTS energy_baseline
    ADD COLUMN IF NOT EXISTS nmbe_pct_train DOUBLE PRECISION NULL;
ALTER TABLE IF EXISTS energy_baseline
    ADD COLUMN IF NOT EXISTS nmbe_pct_holdout DOUBLE PRECISION NULL;
ALTER TABLE IF EXISTS energy_baseline
    ADD COLUMN IF NOT EXISTS acceptance TEXT NULL DEFAULT NULL;
