# Fix matrix

Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.
Set: held-out. Runs: [41099054641](https://github.com/seanudeke/Expectrail/actions/runs/41099054641) (016a4fe). Rule: first non-error result per case and condition, in run order.

| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |
| --- | --- | --- | --- | --- | --- |
| screenshots | 7 of 8 | 1 | 0 | 0 | 0 |
| expectrail | 8 of 8 | 0 | 0 | 0 | 0 |

Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, so attempts are a floor for a run with errors.

| Run | Muse Code attempts | SAM images (USD) | Job minutes |
| --- | --- | --- | --- |
| 41099054641 | 19 | 1,859 ($4.65) | 181 |

| Case | Condition | Outcome | Attempts | Minutes | Run |
| --- | --- | --- | --- | --- | --- |
| layering/v5 | expectrail | fixed | accept | 7 | 41099054641 |
| layering/v5 | screenshots | fixed | accept | 6 | 41099054641 |
| layering/v6 | expectrail | fixed | accept | 5 | 41099054641 |
| layering/v6 | screenshots | fixed | accept | 4 | 41099054641 |
| missing-texture/v5 | expectrail | fixed | accept | 4 | 41099054641 |
| missing-texture/v5 | screenshots | fixed | accept | 5 | 41099054641 |
| missing-texture/v6 | expectrail | fixed | accept | 8 | 41099054641 |
| missing-texture/v6 | screenshots | fixed | accept | 4 | 41099054641 |
| physics-fall-through/v5 | expectrail | fixed | accept | 7 | 41099054641 |
| physics-fall-through/v5 | screenshots | fixed | accept | 12 | 41099054641 |
| physics-fall-through/v6 | expectrail | fixed | accept | 6 | 41099054641 |
| physics-fall-through/v6 | screenshots | fixed | accept | 9 | 41099054641 |
| sinking/v3 | expectrail | fixed | accept | 11 | 41099054641 |
| sinking/v3 | screenshots | fixed | accept | 11 | 41099054641 |
| sinking/v4 | expectrail | fixed | timeout, accept | 37 | 41099054641 |
| sinking/v4 | screenshots | not-fixed | reject, timeout, timeout | 44 | 41099054641 |
