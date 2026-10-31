# Bench

Every number the README or the video quotes comes from a file here and reruns with one command.

| What | Files | Rerun |
| --- | --- | --- |
| Detection: development variants | `detection/dev.json`, table in `detection/README.md` | `bench/rerun-detection.sh dev` |
| Detection: held-out variants (ids and counts only) | `detection/held-out.json` | `bench/rerun-detection.sh held-out` |
| Detection: reproductions of publicly reported Godot bugs, today's checks against the engine-record checks | `reported/reported.json`, table in `reported/README.md` | Actions, **Reported bench** (it also runs on a pull request that touches it), then `python3 -m agents.bench_collect --reported --run <id>` |
| Natural-catch trial on the reported bugs: Muse Code given the reporter's words, every candidate judged by Expectrail, the public check and Muse from screenshots | `reported/trial.json`, table in `reported/trial.md` | Actions, **Fix matrix** (live, set reported), then `python3 -m agents.bench_collect --trial --run <id>` |
| Detection judged by Muse Glimmer checked against the engine (no SAM) | `detection/<set>-glimmer-engine.json` | `bench/rerun-detection.sh held-out main glimmer-engine` (or `dev`) |
| Fix matrix: development variants, screenshots vs Expectrail | `fix-matrix/dev.json`, table in `fix-matrix/README.md` | Actions, **Fix matrix** (live), then `python3 -m agents.bench_collect --matrix --run <id> --set dev` |
| A live review, republished as recorded evidence: Muse Code's fix in demo run 1 of run 41105875960, the same checks before and after, with its frames | `docs/review/live-demo-run-1/` (`change-evidence.json`, `index.html`, `assets/`) | Actions, **Fix matrix** with bench `demo` (review on), then `python3 -m agents.review_html <change-evidence.json> --recorded "<run>" --name index.html` |
| A live review on the loop as it ships (Muse Code fixing from a plain report), republished as recorded evidence: demo run 1 of run 41223748922, the same checks before and after, with its frames | `docs/review/report-first-run-1/` (`change-evidence.json`, `index.html`, `assets/`) | Actions, **Fix matrix** with bench `demo` (review on), then `python3 -m agents.review_html <change-evidence.json> --recorded "<run>" --name index.html` |
| A rejected fix's review, republished as recorded evidence: the fixture that draws the robot inside the ground, SAM probe run 41123758768, the same checks before and after, with its frames | `docs/review/sinking-fix/` (`change-evidence.json`, `index.html`, `assets/`) | Actions, **SAM probe** mode verify with candidate `agents/fixtures/fix-but-sink-player.patch` (keeps the `sam-review` artifact), then `python3 -m agents.review_html <change-evidence.json> --recorded "<run>" --name index.html` |
| Fix matrix: development variants under all three briefings (escalate, screenshots, expectrail), October 31 | `fix-matrix/report-first/dev.json`, table in `fix-matrix/report-first/README.md` | Actions, **Fix matrix** (live), then `python3 -m agents.bench_collect --matrix --run <id> --set dev --out bench/fix-matrix/report-first` |
| Fix matrix: held-out variants (ids and counts only). The first run, on a fixed commit (branch `heldout/run-1`), is the held-out result; later runs are repeats and are recorded beside it, never in its place | `fix-matrix/held-out/held-out.json`, table in `fix-matrix/held-out/README.md` | Actions, **Fix matrix** (live, set held-out) on a fixed commit, then `python3 -m agents.bench_collect --matrix --run <id> --set held-out --out bench/fix-matrix/held-out` |
| Fix matrix: held-out run 2, a repeat of run 1 on a fixed commit (branch `heldout/run-2`, `e216fb7`, main after the timeout-evidence fix #108), recorded beside run 1, never merged with it. The same counts as run 1 (Expectrail 8 of 8, screenshots 7 of 8), the same single case not fixed with screenshots, there by three Muse Code timeouts; every Muse run went through the key gateway (19 of 19) | `fix-matrix/held-out-run-2/held-out.json`, table in `fix-matrix/held-out-run-2/README.md` | Actions, **Fix matrix** (live, set held-out) on `heldout/run-2`, then `python3 -m agents.bench_collect --matrix --run 41199992529 --set held-out --out bench/fix-matrix/held-out-run-2` |
| Live Muse Code film, clean prompt | `live-muse-clean-v1/` | see its README |
| First live Muse Spark spec draft | `spec-writer-live/` | see its README |
| Muse Spark Open, live: the approved checks drafted again, the ground draft on the seeded bugs, the scripted playtest sorted | `spark-open/<run>/results.json` and table, index in `spark-open/README.md` | Actions, **Spark Open**, then `python3 -m agents.spark_open collect --run <id>` |
| Offline demo-path stub | `overnight-offline.json` | below |
| Demo path, live: the overnight loop end to end, N independent runs | `demo-loop/demo.json`, table in `demo-loop/README.md` | Actions, **Fix matrix** with bench `demo`, then `python3 -m agents.bench_collect --demo --run <id>` |
| Demo path, live, after the report-first change (docs/report-first.md) | `demo-loop/report-first/demo.json`, table in `demo-loop/report-first/README.md` | the same, with `--out bench/demo-loop/report-first` |
| SAM video against images, public runs (measured, not used) | `sam-video/run-*.json`, table in `sam-video/README.md` | Actions, **SAM probe**, mode `video-compare` |
| Judge benchmark: who accepts a fix that only looks right (Expectrail with and without SAM, Muse from screenshots; with `judge_glimmer`, also Expectrail with Glimmer checked against the engine) | `judge/judge.json`, table in `judge/README.md`; the run with Glimmer in `judge/glimmer/` | Actions, **Fix matrix** with bench `judge` (live), then `python3 -m agents.bench_collect --judge --run <id> [--run <id>] [--out <folder>]` |

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
