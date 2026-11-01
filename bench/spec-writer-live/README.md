# Live Muse Spark spec draft (Oct 27, 2026)

Sean ran the spec writer against the live Meta Model API on his machine:

```sh
python3 -m expectrail.spec_writer draft "The player never falls through the ground" \
  --id player-stays-above-ground-live --out spec-live.json
```

Model: `muse-spark-1.3` (the default; not the contributor tier). The draft passed the spec schema and
the lint rules. [`spec-live.json`](spec-live.json) is the output, unedited.

## Review (Sean): not approved as drafted

| | Muse Spark draft | Approved spec ([`specs/player-stays-above-ground.json`](../../specs/player-stays-above-ground.json)) |
| --- | --- | --- |
| Assertion | never-crosses: player stays above the ground's top edge | same |
| Object prompts for SAM | "player character", "ground" | "small robot character", "grass-topped ground" |
| Tolerance | 8 px | 12 px |
| Frames | all (no window) | 0 to 119 |

The structure is right. The object prompts are too generic for SAM 3.1: "player character" does not
say it is a robot, and "ground" also matches the floating grass platforms, which would put the
boundary on the wrong surface. Muse Spark saw only the sentence, never the game, so it could not
know. This is the reason a person approves every spec. The approved, hand-tightened spec stays
the active one.

Possible next step: send Muse Spark one key frame with the sentence so it can name the objects it
sees, and measure how often its drafts are approvable without edits.

## Names updated on Nov 1

The project's earlier name was replaced with Expectrail in the format IDs in `spec-live.json`. Nothing else
changed. The run wrote the earlier names; the files as recorded are at commit `85a5e253f635`.
