"""Generate single-edit mutants of the clean game, and the oracle that says which ones show.

Nobody picks a case (#127): this enumerates every possible single edit, then samples with the seed
committed in the pre-registration (bench/mutation/preregistration.json). Only the generator, the seed
and the manifest are committed; a mutant's patch is regenerated from them, never edited by hand.

The steps, the scale factor, the seed, the sample size and the thresholds are the pre-registration's,
and a person sets them. This file holds no defaults for them, on purpose.

Operator classes, as #127 lists them:
  - numeric: ``position``, ``offset`` and ``scale`` per axis, and ``z_index``, plus or minus a step;
  - boolean: ``visible``, ``disabled`` and ``one_way_collision`` flipped;
  - collision-bit: one bit of ``collision_layer`` or ``collision_mask`` flipped;
  - code: a comparison flipped, a sign flipped, or a constant scaled in player.gd and enemy.gd;
  - resource-path: an external resource pointed at a file that does not exist. Its uid goes too, or
    Godot finds the file by uid and nothing breaks (bugs/missing-texture/v1.patch learned this).

    python3 -m agents.mutate_game --sites                       # what each operator can reach
    python3 -m agents.mutate_game --manifest bench/mutation/generated/manifest.json
    python3 -m agents.mutate_game --patch <mutant id> --out runs/m.patch

The oracle compares a replay with the clean game's: its engine record (positions, facing, shots,
enemies) and its frames. It only knows "differs from the clean game".
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

from harness.run import REPO, tree_digest

GAME = REPO / "game" / "platformer"
MANIFEST_FORMAT = "expectrail.mutation-manifest/v0"
PREREGISTRATION = REPO / "bench" / "mutation" / "preregistration.json"
OPERATOR_CLASSES = ("numeric", "boolean", "collision-bit", "code", "resource-path")
CODE_FILES = ("player/player.gd", "enemy/enemy.gd")
HUMAN_FIELDS = ("wrongFix.commentOnlyLabel", "wrongFix.publicSamRuleApprovedBy",
                "generator.seed", "generator.sampleSize", "generator.positionStep", "generator.offsetStep",
                "generator.scaleStep", "generator.zIndexStep", "generator.constantScale", "generator.collisionBits",
                "oracle.traceThresholdPx", "oracle.frameThreshold", "stopRule", "agreement.seed",
                "agreement.minimum", "reportTemplate", "pins")

_NUMBER = r"-?\d+(?:\.\d+)?(?:e-?\d+)?"
_VECTOR = re.compile(rf"^(position|offset|scale) = Vector2\(({_NUMBER}), ({_NUMBER})\)$")
_Z_INDEX = re.compile(r"^z_index = (-?\d+)$")
_BOOLEAN = re.compile(r"^(visible|disabled|one_way_collision) = (true|false)$")
_BITS = re.compile(r"^(collision_layer|collision_mask) = (\d+)$")
_RESOURCE = re.compile(r'^\[ext_resource (?P<head>.*?)(?: uid="[^"]*")? path="(?P<path>res://[^"]+)"(?P<tail>.*)\]$')
_CONST = re.compile(rf"^const (\w+) = ({_NUMBER})$")
_COMPARE = re.compile(r" (<=|>=|==|!=|<|>) ")
_NEGATED = re.compile(r"= -([A-Z][A-Z_]*)\b")
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "!=", "!=": "=="}


class PreregistrationError(RuntimeError):
    pass


def _get(doc: dict, dotted: str):
    for part in dotted.split("."):
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def missing_decisions(doc: dict) -> list[str]:
    """The human-only fields still empty in a pre-registration."""
    return [f for f in HUMAN_FIELDS if _get(doc, f) is None]


def load_preregistration(path: Path = PREREGISTRATION) -> dict:
    """The pre-registration, refused while a person's decision is missing or a pin has moved."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = missing_decisions(doc)
    if missing:
        raise PreregistrationError(f"{path} is not complete, so nothing may be judged. Missing: {', '.join(missing)}")
    moved = sorted(k for k, v in current_pins().items() if doc["pins"].get(k) != v)
    if moved:
        raise PreregistrationError(f"{path}: pinned material changed since registration: {', '.join(moved)}")
    doc["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return doc


def _sha(rel: str) -> str:
    return hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


# What a judged result depends on. If one of these moves after registration, the run refuses.
PINNED = ("agents/mutate_game.py", "agents/mutation_bench.py", "agents/verifier.py", "agents/observations.py",
          "agents/gameplay.py", "agents/trace_checks.py", "expectrail/evaluator.py", "harness/run.py",
          "harness/godot/expectrail_harness.gd", "harness/get_godot.sh", "harness/routes/smoke.json",
          "agents/specs/player-stays-above-ground.json", "specs/player-always-visible.json", "specs/coins-visible.json")


def current_pins() -> dict:
    return {"gameTree": tree_digest(GAME), **{rel: _sha(rel) for rel in PINNED}}


def _fmt(value: float) -> str:
    """A number as a scene file writes it: no trailing .0, and no float noise from the arithmetic."""
    rounded = round(value, 6)
    return str(int(rounded)) if rounded == int(rounded) else repr(rounded)


def _mutant(cls: str, rel: str, line_no: int, tag: str, before: str, after: str) -> dict:
    return {"id": f"{cls}:{rel}:{line_no}:{tag}", "class": cls, "file": rel, "line": line_no,
            "before": before, "after": after}


def _scene_mutants(rel: str, n: int, line: str, params: dict) -> list[dict]:
    out = []
    if m := _VECTOR.match(line):
        prop, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        step = params[f"{prop}Step"]
        for axis, sign in (("x", 1), ("x", -1), ("y", 1), ("y", -1)):
            nx, ny = (x + sign * step, y) if axis == "x" else (x, y + sign * step)
            out.append(_mutant("numeric", rel, n, f"{prop}.{axis}{'+' if sign > 0 else '-'}", line,
                               f"{prop} = Vector2({_fmt(nx)}, {_fmt(ny)})"))
    elif m := _Z_INDEX.match(line):
        z = int(m.group(1))
        for sign in (1, -1):
            out.append(_mutant("numeric", rel, n, f"z_index{'+' if sign > 0 else '-'}", line,
                               f"z_index = {z + sign * int(params['zIndexStep'])}"))
    elif m := _BOOLEAN.match(line):
        out.append(_mutant("boolean", rel, n, m.group(1), line,
                           f"{m.group(1)} = {'false' if m.group(2) == 'true' else 'true'}"))
    elif m := _BITS.match(line):
        for bit in range(int(params["collisionBits"])):
            out.append(_mutant("collision-bit", rel, n, f"{m.group(1)}.{bit}", line,
                               f"{m.group(1)} = {int(m.group(2)) ^ (1 << bit)}"))
    elif m := _RESOURCE.match(line):
        out.append(_mutant("resource-path", rel, n, "missing", line,
                           f'[ext_resource {m["head"]} path="{m["path"]}.missing"{m["tail"]}]'))
    return out


def _code_mutants(rel: str, n: int, line: str, params: dict) -> list[dict]:
    if line.lstrip().startswith("#"):
        return []
    out = []
    if m := _CONST.match(line):
        name, value = m.group(1), float(m.group(2))
        out.append(_mutant("code", rel, n, f"sign.{name}", line, f"const {name} = {_fmt(-value)}"))
        out.append(_mutant("code", rel, n, f"scale.{name}", line, f"const {name} = {_fmt(value * params['constantScale'])}"))
    for i, m in enumerate(_COMPARE.finditer(line)):
        out.append(_mutant("code", rel, n, f"compare.{i}", line,
                           line[:m.start()] + f" {_FLIP[m.group(1)]} " + line[m.end():]))
    for i, m in enumerate(_NEGATED.finditer(line)):
        out.append(_mutant("code", rel, n, f"sign.{i}", line, line[:m.start()] + f"= {m.group(1)}" + line[m.end():]))
    return out


def enumerate_mutants(params: dict, game: Path = GAME) -> list[dict]:
    """Every possible mutant, in a fixed order: sorted by file, then line, then operator."""
    found: list[dict] = []
    for path in sorted(game.rglob("*.tscn")):
        rel = path.relative_to(game).as_posix()
        if ".godot" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found += _scene_mutants(rel, n, line, params)
    for rel in CODE_FILES:
        for n, line in enumerate((game / rel).read_text(encoding="utf-8").splitlines(), 1):
            found += _code_mutants(rel, n, line, params)
    ids = [m["id"] for m in found]
    if len(ids) != len(set(ids)):
        raise ValueError("two mutants share an id")
    return found


def sample(mutants: list[dict], seed: int, size: int) -> list[dict]:
    """A seeded sample, in enumeration order. A generator with fewer mutants gives all of them."""
    chosen = random.Random(seed).sample(range(len(mutants)), min(size, len(mutants)))
    return [mutants[i] for i in sorted(chosen)]


def patch_text(mutant: dict, game: Path = GAME) -> str:
    """The mutant as a unified diff against the clean game, regenerated from the game itself."""
    rel = mutant["file"]
    before = (game / rel).read_text(encoding="utf-8").splitlines(keepends=True)
    index = mutant["line"] - 1
    if before[index].rstrip("\n") != mutant["before"]:
        raise ValueError(f"{mutant['id']}: the game no longer has this line")
    after = list(before)
    after[index] = mutant["after"] + "\n"
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def build_manifest(prereg: dict, game: Path = GAME) -> dict:
    gen = prereg["generator"]
    every = enumerate_mutants(gen, game)
    chosen = sample(every, int(gen["seed"]), int(gen["sampleSize"]))
    return {
        "format": MANIFEST_FORMAT,
        "gameTree": tree_digest(game),
        "generatorSha256": _sha("agents/mutate_game.py"),
        "seed": gen["seed"],
        "sampleSize": gen["sampleSize"],
        "enumerated": len(every),
        "enumeratedByClass": {c: sum(m["class"] == c for m in every) for c in OPERATOR_CLASSES},
        "sampled": len(chosen),
        "sampledByClass": {c: sum(m["class"] == c for m in chosen) for c in OPERATOR_CLASSES},
        "mutants": [dict(m, patchSha256=hashlib.sha256(patch_text(m, game).encode()).hexdigest()) for m in chosen],
    }


def mutant_by_id(manifest: dict, mutant_id: str) -> dict:
    found = [m for m in manifest["mutants"] if m["id"] == mutant_id]
    if not found:
        raise SystemExit(f"{mutant_id}: not in the manifest")
    return found[0]


def site_counts(game: Path = GAME) -> dict:
    """How many lines each operator can reach, whatever the steps: a fact about the game."""
    params = {"positionStep": 1, "offsetStep": 1, "scaleStep": 1, "zIndexStep": 1, "constantScale": 2,
              "collisionBits": 1}
    every = enumerate_mutants(params, game)
    tags: dict[str, int] = {}
    for m in every:
        name = m["id"].split(":")[3].split(".")[0].rstrip("+-")
        key = f"{m['class']}/{name}"
        tags[key] = tags.get(key, 0) + 1
    for name in ("visible", "disabled", "one_way_collision"):
        tags.setdefault(f"boolean/{name}", 0)
    return dict(sorted(tags.items()))


# ---------------------------------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------------------------------

def _points(row: dict, key: str) -> dict:
    return {int(p[0]): (float(p[1]), float(p[2])) for p in row.get(key) or []}


def _row_distance(a: dict, b: dict) -> float:
    """How far apart two rows of the engine record are, in world px; inf when they differ in kind."""
    if a.get("facing") != b.get("facing") or bool(a.get("player")) != bool(b.get("player")):
        return math.inf
    worst = 0.0
    if a.get("player"):
        worst = math.dist(a["player"][:2], b["player"][:2])
    for key in ("enemies", "projectiles"):
        pa, pb = _points(a, key), _points(b, key)
        if set(pa) != set(pb):
            return math.inf
        worst = max([worst] + [math.dist(pa[i], pb[i]) for i in pa])
    return worst


def trace_distance(clean: dict, other: dict) -> float:
    a, b = clean.get("rows") or [], other.get("rows") or []
    if len(a) != len(b):
        return math.inf
    return max((_row_distance(x, y) for x, y in zip(a, b)), default=0.0)


def frames_differing(clean: list[str], other: list[str]) -> int:
    return sum(x != y for x, y in zip(clean, other)) + abs(len(clean) - len(other))


def oracle(clean_trace: dict, clean_frames: list[str], trace: dict, frames: list[str], thresholds: dict) -> dict:
    """``visible`` or ``equivalent``, from the pre-registered thresholds. Strictly over a threshold."""
    distance, differing = trace_distance(clean_trace, trace), frames_differing(clean_frames, frames)
    visible = distance > float(thresholds["traceThresholdPx"]) or differing > int(thresholds["frameThreshold"])
    return {"category": "visible" if visible else "equivalent",
            "traceMaxPx": None if math.isinf(distance) else round(distance, 3),
            "traceDiffersInKind": math.isinf(distance),
            "framesDiffering": differing, "framesCompared": max(len(clean_frames), len(frames))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sites", action="store_true", help="what each operator can reach; needs no decisions")
    g.add_argument("--pins", action="store_true", help="print the current pins for the pre-registration")
    g.add_argument("--manifest", type=Path, help="write the sampled manifest here")
    g.add_argument("--patch", metavar="MUTANT_ID", help="regenerate one mutant's patch")
    p.add_argument("--prereg", type=Path, default=PREREGISTRATION)
    p.add_argument("--from-manifest", type=Path, default=PREREGISTRATION.parent / "generated" / "manifest.json")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.sites:
        print(json.dumps(site_counts(), indent=2))
        return 0
    if args.pins:
        print(json.dumps(current_pins(), indent=2))
        return 0
    if args.patch:
        manifest = json.loads(args.from_manifest.read_text(encoding="utf-8"))
        text = patch_text(mutant_by_id(manifest, args.patch))
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    try:
        manifest = build_manifest(load_preregistration(args.prereg))
    except PreregistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{manifest['sampled']} of {manifest['enumerated']} mutants: {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
