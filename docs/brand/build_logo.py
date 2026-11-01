"""Build the Expectrail logo files (docs/brand/) from one construction: python3 docs/brand/build_logo.py

The mark, on a 64-unit grid: a rail 52 x 4 (the expectation), and resting on it a yellow frame 32 x 32
(a frame of the game, what Expectrail looks at). Inside the frame a telescope stands on the rail, on a
two-legged tripod, aimed up and to the right, toward the name: Expectrail watches. At small sizes the
telescope melts into the frame and the mark reads as a box resting on a rail, as before.

The wordmark: TeX Gyre Adventor Regular outlines (GUST Font License), x-height 24, tracking -0.006 em,
given weight with a 0.85-unit outline stroke. The dot of the i is a square, and the "ai" inside the name
is measured: coloured, with a short yellow rail under it. In the lockup the frame's top lines up with
the ascenders and its foot with the baseline, and the telescope looks along the word to the "ai".

Colours: ink #16133A, paper #F6F7FB, rail yellow #FFC928, stone #4B4178. On a dark ground the "ai" is
yellow; on a light ground it is stone, since yellow text on paper fails contrast. The telescope is ink in
both, because it sits on the yellow frame.
"""
import math
import os
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

INK, PAPER, RAIL, STONE = "#16133A", "#F6F7FB", "#FFC928", "#4B4178"
# TeX Gyre Adventor Regular, OpenType (texlive-fonts-recommended, or https://www.gust.org.pl/projects/e-foundry/tex-gyre)
REGULAR = os.environ.get("ADVENTOR_REGULAR_OTF",
                         "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreadventor-regular.otf")
OUT = Path(__file__).resolve().parent

BASELINE, XHEIGHT = 46, 24
STROKE = 0.85            # the wordmark's added weight
TRACKING_EM = -0.006     # -0.2633 units at this size
WORD_X = 72              # where the word starts in the lockup


