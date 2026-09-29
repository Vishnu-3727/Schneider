-- JouleMitra Phase 1 seed: 1 site (Demo SME Foundry, Asia/Kolkata)
-- with 3 demo machines: induction_furnace, air_compressor, cooling_pump.
-- Simulator physics is generic per machine TYPE (furnace/compressor/pump),
-- not foundry-hardcoded; these rows are just demo instances.

INSERT INTO site (id, name, location, timezone, industry_type) VALUES
    ('demo-foundry-01', 'Demo SME Foundry', 'India', 'Asia/Kolkata', 'foundry')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, location = EXCLUDED.location,
    timezone = EXCLUDED.timezone, industry_type = EXCLUDED.industry_type;

INSERT INTO machine (id, site_id, name, machine_type, rated_power_kw) VALUES
    ('furnace-01', 'demo-foundry-01', 'Induction Furnace 1', 'furnace', 200.0),
    ('compressor-01', 'demo-foundry-01', 'Air Compressor 1', 'compressor', 30.0),
    ('pump-01', 'demo-foundry-01', 'Cooling Pump 1', 'pump', 15.0)
ON CONFLICT (id) DO UPDATE SET
    site_id = EXCLUDED.site_id, name = EXCLUDED.name,
    machine_type = EXCLUDED.machine_type, rated_power_kw = EXCLUDED.rated_power_kw;

INSERT INTO sensor (id, machine_id, channel, unit, source) VALUES
    ('furnace-01-power', 'furnace-01', 'kW', 'kW', 'SIMULATED'),
    ('furnace-01-voltage', 'furnace-01', 'V', 'V', 'SIMULATED'),
    ('furnace-01-current', 'furnace-01', 'I', 'A', 'SIMULATED'),
    ('furnace-01-temp', 'furnace-01', 'temperature', 'C', 'SIMULATED'),
    ('furnace-01-vibration', 'furnace-01', 'vibration', 'mm/s', 'SIMULATED'),
    ('compressor-01-power', 'compressor-01', 'kW', 'kW', 'SIMULATED'),
    ('compressor-01-current', 'compressor-01', 'I', 'A', 'SIMULATED'),
    ('compressor-01-vibration', 'compressor-01', 'vibration', 'mm/s', 'SIMULATED'),
    ('pump-01-power', 'pump-01', 'kW', 'kW', 'SIMULATED'),
    ('pump-01-current', 'pump-01', 'I', 'A', 'SIMULATED'),
    ('pump-01-rpm', 'pump-01', 'rpm', 'rpm', 'SIMULATED')
ON CONFLICT (id) DO NOTHING;

INSERT INTO "user" (name, role) VALUES
    ('Demo Manager', 'factory_manager')
ON CONFLICT DO NOTHING;
