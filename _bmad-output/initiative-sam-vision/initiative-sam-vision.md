---
tracker_id: ""
type: initiative
title: "Every Nightshift verdict rests on what SAM saw in the captured frames"
sources: ["docs/sam.md", "docs/evaluation.md"]
companions: []
after: []
risk: medium
---

# Every Nightshift verdict rests on what SAM saw in the captured frames

## Description

Nightshift already judges a candidate fix on the game's position log and on the level's ground line.
That is blind to anything that is drawn wrong while positioned right: a hidden sprite, a missing
texture, a robot sunk to the waist. This initiative makes vision a first-class judge: SAM 3.1 reads
the captured frames, the evaluator decides the spec over its boxes in plain code, and every
acceptance rests on what is actually on screen. It starts from the working adapter and the October 28
live calibration, closes the one unmeasured part (detection on the private held-out variants), and
settles the cost and score-margin questions with numbers.

## Outcome

For Sean as the reviewer, a candidate that passes every check is one whose picture SAM saw on every
frame, on the candidate, the clean game and every private route; a wrong picture fails or goes to
review, never silently passes.

## Requirements

1. **Frames become observations** (docs/sam.md, Status and Where SAM runs)
   **Given** a run with captured frames and an approved spec,
   **When** the adapter runs against `sam-3.1`,
   **Then** it writes an observations document holding one box and one confidence per spec object per
   frame,
   **And** every captured frame in the window is either judged or explicitly unjudged.

2. **The approved prompts hold on our art** (docs/sam.md, What the live probes found)
   **Given** a clean run,
   **When** `player-always-visible` and `coins-visible` are judged,
   **Then** the player is found in 120 of 120 frames and the coins in 120 of 120,
   **And** every found box scores at or above the 0.5 threshold.

3. **The fall-through verdict matches the screen** (docs/sam.md, What the live probes found)
   **Given** the recorded fall-through runs v1 and v2 and the clean run,
   **When** `player-stays-above-ground` is evaluated,
   **Then** both bugged runs fail and the clean run passes.

4. **A pass rests on every frame** (docs/sam.md, How it looks at fewer frames)
   **Given** a pass on the sample,
   **When** the observation document is written,
   **Then** every remaining frame of the window was judged before the pass, and a fail names the
   first bad frame exactly,
   **And** the document records frames analyzed, refined and confirmed against frames captured.

5. **A failure is never a pass** (docs/sam.md, When SAM fails)
   **Given** a failed, partial or unrecognised SAM reply, a box without confidence, a non-finite
   number, missing frames or no frames at all,
   **When** the check is decided,
   **Then** the result is needs-review,
   **And** an error file names the reason for that replay and spec.

6. **The ground cannot be moved by the candidate** (docs/sam.md, The ground, from the level)
   **Given** a candidate that edits `level/**` and lowers the floor under the robot,
   **When** the ground spec is judged,
   **Then** the ground line comes from the unpatched game's tile polygons,
   **And** the candidate is rejected, as it is on the held-out routes.

7. **Held-out detection is measured** (docs/evaluation.md, Held out)
   **Given** each active private held-out variant and the clean game,
   **When** the held-out benchmark runs,
   **Then** each variant is reported caught or not caught over the smoke route and every private
   route, and the clean game is reported as a false alarm or not,
   **And** only variant ids, counts and verdicts leave the verifier machine.

8. **Video tracking earns its place** (docs/sam.md, Not built yet)
   **Given** the per-frame path and the clip path,
   **When** both are measured on the same runs,
   **Then** a recorded decision names the cost and the tracking stability of each,
   **And** the clip path is adopted only if it wins on one of them without losing frame-level
   precision.

9. **Positions stay in code** (docs/sam.md, Where SAM runs; Box and point prompts from the engine)
   **Given** any spec and any replay,
   **When** a request is sent to SAM,
   **Then** the prompt is the spec's noun phrase and carries no coordinates,
   **And** the ground line and object positions are computed from the level and the trace.

10. **The score margin is visible** (docs/sam.md, What is still open)
    **Given** a clean run,
    **When** a SAM spec is judged,
    **Then** its minimum clean score is recorded or its floor is pinned above 0.5,
    **And** a later clean run below that mark is reported instead of passing quietly.

## Constraints

- C1 (docs/sam.md, Where SAM runs): `MODEL_API_KEY` stays separate from `META_API_KEY`; the overnight
  loop and `prove_live` refuse Muse Code with SAM on when it is missing or the same key.
- C2 (docs/evaluation.md, Held out): private patches, routes, frames and descriptions never leave the
  verifier machine; only ids and verdicts are published.
