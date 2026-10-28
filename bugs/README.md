# Seeded bugs

Each bug is a small patch against `game/platformer`, applied by the harness to a copy of the game
(`python3 -m harness.run --patch bugs/<family>/<variant>.patch ...`). The game directory itself
always stays clean. Every family gets four variants and matched clean runs; some variants are held
out from development and from the fixer.

| Family | Variant | What breaks | Assertion type |
| --- | --- | --- | --- |
| physics-fall-through | v1 | The player's collision mask drops the ground layer (30 to 14), so the player falls through the ground but still lands on platforms | never-crosses |
| physics-fall-through | v2 | The ground tiles in `level/tileset.tres` lose their collision layer (16 to 0) | never-crosses |
| missing-texture | v1 | The coin's texture path in `level/coin.tscn` points to a missing file (`coin_missing.webp`) | visible |
| missing-texture | v2 | The coin's texture assignment in `level/coin.tscn` is cleared | visible |
| layering | v1 | The player's `z_index` in `game_singleplayer.tscn` drops behind the level art (3 to -3) | visible |
| layering | v2 | The player's `z_index` drops to -3 and `z_as_relative` is set to false | visible |

Held-out variants do not live in this repository until the event ends; keep them where the fixer
cannot read them (see docs/contracts.md).
