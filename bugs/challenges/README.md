# Shortcut fixes and healthy retunes

Challenges for discovery's guards ([docs/discovery.md](../../docs/discovery.md)). A guard is a
contract that the feature still works: the double jump still lifts, a ready press still fires, the
enemies are still there and still patrol. A fix that makes a reported symptom go away by disabling
the feature should trip one; a deliberate retune should trip nothing. Each is a patch against the
clean game, run as its own build in the **Discovery** workflow.

| Patch | Kind | What it does | Expected |
| --- | --- | --- | --- |
| `shortcut-no-double-jump.patch` | shortcut | Removes the air jump, so jumping in mid-air can never happen again (a "fix" for unlimited air jumps) | flagged by `jump-air-jump-exists` |
| `shortcut-gun-never-fires.patch` | shortcut | Inverts the cooldown check, so the gun never fires (a "fix" for the gun ignoring its cooldown) | flagged by `weapon-ready-press-fires` |
| `shortcut-no-turning.patch` | shortcut | Removes the sprite flip, so the robot always faces right (a "fix" for flipping the whole body) | flagged by `facing-follows-motion` |
| `shortcut-enemies-stand-still.patch` | shortcut | Sets the enemies' walking speed to 0 (a "fix" for enemies walking off ledges) | flagged by `enemy-patrols` |
| `healthy-faster-walk.patch` | healthy | The robot walks 10% faster (300 to 330 px/s) | no finding |
| `healthy-faster-enemies.patch` | healthy | Enemies patrol a little faster (22 to 26 px/s) | no finding |

We wrote these knowing the guards, so they show the guards do what they are for; they are not a
blind test. Result, run 41326269491: all four shortcuts flagged by the guard named above, neither
retune flagged ([docs/discovery.md](../../docs/discovery.md#shortcut-fixes-and-healthy-retunes-november-1)).
