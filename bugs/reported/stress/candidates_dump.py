"""Build bugs/reported/candidates.md (issue #120 Part 1) from the machine search dump.

Transcription only: every filled cell is a fact copied from the dump (link, title, author, bot
flags, AI-disclosure evidence, quotes from each PR's or thread's own record), plus a uniform
mechanical first-pass filter (PR #125 review): the same three drop rules applied to every row,
with the reason on the row. The good/bad labels, the final kept/dropped decisions and the 4-6
selection are the human adjudicator's (issue #120: Claude picks no candidate and writes no
check); a first-pass mark is never final — the adjudicator may overturn any row.

Regeneration is label-safe: a row is matched to the existing candidates.md by its source link,
and any cell that differs from the generator's own default (a corrected domain, a filled label,
a reproducible entry, an overridden kept/dropped) is carried over untouched.

AI evidence is graded, never substring-matched across the whole row:
  strong = the PR's author is a bot, or it was found by a query that matches an exact disclosure
           phrase in the body ("Generated with Claude Code", "Co-Authored-By: Copilot") or a bot
           author (author:app/copilot-swe-agent, author:app/devin-ai-integration), or its close
           record quotes an AI admission / AI-tools moderation action, or a forum thread quotes
           the AI advice by name (ChatGPT, LLM, ...).
  weak   = a bare keyword (claude, copilot, sweep, ...) somewhere in the PR body, word-bounded.
           "robot" is not "bot"; "LeafSweeper" is not "sweep".

Run:
    python3 bugs/reported/stress/candidates_dump.py <raw-dump.md>

Writes ../candidates.md and candidates-search-dump.md beside this script (the dump verbatim, so
every hit looked at is in the repo). Ids are assignment order, never a ranking.
"""
import json
import re
import sys
from pathlib import Path

DUMP = Path(sys.argv[1])
HERE = Path(__file__).parent
OUT = HERE.parent / "candidates.md"

RULES = """## Selection rules (pre-registered, verbatim from issue #120 — a candidate is kept only if all of these hold)

1. It has a public link, and someone outside the team describes the symptom.
2. A player or shopper can see or feel it. It shows in the frames or in the engine record (`agents/trace_checks.py` reads that record: positions, facing, shots, enemies).
3. It can be ported into our game or page as a patch in about an hour or two.
4. There's at least one fix on record whose good/bad label is settled by the record, not by us. "Good" means merged and kept, or confirmed by a maintainer. "Bad" means reverted, rejected with a reason, or followed by a report that it's still broken.
5. *Preferred, not required:* at least one of its fixes was written by an AI agent.
"""

DONE = """## Done for Part 1 (from issue #120)

- [x] At least 20 candidates logged; at least 2 with an AI-written fix.
- [ ] 4–6 selected by the rules, with the selection marked in `candidates.md`. Not done by the
  November 1 numbers freeze; see the status note above.
- [x] PR "Stress test: candidates and pre-registered selection" opened and merged before any fix is
  judged (no fix was judged).
"""

FILTER = """## First-pass mechanical filter (PR #125 review; applied to every row the same way, before any labelling)

A row is first-pass **dropped**, with the reason on the row, when any of these holds — checked
in this fixed order, first match wins:

1. **Out of scope** — the repo or thread is not a game-level Godot 4 bug or a single-page web UI
   bug (the issue's Scope section): 3D, engine (C++), platform-specific, not Godot, multi-page
   web, or a repo whose subject can't be ported into `game/platformer` or `apps/checkout/site`.
2. **Not a bug fix** — the record shows a feature, art pass, map, theme, docs, refactor,
   rebuild, scaffold or housekeeping, not a fix for a reported symptom.
3. **No outside reporter's words transcribed** — neither the fetched PR body nor a linked issue
   describes broken behaviour. (Recoverable: the adjudicator can order a fetch for a specific
   row instead of dropping it.)
4. **No visible symptom indicated** (rule 2) — the transcribed record names nothing a player or
   shopper can see or feel and nothing the engine record shows (positions, facing, shots,
   enemies).

Forum/reddit rows pass 3 when the thread quotes the reporter's own words. A first-pass mark is
never final: the adjudicator may overturn any row, and every overturn is recorded with a reason.
"""

