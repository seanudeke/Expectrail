"""Loading, hashing and validating the lane contracts in contracts/*.schema.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pixelproof.legacy import format_ids

SCHEMAS = Path(__file__).resolve().parent.parent / "contracts"
KINDS = (
    "route",
    "replay",
    "test-spec",
    "observations",
    "verdict",
    "repair-request",
    "verification",
    "gameplay-verdict",
    "release-candidate",
    "overnight-summary",
)


class ContractError(ValueError):
    pass


def canonical(doc) -> bytes:
    """The bytes a contract's sha256 is taken over: sorted keys, no spaces."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(doc) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def kind_of(doc) -> str:
    """The document kind; pre-rename nightshift.<kind>/v0 IDs are read the same way."""
    fmt = doc.get("format", "") if isinstance(doc, dict) else ""
    for kind in KINDS:
        if fmt in format_ids(kind):
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
    if kind == "overnight-summary":
        runs = doc["runs"]
        accepted = doc["accepted"]
        results = doc.get("results") or []
        if accepted > runs:
            raise ContractError(f"overnight-summary: accepted ({accepted}) > runs ({runs})")
        if len(results) != runs:
            raise ContractError(
                f"overnight-summary: len(results) ({len(results)}) != runs ({runs})"
            )
        cost = doc.get("cost") or {}
        if cost.get("costProvenance") == "metered" and cost.get("costUsd") is None:
            raise ContractError("overnight-summary: metered cost requires costUsd")
    return kind


def load(path: Path, kind: str | None = None) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if kind and kind_of(doc) != kind:
        raise ContractError(f"{path}: expected pixelproof.{kind}/v0")
    return doc
