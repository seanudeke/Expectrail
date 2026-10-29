---
tracker_id: ""
type: epic
title: "Video tracking earns its place or stays out"
parent: initiative-sam-vision
covers: ["R8"]
sources: ["_bmad-output/initiative-sam-vision/initiative-sam-vision.md"]
companions: []
after: []
refined: true
risk: medium
---

# Video tracking earns its place or stays out

## Description

`sam-3.1` takes a whole clip in one request and tracks objects with stable ids, billed per frame with
a 50-frame minimum. The adapter today sends one frame and one prompt per request and caches per frame.
This epic measures both paths on the same runs and records the decision; if the clip path wins, it is
implemented in the adapter.

## Outcome

For Sean, the cost and the frame-level precision of the observation path are known numbers, and the
adapter sends whichever won.

## Requirements

1. **Both paths are measured on the same runs** (R1, parent R8)
   **Given** the per-frame path and the clip path, **When** both run over the same replays, **Then**
   the comparison records cost, latency and whether tracking stayed stable per object, **And** the
   numbers come from the runs, not from the vendor's documentation.

2. **The decision and its trade-offs are written down** (R2, docs/sam.md, Not built yet)
   **Given** the measurement, **When** the decision is made, **Then** it is dated and names which path
   the adapter sends, **And** the trade-offs it accepted (H.264 compression of frames, a cache per run
   instead of per frame) are recorded beside it.

## Constraints

- C3 (parent C3): whichever path wins, the cache stays verifier state outside the repo.
- C4 (parent C4): the ground is never taken from SAM alone, whichever path sends the frames.

## Done when

- A dated decision records measured cost, latency and tracking stability for both paths, on the same
  runs.
- If the clip path wins, the adapter sends it and a pass still rests on every frame of the window; if
  it loses, the decision says why and the per-frame path stays.
- The trade-offs the decision accepted are written down beside it.

## Boundaries

- Not the verdict's semantics or the score margin: epic-verifier-gate.
- Not what the held-out benchmark reports: epic-held-out-bench.
- Must not change: the rule that a pass rests on every frame, and needs-review on any SAM failure.

## References

- parent — `_bmad-output/initiative-sam-vision/initiative-sam-vision.md`, Requirements R8
- adapter — `agents/sam_observations.py`, request body, cache and sampling
- trade-offs — `docs/sam.md`, Not built yet (Video mode)

## Notes

- Decision (2026-10-28): 3.1 is the tracer bullet and opens the epic; 3.2 waits on its numbers. Its
  wait on the SAM key is carried by its unknown, not by an epic-level after, so the epic is not gated
  as a whole.
- Unknown: the adapter has no clip request path — `request_body()` sends one prompt and one PNG, and
  only the parser is video-ready. Where the sender lives and what encodes H.264 on the runner is
  settled before 3.1 starts; no reference in the repo describes the video request shape.
- Unknown: whether a per-run cache would cost more credit than the per-frame one it replaces. Settled
  by the measurement, not before.
