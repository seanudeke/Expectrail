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
