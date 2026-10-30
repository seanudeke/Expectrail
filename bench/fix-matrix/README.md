# Fix matrix

Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.
Set: dev. Runs: [40916077549](https://github.com/seanudeke/Nightshift/actions/runs/40916077549) (7cca77a), [40927304209](https://github.com/seanudeke/Nightshift/actions/runs/40927304209) (444e9c8), [40927316337](https://github.com/seanudeke/Nightshift/actions/runs/40927316337) (444e9c8). Rule: first non-error result per case and condition, in run order.

| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |
| --- | --- | --- | --- | --- | --- |
| screenshots | 8 of 8 | 0 | 0 | 0 | 0 |
| nightshift | 8 of 8 | 0 | 0 | 0 | 0 |

Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, so attempts are a floor for a run with errors.

| Run | Muse Code attempts | SAM images (USD) | Job minutes |
| --- | --- | --- | --- |
| 40916077549 | 11 | not counted | 240 |
| 40927304209 | 5 | not counted | 104 |
| 40927316337 | 1 | not counted | 10 |

| Case | Condition | Outcome | Attempts | Minutes | Run |
| --- | --- | --- | --- | --- | --- |
| dev/layering/v1 | nightshift | fixed | accept | 16 | 40916077549 |
| dev/layering/v1 | screenshots | fixed | accept | 18 | 40916077549 |
| dev/layering/v2 | nightshift | fixed | accept | 10 | 40927316337 (replaces an error in 40916077549) |
| dev/layering/v2 | screenshots | fixed | accept | 23 | 40916077549 |
| dev/missing-texture/v1 | nightshift | fixed | accept | 17 | 40916077549 |
| dev/missing-texture/v1 | screenshots | fixed | accept | 9 | 40916077549 |
| dev/missing-texture/v2 | nightshift | fixed | accept | 20 | 40916077549 |
| dev/missing-texture/v2 | screenshots | fixed | accept | 9 | 40916077549 |
| dev/physics-fall-through/v1 | nightshift | fixed | accept | 12 | 40916077549 |
| dev/physics-fall-through/v1 | screenshots | fixed | accept | 10 | 40916077549 |
| dev/physics-fall-through/v2 | nightshift | fixed | accept | 13 | 40916077549 |
| dev/physics-fall-through/v2 | screenshots | fixed | accept | 15 | 40916077549 |
| dev/sinking/v1 | nightshift | fixed | timeout, accept | 36 | 40927304209 (replaces an error in 40916077549) |
| dev/sinking/v1 | screenshots | fixed | accept | 22 | 40927304209 (replaces an error in 40916077549) |
| dev/sinking/v2 | nightshift | fixed | accept | 23 | 40927304209 (replaces an error in 40916077549) |
| dev/sinking/v2 | screenshots | fixed | accept | 23 | 40927304209 (replaces an error in 40916077549) |
