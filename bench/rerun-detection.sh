#!/usr/bin/env bash
# Rerun the detection benchmark for one set and record it in bench/detection/ (one command).
#   bench/rerun-detection.sh dev        # the eight public development variants
#   bench/rerun-detection.sh held-out   # the private held-out variants (ids and counts only)
#   bench/rerun-detection.sh dev main glimmer-engine   # judged by Muse Glimmer checked against the engine
# Needs gh (signed in, with Actions access) and the repo's MODEL_API_KEY and HELDOUT_TOKEN secrets.
# Spends Meta credit: SAM 3.1 looks at up to 240 frames per route and variant.
set -euo pipefail
which="${1:?usage: bench/rerun-detection.sh dev|held-out [ref] [sam|glimmer-engine]}"
ref="${2:-main}"
judge="${3:-sam}"
case "$judge" in sam|glimmer-engine) ;; *) echo "judge must be sam or glimmer-engine" >&2; exit 2 ;; esac
repo="seanudeke/Expectrail"
case "$which" in
  dev) mode=dev-bench ;;
  held-out) mode=heldout-bench ;;
  *) echo "usage: bench/rerun-detection.sh dev|held-out [ref]" >&2; exit 2 ;;
esac
runs="repos/$repo/actions/workflows/sam-probe.yml/runs?event=workflow_dispatch&per_page=1"
before=$(gh api "$runs" --jq '.workflow_runs[0].id // 0')
gh api -X POST "repos/$repo/actions/workflows/sam-probe.yml/dispatches" -f ref="$ref" -f "inputs[mode]=$mode" -f "inputs[judge]=$judge" >/dev/null
run="$before"
until [ "$run" != "$before" ]; do sleep 5; run=$(gh api "$runs" --jq '.workflow_runs[0].id // 0'); done
echo "run $run: https://github.com/$repo/actions/runs/$run"
until [ "$(gh api "repos/$repo/actions/runs/$run" --jq .status)" = "completed" ]; do sleep 60; done
python3 -m agents.bench_collect --run "$run" --set "$which"
