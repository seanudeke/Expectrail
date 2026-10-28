# SAM 3.1 in Pixel Proof

SAM 3.1 turns captured frames into observations: for each object a test spec names, where it is in
each frame and how sure the model is. The evaluator then decides the spec over those boxes with
plain code. This page is the handoff for wiring SAM in for real and calibrating it.

## Status

- Built: the adapter (`agents/sam_observations.py`), the probe (`agents/sam_probe.py`), a manual
  GitHub Actions workflow (**SAM probe**), and offline tests (`tests/test_sam.py`).
- Not done yet: **no call has been made to the live API from this repo.** The build environment had
  no key. The parser follows Meta's documented output format and reads a published sample response
  correctly, but the first live run is the real test. Run the probe first (below).
- CI on pull requests keeps using the position-log stand-in (`trace` provider). It has no key.

## Where SAM runs

SAM 3.1 is on the Meta Model API, the same service and key type as Muse Spark. No GPU and no
Hugging Face access are needed.

| | |
| --- | --- |
| Endpoint | `POST https://api.meta.ai/v1/responses` |
| Model | `sam-3.1` |
| Key | `MODEL_API_KEY`, from the shell or the gitignored `.env`; never committed, never pasted into chat |
| One request | one concept prompt (a short noun phrase) and one frame as a base64 PNG |
| Asked for | `include_confidence` (the evaluator thresholds on it), masks in the small one-bit encoding |

`MODEL_API_KEY` is not on Muse Code's environment allowlist (`agents.keys.MUSE_ENV_ALLOWLIST`),
and a test keeps it that way. That only protects the variable, not the value: if `MODEL_API_KEY`
and `META_API_KEY` hold the same key, the fixer holds the verifier's key too. **Use a separate
key for SAM** (a second key from dev.meta.ai, stored as the `MODEL_API_KEY` secret). The adapter
prints a warning when the two are the same. The CI jobs that set `MODEL_API_KEY` from the
`META_API_KEY` secret do not run SAM today; switch them to their own secret before they do.

Check the pricing and rate limits page on dev.meta.ai before a big run. The probe's `--dry-run`
prints how many requests it would send.

## Run it

**From GitHub, no setup.** Actions, then **SAM probe**, then **Run workflow**. It renders the clean
game and every seeded bug, probes every 10th frame (13 frames a run), and puts `probe.md` in the
run summary. Overlays and contact sheets are in the `sam-probe` artifact. It uses the
`MODEL_API_KEY` secret, or `META_API_KEY` if that is the only one set. The workflow appears in the
Actions list once this file is on `main`.

**Locally:**

```sh
export MODEL_API_KEY=...                      # or put it in .env
python3 -m harness.check_seeded --out runs/seeded          # clean + seeded bugs, with frames
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --dry-run   # what it would send
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --out runs/sam-probe
open runs/sam-probe/probe.md runs/sam-probe/*-sheet.png
```

**One replay, then its verdict:**

```sh
python3 -m agents.sam_observations --run runs/seeded/physics-fall-through_v1 \
  --spec specs/player-stays-above-ground.json
```

**The whole loop:** set `PIXELPROOF_OBS_PROVIDER=sam`. The verifier then sends the candidate,
clean and held-out replays' frames to SAM, with the regression spec's prompts and window.

## What to decide from the probe, in order

Any change to a prompt, `minScore` or `tolerancePx` changes the spec, so it needs Sean's approval
again (`python3 -m pixelproof.spec_writer approve ...`).

1. **Is the player found on every clean frame?** The evaluator is strict: one clean frame without
   the player makes the clean check needs-review, and the verifier will not accept a fix. If the
   probe shows misses, try other prompts ("robot", "small robot") or a per-object `minScore`.
2. **What does "grass-topped ground" match?** The floating platforms are grass-topped too. For
   `never-crosses`, the evaluator takes the ground matches that overlap the player horizontally and
   picks the one whose top edge is nearest the player's bottom edge, above or below it. When the
   player jumps under a platform, that can be the platform above, which reads as "past the
   boundary": a false fail on the clean run. The probe shows it as a large gap on a clean jump frame.
   If it happens, narrow the prompt, or change the rule to "the nearest surface under the player"
   (an evaluator change: agree it with Sean and add a test).
