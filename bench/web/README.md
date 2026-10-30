# Second domain: the checkout page

Results for the web checkout page ([`apps/checkout`](../../apps/checkout)), the same verifier on a
second kind of software. Every number is written from a CI run's own annotations.

| File | What it is | Written by |
| --- | --- | --- |
| [`detection/`](detection/README.md) | Would each seeded bug be caught, with and without SAM | `python3 -m agents.bench_collect --app checkout --run <id> --out bench/web/detection` |
| [`judge.md`](judge.md), `judge.json` | Who accepts a change that only looks right: Expectrail with and without SAM, and a pixel diff | `python3 -m agents.web_judge collect --run <id>` |

## How the vision check was chosen

The prompts are tuned on the same development bugs they are measured on. These are the runs that
tuned them, in order, including the tuning that failed, so the result can be checked.

1. **First detection run, prompts "blue button" and "purple logo"** ([41083893650](https://github.com/seanudeke/Expectrail/actions/runs/41083893650)).
   - It caught 8 of 8, with no false alarm.
   - But on the five bugs that hide or cover the button, or push it off screen, "button visible"
     failed on one session and passed on the other. On the broken logo, "logo visible" did the same.
2. **Diagnostic run** ([41086075943](https://github.com/seanudeke/Expectrail/actions/runs/41086075943)).
   Each session's detail line shows SAM's best box next to where the page drew the element.
   - On the phone, with the real button hidden, "blue button" matched the cart's count badge at
     0.73 to 0.76, and the theme toggle at 0.75. The real button scores 0.78.
   - On the desktop, with the logo broken, "purple logo" matched the purple theme toggle at 0.66.
   - So those checks passed with the element gone.
3. **First attempt: a threshold** ([41087329108](https://github.com/seanudeke/Expectrail/actions/runs/41087329108), [41087757081](https://github.com/seanudeke/Expectrail/actions/runs/41087757081), [41088369464](https://github.com/seanudeke/Expectrail/actions/runs/41088369464)).
   - A prompt probe chose "full-width blue button" at minScore 0.71, which sat between the
     distractors (up to 0.65) and the button (0.75 or more) on the bugs. "purple B logo" scored the
     logo 0.89 and nothing else.
   - Detection then looked right: 8 of 8, every failing check on both sessions, no false alarm.
4. **The threshold rejected a correct fix** ([41097183557](https://github.com/seanudeke/Expectrail/actions/runs/41097183557), [41099231676](https://github.com/seanudeke/Expectrail/actions/runs/41099231676)).
   - The first live repair was layering v2. Muse Code moved the covering bar below the button,
     which is a correct fix. All three attempts were rejected.
   - The per-attempt detail showed why: on the phone, SAM found the button exactly where the page
     drew it, but scored it 0.56 with the bar just below it. That is under 0.71, so "button
     visible" failed on the phone and on the private sessions.
   - A threshold tuned on the bugs alone had no room for a correct page that looks a little
     different.
5. **Second attempt: agreement with the page** ([41102997087](https://github.com/seanudeke/Expectrail/actions/runs/41102997087)).
   - The probe was rerun on three frames a session, now including Muse's fix and the judge's
     intended changes, and scored each prompt two ways:
     - SAM alone: any match counts.
     - In agreement with the page: only a SAM box on the page's own paint box for the element
       counts.
   - **Alone, no button prompt is safe.** The badge and the toggle score as high as a correct
     fix's button on the phone.
   - **In agreement, "blue checkout button" is safe at the default minScore of 0.5.** It found the
     drawn button on all 30 frames (lowest 0.65). On the box of a covered, transparent or
     off-screen button, it found nothing.
   - "Continue to checkout button" was fooled even in agreement: it scored 0.54 on the label of
     the transparent button. A text prompt is the wrong tool here.
6. **Validation** ([41104422848](https://github.com/seanudeke/Expectrail/actions/runs/41104422848), [41104434739](https://github.com/seanudeke/Expectrail/actions/runs/41104434739), [41104445469](https://github.com/seanudeke/Expectrail/actions/runs/41104445469)).
   - **Detection:** 8 of 8, every failing check on both sessions, no false alarm.
   - **Judge:** with SAM, 5 of 5 good changes accepted, Muse's fix included, and 0 of 5 bad ones.
   - **Live:** Muse Code fixed layering v2 on the first attempt, accepted on the public and private
     sessions.

**What remains open:**
- The prompts and the agreement rule were chosen on public bugs and changes we wrote, plus one
  Muse fix. There are no private web bugs yet to test them on cases they were not tuned on.
- Agreement means the page's own paint box tells SAM where to look. A pass needs both the page and
  the pixels to say the button is there. Agreement only removes SAM's boxes, never adds one, so it
  cannot make SAM see a button that is not drawn on the element's own box. But a vision check that
  leans on the page's geometry is not independent of the page.

Spend for the eleven runs above: about $9 of SAM images, plus Muse Code on two rejected live
cases and one accepted one.
