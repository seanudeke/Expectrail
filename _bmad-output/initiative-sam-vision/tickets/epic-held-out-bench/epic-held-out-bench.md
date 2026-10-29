---
tracker_id: ""
type: epic
title: "Detection on the private held-out variants is measured"
parent: initiative-sam-vision
covers: ["R7"]
sources: ["_bmad-output/initiative-sam-vision/initiative-sam-vision.md"]
companions: []
after: []
refined: true
risk: high
---

# Detection on the private held-out variants is measured

## Description

Each private held-out bug variant is replayed with no fix on the smoke route and every private route,
and judged by the checks a candidate faces: engine ground, hybrid ground, both SAM specs and gameplay.
A variant is caught when a check fails on at least one route; the clean game runs the same way as a
false-alarm control. The benchmark code and the `heldout-bench` mode exist on PR #39 and have never
produced a real verdict, because every `sam-3.1` call since 19:08Z on Oct 28 returns HTTP 402.

## Outcome

For Sean, every private variant has a known catch status, and the clean game is known to be a false
alarm or not, published as ids, counts and verdicts only.

## Requirements

1. **Every active variant is measured** (R1, parent R7)
   **Given** the private held-out set mounted and a working SAM key,
   **When** the benchmark runs a variant and the clean control,
   **Then** each reports caught or not caught over the smoke route and every private route,
   **And** the clean control reports false alarm or not.

2. **Caught means a check a candidate faces failed** (R2, parent R7; docs/evaluation.md, Held out)
   **Given** one variant's replays,
   **When** the checks are judged,
   **Then** the variant is caught when engine ground, hybrid ground, either SAM spec or gameplay fails
   on at least one route,
   **And** needs-review is never counted as a catch.

3. **Only ids and verdicts leave the runner** (R3, parent R7; docs/evaluation.md, Held out)
   **Given** a finished benchmark run,
   **When** its output is published,
   **Then** the published text holds variant ids, per-check counts and verdicts,
   **And** no private patch, route name, frame or trace appears in an annotation, log or artifact.

4. **A run that decided nothing is loud** (R4, docs/evaluation.md, Held out)
   **Given** a run where every SAM check came back needs-review,
   **When** the benchmark job finishes,
   **Then** the job fails or emits an error annotation naming the reason,
   **And** it is never reported as a green run.

## Constraints

- C1 (parent C1): `MODEL_API_KEY` stays separate from `META_API_KEY`, and a run says which key it used.
- C2 (parent C2): private held-out patches, routes, frames and descriptions never leave the verifier
  machine.

## Done when

- The `heldout-bench` workflow mode is on `main`, and a dispatched run has finished for every active
  variant plus the clean control.
- Each variant is reported caught or not caught, with the per-check counts behind it.
- The clean control reports no catch.
- A benchmark job whose checks could not decide is loud: it fails or annotates as an error, never as a
  green run.
- Only variant ids, counts and verdicts leave the runner; no artifact holds private frames, traces or
  route names.

## Boundaries

- Not the verifier's own gate logic, the score margin or the docs' honesty: epic-verifier-gate.
- Not the adapter's request path: epic-video-tracking.
- Must not change: what leaves the runner, and what the private manifest says.

## References

- parent — `_bmad-output/initiative-sam-vision/initiative-sam-vision.md`, Requirements R7
- benchmark — `agents/heldout_bench.py` and PR #39 (not on `main` yet)
- workflow — `.github/workflows/sam-probe.yml`, `heldout-list` and `heldout-bench` jobs

## Notes

- Decision (2026-10-28): entry 1.1 opens the epic instead of the tracer bullet. The tracer (1.2) needs
  the SAM key, which is blocked on an external billing fix; making runs loud first costs nothing and
  protects the spend that follows.
- Decision (2026-10-28): 1.4 merges before 1.3's full run, so the whole benchmark runs from `main` and
  its results are reproducible; the merge waits only on one real variant result from 1.2.
- Open question: the SAM key returns HTTP 402 `billing_not_configured`. Owner unknown, and unknown
  whether the job resolves `MODEL_API_KEY` or falls back to `META_API_KEY`. The key fix is a `hitl`
  first step here, and every live run waits on it.
- Unknown: the full bench is about 32k `sam-3.1` requests (17 variants and clean, 5 routes, 120
  frames, 3 prompts), with no cache persisted between dispatches; whether that is affordable is
  settled before the run, not after.
