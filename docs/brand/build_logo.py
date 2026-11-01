"""Build the Expectrail logo files (docs/brand/) from one construction: python3 docs/brand/build_logo.py

One idea: the AI, measured. The name already holds it: the "ai" inside expectrail is coloured, its dot is a
square (the observation), and a short yellow rail runs under it (the expectation it is measured against).
The logo is the wordmark alone. The icon, for favicons, app icons and avatars, is that "ai" seen close
up: magnified and cropped by an ink tile, so it reads as a detail of the word, never as two letters
centred on a badge (which is Adobe Illustrator's icon).

The wordmark: TeX Gyre Adventor Regular outlines (GUST Font License), x-height 24, tracking -0.006 em,
given weight with a 0.85-unit outline stroke. The icon: the same a and dotless i at x-height 33 on a
64-unit tile, with a heavier 2.3-unit stroke so it holds at 16 px.

Colours: ink #16133A, paper #F6F7FB, rail yellow #FFC928, stone #4B4178. On a dark ground the "ai" is
yellow; on a light ground it is stone, since yellow text on paper fails contrast. The rail and the dot are
yellow on both. The icon is always yellow on ink.
"""
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
WORD_X = 4               # the word's origin; the e's ink starts 1.84 units in


def r(v: float) -> str:
    """Two decimals, no trailing zeros: the files stay small and diff cleanly."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def poly(points, fill):
    return f'<path d="M{"L".join(f"{r(x)} {r(y)}" for x, y in points)}Z" fill="{fill}"/>'


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
        spans.setdefault(ch, (x, x + adv))          # the first e, for the left edge
        x += adv + tracking
    out = "".join(f'<path d="{d}" fill="{c}" stroke="{c}" stroke-width="{STROKE}" stroke-linejoin="round"/>'
                  for c, d in paths.items() if d)
    # the i's stem, from its own outline, sets the dot and the end of the rail
    stem = _bounds(gs, cmap[0x131], k, spans["i"][0])
    a_left = _bounds(gs, cmap[ord("a")], k, spans["a"][0])[0]
    right = _bounds(gs, cmap[ord("l")], k, spans["l"][0])[1] + STROKE / 2
    left = _bounds(gs, cmap[ord("e")], k, spans["e"][0])[0] - STROKE / 2
    half = STROKE / 2
    dot = stem[1] - stem[0] + STROKE
    out += f'<rect x="{r(stem[0] - half)}" y="{r(BASELINE - XHEIGHT - half - 2.24 - dot)}" width="{r(dot)}" height="{r(dot)}" fill="{RAIL}"/>'
    out += (f'<rect x="{r(a_left - half)}" y="49.2" width="{r(stem[1] + half - (a_left - half))}" height="2.4" '
            f'fill="{RAIL}"/>')
    return out, left, right


def _bounds(gs, name, k, ox):
    """A glyph's left and right ink edges, placed at ox."""
    from fontTools.pens.boundsPen import BoundsPen
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    x0, _, x1, _ = bp.bounds
    return ox + x0 * k, ox + x1 * k


# ---------------------------------------------------------------- the icon
def icon(rounded: bool = True) -> str:
    """The measured "ai", magnified and cropped by an ink tile: the a runs off the left edge and so does
    its rail, as if the word were seen close up. Yellow on ink, the dark logo's "ai" exactly."""
    xh, stroke, right_pad, base, rail_gap, rail_h = 33, 2.3, 17, 47, 4, 3.8
    font = TTFont(REGULAR)
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    k = xh / font["OS/2"].sxHeight
    names = [cmap[ord("a")], cmap[0x131]]
    gap = TRACKING_EM * k * 1000 + hmtx[names[0]][0] * k             # the i's origin, as in the word
    i_l, i_r = _bounds(gs, names[1], k, gap)
    half = stroke / 2
    dot = i_r - i_l + stroke
    ox = 64 - right_pad - (i_r + half)                                 # the i, a fixed distance from the right
    d = ""
    for name, x in zip(names, (0, gap)):
        pen = SVGPathPen(gs, ntos=r)
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, ox + x, base)))
        d += pen.getCommands()
    tile = f'<rect width="64" height="64"{' rx="12"' if rounded else ''}/>'
    return (f'<defs><clipPath id="tile">{tile}</clipPath></defs><g clip-path="url(#tile)">'
            f'<rect width="64" height="64" fill="{INK}"/>'
            f'<path d="{d}" fill="{RAIL}" stroke="{RAIL}" stroke-width="{stroke}" stroke-linejoin="round"/>'
            f'<rect x="{r(ox + i_l - half)}" y="{r(base - xh - half - xh * 0.093 - dot)}" width="{r(dot)}" '
            f'height="{r(dot)}" fill="{RAIL}"/>'
            f'<rect x="0" y="{r(base + rail_gap)}" width="{r(ox + i_r + half)}" height="{rail_h}" fill="{RAIL}"/></g>')


# ---------------------------------------------------------------- files
def svg(body: str, view_box: str, desc: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" role="img" aria-labelledby="t d">'
            f'<title id="t">Expectrail</title><desc id="d">{desc}</desc>{body}</svg>\n')


LOGO_DESC = "The word expectrail, its a and i measured by a short yellow rail, with a square dot"
ICON_DESC = "A close-up of the a and i from expectrail, measured by a yellow rail, with a square dot"


def build() -> dict[str, str]:
    files = {}
    for name, text, ai in (("expectrail-logo.svg", INK, STONE), ("expectrail-logo-reverse.svg", PAPER, RAIL)):
        word, left, right = wordmark(text, ai, WORD_X)
        files[name] = svg(word, f"{r(left - 4)} 9 {r(right - left + 8)} 50", LOGO_DESC)
    files["expectrail-icon.svg"] = svg(icon(), "0 0 64 64", ICON_DESC)
    files["favicon.svg"] = files["expectrail-icon.svg"]
    files["expectrail-icon-square.svg"] = svg(icon(rounded=False), "0 0 64 64", ICON_DESC)  # iOS rounds it itself
    return files


if __name__ == "__main__":
    written = build()
    for n, text in written.items():
        (OUT / n).write_text(text, encoding="utf-8")
    print({n: len(t) for n, t in written.items()})
