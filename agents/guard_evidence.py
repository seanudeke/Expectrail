"""Print the fixer guard's evidence as GitHub Actions annotations.

    python3 -m agents.guard_evidence runs/agents-prove-live runs/oct29-film

For every guard.json under the given folders: one notice with installed / loaded / calls /
blocked / who made the calls, and a warning when the guard was installed but logged nothing (Muse
Code skipped .muse/hooks.json) or when no guard.json exists at all. Annotations can be read through
the GitHub API, so checking a live run does not need its artifacts. Always exits 0: this is
evidence, not a gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _clean(text: object, limit: int = 160) -> str:
    """One line, no workflow-command sequences: tool names come from Muse Code."""
    return " ".join(str(text).split()).replace("::", ": :")[:limit]


def lines_for(roots: list[Path]) -> list[str]:
    out: list[str] = []
    found = sorted(p for root in roots if root.exists() for p in root.rglob("guard.json"))
    if not found:
        out.append(f"::warning title=Fixer guard::no guard.json under {_clean(', '.join(map(str, roots)))}: "
                   "Muse Code did not run with the fixer guard installed")
    for path in found:
        try:
            g = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            out.append(f"::warning title=Fixer guard::{_clean(path)}: unreadable ({_clean(err)})")
            continue
        blocked = g.get("blocked") or []
        tools = g.get("tools") or {}
        tool_list = ", ".join(f"{_clean(k, 40)}={int(v)}" for k, v in sorted(tools.items())
                              if isinstance(v, (int, float)))
        blocked_tools = ", ".join(sorted({_clean(b.get("tool") or "?", 40) for b in blocked if isinstance(b, dict)}))
        out.append(
            f"::notice title=Fixer guard::{_clean(path)}: installed={bool(g.get('installed'))} "
            f"loaded={bool(g.get('loaded'))} calls={int(g.get('calls') or 0)} blocked={len(blocked)}"
            + (f" ({blocked_tools})" if blocked_tools else "")
            + f" source={_clean(g.get('source') or 'muse', 20)} tools: {tool_list or 'none'}"
        )
        if g.get("installed") and not g.get("loaded"):
            out.append(f"::warning title=Fixer guard::{_clean(path)}: installed but no tool calls logged; "
                       "Muse Code may not have loaded .muse/hooks.json")
    return out


def main(argv: list[str] | None = None) -> int:
    roots = [Path(a) for a in (argv if argv is not None else sys.argv[1:])] or [Path("runs")]
    for line in lines_for(roots):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
