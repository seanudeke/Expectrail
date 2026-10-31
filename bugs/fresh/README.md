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
