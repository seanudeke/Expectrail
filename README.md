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

Status: Agents offline Gate-2 film path is in-repo (orchestrator → fixer → verifier → morning/RC
→ overnight rollup/trust). SAM 3.1 observations go through the Meta Model API
([docs/sam.md](docs/sam.md)); the first live run and calibration on our frames (Zayyad) and real
held-out variants (Sean) still come next for the evaluation matrix. See [docs/new-work.md](docs/new-work.md) and
[agents/demo-path.md](agents/demo-path.md).

Known limits and what we would build next: [docs/future-work.md](docs/future-work.md).

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
