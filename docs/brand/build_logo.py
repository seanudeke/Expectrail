"""Build the Expectrail logo files (docs/brand/) from one construction: python3 docs/brand/build_logo.py

Mark on a 64-unit grid (u = 4): a rail 56 x 5 (the expectation), a box 24 x 24 resting on it (what
was observed), and one corner bracket 12-unit arms, 5 thick, 4 clear of the box (it was seen and
measured). Wordmark: TeX Gyre Adventor Bold outlines (GUST Font License), the i's dot replaced by a
square the colour of the box. In the lockup the box is one x-height tall and sits on the word's
baseline, so the box reads as a letter-sized object on the same line as the word.
"""
import os
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

def text_path(font_path, text, size=100, tracking=0, x=0, y=0, kern=True, skip_dot_i=False):
    f = TTFont(font_path)
    gs = f.getGlyphSet()
    cmap = f.getBestCmap()
    upm = f["head"].unitsPerEm
    s = size / upm
    hmtx = f["hmtx"]
    pen = SVGPathPen(gs)
    cx = x
    boxes = {}
    for ch in text:
        gname = cmap[ord(ch)]
        if skip_dot_i and ch == "i":
            gname = cmap.get(0x0131, gname)  # dotless i
        t = TransformPen(pen, (s, 0, 0, -s, cx, y))
        gs[gname].draw(t)
        adv = hmtx[gname][0] * s
        boxes.setdefault(ch, []).append((cx, adv))
        cx += adv + tracking
    return pen.getCommands(), cx - x - tracking, boxes, f


INK, PAPER, RAIL, STONE = "#16133A", "#F6F7FB", "#FFC928", "#4B4178"
# TeX Gyre Adventor Bold, OpenType (texlive-fonts-recommended, or https://www.gust.org.pl/projects/e-foundry/tex-gyre)
ADV = os.environ.get("ADVENTOR_BOLD_OTF", "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreadventor-bold.otf")
OUT = Path(__file__).resolve().parent
DY = 2  # centre the mark vertically in its 64 box

def mark_parts(ink, box, dy=DY):
    rail = f'<rect x="4" y="{44+dy}" width="56" height="5" fill="{ink}"/>'
    b = f'<rect x="24" y="{20+dy}" width="24" height="24" fill="{box}"/>'
    x0, y0, t, a = 15, 11 + dy, 5, 12
    br = f'<path d="M{x0} {y0}H{x0+a}V{y0+t}H{x0+t}V{y0+a}H{x0}Z" fill="{ink}"/>'
    return rail + b + br

def wrap(inner, vb, title, w=None, h=None):
    size = f' width="{w}" height="{h}"' if w else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"{size} role="img" aria-label="{title}">'
            f'<title>{title}</title>{inner}</svg>\n')

def wordmark(color, tittle, x, baseline, xheight):
    f_size = xheight / 0.554
    d, width, boxes, f = text_path(ADV, "expectrail", f_size, -0.03 * f_size, x=x, y=baseline, skip_dot_i=True)
    gs = f.getGlyphSet(); g = f.getBestCmap()[0x131]
    bp = BoundsPen(gs); gs[g].draw(bp); xmin, ymin, xmax, ymax = bp.bounds
    s = f_size / 1000
    out = f'<path d="{d}" fill="{color}"/>'
    for (cx, adv) in boxes["i"]:
        sw = (xmax - xmin) * s
        out += f'<rect x="{cx + xmin*s:.2f}" y="{baseline - xheight - sw*1.55:.2f}" width="{sw:.2f}" height="{sw:.2f}" fill="{tittle}"/>'
    return out, width

files = {}
files["expectrail-mark.svg"] = wrap(mark_parts(INK, RAIL), "0 0 64 64", "Expectrail")
files["expectrail-mark-reverse.svg"] = wrap(mark_parts(PAPER, RAIL), "0 0 64 64", "Expectrail")
# favicon: the mark on an ink tile, readable in light and dark tabs
files["favicon.svg"] = wrap(f'<rect width="64" height="64" rx="12" fill="{INK}"/>' + mark_parts(PAPER, RAIL), "0 0 64 64", "Expectrail")

# lockup: box (24) = x-height, baseline = rail top (y 46)
for name, ink in (("expectrail-logo.svg", INK), ("expectrail-logo-reverse.svg", PAPER)):
    wm, ww = wordmark(ink, RAIL, 72, 44 + DY, 24)
    width = 72 + ww + 4
    files[name] = wrap(mark_parts(ink, RAIL) + wm, f"0 6 {width:.1f} 52", "Expectrail")
for n, svg in files.items():
    open(f"{OUT}/{n}", "w").write(svg)
print({n: len(s) for n, s in files.items()})
