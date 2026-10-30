# Reported bugs: detection

Written by `python3 -m agents.bench_collect --reported` from the run's own annotations; do not edit by hand.
Run [41116202685](https://github.com/seanudeke/Expectrail/actions/runs/41116202685), 2026-10-30, commit aa91509.

Each bug reproduces a publicly reported Godot bug: the team wrote the patches, not the bugs ([bugs/reported/README.md](../../bugs/reported/README.md) has the sources). Each one, and the clean game, was rendered on 5 routes: the smoke route and the reported routes. A bug is caught when any check fails on at least one route.

| Checks | Caught | False alarm on the clean game |
| --- | --- | --- |
| Today's verifier, SAM off (engine ground, gameplay) | **0 of 4** | none |
| Engine-record checks (agents/trace_checks.py) | **4 of 4** | none |
| Each bug's own engine-record check | **4 of 4** | |

The engine-record checks were written after these bugs were reproduced, so this shows that the harness now records what these bugs break and that a one-sentence rule over that record catches each of them without a false alarm. It does not show that the checks would have found the bugs blind, and the verifier does not run them yet.

Spend: no SAM; 14 job minutes.

| Bug | Own check | Today, SAM off | Engine-record | What did not pass |
| --- | --- | --- | --- | --- |
| clean (control) |  | no | no | nothing |
| air-jump | jump-height | no | yes | jump-height on climb-gap: the robot rose 485 px above the floor it left (max 260), highest at tick 285 |
| body-flip | facing-follows-motion | no | yes | shots-follow-facing on turn-and-shoot: 1 of 2 bullets went the other way from where the robot faced (first fired at tick 191)<br>facing-follows-motion on turn-and-shoot: the robot faced away from where it walked on 90 of 199 moving ticks (first at tick 93) |
| enemy-ledge | enemies-stay-up | no | yes | enemies-stay-up on wait-for-patrol: enemy 0 fell 256 px below where it settled (max 64) |
| gun-cooldown | fire-rate | no | yes | fire-rate on tap-shoot: two shots 0.10 s apart (min 0.25 s); 14 shots |

For the clean game the columns are false alarms, not catches.

Rerun: Actions, **Reported bench** (or any pull request that touches it), then `python3 -m agents.bench_collect --reported --run <id>`.