- C3 (docs/sam.md, The cache is verifier state): the cache lives outside the repo, and a verdict that
  must be beyond question runs with `NIGHTSHIFT_SAM_CACHE=off`.
- C4 (docs/sam.md, What the live probes found): SAM cannot see the ground in this art, so the ground
  is never taken from SAM alone.
- C5 (docs/sam.md, Status): pull-request CI has no key and keeps the trace provider, so a SAM check
  cannot be a required PR check.

## Done when

- The real fix is accepted end to end with SAM on (candidate, clean and every private route), and the
  hide-the-player fixture is rejected by `player-always-visible` there.
- All six seeded bugs fail under the approved specs, with no false alarm on the clean run.
- Every active private held-out variant has a caught or not-caught result, and the clean control has
  none reported as a catch.
- A SAM failure path produces needs-review with an error artifact, demonstrated by the offline tests.
- The minimum clean score per SAM spec is recorded or its floor is pinned, and both are above 0.5.
- A dated decision on video tracking exists, with measured cost and latency for both paths.

## Boundaries

- Out: Glimmer. A second vendor is revisitable only if SAM cannot see our art in a setup we can afford.
- Out: box and point prompts from the engine. They trade independence for recall and need a decision
  that says so.
- Out: masks beyond bounding boxes. The evaluator uses boxes, and mask tokens are already parsed and
  ignored.
- Out: changing any approved spec without Sean's approval.
- Touch point: `agents/verifier.py` — decides candidate, clean and held-out checks; owner: epic-verifier-gate.
- Touch point: `harness/godot/nightshift_harness.gd` — records ground, view and level surfaces; owner: epic-verifier-gate.
- Touch point: `.github/workflows/sam-probe.yml` — runs the `probe`, `verify` and `heldout-bench` modes; owner: epic-held-out-bench.
- Touch point: `agents/sam_observations.py` — per-frame requests, cache and the observations document; owner: epic-video-tracking.

Tracer path: adapter → observations → evaluator verdict → verifier gate → held-out benchmark.

## References

- source — `docs/sam.md`, Status; What the live probes found; The ground, from the level; How it looks
  at fewer frames; When SAM fails; Not built yet; What is still open
- source — `docs/evaluation.md`, Bug families; Held out; Budget
- verifier — `agents/verifier.py`, SAM specs and ground checks
- adapter — `agents/sam_observations.py`
- benchmark — `agents/heldout_bench.py` and PR #39 (not on `main` yet)

## Notes

- Assumption: the October 28 live numbers still describe the current art; no art or camera change has
  landed since.
- Open question: the SAM key returns HTTP 402 `billing_not_configured` since 19:08Z on Oct 28. Who owns
  the Meta billing fix, and which secret does the job resolve (`MODEL_API_KEY` or `META_API_KEY`)?
- Decision (2026-10-28): scope is the SAM vision pipeline; Glimmer stays conditional and out.
- Decision (2026-10-28): sampling is every fourth frame by default, and every remaining frame is
  confirmed before a pass.
- Decision (2026-10-28): no platform-baseline epic; the adapter, the verifier's SAM checks, the probe
  workflow and the harness's ground recording are live on `main`, so the opening epic measures the one
  unmeasured risk instead of scaffolding.
- Decision (2026-10-28): no architecture spine; the decisions several epics share (ground line,
  sampling and confirm, needs-review, separate key) are settled in `docs/sam.md` and in code.
- Decision (2026-10-28): R10's home is the verifier recording the minimum clean score per SAM spec in
  the verdict or observations document; no approved spec is edited, so the boundary holds.
- Decision (2026-10-28): the adapter is a touch point owned by epic-video-tracking; if the clip path
  wins it is implemented there, and Done when needs only the dated decision either way.
- Decision (2026-10-28): the held-out routes were probed with SAM on Oct 28 — runs 40698021243 (1 of
  1 route) and 40714948968 (4 of 4 routes) — so `docs/sam.md` line 143 is stale; epic-held-out-bench
  measures detection per variant, it is not first contact.
- Open question: who owns the Meta billing fix for the SAM key, and does the job resolve
  `MODEL_API_KEY` or fall back to `META_API_KEY`? Until answered, the key fix is a `hitl` first step of
  epic-held-out-bench, and every live run waits on it.
- Source conflict: `docs/sam.md` line 143 says the held-out routes have not been probed with SAM, while
  runs 40698021243 (1/1 route) and 40714948968 (4/4 routes) probed them with SAM on.
- Source conflict: `docs/evaluation.md` asks to decide the sample rate after the first measurements; it
  was decided on Oct 28.
