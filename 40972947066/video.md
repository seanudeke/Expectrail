# SAM 3.1: one video per run against one image per frame

Every frame of each public run, both ways. A spec row differs when its verdict or any frame's own verdict differs.

| Run | Spec | Images | Video | Frames that differ | Images ($) | Video ($) |
| --- | --- | --- | --- | --- | --- | --- |
| layering_v1 | player-always-visible | fail | fail | 20 | 0.60 | 0.048 |
| layering_v1 | coins-visible | pass | pass | 0 | 0.60 | 0.048 |
| layering_v2 | player-always-visible | fail | fail | 20 | 0.00 | 0.048 |
| layering_v2 | coins-visible | pass | pass | 0 | 0.00 | 0.048 |
| missing-texture_v1 | player-always-visible | pass | pass | 0 | 0.60 | 0.048 |
| missing-texture_v1 | coins-visible | fail | fail | 0 | 0.60 | 0.048 |
| missing-texture_v2 | player-always-visible | pass | pass | 0 | 0.00 | 0.048 |
| missing-texture_v2 | coins-visible | fail | fail | 0 | 0.00 | 0.048 |
| physics-fall-through_v1 | player-always-visible | fail | fail | 1 | 0.60 | 0.048 |
| physics-fall-through_v1 | coins-visible | pass | pass | 0 | 0.60 | 0.048 |
| physics-fall-through_v2 | player-always-visible | fail | fail | 1 | 0.56 | 0.048 |
| physics-fall-through_v2 | coins-visible | pass | pass | 0 | 0.56 | 0.048 |
| sinking_v1 | player-always-visible | fail | pass | 11 | 0.56 | 0.048 |
| sinking_v1 | coins-visible | pass | pass | 0 | 0.56 | 0.048 |
| sinking_v2 | player-always-visible | fail | pass | 11 | 0.17 | 0.048 |
| sinking_v2 | coins-visible | pass | pass | 0 | 0.17 | 0.048 |

Total at list price: images $3.09, video $0.38.
