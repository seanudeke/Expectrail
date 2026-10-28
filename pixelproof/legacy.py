"""Names from before the project was renamed from Nightshift to Pixel Proof (October 28, 2026).

New output always uses the new names. Input in the old names is still accepted, so the private
held-out set, recorded runs in bench/, and teammates' existing shells and .env files keep working:

- format IDs: ``nightshift.<kind>/v0`` reads the same as ``pixelproof.<kind>/v0``;
- environment variables: ``NIGHTSHIFT_X`` is adopted as ``PIXELPROOF_X`` when the new name is unset;
- the verifier's signing key keeps its old basename on the fixer deny list.
"""
from __future__ import annotations

import os
import sys
from typing import MutableMapping

PREFIX = "pixelproof"
LEGACY_PREFIX = "nightshift"
ENV_PREFIX = "PIXELPROOF_"
LEGACY_ENV_PREFIX = "NIGHTSHIFT_"
LEGACY_SIGNING_KEY = ".nightshift-signing-key"


def format_ids(name: str, version: str = "v0") -> tuple[str, str]:
    """The current and legacy format IDs for one document kind, current first."""
    return f"{PREFIX}.{name}/{version}", f"{LEGACY_PREFIX}.{name}/{version}"


def adopt_legacy_env(environ: MutableMapping[str, str] | None = None, *, quiet: bool = False) -> list[str]:
    """Copy each NIGHTSHIFT_X to PIXELPROOF_X when PIXELPROOF_X is not set. Returns the new names.

    The new name always wins. A legacy setting is never silently dropped: settings such as
    PIXELPROOF_SAM_CACHE=off matter for the recorded demo.
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
        print(
            "pixelproof: using legacy environment variables; rename them to "
            + ", ".join(adopted),
            file=sys.stderr,
        )
    return adopted
