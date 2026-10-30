# Evaluation plan

What we measure, on which cases, so the numbers in the video and the README can be rerun by anyone.
Owner: Sean. Status: draft for the team to review by noon on Tuesday, October 27.

## The question the benchmark answers

Does Expectrail catch and fix visual regressions that a coding agent given screenshots would miss
or fix wrongly? Each case runs under three conditions with the same repair budget, and every
candidate fix is judged by the same independent verifier:

| Condition | What it gets |
| --- | --- |
| Existing checks | The game's own build passing; it has no tests, so every seeded bug passes this condition. This row shows the gap. |
| Muse Code with screenshots | The failing frames, the route, the logs and the instruction in plain English. No structured checks. |
| Expectrail | The same, plus structured test specs, SAM 3.1 observations and the evaluator's verdict. |

## Bug families (first wave)

Four families, matched with clean runs. A variant is a patch in `bugs/`
(seeded by Timo); the clean run is the same route with no patch.

| Family | Test specs | Development variants (in `bugs/`) | Held out |
| --- | --- | --- | --- |
| physics-fall-through | `specs/player-stays-above-ground.json` (never-crosses against the level's ground line: position log, plus SAM's robot box when SAM is on) and `specs/player-always-visible.json` (SAM) | v1 the player's collision mask drops the ground layer; v2 the ground tiles lose their collision layer | v5, v6 |
| sinking (added Oct 28) | `specs/player-stays-above-ground.json` | v1 the player's collision shape sits too high, so it rests inside the ground; v2 the sprite is drawn too low (only the SAM hybrid sees it) | v3, v4 |
| missing-texture | `specs/coins-visible.json` (visible in every frame, SAM) | v1 the coin texture points to a missing file and has lost its UID; v2 the coin texture is cleared | v5, v6 |
| layering | `specs/player-always-visible.json` (visible in every frame, SAM) | v1 the player's z index drops behind the level art; v2 the player's sprite gets a negative z index | v5, v6 |

The held-out variants and routes are described only in the private repository; their mechanisms
are not written down here. The first held-out variants of the three original families (v3 and v4)
were described in this file from Oct 26 to Oct 28, so they stay in git history; they are retired
from the benchmark and replaced by v5 and v6, written fresh on Oct 28 and never described here. SAM 3.1 does not see the ground in this game's art, which is why the
ground line comes from the level itself (docs/sam.md).

The playbook's original layering bug (the HUD drawn behind the background) does not fit this game:
its only HUD, the coin counter, is inside the pause menu and is not on screen during play. Text
overflow, softlock and motion jitter wait until after Gate 2.

**Held out** means two things, both kept in the private repository `seanudeke/Nightshift-heldout`
and never in this one:

- **Held-out variants** (the two active variants of each family in the table) are a
  generalization set. We build and tune Expectrail on v1 and v2 only; the held-out variants run
  once, in the benchmark, and their results are reported separately. They never appear in a repair
  request or on the fixer's machine before then. Detection on them (would the verifier reject a
  candidate that leaves the bug in place) is measured by the `heldout-bench` mode of the SAM probe
  workflow (`agents/heldout_bench.py`), which publishes only each variant's id and verdicts.
- **Held-out routes** guard each candidate fix. The verifier replays the seeded bug plus the
  candidate on routes the fixer has never seen, and requires the visual spec and the gameplay
  check to pass there too. A fix tuned to the smoke route (for example one that only works on its
  exact timing) fails here. The verifier reads the set from `EXPECTRAIL_HELDOUT_DIR`; CI fetches it
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

## How the fix matrix runs

`agents/matrix.py`, run by hand through the **Fix matrix** workflow, takes each development
variant under each condition. Both conditions get the same files: five screenshots of the bugged
run at fixed frames (0, 30, 60, 90, 119, never chosen by a verdict), the route and the run's log,
the same three attempts and the same editable globs (`player/**`, `level/**` and
`game_singleplayer.tscn`, since layering v1 lives in the game scene). The screenshots condition
gets the expected behaviour in plain English and, after a rejected attempt, only that it did not
work. The Expectrail condition also gets the repair request (spec, verdict, evidence) and the
verifier's reasons, and opens a repair only when its own check caught the bug. Every candidate is
judged by the same verifier with SAM on and the private routes mounted; Muse Code runs only inside
bubblewrap there. "Existing checks" needs no run: the game has no tests, so it catches nothing.

The held-out variants go through the same matrix once, after the code freeze (`set: held-out`).
Only ids, outcomes and per-attempt decisions leave the runner for them: a candidate patch, a
verifier reason or Muse's log would describe the private bug.

## Who accepts a fix that only looks right (judge benchmark)

The fix matrix showed both conditions fix all 8 development variants, so the fix rate does not
separate them. What Expectrail is for is the judgement: would it ship a fix that only looks right?
`agents/judge_bench.py` puts 15 candidates, each with a known right answer, in front of three
judges. The 8 good candidates undo each development bug exactly. The 7 bad candidates
(`agents/fixtures/`) look fixed and are not. Five sit on fall-through v1: the fall stops but the
robot is drawn behind the level art or inside the ground; the floor's collision is moved below its
art; the robot can no longer move; or only a comment changes. The sixth pushes the sinking fix so far
the robot floats, and the seventh "fixes" layering by deleting every tree. The judges are the verifier with SAM
on, the verifier with SAM off, and Muse judging from five before and five after screenshots plus
the player's one-line report, inside bubblewrap. Results and both runs are in `bench/judge/`.

Twice, live (runs 40936362830 and 40943391994):

| Judge | Good fixes accepted | Bad fixes accepted |
| --- | --- | --- |
| Expectrail, SAM on | 8 of 8, both runs | 0 of 7, both runs |
| Expectrail, SAM off | 8 of 8, both runs | 3 of 7, both runs |
| Muse from screenshots | 6 of 8, then 7 of 8 | 2 of 7, both runs |

What the reasons show (second run):

- Without SAM the verifier sees the engine, not the picture, so it passes the hidden player, the
  sunk player and the hidden trees. SAM's checks reject all three.
- Muse accepts the lowered floor and the sunk player ("player stays in view, on ground"): five
  frames carry no reference for where the ground should be. It rejects real sinking fixes because
  it reads a normal jump as the robot floating.
- The floating robot fails `player-stays-above-ground` in both modes: the spec holds the feet within
  20 px of the ground, so floating fails as well as sinking.
- Expectrail does not notice the missing trees. It rejects that candidate because the player is
  still drawn at z_index -3, behind the grass, bushes and tiles, so `player-always-visible` fails.
  Muse rejects it because the trees are gone. Deleting scenery that no spec covers would pass.

Limits: the bad candidates were written by us, and three of them (hide, sink, lower the floor) are
cases the verifier was built to reject, so 0 of 7 shows it holds on known tricks, not on new ones.
Fifteen cases is small. The judges do not see the same evidence: that is the comparison we claim
(what each would accept from what it is given), not an equal-information test.

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

Sixteen variants (eight development, eight held out, across four families) and their clean runs,
three conditions, up to three repair attempts each. Each run renders 120 frames; SAM 3.1 sees a
sample: every fourth frame by default (`EXPECTRAIL_SAM_EVERY`), refined to the exact frame when a
sample fails, and every remaining frame confirmed before a pass, so a pass still rests on all 120.
Decided October 28, after the first live measurements.
