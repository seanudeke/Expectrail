# Seeded bugs

The bugs in this table were written by the team ("seeded"). [`reported/`](reported/README.md) holds
the other kind: reproductions of publicly reported Godot bugs, two fixed upstream in this demo and
two reported in other developers' Godot games, each with its source, its own route and its result
in [`bench/reported/`](../bench/reported/README.md).

Each bug is a small patch against `game/platformer`, applied by the harness to a copy of the game
(`python3 -m harness.run --patch bugs/<family>/<variant>.patch ...`). The game directory itself
always stays clean. Every family gets four variants and matched clean runs; some variants are held
out from development and from the fixer.

| Family | Variant | What breaks | Assertion type |
| --- | --- | --- | --- |
| physics-fall-through | v1 | The player's collision mask drops the ground layer (30 to 14), so the player falls through the ground but still lands on platforms | never-crosses |
| physics-fall-through | v2 | The ground tiles in `level/tileset.tres` lose their collision layer (16 to 0) | never-crosses |
| missing-texture | v1 | The coin's texture reference in `level/coin.tscn` points to a missing file (`coin_missing.webp`) and has lost its UID, so Godot cannot fall back to the real texture | visible |
| missing-texture | v2 | The coin's texture assignment in `level/coin.tscn` is cleared | visible |
| layering | v1 | The player's `z_index` in `game_singleplayer.tscn` drops behind the level art (3 to -3) | visible |
| layering | v2 | The player's sprite in `player/player.tscn` gets `z_index = -6`, so it draws behind the level art (same symptom as v1, different file and node) | visible |
| sinking | v1 | The player's collision shape in `player/player.tscn` sits 26 px too high, so the robot rests 26 px inside the ground and still walks normally | never-crosses (position log and SAM hybrid) |
| sinking | v2 | The player's sprite in `player/player.tscn` is drawn 26 px too low; physics is unchanged, so only a visual check can see the robot inside the ground | never-crosses (SAM hybrid only) |

Every variant here must change what the player sees: `python3 -m harness.check_seeded` replays each one and fails if its frames match the clean game (CI job `seeded-bugs`). It replays `bugs/<family>/v*.patch` on the smoke route only, so the reported bugs, most of which need their own route, are named differently and checked by the reported-bug bench instead.

Held-out variants do not live in this repository until the event ends; keep them where the fixer
cannot read them (see docs/contracts.md).
