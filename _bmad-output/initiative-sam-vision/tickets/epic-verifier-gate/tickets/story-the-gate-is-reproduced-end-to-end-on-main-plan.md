---
title: "The gate is reproduced end to end on main"
ticket: 3
status: done
---

## Done

Dispatched from main October 30, the ticket's two fixtures, SAM probe workflow verify mode, SAM on:

- Run 41146702158, `agents/fixtures/fix-collision-mask.patch`: decision **accept** — regression
  ground, visibility and coins pass, gameplay passes, all three clean controls pass, held-out
  ground passes; **no needs-review in any check**; held-out summary 4/4 routes pass on every
  check; review `REPAIR DEMONSTRATED` (exit 0) on `FRESH LIVE` evidence. This was also the first
  live exercise of the 2.1 floor on a main-dispatched verify: no clean check tripped it.
- Run 41146704284, `agents/fixtures/fix-but-hide-player.patch`: decision **reject** — regression
  player-always-visible fails on the candidate (smoke) and passes 0/4 held-out routes; held-out
  player-stays-above-ground fails as well (0/4); review `REJECTED` (exit 1).
- tests/test_sam.py still shows a SAM failure as needs-review; the offline suite is green
  (648 passed, 16 skipped).

The earlier branch dispatches gave the same rows and are published on main: 41101872602
(fix-collision-mask accept) and 41101881327, again 41123758768 (the sinking fixture rejected,
review kept with its frames in docs/review/sinking-fix/); docs/review.md's Measured table names
them.
