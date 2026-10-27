# The game under test

`platformer/` is Godot's official 2D platformer demo, imported unmodified in its own commit so that
anyone can see exactly what we changed during the event.

| | |
| --- | --- |
| Source | https://github.com/godotengine/godot-demo-projects/tree/4.7-6ad6167/2d/platformer |
| Tag and commit | `4.7-6ad6167`, `6ad6167e0577fe3622c18546138f456b107ce93c` |
| Engine | Godot 4.7.2 stable (Compatibility renderer, OpenGL 3) |
| License | MIT, see [LICENSE-godot-demo-projects.md](LICENSE-godot-demo-projects.md) |

Seeded bugs are never committed to this directory. The harness copies the game into a work
directory and applies a seeded-bug patch there, so the clean game stays clean and every bug is a
small, reviewable diff (see `bugs/`).
