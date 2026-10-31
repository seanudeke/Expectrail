# Fix matrix

Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.
Set: dev. Runs: [41223754703](https://github.com/seanudeke/Expectrail/actions/runs/41223754703) (4697f54). Rule: first non-error result per case and condition, in run order.

| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |
| --- | --- | --- | --- | --- | --- |
| screenshots | 6 of 8 | 2 | 0 | 0 | 0 |
| expectrail | 8 of 8 | 0 | 0 | 0 | 0 |
| escalate | 7 of 8 | 1 | 0 | 0 | 0 |

Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, so attempts are a floor for a run with errors.

| Run | Muse Code attempts | SAM images (USD) | Job minutes |
| --- | --- | --- | --- |
| 41223754703 | 32 | 3,333 ($8.33) | 346 |

| Case | Condition | Outcome | Attempts | Minutes | Run |
| --- | --- | --- | --- | --- | --- |
| dev/layering/v1 | escalate | fixed | accept | 7 | 41223754703 |
| dev/layering/v1 | expectrail | fixed | accept | 6 | 41223754703 |
| dev/layering/v1 | screenshots | fixed | accept | 9 | 41223754703 |
| dev/layering/v2 | escalate | fixed | accept | 5 | 41223754703 |
| dev/layering/v2 | expectrail | fixed | accept | 6 | 41223754703 |
| dev/layering/v2 | screenshots | fixed | accept | 10 | 41223754703 |
| dev/missing-texture/v1 | escalate | fixed | accept | 10 | 41223754703 |
| dev/missing-texture/v1 | expectrail | fixed | accept | 6 | 41223754703 |
| dev/missing-texture/v1 | screenshots | fixed | accept | 9 | 41223754703 |
| dev/missing-texture/v2 | escalate | fixed | accept | 9 | 41223754703 |
| dev/missing-texture/v2 | expectrail | fixed | accept | 10 | 41223754703 |
| dev/missing-texture/v2 | screenshots | fixed | accept | 3 | 41223754703 |
| dev/physics-fall-through/v1 | escalate | fixed | accept | 6 | 41223754703 |
| dev/physics-fall-through/v1 | expectrail | fixed | accept | 4 | 41223754703 |
| dev/physics-fall-through/v1 | screenshots | fixed | accept | 11 | 41223754703 |
| dev/physics-fall-through/v2 | escalate | fixed | accept | 9 | 41223754703 |
| dev/physics-fall-through/v2 | expectrail | fixed | accept | 6 | 41223754703 |
| dev/physics-fall-through/v2 | screenshots | fixed | accept | 6 | 41223754703 |
| dev/sinking/v1 | escalate | not-fixed | timeout, timeout, timeout | 46 | 41223754703 |
| dev/sinking/v1 | expectrail | fixed | accept | 9 | 41223754703 |
| dev/sinking/v1 | screenshots | not-fixed | timeout, timeout, timeout | 46 | 41223754703 |
| dev/sinking/v2 | escalate | fixed | timeout, reject, accept | 50 | 41223754703 |
| dev/sinking/v2 | expectrail | fixed | accept | 16 | 41223754703 |
| dev/sinking/v2 | screenshots | not-fixed | timeout, timeout, timeout | 45 | 41223754703 |