3. **Set the tolerance in the right units.** The approved `tolerancePx` is 12, set against the
   position-log stand-in, whose boxes are in game-world pixels. SAM's boxes are in captured-frame
   pixels, and frames are 1600x960 for an 800x480 game viewport (camera zoom 1), so one world pixel
   is two frame pixels: 12 here means 6 in the old units. The probe prints the worst clean gap and
   the fall-through gaps. Pick a tolerance above every clean gap and below the bugs'.
4. **The other bug families need their own specs.** On the missing-texture and layering runs this
   spec is about the player and the ground, so a hidden player shows up as "not found", which is
   needs-review. That is correct for this spec. Catching those bugs needs specs such as "the coin is
   visible" and "the player is visible".
5. **Sample rate.** The default is every 4th frame, the rate in `docs/evaluation.md`. Time and
   cost per request from the probe run decide whether to change it.

## How it looks at fewer frames

- **Sample.** Every Nth frame of the spec's window, plus its last frame (`PIXELPROOF_SAM_EVERY`,
  default 4).
- **Refine.** When the spec fails on a sampled frame, look at every frame between the last sample
  that passed on its own and the first failing one, so the first bad frame in the report is exact.
  A sample where the object was missing or the check did not apply does not count as passing, so
  the stretch reaches back past it. In the offline test, a fall that starts between samples is
  found at the same frame as looking at every frame, from 22 of 120 frames.
- **Cache.** Results are kept by frame SHA-256, prompt, model and request settings, so a frame
  that was already judged is never sent again. Replays are bit-identical, so an unchanged route
  costs nothing the second time.
- **Counting assertions are not sampled.** `visible` with a `minFraction` below 1 looks at every
  frame. `reaches` samples, and unless a sample already reaches the goal it looks at every frame
  before deciding.

Limits, plainly: a glitch shorter than the gap between samples can be missed (use
`PIXELPROOF_SAM_EVERY=1` for a run that must not miss one). Every verdict says how many frames it
judged, and the observations document records `framesAnalyzed` against `framesCaptured`.

**The cache is verifier state.** It lives outside the repo (`~/.cache/pixelproof/sam`, or
`PIXELPROOF_SAM_CACHE`), so it is never in the fixer's worktree, and under bubblewrap the fixer gets
an empty home directory and cannot reach it. With no OS sandbox nothing stops a process on the same
machine from writing there, so set `PIXELPROOF_SAM_CACHE=off` for the recorded demo and any run
whose verdict has to be beyond question.

## When SAM fails

Any failure makes the check needs-review, never a pass and never a crash. That covers a failed,
partial or unrecognised reply, a box without a confidence, a number that is not finite, missing
frames, and anything unexpected:

- candidate replay: the regression check is needs-review, error in `observations-error.txt`;
- clean replay: the clean check is needs-review, error in `observations-clean-error.txt` (the
  clean fixture is only used when the harness itself fails, as before);
- held-out routes: needs-review.

Rate limits, server errors and dropped connections are retried three times with backoff; bad
requests are not retried. After the first failure, queued requests for that replay are cancelled.
The parser is strict: text it does not recognise is an error, not "nothing found", so a refusal or
a format change can never be cached as a frame with no player in it.

## Not built yet

- **Video mode.** SAM 3.1 can take a whole clip in one request and track objects with stable ids
  (billed per frame, 50-frame minimum per request, up to 16 tracked objects). Worth it if
  per-frame requests are slow or costly. Trade-offs: H.264 compression of the frames, and the
  cache would work per run instead of per frame.
- **Box and point prompts from the engine.** SAM 3.1 also takes a box or point saying where to look.
  Prompting it with where the engine says the player is would make detection more reliable, and a
  missing texture or a hidden sprite would still come back empty. It also makes vision less
  independent of the engine, so if we use it we say so.
- **Masks.** Boxes are all the evaluator uses today.
