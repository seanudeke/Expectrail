"""Names from before the project was renamed from Nightshift to Expectrail (October 30, 2026).

New output always uses the new names. Input in the old names is still accepted, so the private
held-out set, recorded runs in bench/, earlier CI annotations and teammates' existing shells and
.env files keep working:

- format IDs: ``nightshift.<kind>/v0`` reads the same as ``expectrail.<kind>/v0``;
- environment variables: ``NIGHTSHIFT_X`` is adopted as ``EXPECTRAIL_X`` when the new name is unset;
- the verifier's signing key keeps its old basename on the fixer's deny list;
- the fix matrix's condition, called ``nightshift`` in runs before the rename, reads as ``expectrail``.
"""
from __future__ import annotations

import os
import sys
from typing import MutableMapping

PREFIX = "expectrail"
LEGACY_PREFIX = "nightshift"
ENV_PREFIX = "EXPECTRAIL_"
LEGACY_ENV_PREFIX = "NIGHTSHIFT_"
SIGNING_KEY = ".expectrail-signing-key"
LEGACY_SIGNING_KEY = ".nightshift-signing-key"


def format_ids(name: str, version: str = "v0") -> tuple[str, str]:
    """The current and legacy format IDs for one document kind, current first."""
    return f"{PREFIX}.{name}/{version}", f"{LEGACY_PREFIX}.{name}/{version}"


def current_name(name: str) -> str:
    """A name from before the rename (a fix-matrix condition, say) under its current spelling."""
    return PREFIX if name == LEGACY_PREFIX else name


def adopt_legacy_env(environ: MutableMapping[str, str] | None = None, *, quiet: bool = False) -> list[str]:
    """Copy each NIGHTSHIFT_X to EXPECTRAIL_X when EXPECTRAIL_X is not set. Returns the new names.

    The new name always wins. A legacy setting is never silently dropped: settings such as
    EXPECTRAIL_SAM_CACHE=off or EXPECTRAIL_HELDOUT_DIR change what a run does.
    """
    env = os.environ if environ is None else environ
    adopted = []
    for key in sorted(env):
        if not key.startswith(LEGACY_ENV_PREFIX):
            continue
        new = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX):]
        if new not in env:
            env[new] = env[key]
            adopted.append(new)
    if adopted and not quiet:
        print("expectrail: using environment variables named before the rename; rename them to "
              + ", ".join(adopted), file=sys.stderr)
    return adopted
