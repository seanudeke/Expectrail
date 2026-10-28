# Bench stubs (agents lane)

`overnight-offline.json` is regenerated from an overnight `summary.json` by:

```sh
python3 -m agents.bench --summary runs/loop/summary.json --out bench/overnight-offline.json
```

**Provenance is always `agents-offline-stub`.** These numbers are for the filmable
agents demo path (wall-clock + offline cost honesty). They are **not** the Gate-2
evaluation matrix in `docs/evaluation.md` and do not claim Meta API spend.
