# macOS Local Interactive Runner

These scripts are strictly for **local manual running, playing, and visual inspection on macOS**.

> [!NOTE]
> The automated CI/CD pipeline, the verifier, and the agent repair loop do **not** use these scripts. The automated test pipeline runs headless on Linux using `harness/run.py` and `harness/get_godot.sh` under Xvfb and Mesa software OpenGL with deterministic route files.

---

### Quick Start

To launch and play the game locally on your Mac:

```sh
./harness/macos/play_local.sh
```

### What `play_local.sh` Does:
1. **Downloads the matching pinned Godot engine** (Godot 4.7.2 macOS universal binary) via `get_godot_mac.sh` into `tools/godot_mac/` if it is not already present.
2. **Removes macOS Gatekeeper quarantine attributes** (`xattr -cr`) to prevent OS launch warnings or execution blocks.
3. **Pre-imports project assets headlessly** (`--headless --import`) so all sprite sheets, fonts, audio, and `AnimationPlayer` libraries are compiled cleanly before the window opens.
4. **Launches the native macOS window** with direct keyboard and gamepad input.

---

### In-Game Controls

| Action | Keyboard | Gamepad |
| :--- | :--- | :--- |
| **Move Left / Right** | `A` / `D` or Left / Right Arrows | Left Stick / D-Pad |
| **Jump** | `W` or Up Arrow *(supports double jump)* | Bottom button (`A` / `Cross`) |
| **Shoot** | `Space` or `Z` | Left button (`X` / `Square`) |
| **Pause & Coin Counter** | `Escape` | Start button |
| **Toggle Fullscreen** | `F11` or `Alt + Enter` | — |

---

### Playing with a Seeded Bug

Pass `--patch <patch-file>` (repeatable) to copy the game into `runs/local_play`, apply the patch, and launch it without touching the clean game:

```sh
# 1. Physics fall-through (player drops through the ground):
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v1.patch
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v2.patch

# 2. Missing coin textures (coins are invisible):
./harness/macos/play_local.sh --patch bugs/missing-texture/v1.patch
./harness/macos/play_local.sh --patch bugs/missing-texture/v2.patch

# 3. Layering bug (player is hidden behind the scenery/background):
./harness/macos/play_local.sh --patch bugs/layering/v1.patch
./harness/macos/play_local.sh --patch bugs/layering/v2.patch

# 4. Seeded bug + candidate fix applied together:
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v1.patch --patch agents/fixtures/fix-collision-mask.patch
```

