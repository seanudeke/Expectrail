"""Detect whether live Muse Wonder / Muse Code can run in this environment."""
from __future__ import annotations

import os
import shutil
from typing import TypedDict


class ModeResolution(TypedDict, total=False):
    mode: str
    offline_triage: bool
    use_muse: bool
    wonder_key_present: bool
    muse_ready: bool
    verification_default: str  # fixture | harness — informational; loop may override


def wonder_key() -> str | None:
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
    return key if key else None


def muse_code_ready() -> bool:
    return shutil.which("muse") is not None and bool(os.environ.get("META_API_KEY"))


def resolve_mode(requested: str) -> ModeResolution:
    """Map auto|offline|live to concrete triage/fixer flags.

    auto: Wonder live if a key exists; Muse Code live if muse + META_API_KEY exist;
          otherwise fixtures. CI stays deterministic without secrets.
    live: requires Wonder key and Muse Code readiness; fails closed otherwise.
    """
    if requested not in ("auto", "offline", "live"):
        raise ValueError(f"unknown mode: {requested}")
    if requested == "offline":
        return {
            "mode": "offline",
            "offline_triage": True,
            "use_muse": False,
            "wonder_key_present": False,
            "muse_ready": False,
            "verification_default": "fixture",
        }
    if requested == "live":
        if not wonder_key():
            raise SystemExit(
                "live mode needs MODEL_API_KEY or META_API_KEY for Wonder triage"
            ) from None
        if not muse_code_ready():
            raise SystemExit(
                "live mode needs muse on PATH and META_API_KEY for Muse Code"
            ) from None
        return {
            "mode": "live",
            "offline_triage": False,
            "use_muse": True,
            "wonder_key_present": True,
            "muse_ready": True,
            "verification_default": "fixture",
        }
    # auto
    return {
        "mode": "auto",
        "offline_triage": wonder_key() is None,
        "use_muse": muse_code_ready(),
        "wonder_key_present": wonder_key() is not None,
        "muse_ready": muse_code_ready(),
        "verification_default": "fixture",
    }


def seal_mode_flags(
    resolved: ModeResolution,
    *,
    force_offline_triage: bool,
    force_online_triage: bool,
    force_muse: bool,
) -> ModeResolution:
    """Apply CLI overrides only when they do not contradict the sealed mode.

    Raises SystemExit on contradictions so overnight policy cannot silently lie.
    """
    mode = resolved["mode"]
    offline_triage = resolved["offline_triage"]
    use_muse = resolved["use_muse"]

    if force_offline_triage and force_online_triage:
        raise SystemExit("conflicting flags: --offline-triage and --online-triage") from None

    if force_offline_triage:
        if mode == "live":
            raise SystemExit("--offline-triage conflicts with --mode live") from None
        offline_triage = True
    if force_online_triage:
        if mode == "offline":
            raise SystemExit("--online-triage conflicts with --mode offline") from None
        if not wonder_key():
            raise SystemExit("--online-triage needs MODEL_API_KEY or META_API_KEY") from None
        offline_triage = False
    if force_muse:
        if mode == "offline":
            raise SystemExit("--use-muse conflicts with --mode offline") from None
        if not muse_code_ready():
            raise SystemExit("--use-muse needs muse on PATH and META_API_KEY") from None
        use_muse = True

    out: ModeResolution = {
        "mode": mode,
        "offline_triage": offline_triage,
        "use_muse": use_muse,
        "wonder_key_present": resolved.get("wonder_key_present", wonder_key() is not None),
        "muse_ready": resolved.get("muse_ready", muse_code_ready()),
        "verification_default": resolved.get("verification_default", "fixture"),
    }
    return out
