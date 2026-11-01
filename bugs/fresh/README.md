# The fresh defect set: commitment only

The blind discovery run ([docs/discovery.md](../../docs/discovery.md#the-blind-run)) is scored on a
set of fresh defects and intentional changes that live only in the private held-out repository, under
`fresh/`. They were written after discovery was frozen (`discovery/freeze.json`, commit
`0b6556c14a51`), by someone working without the discoverer's rules in front of them.

`fresh.sha256` (added in pull request #150 after the set was written: ten entries, before any blind
run) holds the digest of every file under `fresh/`, computed with
`python -m expectrail.discovery.fresh digest <set>/fresh`. The blind run refuses a set with any
other digest. Nothing else about the set (its patches, descriptions, routes or areas) enters this
repository until the event is over.

Blind run 1 (run 41248745687, October 31, planner off) verified the freeze and this digest before
replaying anything: 4 of the 8 defects flagged, neither intentional change nor the clean game
([docs/discovery.md](../../docs/discovery.md#blind-run-1-october-31)).

## Set 2

Set 1 is retired after blind runs 1 and 2: the planner needed a fix to a frozen file
(`expectrail/discovery/planner.py`) after its author had seen set 1's descriptions, so the fix goes
into a new freeze instead (freeze 2, `discovery/freeze.json`; freeze 1 is kept as
`discovery/freeze-1.json`). Set 2 is written against freeze 2, in `fresh-2/` of the private
repository, with ids `g01` to `g10`, and its digest goes in `fresh-2.sha256` here, computed with
`python -m expectrail.discovery.fresh digest <set>/fresh-2`, before its first run. The blind
workflow (input `set: fresh-2`) refuses set 1 under freeze 2, because set 1's manifest names
freeze 1.
