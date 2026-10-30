# Fix matrix

Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.
Set: dev. Runs: [41109646183](https://github.com/seanudeke/Expectrail/actions/runs/41109646183) (07c4ff2). Rule: first non-error result per case and condition, in run order.

| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |
| --- | --- | --- | --- | --- | --- |
| screenshots | 8 of 8 | 0 | 0 | 0 | 0 |
| expectrail | 8 of 8 | 0 | 0 | 0 | 0 |

Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, so attempts are a floor for a run with errors.

| Run | Muse Code attempts | SAM images (USD) | Job minutes |
| --- | --- | --- | --- |
| 41109646183 | 16 | 2,209 ($5.52) | 46 |

| Case | Condition | Outcome | Attempts | Minutes | Run |
| --- | --- | --- | --- | --- | --- |
| dev/fall-through/v1 | expectrail | fixed | accept | 3 | 41109646183 |
| dev/fall-through/v1 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/fall-through/v2 | expectrail | fixed | accept | 2 | 41109646183 |
| dev/fall-through/v2 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/layering/v1 | expectrail | fixed | accept | 3 | 41109646183 |
| dev/layering/v1 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/layering/v2 | expectrail | fixed | accept | 2 | 41109646183 |
| dev/layering/v2 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/missing-texture/v1 | expectrail | fixed | accept | 6 | 41109646183 |
| dev/missing-texture/v1 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/missing-texture/v2 | expectrail | fixed | accept | 2 | 41109646183 |
| dev/missing-texture/v2 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/sinking/v1 | expectrail | fixed | accept | 8 | 41109646183 |
| dev/sinking/v1 | screenshots | fixed | accept | 2 | 41109646183 |
| dev/sinking/v2 | expectrail | fixed | accept | 2 | 41109646183 |
| dev/sinking/v2 | screenshots | fixed | accept | 2 | 41109646183 |
