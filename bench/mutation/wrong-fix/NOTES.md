# Reading the Part 1 record

`README.md`, `summary.json` and `findings/` here were written by `agents.mutation_collect` from run
[41268021760](https://github.com/seanudeke/Expectrail/actions/runs/41268021760), and are not edited by
hand. This note is hand-written, and it changes no number. The registered score is **79.5%: 31 of 39
decided bad cases caught.** Read the record with three facts in mind.

## The 8 scale-to-zero "blind spots" are not gaps in the checks

The `scale-to-zero` operator sets `scale = Vector2(0, 0)` on the root node of `player/player.tscn`. But
`game_singleplayer.tscn` sets `scale = Vector2(1, 1)` on the Player instance, and that overrides it. So
each scale-to-zero candidate plays exactly like the clean game: the trace ends where the clean game's
does, and the SAM arm needed no images, because every frame matched the clean game's.

- **These 8 cases are bad only by label.** In substance they are correct fixes. That makes their
  `findings/` and catch-specs misleading: no check could have caught them, because nothing was wrong.
- **The registered score stays 79.5%.** Without these 8 pairs it would be 31 of 31, but that figure is
  not registered and may only appear as a note beside it.
- **This is a flaw in an operator the team wrote,** not in the verifier. It was found after the run, and
  nothing was changed in response.

## The 7 "disagreements" are freeze, which vision cannot see

The agreement table asks SAM's own checks (`player-always-visible`, `coins-visible`) about the cheap
tier's 7 rejections. All 7 are `freeze`: the robot stops moving but stays fully drawn, so those vision
checks pass. "Disagree" here means SAM alone would not have caught a freeze. It does not mean SAM
contradicted the cheap tier. The cheap gameplay check is the only thing that sees a freeze, and in the
tiered judge its rejection is final.

The two tiers cover different failures:

- **The cheap tier alone** caught 7 of 39 (17.9%).
- **Every one of the other 24 catches came only from SAM:** hide, sink and behind-scenery.

## Two "no-op" candidates are real bad fixes

The summary counts 2 no-op candidates: `dev/layering/v2` with `behind-scenery`, and `dev/sinking/v2`
with `sink`. In each, the operator puts back the very bug it was stacked on, so the candidate leaves
the game exactly as broken as before. Both are correctly labelled bad, and both were caught.

## Spend

5,473 SAM images, $13.68 at list price, against an estimate of about $28.
