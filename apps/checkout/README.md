# Checkout: the second domain

Expectrail's anchor is the Godot game. This app is supporting evidence that the same verifier carries
over to software that is not a game: a web checkout page, judged by the same evaluator, the same SAM
3.1 observer and the same verdict logic, with only a new harness adapter
([`harness/web/`](../../harness/web)): Chromium, driven by Playwright, replays a shopper's session
as Godot replays a route, and the page's layout log stands in for the engine's position log.

| Path | What |
| --- | --- |
| `site/` | Bootstrap's Checkout example and the Bootstrap files it loads, unmodified (prior work, MIT; see NOTICE) |
| `bugs/<family>/vN.patch` | Seeded bugs, two public development variants per family, written for the event |
| `specs/` | The checks, one sentence each (drafted for review; a person approves each, as for the game) |

`site/` is copied from `bootstrap-5.3.8-examples.zip` (Bootstrap v5.3.8 release; zip sha256
`b851efe3b1589a4487c44a6b55671bbba54abb7740673be9c47a1e271ead1782`): `checkout/index.html`,
`checkout/checkout.css`, `checkout/checkout.js`, `assets/dist/css/bootstrap.min.css`,
`assets/dist/js/bootstrap.bundle.min.js`, `assets/brand/bootstrap-logo.svg` and
`assets/js/color-modes.js`. No file in it is changed; seeded bugs and fixes are patches.

## The four bug families, on a web page

The families are the game's, so the same question is asked of each: which kind of evidence sees it.

| Family | Variant | What the patch does | Seen by |
| --- | --- | --- | --- |
| Layering | v1 | A promo bar slides up over the checkout button and takes its clicks | behaviour, vision |
| Layering | v2 | The same bar covers the button but lets clicks through: a script can click it, a shopper cannot see it | vision only |
| Missing texture | v1 | The logo's path has a typo, so it never loads; its box keeps its size | vision only |
| Missing texture | v2 | The primary button's colours go transparent: there and clickable, nothing drawn | vision only |
| Fall-through | v1 | A spacing change pushes the checkout button off the bottom of the screen | layout, vision |
| Fall-through | v2 | The button is positioned absolutely, above the top of the page | layout, behaviour, vision |
| Sinking | v1 | The button is nudged down with relative positioning, half outside the form | layout, vision |
| Sinking | v2 | The button is drawn lower with a transform; its layout slot does not move | vision only |

"Seen by" is what the patch was written to test; the measured results are in `bench/web/`.
