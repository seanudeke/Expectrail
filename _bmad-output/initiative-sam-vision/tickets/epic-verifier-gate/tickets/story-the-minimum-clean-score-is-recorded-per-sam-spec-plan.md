---
title: "The minimum clean score is recorded per SAM spec"
ticket: 1
status: done
---

## Built

On branch `verifier/clean-score-floor`, PR #43:

- `agents/verifier.py`: every SAM verdict file now carries `samMinScore` (lowest per-frame
  best-detection score across the spec's prompted objects). The clean replay is gated by
  `SAM_CLEAN_SCORE_FLOOR = 0.60`: a clean pass below it becomes needs-review with the reason in the
  verdict file. Candidate and held-out margins are recorded, not gated. No approved spec edited,
  no contract change (the verdict schema is open).
- Floor provenance: the Oct 28 clean probes on `sam-probe-results` — run 40656097298
  (player-always-visible) minimum 0.644, run 40656100304 (coins-visible) minimum 0.688. 0.60 keeps
  ≥7% headroom under both.
- `tests/test_sam.py`: the clean coins verdict records 0.85; a clean robot at 0.55 (above the spec's
  0.5, below the floor) is needs-review with the floor named in the reason, while the candidate
  check still passes. Full suite green offline (257 passed).

## Not verified

No live clean run has been judged with the floor yet: the SAM key still returns
HTTP 402 billing_not_configured (confirmed again by run 40800572513, dispatched today). The first
live verify run with SAM on exercises it.

## Done

Merged to main with PR #43 (Oct 29 02:21 UTC). Note: run 40805529944's branch merged main one minute
before that (e60d407, 02:20:54), so the first full bench ran WITHOUT the floor — the floor still has
no live proof; 2.3's end-to-end run will exercise it first.
