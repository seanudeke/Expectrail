---
tracker_id: ""
type: epic
title: "The verdict with SAM on is one SAM saw on every frame"
parent: initiative-sam-vision
covers: ["R1", "R2", "R3", "R4", "R5", "R6", "R9", "R10"]
sources: ["_bmad-output/initiative-sam-vision/initiative-sam-vision.md"]
companions: []
after: []
refined: true
risk: medium
---

# The verdict with SAM on is one SAM saw on every frame

## Description

The adapter, the two SAM specs, the engine and hybrid ground checks and the needs-review paths are
built and live on `main`. What is missing is the score margin in the verdict, the two stale doc
claims, and an end-to-end run on `main` that shows the real fix accepted and the hide-the-player
fixture rejected with SAM on.

## Outcome

For Sean, a pass means SAM looked at every frame of the candidate, the clean game and every private
route, and a drop in how well SAM sees our art shows up in the verdict instead of passing quietly.

## Requirements

1. **Frames become observations** (R1, parent R1)
   **Given** a run with captured frames and an approved spec, **When** the adapter runs, **Then** the
   observations document holds one box and confidence per object per frame, **And** every frame in the
   window is judged or explicitly unjudged.

2. **The approved prompts hold on our art** (R2, parent R2)
   **Given** a clean run, **When** both SAM specs are judged, **Then** the player and the coins are
   found in 120 of 120 frames each, **And** every found box scores at or above 0.5.

3. **The fall-through verdict matches the screen** (R3, parent R3)
   **Given** the recorded fall-through v1 and v2 and the clean run, **When** the ground spec is
   evaluated, **Then** both bugged runs fail and the clean run passes.

4. **A pass rests on every frame** (R4, parent R4)
   **Given** a pass on the sample, **When** the document is written, **Then** every remaining frame was
   judged first and a fail names the first bad frame, **And** frames analyzed, refined and confirmed
   are recorded against frames captured.

5. **A failure is never a pass** (R5, parent R5)
   **Given** a failed, partial or unrecognised reply, a box without confidence, a non-finite number or
   missing frames, **When** the check is decided, **Then** the result is needs-review, **And** an error
   file names the reason for that replay and spec.

6. **The ground cannot be moved by the candidate** (R6, parent R6)
   **Given** a candidate that edits `level/**` and lowers the floor, **When** the ground spec is
   judged, **Then** the line comes from the unpatched game's tile polygons, **And** the candidate is
   rejected, as it is on the held-out routes.

7. **Positions stay in code** (R7, parent R9)
   **Given** any spec and replay, **When** a request is sent, **Then** the prompt is the spec's noun
   phrase with no coordinates, **And** positions and the ground line come from the level and the trace.

8. **The score margin is visible** (R8, parent R10)
   **Given** a clean run, **When** a SAM spec is judged, **Then** its minimum clean score is recorded in
   the verdict or observations document, **And** a later clean run below that mark is reported instead
   of passing quietly.

## Constraints

- C1 (parent C1): `MODEL_API_KEY` stays separate from `META_API_KEY`.
- C3 (parent C3): the cache stays outside the repo, and a verdict beyond question runs with
  `NIGHTSHIFT_SAM_CACHE=off`.
- C4 (parent C4): the ground is never taken from SAM alone.
- C5 (parent C5): pull-request CI keeps the trace provider, so no SAM check is a required PR check.

## Done when

- Each SAM spec carries its minimum clean score in the verdict or observations document, and a later
  clean run below that mark is reported rather than passed quietly.
- A SAM failure path produces needs-review with an error artifact, shown by the offline tests.
- An end-to-end run on `main` with SAM on accepts `fix-collision-mask.patch` and rejects
  `fix-but-hide-player.patch`.
- `docs/sam.md` and `docs/evaluation.md` say what the runs show: the held-out claim and the sample-rate
  line are corrected.

## Boundaries

- Not the held-out benchmark's own results: epic-held-out-bench.
- Not the adapter's request path or its cache unit: epic-video-tracking.
- Must not change: any approved spec, and the rule that a SAM failure is never a pass.

## References

- parent — `_bmad-output/initiative-sam-vision/initiative-sam-vision.md`, Requirements R1-R6, R9, R10
- verifier — `agents/verifier.py`, SAM specs, ground checks and needs-review paths
- adapter — `agents/sam_observations.py`
- specs — `specs/player-always-visible.json`, `specs/coins-visible.json`, `specs/player-stays-above-ground.json`

## Notes

- Decision (2026-10-28): 2.1 opens the epic rather than the tracer bullet. The tracer (2.3) is a live
  dispatch and waits on the SAM key that epic-held-out-bench owns; that wait is carried by 2.3's
  unknown, not by an epic-level after, so the offline stories stay ready.
- Decision (2026-10-28): the score margin is recorded verifier-side in `verdict-<spec>.json`, not in
  the observations document, which the adapter assembles and which belongs to epic-video-tracking.
- Decision (2026-10-28): R5 needs no new work; `tests/test_sam.py` already shows every SAM failure
  path as needs-review on `main`, and 2.3 re-runs it as part of its verify.
- Unknown: `agents/heldout_bench.py` imports the verifier's internals (`_ground_observations`,
  `_sam_verdicts`, `sam_specs`, `reference_surfaces`); any change here keeps that importable, or the
  benchmark breaks. Settled before the first story that touches the verifier.
