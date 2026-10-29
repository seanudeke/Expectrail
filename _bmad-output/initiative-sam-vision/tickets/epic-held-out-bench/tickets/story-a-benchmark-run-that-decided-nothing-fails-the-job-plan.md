---
title: "A benchmark run that decided nothing fails the job"
ticket: 1
status: in-review
---

## Built

On branch `bench/heldout-detection`, commit `71f7042`, pushed to PR #39:

- `agents/heldout_bench.py`: `main()` exits 1 when the decisive verdict is needs-review (SAM on:
  `caughtWithSamOn`; SAM off: `caughtWithSamOff`), and `annotation()` reports each reason as `::error`
  instead of `::warning`.
- `.github/workflows/sam-probe.yml`: the `heldout-bench` step always publishes the annotation and the
  timing notice, then fails with the benchmark's exit code, so a green job means the checks ran.
- `tests/test_heldout_bench.py`: a blind run exits 1 with SAM on and with SAM off, a decided run exits
  0; the error annotation expectation updated. 261 tests pass offline.

## Not verified

The story's dispatch check needs a `heldout-bench` run with a set-but-garbage `MODEL_API_KEY`, which
needs write access to the `seanudeke/Nightshift` secrets. Nothing was dispatched.
