# Drawn-floor ground check, public routes

The ground check measured the robot against the floor's collision only, so a floor whose art is
drawn away from its collision was invisible to every check (held-out sinking/v4, missed until
Oct 30). The harness now renders the tile layers alone once per run and logs where they are drawn
(`levelArt` in trace.json), and the ground line is the higher of the clean level's collision and the
floor as drawn (`agents.observations.drawn_surface_under`; docs/sam.md, "The drawn floor").

This folder is the check on public material, made before it ran on the held-out set: three
floor-art bugs written for it (collision untouched in all three), and every development variant and
candidate fixture, on the four public routes. Judged as the verifier does with SAM off (position
log against the ground line). Rerun: `python3 bench/drawn-floor/check.py --out runs/drawn-floor`
(about 30 s a replay; writes `results.json`).

| Run | Collision only: fail | Collision or drawn floor: fail | Worst gap (px) |
| --- | --- | --- | --- |
| clean | 0 of 4 | 0 of 4 | 2.0 |
| dev/layering/v1 | 0 of 4 | 0 of 4 | 2.0 |
| dev/layering/v2 | 0 of 4 | 0 of 4 | 2.0 |
| dev/missing-texture/v1 | 0 of 4 | 0 of 4 | 2.0 |
| dev/missing-texture/v2 | 0 of 4 | 0 of 4 | 2.0 |
| dev/physics-fall-through/v1 | 4 of 4 | 4 of 4 | 77.2 |
| dev/physics-fall-through/v2 | 4 of 4 | 4 of 4 | 77.2 |
| dev/sinking/v1 | 4 of 4 | 4 of 4 | 28.0 |
| dev/sinking/v2 | 0 of 4 | 0 of 4 | 2.0 |
| floor/art-origin-up: the tile set's texture origin draws every tile 26 px higher | 0 of 4 | **4 of 4** | 28.0 |
| floor/art-shader-up: a shader draws the tile layer 26 px higher | 0 of 4 | **4 of 4** | 28.0 |
| floor/art-shader-down: a shader draws it 26 px lower (the robot looks like it floats) | 0 of 4 | 0 of 4 | 0.0 |
| candidate/fix-collision-mask (the real fix) | 0 of 4 | 0 of 4 | 2.0 |
| candidate/fix-but-hide-player | 0 of 4 | 0 of 4 | 2.0 |
| candidate/fix-but-sink-player | 0 of 4 | 0 of 4 | 2.0 |
| candidate/fix-and-lower-the-floor | 4 of 4 | 4 of 4 | 28.0 |
| candidate/freeze-player | 0 of 4 | 0 of 4 | 1.0 |
| candidate/fix-comment-only | 4 of 4 | 4 of 4 | 77.2 |
| candidate/fix-sinking-overcorrected | 3 of 4 | 3 of 4 | 77.2 |

Worst gap is how far the robot's feet go below the ground line, world pixels, over all routes (the
spec allows 10, which is 20 frame pixels). The drawn floor changes no verdict for any development
variant or candidate, and fails both bugs that draw the floor higher than it collides on every
route. dev/sinking/v2 (the robot's own sprite drawn low) is still the SAM hybrid's to catch; this
check measures the floor, not the robot.

Two things found on the way, both on public routes, both fixed before the held-out run: a platform
overhead whose art reached into the robot's head room (smoke) was taken for the floor, and so was
the overhanging end of a platform the robot jumped up beside (combat). Art now counts as a floor
only if it starts at most 64 px above the robot's origin, like the collision search, and reaches
down past its feet.

The grass constant, 8 px: on the clean level the art starts 1 to 10 px above the collision over all
3,648 exposed surface columns (8 at the mode), so the drawn line is the art's top lowered by 8.
