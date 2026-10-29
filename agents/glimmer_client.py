"""Muse Glimmer (open weights) as Nightshift's frame-vision backend, behind SAM's client interface.

    export FIREWORKS_API_KEY=...                     # or NIGHTSHIFT_GLIMMER_API_KEY; never commit it
    # verdicts: an object counts only where SAM and Glimmer both see it (needs MODEL_API_KEY too)
    NIGHTSHIFT_VISION_BACKEND=both NIGHTSHIFT_OBS_PROVIDER=sam python3 -m agents.gate1 ...
    # measuring Glimmer alone on known runs
    NIGHTSHIFT_VISION_BACKEND=glimmer python3 -m agents.sam_probe --spec specs/player-always-visible.json \\
        --runs runs/seeded/*/

The verifier's vision checks (the visibility specs and the hybrid ground check) ask one question per
frame and object: where is "<noun phrase>" drawn? ``agents.sam_observations`` asks SAM 3.1 through
the Meta Model API. With ``NIGHTSHIFT_VISION_BACKEND=glimmer`` the same question goes to Muse
Glimmer 30B (Apache 2.0) on any OpenAI-compatible endpoint: Fireworks serverless by default
(``accounts/fireworks/models/muse-glimmer-30b``), or our own vLLM/SGLang server
(``NIGHTSHIFT_GLIMMER_API_BASE=http://<host>:8000/v1``,
``NIGHTSHIFT_GLIMMER_MODEL=meta-models/Muse-Glimmer-30B``). Everything around the call stays the
same: sampling, refining to the first bad frame, confirming every frame before a pass, the cache,
and needs-review on any failure.

Glimmer never decides an accept on its own. It reads images the way a language model reads text,
and the fixer controls the candidate's pixels: a fix could draw text into the game that talks a
vision-language model into "the robot is there". SAM 3.1 is a segmenter and cannot be talked to. So
the verifier uses ``NIGHTSHIFT_VISION_BACKEND=both``: SAM's boxes count only on frames where Glimmer
also sees the object (``BothClient``), which can only make the gate stricter than SAM alone.
``glimmer`` alone is for measuring Glimmer (``agents.sam_probe``, or the verifier with
``NIGHTSHIFT_GLIMMER_ALONE=1`` on known fixtures); without that flag the verifier refuses it and every
vision check is needs-review.

What differs from SAM, and the code is honest about:

- Glimmer is a vision-language model, not a segmenter. It answers in JSON with boxes it reads off
  the image; it has no mask and no calibrated score. ``confidence`` is Glimmer's own 0-1 rating,
  recorded as the detection score so the evaluator's threshold applies, and labelled
  self-reported in the observations document (``model.provider``).
- Coordinates: the prompt asks for pixels of the image it was sent. Some VLMs answer on a 0-1000
  grid instead; set ``NIGHTSHIFT_GLIMMER_COORDS=norm1000`` (or ``norm1``) if the probe shows that.
  A box far outside the image is refused (needs-review), never clipped into a pass.
- Positions stay in code: Glimmer is only ever asked for the spec's noun phrase, never "is it
  below the ground"; the evaluator decides that from the boxes, as it does for SAM.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from agents.sam_observations import MetaSamClient, SamError, data_url, png_size

API_BASE = os.environ.get("NIGHTSHIFT_GLIMMER_API_BASE", "https://api.fireworks.ai/inference/v1")
MODEL = os.environ.get("NIGHTSHIFT_GLIMMER_MODEL", "accounts/fireworks/models/muse-glimmer-30b")
KEY_ENVS = ("NIGHTSHIFT_GLIMMER_API_KEY", "FIREWORKS_API_KEY")
COORDS_ENV = "NIGHTSHIFT_GLIMMER_COORDS"
COORDS = ("pixels", "norm1000", "norm1")
# Bump when the prompt or the parsing changes, so cached answers to an older question are not reused.
REQUEST_VERSION = "glimmer-1"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# A corner more than 2% of the frame outside the image is a format error (another grid, or not a box).
OUT_OF_FRAME = 0.02
SCHEMA_REFUSAL = ("response_format", "json_schema", "schema", "structured")

SYSTEM_PROMPT = (
    "You are the eyes of an automated test for a 2D platformer game. You look at one captured frame "
    "and report where a named thing is drawn in it. Report only what is visibly drawn in this image: "
    "something hidden behind scenery, off screen, or not drawn at all is not visible. Never guess."
)

BOX_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objects"],
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["box", "confidence"],
                "properties": {
                    "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }
    },
}

Transport = Callable[[dict], "tuple[bytes, str]"]


def user_prompt(prompt: str, size: tuple[int, int]) -> str:
    w, h = size
    return (
        f'This image is {w} by {h} pixels. Find every visible "{prompt}". '
        'Answer with JSON only: {"objects": [{"box": [x0, y0, x1, y1], "confidence": c}]}, one entry per '
        f"separate {prompt}. Box corners are pixels of this image: x0, y0 is the top-left corner and x1, "
        "y1 the bottom-right, with the origin at the top-left and y growing downward. confidence is how "
        'sure you are, from 0 to 1. If none is visible, answer {"objects": []}.'
    )


def request_body(prompt: str, image_url: str, size: tuple[int, int], model: str = MODEL,
                 structured: bool = True) -> dict:
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt(prompt, size)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
    }
    if structured:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "nightshift_boxes", "schema": BOX_SCHEMA}}
    else:
        body["response_format"] = {"type": "json_object"}
    return body


def answer_text(raw: bytes) -> str:
    try:
        doc = json.loads(raw)
        content = doc["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
        raise SamError(f"glimmer reply is not a chat completion: {raw[:160]!r}") from exc
    if isinstance(content, list):  # content parts
        texts = [p.get("text", "") for p in content if isinstance(p, dict)]
        if not all(isinstance(t, str) for t in texts):
            raise SamError("glimmer reply has a content part whose text is not a string")
        content = "".join(texts)
    if not isinstance(content, str):
        raise SamError("glimmer reply has no text content")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return text.strip()


def _num(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SamError(f"glimmer box value is not a number: {str(value)[:40]!r}")
    try:
        out = float(value)
    except OverflowError as exc:
        raise SamError("glimmer box value is too large to be a pixel") from exc
    if not math.isfinite(out):
        raise SamError(f"glimmer box value is not finite: {out!r}")
    return out


def parse_boxes(text: str, size: tuple[int, int], coords: str = "pixels") -> list[dict]:
    """Glimmer's JSON answer -> [{"box": [x0, y0, x1, y1], "score": c}] in pixels of ``size``.

    Prose, a missing confidence, corners in the wrong order, a box outside the frame or any other
    surprise raises SamError, which the verifier turns into needs-review. Nothing is repaired into a
    box: an [x, y, w, h] answer or one on another grid is refused, not reinterpreted.
    """
    if coords not in COORDS:
        raise SamError(f"{COORDS_ENV} must be one of {', '.join(COORDS)}")
    try:
        return _parse_boxes(text, size, coords)
    except SamError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise SamError(f"unreadable glimmer answer: {type(exc).__name__}") from exc


def _parse_boxes(text: str, size: tuple[int, int], coords: str) -> list[dict]:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise SamError(f"glimmer did not answer in JSON: {text[:120]!r}") from exc
    objects = doc.get("objects") if isinstance(doc, dict) else None
    if not isinstance(objects, list):
        raise SamError(f"glimmer answer has no objects list: {text[:120]!r}")
    w, h = float(size[0]), float(size[1])
    scale = {"pixels": (1.0, 1.0), "norm1000": (w / 1000.0, h / 1000.0), "norm1": (w, h)}[coords]
    out = []
    for obj in objects:
        if not isinstance(obj, dict) or not isinstance(obj.get("box"), list) or len(obj["box"]) != 4:
            raise SamError(f"unreadable glimmer box: {str(obj)[:120]}")
        if "confidence" not in obj:
            raise SamError("glimmer returned a box without a confidence; a missing score is never guessed")
        score = _num(obj["confidence"])
        if not 0.0 <= score <= 1.0:
            raise SamError(f"glimmer confidence outside 0..1: {score}")
        x0, y0, x1, y1 = (_num(v) for v in obj["box"])
        x0, x1 = x0 * scale[0], x1 * scale[0]
        y0, y1 = y0 * scale[1], y1 * scale[1]
        if x1 <= x0 or y1 <= y0:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} is not [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        if x0 < -OUT_OF_FRAME * w or x1 > (1 + OUT_OF_FRAME) * w or \
                y0 < -OUT_OF_FRAME * h or y1 > (1 + OUT_OF_FRAME) * h:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} is outside the {int(w)}x{int(h)} frame; "
                           f"check {COORDS_ENV} (now {coords})")
        x0, x1 = max(0.0, x0), min(w, x1)
        y0, y1 = max(0.0, y0), min(h, y1)
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} has no area inside the frame")
        # The score is kept as given: rounding could lift 0.49996 over the evaluator's 0.5.
        out.append({"box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)], "score": score})
    return sorted(out, key=lambda d: (-d["score"], d["box"]))


def api_key() -> str | None:
    for name in KEY_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


class GlimmerClient(MetaSamClient):
    """Muse Glimmer behind ``segment(png, prompt)``, so agents.sam_observations runs unchanged."""

    def __init__(self, *, model: str | None = None, base: str | None = None, key: str | None = None,
                 transport: Transport | None = None, coords: str | None = None, retries: int = 3,
                 timeout: float = 180.0, sleep: Callable[[float], None] = time.sleep):
        super().__init__(model=model or MODEL, base=base or API_BASE, transport=transport, retries=retries,
                         timeout=timeout, sleep=sleep)
        self._key = key
        self.coords = (coords or os.environ.get(COORDS_ENV, "pixels")).strip().lower()
        if self.coords not in COORDS:
            raise SamError(f"{COORDS_ENV} must be one of {', '.join(COORDS)}, not {self.coords!r}")
        host = urllib.parse.urlparse(self.base).hostname or self.base
        # What the observations document records as the provider (see _document).
        self.provider = f"open-weights glimmer at {host}, self-reported confidence"
        # Part of the cache key: a changed prompt or coordinate reading never reuses old answers.
        self.cache_tag = f"#{REQUEST_VERSION}#{self.coords}"
        self._structured = True
        self._flag = threading.Lock()

    def _http(self, body: dict) -> tuple[bytes, str]:
        key = self._key or api_key()
        if not key:
            raise SamError(f"set one of {', '.join(KEY_ENVS)} for {self.base} (never commit it)")
        if key == os.environ.get("META_API_KEY", "").strip():
            raise SamError("the Glimmer key is the same as META_API_KEY, which Muse Code (the fixer) "
                           "receives; the verifier's vision key must be its own")
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")

    def _call(self, body: dict) -> tuple[bytes, str]:
        delay = 2.0
        for attempt in range(self.retries + 1):
            with self._lock:
                self.calls += 1
            started = time.monotonic()
            try:
                return self._transport(body)
            except SamError:
                raise
            except urllib.error.HTTPError as err:
                try:
                    detail = err.read().decode(errors="replace")[:300]
                except (OSError, http.client.HTTPException):
                    detail = ""
                if err.code not in RETRY_STATUS or attempt == self.retries:
                    raise SamError(f"glimmer HTTP {err.code}: {detail}") from err
            except (OSError, http.client.HTTPException) as err:
                if attempt == self.retries:
                    raise SamError(f"glimmer unreachable after {attempt + 1} tries: "
                                   f"{type(err).__name__}: {err}") from err
            finally:
                with self._lock:
                    self.seconds += time.monotonic() - started
            self._sleep(delay)
            delay *= 2
        raise SamError("unreachable")  # pragma: no cover

    def segment(self, png: Path, prompt: str) -> list[dict]:
        size = png_size(png)
        url = data_url(png)
        structured = self._structured
        try:
            raw, _ = self._call(request_body(prompt, url, size, self.model, structured))
        except SamError as exc:
            # A server that rejects json_schema gets plain JSON mode, once, remembered. Any other
            # 400 (image too large, context length) is a real failure: needs-review.
            text = str(exc).lower()
            if not (structured and text.startswith("glimmer http 400") and any(w in text for w in SCHEMA_REFUSAL)):
                raise
            with self._flag:
                self._structured = False
            raw, _ = self._call(request_body(prompt, url, size, self.model, False))
        return parse_boxes(answer_text(raw), size, self.coords)


class BothClient:
    """SAM 3.1's boxes, counted only on frames where Muse Glimmer also sees the object.

    The verdict backend: an object is found when both models find it, so adding Glimmer can only
    make a check stricter than SAM alone. Boxes (and their scores) are SAM's, since the evaluator's
    geometry needs a segmenter's precision; Glimmer answers "is it visibly drawn here at all".
    """

    def __init__(self, sam_client: MetaSamClient | None = None, glimmer: GlimmerClient | None = None,
                 min_score: float | None = None):
        from nightshift.evaluator import DEFAULT_MIN_SCORE

        self.sam = sam_client or MetaSamClient()
        self.glimmer = glimmer or GlimmerClient()
        self.min_score = DEFAULT_MIN_SCORE if min_score is None else min_score
        self.model = f"{self.sam.model}+{self.glimmer.model}"
        self.base = f"{self.sam.base}|{self.glimmer.base}"
        self.cache_tag = self.glimmer.cache_tag + "#both-1"
        host = urllib.parse.urlparse(self.glimmer.base).hostname or self.glimmer.base
        self.provider = f"SAM 3.1 boxes, counted only where open-weights glimmer at {host} also sees the object"

    @property
    def calls(self) -> int:
        return self.sam.calls + self.glimmer.calls

    @property
    def seconds(self) -> float:
        return self.sam.seconds + self.glimmer.seconds

    def segment(self, png: Path, prompt: str) -> list[dict]:
        seen = [d for d in self.glimmer.segment(png, prompt) if d["score"] >= self.min_score]
        if not seen:
            return []  # Glimmer does not see it: not found, whatever SAM says
        return self.sam.segment(png, prompt)
