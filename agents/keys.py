"""Detect whether live Muse Wonder / Muse Code can run in this environment.

Also loads a gitignored repo-root `.env` at CLI entry (never from readiness helpers),
so local Meta keys work without exporting them every shell. Process env always wins.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping, TypedDict

from harness.run import REPO

# Keys we will adopt from a local `.env` (setdefault only).
DOTENV_KEYS = frozenset({
    "META_API_KEY",
    "MODEL_API_KEY",
    "META_API_BASE",
    "NIGHTSHIFT_MODEL_API_BASE",
    "NIGHTSHIFT_SPEC_MODEL",
    # Open weights (Muse Spark Open on a partner endpoint) for agents.feedback --sorter open
    "BASETEN_API_KEY",
    "NIGHTSHIFT_OPEN_API_KEY",
    "NIGHTSHIFT_OPEN_API_BASE",
    "NIGHTSHIFT_OPEN_MODEL",
    # Open weights: Muse Glimmer as the vision backend (agents.glimmer_client)
    "NIGHTSHIFT_VISION_BACKEND",
    "FIREWORKS_API_KEY",
    "NIGHTSHIFT_GLIMMER_API_KEY",
    "NIGHTSHIFT_GLIMMER_API_BASE",
    "NIGHTSHIFT_GLIMMER_MODEL",
    "NIGHTSHIFT_GLIMMER_COORDS",
})

# Muse Code subprocess: model key + runtime/TLS/temp/proxy hygiene — not a sandbox.
MUSE_ENV_ALLOWLIST = frozenset({
    "META_API_KEY",
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
})

PROMPT_POLICY = "clean-v1"


class ModeResolution(TypedDict, total=False):
    mode: str
    offline_triage: bool
    use_muse: bool
    wonder_key_present: bool
    muse_ready: bool
    verification_default: str  # fixture | harness — informational; loop may override


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Load KEY=VAL from a `.env` file into os.environ via setdefault.

    - Missing file: no-op.
    - Never overrides keys already present in the process environment (including empty
      string — CI/tests that clear or set META_API_KEY win).
    - Only adopts keys in DOTENV_KEYS.
    - Supports optional `export ` prefix, optional quotes, spaces around `=`.
    Returns the key→value pairs that were newly set (for tests).
    """
    env_path = path if path is not None else REPO / ".env"
    if not env_path.is_file():
        return {}
    adopted: dict[str, str] = {}
    text = env_path.read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise SystemExit(f"malformed .env line (no '='): {raw!r} in {env_path}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key not in DOTENV_KEYS:
            continue
        if value == "":
            continue
        if key in os.environ:
            continue
        os.environ[key] = value
        adopted[key] = value
    return adopted


def muse_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Allowlisted env for `muse exec` — leak hygiene, not OS isolation."""
    src = dict(base) if base is not None else dict(os.environ)
    out = {k: v for k, v in src.items() if k in MUSE_ENV_ALLOWLIST and v != ""}
    return out


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


def require_separate_sam_key() -> None:
    """With SAM on, refuse to run Muse Code (the fixer) unless SAM has its own key.

    The verifier reads MODEL_API_KEY; Muse Code receives META_API_KEY (MUSE_ENV_ALLOWLIST). If
    both hold the same key, the fixer holds the verifier's key, which breaks the promise that the
    fixer never sees verifier secrets. Called by entry points that run Muse; a no-op when the
    observations provider is not SAM.
    """
    from agents.observations import resolve_provider

    if resolve_provider() != "sam":
        return
    from agents.sam_observations import SamError, vision_backend

    muse_key = os.environ.get("META_API_KEY", "").strip()
    try:
        backend = vision_backend()
    except SamError as exc:
        raise SystemExit(str(exc)) from None
    if backend in ("glimmer", "both", "glimmer-engine"):
        from agents.glimmer_client import KEY_ENVS, api_key

        glimmer = api_key()
        if not glimmer:
            raise SystemExit(f"NIGHTSHIFT_VISION_BACKEND={backend} needs one of {', '.join(KEY_ENVS)}")
        if muse_key and glimmer == muse_key:
            raise SystemExit("the Glimmer key is the same as META_API_KEY, which Muse Code (the fixer) "
                             "receives; the verifier's vision key must be its own")
        if backend in ("glimmer", "glimmer-engine"):
            return
    sam_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not sam_key:
        raise SystemExit("NIGHTSHIFT_OBS_PROVIDER=sam needs MODEL_API_KEY (a Meta Model API key for SAM)")
    if muse_key and sam_key == muse_key:
        raise SystemExit("MODEL_API_KEY is the same key as META_API_KEY, which Muse Code (the fixer) "
                         "receives. Create a second key on dev.meta.ai for SAM and set it as "
                         "MODEL_API_KEY, so the fixer never holds the verifier's key.")
