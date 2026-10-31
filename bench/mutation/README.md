# Mutation bench

How much does Expectrail's tiered checker catch, which checks catch what, what does it miss, and what
did the judging cost? Issue #127 sets the rules. Nobody on the team writes a bug or picks a case.

**Status: draft pre-registration. No case has been judged.** `agents/mutation_bench.py` and the
**Mutation bench** workflow refuse to run until [`preregistration.json`](preregistration.json) has no
empty field left, the code it pins has not moved, and the committed manifest is exactly what the
generator writes. A judged run starts only from `main`, so nothing is judged before the file is merged.
Rehearsals prove the plumbing first, on any branch: `dry-run` (one known pair, no SAM, no key),
`dry-run-sam` (the same pair through forced SAM, about $1.20) and `dry-run-mutants` (two mutants, one
of them a scene that has lost its script, no SAM, no key). A rehearsal is never a result, and its rows
name no registration, so a summary refuses to mix one with a judged run.

The pins cover the game, the development bugs, the operators, the specs, the verifier, the observers,
the generator, the bench and its workflow. Changing any of them after registration refuses every run
until the pins are set again, which is a change to the registration and has to be reported as one.

## What a person decides before anything is judged

| Field | Who | What |
| --- | --- | --- |
| `wrongFix.commentOnlyLabel` | Sean | `good` or `bad`. A comment stacked on the correct undo leaves the game correct, so #127's "bad by construction" does not hold for these 8 of the 48 pairs. |
| `wrongFix.publicSamRuleApprovedBy` | Sean | Approves leaving the verifier's held-out arm out of the bench's decision. Without this rule, SAM-on can never accept here. |
| `generator.*` | Taofeek | Seed, sample size and the operator steps. |
| `generator.sampling`, `generator.samplingWhy` | Taofeek | `{"method": "uniform"}`, or `{"method": "stratified", "perClass": {"numeric": n, ...}}`, whose counts must add up to `sampleSize`; and why. A class with fewer mutants than its count gives all it has, the manifest reports the shortfall, and the rest is never moved to another class. |
| `oracle.traceThresholdPx`, `oracle.frameThreshold` | Taofeek | What counts as visible. |
| `stopRule` | Taofeek | What happens if few mutants are visible. |
| `agreement.seed`, `agreement.minimum` | Taofeek | The seeded sample of cheap rejections SAM also judges. Sean asked for at least 20. |
| `reportTemplate` | Taofeek | The one-line symptom for Part 3. |
| `pins` | Taofeek, last | `python3 -m agents.mutate_game --pins`, once everything else is final. |

Then write the manifest and commit both: `python3 -m agents.mutate_game --manifest bench/mutation/generated/manifest.json`.

## What the operators can reach

From `python3 -m agents.mutate_game --sites`, one mutant per axis and direction with one collision
bit. These are facts about the game, and they bear on the operator list and the sample:

| Operator | Mutants |
| --- | --- |
| `position` | 1,268 |
| `scale` | 828 |
| `z_index` | 506 |
| resource path | 66 |
| `offset` | 40 |
| comparison, sign and constant in `player.gd` and `enemy.gd` | 20 |
| `collision_mask`, `collision_layer`, one bit | 13 |
| `one_way_collision` | 1 |
| `visible`, `disabled` | **0** |

`python3 -m agents.mutate_game --mutants-by-class` gives the same counts at the steps in the
pre-registration, once they are filled in.

Godot leaves a property out of a scene file when it holds its default, so `visible` and `disabled`
have no line to flip. An unstratified sample of this list is nearly all `position`, `scale` and
`z_index` in the level's scenery.

## How a case is scored

Only a check that ran to completion and failed is a catch. See `agents/mutation_bench.py` for the
outcomes (`caught-cheap`, `caught-sam`, `survived`, `undecided`, `crash`, `error`). The mutation score
is caught over caught plus survived, on cases labelled bad; everything else is reported beside it.

**Limits to state with any result.** The tier is this bench's policy: the verifier itself runs SAM on
every candidate. The specs judge the first two seconds of one route, and the smoke route never
shoots, so a mutant in the gun reads as equivalent. The oracle only knows "differs from the clean
game". Public checks only.
