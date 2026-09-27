-- JouleMitra Phase 4A seed: ONE illustrative time-of-use tariff.
-- source_class='ASSUMPTION', reference_note says ILLUSTRATIVE: this is NOT a
-- real tariff order. Replace with the plant's DISCOM tariff before any
-- commercial decision. Tariff VALUES live only here, never in code.
-- Re-applied on every init_db. The upsert only overwrites rows still
-- labelled ASSUMPTION, so a real DISCOM tariff entered later is never
-- clobbered by a re-seed. A period with end_local <= start_local wraps past
-- midnight (e.g. 22:00-00:00 covers the late evening off-peak block).

INSERT INTO tariff (site_id, period_name, start_local, end_local,
                    energy_inr_per_kwh, demand_inr_per_kw,
                    valid_from, source_class, reference_note)
VALUES
    ('demo-foundry-01', 'off_peak_night', '00:00', '06:00',
     6.0, NULL, '2026-01-01', 'ASSUMPTION',
     'ILLUSTRATIVE - not a real tariff order - replace with the plant DISCOM tariff'),
    ('demo-foundry-01', 'normal_day', '06:00', '18:00',
     7.5, NULL, '2026-01-01', 'ASSUMPTION',
     'ILLUSTRATIVE - not a real tariff order - replace with the plant DISCOM tariff'),
    ('demo-foundry-01', 'evening_peak', '18:00', '22:00',
     10.5, NULL, '2026-01-01', 'ASSUMPTION',
     'ILLUSTRATIVE - not a real tariff order - replace with the plant DISCOM tariff'),
    ('demo-foundry-01', 'off_peak_late', '22:00', '00:00',
     6.0, NULL, '2026-01-01', 'ASSUMPTION',
     'ILLUSTRATIVE - not a real tariff order - replace with the plant DISCOM tariff')
ON CONFLICT (site_id, period_name, valid_from) DO UPDATE SET
    start_local = EXCLUDED.start_local,
    end_local = EXCLUDED.end_local,
    energy_inr_per_kwh = EXCLUDED.energy_inr_per_kwh,
    demand_inr_per_kw = EXCLUDED.demand_inr_per_kw,
    source_class = EXCLUDED.source_class,
    reference_note = EXCLUDED.reference_note
WHERE tariff.source_class = 'ASSUMPTION';
