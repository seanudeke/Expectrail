# The Expectrail identity

![The Expectrail brand sheet](expectrail-brand-sheet.png)

**One idea: the AI, measured.** The name already holds it. Inside expectrail, the "ai" is picked out.
Its dot is a square, which is the observation: what Expectrail saw. A yellow rail runs under it, which
is the expectation it is measured against. Nothing else is needed, so nothing else is drawn.

- **The logo is the word.** It has no symbol beside it, because the word already carries the idea, and
  a second mark would only repeat it or compete with it.
- **The icon is the idea, close up.** It's the same "ai", magnified and cropped by an ink tile. The a
  and its rail run off the left edge, as if the word were seen through a lens. Cropped, it reads as a
  detail of the name. It never reads as two letters centred on a badge, which is Adobe Illustrator's
  icon.

## How it was judged

The identity was checked against the standards the leading identity designers use:

- a mark should be appropriate, distinctive and simple, and never generic or complicated (Sagi Haviv,
  Chermayeff & Geismar & Haviv);
- the principal role of a logo is to identify, and simplicity is its means (Paul Rand).

Candidates that failed were retired:

- **The corner bracket:** it added a second idea to explain.
- **A telescope:** it was generic, with a slightly wrong meaning (far away, not close up), and it was
  lost at 16 px.
- **A square resting on a rail:** in one colour it reads as a top hat.
- **An "ai" centred on a tile:** it's too close to Adobe Illustrator's icon.

The measured "ai" passes every test:

- it's appropriate, because the product checks AI's work against an expectation;
- it's distinctive, because no other name holds its own subject;
- it's simple enough to sketch from memory;
- it holds at 16 px and in one colour.

## Files

| File | Use |
| --- | --- |
| [`expectrail-logo.svg`](expectrail-logo.svg) | The logo on paper or any light ground |
| [`expectrail-logo-reverse.svg`](expectrail-logo-reverse.svg) | The logo on ink or any dark ground |
| [`expectrail-icon.svg`](expectrail-icon.svg) | The icon: app icons, avatars, social cards |
| [`favicon.svg`](favicon.svg) | The same icon, for the site's tab |
| [`expectrail-icon-square.svg`](expectrail-icon-square.svg) | The icon without rounded corners, for platforms that round it themselves (iOS) |
| [`png/`](png) | The logos at 1200 px wide and the icon at 512 px, transparent |
| [`expectrail-brand-sheet.png`](expectrail-brand-sheet.png) | The identity on one image, for slides and the video |

The SVGs are built by [`build_logo.py`](build_logo.py) from one construction. Edit that, not the SVGs.
The PNGs, the brand sheet, and the site's Open Graph image and touch icon are rendered from the SVGs
in Chromium, so re-render them after any change.

The script needs `fontTools` and the TeX Gyre Adventor Regular OpenType file. Set
`ADVENTOR_REGULAR_OTF` if it isn't at the TeX Live path.

## Construction

**The word**
- TeX Gyre Adventor Regular outlines, at an x-height of 24 units.
- Tracked -0.006 em.
- Given weight with a 0.85-unit outline stroke.
- The i is the dotless glyph, and its dot is a square as wide as the i's stem, including the stroke.

**The rail**
- 2.4 units thick and 3.2 below the baseline.
- It runs from the a's left edge to the i's right edge, and under no other letter.

**The icon**
- The same a and dotless i at an x-height of 33 on a 64-unit tile, with a heavier 2.3-unit stroke so
  it holds at 16 px.
- The i sits 17 units in from the right edge, so the a runs off the left.
- The rail is 3.8 thick and runs from the left edge to the i's right edge.

## Colour

| Name | Hex | Use |
| --- | --- | --- |
| Ink | `#16133A` | The word on light grounds, the icon's tile, dark panels |
| Rail | `#FFC928` | The rail and the dot always, the "ai" on dark grounds and in the icon, Expectrail's own results |
| Paper | `#F6F7FB` | The page, and the word on dark grounds |
| Stone | `#4B4178` | The "ai" on light grounds, and secondary text |
| Pass | `#157F4E` | "Accepted" verdicts only |
| Fail | `#C2303A` | "Rejected" verdicts only |

Contrast ratios:

| Pair | Ratio |
| --- | --- |
| Ink on paper | 16.5:1 |
| Stone on paper | 8.4:1 |
| Rail on ink, as in the icon and the dark logo | 11.5:1 |
| White on pass | 5.0:1 |
| White on fail | 5.6:1 |
| Rail on paper | 1.4:1 |

Rail on paper is too faint for text, so on a light ground yellow is only ever a shape or an underline.

## Use

- **Clear space:** the x-height, on every side.
- **Minimum size:** the logo should be at least 20 px tall on screen. Below that, use the icon.
- **Type:** TeX Gyre Adventor for headings, labels and numbers, in sentence case, and Lora for
  reading. Both are self-hosted on the site with their licences
  ([`../assets/fonts/`](../assets/fonts/README.md)).

**Don't:**
- put the icon beside the word;
- centre the "ai" in a tile, or uncrop the icon;
- make the "ai" yellow on a light ground, or use the light logo on a dark one;
- move the rail under other letters, or round the dot;
- set the word in a live font.

Retired on October 31: the bracket mark, and the frame-and-telescope icon.