def r(v: float) -> str:
    """Two decimals, no trailing zeros: the files stay small and diff cleanly."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def poly(points, fill):
    return f'<path d="M{"L".join(f"{r(x)} {r(y)}" for x, y in points)}Z" fill="{fill}"/>'


# ---------------------------------------------------------------- the mark
def telescope(bx: float, by: float, s: float, fill: str) -> str:
    """A telescope on a two-legged tripod, standing on the floor of a frame of side s at (bx, by)."""
    u = s / 32                                   # drawn on a 32-unit frame
    px, py = bx + 13 * u, by + 18.5 * u          # the mount
    floor = by + s
    out = ""
    for foot in (5.5, 20.5):                     # the legs, cut flat on the floor
        fx = bx + foot * u
        dx, dy = fx - px, floor - py
        n = math.hypot(dx, dy)
        ox, oy = -dy / n * 1.35 * u, dx / n * 1.35 * u      # half the leg's width, across it
        top = [(px + ox, py + oy), (px - ox, py - oy)]
        bottom = []
        for qx, qy in top:                       # each edge of the leg, run down to the floor
            t = (floor - qy) / dy
            bottom.append((qx + dx * t, floor))
        out += poly([top[0], top[1], bottom[1], bottom[0]], fill)
    out += f'<rect x="{r(px - 2.2 * u)}" y="{r(py - 1.6 * u)}" width="{r(4.4 * u)}" height="{r(3.6 * u)}" fill="{fill}"/>'
    a = math.radians(-30)                        # the tube, stepped like a spyglass, aimed up and right
    ax, ay = math.cos(a), math.sin(a)
    nx, ny = -ay, ax
    cx, cy = px + nx * -1.4 * u, py + ny * -1.4 * u          # the tube rides just above the mount
    for t0, t1, h in ((-11, -6.5, 3.4), (-6.5, 3, 5.2), (3, 13.5, 7.4)):
        hh = h * u / 2
        p0 = (cx + ax * t0 * u, cy + ay * t0 * u)
        p1 = (cx + ax * t1 * u, cy + ay * t1 * u)
        out += poly([(p0[0] + nx * hh, p0[1] + ny * hh), (p1[0] + nx * hh, p1[1] + ny * hh),
                     (p1[0] - nx * hh, p1[1] - ny * hh), (p0[0] - nx * hh, p0[1] - ny * hh)], fill)
    return out


def mark(rail_colour: str) -> str:
    return (f'<rect x="6" y="46" width="52" height="4" fill="{rail_colour}"/>'
            f'<rect x="16" y="14" width="32" height="32" fill="{RAIL}"/>' + telescope(16, 14, 32, INK))


# ---------------------------------------------------------------- the wordmark
def wordmark(text_colour: str, ai_colour: str, x0: float) -> str:
    font = TTFont(REGULAR)
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    k = XHEIGHT / font["OS/2"].sxHeight
    tracking = TRACKING_EM * k * 1000
    paths = {text_colour: "", ai_colour: ""}
    x, spans = x0, {}
    for ch in "expectrail":
        name = cmap[0x131] if ch == "i" else cmap[ord(ch)]    # a dotless i: its dot is a square
        pen = SVGPathPen(gs, ntos=r)
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x, BASELINE)))
        colour = ai_colour if ch in "ai" else text_colour
        paths[colour] += pen.getCommands()
        adv = hmtx[name][0] * k
        spans[ch] = (x, x + adv)
        x += adv + tracking
    out = "".join(f'<path d="{d}" fill="{c}" stroke="{c}" stroke-width="{STROKE}" stroke-linejoin="round"/>'
                  for c, d in paths.items() if d)
    # the i's stem, from its own outline, sets the dot and the end of the rail
    stem = _bounds(gs, cmap[0x131], k, spans["i"][0])
    a_left = _bounds(gs, cmap[ord("a")], k, spans["a"][0])[0]
    right = _bounds(gs, cmap[ord("l")], k, spans["l"][0])[1] + STROKE / 2
    half = STROKE / 2
    dot = stem[1] - stem[0] + STROKE
    out += f'<rect x="{r(stem[0] - half)}" y="{r(BASELINE - XHEIGHT - half - 2.24 - dot)}" width="{r(dot)}" height="{r(dot)}" fill="{RAIL}"/>'
    out += (f'<rect x="{r(a_left - half)}" y="49.2" width="{r(stem[1] + half - (a_left - half))}" height="2.4" '
            f'fill="{RAIL}"/>')
    return out, right


def _bounds(gs, name, k, ox):
    """A glyph's left and right ink edges, placed at ox."""
    from fontTools.pens.boundsPen import BoundsPen
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    x0, _, x1, _ = bp.bounds
    return ox + x0 * k, ox + x1 * k


# ---------------------------------------------------------------- files
def svg(body: str, view_box: str, desc: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" role="img" aria-labelledby="t d">'
            f'<title id="t">Expectrail</title><desc id="d">{desc}</desc>{body}</svg>\n')


MARK_DESC = "A telescope on a tripod inside a yellow frame that rests on a rail"
LOCKUP_DESC = MARK_DESC + ", beside the word expectrail with its a and i measured by a short yellow rail"


def build() -> dict[str, str]:
    files = {}
    files["expectrail-mark.svg"] = svg(mark(INK), "0 0 64 64", MARK_DESC)
    files["expectrail-mark-reverse.svg"] = svg(mark(PAPER), "0 0 64 64", MARK_DESC)
    # the app icon: the mark on an ink tile, a little larger so the frame fills it
    tile = (f'<rect width="64" height="64" rx="12" fill="{INK}"/>'
            f'<g transform="translate(32 33) scale(1.08) translate(-32 -32)">{mark(PAPER)}</g>')
    files["favicon.svg"] = svg(tile, "0 0 64 64", MARK_DESC)
    for name, text, ai, rail in (("expectrail-logo.svg", INK, STONE, INK),
                                 ("expectrail-logo-reverse.svg", PAPER, RAIL, PAPER)):
        word, end = wordmark(text, ai, WORD_X)
        files[name] = svg(mark(rail) + word, f"2 4 {r(end + 4 - 2)} 56", LOCKUP_DESC)
    return files


if __name__ == "__main__":
    written = build()
    for n, text in written.items():
        (OUT / n).write_text(text, encoding="utf-8")
    print({n: len(t) for n, t in written.items()})