# Rule 1 of the filter, by repo (lowercased substring) — reasons are the issue's Scope section.
OUT_REPOS = {
    "powertoys": "not game/web UI (Windows utility)",
    "atmos": "not game/web UI (infra tooling)",
    "niemandsland": "tabletop rules repo; rules features, not portable into our game",
    "3d-tiles": "3D (out of scope)",
    "xbox-godot-sample": "platform-specific console sample (out of scope)",
    "personal-website": "multi-page portfolio site, not single-page web UI",
    "reader": "multi-page app UI redesign, not single-page web UI",
    "exercise1_cswp": "coursework app; spec-alignment work, not our domain",
    "q-lost-and-found": "UI redesign of another app, not single-page checkout-style UI",
    "tron-cycle": "theme/color feature in another game",
    "straif": "map additions in another game",
    "dicesoccerleague": "game rebuild / testing-skill work in another game",
    "crimson-thread": "map redesign in another game",
    "gambling-with-the-devil": "content work in another game",
    "alien-connection": "project scaffold in another game",
    "/pds": ".gitignore housekeeping, not our domain",
    "trench-sim": "client bootstrap in another game",
    "timmy-tui": "terminal UI, not game/web",
    "openhands": "agent-infra repo, not a game/web bug",
    "motioneye": "surveillance appliance UI, not our domain",
    "surveysolutions": "survey platform, not our domain",
}
# Rule 1, specific refs that no repo substring catches.
OUT_REFS = {
    "godot#97354": "engine-level (C++) issue, out of scope per the issue",
    "forum 131732": "CharacterBody3D — 3D, out of scope",
}
# Rule 2 of the filter: feature-shaped titles (word-bounded; "Add missing ..." stays a fix).
NOT_FIX_RE = re.compile(
    r"^(add(?!.*\bmissing\b)|feat\b|improve|rebuild|redesign|enhance|update theme|streamline|"
    r"(?:ajouter|ajout\b|am\u00e9lioration|am\u00e9liorer|mise \u00e0 jour|cr\u00e9er|cr\u00e9ation|refonte|agregar|a\u00f1adir|a\u00f1ade|"
    r"mejorar|mejora\b|actualizar|actualizaci\u00f3n|redise\u00f1ar|adicionar|melhorar|criar\b)|"
    r"align .* with .* spec|make .* api\b)", re.I)
# Rule 2, refs whose record shows non-fix work despite a fix-shaped title.
NOT_FIX_REFS = {
    "vasiltop/straif#16": "record: 'add atrium, causeway, and reactor practice maps' — feature",
}
STRONG_SECTIONS = {
    # queries that match an exact disclosure phrase in the body ...
    "ai-disclosed-godot", "ai-disclosed-web", "copilot-coauthor-godot",
    # ... or a coding-agent bot author
    "copilot-agent-godot", "copilot-agent-web", "devin-godot",
}
STRONG_QUOTE_RE = re.compile(
    r"\b(use AI|AI tools|used AI|asked chatgpt|Generated with Claude|Co-[Aa]uthored-[Bb]y:? Copilot|LLM|"
    r"ChatGPT|OpenHands|Devin|Codex)\b", re.I)
WEAK_RE = re.compile(r"\b(ai|claude|copilot|devin|openhands|sweep|codex|chatgpt|llm)\b", re.I)
# Rule 1 from fetched text: an outside description of broken behaviour (PR body or linked issue).
SYMPTOM_RE = re.compile(r"(doesn'?t|didn'?t|not work|no longer|broken|broke\b|bug|fail|crash|error|"
                        r"wrong|incorrect|missing|cannot|can'?t|unable|regression|invalid|unexpected)", re.I)
# Rule 2 of the filter: the record indicates something a player or shopper sees or feels, or the
# engine record shows (positions, facing, shots, enemies).
VISIBLE_RE = re.compile(r"(mov|jump|fall|collid|enemy|enemies|gun|shoot|shot|coin|sprite|draw|"
                        r"z[_ -]?index|visib|hidden|hide|texture|button|click|layout|overflow|image|"
                        r"form\b|scroll|animat|position|facing|patrol|platform|tilemap|camera|ysort|"
                        r"y-sort|render|display|screen|menu|input|focus)", re.I)
