# Nightshift

**An overnight crew of Meta models that plays a game build, sees what is broken, fixes it, and keeps
a fix only if checks the fixer cannot touch accept it.** Built for the Meta Global AI Developer
Hackathon (Indie track), October 26 to November 4, 2026.

Coding agents can make tests pass while the game is visibly broken, because most build pipelines
never check what players see. Nightshift checks:

1. **Play.** A harness replays a fixed route through the game and captures every frame, the same
   way every time.
2. **See.** Muse Spark turns a plain-English check ("the player never falls through the ground")
   into a structured test spec that a person approves once. SAM 3.1 finds and tracks the objects
   the spec names. A deterministic evaluator, not a model, decides pass or fail.
3. **Fix.** Muse Code gets the failing check, the replay and the evidence, and patches the game in
   a fixer worktree that does not mount the evaluator, held-out cases, or signing keys
   (deny-by-absence). Muse may still see other host paths on a shared filesystem; we do not claim
   an OS container here.
4. **Verify.** A separate verifier rebuilds, replays, and runs the regression, gameplay, held-out
   and clean checks. It accepts a candidate only if every check passes, and it rejects a fix that
   only looks right, such as one that stops the fall by freezing the player.
5. **Hand over.** By morning: before-and-after frames, the diff, unresolved cases, and a release
   candidate signed outside the fixer's reach, for a human to approve.

**Feedback goes in, but never straight to the fixer.** Muse Voice Transcribe turns a recorded
playtest into who-said-what. When Muse Spark sorts a remark as a bug and writes a one-line check
for it, that becomes a draft test spec that waits for a person's approval; raw speech never becomes
a spec. A request to weaken or switch off a check ("just turn the floor check off") is refused and
queued for a person, whether the fixed phrase rules or the model catch it. Inside the fixer, a
Muse Code hook blocks file-tool writes outside the editable files and logs every tool call (shell
commands are logged, not checked). The morning report lists both under "Feedback in" and "Refused
or blocked".
[docs/feedback-recording.md](docs/feedback-recording.md)

Status, October 30: the whole loop runs live, end to end: Wonder triage, Muse Code in a sandbox,
the Godot harness, the verifier with SAM 3.1 on the private held-out routes, the signed morning
report and the trust check. See [docs/new-work.md](docs/new-work.md) and
[agents/demo-path.md](agents/demo-path.md).

## Results

Every number here comes from a file in [`bench/`](bench), written from a CI run's own output, with
the command that reruns it. Four bug families (physics fall-through, missing texture, layering,
sinking), with two public development variants and two private held-out variants of each; the
detection benches replay every variant, and the clean game, on five routes.

