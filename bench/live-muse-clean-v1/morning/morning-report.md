# Nightshift morning report

**Decision:** `accept`
**Request:** `rr-gate1`
**Request sha256:** `a8af3bb8fd86e4d3fa7ffbd927d1fd883ab08fa675398f57ff7d72d21d3515db`
**Attempt:** 1
**Candidate patch sha256:** `ceda817fc43cb1249404a110b2517adc10e22b5d39ec7c29f0ed322862e38c09`

## Checks
- `regression` / `player-stays-above-ground` on `smoke` → **pass**
- `gameplay` / `player-motion-on-smoke` on `smoke` → **pass**
- `clean` / `player-stays-above-ground` on `clean-control` → **pass**
- `held-out` / `player-stays-above-ground` on `held-out-interim` → **pass**

## Reasons
- all 4 checks passed

## Suite provenance
- candidate: source=`fixture` path=`/Users/fehintola/Documents/GitHub/Nightshift/agents/fixtures/obs-fixed.json` obsSha256=`ca960e024b7a8206…`
- clean: source=`fixture` path=`/Users/fehintola/Documents/GitHub/Nightshift/agents/fixtures/obs-clean.json` obsSha256=`7395c39139725a6c…`
- held-out: source=`interim-fixture` path=`/Users/fehintola/Documents/GitHub/Nightshift/agents/fixtures/obs-held-out.json` obsSha256=`572202e6219eed6c…`

## Gameplay
- result: `pass`
- reason: player moved 290.0px (min 200.0), ended on floor, no sustained below-ground
- source: `fixture-trace:trace-fixed.json`
- minDeltaX: `200.0`
- deltaX: `290.0`
- endOnFloor: `True`
- belowStreak: `0`
- sampleCount: `3`

## Before / after frames
- before: `frames/before-00.png` (sha256 `d64794a278dd4b21…`)
  ![before](frames/before-00.png)
- after: `frames/after-00.png` (sha256 `cadd538835e83f37…`)
  ![after](frames/after-00.png)

## Candidate diff (head)
```diff
--- a/player/player.tscn
+++ b/player/player.tscn
@@ -187,7 +187,7 @@
 
 [node name="Player" type="CharacterBody2D" unique_id=457318108]
 scale = Vector2(0.8, 0.8)
-collision_mask = 14
+collision_mask = 30
 floor_constant_speed = true
 platform_on_leave = 2
 script = ExtResource("3")
```

## Unresolved for a human
- none

## Signed release candidate
- file: `release-candidate.json`
- verification sha256: `235a53261677713abbaec30924c30a2e2a027fb8cd0287258ada106baed3d84e`
- signature: `d29c64eba2c6aed6…`
- signing material: `demo-fake-key` (never mounted into the fixer workspace)
- request id: `rr-gate1`
- request sha256: `a8af3bb8fd86e4d3fa7ffbd927d1fd883ab08fa675398f57ff7d72d21d3515db`

