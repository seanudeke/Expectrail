"""The generic probe library: reusable ways to exercise a platformer, not recipes for known bugs.

Each probe is a bounded action program (expectrail/discovery/route_compiler.py) built only from the
profile's action catalog. The families are the ones a tester uses on any platformer: wait a long
time, hold each direction, reverse, tap an action at several rates, tap it once, twice or many times,
move while firing. Positions are a fixed sweep of walk durations, chosen in advance; none is aimed at
a place where a known bug shows.

Some families come in twins for relations: the same probe with one thing changed (more presses,
faster taps, the other direction). ``pairs()`` names them; the relation templates compare a signal
between the two.
"""
from __future__ import annotations

WALK_SWEEP = (0, 40, 80, 120)    # ticks of walking right before the jump taps: a fixed, even sweep
JUMP_COUNTS = (1, 2, 8)          # one press, the double jump, and many more
JUMP_EVERY = 20                  # ticks between jump taps
TAP_TICKS = 4
SHOT_RATES = (48, 12)            # ticks between shoot taps: slower than any plausible cooldown, and fast
SHOT_WINDOW = 144                # 1.2 s of tapping
LONG_WAIT = 1080                 # nine seconds: several enemy patrol turns


def _tap(action: str) -> dict:
    return {"op": "tap", "action": action, "durationTicks": TAP_TICKS}


def _taps(action: str, count: int, every: int) -> dict:
    return {"op": "repeat", "count": count,
            "body": {"op": "sequence", "steps": [_tap(action), {"op": "wait", "durationTicks": every - TAP_TICKS}]}}


def _taps_flat(action: str, count: int, every: int) -> dict:
    """The same taps written out, for use inside ``parallel`` within the three-level nesting cap."""
    steps: list[dict] = []
    for _ in range(count):
        steps += [_tap(action), {"op": "wait", "durationTicks": every - TAP_TICKS}]
    return {"op": "sequence", "steps": steps}


def _walk(direction: str, ticks: int) -> list[dict]:
    return [{"op": "hold", "action": f"move_{direction}", "durationTicks": ticks}] if ticks else []


def library(actions) -> list[dict]:
    """Every library probe the action catalog supports: {id, family, description, program, tags}."""
    actions = set(actions)
    probes: list[dict] = []

    def add(pid, family, description, steps, tags=()):
        program = steps[0] if len(steps) == 1 else {"op": "sequence", "steps": steps}
        probes.append({"id": pid, "family": family, "description": description, "program": program,
                       "tags": sorted(tags)})

    add("wait-long", "wait", "Stand still for nine seconds.", [{"op": "wait", "durationTicks": LONG_WAIT}],
        tags={"no-shoot", "long"})
    for d in ("right", "left"):
        if f"move_{d}" in actions:
            add(f"hold-{d}", "hold", f"Hold move_{d} for two seconds, then stop.",
                [*_walk(d, 240), {"op": "wait", "durationTicks": 30}], tags={"no-shoot", f"mirror-{d}"})
    if {"move_left", "move_right"} <= actions:
        add("reverse", "reverse", "Walk right, left, right, a second and a half each.",
            [*_walk("right", 90), *_walk("left", 90), *_walk("right", 90)], tags={"no-shoot"})
    if "jump" in actions and "move_right" in actions:
        for walk in WALK_SWEEP:
            for n in JUMP_COUNTS:
                add(f"jump-w{walk}-x{n}", "jump-taps",
                    f"Walk right for {walk} ticks, stop, then press jump {n} times, every {JUMP_EVERY} ticks.",
                    [*_walk("right", walk), {"op": "wait", "durationTicks": 10}, _taps("jump", n, JUMP_EVERY)],
                    tags={"no-shoot", f"jump-w{walk}", f"jump-x{n}"})
    if "shoot" in actions:
        for facing, pre in (("right", []), ("left", _walk("left", 12))):
            for every in SHOT_RATES:
                add(f"shoot-{facing}-every{every}", "shoot-rate",
                    f"Face {facing}, stand still, tap shoot every {every} ticks for 1.2 s.",
                    [*pre, {"op": "wait", "durationTicks": 20}, _taps("shoot", SHOT_WINDOW // every, every)],
                    tags={f"shoot-{facing}", f"every{every}"})
        for d in ("right", "left"):
            if f"move_{d}" in actions:
                add(f"move-fire-{d}", "move-and-fire",
                    f"Walk {d} while tapping shoot, stop, then tap shoot twice standing still.",
                    [{"op": "parallel", "branches": [_walk(d, 120)[0], _taps_flat("shoot", 3, 40)]},
                     {"op": "wait", "durationTicks": 30}, _taps("shoot", 2, 48)], tags={f"mirror-{d}"})
    return probes


def pairs(probes: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Twin probes for each relation template: (left, right)."""
    ids = {p["id"] for p in probes}
    out: dict[str, list[tuple[str, str]]] = {"extra-air-presses": [], "air-jump-exists": [], "faster-taps": [],
                                              "mirror": []}
    for walk in WALK_SWEEP:
        if {f"jump-w{walk}-x2", f"jump-w{walk}-x8"} <= ids:
            out["extra-air-presses"].append((f"jump-w{walk}-x2", f"jump-w{walk}-x8"))
        if {f"jump-w{walk}-x1", f"jump-w{walk}-x2"} <= ids:
            out["air-jump-exists"].append((f"jump-w{walk}-x1", f"jump-w{walk}-x2"))
    for facing in ("right", "left"):
        slow, fast = f"shoot-{facing}-every{SHOT_RATES[0]}", f"shoot-{facing}-every{SHOT_RATES[1]}"
        if {slow, fast} <= ids:
            out["faster-taps"].append((slow, fast))
    if {"hold-right", "hold-left"} <= ids:
        out["mirror"].append(("hold-right", "hold-left"))
    if {"move-fire-right", "move-fire-left"} <= ids:
        out["mirror"].append(("move-fire-right", "move-fire-left"))
    return out
