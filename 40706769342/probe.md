# SAM probe: player-stays-above-ground

Model `sam-3.1`. Prompts: player = "blue robot", ground = "grass-topped ground". API calls 80, cache hits 37.

Verdicts below are on the probed frames only, not a full run.

| Run | Frames | Verdict | player found | ground found |
| --- | --- | --- | --- | --- |
| clean | 13 | pass | 13/13 | 13/13 |
| layering_v1 | 13 | needs-review | 7/13 | 13/13 |
| layering_v2 | 13 | needs-review | 7/13 | 13/13 |
| missing-texture_v1 | 13 | pass | 13/13 | 13/13 |
| missing-texture_v2 | 13 | pass | 13/13 | 13/13 |
| physics-fall-through_v1 | 13 | fail | 3/13 | 3/13 |
| physics-fall-through_v2 | 13 | fail | 3/13 | 3/13 |
| sinking_v1 | 13 | fail | 13/13 | 13/13 |
| sinking_v2 | 13 | fail | 13/13 | 13/13 |

## Per object

**clean**: no violation in 13 frames
- player: best score min 0.82, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**layering_v1**: no violation in 7 frames judged, but an object was not found in 6 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.60, max 0.95; matches per frame 0 to 1; box width {'min': 64.0, 'median': 117.0, 'max': 118.0}, height {'min': 61.0, 'median': 121.0, 'max': 122.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**layering_v2**: no violation in 7 frames judged, but an object was not found in 6 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.60, max 0.95; matches per frame 0 to 1; box width {'min': 64.0, 'median': 117.0, 'max': 118.0}, height {'min': 61.0, 'median': 121.0, 'max': 122.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**missing-texture_v1**: no violation in 13 frames
- player: best score min 0.84, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**missing-texture_v2**: no violation in 13 frames
- player: best score min 0.84, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**physics-fall-through_v1**: player is 70px past the boundary (above 780, tolerance 12) (first at frame 10, 2 frames)
- player: best score min 0.00, median 0.00, max 0.95; matches per frame 0 to 1; box width {'min': 80.0, 'median': 117.0, 'max': 118.0}, height {'min': 47.0, 'median': 122.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 1.00; matches per frame 0 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 72.0, 'median': 180.0, 'max': 180.0}

**physics-fall-through_v2**: player is 70px past the boundary (above 780, tolerance 12) (first at frame 10, 2 frames)
- player: best score min 0.00, median 0.00, max 0.94; matches per frame 0 to 1; box width {'min': 81.0, 'median': 117.0, 'max': 118.0}, height {'min': 47.0, 'median': 122.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 1.00; matches per frame 0 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 72.0, 'median': 180.0, 'max': 180.0}

**sinking_v1**: player is 47px past the boundary (above 780, tolerance 12) (first at frame 10, 4 frames)
- player: best score min 0.62, median 0.91, max 0.96; matches per frame 1 to 1; box width {'min': 73.0, 'median': 100.0, 'max': 118.0}, height {'min': 105.0, 'median': 122.0, 'max': 127.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

**sinking_v2**: player is 56px past the boundary (above 780, tolerance 12) (first at frame 0, 5 frames)
- player: best score min 0.62, median 0.91, max 0.96; matches per frame 1 to 1; box width {'min': 73.0, 'median': 93.0, 'max': 118.0}, height {'min': 101.0, 'median': 121.0, 'max': 127.0}
- ground: best score min 1.00, median 1.00, max 1.00; matches per frame 1 to 1; box width {'min': 1600.0, 'median': 1600.0, 'max': 1600.0}, height {'min': 180.0, 'median': 180.0, 'max': 180.0}

## Tolerance

Approved spec: tolerancePx = 12 (set against the position-log stand-in, whose boxes are in game-world pixels; SAM boxes are in captured-frame pixels, twice as large here).

- clean (clean): worst gap 7.0 px
- layering_v1 (bug): worst gap -14.0 px
- layering_v2 (bug): worst gap -14.0 px
- missing-texture_v1 (bug): worst gap 7.0 px
- missing-texture_v2 (bug): worst gap 7.0 px
- physics-fall-through_v1 (bug): worst gap 72.0 px
- physics-fall-through_v2 (bug): worst gap 72.0 px
- sinking_v1 (bug): worst gap 59.0 px
- sinking_v2 (bug): worst gap 59.0 px

A gap above the tolerance is a fail. The tolerance has to sit above every clean gap and below the gaps of the bugs this spec should catch; the clean worst here is 7.0 px.
