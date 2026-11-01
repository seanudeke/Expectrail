---
title: "Every active variant and the clean control measured"
ticket: 3
status: done
---

## Done

Run 41003749744 (Oct 30, dispatched from main at 33c7a9f, collected by `bench/rerun-detection.sh
held-out` into `bench/detection/held-out.json`): all 8 active variants plus the clean control,
five routes each — 8 of 8 caught with SAM on, 4 of 8 off, no false alarm on clean.

The owed counting landed in 3cb0e95 and is in that run's own annotations (verified via the
check-run annotations API): `Bench SAM images <variant>` (clean: 1,164) beside each result
annotation, and the workflow's `Bench time <variant>` wall clock (clean: 472 s). The published
record carries the totals: `spend` = samImages 7,693, samUsd 19.23, jobMinutes 50.6. Counting
comes from `sam_usage()`/`sam_images_since()` in agents/sam_observations.py; the annotation is
printed by `annotation()` in agents/heldout_bench.py.
