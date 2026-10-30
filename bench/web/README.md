# Second domain: the checkout page

Results for the web checkout page ([`apps/checkout`](../../apps/checkout)), the same verifier on a
second kind of software. Every number is written from a CI run's own annotations.

| File | What it is | Written by |
| --- | --- | --- |
| [`detection/`](detection/README.md) | Would each seeded bug be caught, with and without SAM | `python3 -m agents.bench_collect --app checkout --run <id> --out bench/web/detection` |
| [`judge.md`](judge.md), `judge.json` | Who accepts a change that only looks right: Expectrail with and without SAM, and a pixel diff | `python3 -m agents.web_judge collect --run <id>` |

## How the prompts were chosen

The prompts are tuned on the same development bugs they are measured on. These are the runs that
tuned them, in order, so the tuning can be checked.

1. **First detection run, prompts "blue button" and "purple logo"** ([41083893650](https://github.com/seanudeke/Expectrail/actions/runs/41083893650)).
   - It caught 8 of 8, with no false alarm.
   - But on the five bugs that hide or cover the button, or push it off screen, "button visible"
     failed on one session and passed on the other. On the broken logo, "logo visible" did the same.
2. **Diagnostic run** ([41086075943](https://github.com/seanudeke/Expectrail/actions/runs/41086075943)).
   Each session's detail line shows SAM's best box next to where the page drew the element.
   - On the phone, with the real button hidden, "blue button" matched the cart's count badge at
     0.73 to 0.76, and the theme toggle at 0.75. The real button scores 0.78.
   - On the desktop, with the logo broken, "purple logo" matched the purple theme toggle at 0.66.
   - So those checks passed with the element gone. The button bugs were still caught, but by the
     inside-the-form check, because the badge is not in the form.
3. **Prompt probe** ([41087329108](https://github.com/seanudeke/Expectrail/actions/runs/41087329108), [`agents/web_probe.py`](../../agents/web_probe.py)).
   Eleven candidate prompts were scored, using the last frame of each session.
   - **Logo:** "purple B logo" scored the drawn logo 0.89 and found nothing else.
   - **Button:** no prompt was clear of the distractors at the default minScore of 0.5. "full-width
     blue button" had the widest gap: the drawn button at 0.78, ranked first every time, and
     nothing else above 0.55.
4. **Validation on every frame** ([41087757081](https://github.com/seanudeke/Expectrail/actions/runs/41087757081), then [41088369464](https://github.com/seanudeke/Expectrail/actions/runs/41088369464)).
   - The first run used minScore 0.66. On the phone, with the button pushed off screen, the theme
     toggle reached 0.65, too close to 0.66.
   - The second run used 0.71. Over every frame SAM looked at, the drawn button scored 0.75 or
     more and nothing else scored above 0.65.
   - Both runs caught 8 of 8, with every failing check failing on both sessions and no false alarm.

**What remains open:**
- The button's margin is about 0.05 on each side of the threshold, on the phone session only.
- The distractor is part of the unmodified example page.
- There are no private web variants yet to test the prompts on bugs they were not tuned on.

Spend for all five runs: about $4 of SAM images.
