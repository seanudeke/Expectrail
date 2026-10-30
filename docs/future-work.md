# Future work: known limits and what comes next

Expectrail is meant to be an independent verification layer for changes made by AI coding agents:
the agent that writes a change never certifies it. This is a ten-day hackathon build of that idea on
one Godot demo game, along scripted routes, with bugs we seeded ourselves. This page says plainly
what it does not do yet and what we would build next, so anyone judging or extending it knows where
the edges are. The last section says which parts would carry over beyond games.

## What it is today

- One game: Godot's 2D platformer demo, one level.
- One way to play: scripted routes, replayed on exact physics ticks.
- Four bug families (physics fall-through, missing texture, layering, sinking), with two public
  development variants and two private held-out variants each, plus the clean game
  ([evaluation plan](evaluation.md), results in [`bench/`](../bench)).
- One kind of agent change: repairs of a reported bug.
- Four visual assertion types: visible, inside-region, never-crosses and reaches.
- A fixer that writes small patches in its own worktree, inside bubblewrap in the live runs (only
  the worktree mounted; network on, because it calls Meta's API) and deny-by-absence without it (a
  worktree that does not contain the verifier's files), a separate verifier, and a person who
  approves the release candidate.

## Finding bugs

**It replays; it does not explore.** A route is a fixed list of inputs. A bug that only shows up
where the route never goes stays invisible, so today Expectrail is closer to visual regression
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

**The observers are measured on one art style.** SAM 3.1 finds the robot and the coins in this
game's pixel art on every clean frame, but it does not see the ground at all, and "small robot"
also matches the enemies ([docs/sam.md](sam.md)). Muse Glimmer's boxes are too loose for the ground
check ([docs/open-weights.md](open-weights.md)). The engine's position log covers what the models
cannot, but only for objects the harness logs (the robot and the coins).

Next:
- Score the observers against the position log on each new art style before trusting their verdicts.
- Log more objects from the engine, so a check about an enemy or a door is not needs-review.
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
- Reproduce real, historical bugs from open-source Godot games and compare Expectrail's fix with
  the one the maintainers shipped.
- Mutation-test the suite: if a deliberately broken fix passes, the suite is too weak.
- Longer gameplay routes, with a person keeping the final say.

## Running it for real

**Godot only, with a harness inside the engine.** Studios on Unity or Unreal can't use it, and some
teams can't add a harness to their build.

Next: harness adapters for Unity and Unreal using their fixed-frame-rate capture, plus a capture mode
that needs no engine changes, labeled as weaker on determinism.

**Scale is not measured.** On one level, a verified fix takes 12 to 22 minutes and about $3 of SAM
images ([`bench/demo-loop/`](../bench/demo-loop/README.md)); nobody has run it on a real project's
worth of routes.

Next: run routes in parallel on cloud machines without GPUs, sample frames instead of sending every
one, and skip routes a change cannot affect.

**It runs from GitHub Actions workflows and the command line, on our repository.**

Next: a CI gate any repository can add, the verdict and evidence as a pull request comment, export to
issue trackers, and release pipelines that check a release candidate's signature before shipping it.

**The trust test is one planted instruction plus a canary probe.**

Next: a set of poisoned assets instead of one, stronger default network denial inside the fixer
sandbox on every host (not only when bwrap/docker is present), and provenance for every artifact a
night produces.

## Beyond games

The north star is any change an agent makes to any software, verified by something the agent does
not control. We have built and measured game repairs, and one web page as a second domain
(below). What we expect to carry over, and what would have to be rebuilt:

| Part | Carries over? |
| --- | --- |
| The agent cannot reach the checks, the held-out cases or the signing key | Yes: it is a property of where things are mounted, not of games |
| Evidence comes from running the changed software, not from the diff or the agent's account of it | Yes, given a way to run the software the same way every time |
| A person approves each check, written as one plain sentence and drafted by a model | Yes |
| Held-out cases the fixer never sees, and a clean control that must not raise a false alarm | Yes |
| Acceptance signed outside the agent's reach, checked before release | Yes |
| A missing or uncertain observation is "needs review", never a pass | Yes |
| The Godot harness and its exact-tick replay | No: each kind of software needs its own way to replay |
| Vision checks on game frames, and the engine's position log | No: these are this domain's evidence |

The closest next domain was a web interface, and we have built one, a checkout page, as supporting
evidence ([`apps/checkout`](../apps/checkout); results in the README's "Beyond games").

- **What was reused.** The evaluator, the contracts, the decision rule, the fixer and its sandbox,
  and the judge were reused unchanged.
- **What was rebuilt.** As the table above predicts, the rebuilt parts were the replay and the
  domain's evidence:
  - Chromium replays a recorded checkout session, as the Godot harness replays a route
    ([`harness/web`](../harness/web)).
  - The page's layout boxes stand in for the engine's position log.
  - Whether the order went through stands in for the gameplay check.
- **What it does not yet have.** Held-out web variants, the live repair loop, and checks written by
  anyone outside the team.

Further out are backend and infrastructure changes, where the evidence is logs, metrics and
responses rather than pixels. None of that is built.

## Helping

To work on any of these, open an issue that names the section.
