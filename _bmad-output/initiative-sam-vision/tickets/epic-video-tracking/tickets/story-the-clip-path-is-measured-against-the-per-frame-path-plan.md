---
title: "The clip path is measured against the per-frame path"
ticket: 1
status: done
---

## Done

Measured October 29 with the SAM probe workflow's video-compare mode: run 40972278900 (clean)
and run 40972947066 (the 8 public bugs), published in `bench/sam-video/` (per-run JSON plus the
regenerated README). The comparison names, per run and per spec: requests sent (`images`,
`videoFrames`, `mp4Bytes`), cost at list price ($3.69 images vs $0.43 video in total), and
tracked-id stability per object (`objects`: foundByBoth, onlyImages/onlyVideo,
framesWithADifferentCount, score and box deltas). The per-frame path has no cross-frame id by
construction — one image and one prompt per request; sam-3.1's tracking exists only in video
mode (docs/sam.md, "Video input").

Deviation, recorded: the module does not time itself, so wall clock is not in the comparison
file; it is the Actions job record — the sam-video job took 4 min 37 s (clean) and 11 min 27 s
(the eight bugs), rendering plus both send paths. Those numbers are now stated in docs/sam.md
beside the decision. Add timing to agents/sam_video.py only if the clip path is ever revisited.
