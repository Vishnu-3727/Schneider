# Monte Carlo validation of savings verification (SIMULATED data)

Paired runs: for each seed the SAME plant is simulated twice with the same seed -- once with the intervention, once with a NO-OP intervention (common random numbers). TRUE saving = energy(NO-OP post) - energy(intervention post). Setup: furnace-01 (200 kW), chronic idle holding 60 %, 7-day baseline + 3-day measurement, step 300 s. Command: `python scripts/validation/monte_carlo_verify.py --n 100 --seed0 1`. Runtime 74 s. All data SIMULATED; says nothing about real plant performance. Thresholds were NOT tuned to these numbers.

## Summary

| scenario | N | paired | VERIFIED | NOT_VERIFIED | NOT_COMPARABLE | INSUFFICIENT_DATA | false-claim all | false-claim paired | coverage all | coverage paired | mean TRUE kWh | mean reported kWh | mean |error| kWh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_effect | 100 | 100 | 1 | 94 | 5 | 0 | 1.0% | 1.0% | 98.9% | 98.9% | 0.0 | -1.9 | 60.4 |
| partial | 100 | 100 | 70 | 25 | 5 | 0 | n/a | n/a | 100.0% | 100.0% | 305.8 | 297.1 | 60.6 |
| full | 100 | 0 | 98 | 0 | 2 | 0 | 50.0% | n/a | 64.3% | n/a | 779.6 | 721.1 | 197.6 |
| worse | 100 | 0 | 0 | 97 | 3 | 0 | 0.0% | n/a | 57.7% | n/a | -1,094.2 | -1,125.3 | 214.6 |
| production_shift | 100 | 100 | 0 | 0 | 100 | 0 | n/a | n/a | n/a | n/a | 158.3 | n/a | n/a |

false-claim = share VERIFIED among runs with TRUE saving <= 0; coverage = share of comparable runs (a saving was reported) where TRUE saving lies within reported saving +/- uncertainty (stated confidence 90 %); means over comparable runs for reported/error. Each metric is shown over all pairs and over paired pairs only (identical heat-start times in both runs); unpaired pairs are different random realisations, not measurements of verify.

## no_effect (N=100, paired=100)

Outcomes: VERIFIED 1, NOT_VERIFIED 94, NOT_COMPARABLE 5, INSUFFICIENT_DATA 0. Result classes: SUCCESS 1, NO_EFFECT 94, WORSE 0, NOT_COMPARABLE 5, INSUFFICIENT_DATA 0. False-claim 1.0% (1/100 VERIFIED among runs with TRUE saving <= 0); paired-only 1.0% (1/100); coverage 98.9% (n=95 comparable); paired-only 98.9% (n=95 comparable); mean TRUE 0.0 kWh, mean reported -1.9 kWh, mean |error| 60.4 kWh.

Nothing was changed (NO-OP control: effectiveness 0), so the TRUE saving is exactly 0 and any VERIFIED outcome would be a false claim. The false-claim rate says how often the 90 % uncertainty band cried wolf on identical plants; a small single-digit rate is the expected price of a 90 % confidence level, while anything near or above 10 % would mean the uncertainty is understated.

## partial (N=100, paired=100)

Outcomes: VERIFIED 70, NOT_VERIFIED 25, NOT_COMPARABLE 5, INSUFFICIENT_DATA 0. Result classes: SUCCESS 70, NO_EFFECT 25, WORSE 0, NOT_COMPARABLE 5, INSUFFICIENT_DATA 0. False-claim n/a (0/0 VERIFIED among runs with TRUE saving <= 0); paired-only n/a (0/0); coverage 100.0% (n=95 comparable); paired-only 100.0% (n=95 comparable); mean TRUE 305.8 kWh, mean reported 297.1 kWh, mean |error| 60.6 kWh.

The fix is real but small (effectiveness 0.5, compliance 0.6), so whether 3 days of data can prove it depends on how much idle waste that week's seed happened to contain: waste-rich weeks verify, the rest honestly return NO_EFFECT with the saving inside the uncertainty band. That borderline split is the expected answer, not a miss -- a longer measurement window would narrow the uncertainty.

## full (N=100, paired=0)

Outcomes: VERIFIED 98, NOT_VERIFIED 0, NOT_COMPARABLE 2, INSUFFICIENT_DATA 0. Result classes: SUCCESS 98, NO_EFFECT 0, WORSE 0, NOT_COMPARABLE 2, INSUFFICIENT_DATA 0. False-claim 50.0% (1/2 VERIFIED among runs with TRUE saving <= 0); paired-only n/a (0/0); coverage 64.3% (n=98 comparable); paired-only n/a (n=0 comparable); mean TRUE 779.6 kWh, mean reported 721.1 kWh, mean |error| 197.6 kWh.

The full fix (effectiveness 1.0, rebound 0.15) saves several hundred kWh, well above the uncertainty, so the detection rate -- the share VERIFIED -- should be at or near 100 %. Anything much lower would mean real savings are being missed. Most pairs here are unpaired (rebound moves heat starts, so the runs are different realisations): the all-pairs coverage mixes in realisation noise and only the paired-only cut measures the uncertainty band itself.

## worse (N=100, paired=0)

Outcomes: VERIFIED 0, NOT_VERIFIED 97, NOT_COMPARABLE 3, INSUFFICIENT_DATA 0. Result classes: SUCCESS 0, NO_EFFECT 0, WORSE 97, NOT_COMPARABLE 3, INSUFFICIENT_DATA 0. False-claim 0.0% (0/100 VERIFIED among runs with TRUE saving <= 0); paired-only n/a (0/0); coverage 57.7% (n=97 comparable); paired-only n/a (n=0 comparable); mean TRUE -1,094.2 kWh, mean reported -1,125.3 kWh, mean |error| 214.6 kWh.

Reheat outweighs the fix (rebound 1.0), so TRUE saving is negative and verification must report WORSE / NOT_VERIFIED, never VERIFIED. The false-claim rate here is the share VERIFIED among runs where energy went up; it must be zero, and the WORSE label shows the increase is reported, not hidden. Most pairs here are unpaired (rebound moves heat starts, so the runs are different realisations): the all-pairs coverage mixes in realisation noise and only the paired-only cut measures the uncertainty band itself.

## production_shift (N=100, paired=100)

Outcomes: VERIFIED 0, NOT_VERIFIED 0, NOT_COMPARABLE 100, INSUFFICIENT_DATA 0. Result classes: SUCCESS 0, NO_EFFECT 0, WORSE 0, NOT_COMPARABLE 100, INSUFFICIENT_DATA 0. False-claim n/a (0/0 VERIFIED among runs with TRUE saving <= 0); paired-only n/a (0/0); coverage n/a (n=0 comparable); paired-only n/a (n=0 comparable); mean TRUE 158.3 kWh, mean reported n/a kWh, mean |error| n/a kWh.

Production shifts after the change (post_idle_scale 0.1), so the post period is not comparable to the baseline and every run must be refused as NOT_COMPARABLE with no saving reported -- even though a TRUE intervention effect exists. Any VERIFIED outcome here would be a saving claimed under non-comparable conditions, which the method forbids.
