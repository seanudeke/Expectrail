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

The contributor's local checkout path (`/Users/<name>/Documents/GitHub/<repository>`) was replaced
with `<checkout>` in five files: `fix/muse.log`, `morning/morning-report.md`,
`morning/morning-summary.json`, `trust/canary-attempts.json` and `verify/verification.json`.
Nothing else changed. Because `verify/verification.json` changed, its canonical digest no longer
matches the `verificationSha256` that `morning/release-candidate.json` signed, so the signature
does not verify against the scrubbed copy. The original files, which do verify, are in this
repository's history at commit `e216fb7` (for example
`git show e216fb7:bench/live-muse-clean-v1/verify/verification.json`).

## Names updated on Nov 1

The project's earlier name was replaced with Expectrail in seven files: in format IDs, the
evaluator's name, the signing key's file name and the morning report's title
(`morning/morning-report.md`, `morning/morning-summary.json`, `morning/release-candidate.json`,
`repair-request.json`, `trust/canary-attempts.json`, `trust/trust-evidence.md`,
`verify/verification.json`). Nothing else changed. The run itself used the earlier names, so the
digests in `morning/release-candidate.json` refer to the files as they were: before this change at
commit `85a5e253f635`, and before the Oct 30 scrub at `e216fb7`.