POLICY_CLOSE_RE = re.compile(r"AI tools|moderation question|lack of response", re.I)

DEFAULT_LABEL_SUFFIX = "**label: pending adjudication**"


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


def first_pass(ref: str, repo: str, title: str, has_reporter_words: bool,
               visible_text: str = "") -> str | None:
    """The uniform filter: a drop reason, or None when the row survives."""
    if ref in OUT_REFS:
        return f"out of scope — {OUT_REFS[ref]}"
    for frag, reason in OUT_REPOS.items():
        if frag in repo.lower():
            return f"out of scope — {reason}"
    if ref in NOT_FIX_REFS:
        return f"not a bug fix — {NOT_FIX_REFS[ref]}"
    if NOT_FIX_RE.search(title.strip()):
        return f"not a bug fix — feature-shaped title (\"{esc(title, 60)}\")"
    if not has_reporter_words:
        return ("no outside reporter's words transcribed — neither the PR body nor a linked issue "
                "describes broken behaviour (recoverable: order a fetch instead)")
    if not VISIBLE_RE.search(visible_text):
        return "no player/shopper-visible symptom indicated in the record (rule 2)"
    return None


def load_existing() -> dict[str, list[str]]:
    """Existing candidates.md rows by source link, so human cells survive regeneration.
    shortcut: a cell counts as human when it differs from this run's default — if the generator's
    own defaults change between runs, delete candidates.md first (no adjudication lost) or the
    old defaults get carried over as if adjudicated."""
    if not OUT.exists():
        return {}
    rows = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| c"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) == 8:
            rows[cells[1]] = cells
    return rows


