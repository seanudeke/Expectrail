# Advisory discovery: checks nobody wrote

Built October 31, 2026. In one line: **replay generic probes on a build, judge every replay with
contracts read from the game's own code, and report a finding only when it fails three times out of
three.** Nothing here accepts or rejects a fix. The verifier and its checks are unchanged.

## Two kinds of checks

Expectrail now runs two kinds of checks, and only one of them can reject a change:

| | Written by people | Discovered by Expectrail |
| --- | --- | --- |
| What | Three approved specs (the robot stays above the ground, the robot is visible, the coins are visible), the gameplay check, and the held-out bugs and routes. Five engine-record checks for the reported bugs, written after they were reproduced and run by the reported-bug bench and trial, not by the verifier | 22 generic probes, judged by contracts that twelve templates build from a profile of four claims read from the game's code (the double jump, the gun's cooldown, the sprite's facing, the enemies' patrol). Optionally, Muse Spark proposes more probes and contracts in the same closed language |
| Who writes them | Muse Spark drafts a spec from one sentence and a person approves it; teammates write the held-out cases | The templates, with no model; a planner's contracts carry `model_prior` authority and are never approved by being proposed |
| Effect | Gate: any failure rejects the change | Advisory: findings are reported beside the decision and never change it |
| Shown so far | 8 of 8 held-out bugs caught with SAM; 0 of 7 fixes that only look right accepted | 4 of 4 reported bugs found, no false alarm on the clean game (development reproduction); 2 of the 8 development bugs it was not written for |

