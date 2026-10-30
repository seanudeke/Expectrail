# Live Muse Code film (clean-v1)

Raw evidence from `python3 -m agents.prove_live --out runs/prove` on physics-fall-through v1.

- Prompt policy: `clean-v1` (failing check + evidence + editable globs; no solution hints)
- `fix/muse.log` — raw Muse Code output
- `fix/muse-prompt.txt` — exact prompt sent
- `fix/candidate.*` — Muse patch + provenance (`promptPolicy`, `promptSha256`)
- `trust/` — deny-by-absence canary film
- `.env` is **not** included (gitignored local secret)

Regenerate locally with `META_API_KEY` in `.env`; do not commit `.env`.

## Scrubbed on Oct 30

The contributor's local checkout path (`/Users/<name>/Documents/GitHub/Nightshift`) was replaced
with `<checkout>` in five files: `fix/muse.log`, `morning/morning-report.md`,
`morning/morning-summary.json`, `trust/canary-attempts.json` and `verify/verification.json`.
Nothing else changed. Because `verify/verification.json` changed, its canonical digest no longer
matches the `verificationSha256` that `morning/release-candidate.json` signed, so the signature
does not verify against the scrubbed copy. The original files, which do verify, are in this
repository's history at commit `e216fb7` (for example
`git show e216fb7:bench/live-muse-clean-v1/verify/verification.json`).
