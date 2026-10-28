"""Install the fixer guard hook into fixer-work before Muse Code runs, and read its log after.

The hook (agents/fixer_guard_hook.py) blocks writes outside the repair request's editable globs
and the web tools, and logs every tool call to .muse/fixer-guard.jsonl. Muse Code only loads a
project hook file with --trust-workspace (the fixer passes it) and silently skips a malformed
one, so the log is the proof it ran: no log lines means "not confirmed", never "nothing blocked".

The guard is evidence and a first line. The hard gate stays where it was: the verifier rebuilds
from the candidate patch, and the fixer refuses any patch outside the editable globs.

Set NIGHTSHIFT_FIXER_GUARD=0 to run Muse without it (for comparing runs).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from collections import Counter
from pathlib import Path

HOOK_SOURCE = Path(__file__).resolve().parent / "fixer_guard_hook.py"
GUARD_ENV = "NIGHTSHIFT_FIXER_GUARD"
MUSE_DIR = ".muse"
HOOK_REL = f"{MUSE_DIR}/hooks/fixer_guard.py"
POLICY_REL = f"{MUSE_DIR}/fixer-guard.json"
LOG_REL = f"{MUSE_DIR}/fixer-guard.jsonl"
DENY_TOOLS = ("web_fetch", "web_search")
HOOK_TIMEOUT_S = 5


def guard_enabled(environ=None) -> bool:
    value = (environ if environ is not None else os.environ).get(GUARD_ENV, "1").strip().lower()
    return value not in ("0", "off", "false", "no")


def hooks_config(root_as_muse_sees_it: str) -> dict:
    """The .muse/hooks.json Muse Code reads. Only type/command/timeout keys; no matcher (all tools)."""
    script = f"{root_as_muse_sees_it.rstrip('/')}/{HOOK_REL}"
    return {"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": f"python3 {shlex.quote(script)}", "timeout": HOOK_TIMEOUT_S},
    ]}]}}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_guard(work: Path, editable: list[str], *, root_as_muse_sees_it: str) -> dict:
    """Write .muse/hooks.json, the hook script and its policy into fixer-work.

    root_as_muse_sees_it is the workspace path inside the sandbox ("/fixer" under bwrap), so the
    hook command does not depend on the directory Muse starts hooks in.
    """
    muse = work / MUSE_DIR
    if muse.exists():
        shutil.rmtree(muse)
    (muse / "hooks").mkdir(parents=True)
    hook = work / HOOK_REL
    shutil.copy2(HOOK_SOURCE, hook)
    policy = {"editable": list(editable), "denyTools": list(DENY_TOOLS)}
    (work / POLICY_REL).write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    hooks = work / MUSE_DIR / "hooks.json"
    hooks.write_text(json.dumps(hooks_config(root_as_muse_sees_it), indent=2) + "\n", encoding="utf-8")
    return {
        "installed": True,
        "hookSha256": _sha(hook),
        "hooksJsonSha256": _sha(hooks),
        "policy": policy,
        "command": hooks_config(root_as_muse_sees_it)["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
    }


def read_log(path: Path) -> list[dict]:
    entries = []
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            entries.append(doc)
    return entries


def summarize(entries: list[dict], installed: dict | None) -> dict:
    blocked = [
        {k: e[k] for k in ("tool", "path", "rel", "reason") if k in e}
        for e in entries if e.get("decision") == "deny"
    ]
    return {
        "installed": bool(installed and installed.get("installed")),
        "loaded": bool(entries),
        "calls": len(entries),
        "tools": dict(sorted(Counter(str(e.get("tool") or "?") for e in entries).items())),
        "blocked": blocked,
        "commands": [e["command"] for e in entries if e.get("command")][:20],
        "policy": (installed or {}).get("policy"),
        "hookSha256": (installed or {}).get("hookSha256"),
    }


def collect_guard(work: Path, out: Path, installed: dict | None) -> dict:
    """Copy the hook log next to the candidate and write guard.json."""
    log = work / LOG_REL
    entries = read_log(log)
    if log.is_file():
        shutil.copy2(log, out / "guard-log.jsonl")
    summary = summarize(entries, installed)
    (out / "guard.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
