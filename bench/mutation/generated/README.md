Recorded from runs 41268023631, 41323827584, 41323829361 by `python3 -m agents.mutation_collect`. Actual SAM spend: 15,862 images, $39.66 at list price.

# Mutation bench

Public checks only. A survivor is a finding, not a CI failure. Only a check that ran and failed counts as a catch. Registration `719eb1e2c049b374aa0b9161e0a3c96f159a964b5be2c28a0731c9cc753061ab`.

Mutation score, weighted by each class's estimated decided mutants: **0.9%**, covering 100% of the estimated visible mutants of the sampled classes (classes with no score: boolean; classes never sampled: none).

Over the sample as drawn: 13.0% (10 of 77 decided bad cases caught). The sample's class counts were set by hand, so this figure depends on them and is not a score for the whole game.

Good cases accepted: 0.

| Outcome | Cases |
| --- | --- |
| caught-cheap | 5 |
| caught-sam | 5 |
| survived | 67 |
| undecided | 0 |
| crash | 0 |
| error | 0 |
| awaiting-sam | 0 |

Unlabelled, left out of the score: 0. No-op candidates: 0. Equivalent, dropped with a reason: 73.

Of 150 sampled: 77 judged, 73 equivalent, 0 missing, 0 not in the manifest.

## How the sample stands to the game

Method: stratified. Short of the plan by 0.

| Class | Mutants in the game | Sampled | Equivalent | Decided | Estimated decided | Score |
| --- | --- | --- | --- | --- | --- | --- |
| numeric | 2642 | 70 | 25 | 45 | 1698.4 | 0.0% |
| boolean | 1 | 1 | 1 | 0 | 0.0 | - |
| collision-bit | 65 | 30 | 27 | 3 | 6.5 | 66.7% |
| code | 19 | 19 | 5 | 14 | 14.0 | 35.7% |
| resource-path | 65 | 30 | 15 | 15 | 32.5 | 20.0% |

## Per class

| | Score | Caught, cheap | Caught, SAM only | Survived | Undecided | Crash | Error | SAM images, tiered | SAM images, full run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| code | 35.7% | 4 | 1 | 9 | 0 | 0 | 0 | 1946 | 2754 |
| collision-bit | 66.7% | 1 | 1 | 1 | 0 | 0 | 0 | 114 | 338 |
| numeric | 0.0% | 0 | 0 | 45 | 0 | 0 | 0 | 9128 | 9128 |
| resource-path | 20.0% | 0 | 3 | 12 | 0 | 0 | 0 | 3085 | 3085 |

## Which checks catch what

| Check | Cases it failed on |
| --- | --- |
| cheap gameplay/player-motion-on-smoke | 3 |
| engine-record enemies-stay-up | 1 |
| engine-record facing-follows-motion | 1 |
| sam gameplay/player-motion-on-smoke | 3 |
| sam regression/coins-visible | 2 |
| sam regression/player-always-visible | 3 |

## Agreement with the cheap tier

5 cheap rejections also judged by SAM's own checks: 0 agree, 5 disagree, 0 undecided.

## Disagreements

- code:player/player.gd:11:sign.TERMINAL_VELOCITY
- code:player/player.gd:43:compare.0
- code:player/player.gd:9:scale.JUMP_VELOCITY
- code:player/player.gd:9:sign.JUMP_VELOCITY
- collision-bit:enemy/enemy.tscn:253:collision_mask.4

## Vision-only wins

- collision-bit:enemy/enemy.tscn:252:collision_layer.1
- resource-path:gui/pause_menu.tscn:4:missing
- code:player/player.gd:56:compare.0
- resource-path:level/coin.tscn:3:missing
- resource-path:level/coin.tscn:5:missing

## Blind spots

- code:enemy/enemy.gd:41:compare.0
- code:enemy/enemy.gd:52:compare.0
- collision-bit:enemy/enemy.tscn:253:collision_mask.0
- numeric:level/background/parallax_background.tscn:122:position.x-
- numeric:level/background/parallax_background.tscn:23:position.x+
- numeric:level/level.tscn:102:scale.x+
- numeric:level/level.tscn:1033:scale.x-
- numeric:level/level.tscn:1110:scale.x-
- numeric:level/level.tscn:1157:position.x+
- numeric:level/level.tscn:1192:scale.x+
- numeric:level/level.tscn:1220:position.x-
- code:enemy/enemy.gd:53:compare.0
- numeric:level/level.tscn:1242:position.x-
- numeric:level/level.tscn:1330:position.y+
- numeric:level/level.tscn:1579:position.x+
- numeric:level/level.tscn:228:scale.y+
- numeric:level/level.tscn:248:position.x-
- numeric:level/level.tscn:263:scale.y-
- numeric:level/level.tscn:298:scale.x-
- numeric:level/level.tscn:304:position.x-
- numeric:level/level.tscn:354:scale.y+
- numeric:level/level.tscn:365:z_index+
- code:enemy/enemy.gd:9:scale.WALK_SPEED
- numeric:level/level.tscn:515:scale.x-
- numeric:level/level.tscn:536:scale.y+
- numeric:level/level.tscn:550:scale.y-
- numeric:level/level.tscn:613:scale.y+
- numeric:level/level.tscn:640:position.x-
- numeric:level/level.tscn:641:scale.y+
- numeric:level/level.tscn:647:position.x-
- numeric:level/level.tscn:648:scale.x-
- numeric:level/level.tscn:654:position.x+
- numeric:level/level.tscn:661:position.y+
- code:enemy/enemy.gd:9:sign.WALK_SPEED
- numeric:level/level.tscn:662:scale.x-
- numeric:level/level.tscn:669:scale.y-
- numeric:level/level.tscn:683:scale.y-
- numeric:level/level.tscn:696:position.y-
- numeric:level/level.tscn:914:scale.x-
- numeric:level/level.tscn:956:scale.y-
- numeric:level/level.tscn:962:position.x-
- numeric:level/level.tscn:963:scale.y+
- numeric:level/level.tscn:991:scale.x-
- numeric:level/level.tscn:997:position.x+
- code:player/player.gd:33:compare.0
- numeric:level/level.tscn:998:scale.y-
- numeric:level/platforms/platform.tscn:118:scale.y-
- numeric:level/platforms/platform.tscn:46:scale.y-
- numeric:level/platforms/platform.tscn:66:position.y+
- numeric:level/platforms/platform.tscn:87:position.y+
- numeric:level/platforms/platform.tscn:95:scale.y+
- numeric:player/player.tscn:204:position.x-
- resource-path:enemy/enemy.tscn:7:missing
- resource-path:level/background/parallax_background.tscn:4:missing
- resource-path:level/level.tscn:12:missing
- resource-path:level/level.tscn:13:missing
- resource-path:level/level.tscn:15:missing
- resource-path:level/level.tscn:18:missing
- resource-path:level/level.tscn:20:missing
- resource-path:level/level.tscn:4:missing
- resource-path:level/platforms/platform.tscn:10:missing
- resource-path:level/platforms/platform.tscn:4:missing
- code:player/player.gd:65:compare.0
- resource-path:level/platforms/platform.tscn:5:missing
- resource-path:level/platforms/platform.tscn:7:missing
- code:player/player.gd:70:compare.0
- code:player/player.gd:7:scale.WALK_SPEED

## SAM images

Spent 15862: 480 judging the clean game once, 14273 on what the cheap tier passed, 1032 on the agreement check, 77 on the pre-run check. A full SAM run, measured on 77 of 77 cases: 15305.
