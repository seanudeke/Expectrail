# Mutation bench

How much does Expectrail's tiered checker catch, which checks catch what, what does it miss, and what
did the judging cost? Issue #127 sets the rules. Nobody on the team writes a bug or picks a case.

**Status: draft pre-registration. No case has been judged.** `agents/mutation_bench.py` and the
**Mutation bench** workflow refuse to run until [`preregistration.json`](preregistration.json) has no
empty field left, the code it pins has not moved, and the committed manifest is exactly what the
generator writes. A judged run starts only from `main`, so nothing is judged before the file is merged.
Rehearsals prove the plumbing first, on any branch, on cases the study cannot draw: `dry-run` (the
judge benchmark's public comment-only fixture on an unfixed bug, no SAM, no key), `dry-run-sam` (the
same pair through forced SAM, about $1.20) and `dry-run-mutants` (three stand-ins in files the generator never edits, no SAM,
no key). A rehearsal is never a result: it has no score, its rows name no registration, a summary
refuses to mix it with a judged run, and it fails if it did not reach what it rehearses. The
pre-registration discloses what earlier rehearsals, on members of the population, happened to show.

Three cases judged before registration are excluded before the draw, by Sean's decision, whatever
they did: the `freeze` pair on physics fall-through v1 and two mutants (`excludedBeforeDraw`). So Part 1
is 47 pairs, not 48. The registration names them, and the manifest lists them.

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

To register, put your decisions in a file by their dotted names (the list is at the top of
`agents/mutation_register.py`) and run:

    python3 -m agents.mutation_register --values decisions.json          # checks, and writes nothing
    python3 -m agents.mutation_register --values decisions.json --write

It writes your decisions and Sean's two, then the pins last, then the manifest, and reads both back
through the gates a judged run uses. It never overwrites a registration, and never pins uncommitted
work. Commit both files in one pull request, and say it is the registration.

## Recording a run

    python3 -m agents.mutation_collect --part wrong-fix --run <id>                 # Part 1
    python3 -m agents.mutation_collect --part generated --run <cheap>              # Part 2, the cheap tier
    python3 -m agents.mutation_collect --plan-sam --run <cheap>                    # what the SAM phase needs
    python3 -m agents.mutation_collect --part generated --run <cheap> --run <sam>  # Part 2, both phases

It reads the runs' own artifacts, counts a mutant judged in both phases once, reports any case missing,
and refuses a rehearsal, another registration or the wrong part. The tools are not pinned.

## Part 3

`agents/mutation_fix.py` and the **Mutation fix** workflow. `reportTemplate` must hold `{sentence}`, which
takes the sentence of the check that caught the mutant, so no report is written by hand.

    python3 -m agents.mutation_fix --pick --seed <your seed>   # after Part 2 is recorded; commit cases.json
    python3 -m agents.mutation_fix --estimate                  # post this in #156 first
    python3 -m agents.mutation_fix --record --run <id>

The workflow's `rehearsal` mode runs the path on a stand-in, with no Muse, no SAM and no key.

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

## How to read a stratified score

With counts set per class, the pooled score over the sample depends on those counts: a class of 13
mutants given as many cases as a class of 2,642 counts as much. So the report leads with a weighted
score, shows the pooled figure as a figure about the sample, and gives every class's own score.

A class's score is over its decided cases, so it weighs what it is estimated to hold of those: its
size times the share of its sample that was decided. Its plain size would count scenery edits nobody
could ever catch. A class with no score is named and left out of the weights, and the report says what
share of the estimated visible mutants the score covers. The estimate is only as good as each class's
sample: a class sampled lightly has a rough share and a rough score.

## How a case is scored

Only a check that ran to completion and failed is a catch. See `agents/mutation_bench.py` for the
outcomes (`caught-cheap`, `caught-sam`, `survived`, `undecided`, `crash`, `error`). The mutation score
is caught over caught plus survived, on cases labelled bad; everything else is reported beside it.

**Limits to state with any result.** The tier is this bench's policy: the verifier itself runs SAM on
every candidate. The specs judge the first two seconds of one route, and the smoke route never
shoots, so a mutant in the gun reads as equivalent. The oracle only knows "differs from the clean
game". Public checks only.
