"""Normalize one replay's raw trace into an expectrail.episode/v1 record.

The raw trace is what harness/godot/expectrail_harness.gd writes: one row per physics tick with the
player, its floor state, its sprite's facing, and the enemies and bullets it tracks. The episode keeps
those samples, states what the recorder collected (``capabilities``), checks that ticks are contiguous,
and derives the events the contract interpreter reads (a bullet's first appearance, a take-off, a
landing). It never fills a gap, smooths a value or invents an event the trace does not show.

A trace from before the recorder declared its capabilities is still read, with narrower guarantees:
its enemies and bullets were only written when there were some, so an empty tick cannot prove that
none were there, and those collections are "unknown".
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from expectrail.contracts import canonical_v1

ADAPTER = "godot-platformer/v1"


class EpisodeError(ValueError):
    pass


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collection(rows: list[dict], key: str, declared: str | None) -> str:
    if declared in ("complete", "initial-instances", "absent"):
        return declared
    return "unknown"


def _points(raw, key: str, tick: int) -> list:
    out = []
    for item in raw:
        if not (isinstance(item, (list, tuple)) and len(item) == 3 and _finite(*item[1:])
                and isinstance(item[0], int)):
            raise EpisodeError(f"tick {tick}: malformed {key} entry {item!r}")
        out.append([int(item[0]), float(item[1]), float(item[2])])
    return out


def normalize(trace: dict, route: dict, *, episode_id: str, trace_bytes: bytes | None = None,
              replay: dict | None = None, replay_bytes: bytes | None = None) -> dict:
    """The episode for one replay. Raises EpisodeError on a malformed trace or an unsupported rate pair."""
    rows = [r for r in trace.get("rows") or [] if isinstance(r, dict)]
    if not rows:
        raise EpisodeError("the trace has no rows")
    tps = trace.get("physicsTicksPerSecond")
    if not isinstance(tps, int) or tps <= 0:
        raise EpisodeError("the trace does not say how many physics ticks make a second")
    fps = ((replay or {}).get("capture") or {}).get("fps")
    mapping = None
    if isinstance(fps, int) and fps > 0:
        if tps % fps:
            raise EpisodeError(f"unsupported rate pair: {tps} ticks to {fps} frames a second")
        mapping = {"protocol": "tick-step/v1", "step": tps // fps}
    declared = trace.get("capabilities") if isinstance(trace.get("capabilities"), dict) else {}
    enemies_cap = _collection(rows, "enemies", declared.get("enemies"))
    projectiles_cap = _collection(rows, "projectiles", declared.get("projectiles"))
    caps = {
        "player": any(r.get("player") for r in rows),
        "onFloor": any("onFloor" in r for r in rows),
        "facing": any("facing" in r for r in rows),
        "enemies": enemies_cap,
        "projectiles": projectiles_cap,
    }
    samples = []
    for r in rows:
        tick = r.get("tick")
        if not isinstance(tick, int) or tick < 0:
            raise EpisodeError(f"malformed tick {tick!r}")
        player = r.get("player")
        if player is not None:
            if not (isinstance(player, (list, tuple)) and len(player) == 2 and _finite(*player)):
                raise EpisodeError(f"tick {tick}: malformed player {player!r}")
            player = [float(player[0]), float(player[1])]
        facing = r.get("facing")
        if facing not in (-1, 1, None):
            raise EpisodeError(f"tick {tick}: malformed facing {facing!r}")
        on_floor = r.get("onFloor")
        if on_floor is not None and not isinstance(on_floor, bool):
            raise EpisodeError(f"tick {tick}: malformed onFloor {on_floor!r}")

        def collection(key: str, cap: str):
            if key in r:
                return _points(r[key] or [], key, tick)
            # Absent key: an empty collection only when the recorder said it writes every tick.
            return [] if cap in ("complete", "initial-instances", "absent") else None

        samples.append({"tick": tick, "player": player, "onFloor": on_floor, "facing": facing,
                        "enemies": collection("enemies", enemies_cap),
                        "projectiles": collection("projectiles", projectiles_cap)})
    ticks = [s["tick"] for s in samples]
    if ticks != sorted(ticks) or len(set(ticks)) != len(ticks):
        raise EpisodeError("ticks are not strictly increasing")
    gaps = [[a + 1, b - 1] for a, b in zip(ticks, ticks[1:]) if b != a + 1]
    events = derive_events(samples, projectiles_cap, enemies_cap)
    inputs = [{"tick": int(e["tick"]), "action": str(e["action"]), "pressed": bool(e["pressed"])}
              for e in route.get("events") or []]
    return {
        "format": "expectrail.episode/v1",
        "id": episode_id,
        "adapter": ADAPTER,
        "source": {
            "routeName": str(route.get("name") or "route"),
            "routeSha256": _sha_bytes(canonical_v1(route)),
            "traceSha256": _sha_bytes(trace_bytes) if trace_bytes is not None else _sha_bytes(canonical_v1(trace)),
            "replaySha256": _sha_bytes(replay_bytes) if replay_bytes is not None else None,
        },
        "physicsTicksPerSecond": tps,
        "captureFps": fps if isinstance(fps, int) else None,
        "frameMapping": mapping,
        "capabilities": caps,
        "completeness": {"contiguous": not gaps, "firstTick": ticks[0], "lastTick": ticks[-1], "gaps": gaps},
        "inputs": inputs,
        "samples": samples,
        "events": events,
    }


def derive_events(samples: list[dict], projectiles_cap: str, enemies_cap: str) -> list[dict]:
    """Take-offs, landings, each bullet's first appearance, and disappearances the recorder can vouch for."""
    events: list[dict] = []
    prev_floor = None
    for s in samples:
        floor = s["onFloor"]
        if prev_floor is True and floor is False:
            events.append({"type": "takeoff", "tick": s["tick"], "id": None, "x": None, "y": None})
        elif prev_floor is False and floor is True:
            events.append({"type": "landing", "tick": s["tick"], "id": None, "x": None, "y": None})
        if floor is not None:
            prev_floor = floor
    for key, kind, cap in (("projectiles", "projectile", projectiles_cap), ("enemies", "enemy", enemies_cap)):
        seen: dict[int, int] = {}
        last: dict[int, int] = {}
        for s in samples:
            for pid, x, y in s[key] or []:
                if pid not in seen:
                    seen[pid] = s["tick"]
                    if kind == "projectile":
                        events.append({"type": "projectile_spawn", "tick": s["tick"], "id": pid, "x": x, "y": y})
                last[pid] = s["tick"]
        if cap in ("complete", "initial-instances"):
            end = samples[-1]["tick"]
            for pid, t in last.items():
                if t < end:
                    events.append({"type": f"{kind}_gone", "tick": t + 1, "id": pid, "x": None, "y": None})
    events.sort(key=lambda e: (e["tick"], e["type"], e["id"] if e["id"] is not None else -1))
    return events


def from_run_dir(run_dir: Path, route: dict, *, episode_id: str) -> dict:
    """The episode for a harness run directory (trace.json and replay.json)."""
    trace_bytes = (run_dir / "trace.json").read_bytes()
    replay_path = run_dir / "replay.json"
    replay_bytes = replay_path.read_bytes() if replay_path.is_file() else None
    return normalize(json.loads(trace_bytes), route, episode_id=episode_id, trace_bytes=trace_bytes,
                     replay=json.loads(replay_bytes) if replay_bytes else None, replay_bytes=replay_bytes)
