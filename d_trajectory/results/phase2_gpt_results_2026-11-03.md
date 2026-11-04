# D phase 2: GPT-5-mini + examiner profile, results (2026-11-03)

## Key observation (read first)

**The profile already contains the answer, so the LLM copies it.** The examiner statistics were built with the same rules
as our answer keys, so each card line is defined exactly like a task target: "Days from a reply to the next letter:
median 33" is the Next-action target; "Further rejections after the first reply: 0/1/2/3+" is the Rounds target;
"allowed / abandoned within 12 / 24 months after the first reply" are two points of the Disposition curves. The prompt
does not ask the model to use these numbers, but it does not need to: it sees a number that matches the question exactly,
and taking it is the sensible move. Evidence: GPT + own profile = the card's median days in 86/100 cases; its 24-month
allowance follows the card (0.97); with the wrong examiner's card it copies that card just as faithfully (88/100) and its
timing falls to chance (−0.04); and it ties with "numbers only" on every metric. So the full-profile gain measures a
lookup, not reading. The controlled test without target-shaped statistics is Addendum A (examples only,
`personalization_protocol.md` section 9). B and C should check whether any card line is defined like one of their own targets (for example, "Next letter
after such a reply: allowance 32%, final rejection 64%" would be, for a task that predicts the type of the next letter).

Protocol: `D_trajectory/personalization_protocol.md` (frozen before runs). 100 test_core cases, state + history (A_v1),
profile package B_D_C_v4_reviewed_2026_11_02. Format check passed (5 cases × own/mismatched × 2 prompts, 20/20 ok;
a bug in the notebook's cutoff check was fixed, not in the runs). One Azure 429 failure (13862126, rounds own) re-run → all 4 runs 100/100.
Cost about $5.2 (GPT). Qwen runs not yet done (new Azure resource capstone-gpt-resource, North Central US, needs H100 quota).

| Method | Disp C ↑ | Disp IBS ↓ | Rounds MAE ↓ | Rounds Acc ↑ | Next C ↑ | Next MAE d ↓ |
| --- | --- | --- | --- | --- | --- | --- |
| KM | 0.500 | 0.188 | 0.99 | 0.37 | 0.500 | 36.3 |
| GPT-5-mini, no profile | 0.493 | 0.248 | 0.99 | 0.41 | 0.560 | 37.3 |
| GPT + mismatched profile | 0.594 | 0.203 | 1.10 | 0.34 | 0.485 | 42.6 |
| GPT + own profile | 0.671 | 0.155 | 0.96 | 0.45 | 0.727 | 26.5 |
| Numbers only, own (prior_own) | 0.686 | 0.154 | 0.94 | 0.43 | 0.725 | 27.4 |
| Qwen3.6-27B, no profile | 0.589 | 0.187 | 0.96 | 0.49 | 0.563 | 48.4 |

Paired (1,000 bootstraps, seed 20261010, 95% CI):
- Own − no profile: Disp C +0.178 [+0.093, +0.258], IBS −0.093 [−0.138, −0.048], Next C +0.168 [+0.085, +0.251], Next MAE −10.8 d [−15.8, −5.8]; Rounds not clear.
- Own − mismatched: Next C +0.242 [+0.147, +0.329], Next MAE −16.1 d [−22.1, −9.5], IBS −0.048 [−0.091, −0.004], Rounds Acc +0.11 [+0.01, +0.22]; Disp C +0.077 [−0.013, +0.161] not clear.
- Own − numbers only: all CIs include 0 (Disp C −0.015, IBS +0.001, Next C +0.002, Next MAE −0.9 d [−2.5, +0.5]).
- Mismatched − no profile: Disp C +0.101 [+0.005, +0.195] (just clear); Next MAE +5.3 d (worse, not clear).

Reading (protocol section 4): the profile helps GPT a lot and the gain is examiner-specific (timing), but GPT does not
beat the examiner numbers alone → shortcut result: the model takes the examiner's base rate from the card and adds
nothing measurable from the case record. Wrong examiner's speed makes timing worse than no profile.
Pending: copy check (`code/copy_check_cell.py`, Colab), Qwen own/mismatched runs.

## Copy check (no API, `code/copy_check_cell.py`)

| Method | Card | rank corr (pred days, card median) | within 3 days of card | exactly card | rank corr with true days | rank corr (F_allow 24m, card 24m) |
| --- | --- | --- | --- | --- | --- | --- |
| GPT + own profile | own | 0.983 | 0.91 | **0.86** | 0.601 | 0.971 |
| GPT + mismatched | mismatched | 0.989 | 0.91 | 0.88 | −0.040 | 0.921 |
| GPT, no profile | (own, for reference) | 0.212 | 0.07 | 0.01 | 0.176 | 0.087 |
| Numbers only (shrunk) | own | 0.982 | 0.44 | 0.04 | 0.606 | 0.978 |

100% of rationales cite the examiner's history. Conclusion: GPT answers "days to next action" with the card's raw
KM median in 86% of cases (88% with the wrong examiner's card), and its 24-month allowance follows the card (0.97).
It is a lookup of the printed base rate, not a reading of the case record; with the wrong card it copies the wrong
examiner and loses all ranking ability (−0.04). Same accuracy as numbers only, because both are the card median
(raw vs shrunk).
