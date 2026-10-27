"""Detect whether live Muse Wonder / Muse Code can run in this environment."""
from __future__ import annotations

import os
import shutil


def wonder_key() -> str | None:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY") or None


def muse_code_ready() -> bool:
    return shutil.which("muse") is not None and bool(os.environ.get("META_API_KEY"))


def resolve_mode(requested: str) -> dict:
    """Map auto|offline|live to concrete triage/fixer flags.

    auto: Wonder live if a key exists; Muse Code live if muse + META_API_KEY exist;
          otherwise fixtures. CI stays deterministic without secrets.
    """
    if requested not in ("auto", "offline", "live"):
        raise ValueError(f"unknown mode: {requested}")
    if requested == "offline":
        return {"mode": "offline", "offline_triage": True, "use_muse": False}
    if requested == "live":
        if not wonder_key():
            raise SystemExit("live mode needs MODEL_API_KEY or META_API_KEY for Wonder triage") from None
        if not muse_code_ready():
            raise SystemExit("live mode needs muse on PATH and META_API_KEY for Muse Code") from None
        return {"mode": "live", "offline_triage": False, "use_muse": True}
    # auto
    return {
        "mode": "auto",
        "offline_triage": wonder_key() is None,
        "use_muse": muse_code_ready(),
        "wonder_key_present": wonder_key() is not None,
        "muse_ready": muse_code_ready(),
    }
