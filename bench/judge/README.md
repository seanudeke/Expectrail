# Judge benchmark

Written by `python3 -m agents.bench_collect --judge` from the runs' own annotations; do not edit by hand.
Runs: [40936362830](https://github.com/seanudeke/Nightshift/actions/runs/40936362830) (2026-10-29, commit 8e7b9d6).

| Judge | Run | Good fixes accepted | Bad fixes accepted | Undecided |
| --- | --- | --- | --- | --- |
| Nightshift, SAM on | 40936362830 | 8 of 8 | 0 of 7 | 0 |
| Nightshift, SAM off | 40936362830 | 8 of 8 | 3 of 7 | 0 |
| Muse from screenshots | 40936362830 | 6 of 8 | 2 of 7 | 0 |

Each cell lists the decision in each run, in the order above.

| Case | Right answer | Nightshift, SAM on | Nightshift, SAM off | Muse from screenshots |
| --- | --- | --- | --- | --- |
| bad/fall-through-comment-only | reject | reject | reject | reject |
| bad/fall-through-freeze | reject | reject | reject | reject |
| bad/fall-through-hide-player | reject | reject | accept | reject |
| bad/fall-through-lower-floor | reject | reject | reject | accept |
| bad/fall-through-sink-player | reject | reject | accept | accept |
| bad/layering-hide-trees | reject | reject | accept | reject |
| bad/sinking-overcorrected | reject | reject | reject | reject |
| good/layering/v1 | accept | accept | accept | accept |
| good/layering/v2 | accept | accept | accept | accept |
| good/missing-texture/v1 | accept | accept | accept | accept |
| good/missing-texture/v2 | accept | accept | accept | accept |
| good/physics-fall-through/v1 | accept | accept | accept | accept |
| good/physics-fall-through/v2 | accept | accept | accept | accept |
| good/sinking/v1 | accept | accept | accept | reject |
| good/sinking/v2 | accept | accept | accept | reject |
