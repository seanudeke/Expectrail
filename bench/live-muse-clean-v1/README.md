# Live Muse Code film (clean-v1)

Raw evidence from `python3 -m agents.prove_live --out runs/prove` on physics-fall-through v1.

- Prompt policy: `clean-v1` (failing check + evidence + editable globs; no solution hints)
- `fix/muse.log` — raw Muse Code output
- `fix/muse-prompt.txt` — exact prompt sent
- `fix/candidate.*` — Muse patch + provenance (`promptPolicy`, `promptSha256`)
- `trust/` — deny-by-absence canary film
- `.env` is **not** included (gitignored local secret)

Regenerate locally with `META_API_KEY` in `.env`; do not commit `.env`.
