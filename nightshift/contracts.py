"""Loading, hashing and validating the lane contracts in contracts/*.schema.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent.parent / "contracts"
KINDS = ("route", "replay", "test-spec", "observations", "verdict", "repair-request", "verification")


class ContractError(ValueError):
    pass


def canonical(doc) -> bytes:
    """The bytes a contract's sha256 is taken over: sorted keys, no spaces."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(doc) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def kind_of(doc) -> str:
    fmt = doc.get("format", "") if isinstance(doc, dict) else ""
    for kind in KINDS:
        if fmt == f"nightshift.{kind}/v0":
            return kind
    raise ContractError(f"unknown or missing format: {fmt!r}")


def schema(kind: str) -> dict:
    return json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))


def validate(doc, kind: str | None = None) -> str:
    """Check doc against its schema; returns its kind. Needs the jsonschema package."""
    import jsonschema

    kind = kind or kind_of(doc)
    errors = sorted(jsonschema.Draft202012Validator(schema(kind)).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise ContractError(f"{kind}: {where}: {first.message}")
    return kind


def load(path: Path, kind: str | None = None) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if kind and kind_of(doc) != kind:
        raise ContractError(f"{path}: expected nightshift.{kind}/v0")
    return doc
