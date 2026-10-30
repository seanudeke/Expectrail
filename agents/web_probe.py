"""Prompt sweep for the checkout page: which SAM prompt finds the right element, and nothing else?

The web bench's first SAM run caught every bug, but its detail lines showed why some checks split
one session each way: on the phone session "blue button" also matches the cart's count badge and the
page's theme toggle, so with the real button hidden SAM still reports a "blue button", and on the
desktop session "purple logo" matches the theme toggle once the logo is gone. This probe measures,
for each candidate prompt, how SAM scores the real element where the page draws it and how it scores
everything else, on the clean page and on the bugs that hide or move each element:

- sessions where the element is drawn (clean, the bugs that only move it): the score of the
  detection that matches where the page drew it (IoU of at least 0.5), and whether it ranks first;
- every other detection, and every detection on a session where the element is not drawn, is a
  distractor; the prompt is safe at a threshold when every true match clears it and no distractor
  does.

The ground truth is the page's own paint box (harness/web), not a human label. One frame per
session (the last), so a sweep of the default prompts costs about 80 SAM images. Public variants
only; nothing here edits a spec.

    python3 -m agents.web_probe --out runs/web-probe
    python3 -m agents.web_probe --prompt "button=wide blue button" --prompt "logo=purple logo" --out runs/web-probe
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.web_bench import CLEAN, ROUTES, dev_variants, iou
from expectrail.evaluator import DEFAULT_MIN_SCORE
from harness.run import REPO
from harness.web.run import run as web_run

# For each variant, whether the page draws each object where a shopper can see it.
CASES: dict[str, dict[str, bool]] = {
    CLEAN: {"button": True, "logo": True},
    "dev/sinking/v2": {"button": True},          # moved down by a transform, still drawn
    "dev/layering/v2": {"button": False},        # covered by the promo bar
    "dev/missing-texture/v2": {"button": False},  # drawn transparent
    "dev/fall-through/v2": {"button": False},    # drawn above the page
    "dev/missing-texture/v1": {"logo": False},   # the image fails to load
}
PROMPTS: dict[str, list[str]] = {
    "button": ["blue button", "wide blue button", "large blue button", "blue checkout button",
               "full-width blue button", "Continue to checkout button"],
    "logo": ["purple logo", "Bootstrap logo", "purple B logo", "purple square logo", "logo"],
}
MATCH_IOU = 0.5


def score_prompt(sessions: list[dict], name: str, prompt: str) -> dict:
    """sessions: [{"truth": box or None, "found": {prompt: detections}}] for one object."""
    true_scores, firsts, distractors = [], 0, []
    for s in sessions:
        found = sorted(s["found"].get(prompt) or [], key=lambda d: -(d.get("score") or 0))
        truth = s["truth"]
        matched = [d for d in found if truth is not None and iou(d["box"], truth) >= MATCH_IOU]
        others = [d for d in found if d not in matched]
        distractors += [d.get("score") or 0 for d in others]
        if truth is not None:
            best = max((d.get("score") or 0 for d in matched), default=0.0)
            true_scores.append(best)
            firsts += bool(matched) and found[0] in matched
    lo = min(true_scores) if true_scores else None
    hi = max(distractors, default=0.0)
    return {"object": name, "prompt": prompt, "drawnSessions": len(true_scores), "rankedFirst": firsts,
            "trueMin": lo, "distractorMax": hi, "margin": None if lo is None else round(lo - hi, 3),
            "safeAtDefault": lo is not None and lo >= DEFAULT_MIN_SCORE and hi < DEFAULT_MIN_SCORE,
            "threshold": None if lo is None or lo <= hi else round((lo + hi) / 2, 2)}


def collect(out: Path, prompts: dict[str, list[str]], client=None, cache=None) -> dict[str, list[dict]]:
    """Render each case's sessions, ask SAM for every prompt on the last frame, and keep the truth."""
    from agents.sam_observations import Cache, default_cache_dir, default_client, frame_files, observe

    client = client or default_client(verdict=True)
    cache = cache if cache is not None else Cache(default_cache_dir())
    variants = dev_variants()
    sessions: dict[str, list[dict]] = {name: [] for name in prompts}
    for key, drawn in CASES.items():
        names = [n for n in drawn if n in prompts]
        if not names:
            continue
        patches = [] if key == CLEAN else [variants[key]]
        for route in ROUTES:
            run_dir = out / key.replace("/", "_") / route.stem
            web_run(route, run_dir, patches)
            trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
            frames = frame_files(run_dir / "frames")
            last = max(frames)
            row = next(r for r in trace["rows"] if r["frame"] == last)
            asks = {f"{n}|{p}": p for n in names for p in prompts[n]}
            seen = observe(frames, [last], asks, client, cache)[last]
            for n in names:
                element = row["elements"].get(n) or {}
                truth = list(element["painted"]) if drawn[n] and element.get("shown") else None
                sessions[n].append({"variant": key, "route": route.stem, "truth": truth,
                                    "found": {p: seen[f"{n}|{p}"] for p in prompts[n]}})
    (out / "sessions.json").write_text(json.dumps(sessions, indent=1) + "\n", encoding="utf-8")
    return sessions


def summary(r: dict) -> str:
    true = "n/a" if r["trueMin"] is None else f"{r['trueMin']:.2f}"
    verdict = "safe" if r["safeAtDefault"] else f"split at {r['threshold']}" if r["threshold"] else "unsafe"
    return (f'"{r["prompt"]}" true {true} first {r["rankedFirst"]}/{r["drawnSessions"]} '
            f'distractor {r["distractorMax"]:.2f} {verdict}')


def report(sessions: dict[str, list[dict]], prompts: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    rows, lines = [], []
    for name, candidates in prompts.items():
        scored = [score_prompt(sessions[name], name, p) for p in candidates]
        rows += scored
        parts = [summary(r) for r in scored]
        lines.append(f"::notice title=Prompt probe {name}::" + "; ".join(parts))
        ok = [r for r in scored if r["rankedFirst"] == r["drawnSessions"] and r["margin"] is not None and r["margin"] > 0]
        if ok:
            best = max(ok, key=lambda r: (r["safeAtDefault"], r["margin"]))
            lines.append(f"::notice title=Prompt probe {name} best::\"{best['prompt']}\": every drawn {name} ranked "
                         f"first, true min {best['trueMin']:.2f}, distractor max {best['distractorMax']:.2f}, "
                         + ("safe at the default minScore" if best["safeAtDefault"]
                            else f"needs minScore {best['threshold']}"))
        else:
            lines.append(f"::warning title=Prompt probe {name} best::no candidate separates the {name} from "
                         "everything else on these sessions")
    return rows, lines


def parse_prompts(values: list[str]) -> dict[str, list[str]]:
    if not values:
        return PROMPTS
    chosen: dict[str, list[str]] = {}
    for value in values:
        name, sep, prompt = value.partition("=")
        if not sep or name not in PROMPTS or not prompt.strip():
            raise SystemExit(f"--prompt takes OBJECT=PROMPT with OBJECT one of {sorted(PROMPTS)}: {value!r}")
        chosen.setdefault(name, []).append(prompt.strip())
    return chosen


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--prompt", action="append", default=[], help="OBJECT=PROMPT (default: the built-in candidates)")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "web-probe")
    args = p.parse_args(argv)
    prompts = parse_prompts(args.prompt)
    args.out.mkdir(parents=True, exist_ok=True)
    sessions = collect(args.out, prompts)
    rows, lines = report(sessions, prompts)
    (args.out / "probe.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
