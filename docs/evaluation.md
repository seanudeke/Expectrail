# Evaluation plan

What we measure, on which cases, so the numbers in the video and the README can be rerun by anyone.
Owner: Sean. Status: draft for the team to review by noon on Tuesday, October 27.

## The question the benchmark answers

Does Pixel Proof catch and fix visual regressions that a coding agent given screenshots would miss
or fix wrongly? Each case runs under three conditions with the same repair budget, and every
candidate fix is judged by the same independent verifier:

| Condition | What it gets |
| --- | --- |
| Existing checks | The game's own build passing; it has no tests, so every seeded bug passes this condition. This row shows the gap. |
| Muse Code with screenshots | The failing frames, the route, the logs and the instruction in plain English. No structured checks. |
| Pixel Proof | The same, plus structured test specs, SAM 3.1 observations and the evaluator's verdict. |

## Bug families (first wave)

Three families, four variants each, matched with clean runs. A variant is a patch in `bugs/`
(seeded by Timo); the clean run is the same route with no patch. Mechanisms marked "to verify" are
candidates until a run shows the symptom.

| Family | Test spec | Variants (v1 to v4) | Held out |
| --- | --- | --- | --- |
| physics-fall-through | `specs/player-stays-above-ground.json` (never-crosses) | v1 player collision mask drops the ground layer (done); v2 the ground tiles lose their collision layer (to verify); v3 the ground's collision layer moves to a layer the player ignores (to verify); v4 the player's collision shape shrinks to nothing (to verify) | v3, v4 |
| missing-texture | `specs/coins-are-visible.json` (visible, 90% of frames) | v1 the coin's texture path points to a missing file; v2 the coin texture is cleared; v3 the coin sprite's frame grid is wrong so it draws an empty cell; v4 the coin is fully transparent (all to verify) | v3, v4 |
| layering | `specs/player-is-visible.json` (visible, every frame) | v1 the player's z index drops below the level art; v2 the player stops using relative z and sits below the background; v3 the background moves in front of the player; v4 the tile layer moves in front of the player (all to verify) | v3, v4 |

The playbook's original layering bug (the HUD drawn behind the background) does not fit this game:
its only HUD, the coin counter, is inside the pause menu and is not on screen during play. Text
overflow, softlock and motion jitter wait until after Gate 2.

**Held out** means two things, both kept in the private repository `seanudeke/Nightshift-heldout`
and never in this one:

- **Held-out variants** (v3 and v4 of each family) are a generalization set. We build and tune
  Pixel Proof on v1 and v2 only; v3 and v4 run once, in the benchmark, and their results are
  reported separately. They never appear in a repair request or on the fixer's machine before then.
- **Held-out routes** guard each candidate fix. The verifier replays the seeded bug plus the
  candidate on routes the fixer has never seen, and requires the visual spec and the gameplay
  check to pass there too. A fix tuned to the smoke route (for example one that only works on its
  exact timing) fails here. The verifier reads the set from `PIXELPROOF_HELDOUT_DIR`; CI fetches it
  with the `HELDOUT_TOKEN` secret and never uploads held-out frames or traces as artifacts. Without
  the set (offline runs, forks) the check falls back to an interim fixture, labeled
  `interim-fixture` in the verification's suite provenance.

**Clean controls:** each family's spec must pass on the clean route. A spec that fails a clean run
is a false alarm and counts against us, not a bug.

## Ground truth

The harness records the player's true position every tick (`trace.json`), so for the physics and
layering families we know what really happened without trusting a model:

- a fall-through is real when the player's y keeps rising past the ground's y (in the clean smoke
  route the player never goes below y = 640; with v1 it reaches y = 1922);
- every seeded variant is a known bug, and every clean run is a known non-bug.

That gives each verdict a label, so "defects caught" and "false alarms" are measured, not judged by
eye. The trace is the verifier's instrumentation: it is added at run time by the harness, outside
the patch the fixer writes.

## Gameplay checks (verifier side)

A fix must keep the game playable. On the smoke route, the clean game:

- moves the player about 485 units to the right (x from 90 to about 575);
- ends with the player standing on the floor;
- never puts the player below the ground.

A candidate that stops the fall by freezing the player, or by removing gravity, fails these and is
rejected even though the visual check passes. Taofeek's verifier implements them in
`agents.gameplay` from the harness/fixture `trace.json` (not SAM observations or an invented
goal). The verification check id is the opaque label `player-motion-on-smoke` (not a SAM
`reaches` assertion). Harness smoke uses `MIN_DELTA_X_HARNESS` (slack under the ~485 clean
measurement); offline fixtures use `MIN_DELTA_X_FIXTURE`. Same predicate for both.

## What we report

For each condition, across all variants and clean runs:

- defects detected out of defects tested;
- false alarms out of clean runs;
- fixes accepted by the verifier out of fixes attempted, and accepted fixes that broke something else;
- unresolved cases and why;
- wall-clock time, model calls, and total cost (API spend and compute).

Rules: report frames analyzed, not frames captured; repeated runs of the same variant are not
separate bugs; held-out results are reported separately from development results; every number on
screen comes from `bench/` and reruns with one command.

## Budget

Twelve variants and three clean runs, three conditions, up to three repair attempts each. Each run
renders 120 frames; SAM 3.1 sees a sample (for example every fourth frame, plus frames where the
picture changes), not every frame. Decide the sample rate after Zayyad's first measurements.
