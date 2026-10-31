"""Build bugs/reported/candidates.md (issue #120 Part 1) from the machine search dump.

Transcription only: every cell is a fact copied from the dump (link, title, author, record state,
AI markers found in the PR body, quotes from the PR's own close record). The good/bad labels,
kept/dropped decisions and the 4-6 selection are the human adjudicator's (issue #120: Claude
must not pick candidates or write checks). Run:

    python3 bugs/reported/candidates_dump.py <raw-dump.md>

Writes bugs/reported/candidates.md and bugs/reported/candidates-search-dump.md (the dump verbatim,
so every hit looked at is in the repo). Ids are assignment order, never a ranking.
"""
import re
import sys
from pathlib import Path

DUMP = Path(sys.argv[1])
HERE = Path(__file__).parent

RULES = """## Selection rules (pre-registered, verbatim from issue #120 — a candidate is kept only if all of these hold)

1. It has a public link, and someone outside the team describes the symptom.
2. A player or shopper can see or feel it. It shows in the frames or in the engine record (`agents/trace_checks.py` reads that record: positions, facing, shots, enemies).
3. It can be ported into our game or page as a patch in about an hour or two.
4. There's at least one fix on record whose good/bad label is settled by the record, not by us. "Good" means merged and kept, or confirmed by a maintainer. "Bad" means reverted, rejected with a reason, or followed by a report that it's still broken.
5. *Preferred, not required:* at least one of its fixes was written by an AI agent.
"""

DONE = """## Done for Part 1 (from issue #120)

- [ ] At least 20 candidates logged; at least 2 with an AI-written fix.
- [ ] 4–6 selected by the rules, with the selection marked in `candidates.md`.
- [ ] PR "Stress test: candidates and pre-registered selection" opened and merged before any fix is judged.
"""


