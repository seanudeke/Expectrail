# Bench stubs (agents lane)

Everything in this folder was recorded before the project was renamed from Nightshift to Pixel
Proof on October 28, 2026, and is kept exactly as recorded: it still says `nightshift` in format
IDs, paths and logs. The code reads the old format IDs the same as the new ones
([docs/contracts.md](../docs/contracts.md#names-from-before-the-rename)). Regenerate a file to
get the new names.

`overnight-offline.json` is regenerated from an overnight `summary.json` by:

```sh
python3 -m agents.bench --summary runs/loop/summary.json --out bench/overnight-offline.json
```

**Provenance is always `agents-offline-stub`.** These numbers are for the filmable
agents demo path (wall-clock + offline cost honesty). They are **not** the Gate-2
evaluation matrix in `docs/evaluation.md` and do not claim Meta API spend.
