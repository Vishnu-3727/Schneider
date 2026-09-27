# JouleMitra — Simulation scenarios (Phase 2)

Engine: `apps/simulator/factory_simulator.py` (`SimulatedFactory`). All
records carry `source=SIMULATED`. Scenario effects are in-run physics
overrides applied BEFORE energy integration (never post-hoc packet edits,
which would corrupt the cumulative counter).

Common parameters: `scenario_start_h` (offset from run start),
`scenario_duration_h`, `magnitude`. CLI:
`python -m apps.simulator --normal-days 7 --scenario IDLE_WASTE --hours 24
--post [--magnitude X] [--end ISO]`.
Ground-truth windows (`scenario_windows()`) exist for tests only and are
never stored as telemetry.

Hour-boundary alignment: the first telemetry row is stamped at the run start
(`ts = start + i·step`, not `start + (i+1)·step`), so each hourly telemetry
bucket holds the same step set whose production hour index the factory
derives from `i` — production, state shares and energy all cover the same
steps (only the cumulative-counter delta inherently spans one step less).
Without this, production lands one bucket off its energy and every hour
mis-scores.

## NORMAL (existing, Phase 1)

Furnace batch cycle (heating/melting/holding/idle), compressor load/unload,
pump modulated — see `docs/ASSUMPTIONS.md` A4–A6.

## IDLE_WASTE (magnitude unused, structural)

- Furnace: forced powered holding (0.45 × rated) with zero production —
  energy spent with no useful output. SEC → NO_PRODUCTION, energy reported
  as non-productive kWh.
- Compressor: forced continuously loaded (0.90 × rated) against no demand
  (+~30 % energy at zero output). The compressor is auxiliary
  (`NON_PRODUCTION_TYPES`): its SEC reports NOT_APPLICABLE, and detection
  is by deviation, not SEC.
- Pump: unchanged (unaffected control).
- Detected by: L1_IDLE_WASTE (furnace) + L1_DEVIATION (compressor).
- Persistence, not a single hour, is the signal: a melt-free hour is normal
  inter-heat batch rhythm, so the idle rule fires only after
  `IDLE_CONSECUTIVE_N` (4) consecutive qualifying intervals — beyond the
  longest legitimate melt-free span (see docs/ASSUMPTIONS.md A17).

## HIGH_LOAD (default magnitude 0.25 = +25 % power, same useful output)

- Furnace: normal cycle, every power setpoint × (1 + magnitude), production
  unchanged. Compressor: loaded/unloaded fractions × (1 + magnitude).
- Rows stay GOOD quality (1.19 × rated max < 1.5 × spike multiple).
- Detected by: L1_DEVIATION (+25 %) + L1_POWER (peak above 1.1 × rated).

## PRODUCTION_SURGE (default magnitude 0.30)

- Furnace only: MORE HEATS PER DAY — idle gaps (incl. lunch/shift extras)
  shrink via the furnace `idle_scale` knob while per-kg melting physics is
  unchanged: same kWh/kg, higher production, higher energy. State mixes stay
  on the training manifold by construction, so the baseline predicts it
  (small aggregate deviation, measured numbers in docs/VALIDATION.md) and
  raises no event. THIS is the legitimate-load case the baseline must not
  flag.
- Melting peak stays below the L1 power rule (1.1 ×) and the spike multiple
  (1.5 ×).

## Still NotImplementedError (Phase 3+)

EQUIPMENT_DEGRADATION, TARIFF_SHIFT, COMBINED_ANOMALY (see
`PHASE3_SCENARIOS`). `fault_generator.apply_fault` passes NORMAL through
and raises for everything else (post-hoc edits would break the energy
counter — Phase-2 scenarios live in `SimulatedFactory`).
