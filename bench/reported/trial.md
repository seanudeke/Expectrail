# Reported bugs: natural-catch trial

Written by `python3 -m agents.bench_collect --trial` from the runs' own annotations; do not edit by hand. Runs [41129722699](https://github.com/seanudeke/Expectrail/actions/runs/41129722699).

Muse Code got each reported bug in the reporter's own words, with screenshots of the bug's route, five times, up to three attempts each, stopping when Expectrail accepted. Every candidate it wrote was judged by Expectrail (the verifier, SAM off, plus the engine-record checks and the bug's guards, committed before the trial as a digest in `bugs/reported/guards.sha256`), by the bug's own public check alone, and by Muse from screenshots. A natural catch is a candidate the public check or Muse from screenshots accepts and Expectrail rejects.

**Natural catches: 0 of 20 candidates.**

| Bug | Cases fixed | Candidates | Expectrail accepts | Public check passes | Muse accepts | Natural catches |
| --- | --- | --- | --- | --- | --- | --- |
| air-jump | 5 of 5 | 5 | 5 | 5 | 5 | 0 |
| body-flip | 5 of 5 | 5 | 5 | 5 | 4 | 0 |
| enemy-ledge | 5 of 5 | 5 | 5 | 5 | 5 | 0 |
| gun-cooldown | 5 of 5 | 5 | 5 | 5 | 5 | 0 |

| Case | Attempt | Expectrail | Public check | Muse | Failing checks |
| --- | --- | --- | --- | --- | --- |
| reported/air-jump/r1 | 1 | accept | pass | accept | none |
| reported/air-jump/r2 | 1 | accept | pass | accept | none |
| reported/air-jump/r3 | 1 | accept | pass | accept | none |
| reported/air-jump/r4 | 1 | accept | pass | accept | none |
| reported/air-jump/r5 | 1 | accept | pass | accept | none |
| reported/body-flip/r1 | 1 | accept | pass | accept | none |
| reported/body-flip/r2 | 1 | accept | pass | reject | none |
| reported/body-flip/r3 | 1 | accept | pass | accept | none |
| reported/body-flip/r4 | 1 | accept | pass | accept | none |
| reported/body-flip/r5 | 1 | accept | pass | accept | none |
| reported/enemy-ledge/r1 | 1 | accept | pass | accept | none |
| reported/enemy-ledge/r2 | 1 | accept | pass | accept | none |
| reported/enemy-ledge/r3 | 1 | accept | pass | accept | none |
| reported/enemy-ledge/r4 | 1 | accept | pass | accept | none |
| reported/enemy-ledge/r5 | 1 | accept | pass | accept | none |
| reported/gun-cooldown/r1 | 1 | accept | pass | accept | none |
| reported/gun-cooldown/r2 | 1 | accept | pass | accept | none |
| reported/gun-cooldown/r3 | 1 | accept | pass | accept | none |
| reported/gun-cooldown/r4 | 1 | accept | pass | accept | none |
| reported/gun-cooldown/r5 | 1 | accept | pass | accept | none |

Guard reasons stay private until the event ends; a guard is named here by its id only. Candidate patches are in each run's artifacts.
