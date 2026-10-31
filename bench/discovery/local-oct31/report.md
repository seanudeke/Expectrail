# Advisory discovery

## local-reported

Evidence: **FRESH LIVE**, condition **development-reproduction**, complete. 150 replays in 548 s.

Withheld from every stage: bug reports; patches and diffs; the reported bugs' routes; the hand-written trace rules and guards of the reported-bug bench.

| Snapshot | Role | Replays | pass | fail | not exercised | insufficient | error |
|---|---|---:|---:|---:|---:|---:|---:|
| clean | reference | 22 | 91 | 0 | 64 | 0 | 0 |
| air-jump | base | 22 | 87 | 4 | 64 | 0 | 0 |
| gun-cooldown | base | 22 | 87 | 4 | 64 | 0 | 0 |
| body-flip | base | 22 | 84 | 7 | 64 | 0 | 0 |
| enemy-ledge | base | 22 | 90 | 1 | 64 | 0 | 0 |

### Findings

| Snapshot | Contract | Probes | Reproduced | Observation |
|---|---|---|---|---|
| air-jump | `jump-no-extra-air-jumps-jump-w0-x8` (inferred_code) | jump-w0-x2, jump-w0-x8 | 3/3 (reproduced) | air_jumps is 7 on air-jump-jump-w0-x8 and 1 on air-jump-jump-w0-x2; expected right lte left within 0 |
| air-jump | `jump-no-extra-air-jumps-jump-w40-x8` (inferred_code) | jump-w40-x2, jump-w40-x8 | 3/3 (reproduced) | air_jumps is 7 on air-jump-jump-w40-x8 and 1 on air-jump-jump-w40-x2; expected right lte left within 0 |
| air-jump | `jump-no-extra-air-jumps-jump-w80-x8` (inferred_code) | jump-w80-x2, jump-w80-x8 | 3/3 (reproduced) | air_jumps is 7 on air-jump-jump-w80-x8 and 1 on air-jump-jump-w80-x2; expected right lte left within 0 |
| air-jump | `jump-no-extra-air-jumps-jump-w120-x8` (inferred_code) | jump-w120-x2, jump-w120-x8 | 3/3 (reproduced) | air_jumps is 7 on air-jump-jump-w120-x8 and 1 on air-jump-jump-w120-x2; expected right lte left within 0 |
| gun-cooldown | `weapon-min-interval` (inferred_code) | shoot-right-every12 | 3/3 (reproduced) | two projectile_spawn events 12 ticks apart (min 30) |
| gun-cooldown | `weapon-faster-taps-shoot-right-every12` (inferred_code) | shoot-right-every48, shoot-right-every12 | 3/3 (reproduced) | projectile_count is 12 on gun-cooldown-shoot-right-every12 and 3 on gun-cooldown-shoot-right-every48; expected right lte left within 1 |
| gun-cooldown | `weapon-faster-taps-shoot-left-every12` (inferred_code) | shoot-left-every48, shoot-left-every12 | 3/3 (reproduced) | projectile_count is 12 on gun-cooldown-shoot-left-every12 and 3 on gun-cooldown-shoot-left-every48; expected right lte left within 1 |
| body-flip | `facing-follows-motion` (inferred_code) | hold-left | 3/3 (reproduced) | moving left while facing right |
| body-flip | `facing-bullets-follow-facing` (inferred_code) | shoot-left-every48 | 3/3 (reproduced) | bullet 3 travelled +42 px while the shooter faced left |
| body-flip | `facing-mirror-hold-left` (inferred_code) | hold-right, hold-left | 3/3 (reproduced) | facing_flips is 240 on body-flip-hold-left and 0 on body-flip-hold-right; expected right lte left within 2 |
| body-flip | `facing-mirror-move-fire-left` (inferred_code) | move-fire-right, move-fire-left | 3/3 (reproduced) | facing_flips is 120 on body-flip-move-fire-left and 0 on body-flip-move-fire-right; expected right lte left within 2 |
| enemy-ledge | `enemy-max-drop` (inferred_code) | wait-long | 3/3 (reproduced) | enemy 0 dropped 256 px below where it settled (max 64) |

### Rejected on the healthy reference

None.

### Stages

- library probes: complete. 22 probes on 5 snapshots
- planner: skipped. no planner configured
- reference check: complete. 0 contracts fail on the healthy reference and are rejected
- reproduction: complete. 12 findings, each replayed up to 3 times

A finding is advisory: a contract inferred from the game's code or proposed by a model failed on this build, three times out of three, and passed on the healthy reference. It does not reject anything. No finding means none within these probes and contracts, nothing more.
