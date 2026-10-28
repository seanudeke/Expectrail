#!/usr/bin/env python3
"""Muse Code PreToolUse hook for the fixer: no writes outside the editable globs, no web tools.

agents.guard copies this file into fixer-work/.muse/hooks/ next to a policy file and registers it
in .muse/hooks.json. Muse Code runs it before every tool call with the call as JSON on stdin.
It answers with a deny decision or {} (no opinion; never a bare allow), and appends one line per
call to .muse/fixer-guard.jsonl, which is how the run proves the hook loaded at all.

Standard library only, no repo imports: it runs inside the fixer sandbox. Fails closed: a write
it cannot check is denied. Shell commands are logged, not parsed; the OS sandbox and the
verifier's editable-glob check still stand behind it.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MUSE_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(MUSE_DIR)
POLICY = os.path.join(MUSE_DIR, "fixer-guard.json")
LOG = os.path.join(MUSE_DIR, "fixer-guard.jsonl")
WRITE_TOOLS = {"write_file", "edit_file"}
READ_TOOLS = {"read_file", "search"}
DEFAULT_DENY_TOOLS = {"web_fetch", "web_search"}


def path_allowed(rel: str, globs: list[str]) -> bool:
    # Same rule as agents.patchutil.path_allowed, copied so the hook needs nothing from the repo.
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.rstrip("/")) for g in globs)


def workspace_rel(raw, cwd: str | None) -> tuple[str | None, str | None]:
    """(path relative to the workspace, problem). Resolves .. and symlinks before judging."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "write with no path"
    base = cwd if cwd and os.path.isabs(cwd) else ROOT
    full = raw if os.path.isabs(raw) else os.path.join(base, raw)
    real = os.path.realpath(full)
    root = os.path.realpath(ROOT)
    if os.path.commonpath([real, root]) != root:
        return None, f"{raw} is outside the fixer workspace"
    rel = os.path.relpath(real, root).replace(os.sep, "/")
    return rel, None


def decide(payload: dict, policy: dict | None) -> tuple[str, str, dict]:
    """-> (decision, reason, log fields). decision is deny or pass."""
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    fields: dict = {"tool": tool}
    deny_tools = set((policy or {}).get("denyTools", DEFAULT_DENY_TOOLS))
    if tool in deny_tools:
        return "deny", f"{tool} is not available to the fixer", fields
    if tool in ("bash", "bash_input"):
        cmd = tool_input.get("command") or tool_input.get("input") or ""
        fields["command"] = str(cmd)[:200]
        return "pass", "shell is logged, not parsed", fields
    if tool in READ_TOOLS:
        if "path" in tool_input:
            fields["path"] = str(tool_input.get("path"))[:300]
        return "pass", "read", fields
    is_write = tool in WRITE_TOOLS or (tool not in READ_TOOLS and "path" in tool_input)
    if not is_write:
        return "pass", "not a file write", fields
    fields["path"] = str(tool_input.get("path"))[:300]
    if policy is None or not isinstance(policy.get("editable"), list) or not policy["editable"]:
        return "deny", "guard policy missing; writes are blocked", fields
    rel, problem = workspace_rel(tool_input.get("path"), payload.get("cwd"))
    if problem:
        return "deny", problem, fields
    fields["rel"] = rel
    if rel == ".muse" or rel.startswith(".muse/"):
        return "deny", "the guard's own files are read-only", fields
    if not path_allowed(rel, policy["editable"]):
        globs = ", ".join(policy["editable"])
        return "deny", f"{rel} is outside the editable files ({globs})", fields
    return "pass", "inside editable globs", fields


def load_policy() -> dict | None:
    try:
        with open(POLICY, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def log(entry: dict) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def main() -> int:
    payload: dict = {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        decision, reason, fields = decide(payload, load_policy())
    except Exception as err:  # noqa: BLE001 — anything unexpected blocks the call
        decision, reason, fields = "deny", f"guard error: {type(err).__name__}: {err}", {
            "tool": str(payload.get("tool_name") or "") if isinstance(payload, dict) else ""}
    log({"t": round(time.time(), 3), "id": payload.get("tool_use_id") if isinstance(payload, dict) else None,
         "decision": decision, "reason": reason, **fields})
    if decision == "deny":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"Fixer guard: {reason}"}}))
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
