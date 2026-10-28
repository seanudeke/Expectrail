"""SAM 3.1 observations through the Meta Model API: the ``sam`` observations provider.

For the frames of one replay, asks SAM 3.1 (model ``sam-3.1`` on ``POST /v1/responses``) to find
each object a test spec names, and writes nightshift.observations/v0 with boxes in pixels of the
captured frame. The evaluator then decides the spec over that document, exactly as it does for the
position-log stand-in.

Looking at fewer frames (docs/sam.md has the reasoning and the limits):
  - sample: every Nth frame of the spec's window, plus its last frame (NIGHTSHIFT_SAM_EVERY,
    default 4, the rate in docs/evaluation.md);
  - refine: when the spec fails on a sampled frame, look at every frame between the last passing
    sample and the first failing one, so the first bad frame in the report is exact;
  - cache: results are kept by frame SHA-256, prompt, model and request settings, so a frame that
    was already judged is never sent again (NIGHTSHIFT_SAM_CACHE; "off" disables it).
A frame that was not looked at is absent from the document, as the contract says.

The key is read from MODEL_API_KEY in the environment (or the gitignored .env) and nowhere else.
It is not on the fixer's environment allowlist (agents.keys.MUSE_ENV_ALLOWLIST), so Muse Code
never sees it.

    python3 -m agents.sam_observations --run runs/seeded/clean --spec specs/player-stays-above-ground.json
    NIGHTSHIFT_OBS_PROVIDER=sam ...   # the verifier then uses this module through agents.observations
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from nightshift.evaluator import evaluate

API_BASE = os.environ.get("NIGHTSHIFT_MODEL_API_BASE", "https://api.meta.ai/v1")
MODEL = os.environ.get("NIGHTSHIFT_SAM_MODEL", "sam-3.1")
KEY_ENV = "MODEL_API_KEY"
EVERY_ENV = "NIGHTSHIFT_SAM_EVERY"
CACHE_ENV = "NIGHTSHIFT_SAM_CACHE"
WORKERS_ENV = "NIGHTSHIFT_SAM_WORKERS"
DEFAULT_EVERY = 4
DEFAULT_WORKERS = 4
# Bump when the request or the parsing changes, so older cache entries are never reused.
REQUEST_VERSION = "1"
# Confidence is required: the evaluator thresholds on it, and a missing score is never guessed.
# Masks are not used yet, so ask for the smaller encoding.
METADATA = {"include_confidence": "true", "mask_encoding": "one_bit"}
DEFAULT_PROMPTS = {"player": "small robot character", "ground": "grass-topped ground"}
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# Kinds whose verdict fails as soon as one judged frame fails, so sampling can only miss a
# failure, never invent one, and refinement can only move the first failing frame earlier.
SAMPLE_SAFE = frozenset({"never-crosses", "inside-region"})

Transport = Callable[[dict], "tuple[bytes, str]"]


class SamError(RuntimeError):
    """SAM could not produce observations. Callers must treat the check as needs-review."""


# ---------------------------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------------------------

# One line per image (one per frame for video). A line starts with a frame marker <Nf> and holds
# comma-separated records: <id><|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...|>
# Mask payloads never contain '|' or '<', so a token ends at the first '|>'.
TOKEN_RE = re.compile(r"<(\d+)f>|(-?\d+)<\|box;([^|]*)\|>|<\|mask;[^|]*\|>")


def _fields(text: str) -> dict[str, str]:
    out = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_output(text: str, frame_size: tuple[int, int] | None = None) -> list[dict]:
    """Parse SAM 3.1 special-token output into box records.

    Box corners on the wire are inclusive pixel indices; records come back half-open
    ``[x0, y0, x1, y1]`` (x1 = x2 + 1, so width = x2 - x1 + 1), scaled to ``frame_size`` when the
    service reports a different media size. ``score`` is the box confidence ``c`` or None.
    """
    records = []
    frame = None
    for m in TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            frame = int(m.group(1))
            continue
        if m.group(3) is None:
            continue  # a mask token; boxes are all the evaluator needs today
        f = _fields(m.group(3))
        try:
            x1, y1, x2, y2 = (float(f[k]) for k in ("x1", "y1", "x2", "y2"))
        except (KeyError, ValueError) as exc:
            raise SamError(f"unreadable box token: {m.group(0)[:120]}") from exc
        box = [x1, y1, x2 + 1, y2 + 1]
        if frame_size and "w" in f and "h" in f:
            w, h = float(f["w"]), float(f["h"])
            if w > 0 and h > 0 and (w, h) != (float(frame_size[0]), float(frame_size[1])):
                sx, sy = frame_size[0] / w, frame_size[1] / h
                box = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
        try:
            score = float(f["c"]) if "c" in f else None
        except ValueError as exc:
            raise SamError(f"unreadable confidence in: {m.group(0)[:120]}") from exc
        records.append({"frame": frame, "id": int(m.group(2)), "box": [round(v, 3) for v in box],
                        "score": score})
    return records


def _from_sse(text: str) -> str:
    parts, completed = [], False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise SamError(f"unreadable stream event: {data[:120]}") from exc
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            parts.append(event.get("delta") or "")
        elif kind == "response.completed":
            completed = True
        elif kind in ("error", "response.failed", "response.incomplete"):
            raise SamError(f"sam-3.1 stream ended with {kind}: {json.dumps(event)[:300]}")
    if not completed:
        raise SamError("sam-3.1 stream ended without response.completed; the output may be partial")
    return "".join(parts)


def _from_response(doc: dict) -> str:
    if doc.get("error"):
        raise SamError(f"sam-3.1 error: {json.dumps(doc['error'])[:300]}")
    status = doc.get("status")
    if status not in (None, "completed"):
        raise SamError(f"sam-3.1 response status {status!r}; the output may be partial")
    if isinstance(doc.get("output_text"), str):
        return doc["output_text"]
    parts = []
    for item in doc.get("output") or []:
        for block in item.get("content") or []:
            if block.get("type") == "output_text":
                parts.append(block.get("text") or "")
    return "".join(parts)


def output_text(raw: bytes, content_type: str = "") -> str:
    """The model's output text from a Responses API reply, streamed (SSE) or not."""
    text = raw.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type or text.lstrip().startswith(("event:", "data:")):
        return _from_sse(text)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SamError(f"sam-3.1 reply is not JSON: {text[:120]!r}") from exc
    return _from_response(doc)


