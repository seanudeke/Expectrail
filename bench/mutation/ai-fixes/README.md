# Mutation bench, Part 3: AI-written fixes on generated bugs

Recorded from run 41330361829. Expectrail accepted a candidate on 10 of 10 generated bugs, 10 of them labelled good by the oracle (0 with none accepted, 0 needing review, 0 errors).

Of 10 candidates, the oracle labelled 10 good, 0 bad and 0 unknown, on routes the judge does not use.

| Count | Candidates |
| --- | --- |
| Natural catches | 0 |
| False accepts | 0 |
| False rejects | 0 |

SAM images: 250 ($0.62), including 240 judging the clean game once. Muse Code does not report its use per run.

| Case | Attempt | Source | Decision | Label | Public check | Muse from screenshots |
| --- | --- | --- | --- | --- | --- | --- |
| code:player/player.gd:11:sign.TERMINAL_VELOCITY | 1 | muse | accept | good | pass | reject |
| code:player/player.gd:43:compare.0 | 1 | muse | accept | good | pass | accept |
| code:player/player.gd:56:compare.0 | 1 | muse | accept | good | pass | accept |
| code:player/player.gd:9:scale.JUMP_VELOCITY | 1 | muse | accept | good | pass | reject |
| code:player/player.gd:9:sign.JUMP_VELOCITY | 1 | muse | accept | good | pass | reject |
| collision-bit:enemy/enemy.tscn:252:collision_layer.1 | 1 | muse | accept | good | pass | reject |
| collision-bit:enemy/enemy.tscn:253:collision_mask.4 | 1 | muse | accept | good | pass | accept |
| resource-path:gui/pause_menu.tscn:4:missing | 1 | muse | accept | good | pass | reject |
| resource-path:level/coin.tscn:3:missing | 1 | muse | accept | good | pass | accept |
| resource-path:level/coin.tscn:5:missing | 1 | muse | accept | good | pass | accept |
