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

The detection files are written by `python3 -m agents.bench_collect --run <id> --set dev|held-out`
from the run's own annotations, so they carry the run, commit and date they came from.

## Offline demo-path stub (agents lane)

`overnight-offline.json` is regenerated from an overnight `summary.json` by:

```sh
python3 -m agents.bench --summary runs/loop/summary.json --out bench/overnight-offline.json
```

**Provenance is always `agents-offline-stub`.** These numbers are for the filmable
agents demo path (wall-clock + offline cost honesty). They are **not** the Gate-2
evaluation matrix in `docs/evaluation.md` and do not claim Meta API spend.