def request_body(prompt: str, image_url: str, model: str = MODEL) -> dict:
    """One concept prompt and one image, as the Responses API expects them."""
    return {
        "model": model,
        "stream": False,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_url},
        ]}],
        "metadata": dict(METADATA),
    }


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SamError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height)


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------------------------

class MetaSamClient:
    """Calls sam-3.1 once per (frame, prompt). ``transport`` is injectable for tests."""

    def __init__(self, *, model: str = MODEL, base: str | None = None, transport: Transport | None = None,
                 retries: int = 3, timeout: float = 120.0, sleep: Callable[[float], None] = time.sleep):
        self.model = model
        self.base = (base or API_BASE).rstrip("/")
        self._transport = transport or self._http
        self.retries, self.timeout, self._sleep = retries, timeout, sleep
        self.calls = 0
        self._lock = threading.Lock()

    def _http(self, body: dict) -> tuple[bytes, str]:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise SamError(f"set {KEY_ENV} to a Meta Model API key in your shell or the gitignored .env "
                           "(never commit it, never paste it into chat)")
        req = urllib.request.Request(
            f"{self.base}/responses", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")

    def _call(self, body: dict) -> tuple[bytes, str]:
        delay = 2.0
        for attempt in range(self.retries + 1):
            with self._lock:
                self.calls += 1
            try:
                return self._transport(body)
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:300]
                if err.code not in RETRY_STATUS or attempt == self.retries:
                    raise SamError(f"sam-3.1 HTTP {err.code}: {detail}") from err
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt == self.retries:
                    raise SamError(f"sam-3.1 unreachable after {attempt + 1} tries: {err}") from err
            self._sleep(delay)
            delay *= 2
        raise SamError("unreachable")  # pragma: no cover

    def segment(self, png: Path, prompt: str) -> list[dict]:
        """Every match for ``prompt`` in one frame: ``[{"box", "score"}]``, best first."""
        size = png_size(png)
        raw, content_type = self._call(request_body(prompt, data_url(png), self.model))
        detections = []
        for record in parse_output(output_text(raw, content_type), frame_size=size):
            if record["score"] is None:
                raise SamError("sam-3.1 returned a box without a confidence although the request asks "
                               "for one (metadata.include_confidence); a missing score is never guessed")
            detections.append({"box": record["box"], "score": max(0.0, min(1.0, record["score"]))})
        return sorted(detections, key=lambda d: (-d["score"], d["box"]))


# ---------------------------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------------------------

