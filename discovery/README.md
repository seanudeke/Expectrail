# Discovery inputs

What advisory discovery ([docs/discovery.md](../docs/discovery.md)) reads, as opposed to the checks
people write ([`specs/`](../specs)).

- [`platformer.profile.json`](platformer.profile.json): the mechanics profile. Four claims read from
  the game's code and settings (the double jump, the gun's cooldown, the sprite's facing, the
  enemies' patrol), each with its parameters, where in the code it comes from, and its known
  exceptions, plus the twelve templates that turn the claims into trace contracts. Every claim is
  `inferred_code` and no template is approved (`approvalRef` is null), so every contract built from
  them is advisory.
- [`freeze.json`](freeze.json): the freeze for the blind run. The sha256 of every file that decides a
  finding and of the clean game, and the exact blind command. Check a checkout with
  `python -m expectrail.discovery.freeze verify`. Until the blind run is recorded, a test fails if
  any frozen file changes; change them only after that, deliberately, with a new freeze.
