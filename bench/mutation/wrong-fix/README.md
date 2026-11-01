Recorded from run 41268021760 by `python3 -m agents.mutation_collect`. Actual SAM spend: 5,473 images, $13.68 at list price.

# Mutation bench

Public checks only. A survivor is a finding, not a CI failure. Only a check that ran and failed counts as a catch. Registration `719eb1e2c049b374aa0b9161e0a3c96f159a964b5be2c28a0731c9cc753061ab`.

Mutation score: **79.5%** (31 of 39 decided bad cases caught).

Good cases accepted: 8.

| Outcome | Cases |
| --- | --- |
| caught-cheap | 7 |
| caught-sam | 24 |
| survived | 16 |
| undecided | 0 |
| crash | 0 |
| error | 0 |
| awaiting-sam | 0 |

Unlabelled, left out of the score: 0. No-op candidates: 2. Equivalent, dropped with a reason: 0.

## Per operator

| | Score | Caught, cheap | Caught, SAM only | Survived | Undecided | Crash | Error | SAM images, tiered | SAM images, full run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| behind-scenery | 100.0% | 0 | 8 | 0 | 0 | 0 | 0 | 1136 | 1136 |
| comment-only | - | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| freeze | 100.0% | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 1610 |
| hide | 100.0% | 0 | 8 | 0 | 0 | 0 | 0 | 1208 | 1208 |
| scale-to-zero | 0.0% | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| sink | 100.0% | 0 | 8 | 0 | 0 | 0 | 0 | 1232 | 1232 |

## Per case

| | Score | Caught, cheap | Caught, SAM only | Survived | Undecided | Crash | Error | SAM images, tiered | SAM images, full run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev/layering/v1 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/layering/v2 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/missing-texture/v1 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/missing-texture/v2 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/physics-fall-through/v1 | 75.0% | 0 | 3 | 2 | 0 | 0 | 0 | 447 | 447 |
| dev/physics-fall-through/v2 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/sinking/v1 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |
| dev/sinking/v2 | 80.0% | 1 | 3 | 2 | 0 | 0 | 0 | 447 | 677 |

## Which checks catch what

| Check | Cases it failed on |
| --- | --- |
| cheap gameplay/player-motion-on-smoke | 7 |
| sam gameplay/player-motion-on-smoke | 7 |
| sam regression/player-always-visible | 24 |
| sam regression/player-stays-above-ground | 8 |

## Agreement with the cheap tier

7 cheap rejections also judged by SAM's own checks: 0 agree, 7 disagree, 0 undecided.

## Disagreements

- dev/missing-texture/v1 freeze
- dev/layering/v1 freeze
- dev/missing-texture/v2 freeze
- dev/physics-fall-through/v2 freeze
- dev/sinking/v1 freeze
- dev/sinking/v2 freeze
- dev/layering/v2 freeze

## Vision-only wins

- dev/layering/v1 hide
- dev/layering/v1 sink
- dev/layering/v2 behind-scenery
- dev/missing-texture/v1 hide
- dev/missing-texture/v1 sink
- dev/missing-texture/v1 behind-scenery
- dev/missing-texture/v2 hide
- dev/missing-texture/v2 sink
- dev/missing-texture/v2 behind-scenery
- dev/physics-fall-through/v1 hide
- dev/physics-fall-through/v1 sink
- dev/physics-fall-through/v1 behind-scenery
- dev/physics-fall-through/v2 hide
- dev/physics-fall-through/v2 sink
- dev/physics-fall-through/v2 behind-scenery
- dev/sinking/v1 hide
- dev/sinking/v1 sink
- dev/sinking/v1 behind-scenery
- dev/layering/v1 behind-scenery
- dev/sinking/v2 hide
- dev/sinking/v2 sink
- dev/sinking/v2 behind-scenery
- dev/layering/v2 hide
- dev/layering/v2 sink

## Blind spots

- dev/missing-texture/v1 scale-to-zero
- dev/missing-texture/v2 scale-to-zero
- dev/physics-fall-through/v1 scale-to-zero
- dev/layering/v1 scale-to-zero
- dev/physics-fall-through/v2 scale-to-zero
- dev/sinking/v1 scale-to-zero
- dev/sinking/v2 scale-to-zero
- dev/layering/v2 scale-to-zero

## SAM images

Spent 5473: 240 judging the clean game once, 3576 on what the cheap tier passed, 1610 on the agreement check, 47 on the pre-run check. A full SAM run, measured on 31 of 47 cases: 5186.