def default_cache_dir() -> Path | None:
    """Verifier-side state, outside the repo so the fixer's worktree never contains it.

    Under bwrap the fixer gets a fresh tmpfs HOME, so it cannot reach this either. With no OS
    sandbox (kind ``none``) nothing stops a host process from writing here; see docs/sam.md.
    """
    raw = os.environ.get(CACHE_ENV)
    if raw is not None:
        return None if raw.strip().lower() in ("", "off", "0", "none") else Path(raw).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "nightshift" / "sam"


class Cache:
    def __init__(self, root: Path | None):
        self.root = Path(root) if root else None
        self.hits = 0
        self._lock = threading.Lock()

    @staticmethod
    def key(frame_sha: str, prompt: str, model: str) -> str:
        parts = [REQUEST_VERSION, model, prompt, frame_sha, METADATA]
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> list[dict] | None:
        if self.root is None:
            return None
        try:
            doc = json.loads(self._path(key).read_text(encoding="utf-8"))
            detections = doc["detections"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        with self._lock:
            self.hits += 1
        return detections

    def put(self, key: str, detections: list[dict], meta: dict) -> None:
        if self.root is None:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"detections": detections, **meta}, fh)
        os.replace(tmp, path)


# ---------------------------------------------------------------------------------------------
# Which frames to look at
# ---------------------------------------------------------------------------------------------

def frame_files(frames_dir: Path) -> dict[int, Path]:
    """Movie Maker frames: f00000000.png, f00000001.png, ... keyed by frame number."""
    frames = {}
    for path in Path(frames_dir).glob("f*.png"):
        digits = path.stem[1:]
        if digits.isdigit():
            frames[int(digits)] = path
    return dict(sorted(frames.items()))


def window(available: list[int], spec: dict | None) -> list[int]:
    w = (spec or {}).get("window", {})
    lo, hi = w.get("fromFrame", 0), w.get("toFrame")
    return [i for i in available if i >= lo and (hi is None or i <= hi)]


def sample(indices: list[int], every: int) -> list[int]:
    """Every ``every``-th frame from the start of the window, plus its last frame."""
    if every <= 1 or not indices:
        return list(indices)
    start = indices[0]
    picked = [i for i in indices if (i - start) % every == 0]
    if indices[-1] not in picked:
        picked.append(indices[-1])
    return picked


def sampling_plan(spec: dict | None, every: int) -> int:
    """The sample rate this spec can safely use.

    never-crosses and inside-region fail on any failing frame, so sampling can only miss a
    failure. ``reaches`` can sample (a sampled frame that reaches is a real pass; a fail is
    re-checked on every frame). ``visible`` counts frames against a fraction, so it looks at
    every frame unless the fraction is 1.0.
    """
    if not spec:
        return every
    assertion = spec.get("assertion", {})
    kind = assertion.get("type")
    if kind in SAMPLE_SAFE or kind == "reaches":
        return every
    if kind == "visible" and float(assertion.get("minFraction", 1.0)) >= 1.0:
        return every
    return 1


def refine_targets(indices: list[int], looked: set[int], verdict: dict) -> list[int]:
    """Frames to add after a failing sampled verdict so the first failing frame is exact."""
    if verdict.get("result") != "fail":
        return []
    first = verdict.get("firstFrame")
    if first is None:  # e.g. "reaches": the moment may sit between two samples
        return [i for i in indices if i not in looked]
    before = [i for i in looked if i < first]
    previous = max(before) if before else indices[0] - 1
    return [i for i in indices if previous < i < first and i not in looked]


# ---------------------------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------------------------

def _prompts(spec: dict | None, prompts: dict | None) -> dict[str, str]:
    if spec and spec.get("objects"):
        return {name: obj["prompt"] for name, obj in spec["objects"].items()}
    return dict(prompts or DEFAULT_PROMPTS)


def observe(frames: dict[int, Path], indices: list[int], prompts: dict[str, str], client: MetaSamClient,
            cache: Cache, workers: int = DEFAULT_WORKERS) -> dict[int, dict]:
    """{frame: {object name: detections}} for the given frames, from the cache or SAM."""
    shas = {i: sha256_bytes(frames[i]) for i in indices}
    jobs = [(i, name) for i in indices for name in prompts]

    def run(job):
        i, name = job
        key = Cache.key(shas[i], prompts[name], client.model)
        detections = cache.get(key)
        if detections is None:
            detections = client.segment(frames[i], prompts[name])
            cache.put(key, detections, {"frameSha256": shas[i], "prompt": prompts[name], "model": client.model})
        return i, name, detections

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(run, jobs))
    observed: dict[int, dict] = {i: {} for i in indices}
    for i, name, detections in results:
        observed[i][name] = detections
    return observed


