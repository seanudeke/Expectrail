"""Fetch PR descriptions and linked issues for the rows candidates.md dropped unread.

PR #125 review point 1: the first-pass filter dropped every GitHub-PR row for "no outside
reporter's words transcribed" without reading it. This fetches, for each such row, the PR
description and any linked issue (fixes/closes/resolves #N), and writes the excerpts to
pr-bodies.json beside this script. Transcription only: excerpts are whitespace-collapsed and
truncated; nothing is interpreted. candidates_dump.py then re-runs the filter with the fetched
words. Paced for GitHub's secondary rate limits; rerunnable (already-fetched refs are skipped).

    python3 bugs/reported/stress/fetch_pr_bodies.py
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
CANDIDATES = HERE.parent / "candidates.md"
OUT = HERE / "pr-bodies.json"
DROP_REASON = "no outside reporter's words transcribed"
URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
ISSUE_REF_RE = re.compile(
    r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*[:#]?\s*"
    r"(?:https://github\.com/[^\s)]+/(?:issues|pull)/|#)(\d+)", re.I)


def api(path: str):
    for attempt in range(3):
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            try:
                return json.loads(out.stdout)
            except json.JSONDecodeError:
                return None
        if "rate limit" in out.stderr.lower():
            time.sleep(60)
            continue
        return None  # 404 or hidden: recorded as unavailable
    return None


def excerpt(text: str | None, limit: int) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def main() -> None:
    bodies = json.loads(OUT.read_text()) if OUT.exists() else {}
    refs = []
    for line in CANDIDATES.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| c") or DROP_REASON not in line:
            continue
        m = URL_RE.search(line)
        if m:
            key = f"{m.group(1)}/{m.group(2)}#{m.group(3)}"
            if key not in bodies:
                refs.append((key, m.group(1), m.group(2), m.group(3)))
    print(f"{len(refs)} rows to fetch ({len(bodies)} already cached)", flush=True)
    for i, (key, owner, repo, num) in enumerate(refs, 1):
        pr = api(f"repos/{owner}/{repo}/pulls/{num}")
        entry = {"fetched": "2026-10-31"}
        if pr is None:
            entry["prBody"] = None
            entry["unavailable"] = True
        else:
            entry["prBody"] = excerpt(pr.get("body"), 600)
            m = ISSUE_REF_RE.search(pr.get("body") or "")
            if m:
                issue = api(f"repos/{owner}/{repo}/issues/{m.group(1)}")
                entry["linkedIssue"] = m.group(1)
                if issue and "pull_request" not in issue:
                    entry["issueAuthor"] = issue["user"]["login"]
                    entry["issueTitle"] = excerpt(issue.get("title"), 160)
                    entry["issueBody"] = excerpt(issue.get("body"), 400)
        bodies[key] = entry
        if i % 10 == 0:
            OUT.write_text(json.dumps(bodies, indent=1, ensure_ascii=False) + "\n")
            print(f"{i}/{len(refs)}", flush=True)
        time.sleep(0.7)
    OUT.write_text(json.dumps(bodies, indent=1, ensure_ascii=False) + "\n")
    linked = sum(1 for e in bodies.values() if e.get("issueTitle"))
    print(f"done: {len(bodies)} cached, {linked} with a linked issue's words")


if __name__ == "__main__":
    sys.exit(main())
