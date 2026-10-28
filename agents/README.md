# Agents lane (Taofeek)

Orchestrator, Muse Code fixer, protected verifier, Muse Wonder triage, and morning report.

## Muse credentials (Phase 0)

1. Claim hackathon credit and create a key at [dev.meta.ai](https://dev.meta.ai) (`LLM_…`).
2. **Cursor Chat on Wonder:** Settings → Models → OpenAI API key = Meta key, override base URL `https://api.meta.ai/v1`, add custom model `muse-wonder-1.0`.
3. **Muse Code fixer:** `export META_API_KEY=LLM_…` and ensure `muse` is on `PATH` (`curl -fsSL https://dev.meta.ai/install.sh | sh`).
4. **Wonder triage API:** same key as `MODEL_API_KEY` or `META_API_KEY`.

Never commit keys. The fixer workspace must not contain signing material (see `python -m agents.trust`).

## Suite kinds

After editable/base-tree gates, the verifier emits four check kinds: `regression`, `gameplay`,
`clean`, `held-out`. `decide()` accepts only when all four are present and pass (incomplete sets
are `needs-review`). **Gameplay** is judged by `agents.gameplay` from the candidate harness
`trace.json` (or mapped offline `agents/fixtures/trace-*.json`) — min Δx, end-on-floor, no
sustained below-ground — not a SAM `reaches` / invented goal. The verifier writes schema-valid
`verdict-gameplay.json` (`nightshift.gameplay-verdict/v0`); morning films a `## Gameplay`
section. The check id `player-motion-on-smoke` is an opaque motion label (not a SAM
`reaches` goal). The retired `player-reaches-end-of-route.json` basename stays on the
fixer deny-list forever; `player-motion-on-smoke.json` is deny-listed too so neither can
mount into fixer-work. Overnight rollup films latest gameplay-reject reason/source/Δx.
Clean uses a no-patch harness replay when available; if Godot
aborts on that second import (seen on CI), it falls back to `agents/fixtures/obs-clean.json`
and still decides (`suite.clean.source=fixture-fallback`). Held-out replays the
seed + candidate on the private held-out routes when `NIGHTSHIFT_HELDOUT_DIR` points at a checkout
of `seanudeke/Nightshift-heldout` (suite source `harness`; visual spec and gameplay must both pass;
an unusable set is `needs-review`, never a pass). Offline and fixture runs keep
`agents/fixtures/obs-held-out.json` as a labeled `interim-fixture` control. Keep the held-out
checkout off any machine where Muse Code runs. Optional `suite` on `verification.json`
records candidate/clean/held-out provenance.

Trust (`agents.trust`) proves deny-by-absence under fixer-work for the signing key **and** suite
control basenames (`obs-clean.json`, `obs-held-out.json`, `evaluator.py`, suite specs,
`verdict-gameplay.json`) — mount absence only, not whole-repo read isolation. Overnight rollup
films `triage=` / `fixer=` sources and Trust PASS/FAIL when trust ran (`--no-trust` omits Trust).

## Gate 1

```sh
# Offline/CI path (fixture candidate + synthetic observations — no Godot required)
# Also writes runs/gate1/morning/ (report + release-candidate.json)
python3 -m agents.gate1 --out runs/gate1 --skip-harness \
  --observations agents/fixtures/obs-fixed.json

# Freeze-player must reject
python3 -m agents.fixer --request runs/gate1/repair-request.json --out runs/freeze \
  --candidate-patch agents/fixtures/freeze-player.patch
python3 -m agents.verifier --request runs/gate1/repair-request.json \
  --candidate runs/freeze/candidate.patch --out runs/freeze-verify \
  --skip-harness --observations agents/fixtures/obs-freeze.json
# expect decision: reject

# Live Muse Code (requires META_API_KEY + muse + Linux Godot/Xvfb for harness verify)
python3 -m agents.gate1 --out runs/gate1-muse --use-muse

# Harness-backed verify (Linux + xvfb + Godot; CI job agents-harness-verify)
python3 -m agents.gate1 --out runs/harness-accept \
  --candidate-patch agents/fixtures/fix-collision-mask.patch
```

## Gate 2

Modes are sealed: `--mode offline` cannot be combined with `--use-muse` / `--online-triage`;
`--mode live` cannot be combined with `--offline-triage`. Live Wonder that soft-falls to
fixtures rejects the run. Signing key is written under `verifier-host/` only after the fixer
returns. Default verification is fixture observations (`verificationProvenance`); pass
`--no-skip-harness` for Godot harness verify.

```sh
# One-command overnight path (auto: Wonder/Muse when keys exist, else fixtures)
python3 -m agents.loop --out runs/loop --mode auto --runs 1

# CI / deterministic — see agents/demo-path.md for the filmable hand-over checklist
python3 -m agents.loop --out runs/loop --mode offline --runs 10
# → summary.json is nightshift.overnight-summary/v0 (wall-clock + unmetered-offline cost)
python3 -m agents.bench --summary runs/loop/summary.json

# Force live Wonder + Muse Code (fails closed without keys + muse)
export META_API_KEY=LLM_…
export MODEL_API_KEY="$META_API_KEY"
python3 -m agents.loop --out runs/loop-live --mode live --runs 1

# Trust beat evidence for the demo (standalone sandbox, or bound by the loop)
python3 -m agents.trust --out runs/trust
# → runs/trust/trust-evidence.md + canary-attempts.json (scripted denial film)
```

## Prove live (playbook: Muse accept + trust canary)

One command for the two camera beats. Trust canary is always free; Muse spend is opt-in.

```sh
# Item 2 only — scripted fixer attempts denied by mount absence (CI runs this)
python3 -m agents.prove_live --out runs/prove --trust-only
# → runs/prove/prove.md + trust/canary-attempts.json

# Items 1 + 2 — live Muse Code fix → verifier accept, plus trust film
export META_API_KEY=LLM_…
python3 -m agents.prove_live --out runs/prove
# → runs/prove/muse-gate/ (candidate from muse, morning report) + trust/

# Optional extra spend: also ask Muse to follow the poisoned asset
python3 -m agents.prove_live --out runs/prove --muse-trust-probe

# CI: Actions → CI → Run workflow (needs repo secret META_API_KEY)
# Job: agents-live-muse
```

Without `META_API_KEY`, full mode exits 2 (skipped) so automation can fail closed without inventing spend.
