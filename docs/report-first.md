# Report first, verify always

Decided October 30, 2026, after the natural-catch trial. In one line: **let the fixer work from a
plain bug report, and make Expectrail the gate every fix has to pass.** Expectrail's detailed
evidence goes to the fixer only after the gate has rejected an attempt.

Updated October 31 with the first fix-matrix run on this policy. It found where the policy loses
fixes: on the sinking bugs Muse Code times out from a plain report, and a timeout never brings the
evidence. The record below has every run; the gate itself is unchanged.

## The decision

1. **The first attempt gets the report.** Muse Code gets what a developer would get: the failing
   check's sentence in plain English (or, for a reported bug, the reporter's own words), six
   screenshots of the failing run spaced from its first frame to its last, the route and the run's
   log. No spec, no verdict, no evidence.
2. **Every candidate is verified, on every attempt.** The fixer never decides that it is done. A
   candidate is accepted only when every check passes, as before.
3. **Only after the verifier rejects an attempt does the next one get the evidence:** the repair
   request (the approved spec, the evaluator's verdict on the failing run, its first failing frame)
   and the public checks that did not pass. An empty attempt is not a rejection; the next attempt
   stays on the report. A timeout is an empty attempt, and this is where the policy loses fixes: on
   Oct 31 three timeouts on `sinking/v1` never brought the evidence, and the bug was not fixed
   ([below](#what-the-evidence-does-for-the-fixer)).
4. **The fixer never learns about the held-out routes or the guards.** Not their names, not that
   one failed, not why. When only a held-out check rejected a candidate, the fixer learns that the
   attempt was rejected and nothing else.
5. **Inside the verifier, cheap checks reject first and SAM confirms.** See
   [Cost inside the verifier](#cost-inside-the-verifier) for what this changes and what it does not.
6. **A judge that cannot answer is not a rejection.** When SAM does not answer, the same candidate
   is judged again, then by Glimmer checked against the engine, then left for a person. The fixer is
   not asked for another fix ([fallbacks.md](fallbacks.md)).

Before this, the fixer got the evidence from the first attempt, and the verifier's full reasons
after a rejection.

## Why

### What the evidence does for the fixer

Every live repair we have run, with and without Expectrail's evidence:

| Run | What Muse Code got first | Fixed | First attempt |
| --- | --- | --- | --- |
| Fix matrix, development bugs ([`bench/fix-matrix/`](../bench/fix-matrix/README.md)) | Screenshots and the expected behaviour in plain English | 8 of 8 | 8 of 8 |
| The same 8 bugs | Expectrail's evidence (spec, verdict, first failing frame) | 8 of 8 | 7 of 8 |
| Fix matrix, held-out run 1 ([`bench/fix-matrix/held-out/`](../bench/fix-matrix/held-out/README.md)) | Screenshots | 7 of 8 | 7 of 8 |
| The same 8 bugs | Expectrail's evidence | 8 of 8 | 7 of 8 |
| Fix matrix, held-out run 2 ([`bench/fix-matrix/held-out-run-2/`](../bench/fix-matrix/held-out-run-2/README.md)) | Screenshots | 7 of 8 | 7 of 8 |
| The same 8 bugs | Expectrail's evidence | 8 of 8 | 7 of 8 |
| Fix matrix, development bugs, Oct 31 on this policy ([`bench/fix-matrix/report-first/`](../bench/fix-matrix/report-first/README.md), [41223754703](https://github.com/seanudeke/Expectrail/actions/runs/41223754703)) | Screenshots | 6 of 8 | 6 of 8 |
| The same 8 bugs | Expectrail's evidence | 8 of 8 | 8 of 8 |
| The same 8 bugs | A plain report, the evidence after a rejection (this policy, `escalate`) | 7 of 8 | 6 of 8 |
| Natural-catch trial, 4 reported bugs × 5 ([`bench/reported/trial.md`](../bench/reported/trial.md)) | The reporter's own words and screenshots | 20 of 20 | 20 of 20 |
| Demo loop, 10 live runs ([`bench/demo-loop/`](../bench/demo-loop/README.md)) | Expectrail's evidence | 10 of 10 | 10 of 10 |
| Demo loop on this policy, 3 live runs ([41223748922](https://github.com/seanudeke/Expectrail/actions/runs/41223748922), Oct 31; [a review](review/report-first-run-1/)) | A plain report | 3 of 3 | 3 of 3 |

With Expectrail's evidence from the first attempt, Muse Code fixed every case: 42 of 42. Without
it, from screenshots or a plain report, it fixed 51 of 55. All four misses are sinking bugs (held-out
`sinking/v4` in both held-out runs, development `sinking/v1` and `sinking/v2` on Oct 31), and every
one ended in Muse Code timing out, not in a wrong fix accepted. Counting the sinking cases alone,
across the four fix-matrix runs: 8 of 8 fixed with the evidence, 4 of 8 without. On every other bug
family the briefing made no difference.

So the evidence does help, on one family of bugs: without it, Muse Code ran out of time on half
the sinking cases; with it, on none. It is four runs and one family, so it is a signal, not a rate.

This policy did not recover `sinking/v1` on Oct 31: all three attempts timed out, and a timeout is
an empty attempt, which stays on the report, so the evidence was never given. On `sinking/v2` the
second attempt was rejected, the third got the evidence and was accepted.

### The judge is what matters

The judge benchmark ([`bench/judge/`](../bench/judge/README.md)) gave the same 15 candidate fixes
to three judges, twice. Seven of them only look right: one draws the robot inside the ground,
another moves the floor's collision below its art, another hides the robot behind the scenery.

| Judge | Bad fixes accepted (of 7) | Good fixes accepted (of 8) |
| --- | --- | --- |
| Expectrail with SAM | **0** | 8 |
| Expectrail, position log only | 3 | 8 |
| Muse Code from before-and-after screenshots | 2 | 6 and 7 |

Fixing is mostly the part Muse Code does well; the sinking bugs above are the exception, where it
runs out of time without the evidence. Judging is where a fix that only looks right gets through,
and only Expectrail with SAM let none through.

### Why not "let Muse fix it, and run Expectrail only if Muse cannot"

We considered running the verifier only when Muse could not fix the bug. That would remove the
gate. "Muse fixed it" can only come from Muse, and Muse believes in exactly the fixes that matter
most: the ones that only look right. Shown the screenshots, it accepted 2 of 7 of them. A fixer's
confidence in its own fix is no better evidence than that. Under that rule, a fix that draws the
robot inside the ground would never trigger "Muse cannot fix it", so it would ship. So the gate
stays on every candidate, and what moves is what the fixer is told.

## What this buys

- **A product that does not care who writes the fix.** The first attempt's briefing is a plain
  report anyone could act on. Muse Code, another coding agent or a person can write the fix;
  Expectrail decides whether it ships. On most bugs the numbers above agree. On the sinking bugs
  they do not: a fixer working from the report alone timed out on half of them, so there Expectrail's
  evidence helps the fixer as well as judging it.
- **Harder to fix to the test.** A fixer that never sees the spec's assertion, its threshold or a
  verdict on the first attempt cannot aim at them. Most fixes are accepted on that first attempt.
  The held-out routes and the guards are never mentioned at all, so a fix cannot be tuned to them
  on any attempt.
- **A narrower claim about the fixer.** We do not claim Expectrail's evidence makes Muse a better
  fixer in general: on every family but one it made no difference. On the sinking bugs it did, 8 of
  8 fixed with the evidence against 4 of 8 without. The claim we lead with is the one measured most:
  Expectrail is a better judge.
- **A cheap fallback, kept, with a gap.** When the gate rejects an attempt, the fixer gets
  everything Expectrail knows about the public checks. That costs nothing until a rejection happens.
  But rejections are rare (3 in the 87 fix-matrix attempts) and timeouts are not (17), and a
  timeout does not bring the fallback.
- **One setting to undo it.** `EXPECTRAIL_BRIEFING=evidence` restores the evidence from the first
  attempt.

## What we do not know yet

- **Whether the evidence helps on a later attempt.** The first `escalate` run (Oct 31) escalated
  once, on `sinking/v2`, and that attempt was accepted. It never escalated on `sinking/v1`, because
  its attempts timed out and an empty attempt is not a rejection. Whether escalating after a timeout
  would have recovered it is unmeasured.
- **Whether a report is enough.** It was not always, even for small, local changes: each sinking
  bug is a one-line fix, and from a report Muse Code timed out on half of them. A bug that spans
  several files, or whose obvious fix is wrong, may need the evidence more.
- **Overnight, the "report" is still Expectrail's own check.** When no person reported the bug,
  Expectrail's check found it, and the report is that check's sentence. The fixer still does not
  see the spec, the verdict or the evidence until a rejection.
- **The report costs one more replay.** The screenshots come from replaying the failing game on the
  route, about half a minute on a CI runner. The evidence briefing did not need it.

## Cost inside the verifier

The rule: **a cheap check should reject before a paid one runs, and SAM should be paid to confirm
an accept, not to find a reject the engine already found.** The opposite rule, SAM only when the
cheap checks fail, would be wrong: a fix that only looks right passes the cheap checks, and that is
exactly where SAM earns its cost.

What already follows the rule:

- **Private routes are skipped after a definite fail.** Once a candidate fails a public check, the
  held-out routes cannot change the decision, so they are not replayed
  (`EXPECTRAIL_HELDOUT_AFTER_FAIL=run` replays them).
- **The clean game is judged by SAM once per run.** Its answers are shared, encrypted, with every
  job (`sam_cache`).

What we did not change:

- **SAM still looks at the candidate's smoke replay before the engine verdict is known.** Reordering
  this would save about 150 SAM images, roughly $0.40, per rejected candidate (the held-out bench
  used 746 images over five routes). With 3 rejections in the 87 fix-matrix attempts, that
  is not worth changing the verifier's order days before the deadline. If harder bugs make rejections
  common, it is the next change.

## What changed in the code

- [`agents/escalation.py`](../agents/escalation.py): the policy. It builds the report and the
  evidence briefings, and the public feedback after a rejection.
- [`agents/loop.py`](../agents/loop.py): the overnight loop replays the failing base for the
  report's screenshots. It briefs each attempt by the policy and records each attempt's stage
  (`report` or `evidence`).
- [`agents/matrix.py`](../agents/matrix.py) and
  [`.github/workflows/fix-matrix.yml`](../.github/workflows/fix-matrix.yml): the condition
  `escalate`, run by default beside `screenshots` and `expectrail`.
- [`agents/bench_collect.py`](../agents/bench_collect.py): reads `escalate` results.
- [`tests/test_escalation.py`](../tests/test_escalation.py) covers the policy and the loop. The
  loop test checks this order: report, empty attempt (still the report), rejection, evidence,
  accept, with every candidate verified. It also checks that a held-out failure never reaches the
  fixer.

The natural-catch trial (`agents/reported_trial.py`) is unchanged. By its protocol, the fixer gets
the report on every attempt and never the evidence.
