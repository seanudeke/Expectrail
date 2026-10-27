# Harness

The harness turns a route into frames a model can look at, the same way every time.

```sh
./harness/get_godot.sh                                   # Godot 4.7.2, checked against its SHA-512
python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke
python3 -m harness.run --route harness/routes/smoke.json --out runs/fall \
  --patch bugs/physics-fall-through/v1.patch             # with a seeded bug
python3 -m harness.replay_check --route harness/routes/smoke.json --runs 10
```

How it works:

1. It copies `game/platformer` to `<out>/work`, applies the patch to the copy if one is given, and
   adds `nightshift_harness.gd` to the copy as an autoload. The game in the repository never changes.
2. It imports the project headless, then runs it under a virtual display (`xvfb-run`) with the
   Compatibility renderer on software OpenGL (Mesa llvmpipe). `--headless` cannot be used for
   capture: it does not render.
3. Godot's Movie Maker mode (`--write-movie`, `--fixed-fps 60`) writes every frame to a PNG. It runs
   in non-real time, so a slow machine produces the same frames, more slowly, instead of dropping
   them.
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
  ground line from about frame 8 to frame 20, then off screen.

Not settled yet: the input driver for gamepad-style analog input (routes only press actions), and
resetting mid-run (each run starts the game fresh, which takes a few seconds).
