# Demo path (offline, filmable)

One-command Gate-2 hand-over without Meta keys:

```sh
python3 -m agents.loop --out runs/demo-path --mode offline --runs 10
```

Open:

- `runs/demo-path/morning-report.md` — overnight rollup (accepts, wall-clock, cost stub, trust)
- `runs/demo-path/summary.json` — schema-valid `nightshift.overnight-summary/v0`
- `runs/demo-path/frames/` — latest accept before/after
- `runs/demo-path/run-00/morning/release-candidate.json` — signed RC pointer
- `runs/demo-path/run-00/trust/trust-evidence.md` — deny-by-absence evidence

Freeze reject film (optional):

```sh
python3 -m agents.loop --out runs/demo-freeze --mode offline --runs 1 \
  --candidate-patch agents/fixtures/freeze-player.patch \
  --observations agents/fixtures/obs-freeze.json
```

Regenerate the agents offline bench stub:

```sh
python3 -m agents.bench --summary runs/demo-path/summary.json
```

Harness morning film (Linux CI `agents-harness-verify`): after Godot verify, `agents.report`
writes `runs/harness-accept/morning/` and `runs/harness-negatives/freeze-morning/` with
schema-valid RCs and suite/gameplay sections.

`--no-trust` is for local debugging only — the demo path keeps trust on so the rollup films
`## Trust` PASS evidence.
