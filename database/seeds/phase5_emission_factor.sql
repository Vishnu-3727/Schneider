-- India all-grid CO2 emission factors (CEA CO2 Baseline Database for the
-- Indian Power Sector). EXTERNAL_REFERENCE. Values as reported publicly for
-- each version. CONFIRM against the CEA user-guide table before any
-- external use (see note). CEA factors cover CO2 only (not other GHGs).
-- effective_from/_to = the fiscal year the factor describes. For later
-- dates the latest available factor is applied and flagged
-- LATEST_AVAILABLE (services/verification/impact.py).
INSERT INTO emission_factor (id, geography, value_kg_per_kwh, unit, gas_basis, source_name,
    version, fiscal_year, effective_from, effective_to, source_class, note)
VALUES
    ('cea-v20-fy2023-24', 'India (all-India grid)', 0.727, 'kgCO2/kWh', 'CO2 only',
     'CEA CO2 Baseline Database for the Indian Power Sector', 'v20.0', 'FY2023-24',
     '2023-04-01', '2024-03-31', 'EXTERNAL_REFERENCE',
     'Weighted average incl. RE, 0.727 tCO2/MWh as reported for v20.0 (Dec 2024) - confirm against the CEA user guide'),
    ('cea-v21-fy2024-25', 'India (all-India grid)', 0.710, 'kgCO2/kWh', 'CO2 only',
     'CEA CO2 Baseline Database for the Indian Power Sector', 'v21.0', 'FY2024-25',
     '2024-04-01', '2025-03-31', 'EXTERNAL_REFERENCE',
     'Weighted average, 0.710 tCO2/MWh as reported for v21.0 (secondary sources also cite 0.7117) - confirm against the CEA user guide table')
ON CONFLICT (id) DO NOTHING;