def _document(observed, prompts, model, replay_sha256, captured, in_window, every, refined) -> dict:
    return {
        "format": "nightshift.observations/v0",
        "replay": {"sha256": replay_sha256},
        "model": {"name": model, "provider": "meta-model-api", "prompts": dict(prompts)},
        "frames": [{"frame": i, "objects": {name: observed[i][name] for name in prompts}}
                   for i in sorted(observed)],
        # Deterministic given the same detections, so the document digest is stable run to run.
        "analysis": {"framesCaptured": captured, "framesInWindow": in_window,
                     "framesAnalyzed": len(observed), "every": every,
                     "refined": ({"frames": len(refined), "from": min(refined), "to": max(refined)}
                                 if refined else None)},
    }


def from_replay(
    trace: dict | None = None,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
    frames_dir: str | Path | None = None,
    *,
    spec: dict | None = None,
    prompts: dict[str, str] | None = None,
    every: int | None = None,
    refine: bool = True,
    client: MetaSamClient | None = None,
    cache: Cache | None = None,
    workers: int | None = None,
    stats: dict | None = None,
) -> dict:
    """nightshift.observations/v0 for one replay, from SAM 3.1. Matches the seam's signature.

    ``trace``, ``fps`` and ``physics_tps`` are accepted for the seam and unused: SAM looks at
    pixels only. ``spec`` supplies the prompts, the frame window and the assertion that decides
    whether sampling is safe and where to refine.
    """
    if frames_dir is None or not Path(frames_dir).is_dir():
        raise SamError("the sam provider needs the replay's captured frames (frames_dir)")
    frames = frame_files(Path(frames_dir))
    if not frames:
        raise SamError(f"no frames in {frames_dir}")
    client = client or MetaSamClient()
    cache = cache if cache is not None else Cache(default_cache_dir())
    workers = workers or int(os.environ.get(WORKERS_ENV, DEFAULT_WORKERS))
    rate = every or int(os.environ.get(EVERY_ENV, DEFAULT_EVERY))
    rate = sampling_plan(spec, max(1, rate))
    names = _prompts(spec, prompts)

    indices = window(list(frames), spec)
    if not indices:
        raise SamError("no captured frame falls inside the spec's window")
    observed = observe(frames, sample(indices, rate), names, client, cache, workers)
    refined: list[int] = []
    if refine and spec and rate > 1:
        doc = _document(observed, names, client.model, replay_sha256, len(frames), len(indices), rate, [])
        refined = refine_targets(indices, set(observed), evaluate(spec, doc))
        if refined:
            observed.update(observe(frames, refined, names, client, cache, workers))
    if stats is not None:
        stats.update(calls=client.calls, cacheHits=cache.hits, framesAnalyzed=len(observed),
                     framesCaptured=len(frames), every=rate, refined=len(refined))
    return _document(observed, names, client.model, replay_sha256, len(frames), len(indices), rate, refined)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    from nightshift.contracts import digest, load, validate

    p = argparse.ArgumentParser(description="SAM 3.1 observations for one replay, then the verdict.")
    p.add_argument("--run", type=Path, required=True, help="a harness run dir with frames/ and replay.json")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--every", type=int, help=f"look at every Nth frame (default {DEFAULT_EVERY})")
    p.add_argument("--no-refine", action="store_true")
    p.add_argument("--out", type=Path, help="default: <run>/observations-sam.json")
    args = p.parse_args(argv)
    load_dotenv()

    spec = load(args.spec, "test-spec")
    replay = args.run / "replay.json"
    stats: dict = {}
    try:
        doc = from_replay(
            replay_sha256=sha256_bytes(replay) if replay.is_file() else "0" * 64,
            frames_dir=args.run / "frames", spec=spec, every=args.every, refine=not args.no_refine,
            stats=stats)
    except SamError as exc:
        print(f"needs-review: {exc}", file=sys.stderr)
        return 2
    validate(doc, "observations")
    out = args.out or args.run / "observations-sam.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    verdict = evaluate(spec, doc)
    print(f"observations: {out} ({digest(doc)[:12]})")
    print(f"frames analyzed: {stats['framesAnalyzed']} of {stats['framesCaptured']} (every {stats['every']}, "
          f"{stats['refined']} refined); API calls {stats['calls']}, cache hits {stats['cacheHits']}")
    print(f"{verdict['result']}: {verdict['reason']}")
    return {"pass": 0, "fail": 1, "needs-review": 2}[verdict["result"]]


if __name__ == "__main__":
    sys.exit(main())
