# What we built during the event

The rules say the demo may only show work done during the event (October 26 to November 4, 2026).
This log, not the repository's creation date, is what shows it. Add a line when you land
something; keep prior work out of it.

## Prior work we use (not built during the event)

- `game/platformer`: Godot's official 2D platformer demo, imported unmodified (MIT). See
  [game/README.md](../game/README.md).
- Godot 4.7.2, Mesa and Xvfb, and the Meta models (SAM 3.1, Muse Spark, Muse Code) through their
  public interfaces.
- [OBAAF](https://github.com/Obaaf/OBAAF) (Apache-2.0): prior open-source work by a team member (Sean),
  published before the event. It will run underneath Nightshift as a dependency (recording and
  signing the release candidate) and is not wired in yet; nothing in Nightshift itself predates the
  event. The organizers said on the October 27 call that prior open-source work
  may be used if it is disclosed; we have asked for that in writing.

## Log

| Date | What | Where |
| --- | --- | --- |
| Oct 26 | Repository, license, unmodified game import | `LICENSE`, `NOTICE`, `game/` |
| Oct 26 | Seven lane contracts with schemas and examples | `contracts/`, `docs/contracts.md` |
| Oct 26 | Capture harness: route player, Movie Maker capture under Xvfb, replay check | `harness/` |
| Oct 26 | Reference evaluator for four assertion types, with tests | `nightshift/`, `tests/` |
| Oct 26 | First seeded bug: physics fall-through, variant 1 | `bugs/physics-fall-through/` |
| Oct 26 | CI: tests and a capture smoke test on a GPU-less runner | `.github/workflows/ci.yml` |
| Oct 26 | Agents lane Gate 1: orchestrator, Muse Code fixer, multi-patch verifier, freeze-player reject | `agents/`, `harness/run.py` |
| Oct 26 | Agents lane Gate 2: Wonder triage, morning report, trust beat, 10-run loop CI | `agents/triage.py`, `report.py`, `trust.py`, `loop.py` |
| Oct 26 | Harness-backed agents verify on Linux CI (accept / freeze reject / seed fail) | `.github/workflows/ci.yml` `agents-harness-verify` |
| Oct 27 | Evaluation plan: three bug families, held-out variants, ground truth, gameplay checks | `docs/evaluation.md` |
| Oct 27 | Test specs for the first three families (drafts awaiting approval) | `specs/` |
| Oct 27 | Muse Spark spec writer: plain English to a validated test spec, then human approval | `nightshift/spec_writer.py` |
| Oct 26 | Overnight loop auto/live/offline + filmable trust evidence | `agents/loop.py`, `agents/keys.py`, `agents/trust.py` |
| Oct 26 | Filmable morning report: before/after frames + overnight rollup | `agents/report.py`, `agents/loop.py`, `agents/fixtures/frames/` |
| Oct 27 | Verifier suite completeness: clean + held-out kinds in decide() | `nightshift/evaluator.py`, `agents/verifier.py`, `agents/fixtures/obs-clean.json` |
| Oct 27 | Harness clean-replay abort falls back to fixture clean obs | `agents/verifier.py` |
| Oct 27 | Suite provenance + trust deny-by-absence for clean/held-out/evaluator | `agents/isolation.py`, `agents/verifier.py`, `agents/trust.py` |
| Oct 27 | Trace-native gameplay gate (min Δx / end-on-floor / below-ground) | `agents/gameplay.py`, `agents/verifier.py`, `agents/fixtures/trace-*.json` |
| Oct 27 | Gameplay-verdict contract + filmable morning Gameplay section | `contracts/gameplay-verdict.schema.json`, `agents/report.py` |
| Oct 27 | Honest motion check id, filmable overnight gameplay rollup, RC contract | `agents/verifier.py`, `agents/report.py`, `contracts/release-candidate.schema.json` |
| Oct 27 | Overnight summary contract, wall-clock/cost stubs, RR→RC bind, demo package | `contracts/overnight-summary.schema.json`, `agents/loop.py`, `agents/bench.py`, `bench/` |
| Oct 27 | Film/operability hardening: sources, trust film, harness morning, multi-gameplay fail-closed | `agents/report.py`, `agents/isolation.py`, `.github/workflows/ci.yml` |
| Oct 27 | Film honesty: needs-review rollup, RC verify, RR triage provenance, Gate1 morning | `agents/report.py`, `agents/gate1.py`, `agents/triage.py` |
| Oct 27 | Automate live Muse accept + trust canary denial film (`prove_live`, canary probe, dispatch CI) | `agents/prove_live.py`, `agents/trust.py`, `.github/workflows/ci.yml` |
| Oct 27 | Future work: known limits and next steps | `docs/future-work.md` |
| Oct 27 | Fall-through spec approved by Sean (coins and player-visible held until their bugs and SAM numbers exist) | `specs/player-stays-above-ground.json` |
| Oct 27 | Clean-v1 Muse prompt (no answer leak), gitignored `.env`, Muse env scrub, honest deny-by-absence docs | `agents/fixer.py`, `agents/keys.py`, `README.md`, `docs/contracts.md` |
| Oct 27 | Live Muse Code v1 film under clean-v1 (muse.log + prove package) | `bench/live-muse-clean-v1/` |
| Oct 27 | Real held-out check: verifier replays candidates on private held-out routes (`NIGHTSHIFT_HELDOUT_DIR`), CI fetch via secret, held-out variants v3/v4 in the private repo | `agents/verifier.py`, `.github/workflows/ci.yml`, `docs/evaluation.md` |
| Oct 27 | Bounded Muse retries, daily E2E, OS sandbox canary, future-work honesty scrub | `agents/loop.py`, `agents/daily.py`, `agents/sandbox.py` |
| Oct 27 | CI contract: never put `secrets.*` in job-level `if` (workflow start failure) | `tests/test_agents.py`, `.github/workflows/ci.yml` |
