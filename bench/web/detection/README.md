# Detection benchmark: the checkout page

Written by `python3 -m agents.bench_collect` from the run's own annotations; do not edit by hand.
A variant is caught when any check fails on at least one route. Rerun a set by
dispatching `web-bench.yml` (bench detection) and collecting with `python3 -m agents.bench_collect --app checkout --run <id> --out bench/web/detection`.

## dev (run [41104422848](https://github.com/seanudeke/Expectrail/actions/runs/41104422848), 2026-10-30, commit f3851da)

Caught with SAM: **8 of 8**. Without SAM: **4 of 8**. False alarms on the clean page (2 routes): none with SAM, none without.

Spend: SAM images 386 ($0.96); 3 job minutes.

| Variant | Caught, SAM on | Caught, SAM off | Failing checks (routes) |
| --- | --- | --- | --- |
| dev/fall-through/v1 | yes | yes | layout 2, checkout-button-visible 2 |
| dev/fall-through/v2 | yes | yes | layout 2, behaviour 2, checkout-button-visible 2 |
| dev/layering/v1 | yes | yes | behaviour 2, checkout-button-visible 2 |
| dev/layering/v2 | yes | no | checkout-button-visible 2 |
| dev/missing-texture/v1 | yes | no | logo-visible 2 |
| dev/missing-texture/v2 | yes | no | checkout-button-visible 2 |
| dev/sinking/v1 | yes | yes | layout 2, hybrid 2 |
| dev/sinking/v2 | yes | no | hybrid 2 |
