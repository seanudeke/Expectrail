# Detection benchmark

Written by `python3 -m agents.bench_collect` from the run's own annotations; do not edit by hand.
A variant is caught when any check fails on at least one route. Rerun a set with
`bench/rerun-detection.sh dev` or `bench/rerun-detection.sh held-out`.

## dev (run [40841977642](https://github.com/seanudeke/Nightshift/actions/runs/40841977642), 2026-10-29, commit c8bce4d)

Caught with SAM: **8 of 8**. Without SAM: **3 of 8**. False alarms on the clean game (5 routes): none with SAM, none without.

| Variant | Caught, SAM on | Caught, SAM off | Failing checks (routes) |
| --- | --- | --- | --- |
| dev/layering/v1 | yes | no | player-always-visible 5 |
| dev/layering/v2 | yes | no | player-always-visible 5 |
| dev/missing-texture/v1 | yes | no | coins-visible 5 |
| dev/missing-texture/v2 | yes | no | coins-visible 5 |
| dev/physics-fall-through/v1 | yes | yes | engine 5, gameplay 5, hybrid 5, player-always-visible 5 |
| dev/physics-fall-through/v2 | yes | yes | engine 5, gameplay 5, hybrid 5, player-always-visible 5 |
| dev/sinking/v1 | yes | yes | engine 5, hybrid 5, player-always-visible 2 |
| dev/sinking/v2 | yes | no | hybrid 5, player-always-visible 2 |

## held-out (run [41003749744](https://github.com/seanudeke/Nightshift/actions/runs/41003749744), 2026-10-30, commit 92508d9)

Caught with SAM: **8 of 8**. Without SAM: **4 of 8**. False alarms on the clean game (5 routes): none with SAM, none without.

Spend: SAM images 7,693 ($19.23); 51 job minutes.

| Variant | Caught, SAM on | Caught, SAM off | Failing checks (routes) |
| --- | --- | --- | --- |
| layering/v5 | yes | no | player-always-visible 5 |
| layering/v6 | yes | no | player-always-visible 5 |
| missing-texture/v5 | yes | no | coins-visible 5 |
| missing-texture/v6 | yes | no | coins-visible 5 |
| physics-fall-through/v5 | yes | yes | engine 5, gameplay 5, hybrid 5, player-always-visible 5 |
| physics-fall-through/v6 | yes | yes | engine 5, gameplay 5, hybrid 5, player-always-visible 5 |
| sinking/v3 | yes | yes | engine 5, hybrid 5, player-always-visible 3 |
| sinking/v4 | yes | yes | engine 5, hybrid 5 |
