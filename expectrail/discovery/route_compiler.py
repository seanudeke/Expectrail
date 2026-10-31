"""Compile a bounded action program into an exact expectrail.route/v0.

A probe is a small program, from the probe library or from the planner, never code:

    {"op": "tap", "action": "jump", "durationTicks": 4}
    {"op": "hold", "action": "move_right", "durationTicks": 90}
    {"op": "wait", "durationTicks": 20}
    {"op": "sequence", "steps": [...]}
    {"op": "parallel", "branches": [a, b]}            # at most two, from the same cursor
    {"op": "repeat", "count": 8, "body": {...}}         # an addition: compact repeats, count <= 32

The compiler keeps an integer cursor in physics ticks. A tap or a hold presses at the cursor,
releases after ``durationTicks`` and advances; a wait advances. ``parallel`` compiles both branches
from the same cursor and advances to the later end; two branches may not drive the same action.
Every episode starts with every action released and ends released. Unknown actions, non-positive
durations, nesting deeper than three levels, contradictory transitions on one tick, and routes over
the tick or event caps are refused: a model supplies parameters, never a schedule of its own.
"""
from __future__ import annotations

from expectrail.contracts import validate

LEAD_TICKS = 10          # the game settles for a few ticks before input counts
TAIL_TICKS = 60          # half a second after the last release, so landings and bullets finish
MAX_TICKS = 1800         # 15 s of physics at 120 ticks a second
MAX_EVENTS = 256
MAX_DEPTH = 3
MAX_REPEAT = 32
OPS = ("tap", "hold", "wait", "sequence", "parallel", "repeat")


class ProgramError(ValueError):
    pass


def _positive_int(node: dict, key: str) -> int:
    value = node.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProgramError(f"{node.get('op')}: {key} must be a positive integer, got {value!r}")
    return value


def _compile(node, cursor: int, depth: int, actions: frozenset[str], events: list) -> tuple[int, set[str]]:
    """Append events for ``node`` starting at ``cursor``; return (new cursor, actions it drives)."""
    if not isinstance(node, dict) or node.get("op") not in OPS:
        raise ProgramError(f"unknown instruction {node!r:.80}")
    allowed = {"tap": {"op", "action", "durationTicks"}, "hold": {"op", "action", "durationTicks"},
               "wait": {"op", "durationTicks"}, "sequence": {"op", "steps"}, "parallel": {"op", "branches"},
               "repeat": {"op", "count", "body"}}[node["op"]]
    extra = set(node) - allowed
    if extra:
        raise ProgramError(f"{node['op']}: unexpected fields {sorted(extra)}")
    op = node["op"]
    if op in ("tap", "hold"):
        action = node.get("action")
        if action not in actions:
            raise ProgramError(f"{op}: {action!r} is not in the approved action catalog")
        d = _positive_int(node, "durationTicks")
        events.append({"tick": cursor, "action": action, "pressed": True})
        events.append({"tick": cursor + d, "action": action, "pressed": False})
        return cursor + d, {action}
    if op == "wait":
        return cursor + _positive_int(node, "durationTicks"), set()
    if depth >= MAX_DEPTH:
        raise ProgramError(f"nesting deeper than {MAX_DEPTH} levels")
    if op == "sequence":
        steps = node.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ProgramError("sequence: steps must be a non-empty list")
        driven: set[str] = set()
        for step in steps:
            cursor, used = _compile(step, cursor, depth + 1, actions, events)
            driven |= used
        return cursor, driven
    if op == "repeat":
        count = _positive_int(node, "count")
        if count > MAX_REPEAT:
            raise ProgramError(f"repeat: count {count} is over {MAX_REPEAT}")
        driven = set()
        for _ in range(count):
            cursor, used = _compile(node.get("body"), cursor, depth + 1, actions, events)
            driven |= used
        return cursor, driven
    branches = node.get("branches")
    if not isinstance(branches, list) or not 1 <= len(branches) <= 2:
        raise ProgramError("parallel: one or two branches")
    ends, driven_sets = [], []
    for branch in branches:
        end, used = _compile(branch, cursor, depth + 1, actions, events)
        ends.append(end)
        driven_sets.append(used)
    if len(driven_sets) == 2 and driven_sets[0] & driven_sets[1]:
        raise ProgramError(f"parallel: both branches drive {sorted(driven_sets[0] & driven_sets[1])}")
    return max(ends), set().union(*driven_sets)


def compile_route(program: dict, *, name: str, description: str, actions, seed: int = 1,
                  max_ticks: int = MAX_TICKS) -> dict:
    """The route for one probe program, validated against contracts/route.schema.json."""
    events: list[dict] = []
    end, _ = _compile(program, LEAD_TICKS, 0, frozenset(actions), events)
    ticks = end + TAIL_TICKS
    if ticks > max_ticks:
        raise ProgramError(f"the program runs {ticks} ticks (max {max_ticks})")
    if len(events) > MAX_EVENTS:
        raise ProgramError(f"{len(events)} input events (max {MAX_EVENTS})")
    seen: dict[tuple[int, str], bool] = {}
    for ev in events:
        key = (ev["tick"], ev["action"])
        if key in seen and seen[key] != ev["pressed"]:
            raise ProgramError(f"{ev['action']} is both pressed and released on tick {ev['tick']}")
        seen[key] = ev["pressed"]
    # One transition per action per tick, then check presses and releases alternate.
    unique = sorted({(e["tick"], e["action"], e["pressed"]) for e in events})
    state: dict[str, bool] = {}
    for tick, action, pressed in unique:
        if state.get(action, False) == pressed:
            raise ProgramError(f"{action} is {'pressed' if pressed else 'released'} twice in a row (tick {tick})")
        state[action] = pressed
    if any(state.values()):
        raise ProgramError("an action is still held at the end")
    route = {"format": "expectrail.route/v0", "name": name, "description": description[:200], "ticks": ticks,
             "seed": seed, "events": [{"tick": t, "action": a, "pressed": p} for t, a, p in unique]}
    validate(route, "route")
    return route
