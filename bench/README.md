# Bench

Every number the README or the video quotes comes from a file here and reruns with one command.

| What | Files | Rerun |
| --- | --- | --- |
| Detection: development variants | `detection/dev.json`, table in `detection/README.md` | `bench/rerun-detection.sh dev` |
| Detection: held-out variants (ids and counts only) | `detection/held-out.json` | `bench/rerun-detection.sh held-out` |
| Fix matrix: development variants, screenshots vs Nightshift | `fix-matrix/dev.json`, table in `fix-matrix/README.md` | Actions, **Fix matrix** (live), then `python3 -m agents.bench_collect --matrix --run <id> --set dev` |
| Live Muse Code film, clean prompt | `live-muse-clean-v1/` | see its README |
| First live Muse Spark spec draft | `spec-writer-live/` | see its README |
| Offline demo-path stub | `overnight-offline.json` | below |
| SAM video against images, public runs (measured, not used) | `sam-video/run-*.json`, table in `sam-video/README.md` | Actions, **SAM probe**, mode `video-compare` |
| Judge benchmark: who accepts a fix that only looks right (Nightshift with and without SAM, Muse from screenshots) | `judge/judge.json`, table in `judge/README.md` | Actions, **Fix matrix** with bench `judge` (live), then `python3 -m agents.bench_collect --judge --run <id> [--run <id>]` |

The detection files are written by `python3 -m agents.bench_collect --run <id> --set dev|held-out`
from the run's own annotations, so they carry the run, commit and date they came from.

## Cost

Each result counts the images it sent to sam-3.1 (`agents.sam_observations.sam_usage`): detection per
variant, the fix matrix per case and condition, the judge benchmark per case. The collectors add them up
per run and price them at $2.50 per 1,000 images, the image segmentation price on the
[Meta Model API pricing page](https://dev.meta.ai/docs/pricing-rate-limits) (read Oct 29, 2026). Runs
from before the count existed say "not counted"; nothing is estimated.

Muse Code does not report its token use, so its spend is counted as calls (fix attempts, judge calls) and
priced from the usage export on dev.meta.ai. The Actions jobs themselves are free on a public
repository; job minutes are listed for scale.

The team's whole bill is in `cost/`: the dev.meta.ai usage export (team id left out of the file name),
priced by `python3 -m agents.usage_report bench/cost/meta-usage-2026-10-24-to-30.csv --credits 150 --out bench/cost`
(the $150 of free credits used before billing started are not in the export).

## Offline demo-path stub (agents lane)

`overnight-offline.json` is regenerated from an overnight `summary.json` by:

```sh
python3 -m agents.bench --summary runs/loop/summary.json --out bench/overnight-offline.json
```

**Provenance is always `agents-offline-stub`.** These numbers are for the filmable
agents demo path (wall-clock + offline cost honesty). They are **not** the Gate-2
evaluation matrix in `docs/evaluation.md` and do not claim Meta API spend.
