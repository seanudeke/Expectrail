# Open weights in Nightshift

**Muse Glimmer 30B is a second pair of eyes in every vision check, and Muse Spark Open writes the
checks.** Both are Meta open-weight models, served through partner inference (Fireworks, Baseten) or
our own server. Muse Code (the fixer), Muse Voice Transcribe and SAM 3.1 stay on Meta's hosted API.

This page is for the infrastructure partner verifying the open-weights prize, and for us: what runs
on which model, where, and how to check it.

| Role | Model (license) | Served by | Turn it on | Code |
| --- | --- | --- | --- | --- |
| Vision checks: is the robot visible, are the coins drawn, where are the robot's feet against the level's ground line | Muse Glimmer 30B (Apache 2.0, per its model card), together with SAM 3.1 (`both`) or checked against the game engine with no SAM (`glimmer-engine`) | A Fireworks on-demand deployment of `accounts/fireworks/models/muse-glimmer-30b` (Glimmer left Fireworks serverless on Sep 25, 2026); or any OpenAI-compatible server we run | `NIGHTSHIFT_OBS_PROVIDER=sam NIGHTSHIFT_VISION_BACKEND=both` (keys in `FIREWORKS_API_KEY` and `MODEL_API_KEY`) or `=glimmer-engine` (`FIREWORKS_API_KEY` only) | `agents/glimmer_client.py`, `agents/engine_check.py` |
| Test-spec drafting from plain English | Muse Spark Open (Muse Model License) | Baseten, `meta-models/muse-spark-open-1026` | `python3 -m nightshift.spec_writer draft "..." --endpoint open`, key in `BASETEN_API_KEY` | `nightshift/spec_writer.py` |
| Sorting playtester feedback and drafting checks from it | Muse Spark Open | Baseten | `python3 -m agents.feedback ... --sorter open` | `agents/feedback.py` |

## Serve Glimmer on Fireworks (on-demand)

Fireworks retired Glimmer from serverless on Sep 25, 2026 (its model page says so), so a request to
`accounts/fireworks/models/muse-glimmer-30b` returns HTTP 404 "Model not found, inaccessible, and/or
not deployed". It still runs as an on-demand deployment: dedicated GPUs, billed per GPU-second while
a replica is up, and able to scale to zero when idle.

1. Create the deployment, from the model's page in the Fireworks dashboard or with `firectl`:

   ```sh
   firectl deployment create accounts/fireworks/models/muse-glimmer-30b \
     --deployment-shape default --min-replica-count 0 --max-replica-count 1 \
     --scale-to-zero-window 15m --wait
   ```

   It prints `accounts/<account>/deployments/<id>`.
2. Put that string in the repository variable `GLIMMER_MODEL` (Settings → Secrets and variables →
   Actions → Variables), or in `NIGHTSHIFT_GLIMMER_MODEL` for local runs.
3. The probe workflow wakes the deployment first (`python -m agents.glimmer_client --warm`): a
   deployment at zero replicas answers 503 for a few minutes while it starts.
