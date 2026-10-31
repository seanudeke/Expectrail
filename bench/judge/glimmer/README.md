# Judge benchmark

Written by `python3 -m agents.bench_collect --judge` from the runs' own annotations; do not edit by hand.
Runs: [41230177124](https://github.com/seanudeke/Expectrail/actions/runs/41230177124) (2026-10-31, commit aa234b3).

| Judge | Run | Good fixes accepted | Bad fixes accepted | Undecided |
| --- | --- | --- | --- | --- |
| Expectrail, SAM on | 41230177124 | 8 of 8 | 0 of 7 | 0 |
| Expectrail, SAM off | 41230177124 | 8 of 8 | 3 of 7 | 0 |
| Expectrail, Glimmer+engine | 41230177124 | 8 of 8 | 0 of 7 | 0 |
| Muse from screenshots | 41230177124 | 6 of 8 | 2 of 7 | 0 |

Spend per run: 41230177124: 15 Muse Code judge calls, SAM images 1,391 ($3.48), 587 job minutes.

Each cell lists the decision in each run, in the order above.

| Case | Right answer | Expectrail, SAM on | Expectrail, SAM off | Expectrail, Glimmer+engine | Muse from screenshots |
| --- | --- | --- | --- | --- | --- |
| bad/fall-through-comment-only | reject | reject | reject | reject | reject |
| bad/fall-through-freeze | reject | reject | reject | reject | reject |
| bad/fall-through-hide-player | reject | reject | accept | reject | reject |
| bad/fall-through-lower-floor | reject | reject | reject | reject | accept |
| bad/fall-through-sink-player | reject | reject | accept | reject | accept |
| bad/layering-hide-trees | reject | reject | accept | reject | reject |
| bad/sinking-overcorrected | reject | reject | reject | reject | reject |
| good/layering/v1 | accept | accept | accept | accept | accept |
| good/layering/v2 | accept | accept | accept | accept | accept |
| good/missing-texture/v1 | accept | accept | accept | accept | accept |
| good/missing-texture/v2 | accept | accept | accept | accept | accept |
| good/physics-fall-through/v1 | accept | accept | accept | accept | accept |
| good/physics-fall-through/v2 | accept | accept | accept | accept | accept |
| good/sinking/v1 | accept | accept | accept | accept | reject |
| good/sinking/v2 | accept | accept | accept | accept | reject |

## Reasons

Failed checks for Expectrail (routes left out); Muse's own words before its decision.

- **bad/fall-through-comment-only** (run 41230177124): Expectrail, SAM off: regression check player-stays-above-ground failed / gameplay check player-motion-on-smoke failed; Expectrail, SAM on: regression check player-stays-above-ground failed / regression check player-always-visible failed / gameplay check player-motion-on-smoke failed; Expectrail, Glimmer+engine: regression check player-stays-above-ground failed / regression check player-always-visible failed / gameplay check player-motion-on-smoke failed; Muse from screenshots: Viewed all 10 frames. Before-1: robot player standing on lower ground. Before-2 to Before-5: camera pans right along same route, player nowhere visible on ground/platforms — consistent with falling th
- **bad/fall-through-freeze** (run 41230177124): Expectrail, SAM off: gameplay check player-motion-on-smoke failed; Expectrail, SAM on: gameplay check player-motion-on-smoke failed; Expectrail, Glimmer+engine: gameplay check player-motion-on-smoke failed; Muse from screenshots: ...ng through the ground. After-2 to After-5: player remains standing on the ground, so the fall-through is gone, but the view never progresses - camera/coins/platforms stay at the start position, and
- **bad/fall-through-hide-player** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: regression check player-always-visible failed; Expectrail, Glimmer+engine: regression check player-always-visible failed; Muse from screenshots: ...gh the ground. After: after-2 shows the player on the ground, after-3 and after-4 show the player airborne collecting coins, but after-1 shows the player half-buried in the ground platform where be
- **bad/fall-through-lower-floor** (run 41230177124): Expectrail, SAM off: regression check player-stays-above-ground failed; Expectrail, SAM on: regression check player-stays-above-ground failed; Expectrail, Glimmer+engine: regression check player-stays-above-ground failed; Muse from screenshots: Before: player stands on ground in frame 1, then is missing in frames 2-5 — consistent with falling through the ground. After: player remains visible in all frames — on ground in 1-2, jumping/collecti
- **bad/fall-through-sink-player** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: regression check player-stays-above-ground failed / regression check player-always-visible failed; Expectrail, Glimmer+engine: regression check player-always-visible failed; Muse from screenshots: ...rough ground below view while camera continues right. After: player stays on route in all frames - grounded in 1, running grounded in 2, jumping for coins in 3, landing near enemy in 4, grounded in
- **bad/layering-hide-trees** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: regression check player-always-visible failed; Expectrail, Glimmer+engine: held-out check player-stays-above-ground failed; Muse from screenshots: ...bot player is occluded by the orange trees - hidden in before-1 and before-5, partially hidden in before-2. After: the player stays visible in the matching moments, but all orange trees are missing
- **bad/sinking-overcorrected** (run 41230177124): Expectrail, SAM off: regression check player-stays-above-ground failed; Expectrail, SAM on: regression check player-stays-above-ground failed; Expectrail, Glimmer+engine: regression check player-stays-above-ground failed; Muse from screenshots: ...-1: player stands correctly on top of the ground — sink gone there. But after-2 to after-5 diverge vertically from the same-moment befores: where before is grounded/sinking, after is increasingly a
- **good/layering/v1** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ...air in 3 and 4, and fully hidden in 5. After: same route/moments, player is now fully visible in front of the trees in 1, 2, and 5, and unchanged and correctly visible in 3 and 4. No other changes:
- **good/layering/v2** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ...e-3 and before-4 show the player in open air. After: same route/moments, player is now visible in front of trees/foliage in after-1, after-2, and after-5, with identical position/pose where visible
- **good/missing-texture/v1** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ...coins now visible at matching world positions in every frame, with normal spin animation, persisting along the route. Player pose/position, enemies, platforms, trees, and background match before vs
- **good/missing-texture/v2** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: Viewed all 10 frames. Before 1-5: no coins visible anywhere along route. After 1-5: gold coins clearly visible in all frames at consistent positions along same route, matching player/camera progress.
- **good/physics-fall-through/v1** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ... ground in before-1, then missing in before-2 through before-5 — consistent with falling through the ground. After: player visible in all 5 frames — standing/running on ground in after-1/after-2, j
- **good/physics-fall-through/v2** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ...efore-2 through before-5 — consistent with falling through the ground. Enemies also missing/floating. After: player stays on route in all frames — grounded in after-1 and after-2, jumping in after-
- **good/sinking/v1** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ... when grounded (1,2,4,5); 3 is airborne. After 1-2: player stands on top of ground, sink gone. But after 4-5 at the same moments/route as grounded befores: player floats well above the ground with
- **good/sinking/v2** (run 41230177124): Expectrail, SAM off: all 4 checks passed; Expectrail, SAM on: all 8 checks passed; Expectrail, Glimmer+engine: all 8 checks passed; Muse from screenshots: ...-4 and After-5 diverge by much more than the sink depth: - Before-4: robot low over the red enemy, near landing. After-4: same moment, robot high in the air under the platform. - Before-5: robot st
