# Future work: known limits and what comes next

Nightshift is a ten-day hackathon build. It works end to end on one Godot demo game, along scripted
routes, with bugs we seeded ourselves. This page says plainly what it does not do yet and what we
would build next, so anyone judging or extending it knows where the edges are.

## What it is today

- One game: Godot's 2D platformer demo, one level.
- One way to play: scripted routes, replayed on exact physics ticks.
- Three bug families with four seeded variants each, plus clean runs ([evaluation plan](evaluation.md)).
- Four visual assertion types: visible, inside-region, never-crosses and reaches.
- A fixer that writes small patches in its own container, a separate verifier, and a person who
  approves the release candidate.

## Finding bugs

**It replays; it does not explore.** A route is a fixed list of inputs. A bug that only shows up
where the route never goes stays invisible, so today Nightshift is closer to visual regression
testing than to playtesting.

Next:
- Record routes from human playtest sessions. The harness already replays inputs on exact ticks;
  recording them is the missing half.
- Take routes from exploring agents and from bug reports filed by testers or playtesting tools, and
  keep each one as a regression route.
- Report coverage: which levels, states and objects a night actually exercised.

**Coverage depends on the specs someone writes.** Every check starts as one sentence a person writes
and approves. Nothing checks what nobody thought to describe.

Next:
- Have Muse Spark draft specs from design documents and past bug tickets, still approved by a person.
- Grow a spec library for common bug families: the three we have, then text overflow, softlocks and
  motion jitter, which the evaluation plan already defers.

**Four assertion types.** Enough for falls, missing textures and layering, not for timing or UI.

Next: timing ("within N frames"), counts, contact between objects, state changes, UI text that fits
its box, and audio cues.

## Judging what it sees

**SAM 3.1 on pixel art is not measured yet.** The demo game is pixel art, and how well SAM finds
small sprites there is an open question.

Next:
- Score SAM's observations against the position log the harness already records, on each art style,
  before trusting its verdicts.
- Keep the rule that a missing or uncertain object means "needs review", never a pass.

**Determinism is proven on one setup.** Ten replays were bit-identical on a Linux machine with no GPU
and software rendering. Still untested: GPU rendering, multithreaded physics, network play, and
randomness the game does not seed.

Next: replay every failing route several times before reporting it, flag routes whose results
change between runs, and keep a baseline per platform.

## Fixing

**Fixes are small and local.** The seeded bugs are one-line regressions, and the fixer gets a short
budget for small patches.

Next: multi-file fixes, a root-cause note in the morning report, and a link to the commit that
introduced the bug.

**"Accepted" means it passed our suite, not that the game is correct.** The held-out variants are
bugs we seeded ourselves.

Next:
- Reproduce real, historical bugs from open-source Godot games and compare Nightshift's fix with
  the one the maintainers shipped.
- Mutation-test the suite: if a deliberately broken fix passes, the suite is too weak.
- Longer gameplay routes, with a person keeping the final say.

## Running it for real

**Godot only, with a harness inside the engine.** Studios on Unity or Unreal can't use it, and some
teams can't add a harness to their build.

Next: harness adapters for Unity and Unreal using their fixed-frame-rate capture, plus a capture mode
that needs no engine changes, labeled as weaker on determinism.

**Cost and scale are not measured.** We run one level a few times a night.

Next: measure cost per route per night, run routes in parallel on cloud machines without GPUs,
sample frames instead of sending every one, and skip routes a change cannot affect.

**It runs from the command line.**

Next: CI integrations, the morning report as a pull request comment, export to issue trackers, and
release pipelines that check a release candidate's signature before shipping it.

**The trust test is one planted instruction.**

Next: a set of poisoned assets instead of one, network access denied by default in the fixer's
container, and provenance for every artifact a night produces.

## Helping

To work on any of these, open an issue that names the section.
