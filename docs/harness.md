# Harness

The harness turns a route into frames a model can look at, the same way every time.

```sh
./harness/get_godot.sh                                   # Godot 4.7.2, checked against its SHA-512
python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke
python3 -m harness.run --route harness/routes/smoke.json --out runs/fall \
  --patch bugs/physics-fall-through/v1.patch             # with a seeded bug
python3 -m harness.run --route harness/routes/smoke.json --out runs/fixed \
  --patch bugs/physics-fall-through/v1.patch \
  --patch agents/fixtures/fix-collision-mask.patch     # seed then candidate (repeatable --patch)
python3 -m harness.replay_check --route harness/routes/smoke.json --runs 10

# Or run fully containerized (Docker / Linux container):
./harness/docker_run.sh                                  # 10-run replay check inside container
./harness/docker_run.sh python3 -m harness.run --route harness/routes/smoke.json --out runs/container-smoke
```

How it works:

1. It copies `game/platformer` to `<out>/work`, applies one or more patches in order (seed, then
   candidate), and adds `expectrail_harness.gd` to the copy as an autoload. The game in the
   repository never changes. Base asset imports are cached (`tools/godot_cache/.godot`), so clean
   runs skip the full-project re-import. The cache is keyed to the exact Godot binary and game files
   (`tools/godot_cache/.godot.key`) and is rebuilt when either changes; an import folder inside
   `game/platformer` (from the editor or a local play session) is never used. Frames are identical
   with and without the cache.
2. It imports any newly patched assets incrementally, then runs it under a virtual display
   (`xvfb-run`) with the Compatibility renderer on software OpenGL (Mesa llvmpipe). `--headless`
   cannot be used for capture: it does not render.
3. Godot's Movie Maker mode (`--write-movie`, `--fixed-fps 60`, `--disable-vsync`) writes every
   frame to a PNG. It runs in non-real time, so a slow machine produces the same frames, more
   slowly, instead of dropping them.
4. The autoload presses and releases input actions on the exact physics ticks the route names, before
   any game node runs that tick, and a second node records the player's position after every node
   has moved. It writes `trace.json` and quits when the route ends.
5. `replay.json` records the route, the game tree digest, the patch, the engine and device, and the
   sha256 of every frame.

## What we measured on day one (October 26)

On a 2-core cloud container with no GPU (Mesa llvmpipe, LLVM 20), Godot 4.7.2:

- The demo renders correctly under Xvfb; a 240-tick route (2 seconds of game time, 120 frames)
  takes about 20 to 30 seconds including import, most of it PNG encoding.
- Ten runs of the smoke route produced bit-identical frames and identical player traces. That
  settles replay on one machine and one binary only: frames from a GPU machine will differ, so
  evidence and baselines must come from the same runner type.
- The seeded fall-through bug (`bugs/physics-fall-through/v1.patch`) shows the player below the
  ground line from about frame 8 to frame 20, then off screen. Ten runs with the bug were also
  bit-identical, so the failure reproduces the same way every time.

Not settled yet: the input driver for gamepad-style analog input (routes only press actions), and
resetting mid-run (each run starts the game fresh, which takes a few seconds).

## Seeded bugs must be visible

```sh
python3 -m harness.check_seeded            # replays every bugs/<family>/v*.patch against the clean route
```

Each seeded variant must change at least one frame compared with the clean game; otherwise it is a
bug nobody could see, and the benchmark would count it as a miss. CI runs this as `seeded-bugs`.

## Routes

Routes (`expectrail.route/v0`) define exact sequences of physics ticks and input actions to replay deterministically across clean and patched builds:

| Route | File | Ticks | Description |
| :--- | :--- | :--- | :--- |
| `smoke` | `harness/routes/smoke.json` | 240 | Basic forward movement and two jumps (quick pipeline sanity check). |
| `coins` | `harness/routes/coins.json` | 240 | Traverses ground coin clusters, jumps into the coin arc, and verifies coin pickup and visibility. |
| `combat` | `harness/routes/combat.json` | 180 | Forward movement with weapon fire (`shoot`) against the enemy patrol, leap avoidance, and stop. |
| `traversal` | `harness/routes/traversal.json` | 360 | Vertical traversal across elevated and one-way platforms, exercising camera tracking and player layering. |

