"""Fixer↔verifier isolation: shared deny-by-absence names (mount absence only).

These basenames must not appear under fixer-work. This does not claim the Muse
process cannot read the rest of the repo — only that verifier controls are not
mounted into the fixer workspace.
"""
from __future__ import annotations

from pathlib import Path

# Closed list for Gate 1 filmable trust. Basename match under fixer-work.
FIXER_FORBIDDEN_BASENAMES = frozenset({
    ".nightshift-signing-key",
    "obs-clean.json",
    "obs-held-out.json",
    "player-stays-above-ground.json",
    "player-reaches-end-of-route.json",
    "evaluator.py",
})


def forbidden_paths_under(fixer: Path) -> list[Path]:
    """Return paths under fixer whose basename is on the deny list."""
    if not fixer.is_dir():
        return []
    return sorted(
        p for p in fixer.rglob("*")
        if p.is_file() and p.name in FIXER_FORBIDDEN_BASENAMES
    )


def arm(
    *,
    source: str,
    path: str | None = None,
    observations_sha256: str | None = None,
    detail: str | None = None,
) -> dict:
    """One suite provenance arm (candidate / clean / heldOut)."""
    out: dict = {"source": source}
    if path is not None:
        out["path"] = path
    if observations_sha256 is not None:
        out["observationsSha256"] = observations_sha256
    if detail is not None:
        out["detail"] = detail
    return out
