---
title: "The docs say what the runs show"
ticket: 2
status: in-review
---

## Built

On branches `docs/sam-run-truth` (PR #41) and `bmad/sam-vision-plan` (PR #42):

- `docs/sam.md`: the claim that the held-out routes have not been probed with SAM is replaced by the
  runs that did it (40698021243 on one route, 40714948968 to 40714993165 on all four), and says the
  frames never left the runner.
- `docs/evaluation.md`: the sample rate is stated as decided — every fourth frame by default, refined
  to the exact frame on a fail, every remaining frame confirmed before a pass.

## Not verified

No dispatch was needed; both lines are checkable by reading the runs named.
