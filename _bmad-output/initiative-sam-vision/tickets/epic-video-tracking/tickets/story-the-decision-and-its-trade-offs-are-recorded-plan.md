---
title: "The decision and its trade-offs are recorded"
ticket: 2
status: done
---

## Done

docs/sam.md carries the dated decision — "Video input: measured, not used (October 29)" — with
the measured numbers (per-spec verdict diffs, the 11-frame sinking carry-through, the phantom
"blue robot" on layering frame 110, one tracked-object score of 0.938 instead of per-frame
scores, $3.69 vs $0.43) and the trade-offs accepted: video errs toward a pass exactly on the
occlusion and sinking families, so the verifier keeps one image per frame; video stays a
candidate for coins only, and only after blinking coins are tested.

The adapter matches the decision: the verifier's request path in agents/sam_observations.py is
one image and one prompt per request; the video request path exists only for the measurement
module (agents/sam_video.py) and no gate uses it.
