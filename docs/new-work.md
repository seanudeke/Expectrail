# What we built during the event

The rules say the demo may only show work done during the event (October 26 to November 4, 2026).
This log, not the repository's creation date, is what shows it. Add a line when you land
something; keep prior work out of it.

## Prior work we use (not built during the event)

- `game/platformer`: Godot's official 2D platformer demo, imported unmodified (MIT). See
  [game/README.md](../game/README.md).
- Godot 4.7.2, Mesa and Xvfb, and the Meta models (SAM 3.1, Muse Spark, Muse Code) through their
  public interfaces.
- OBAAF (Apache-2.0), only if the organizers confirm in writing that an Indie entry may use it, and
  disclosed as prior open-source work by a team member.

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