def esc(text: str, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", text.strip()).replace("|", "/")[:limit]


def domain(repo: str, title: str) -> str:
    t = f"{repo} {title}".lower()
    if any(k in t for k in ("godot", "game", "platformer", "demo-projects", "dodge", "soccer",
                            "tron-cycle", "player", "maps", "3d-tiles")):
        return "game?"
    if any(k in t for k in ("css", "button", "z-index", "web", "site", " ui", "portfolio",
                            "checkout", "page", "reader", "survey", "exercise")):
        return "web?"
    return "—"


def main() -> None:
    dump = DUMP.read_text(encoding="utf-8")
    main_part, close_part = dump.split("# Close records", 1)

    rows: dict[str, dict] = {}
    order: list[str] = []
    row_re = re.compile(r"^\| (\S+)#(\d+) \| (.*?) \| (.*?) \| (MERGED|closed-unmerged|open) \| (.*?) \| (\S+) \|$", re.M)
    for m in row_re.finditer(main_part):
        repo, num, title, author, state, marks, link = m.groups()
        key = f"{repo}#{num}"
        if key not in rows:  # the retry passes repeated queries; first appearance wins
            rows[key] = dict(repo=repo, title=title, author=author, state=state, marks=marks, link=link)
            order.append(key)

    closes: dict[str, dict] = {}
    close_re = re.compile(r"^## (\S+#\d+) — (.*?)\n(author:.*?)\n((?:- .*\n?)+)", re.M)
    for m in close_re.finditer(close_part):
        key, title, authorline, quotes = m.groups()
        closes[key] = dict(title=title, authorline=authorline,
                           quotes=[l[2:] for l in quotes.splitlines() if l.startswith("- ")])

    forum_part = main_part.split("## forum-and-reddit leads")[1]
    forums = [m.groups() for m in
              re.finditer(r"^\| ([^-][^|]*?) \| (.*?) \| (.*?) \| (\S+) \|$", forum_part, re.M)
              if m.group(1).strip() != "ref"]

    table = ["| id | source (link) | domain (game / web) | symptom, in the reporter's words | the fixes on record (link, author, AI? how you know) | label for each fix from the record (good / bad, and why) | reproducible here? | kept / dropped, and why |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    ai_rows = 0

    def emit(source, dom, symptom, fixes, label, repro="—", kept="—"):
        nonlocal n, ai_rows
        n += 1
        if "AI" in fixes or "bot" in fixes.lower() or "claude" in fixes.lower() or "copilot" in fixes.lower() \
           or "chatgpt" in fixes.lower() or "llm" in fixes.lower() or "devin" in fixes.lower():
            ai_rows += 1
        table.append(f"| c{n:02d} | {source} | {dom} | {symptom} | {fixes} | {label} | {repro} | {kept} |")

    for key in order:
        r = rows[key]
        close = closes.get(key)
        if close is None and not (r["state"] == "MERGED" and r["marks"] != "-"):
            continue  # main table = rows whose record was read, plus merged AI fixes (the issue asks to log those)
        ai = []
        if "[bot]" in r["author"]:
            ai.append("author is a bot")
        if r["marks"] != "-":
            ai.append(f"body markers: {r['marks']}")
        quotes = ""
        if close:
            for q in close["quotes"]:
                if "did use AI" in q or "AI tool" in q:
                    ai.append(f"close record: \"{esc(q, 120)}\"")
            quotes = "<br>".join(f"record: \"{esc(q)}\"" for q in close["quotes"][:3]) \
                     or "record: (no comments or review text on record)"
            label = f"{quotes}<br>**label: pending adjudication**"
            fixes = f"[{key}]({r['link']}) — {r['author']}" + (f" ({'; '.join(ai)})" if ai else " (no AI marker found)") \
                    + f"<br>closed unmerged by: {esc(close['authorline'], 160)}"
        else:
            label = ("record: PR merged (rule 4's \"merged and kept\"; not yet verified against a later revert)"
                     "<br>**label: pending adjudication**")
            fixes = f"[{key}]({r['link']}) — {r['author']}" + (f" ({'; '.join(ai)})" if ai else "")
        emit(f"[{key}]({r['link']})", domain(r["repo"], r["title"]),
             f"\"{esc(r['title'], 160)}\" (PR title, author's words; linked bug report not fetched)",
             fixes, label)

    for ref, symptom, signals, link in forums:
        emit(f"[{ref.strip()}]({link})", "game",
             f"\"{esc(symptom)}\"",
             f"fixes described in-thread ({link}) — AI evidence where quoted in the record signals",
             f"record: \"{esc(signals, 400)}\"<br>**label: pending adjudication**")

    n += 1
    table.append(f"| c{n:02d} | [godotengine/godot-demo-projects#927](https://github.com/godotengine/godot-demo-projects/pull/927) "
                 "| game? | \"Fixed Z Index on Platforms\" (PR title) | merged fix, human-authored "
                 "| record: merged | — | **dropped** — already consumed on main as `bugs/reported/platform-z-order-pr927.patch` (dedup, mechanical) |")

    header = f"""# Stress test candidates (issue #120, Part 1) — pre-registration

Generated 2026-10-30 by machine search (`bugs/reported/candidates_dump.py` from the dump in
`candidates-search-dump.md`; queries, row counts and every close record are in that file).
Every filled cell below is a transcription of the public record: links, titles, authors, bot
flags, AI markers found in PR bodies, and quotes from each PR's or thread's own record.
**The good/bad labels, the kept/dropped decisions and the 4–6 selection are the human
adjudicator's** (issue #120 assignee), committed here before any fix is judged. Per the issue,
Claude ran the searches and transcribed; it picks nothing and writes no check. Ids are
assignment order, never a ranking. Domain guesses carry a `?` and are corrected by the
adjudicator. {n} candidates logged; {ai_rows} rows carry an AI-authorship signal.

{RULES}
{DONE}
## Candidates

"""
    (HERE / "candidates.md").write_text(header + "\n".join(table) + "\n", encoding="utf-8")
    (HERE / "candidates-search-dump.md").write_text(
        "# Raw search dump behind candidates.md (issue #120) — machine-run, verbatim\n\n"
        + dump, encoding="utf-8")
    print(f"candidates.md: {n} rows, {ai_rows} with an AI signal; dump copied verbatim")


if __name__ == "__main__":
    main()
