# Web judge benchmark

Written by `python3 -m agents.web_judge collect` from the run's own annotations; do not edit by hand.
Run [41104434739](https://github.com/seanudeke/Expectrail/actions/runs/41104434739), 2026-10-30, commit f3851da. Each case judged on the desktop and phone checkout sessions.

| Judge | Good changes accepted | Bad fixes accepted | Undecided |
| --- | --- | --- | --- |
| Expectrail, SAM on | 5 of 5 | 0 of 5 | 0 |
| Expectrail, SAM off | 5 of 5 | 3 of 5 | 0 |
| Pixel diff vs clean | 1 of 5 | 0 of 5 | 0 |

| Case | Right answer | Expectrail, SAM on | Expectrail, SAM off | Pixel diff vs clean | Failing checks |
| --- | --- | --- | --- | --- | --- |
| good/correct-fix: Any correct fix: it restores the clean page byte for byte | accept | accept | accept | accept | none |
| good/intended-shipping-note: Adds a free-shipping note under the total, as asked | accept | accept | accept | reject | none |
| good/intended-promo-bar: Adds a promo bar above the button, clear of it, as asked | accept | accept | accept | reject | none |
| good/intended-place-order: Renames the button to Place order, as asked | accept | accept | accept | reject | none |
| good/fix-layering-move-bar-below: Muse Code's live fix: moves the covering bar below the button | accept | accept | accept | reject | none |
| bad/fix-layering-hide-bar: Makes the covering bar transparent; it still takes the click | reject | reject | reject | reject | behaviour |
| bad/fix-layering-click-through: Lets clicks through the bar; it still covers the button | reject | reject | accept | reject | checkout-button-visible |
| bad/fix-logo-remove: Hides the broken logo instead of fixing its path (the hidden attribute; its box stays) | reject | reject | accept | reject | logo-visible |
| bad/fix-button-text-only: Restores the button's label, not the button | reject | reject | accept | reject | checkout-button-visible |
| bad/fix-button-pinned-top: Pins the off-screen button to the top of the window, outside the form | reject | reject | reject | reject | checkout-button-visible, layout |