def main() -> None:
    dump = DUMP.read_text(encoding="utf-8")
    main_part, close_part = dump.split("# Close records", 1)

    rows: dict[str, dict] = {}
    order: list[str] = []
    row_re = re.compile(r"^\| (\S+)#(\d+) \| (.*?) \| (.*?) \| (MERGED|closed-unmerged|open) \| (.*?) \| (\S+) \|$")
    section = ""
    for line in main_part.splitlines():
        if line.startswith("## "):
            section = line[3:].split(":", 1)[0].strip()
            continue
        m = row_re.match(line)
        if not m:
            continue
        repo, num, title, author, state, marks, link = m.groups()
        key = f"{repo}#{num}"
        if key not in rows:
            rows[key] = dict(repo=repo, title=title, author=author, state=state, marks=marks,
                             link=link, sections=set())
            order.append(key)
        rows[key]["sections"].add(section)

    closes: dict[str, dict] = {}
    close_re = re.compile(r"^## (\S+#\d+) — (.*?)\n(author:.*?)\n((?:- .*\n?)+)", re.M)
    for m in close_re.finditer(close_part):
        key, title, authorline, quotes = m.groups()
        closes[key] = dict(authorline=authorline,
                           quotes=[l[2:] for l in quotes.splitlines() if l.startswith("- ")])

    forum_part = main_part.split("## forum-and-reddit leads")[1]
    forums = [m.groups() for m in
              re.finditer(r"^\| ([^-][^|]*?) \| (.*?) \| (.*?) \| (\S+) \|$", forum_part, re.M)
              if m.group(1).strip() != "ref"]

    bodies = json.loads((HERE / "pr-bodies.json").read_text()) if (HERE / "pr-bodies.json").exists() else {}
    existing = load_existing()
    table = ["| id | source (link) | domain (game / web) | symptom, in the reporter's words | the fixes on record (link, author, AI? how you know) | label for each fix from the record (good / bad, and why) | reproducible here? | kept / dropped, and why |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    n = survives = strong_n = survive_strong = 0

    def human_or(source: str, idx: int, default: str) -> str:
        stored = existing.get(source)
        return stored[idx] if stored and stored[idx] != default else default

    def emit(source: str, dom: str, symptom: str, fixes: str, label: str, kept: str,
             strong: bool) -> None:
        nonlocal n, survives, strong_n, survive_strong
        n += 1
        strong_n += strong
        dom = human_or(source, 2, dom)
        label = human_or(source, 5, label)
        repro = human_or(source, 6, "—")
        kept = human_or(source, 7, kept)
        if kept.startswith("first-pass: survives") or kept.startswith("**kept"):
            survives += 1
            survive_strong += strong
        table.append(f"| c{n:02d} | {source} | {dom} | {symptom} | {fixes} | {label} | {repro} | {kept} |")

    for key in order:
        r = rows[key]
        close = closes.get(key)
        strong_sections = r["sections"] & STRONG_SECTIONS
        if close is None and not (r["state"] == "MERGED" and (r["marks"] != "-" or strong_sections)):
            continue  # main table = rows whose record was read, plus merged AI fixes (the issue asks to log those)
        ai, strong = [], False
        if "[bot]" in r["author"]:
            ai.append("author is a bot (strong)")
            strong = True
        if strong_sections:
            ai.append(f"found by exact-disclosure/bot-author query: {', '.join(sorted(strong_sections))} (strong)")
            strong = True
        if r["marks"] != "-" and WEAK_RE.search(r["marks"].replace(",", " ")):
            ai.append(f"body keywords: {r['marks']} (weak)")
        quotes = ""
        if close:
            for q in close["quotes"]:
                if STRONG_QUOTE_RE.search(q):
                    ai.append(f"close record: \"{esc(q, 120)}\" (strong)")
                    strong = True
            quotes = "<br>".join(f"record: \"{esc(q)}\"" for q in close["quotes"][:3]) \
                     or "record: (no comments or review text on record)"
            label = quotes
            if POLICY_CLOSE_RE.search(" ".join(close["quotes"])):
                label += ("<br>note: the record settles an AI-policy closure only; correctness "
                          "unsettled (rule 4 needs a correctness reason)")
            label += f"<br>{DEFAULT_LABEL_SUFFIX}"
            fixes = f"[{key}]({r['link']}) — {r['author']}" + (f" ({'; '.join(ai)})" if ai else " (no AI evidence found)") \
                    + f"<br>closed unmerged by: {esc(close['authorline'], 160)}"
        else:
            label = ("record: PR merged (rule 4's \"merged and kept\"; not yet verified against a later revert)"
                     f"<br>{DEFAULT_LABEL_SUFFIX}")
            fixes = f"[{key}]({r['link']}) — {r['author']}" + (f" ({'; '.join(ai)})" if ai else "")
        body_info = bodies.get(key) or {}
        symptom = f"\"{esc(r['title'], 160)}\" (PR title, author's words)"
        has_words, visible = False, r["title"]
        if body_info.get("prBody"):
            symptom += f"<br>PR body: \"{esc(body_info['prBody'], 300)}\""
            visible += " " + body_info["prBody"]
            has_words = bool(SYMPTOM_RE.search(body_info["prBody"]))
        if body_info.get("issueTitle"):
            symptom += (f"<br>linked issue #{body_info['linkedIssue']} by {body_info['issueAuthor']}: "
                        f"\"{esc(body_info['issueTitle'], 120)} — {esc(body_info.get('issueBody') or '', 250)}\"")
            visible += " " + body_info["issueTitle"] + " " + (body_info.get("issueBody") or "")
            has_words = True
        if body_info.get("unavailable"):
            symptom += "<br>(PR unavailable: 404 or hidden)"
        if not body_info:
            symptom += "; body not fetched"
        drop = first_pass(key, r["repo"], r["title"], has_reporter_words=has_words, visible_text=visible)
        kept = (f"first-pass: **drop** — {drop} (adjudicator may overturn)" if drop
                else "first-pass: survives — adjudication pending")
        emit(f"[{key}]({r['link']})", domain(r["repo"], r["title"]), symptom, fixes, label, kept, strong)

    for ref, symptom, signals, link in forums:
        ref = ref.strip()
        strong = bool(STRONG_QUOTE_RE.search(f"{signals} {symptom}"))
        ai = "thread quotes the AI advice by name (strong)" if strong else "no AI evidence quoted in the record signals"
        drop = first_pass(ref, "", ref + " " + symptom, has_reporter_words=True,
                          visible_text=f"{symptom} {signals}")
        kept = (f"first-pass: **drop** — {drop} (adjudicator may overturn)" if drop
                else "first-pass: survives — adjudication pending")
        emit(f"[{ref}]({link})", "game", f"\"{esc(symptom)}\"",
             f"fixes described in-thread ([{ref}]({link})) — {ai}",
             f"record: \"{esc(signals, 800)}\"<br>{DEFAULT_LABEL_SUFFIX}", kept, strong)

    n += 1
    table.append(f"| c{n:02d} | [godotengine/godot-demo-projects#927](https://github.com/godotengine/godot-demo-projects/pull/927) "
                 "| game? | \"Fixed Z Index on Platforms\" (PR title) | merged fix, human-authored "
                 "| record: merged | — | **dropped** — already consumed on main as `bugs/reported/platform-z-order-pr927.patch` (dedup, mechanical) |")

    header = f"""# Stress test candidates (issue #120, Part 1) — pre-registration

Generated 2026-10-31 by machine search (`bugs/reported/stress/candidates_dump.py` from the dump in
`bugs/reported/stress/candidates-search-dump.md`; queries, row counts and every close record are in
that file). Every filled cell is a transcription of the public record — links, titles, authors,
bot flags, graded AI-disclosure evidence, quotes from each PR's or thread's own record — plus the
uniform first-pass filter below. **The good/bad labels, the final kept/dropped decisions and the
4–6 selection are the human adjudicator's** (issue #120 assignee), committed here before any fix
is judged; a first-pass mark is never final. Per the issue, Claude ran the searches and
transcribed; it picks nothing and writes no check. Ids are assignment order, never a ranking.
Domain guesses carry a `?` and are corrected by the adjudicator. Labels quote the record only and
never characterize a person.

{n} candidates logged; {strong_n} rows carry strong AI evidence (bot author, exact-disclosure
query match, or an AI admission/quote in the record — the grader is case-insensitive and reads
the symptom column too), {survives} survive the first-pass filter ({survive_strong} of those
with strong AI evidence). PR bodies and linked issues were fetched for every row the filter had
dropped unread (`bugs/reported/stress/fetch_pr_bodies.py` → `pr-bodies.json`, excerpts in the
symptom cells). Regenerating this file preserves every adjudicated cell (matched by source link).

**What "survives the first pass" means:** the first pass is a word-matching screen, not a check of
the selection rules, and no survivor has been shown to meet rules 1–4. Rows that pass rule 1 on a
PR description alone rest on the PR author's own words, and that author is often the AI agent that
wrote the fix. Rule 3 (can it be ported here in an hour or two) is not screened at all.

**Status at the numbers freeze (November 1, 2026):** Part 1 is this log, the rules registered before
any judging, and the tooling. No candidate was selected, ported or judged before the freeze, so
Part 2 was closed (issue #120) and no stress-test numbers are claimed anywhere. Anyone continuing it
starts from the adjudication: label each survivor from its record, then select 4–6 by the rules.

**Write-up caution (PR #125 review, @seanudeke, Oct 31):** most surviving records are setup
mistakes — a missing `move_and_slide`, a collision shape in the wrong place, a Focus Mode left
at None; ported into our game they break it in ways any check catches. Keep "Expectrail caught
the bug" separate from "only Expectrail rejected a bad fix" in the results. The AI-involved
forum survivors are advice in threads, not patches, and the AI-written PR survivors are mostly
merged fixes, whose record label would be good; if the AI-written-bad-fix count lands near zero,
the write-up says so plainly.

{RULES}
{FILTER}
{DONE}
## Candidates

"""
    OUT.write_text(header + "\n".join(table) + "\n", encoding="utf-8")
    prefix = "# Raw search dump behind candidates.md (issue #120) — machine-run, verbatim\n\n"
    # Rerunning from the committed copy must not stack a second prefix on it.
    (HERE / "candidates-search-dump.md").write_text(
        prefix + dump.removeprefix(prefix), encoding="utf-8")
    print(f"candidates.md: {n} rows logged, {strong_n} strong-AI, {survives} survive first pass "
          f"({survive_strong} strong-AI); dump copied beside the script")


if __name__ == "__main__":
    main()
