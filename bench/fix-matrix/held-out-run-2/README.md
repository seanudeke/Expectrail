# Fix matrix

Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.
Set: held-out. Runs: [41199992529](https://github.com/seanudeke/Expectrail/actions/runs/41199992529) (e216fb7). Rule: first non-error result per case and condition, in run order.

| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |
| --- | --- | --- | --- | --- | --- |
| screenshots | 7 of 8 | 1 | 0 | 0 | 0 |
| expectrail | 8 of 8 | 0 | 0 | 0 | 0 |

Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, so attempts are a floor for a run with errors.

| Run | Muse Code attempts | SAM images (USD) | Job minutes |
| --- | --- | --- | --- |
| 41199992529 | 19 | 727 ($1.82) | 185 |

| Case | Condition | Outcome | Attempts | Minutes | Run |
| --- | --- | --- | --- | --- | --- |
| layering/v5 | expectrail | fixed | accept | 10 | 41199992529 |
| layering/v5 | screenshots | fixed | accept | 18 | 41199992529 |
| layering/v6 | expectrail | fixed | accept | 3 | 41199992529 |
| layering/v6 | screenshots | fixed | accept | 4 | 41199992529 |
| missing-texture/v5 | expectrail | fixed | accept | 6 | 41199992529 |
| missing-texture/v5 | screenshots | fixed | accept | 13 | 41199992529 |
| missing-texture/v6 | expectrail | fixed | accept | 6 | 41199992529 |
| missing-texture/v6 | screenshots | fixed | accept | 8 | 41199992529 |
| physics-fall-through/v5 | expectrail | fixed | accept | 5 | 41199992529 |
| physics-fall-through/v5 | screenshots | fixed | accept | 7 | 41199992529 |
| physics-fall-through/v6 | expectrail | fixed | accept | 3 | 41199992529 |
| physics-fall-through/v6 | screenshots | fixed | accept | 8 | 41199992529 |
| sinking/v3 | expectrail | fixed | accept | 9 | 41199992529 |
| sinking/v3 | screenshots | fixed | accept | 10 | 41199992529 |
| sinking/v4 | expectrail | fixed | reject, accept | 30 | 41199992529 |
| sinking/v4 | screenshots | not-fixed | timeout, timeout, timeout | 46 | 41199992529 |
