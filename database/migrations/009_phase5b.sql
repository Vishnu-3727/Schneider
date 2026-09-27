-- JouleMitra Phase 5B schema (009_phase5b.sql)
-- emission_factor: grid emission factors as data with provenance (never
-- hard-coded). verification_result gains the cost and CO2 impact of a
-- VERIFIED saving (NOT_APPLICABLE for every other outcome).

CREATE TABLE IF NOT EXISTS emission_factor (
    id TEXT PRIMARY KEY,
    geography TEXT NOT NULL,
    value_kg_per_kwh DOUBLE PRECISION NOT NULL CHECK (value_kg_per_kwh >= 0),
    unit TEXT NOT NULL DEFAULT 'kgCO2/kWh',
    gas_basis TEXT NOT NULL,
    source_name TEXT NOT NULL,
    version TEXT NOT NULL,
    fiscal_year TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    source_class TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);

ALTER TABLE verification_result ADD COLUMN IF NOT EXISTS cost_impact JSONB NOT NULL DEFAULT '{}';
ALTER TABLE verification_result ADD COLUMN IF NOT EXISTS co2_impact JSONB NOT NULL DEFAULT '{}';
