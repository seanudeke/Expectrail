"""What the Meta Model API usage export says we used, and what it comes to at list price.

The export from dev.meta.ai (Usage, then Export) covers the whole team: SAM 3.1 images and video
frames, and the Muse model tokens behind Muse Code, the screenshot judge and the spec writer. It
also reports the amount billed. This prints both, per day and in total, so the cost on screen comes
from the provider's own counts.

    python3 -m agents.usage_report bench/cost/meta-usage-2026-10-24-to-30.csv --credits 150

List prices are from https://dev.meta.ai/docs/pricing-rate-limits (read October 29, 2026). The page
does not say which model or mode Muse Code uses, so tokens are priced both at Muse Spark Standard and
at Contributor rates, and the report says which total matches what was actually spent. Free credits
do not appear in the export: ``--credits`` adds what the team used before billing started.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

PRICES = {  # USD per unit
    ("images_processed", "total"): 2.50 / 1000,       # sam-3.1 image segmentation
    ("video_frames_processed", "total"): 0.20 / 1000,  # sam-3.1 video segmentation
    ("input_tokens", "cached"): 0.15 / 1e6,             # Muse Spark Standard
    ("input_tokens", "uncached"): 1.25 / 1e6,
    ("output_tokens", "output"): 4.25 / 1e6,
}
SAM = {("images_processed", "total"), ("video_frames_processed", "total")}
CONTRIBUTOR = {  # Muse Spark Contributor mode: Meta may use the content to train its models
    ("input_tokens", "cached"): 0.002 / 1e6,
    ("input_tokens", "uncached"): 0.10 / 1e6,
    ("output_tokens", "output"): 0.20 / 1e6,
}


def read(path: Path) -> dict[str, dict[tuple[str, str], float]]:
    """{date: {(metric, series): value}} from the export (UTF-8 with a byte-order mark, CRLF)."""
    days: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            days[row["date"]][(row["metric"], row["series"])] += float(row["value"])
    return {d: dict(v) for d, v in sorted(days.items())}


def summarize(days: dict[str, dict[tuple[str, str], float]], credits: float = 0.0) -> dict:
    out_days = []
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for date, values in days.items():
        for k, v in values.items():
            totals[k] += v
        out_days.append({"date": date, **_costs(values)})
    total = _costs(totals)
    actual = round(total["billedUsd"] + credits, 2)
    fits = {"standard": total["listUsd"], "contributor": total["listContributorUsd"]}
    best = min(fits, key=lambda k: abs(fits[k] - actual))
    return {"days": [d for d in out_days if d["requests"] or d["billedUsd"]], "total": total,
            "creditsUsd": round(credits, 2), "actualUsd": actual,
            "museModeThatMatches": best, "matchOffUsd": round(abs(fits[best] - actual), 2)}


def _costs(values: dict[tuple[str, str], float]) -> dict:
    sam = sum(values.get(k, 0) * p for k, p in PRICES.items() if k in SAM)
    muse = sum(values.get(k, 0) * p for k, p in PRICES.items() if k not in SAM)
    muse_contributor = sum(values.get(k, 0) * p for k, p in CONTRIBUTOR.items())
    return {
        "requests": int(values.get(("requests", "total"), 0)),
        "samImages": int(values.get(("images_processed", "total"), 0)),
        "samVideoFrames": int(values.get(("video_frames_processed", "total"), 0)),
        "inputTokensCached": int(values.get(("input_tokens", "cached"), 0)),
        "inputTokensUncached": int(values.get(("input_tokens", "uncached"), 0)),
        "outputTokens": int(values.get(("output_tokens", "output"), 0)),
        "samListUsd": round(sam, 2),
        "museListUsd": round(muse, 2),
        "listUsd": round(sam + muse, 2),
        "museContributorUsd": round(muse_contributor, 2),
        "listContributorUsd": round(sam + muse_contributor, 2),
        "billedUsd": round(values.get(("spend", "total"), 0), 2),
    }


def markdown(doc: dict, source: str) -> str:
    lines = ["# Model API usage and cost", "",
             (f"Written by `python3 -m agents.usage_report {source}` from the dev.meta.ai usage export for the "
              "team (all keys); do not edit by hand. List prices: dev.meta.ai/docs/pricing-rate-limits, read "
              "October 29, 2026; tokens at Muse Spark Standard rates."), "",
             ("| Day | Requests | SAM images | SAM video frames | Muse tokens in (cached / uncached) | Muse tokens out | "
              "SAM at list | Muse at Standard | Total, Muse at Standard | Billed |"),
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for d in doc["days"] + [dict(doc["total"], date="**Total**")]:
        lines.append(f"| {d['date']} | {d['requests']:,} | {d['samImages']:,} | {d['samVideoFrames']:,} | "
                     f"{d['inputTokensCached']:,} / {d['inputTokensUncached']:,} | {d['outputTokens']:,} | "
                     f"${d['samListUsd']:.2f} | ${d['museListUsd']:.2f} | ${d['listUsd']:.2f} | ${d['billedUsd']:.2f} |")
    t = doc["total"]
    off_std = abs(t["listUsd"] - doc["actualUsd"])
    off_con = abs(t["listContributorUsd"] - doc["actualUsd"])
    mode = doc["museModeThatMatches"].title()
    lines += ["",
              (f"Actually spent: ${t['billedUsd']:.2f} billed + ${doc['creditsUsd']:.2f} of free credits = "
               f"**${doc['actualUsd']:.2f}**."), "",
              "| Muse tokens priced at | Muse | SAM | Total | Off from actual |", "| --- | --- | --- | --- | --- |",
              f"| Standard | ${t['museListUsd']:.2f} | ${t['samListUsd']:.2f} | ${t['listUsd']:.2f} | ${off_std:.2f} |",
              (f"| Contributor | ${t['museContributorUsd']:.2f} | ${t['samListUsd']:.2f} | "
               f"${t['listContributorUsd']:.2f} | ${off_con:.2f} |"), "",
              (f"The actual spend matches SAM at list price with Muse tokens at {mode} rates, "
               f"to within ${doc['matchOffUsd']:.2f}.")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", type=Path)
    p.add_argument("--out", type=Path, help="write usage.json and README.md here")
    p.add_argument("--credits", type=float, default=0.0, help="free credits used in the period (USD; not in the export)")
    args = p.parse_args(argv)
    doc = summarize(read(args.csv), credits=args.credits)
    source = args.csv.as_posix() + (f" --credits {args.credits:g}" if args.credits else "")
    md = markdown(doc, source)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "usage.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (args.out / "README.md").write_text(md, encoding="utf-8")
    print(md, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
