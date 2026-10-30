"""Process-level Muse Glimmer call counter for per-case spend (agents.case_spend).

Glimmer only increments ``GlimmerClient.calls`` on each instance. The fix-matrix and judge
benchmarks never write that into ``result.json``, so this module wraps ``GlimmerClient._call``
once per process and keeps a shared total. Install before invoking a bench case; read the delta
after. Never estimates: when the wrap is installed and Glimmer was never used, the count is 0.
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_calls = 0
_installed = False


def glimmer_usage() -> dict[str, int]:
    """Snapshot of Glimmer HTTP attempts this process has counted: ``{"calls": N}``."""
    with _lock:
        return {"calls": _calls}


def glimmer_calls_since(before: dict[str, int]) -> int:
    """Calls counted since the snapshot ``before`` (from ``glimmer_usage``)."""
    return glimmer_usage()["calls"] - int(before.get("calls") or 0)


def install() -> bool:
    """Wrap ``GlimmerClient._call`` so each attempt bumps the process counter. Idempotent.

    Returns True when the wrap was installed on this call, False when it was already on.
    """
    global _installed
    with _lock:
        if _installed:
            return False
        from agents.glimmer_client import GlimmerClient

        original = GlimmerClient._call

        def counted(self: Any, body: dict) -> tuple[bytes, str]:
            global _calls
            before = self.calls
            try:
                return original(self, body)
            finally:
                with _lock:
                    _calls += max(0, self.calls - before)

        GlimmerClient._call = counted  # type: ignore[method-assign]
        _installed = True
        return True


def reset_for_tests() -> None:
    """Zero the counter. Does not uninstall the wrap."""
    global _calls
    with _lock:
        _calls = 0
