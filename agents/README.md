# Agents lane (Taofeek)

Orchestrator, Muse Code fixer, protected verifier, Muse Wonder triage, and morning report.

## Muse credentials (Phase 0)

1. Claim hackathon credit and create a key at [dev.meta.ai](https://dev.meta.ai) (`LLM_…`).
2. **Cursor Chat on Wonder:** Settings → Models → OpenAI API key = Meta key, override base URL `https://api.meta.ai/v1`, add custom model `muse-wonder-1.0`.
3. **Muse Code fixer:** `export META_API_KEY=LLM_…` and ensure `muse` is on `PATH` (`curl -fsSL https://dev.meta.ai/install.sh | sh`).
4. **Wonder triage API:** same key as `MODEL_API_KEY` or `META_API_KEY`.

Never commit keys. The fixer workspace must not contain signing material (see `python -m agents.trust`).

## Gate 1

```sh
# Offline/CI path (fixture candidate + synthetic observations — no Godot required)
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
```

## Gate 2

```sh
python3 -m agents.triage --out runs/triage --offline
python3 -m agents.loop --out runs/loop --runs 10 --offline-triage
python3 -m agents.trust --out runs/trust
python3 -m agents.report --verification runs/loop/run-00/verify/verification.json \
  --candidate runs/loop/run-00/fix/candidate.patch --out runs/morning
```