| What we measured | Result | Run |
| --- | --- | --- |
| Held-out bugs caught, SAM 3.1 on | **8 of 8**, no false alarm on the clean game | [41003749744](https://github.com/seanudeke/Nightshift/actions/runs/41003749744) |
| Held-out bugs caught, Muse Glimmer checked against the engine, no SAM | **8 of 8**, no false alarm | [41003751876](https://github.com/seanudeke/Nightshift/actions/runs/41003751876) |
| Held-out bugs caught with no vision model (engine and gameplay checks only) | 4 of 8 | the same two runs |
| Development bugs caught: SAM on / Glimmer, no SAM / no vision | 8 of 8 / 8 of 8 / 3 of 8 | [40841977642](https://github.com/seanudeke/Nightshift/actions/runs/40841977642), [41001182605](https://github.com/seanudeke/Nightshift/actions/runs/41001182605) |
| Bad fixes that only look right, accepted by the judge (7 cases, 2 runs) | Nightshift with SAM **0 of 7**; Nightshift without SAM 3 of 7; Muse from screenshots 2 of 7 | [judge](bench/judge/README.md) |
| Good fixes accepted by the judge (8 cases, 2 runs) | Nightshift 8 of 8 both runs; Muse from screenshots 6 and 7 of 8 | [judge](bench/judge/README.md) |
| Development bugs fixed by Muse Code | 8 of 8 with Nightshift's evidence; 8 of 8 from screenshots alone | [fix matrix](bench/fix-matrix/README.md) |
| Demo path, live, end to end, 10 independent runs | **10 of 10 accepted**, each on the first attempt | [40990485265](https://github.com/seanudeke/Nightshift/actions/runs/40990485265) |
| Meta Model API spend, whole team, through October 29 | $204 (SAM images at list price are almost all of it) | [cost](bench/cost/README.md) |

What these numbers do and do not say:

- **The verifier is where Nightshift wins, not the fixer.** Muse Code fixes all 8 development bugs
  from screenshots alone, as well as with our evidence. What screenshots alone cannot do is judge:
  Muse from screenshots accepted 2 of 7 fixes that only look right (one lowers the floor, one sinks
  the robot) and turned down one or two good ones. Nightshift with SAM accepted none of the bad and
  all of the good, in both runs.
- **One held-out catch came after a miss.** The first held-out runs caught 7 of 8. The eighth
  (sinking/v4) draws the floor away from where it collides, and every check measured the robot
  against the collision. The ground check now also follows the floor as drawn. It was built after
  the miss, from the public game, without reading that variant's patch, so it is a check made for
  the class that was missed, not a blind catch ([docs/sam.md](docs/sam.md),
  [`bench/drawn-floor/`](bench/drawn-floor)).
- **Two families need vision.** Missing texture and layering pass every engine and gameplay check;
  only the vision checks catch them, on every route.

**Open weights.** Muse Glimmer 30B, on a Fireworks deployment, can judge every vision check with no
SAM key, checked against the game engine (`glimmer-engine`): 8 of 8 held-out and 8 of 8
development bugs caught, no false alarm, and on the held-out routes the real fix is accepted and the
hide-the-robot fix rejected. Muse Spark Open, on Baseten, drafts test specs and sorts playtester
feedback (`--endpoint open`, `--sorter open`). Live on October 30, its drafts of our three checks
were valid, and its ground draft gave the approved spec's verdict on all 9 seeded runs, after we
fixed a prompt that let it read the boundary the wrong way round. It sorted the scripted playtest
the way the rules do and flagged both requests to switch a check off. Its drafts still need a
person to tighten the object prompts, as Muse Spark's do ([`bench/spark-open/`](bench/spark-open)).
SAM 3.1 stays the default: Glimmer's boxes are too loose for the ground check, so without SAM the ground is
judged on the engine's position log, and a Glimmer bench takes about eight times the job minutes.
[docs/open-weights.md](docs/open-weights.md)

Known limits and what we would build next: [docs/future-work.md](docs/future-work.md).

## Interactive Hosted Demo

Explore the complete Gate 2 audit vault and interactive defect-fix explorer without spending Meta API credits:

- **Local Preview:**
  ```sh
  python3 -m http.server 8000 --directory docs/demo
  # Open http://localhost:8000 in your browser
  ```
- **Live / Static:** Open [`docs/demo/index.html`](docs/demo/index.html) directly in any modern browser.
- **Features:**
  - **Case Explorer:** Switch across all 8 development defect variants (physics fall-through, missing textures, layering, sinking) and 4 rejected anti-cheat exploits (freezing player, hiding player, sinking player, lowering the floor).
  - **Visual & HUD Simulation:** Inspect coordinate traces, floor boundaries, and SAM 3.1 segmentation masks.
  - **Audit Breakdown:** Complete 4-suite verifier checks (`regression`, `gameplay`, `clean`, `held-out`).
  - **Benchmark Matrix:** development set: 8 of 8 bugs caught with SAM, 3 of 8 without; 8 of 8 fixed both from screenshots and with Nightshift (see [`bench/`](bench)).
  - **Security & Trust:** Visualizes "Deny-by-absence" isolation and canary probe denials.
  - **Morning Report & Release Candidate:** 7:30 AM rollup and Ed25519 signature audit.

## Try it

Requires Python 3.10+, and for capture, Linux with `xvfb-run` and Mesa (no GPU needed).

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -t .                  # contracts and evaluator

./harness/get_godot.sh                                       # Godot 4.7.2, SHA-512 checked
python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke
python3 -m harness.run --route harness/routes/smoke.json --out runs/fall \
  --patch bugs/physics-fall-through/v1.patch                 # the same route with a seeded bug
python3 -m harness.replay_check --route harness/routes/smoke.json --runs 10

python3 -m nightshift.evaluator --spec contracts/examples/test-spec.json \
  --observations contracts/examples/observations.json       # decide a check

python3 -m agents.gate1 --out runs/gate1 --skip-harness \
  --observations agents/fixtures/obs-fixed.json             # repair → fix → verify
python3 -m agents.loop --out runs/loop --mode offline --runs 10
# → runs/loop/morning-report.md (rollup) + per-run before/after frames
python3 -m agents.trust --out runs/trust                    # signing key stays off the fixer

# Local Meta keys: copy .env.example → .env (gitignored) and set META_API_KEY / MODEL_API_KEY
python3 -m nightshift.spec_writer draft "The player never falls through the ground" --out /tmp/spec.json
python3 -m nightshift.spec_writer approve /tmp/spec.json --by <you>   # Muse Spark drafts; a person approves
python3 -m agents.feedback --offline --transcript agents/fixtures/feedback/playtest-transcript.json \
  --fixture agents/fixtures/feedback/spark-fixture.json --out runs/feedback   # feedback → draft specs
python3 -m agents.loop --out runs/loop --mode offline --feedback runs/feedback/feedback-intake.json
# Live feedback: python3 -m agents.feedback --audio playtest.wav --consent --out runs/feedback
python3 -m agents.film_feedback --out runs/film-feedback   # hostile-feedback beat → film.md
# Open weights: add --sorter open (Muse Spark Open on Baseten, BASETEN_API_KEY) to agents.feedback
# Live Muse film (clean prompt): python3 -m agents.prove_live --out runs/prove
# Live overnight path: python3 -m agents.loop --mode live
```

See [agents/README.md](agents/README.md) for Muse API / Muse Code setup (`.env`, `META_API_KEY`).

## Layout and lanes

| Path | What | Lane |
| --- | --- | --- |
| [`contracts/`](contracts) | Schemas and examples for everything passed between lanes ([docs](docs/contracts.md)) | everyone |
| [`harness/`](harness) | Route player, Movie Maker capture under Xvfb, replay check ([docs](docs/harness.md)) | Timo |
| [`nightshift/`](nightshift) | Contract helpers, the reference evaluator, and the Muse Spark spec writer | Zayyad, Sean |
| [`specs/`](specs) | Test specs for the bug families; a person approves each one | Sean |
| [`bugs/`](bugs) | Seeded bugs as patches against the clean game ([evaluation plan](docs/evaluation.md)) | Sean, Timo |
| [`docs/demo/`](docs/demo/) | Interactive demo showcase and audit vault web app | Timo |
| [`game/`](game) | Godot's 2D platformer demo, unmodified (MIT) | prior work |
| [`agents/`](agents) | Repair requests, Muse Code fixer, verifier, Wonder triage, morning report | Taofeek |

## Gates

- **Gate 1, October 28:** one seeded bug caught by a visual assertion, fixed by Muse Code in a
  fixer worktree without verifier secrets mounted, and accepted by the protected verifier, end to
  end on one level.
- **Gate 2, November 1:** three bug families with four variants each, clean and held-out cases, the
  benchmark against a Muse Code with screenshots baseline, the morning report, and a demo path that
  passes 10 runs in a row.

## Prior work and rules

The game is Godot's MIT-licensed demo, imported unmodified in its own commit
([game/README.md](game/README.md)). Seeded bugs and fixes are patches, never edits to the clean
game. Everything else in this repository was written during the event, and
[docs/new-work.md](docs/new-work.md) lists it by date.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for third-party work.