The approved checks caught none of the four reported bugs ([`bench/reported/`](../bench/reported/README.md)).
This is the first slice of the answer: the advisory part of the team's autonomous-discovery
specification (its "restricted competition slice"), built on public material only. What comes after
it is in [What's next](#whats-next).

## Status, October 31

- **Built and measured:** everything on this page, locally and in CI (below).
- **Tested blind once:** with the discoverer frozen, ten fresh entries written after the freeze
  and their digest committed (pull request #150), the blind run flagged **4 of 8 defects** and
  **none** of the 2 intentional changes or the clean game, every job complete
  ([below](#blind-run-1-october-31)).
- **Not run live:** the Muse Spark planner. It is built and tested against a fake transport; every
  result on this page is with the planner off.

## What runs

```
mechanics profile ──► templates ──► contracts (closed trace language)
  (claims read from                       │
   the game's code)                       ▼
probe library ──► route compiler ──► headless replays ──► episodes ──► evaluator ──► verdicts
  (generic moves)      (exact routes)      (one per probe     (normalized    (pure, no      │
                                            per build)         traces)        model)         ▼
                     Muse Spark planner (optional): more probes and contracts   reference check, then
                     from the profile and the build's measurements only         3-of-3 reproduction
                                                                                         │
                                                                                         ▼
                                                                          discovery-run/v1 + report
```

| Part | Where | What it does |
| --- | --- | --- |
| Records | [`contracts/*.v1.schema.json`](../contracts), [`expectrail/contracts.py`](../expectrail/contracts.py) | Five closed schemas: episode, trace-spec, trace-verdict, mechanics-profile, discovery-run. Strict JSON: duplicate keys, NaN and Infinity are refused. |
| Recorder | [`harness/godot/expectrail_harness.gd`](../harness/godot/expectrail_harness.gd) | Writes the enemies and bullets on every tick (an empty list means none) and declares what it collects, so an empty tick can prove absence. |
| Episodes | [`expectrail/trace/normalize.py`](../expectrail/trace/normalize.py) | One replay's trace as an episode: contiguous ticks, declared capabilities, derived events (take-off, landing, a bullet's first appearance, a disappearance the recorder can vouch for). Never fills a gap. |
| Interpreter | [`expectrail/trace/evaluator.py`](../expectrail/trace/evaluator.py), [`signals.py`](../expectrail/trace/signals.py) | The only thing that gives a contract meaning. Eight operators from the specification plus `relation`. Five outcomes with counts. |
| Probes | [`expectrail/discovery/probes.py`](../expectrail/discovery/probes.py), [`route_compiler.py`](../expectrail/discovery/route_compiler.py) | 22 generic probes from the action catalog, compiled to exact routes. Programs, never code: tap, hold, wait, sequence, parallel, repeat, with caps on ticks, events, nesting and repeats. |
| Profile and templates | [`discovery/platformer.profile.json`](../discovery/platformer.profile.json), [`templates.py`](../expectrail/discovery/templates.py) | Four claims read from the game's code, each `inferred_code` and unapproved, and twelve templates that turn them into contracts with no model involved. |
| Planner | [`expectrail/discovery/planner.py`](../expectrail/discovery/planner.py) | One Muse Spark call per job. It sees the profile, the probes already run and each build's measurements, under a number, never its name. Its probes must compile and its contracts must validate; anything else is dropped and recorded. Its contracts carry `model_prior` authority. |
| Job | [`expectrail/discovery/run.py`](../expectrail/discovery/run.py), [`cli.py`](../expectrail/discovery/cli.py) | Runs it all under a budget, writes the discovery-run record and a report. |
| CI | [`.github/workflows/discovery.yml`](../.github/workflows/discovery.yml) | One job per build, no reference build, planner off or Spark. |

### The five outcomes

- **pass**: the contract applied, triggered at least as often as it requires, its window was
  completely observed, and nothing contradicted it.
- **fail**: a concrete counterexample in observed data.
- **not_exercised**: nothing triggered it (no bullet, no jump, no movement). It is never a pass.
- **insufficient_observation**: the recorder did not collect what the contract needs, or the window
  has a gap.
- **execution_error**: the evaluation itself failed.

### Relations: a bound from the game itself

`relation` is our one addition to the specification's eight operators. It compares one measurement
between two probes that differ in one thing: eight jump presses against two, shooting every 12
ticks against every 48, walking left against walking right. The bound comes from the game's own
behaviour on the twin probe, so it needs no number from a person and no healthy build. That matters
for a bug that is already in the game.

### What makes a failure a finding

- **The reference check.** When the job has a healthy reference build, a contract that fails on it
  is miscalibrated: it is rejected, and whatever it says about another build is never a finding.
- **Reproduction.** Each failing contract's probes are replayed from a fresh process until they have
  run three times. Three failures make it `reproduced`; anything less is a `flaky_candidate`, with
  the counts.
- **Without a reference** (the CI jobs, one build each), nothing is falsified inside the job. The
  clean game's own job is the false-alarm control: a contract that fails on it would be a false
  alarm on every build.

## Results

### Local, October 31: the clean game and the four reported bugs

One job, the clean game as the reference and each reported bug as a base build, all 22 library
probes on each, planner off: 150 replays in 548 s on one machine (110 probes, 40 reproduction
replays), complete within budget.

| Build | Replays | pass | fail | not exercised | Findings, each 3 of 3 |
| --- | ---: | ---: | ---: | ---: | --- |
| clean (reference) | 22 | 91 | 0 | 64 | none, and no contract rejected |
| air-jump | 22 | 87 | 4 | 64 | eight presses give 7 kicks in the air, two give 1 (`jump-no-extra-air-jumps`, at all four positions) |
| gun-cooldown | 22 | 87 | 4 | 64 | bullets 12 ticks apart, minimum 30 (`weapon-min-interval`); tapping every 12 ticks fires 12 bullets, every 48 fires 3 (`weapon-faster-taps`, both directions) |
| body-flip | 22 | 84 | 7 | 64 | walking left while facing right (`facing-follows-motion`); a bullet flying right while the robot faces left (`facing-bullets-follow-facing`); the sprite turns 240 times walking left, never walking right (`facing-mirror`, twice) |
| enemy-ledge | 22 | 90 | 1 | 64 | an enemy drops 256 px below where it settled, while the robot stands still (`enemy-max-drop`) |

Each bug was found by at least one contract, and the clean game failed none. No contract names a
bug, replays a bug's route or takes a threshold from a bug report (see [What the development
results do and do not say](#what-the-development-results-do-and-do-not-say) for how the profile
was chosen). The guards held where the feature still works: the double jump still exists on every
build, a ready press still fires, the enemies are all still there and still patrol. "Not exercised" is
mostly a contract on a probe that cannot trigger it (a weapon rule on a jump probe). A second full
run gave the same 110 episodes tick for tick. The record: [`bench/discovery/local-oct31/`](../bench/discovery/local-oct31/report.md).

### CI

Run [41238187197](https://github.com/seanudeke/Expectrail/actions/runs/41238187197), October 31,
planner off: one job per build, each with no reference build, all 22 library probes, recorded from
the jobs' own notices in [`bench/discovery/run-41238187197.json`](../bench/discovery/run-41238187197.json).

| Build | Written for? | pass | fail | not exercised | Findings, each 3 of 3 |
| --- | --- | ---: | ---: | ---: | --- |
| clean | the false-alarm control | 91 | 0 | 64 | none |
| air-jump | yes | 87 | 4 | 64 | as in the local run |
| gun-cooldown | yes | 87 | 4 | 64 | as in the local run |
| body-flip | yes | 84 | 7 | 64 | as in the local run |
| enemy-ledge | yes | 90 | 1 | 64 | as in the local run |
| physics-fall-through v1 | no | 75 | 4 | 76 | the double jump no longer works (`jump-air-jump-exists`, all four positions) |
| physics-fall-through v2 | no | 59 | 20 | 76 | the same, and an enemy drops through the floor (`enemy-max-drop`) |
| sinking v1 | no | 91 | 0 | 64 | missed |
| sinking v2 | no | 91 | 0 | 64 | missed |
| missing-texture v1 | no | 91 | 0 | 64 | missed |
| missing-texture v2 | no | 91 | 0 | 64 | missed |
| layering v1 | no | 91 | 0 | 64 | missed |
| layering v2 | no | 91 | 0 | 64 | missed |

- **The four reported bugs and the clean game gave exactly the local counts** on a different machine.
- **The recorder change moved nothing else.** The reported-bug bench ran on the same commit
  ([run 41238187161](https://github.com/seanudeke/Expectrail/actions/runs/41238187161)): today's
  checks still catch none of the four, the engine-record checks still catch all four, and neither
  raises a false alarm on the clean game.
- **Two of the eight development bugs were flagged, by contracts written for something else.** In
  both fall-through variants the robot drops through the ground at once and never stands, so it
  cannot jump at all: the guard that the double jump still works fails. That is a true symptom, not
  the cause; the report says "no air jump", not "fell through the floor". In v2 the ground loses its
  collision for everything, and the enemy rule says so directly.
- **Six were missed, as expected.** Sinking v1 rests the robot inside the ground and no claim is
  about ground contact; sinking v2, missing texture and layering are visual and cannot show in a
  trace. The verifier's approved checks and SAM catch all six today.

## The blind run

The results above are development reproduction. The blind run is the test that is not:

1. **Freeze.** `discovery/freeze.json` records the sha256 of every file that decides a finding (the
   profile and templates, probes, route compiler, signals, interpreter, job, planner prompt and
   model, record schemas, recorder, replay harness) and of the clean game, plus the exact blind
   command, as of commit `0b6556c14a51`. `python -m expectrail.discovery.freeze verify` names
   any file that changed, and a test keeps the freeze holding on main while the fresh set is in use.
2. **Fresh defects, written after the freeze.** Eight to ten defects and one or two intentional
   changes, in the private held-out repository under `fresh/`, each with a private route showing it.
   They are written without the discoverer's rules in front of the writer, and chosen by a random
   draw from a longer written list, so nobody picks them for being easy or hard to catch.
3. **Commit the set's digest** here (`bugs/fresh/fresh.sha256`) before any run.
4. **Run once** with the Discovery blind run workflow
   ([`.github/workflows/discovery-blind.yml`](../.github/workflows/discovery-blind.yml)). It verifies
   the freeze and the digest before replaying anything, runs the clean game as a control, and uses
   no reference build. The public log carries counts only: per opaque id,
   defect or intentional, flagged or not. Which rules fired stays private until the event is over.

Scored: defects flagged out of defects, intentional changes and the clean game flagged (false
alarms), and incomplete jobs. A miss is a result, not a reason to change the frozen system.

### Blind run 1, October 31

Run [41248745687](https://github.com/seanudeke/Expectrail/actions/runs/41248745687), main at
`81f692c`, planner off. Before replaying anything, every job verified the freeze (`6e9ca2bd…`) and
the set's digest against [`bugs/fresh/fresh.sha256`](../bugs/fresh/fresh.sha256). Recorded from the
jobs' counts-only notices in
[`bench/discovery/blind-run-41248745687.json`](../bench/discovery/blind-run-41248745687.json).

| Id | Kind | Flagged | Reproduced findings | Replays |
| --- | --- | --- | ---: | ---: |
| clean | control | no | 0 | 22 |
| f01 | defect | **yes** | 1 | 24 |
| f02 | defect | **yes** | 4 | 38 |
| f03 | intentional | no | 0 | 22 |
| f04 | defect | no | 0 | 22 |
| f05 | defect | no | 0 | 22 |
| f06 | defect | **yes** | 1 | 24 |
| f07 | defect | no | 0 | 22 |
| f08 | defect | no | 0 | 22 |
| f09 | defect | **yes** | 4 | 38 |
| f10 | intentional | no | 0 | 22 |

**4 of 8 defects flagged, 0 false alarms on 3 healthy builds, 0 incomplete jobs.** Every flag
reproduced three times out of three; no finding was flaky.

What it does and does not show:

- **It is the first discovery result on defects nobody tuned the discoverer to.** They were written
  after the freeze, by a separate session that never saw the discoverer's rules, and chosen by a
  seeded random draw from a list of sixteen candidate defects committed first.
- **Eight defects is a small sample.** 4 of 8 says the slice reaches some unseen defects; it does
  not estimate a rate.
- **The writer was not fully independent of us.** The prompt it followed was written by the session
  that built the discoverer, and it suggested the areas to draw from (walking, jumping, shooting,
  enemies, coins, collision, the camera and more), which include the four mechanics the profile
  covers. The writer was an AI agent, not a person.
- **The set's descriptions reached the discoverer's author before the run.** The freeze, verified by
  the run before it replayed anything, is what guarantees the discoverer did not change after that.
- **Which rules fired, and what each entry is, stay private until the event is over,** like the
  held-out bugs. The ids, kinds and flags above are what the run published.

## What the development results do and do not say

- **This is development reproduction, not discovery.** The profile's four claims (the double jump,
  the gun's cooldown, the sprite's facing, the enemies' patrol) and the probe families were written
  by the same team, on the same day, after reading the four bug reports, and the contract that catches
air-jump was added after the first jump contract missed it (next point). No bug report, patch, route
  or hand-written rule went into a run, and every threshold comes from the game's own code or from
  a twin probe, but the choice of what to profile was not blind. The record says so: its condition
  is `development-reproduction`, and it lists what was withheld.
- **The eight development bugs are the check on that.** Nobody wrote a claim for them. Ground contact
  (fall-through, sinking) is not in the profile, and the two visual families (missing texture,
  layering) cannot show in a trace at all; the verifier's approved checks and SAM already cover them.
  Expect misses there: they show the slice reaching only what the profile claims.
- **One contract we expected to catch air-jump did not, and its replacement was written after that
  miss.** The profile bounds the rise above the floor at two full jumps (260 px). The game cuts a
  jump short when the button is released, so short taps never come near it, with the bug or without.
  After seeing that on the air-jump build, we added a signal for the number of upward kicks in one
  stretch of air and switched the twin-probe relation to it (eight presses against two). That is
  tuning against the case, so the air-jump catch is the weakest of the four. The specification warns
  against counting impulses from position alone; on the clean game the count was 0 for one press and
  1 for two or more on all twelve jump probes at four positions, and never above 1 on any of the 22
  probes, and the relation compares two probes from the same spot rather than asserting a number. A
  moving platform, a slope or a stomp could still add a kick.
- **No frames.** Discovery replays headless and reads the trace only, about four times faster. The
  physics is identical (the traces match tick for tick; only the camera's view transform differs, and
  no contract reads it). A finding names its probes, so its replay can be rendered with frames.
- **Nothing is approved.** Every claim is `inferred_code` with no approval, so every contract is
  advisory. Promotion into the verifier (approval, validation against causal variants and
  feature-removal challenges, paired verdicts, signing) is the specification's next stage and is not
  built.
- **The four reported bugs are not the blind claim.** A blind-discovery claim needs fresh defects
  under a frozen protocol; the four public reproductions cannot provide it. Blind run 1 above is
  that test: 4 of 8, on a small set.

## What's next

In order, and none of it built yet unless it says so.

1. **The blind run.** Done once, planner off (above). The same frozen set can measure the planner:
   run it once more with the planner on, under the same freeze.
2. **The Muse Spark planner, live.** One call per job; its proposals go through the same reference
   check and reproduction. Measured against the planner-off run on the same builds.
3. **The rest of the autonomous-discovery specification.** The team's specification has three
   rollouts:
   - *Advisory* (this page is its first slice). Still to come: visual discovery (Muse Spark proposes
     the scene's entity classes, SAM 3.1 finds each, base and candidate compared on matched runs),
     planner rounds between episodes rather than one call, and integrity signals (crashes, fatal
     script errors, non-finite state, no progress) recorded apart from suspected gameplay defects.
   - *Promotion.* Each contract moves through proposed, reproduced, validated, shadow and approved or
     rejected, as append-only registry events. Validation needs at least ten clean runs across three
     healthy configurations, at least two faulty variants from distinct causes and one
     behaviour-preserving patch, guards that reject a fix which disables the feature, and
     applicability tests. A person approves the profile and its templates; a model's proposal never
     approves itself. Validated contracts then run in shadow beside the verifier.
   - *Enforcement.* A project opts in to verification v1 with a pinned contract set: paired verdicts
     against the failing base (repaired, preserved, regression, unresolved, inconclusive), repair
     requests for faults found in the trace rather than on screen, and signing of the exact scope.
     Only then can a discovered contract reject a change.
4. **What we would take from AI code review that runs code.** Greptile's TREX runs the code a pull
   request changes in a sandbox and attaches logs, screenshots and video to its review. Our Greptile
   strategy-adoption specification maps seven of its ideas onto Expectrail; their status:

   | Package | Status | What is left |
   | --- | --- | --- |
   | G01 Map a change to the behaviours it can affect | Not built | A small index of scenes, scripts and resources, linked to profile claims and probes, used to pick probes for a diff; compared with a planner that sees only the diff |
   | G02 One question per investigation | Partly: one planner call proposes probes and contracts | Typed hypotheses with stop conditions, and a ledger that reuses episodes |
   | G03 Confirm findings automatically | Mostly built: identities, not-exercised outcomes, 3-of-3 reproduction, reference falsification, the clean control, guards | Causal variants, feature-removal challenges and healthy variations per contract (the promotion validation above) |
   | G04 Evidence in the pull request | Partly: review pages with paired before-and-after verdicts ([review.md](review.md)), the morning report, CI summaries | A pull request comment with finding ids that stay stable across pushes, posted from a separate trusted step |
   | G05 Allocate models, replays and budget | Largely built: report-first escalation, the judge fallback ladder ([fallbacks.md](fallbacks.md)), job budgets, headless trace-only replays | One budget across planning, replays and judging |
   | G06 Scoped memory of team feedback | Not built | Typed feedback, with approved expectations kept apart from preferences |
   | G07 Import Greptile's findings | Not built | Read-only import of its review comments as hypotheses (GitHub comments, its MCP read tools, or its CLI's JSON output); kept only if it adds confirmed findings |

   G01 and G02 change the frozen planner, so they wait for the blind run. Every value claim in that
   specification (context improves detection, routing saves money, and so on) needs a measured
   comparison before we make it.

## Run it

```
export PATH="$PWD/tools/godot:$PATH"
python -m expectrail.discovery.cli discover --profile discovery/platformer.profile.json \
    --snapshot clean:reference --snapshot air-jump:base:bugs/reported/air-jump.patch \
    --out runs/discovery [--planner spark] [--probes jump-w0-x2,jump-w0-x8]
python -m expectrail.discovery.cli report runs/discovery/discovery-run.json
```

In CI: dispatch the Discovery workflow (planner `off` or `spark`; Spark needs `MODEL_API_KEY`), then
record it with `python -m expectrail.discovery.cli collect --run <id>`, which reads the jobs'
notices into `bench/discovery/`.
