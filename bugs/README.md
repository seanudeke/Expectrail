# Seeded bugs

Each bug is a small patch against `game/platformer`, applied by the harness to a copy of the game
(`python3 -m harness.run --patch bugs/<family>/<variant>.patch ...`). The game directory itself
always stays clean. Every family gets four variants and matched clean runs; some variants are held
out from development and from the fixer.

| Family | Variant | What breaks | Assertion type |
| --- | --- | --- | --- |
| physics-fall-through | v1 | The player's collision mask drops the ground layer (30 to 14), so the player falls through the ground but still lands on platforms | never-crosses |

Held-out variants do not live in this repository until the event ends; keep them where the fixer
cannot read them (see docs/contracts.md).
