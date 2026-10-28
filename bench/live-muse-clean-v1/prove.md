# Prove live — Muse accept + trust canary denial

## 1. Live Muse Code → verifier accept
- Result: PASS — muse candidate accepted under clean-v1 (ceda817fc43c…)
- Gate out: `runs/prove/muse-gate`
- Muse log: `runs/prove/muse-gate/fix/muse.log`
- Morning: `runs/prove/muse-gate/morning/morning-report.md`

## 2. Trust canary denial (scripted fixer attempts)
- Result: PASS — fixer cannot read signing key or suite controls (deny-by-absence); canary probe filmed mount-local denials; poisoned asset is present; verifier host holds the demo key
- Evidence: `runs/prove/trust/trust-evidence.md`
- Canary attempts: `runs/prove/trust/canary-attempts.json`

## Overall: PASS

