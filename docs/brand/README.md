# The Expectrail mark

![The Expectrail brand sheet](expectrail-brand-sheet.png)

**A telescope in a frame on a rail.** Expectrail plays the game and watches each frame, measured
against the line a fix must keep to. The name carries its subject too: the "ai" inside expectrail is
measured.

- **The rail** is the expectation: the floor a fix must keep the robot above, the line every check is
  measured against.
- **The frame** is a frame of the game, what Expectrail looks at. It rests on the rail, which is what
  passing looks like.
- **The telescope** is watching. It stands on the rail inside the frame and looks up the word,
  toward the "ai".
- **The measured "ai"** has a short yellow rail under the a and i, and a square for the dot: the AI's
  work, checked against a line.

The wordmark is `expectrail` in lower case. It is drawn from TeX Gyre Adventor Regular outlines at an
x-height of 24 units, tracked -0.006 em, and given weight with a 0.85-unit outline stroke. In the
lockup, the frame's top lines up with the ascenders and its foot with the baseline.

At small sizes the telescope melts into the frame, and the mark reads as a box resting on a rail.
That is by design.

## Files

| File | Use |
| --- | --- |
| [`expectrail-logo.svg`](expectrail-logo.svg) | The lockup, on paper or any light ground |
| [`expectrail-logo-reverse.svg`](expectrail-logo-reverse.svg) | The lockup on ink or any dark ground |
| [`expectrail-mark.svg`](expectrail-mark.svg), [`expectrail-mark-reverse.svg`](expectrail-mark-reverse.svg) | The mark alone, where the name is already said |
| [`favicon.svg`](favicon.svg) | The mark on an ink tile: browser tabs, app icons, avatars |
| [`png/`](png) | The same at 1200 px (lockups) and 512 px (mark, app icon), transparent |
| [`expectrail-brand-sheet.png`](expectrail-brand-sheet.png) | The mark, its construction, colours and use as one image, for slides and the video |

The SVGs are built by [`build_logo.py`](build_logo.py) from one construction. Edit that, not the SVGs.
The PNGs, the brand sheet, the site's Open Graph image and its touch icon were rendered from the SVGs
in Chromium, so re-render them after any change. The script needs `fontTools` and the TeX Gyre
Adventor Regular OpenType file; set `ADVENTOR_REGULAR_OTF` if it isn't at the TeX Live path.

## Construction

The mark is drawn on a 64-unit grid:

- **The rail** is 52 × 4, at y 46.
- **The frame** is 32 × 32, from (16, 14), resting on the rail.
- **The telescope** is drawn on the frame's own 32-unit grid:
  - The mount is at (13, 18.5).
  - The two legs run from the mount to the floor at x 5.5 and 20.5, 2.7 wide, and are cut flat on the
    rail.
  - The tube has three steps (3.4, 5.2 and 7.4 thick), aimed 30° above level, toward the word.

In the lockup, the word starts at x 72 with its baseline on the rail's top edge. The "ai" rail is 2.4
thick, 3.2 below the baseline, and spans the a's left edge to the i's right edge. The i's dot is a
square as wide as the i's stem, with its outline stroke.

## Colour

| Name | Hex | Use |
| --- | --- | --- |
| Ink | `#16133A` | Text, the rail on light grounds, the telescope always, dark panels |
| Rail | `#FFC928` | The frame, the "ai" rail and dot, the "ai" on dark grounds, Expectrail's own results |
| Paper | `#F6F7FB` | The page; the rail and the word on dark grounds |
| Stone | `#4B4178` | The "ai" on light grounds; secondary text |
| Pass | `#157F4E` | "Accepted" verdicts only |
| Fail | `#C2303A` | "Rejected" verdicts only |

Contrast ratios:

| Pair | Ratio |
| --- | --- |
| Ink on paper | 16.5:1 |
| Stone on paper | 8.4:1 |
| Ink on rail (the telescope on the frame) | 11.5:1 |
| White on pass | 5.0:1 |
| White on fail | 5.6:1 |
| Rail on paper | 1.4:1 |

Because rail on paper is only 1.4:1, yellow on a light ground is a shape or an underline, never text.
On a light ground the "ai" is stone for that reason.

## Use

- **Clear space:** half the frame's height on every side.
- **Minimum size:** the lockup is 24 px tall on screen. Below that, use the mark or the favicon.
- **Type:** TeX Gyre Adventor for headings, labels and numbers, in sentence case, and Lora for
  reading. Both are self-hosted on the site with their licences
  ([`../assets/fonts/`](../assets/fonts/README.md)).

Don't:

- recolour the frame, or make the telescope anything but ink;
- lift the frame off the rail, rotate the mark, or turn the telescope away from the word;
- set the wordmark in a live font;
- make the "ai" yellow on a light ground, or put the positive logo on a dark one.

The bracket mark used before October 31 is retired.
