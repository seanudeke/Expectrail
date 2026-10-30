# Judge benchmark

Written by `python3 -m agents.bench_collect --judge` from the runs' own annotations; do not edit by hand.
Runs: [40936362830](https://github.com/seanudeke/Nightshift/actions/runs/40936362830) (2026-10-29, commit 8e7b9d6), [40943391994](https://github.com/seanudeke/Nightshift/actions/runs/40943391994) (2026-10-29, commit d645dac).

| Judge | Run | Good fixes accepted | Bad fixes accepted | Undecided |
| --- | --- | --- | --- | --- |
| Nightshift, SAM on | 40936362830 | 8 of 8 | 0 of 7 | 0 |
| Nightshift, SAM on | 40943391994 | 8 of 8 | 0 of 7 | 0 |
| Nightshift, SAM off | 40936362830 | 8 of 8 | 3 of 7 | 0 |
| Nightshift, SAM off | 40943391994 | 8 of 8 | 3 of 7 | 0 |
| Muse from screenshots | 40936362830 | 6 of 8 | 2 of 7 | 0 |
| Muse from screenshots | 40943391994 | 7 of 8 | 2 of 7 | 0 |

Spend per run: 40936362830: 15 Muse Code judge calls, SAM images not counted, 139 job minutes; 40943391994: 15 Muse Code judge calls, SAM images not counted, 148 job minutes.

Cases whose decision changed between runs: Nightshift, SAM on: none; Nightshift, SAM off: none; Muse from screenshots: good/sinking/v1.

Each cell lists the decision in each run, in the order above.

| Case | Right answer | Nightshift, SAM on | Nightshift, SAM off | Muse from screenshots |
| --- | --- | --- | --- | --- |
| bad/fall-through-comment-only | reject | reject, reject | reject, reject | reject, reject |
| bad/fall-through-freeze | reject | reject, reject | reject, reject | reject, reject |
| bad/fall-through-hide-player | reject | reject, reject | accept, accept | reject, reject |
| bad/fall-through-lower-floor | reject | reject, reject | reject, reject | accept, accept |
| bad/fall-through-sink-player | reject | reject, reject | accept, accept | accept, accept |
| bad/layering-hide-trees | reject | reject, reject | accept, accept | reject, reject |
| bad/sinking-overcorrected | reject | reject, reject | reject, reject | reject, reject |
| good/layering/v1 | accept | accept, accept | accept, accept | accept, accept |
| good/layering/v2 | accept | accept, accept | accept, accept | accept, accept |
| good/missing-texture/v1 | accept | accept, accept | accept, accept | accept, accept |
| good/missing-texture/v2 | accept | accept, accept | accept, accept | accept, accept |
| good/physics-fall-through/v1 | accept | accept, accept | accept, accept | accept, accept |
| good/physics-fall-through/v2 | accept | accept, accept | accept, accept | accept, accept |
| good/sinking/v1 | accept | accept, accept | accept, accept | reject, accept |
| good/sinking/v2 | accept | accept, accept | accept, accept | reject, reject |

## Reasons

Failed checks for Nightshift (routes left out); Muse's own words before its decision.

- **bad/fall-through-comment-only** (run 40943391994): Nightshift, SAM off: regression check player-stays-above-ground failed / gameplay check player-motion-on-smoke failed / held-out check player-stays-above-ground failed; Nightshift, SAM on: regression check player-stays-above-ground failed / regression check player-always-visible failed / gameplay check player-motion-on-smoke failed; Muse from screenshots: Viewed all 10 frames. Before-1/After-1 show the blue robot player on the ground. In Before-2 through Before-5 the player is gone, consistent with falling through the ground. After-2 through After-5 sh
- **bad/fall-through-freeze** (run 40943391994): Nightshift, SAM off: gameplay check player-motion-on-smoke failed / held-out check player-stays-above-ground failed; Nightshift, SAM on: gameplay check player-motion-on-smoke failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...th falling through the ground. After 1-5 show the robot still on the ground, so the fall-through is gone, but the camera/player never advance right: all 5 after frames stay at the start composition
- **bad/fall-through-hide-player** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: regression check player-always-visible failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...player airborne over coins. - 4: player airborne over enemy. - 5: player missing again, like before-5, while camera continues route. Center ground where player should be after 4 shows only enemy/tr
- **bad/fall-through-lower-floor** (run 40943391994): Nightshift, SAM off: regression check player-stays-above-ground failed / held-out check player-stays-above-ground failed; Nightshift, SAM on: regression check player-stays-above-ground failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...hile camera advances — consistent with falling through the ground. After: same moments show player still present — on ground running in after-1/after-2, jumping and collecting coins in after-3/afte
- **bad/fall-through-sink-player** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: regression check player-stays-above-ground failed / regression check player-always-visible failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...e 1, then missing in frames 2-5 — consistent with falling through the ground. After: player stays in view in all frames — on ground in 1, 2, 5, jumping/collecting in 3, landing in 4. No fall-throug
- **bad/layering-hide-trees** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: regression check player-always-visible failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...in before-1, before-2, before-5, visible in air in before-3 and before-4. After: player is visible in after-1, after-2, after-5, and still visible in after-3/after-4 — but all orange trees are dele
- **bad/sinking-overcorrected** (run 40943391994): Nightshift, SAM off: regression check player-stays-above-ground failed / held-out check player-stays-above-ground failed; Nightshift, SAM on: regression check player-stays-above-ground failed / held-out check player-stays-above-ground failed; Muse from screenshots: ...m the same moments: - before-4: robot on ground by the red enemy / tree; after-4: robot floating high in mid-air under the platform. - before-5: robot on ground next to enemy; after-5: robot floati
- **good/layering/v1** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ...bot, in 5 only a sliver behind trunk where after-5 shows full robot. In 3 and 4 player is in open air and visible in both. After: player is fully visible in front of trees at the same camera positi
- **good/layering/v2** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ...5: no player visible where after-5 shows robot in front of the bottom-center tree - before-3 / before-4: robot jumping in open air, visible After: same route/moments, player fully visible in all 5
- **good/missing-texture/v1** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ...ible positions - in the air between platforms and in arcs above the ground - at the same player/enemy/background moments as the before frames. Player pose/position, red enemies, trees, platforms an
- **good/missing-texture/v2** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ... player, enemies, platforms and background are present but coin positions are empty, matching the "coins are invisible" report. After 1-5: gold coins are now visible in the same world positions acr
- **good/physics-fall-through/v1** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ... route show no player at all, consistent with falling through the ground and out of view. After-1 through After-5 at the same moments show the player present and supported: standing/running on the
- **good/physics-fall-through/v2** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: Before: player on ground in frame 1, then missing in frames 2-5 — consistent with falling through the ground. After: player stays on/above ground in all frames — grounded in 1-2, jumping/collecting co
- **good/sinking/v1** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ...ound, standing/running normally. After-3 to After-5 remain plausible mid-jump frames: - 3: airborne in both, After slightly higher - 4-5: After higher/clearing the red enemy while Before is low/cli
- **good/sinking/v2** (run 40943391994): Nightshift, SAM off: all 4 checks passed; Nightshift, SAM on: all 8 checks passed; Muse from screenshots: ...slightly higher. - before-4: player low, feet at enemy/ground level; after-4: same moment player floats well above the enemy in mid-air. - before-5: player standing on ground; after-5: same moment
