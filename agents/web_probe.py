"""Prompt sweep for the checkout page: which SAM prompt finds the right element, and nothing else?

The web bench's first SAM run caught every bug, but its detail lines showed why some checks split
one session each way: on the phone session "blue button" also matches the cart's count badge and the
page's theme toggle, so with the real button hidden SAM still reports a "blue button", and on the
desktop session "purple logo" matches the theme toggle once the logo is gone. A threshold set between
those distractors and the real button (0.71) then rejected Muse Code's correct live fix for layering
v2: with the promo bar moved just below the button, SAM scored the button 0.56 on the phone.

So the probe measures, for each candidate prompt, how SAM scores the element where the page draws it
(IoU of at least 0.5 with its paint box), on the clean page, on the bugs that hide or move it, and on
pages with a correct or intended change near it, two ways:

- alone: any detection counts, so every other match is a distractor (the badge, the toggle);
- in agreement with the page: only a detection on the page's own box for the element counts, so
  the only thing that can fool it is SAM scoring something there when the element is not drawn
  (the bar covering the button, a transparent button).

The ground truth is the page's own paint box (harness/web), not a human label. Three frames per
session (first, middle, last), so a sweep of the default prompts costs about 280 SAM images
(dispatch web-bench.yml with bench probe). Public patches only; nothing here edits a spec.

    python3 -m agents.web_probe --out runs/web-probe
    python3 -m agents.web_probe --prompt "button=wide blue button" --prompt "logo=purple logo" --out runs/web-probe
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.web_bench import CLEAN, ROUTES, iou
from expectrail.evaluator import DEFAULT_MIN_SCORE
from harness.run import REPO
from harness.web.run import run as web_run

# Each case: the patches that make the page, and whether the page draws each object where a shopper
# can see it. "fix/" and "good/" cases are pages with a change on top: the button is drawn, often with
# something new near it, which is what a threshold tuned on the bugs alone gets wrong.
CASES: dict[str, tuple[list[str], dict[str, bool]]] = {
    CLEAN: ([], {"button": True, "logo": True}),
    "dev/sinking/v2": (["bugs/sinking/v2"], {"button": True}),          # moved down by a transform, still drawn
    "dev/layering/v2": (["bugs/layering/v2"], {"button": False}),       # covered by the promo bar
    "dev/missing-texture/v2": (["bugs/missing-texture/v2"], {"button": False}),  # drawn transparent
    "dev/fall-through/v2": (["bugs/fall-through/v2"], {"button": False}),  # drawn above the page
    "dev/missing-texture/v1": (["bugs/missing-texture/v1"], {"logo": False}),  # the image fails to load
    # Muse Code's live fix for layering v2: the bar moved just below the button. SAM's phone score for
    # the button fell to 0.56, under the 0.71 the bugs alone had suggested, and the fix was rejected.
    "fix/move-bar-below": (["bugs/layering/v2", "candidates/fix-layering-move-bar-below"], {"button": True}),
    "good/intended-promo-bar": (["candidates/intended-promo-bar"], {"button": True}),
    "good/intended-place-order": (["candidates/intended-place-order"], {"button": True}),
}
PROMPTS: dict[str, list[str]] = {
    "button": ["blue button", "full-width blue button", "wide blue button", "blue checkout button",
               "Continue to checkout button"],
    "logo": ["purple logo", "purple B logo"],
}
MATCH_IOU = 0.5


def _score(d: dict) -> float:
    return d.get("score") or 0.0


def score_prompt(sessions: list[dict], name: str, prompt: str) -> dict:
    """sessions: [{"drawn": bool, "frames": [{"at": box or None, "found": {prompt: detections}}]}].

    ``at`` is where the page puts the element (its paint box, when CSS shows it in view), drawn or
    not. Two ways to use SAM's answer:
    - alone: any detection above the threshold counts, so everything not at the drawn element is a
      distractor;
    - in agreement with the page: only a detection on the page's box for the element counts, so the
      only thing that can fool it is SAM scoring something at that box when the element is not drawn
      there (a bar covering the button, a transparent button).
    """
    true_scores, firsts, distractors, at_false = [], 0, [], []
    frames_drawn = 0
    for s in sessions:
        for f in s["frames"]:
            found = sorted(f["found"].get(prompt) or [], key=lambda d: -_score(d))
            at = f["at"]
            on = [d for d in found if at is not None and iou(d["box"], at) >= MATCH_IOU]
            if s["drawn"]:
                frames_drawn += 1
                true_scores.append(max((_score(d) for d in on), default=0.0))
                firsts += bool(on) and found[0] in on
                distractors += [_score(d) for d in found if d not in on]
            else:
                distractors += [_score(d) for d in found]
                at_false += [_score(d) for d in on]
    lo = min(true_scores) if true_scores else None

    def verdict(hi: float) -> dict:
        return {"max": hi, "margin": None if lo is None else round(lo - hi, 3),
                "safeAtDefault": lo is not None and lo >= DEFAULT_MIN_SCORE and hi < DEFAULT_MIN_SCORE,
                "threshold": None if lo is None or lo <= hi else round((lo + hi) / 2, 2)}

    return {"object": name, "prompt": prompt, "drawnFrames": frames_drawn, "rankedFirst": firsts, "trueMin": lo,
            "alone": verdict(max(distractors, default=0.0)), "agreement": verdict(max(at_false, default=0.0))}


def probe_frames(frames: dict) -> list[int]:
    """The first, middle and last frames: the page as loaded, half filled in, and about to submit."""
    keys = sorted(frames)
    return sorted({keys[0], keys[len(keys) // 2], keys[-1]})


def collect(out: Path, prompts: dict[str, list[str]], client=None, cache=None) -> dict[str, list[dict]]:
    """Render each case's sessions, ask SAM for every prompt on three frames, and keep the page's boxes."""
    from agents.sam_observations import Cache, default_cache_dir, default_client, frame_files, observe
    from harness.web.layout import _in_view

    client = client or default_client(verdict=True)
    cache = cache if cache is not None else Cache(default_cache_dir())
    app = REPO / "apps" / "checkout"
    sessions: dict[str, list[dict]] = {name: [] for name in prompts}
    for key, (patch_ids, drawn) in CASES.items():
        names = [n for n in drawn if n in prompts]
        if not names:
            continue
        patches = [app / f"{pid}.patch" for pid in patch_ids]
        for route in ROUTES:
            run_dir = out / key.replace("/", "_") / route.stem
            web_run(route, run_dir, patches)
            trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
            rows = {r["frame"]: r for r in trace["rows"]}
            frames = frame_files(run_dir / "frames")
            chosen = probe_frames(frames)
            asks = {f"{n}|{p}": p for n in names for p in prompts[n]}
            seen = observe(frames, chosen, asks, client, cache)
            for n in names:
                per_frame = []
                for i in chosen:
                    element = rows[i]["elements"].get(n) or {}
                    box = element.get("painted")
                    at = list(box) if element.get("shown") and box and _in_view(box, trace["viewport"]) else None
                    per_frame.append({"frame": i, "at": at, "found": {p: seen[i][f"{n}|{p}"] for p in prompts[n]}})
                sessions[n].append({"variant": key, "route": route.stem, "drawn": drawn[n], "frames": per_frame})
    (out / "sessions.json").write_text(json.dumps(sessions, indent=1) + "\n", encoding="utf-8")
    return sessions


def _verdict(v: dict) -> str:
    return "safe" if v["safeAtDefault"] else f"split at {v['threshold']}" if v["threshold"] else "unsafe"


def summary(r: dict) -> str:
    true = "n/a" if r["trueMin"] is None else f"{r['trueMin']:.2f}"
    return (f'"{r["prompt"]}" true {true} first {r["rankedFirst"]}/{r["drawnFrames"]}; alone vs '
            f'{r["alone"]["max"]:.2f} {_verdict(r["alone"])}; on the page\'s box vs {r["agreement"]["max"]:.2f} '
            f'{_verdict(r["agreement"])}')


def report(sessions: dict[str, list[dict]], prompts: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    rows, lines = [], []
    for name, candidates in prompts.items():
        scored = [score_prompt(sessions[name], name, p) for p in candidates]
        rows += scored
        lines.append(f"::notice title=Prompt probe {name}::" + "; ".join(summary(r) for r in scored))
        for mode in ("alone", "agreement"):
            ok = [r for r in scored if r[mode]["margin"] is not None and r[mode]["margin"] > 0]
            label = "SAM alone" if mode == "alone" else "on the page's box"
            if ok:
                best = max(ok, key=lambda r: (r[mode]["safeAtDefault"], r[mode]["margin"]))
                lines.append(f"::notice title=Prompt probe {name} best, {label}::\"{best['prompt']}\": true min "
                             f"{best['trueMin']:.2f} against {best[mode]['max']:.2f}, "
                             + ("safe at the default minScore" if best[mode]["safeAtDefault"]
                                else f"needs minScore {best[mode]['threshold']}"))
            else:
                lines.append(f"::warning title=Prompt probe {name} best, {label}::no candidate separates the "
                             f"{name} on these sessions")
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
