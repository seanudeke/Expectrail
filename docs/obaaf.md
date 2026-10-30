# OBAAF in Expectrail (Expectrail)

OBAAF (the Open Build and Agent Assurance Framework, https://github.com/Obaaf/OBAAF) is a
dependency here, pinned to commit `ef34304214923953cf7d67343b912385d4ce5906`. It answers a question
Expectrail does not: may this change cause an effect (a pull request, a release), given where it
came from and who approved it. Expectrail answers whether the change does what the player needs.
Both are needed; neither replaces the other. OBAAF does not make a fix more likely to be right, and
a passing Expectrail verdict grants no write access by itself.

**Status: Phase A, reporting only (Oct 30).** Nothing is enforced and no protected effect is
enabled. What runs, in the `obaaf-audit` CI job on every push and pull request:

| What | How | Gated? |
| --- | --- | --- |
| Lane inventory | `.github/obaaf.yml` declares the 8 jobs that hand a Meta model untrusted input and act on its output as agent lanes (OBAAF does not recognise `python -m agents.*`). `agents/assurance/audit.py` fails CI if one is not classified as an agent, or if any job holds a model key without being a declared agent or a listed perception-only job (SAM, Glimmer). | Yes: a new model job needs a declaration and review |
| Pipeline findings | `obaaf check . --format json --fail-on never`; one notice per rule | No, reported |
| Proposals | `agents/assurance/proposal.py` turns a candidate fix into an OBAAF proposal bundle and checks it with `obaaf proposal check --repo` plus Expectrail's own allowlist | Tests only, see below |

## Findings (Oct 30, main at e19b378 plus this change)

| Rule | Before | Now | What it means |
| --- | --- | --- | --- |
| OBAAF-GHA-001: secret in a pull-request job | 1 low | **0** | `agents-harness-verify` checked out the private held-out set on every same-repository pull request, then ran that branch's code: anyone who could push a branch could print the private set. That job now never sees it; `agents-harness-private` checks the private routes on pushes to main, the schedule and manual runs only. |
| OBAAF-REPO-001: no CODEOWNERS | 1 medium | **0** | `.github/CODEOWNERS` names an owner for workflows and everything that decides a verdict. It binds merges only once branch protection requires code-owner review (a repository setting). |
| OBAAF-GHA-005: secret in an agent job | 8 high | 8 high | The Muse key reaches every agent job, because Muse Code calls Meta's API directly. Clearing it needs a model gateway that holds the key outside the job (Phase C). Not suppressed. |
| OBAAF-GHA-020: agent job without egress restriction | 8 low | 8 low | No agent job has an enforced network policy. `OBAAF_EGRESS` would only record intent, so it is not set. |

## Proposals

A candidate fix is a game-relative diff made against the seeded game (`player/player.tscn`). OBAAF
checks repository-relative Git diffs, as a pull request would see them. `normalize()` clones this
repository's committed HEAD into a disposable repository, commits the seeded defect there (benchmark
lineage: never on main), applies the candidate to a second clone, and asks Git for the diff. No game
code runs. The bundle holds `patch.diff` and untrusted `meta.json` only; the verification report
and frames stay outside it, which OBAAF requires.

Two rule sets, both required:

- **OBAAF** (`obaaf proposal check --repo`): no workflow, instruction, CODEOWNERS or OBAAF file; no
  symlink, submodule or rename; at most 100 paths and 1,000,000 bytes; the patch is applied again to
  a temporary index of the base. Expectrail adds its trust boundary to the protected paths:
  `agents/**`, `harness/**`, `expectrail/**`, `contracts/**`, `specs/**`, `tests/**`, `bench/**`,
  `bugs/**`, `requirements*.txt`.
- **Expectrail**: every changed path is under `game/platformer/` and matches the request's editable
  globs.

What the tests show (`tests/test_assurance.py`, run with OBAAF installed in `obaaf-audit`): the real
fall-through fix passes both; the same fix plus a workflow edit, a verifier edit, a spec edit or a
seeded-bug edit is refused; a symlink is refused; the raw game-relative fixture and a bundle with
`verification.json` in it are refused; a bundle changed after normalization fails its digest; a fix
to a game file outside the editable globs passes OBAAF and is refused by Expectrail. The fakes that
hide or sink the robot pass the proposal check, as they should: they are wrong in meaning, not in
where they write, and Expectrail's verifier is what rejects them.

    python3 -m agents.assurance.proposal --seed bugs/physics-fall-through/v1.patch \
        --candidate agents/fixtures/fix-collision-mask.patch --out runs/proposal

## Not done, in order

1. **The replay runs the candidate's code with the verifier's authority.** `harness/run.py` starts
   the patched game with the verifier's environment, network access and file system, which hold
   the SAM key, the private routes and the SAM cache. Scrubbing the environment is the first step;
   a network-less, file-scoped worker for the replay is the real fix.
2. **Evidence binding (Phase B):** a closed candidate manifest, an evidence manifest, and a signed
   statement naming the exact proposal and verification report, verified before any effect.
3. **Protected pull requests (Phase C):** a model gateway so agent jobs hold no provider key,
   enforced egress, separate jobs for capture, attestation, approval and effect, and an independent
   approval in a protected environment. Until then no agent opens a pull request.