4. With minimum replicas at 0 and a 15-minute scale-to-zero window, it stops billing 15 minutes
   after the last request (Fireworks' default window is an hour). Fireworks deletes a deployment
   that has had no traffic for 7 days. Check the GPU price for the shape it picks before leaving it up, and
   recreate it for the judging window (Nov 4 to 9) if the partner needs to see it run.

## How Glimmer fits

The verifier asks one question per frame and object: where is "blue robot" (or "gold coin") drawn?
SAM 3.1 answers through the Meta Model API. Glimmer gets the same question, as an image plus a
JSON-only instruction, and answers with boxes in pixels of the frame.

**With `NIGHTSHIFT_VISION_BACKEND=both` (the verdict setting), an object counts as found only on
frames where both models find it.** The boxes used for geometry are SAM's. So adding Glimmer can
only make a check stricter than SAM alone: a robot Glimmer cannot see fails, even if SAM finds it.

**Glimmer never decides an accept unchecked.** It reads images the way a language model reads
text, and the fixer controls the candidate's pixels: a fix could draw text into the game that talks
a vision-language model into "the robot is there". So each of Glimmer's answers is checked by
something that cannot be talked to:

- **`both`:** SAM 3.1, a segmenter, must find the object too.
- **`glimmer-engine` (no SAM):** the game engine must have put the object there. The harness logs
  where the robot is and where every coin is on every frame (`player` and `coins` in trace.json,
  projected to frame pixels with that frame's camera). A Glimmer box counts only if it contains the
  centre of an object the engine placed on that frame and is at most 3x its width and height
  (`agents/engine_check.py`). A box beside the robot, or one over half the screen, is dropped and
  counted in the observations document (`model.engineCheck`). The trace and the check run on the
  verifier's side, after the frame cache; a replay whose trace cannot place objects is needs-review.

The verifier refuses `NIGHTSHIFT_VISION_BACKEND=glimmer` with neither check (every vision check
becomes needs-review) unless `NIGHTSHIFT_GLIMMER_ALONE=1` is set to measure Glimmer on known
fixtures.

What the engine check does not stop: Glimmer steered onto the object's true position. The fixer can
compute where the hidden robot is, because it wrote the game, and could try to draw text that makes
Glimmer answer with exactly that box. That is a far narrower attack than "write 'robot here'
anywhere", but it is not zero. Where SAM is available, `both` remains the stronger setting.

Everything around the question is shared code (`agents/sam_observations.py`):

- sampling every fourth frame by default (`NIGHTSHIFT_SAM_EVERY`; the probe workflow defaults to
  every tenth);
- refining to the exact first bad frame;
- confirming every remaining frame before a pass;
- the cache, keyed by model, endpoint and prompt version;
- turning any failure into needs-review, never a pass.

The evaluator then decides each spec from the boxes, in plain code. Glimmer is never asked "is it
below the ground", only "where is it".

Why open weights matter here beyond the prize: an unreleased game build is confidential, and a
studio wants its quality gate on infrastructure it controls. With `glimmer-engine`, every vision
check runs on Glimmer, which a studio can serve on its own hardware, and nothing leaves for a
hosted vision API.

## How to verify it

- Every observations document records `model.name` (the model id) and `model.provider`, for example
  `open-weights glimmer at api.fireworks.ai, self-reported confidence`. The verifier keeps one per
  check in `runs/<run>/verify/`.
- **Glimmer probe** (Actions, manual): mode `probe` renders the clean game and every seeded bug and
  asks Glimmer alone what it sees. Mode `verify` runs the Gate 1 path with judge `both` (or Glimmer
  alone, as a measurement), including the private held-out routes. Results are posted as
  annotations on the run. The key is only sent over https to `api.fireworks.ai` or the host in the
  `GLIMMER_ALLOWED_HOST` repository variable.
- Self-hosting: Glimmer's model card documents OpenAI-compatible serving with vLLM and SGLang, and
  says the 4-bit weights fit a 24 GB GPU. Point `NIGHTSHIFT_GLIMMER_API_BASE` at the server's `/v1`
  URL and set `NIGHTSHIFT_GLIMMER_MODEL` to the id it serves. If the server resizes images before the
  model sees them, Glimmer's pixels are in the resized image's space: run the probe and set
  `NIGHTSHIFT_GLIMMER_COORDS` to match before trusting any box.

## What was measured (Oct 29, Fireworks on-demand deployment, 1x H200)

Glimmer alone, probe mode, every 10th frame (13 frames a run), on the same seeded runs SAM was
measured on (docs/sam.md, SAM every 4th frame):

| Spec | Clean | Seeded bugs | SAM on the same bugs |
| --- | --- | --- | --- |
| `player-always-visible` (blue robot) | pass, 13/13 (lowest 0.85) | fall-through v1, v2: fail (3/13); layering v1, v2: fail (7/13); sinking v1: fail (12/13); missing-texture v1, v2: pass | fall-through 6/31, layering 17/31, missing-texture pass |
| `coins-visible` (gold coin) | pass, 13/13, 10 to 14 coins a frame | missing-texture v1, v2: fail (0/13); every robot bug: pass | 11 to 16 coins a frame; missing-texture 0/13 |

Runs 40904213270 (robot) and 40915470775 (coins). Glimmer misses the robot in about the same share
of frames as SAM on each bug, and raised no false alarm on the clean run. Its robot box is about
70x140 pixels against SAM's 95x118, so it answers in pixels (`coords=pixels`).

Verify mode, judge `both`, every 4th frame, with the four private held-out routes:

| Candidate | Decision | Checks |
| --- | --- | --- |
| `fix-collision-mask.patch` (the real fix) | **accept** | all 8 checks pass; ground, robot and coins pass on 4/4 held-out routes (run 40924660911) |
| `fix-collision-mask.patch`, earlier run | needs-review | as above, except coins on one held-out route had no verdict (run 40915475383) |
| `fix-but-hide-player.patch` | **reject** | player-always-visible fails on the candidate and passes on 0/4 held-out routes; coins pass (run 40915479861) |

The earlier needs-review was an observations error on one held-out route (Glimmer seeing no coins
would have been a fail), in a run that shared the one replica with two others. It did not recur
when the run had the deployment to itself, so its kind is unknown; the workflow now reports the
kind of any held-out error (kind only, see "Glimmer verify held-out error"). An error never
passes a check: it stops at needs-review, so the cost of one is a re-run, not a wrong accept.

## What is not measured yet

- **Glimmer on every frame.** The probe sampled 13 frames a run; SAM's clean numbers are on all
  120. Verify mode confirms every frame before a pass, so `both` is measured there, Glimmer alone is not.
- **Box precision.** The hybrid ground check compares the robot's box against the ground line with
  a 20-pixel tolerance. In `both` the boxes are SAM's, so this only matters for Glimmer alone, whose
  box is taller and narrower than SAM's (see above).
- **Confidence is self-reported, and flat.** Glimmer rates its own boxes from 0 to 1, and gave 0.90 to
  every coin on every frame. The evaluator's 0.5 threshold and the verifier's clean-score floor apply
  to that number, but it is not a margin the way SAM's scores are. Another reason `both` is the judge.
- **Speed.** 3.2 s a call with one run on the deployment, 12.2 s with three runs sharing one replica.
  A verify run with `both` took about 35 to 40 minutes, alone or shared.
- **Coordinates.** The prompt asks for pixels of the image. If the probe shows Glimmer answering on
  a 0-1000 grid, set `NIGHTSHIFT_GLIMMER_COORDS=norm1000`. Boxes with corners in the wrong order, or
  more than 2% of the frame outside it, are refused (needs-review); a box a few pixels past an edge
  is clipped to it. A grid mismatch is not always detectable from one answer (on a 1600x960 frame, a
  0-1000 box also looks like pixels), which is why the probe compares Glimmer's boxes with SAM's on
  the same frames first.

## What is not built yet

- **Engine positions for other objects.** The engine check knows the robot and the coins. A spec
  about anything else (an enemy, a door) is needs-review under `glimmer-engine` until the harness
  logs it too.
- **Glimmer's box precision for the ground check.** Under `glimmer-engine` the hybrid ground check
  compares Glimmer's robot box (not SAM's) with the ground line, at the spec's 20-pixel tolerance.
  The clean run of the verify workflow shows whether that holds.

## Keys

`FIREWORKS_API_KEY` (or `NIGHTSHIFT_GLIMMER_API_KEY`) and `BASETEN_API_KEY` (or
`NIGHTSHIFT_OPEN_API_KEY`) are read from the environment or the gitignored `.env`. None of them is on
Muse Code's environment allowlist. The Glimmer key may not be the same as `META_API_KEY`, the key
the fixer holds. In CI, add the `FIREWORKS_API_KEY` repository secret; `both` also needs the SAM key
(`MODEL_API_KEY`). The workflow does not pass the SAM key to a `glimmer-engine` run.
