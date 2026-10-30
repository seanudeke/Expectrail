"""Replay a recorded session in a web app, the way harness/run.py replays a route in the game.

A web route (``expectrail.web-route/v0``) names the page, the viewport, the elements checks may name
(by CSS selector) and the steps a person takes: load, fill, select, check, click. The page is served
from a copy of the app (with any patches applied) under a fixed origin, nothing from the network,
in Chromium through Playwright with a fixed viewport, light colour scheme, reduced motion and no
CSS animations or transitions. After every step the harness saves the viewport as a frame
(``frames/f00000000.png``, the name the observers read) and a row of the layout log: for each named
element, its layout box (the CSS box layout computed, before any transform: what the page's layout
says, as the game engine's position log says where the robot is) and its painted box (after
transforms), and whether CSS shows it at all (display and visibility; opacity counts as shown, as in
Playwright's own visibility check). The last row also records what the session achieved: whether
the final click went through and the form was submitted.

    python3 -m harness.web.run --route harness/web/routes/checkout-desktop.json --out runs/web/clean
    python3 -m harness.web.run --route ... --out runs/web/v1 --patch bugs/web/layering/v1.patch

Outputs <out>/frames/, <out>/trace.json (expectrail.web-trace/v0) and <out>/replay.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from harness.run import REPO, game_env

APP_DIR = REPO / "apps" / "checkout" / "site"
ORIGIN = "http://checkout.test"
ROUTE_FORMAT = "expectrail.web-route/v0"
TRACE_FORMAT = "expectrail.web-trace/v0"
CLICK_TIMEOUT_MS = 3000
# The harness's own settings, not the app's: no animation, transition or blinking caret can make
# two replays of the same session differ.
STILL_CSS = ("*, *::before, *::after { transition: none !important; animation: none !important; "
             "caret-color: transparent !important; scroll-behavior: auto !important; }")
# Chromium switches for repeatable pixels: software raster on one thread, sRGB, no LCD text.
CHROMIUM_ARGS = ["--disable-gpu", "--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none",
                 "--disable-partial-raster", "--disable-threaded-animation", "--disable-threaded-scrolling",
                 "--disable-checker-imaging", "--disable-image-animation-resync", "--num-raster-threads=1",
                 "--run-all-compositor-stages-before-draw", "--disable-skia-runtime-opts", "--hide-scrollbars",
                 "--mute-audio"]
# Per element: the layout box (offset geometry, no transforms), the painted box (client rect, after
# transforms) and whether CSS shows it. Boxes are [x0, y0, x1, y1] in viewport pixels.
LAYOUT_JS = """
(selectors) => {
  const out = {};
  for (const [name, sel] of Object.entries(selectors)) {
    const el = document.querySelector(sel);
    if (!el) { out[name] = null; continue; }
    const cs = getComputedStyle(el);
    const shown = cs.display !== 'none' && cs.visibility !== 'hidden' && el.getClientRects().length > 0;
    let x = 0, y = 0, node = el;
    if (el instanceof HTMLElement) {
      while (node) { x += node.offsetLeft; y += node.offsetTop; node = node.offsetParent; }
      x -= window.scrollX; y -= window.scrollY;
    }
    const r = el.getBoundingClientRect();
    const w = el instanceof HTMLElement ? el.offsetWidth : r.width;
    const h = el instanceof HTMLElement ? el.offsetHeight : r.height;
    if (!(el instanceof HTMLElement)) { x = r.left; y = r.top; }
    out[name] = {shown, layout: [x, y, x + w, y + h].map(v => Math.round(v * 100) / 100),
                 painted: [r.left, r.top, r.right, r.bottom].map(v => Math.round(v * 100) / 100)};
  }
  return out;
}
"""


class WebHarnessError(RuntimeError):
    pass


def load_route(path: Path) -> dict:
    route = json.loads(Path(path).read_text(encoding="utf-8"))
    if route.get("format") != ROUTE_FORMAT:
        raise WebHarnessError(f"{path}: not an {ROUTE_FORMAT} file")
    for key in ("name", "page", "viewport", "elements", "steps"):
        if key not in route:
            raise WebHarnessError(f"{path}: missing {key}")
    return route


def prepare(app: Path, work: Path, patches: list[Path]) -> Path:
    """A copy of the app with the patches applied; the app in the repository is never touched."""
    site = work / "site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(app, site)
    for patch in patches:
        proc = subprocess.run(["patch", "-p1", "--forward", "--batch", "-d", str(site), "-i", str(Path(patch).resolve())],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise WebHarnessError(f"{patch} does not apply: {proc.stdout.strip()[-300:]} {proc.stderr.strip()[-300:]}")
    return site


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(route_path: Path, out: Path, patches: list[Path] | None = None, app: Path | None = None) -> dict:
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright

    route = load_route(route_path)
    patches = list(patches or [])
    out.mkdir(parents=True, exist_ok=True)
    site = prepare(app or APP_DIR, out / "work", patches)
    frames = out / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir()
    width, height = route["viewport"]
    rows: list[dict] = []
    outcome = {"submitted": False, "fields": {}, "error": None}

    def serve(request_route):
        parts = urlsplit(request_route.request.url)
        if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
            request_route.abort()  # nothing leaves the machine
            return
        path = (site / parts.path.lstrip("/")).resolve()
        if site.resolve() not in path.parents or not path.is_file():
            request_route.fulfill(status=404, body="not found")
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        request_route.fulfill(status=200, body=path.read_bytes(), headers={"content-type": mime})

    with sync_playwright() as p:
        # The page's scripts are the candidate's code: Chromium gets the game's environment allowlist,
        # not the verifier's (no model key, no held-out path), and nothing outside the page's origin.
        browser = p.chromium.launch(args=CHROMIUM_ARGS, env=game_env())
        context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                      color_scheme="light", reduced_motion="reduce", locale="en-US",
                                      timezone_id="UTC", java_script_enabled=True)
        context.route("**/*", serve)
        context.add_init_script("document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); "
                                f"s.textContent = {json.dumps(STILL_CSS)}; document.head.appendChild(s); }});")
        page = context.new_page()

        def snapshot(step: dict) -> None:
            n = len(rows)
            page.screenshot(path=str(frames / f"f{n:08d}.png"), full_page=False, animations="disabled",
                            caret="hide")
            rows.append({"frame": n, "step": step.get("do"), "target": step.get("target"),
                         "url": page.url.replace(ORIGIN, ""), "elements": page.evaluate(LAYOUT_JS, route["elements"])})

        def locate(target: str):
            return page.locator(route["elements"].get(target, target)).first

        try:
            for step in route["steps"]:
                kind = step["do"]
                if kind == "load":
                    page.goto(f"{ORIGIN}/{route['page']}", wait_until="load")
                elif kind == "fill":
                    locate(step["target"]).fill(step["value"], timeout=CLICK_TIMEOUT_MS)
                elif kind == "select":
                    locate(step["target"]).select_option(label=step["value"], timeout=CLICK_TIMEOUT_MS)
                elif kind == "check":
                    locate(step["target"]).check(timeout=CLICK_TIMEOUT_MS)
                elif kind == "click":
                    before = page.url
                    try:
                        if step.get("submits"):
                            with page.expect_navigation(timeout=CLICK_TIMEOUT_MS, wait_until="load"):
                                locate(step["target"]).click(timeout=CLICK_TIMEOUT_MS)
                        else:
                            locate(step["target"]).click(timeout=CLICK_TIMEOUT_MS)
                    except PlaywrightTimeout as exc:
                        # The click never landed (something covers the target) or nothing was submitted.
                        outcome["error"] = f"click on {step['target']} did not go through: " + str(exc).splitlines()[0]
                    if step.get("submits") and page.url != before and "?" in page.url:
                        outcome["submitted"] = True
                        outcome["fields"] = {k: v[0] for k, v in parse_qs(urlsplit(page.url).query).items()}
                else:
                    raise WebHarnessError(f"unknown step {kind!r}")
                snapshot(step)
        except PlaywrightError as exc:
            outcome["error"] = outcome["error"] or f"{type(exc).__name__}: " + str(exc).splitlines()[0]
            snapshot({"do": "error"})
        finally:
            browser.close()

    trace = {"format": TRACE_FORMAT, "route": route["name"], "viewport": [width, height], "rows": rows,
             "outcome": outcome}
    (out / "trace.json").write_text(json.dumps(trace, indent=1) + "\n", encoding="utf-8")
    frame_hashes = [_sha256(f) for f in sorted(frames.glob("f*.png"))]
    replay = {"format": "expectrail.web-replay/v0", "route": {"name": route["name"], "sha256": _sha256(route_path)},
              "app": {"name": "checkout", "patches": [{"file": Path(p).name, "sha256": _sha256(p)} for p in patches]},
              "engine": {"name": "chromium", "playwright": _playwright_version()},
              "capture": {"frames": len(frame_hashes), "viewport": [width, height]},
              "frameSha256": hashlib.sha256("".join(frame_hashes).encode()).hexdigest(),
              "trace": {"rows": len(rows), "outcome": outcome}}
    (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    return replay


def _playwright_version() -> str:
    from importlib.metadata import version

    return version("playwright")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--patch", type=Path, action="append", default=[])
    p.add_argument("--app", type=Path, help=f"the app's site directory (default {APP_DIR.relative_to(REPO)})")
    args = p.parse_args(argv)
    try:
        replay = run(args.route, args.out, args.patch, args.app)
    except WebHarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    t = replay["trace"]
    print(f"{replay['capture']['frames']} frames; submitted={t['outcome']['submitted']}; frames sha256 {replay['frameSha256'][:16]}")
    if t["outcome"]["error"]:
        print(f"note: {t['outcome']['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
