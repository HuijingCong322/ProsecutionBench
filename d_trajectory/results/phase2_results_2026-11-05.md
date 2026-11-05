# D phase 2 results (GPT-5-mini, 2026-11-05)

Can the LLM learn an examiner's habits from past applications? Setups, rules and frozen files:
`personalization_protocol.md`. Words and formulas in plain language: `results/phase2_definitions.md`.

- Cases: the same 100 test_core cases as all D tables, cut at the A1 cutoff.
- Model: GPT-5-mini (Azure, reasoning_effort low).
- Runs: card runs done 2026-11-03 and reused; history runs done 2026-11-05.
- Failures: none. All 8 LLM output files hold 100 / 100 answers, all "stop" (none cut off), no retries.
- Cost of the new history runs: about $4.75.
- Qwen: not run.
- Check: every number below was recomputed from the saved outputs with the frozen code. The result matched the Colab run
  exactly.

## 1. Scores

Higher is better for C-index and accuracy. Lower is better for IBS, MAE and days.

| Setup | Disp C-index | Disp IBS | Rounds MAE | Rounds acc | Next C-index | Next MAE (days) |
| --- | --- | --- | --- | --- | --- | --- |
| KM (plain average, no LLM) | 0.500 | 0.188 | 0.99 | 0.37 | 0.500 | 36.3 |
| LLM, no examiner block | 0.493 | 0.248 | 0.99 | 0.41 | 0.560 | 37.3 |
| LLM + own card | 0.671 | **0.155** | 0.96 | **0.45** | **0.727** | **26.5** |
| LLM + wrong card | 0.594 | 0.203 | 1.10 | 0.34 | 0.485 | 42.6 |
| LLM + own 3 histories | 0.641 | 0.188 | 0.98 | 0.42 | 0.568 | 35.6 |
| LLM + wrong 3 histories | 0.518 | 0.213 | 0.98 | 0.43 | 0.557 | 36.1 |
| Numbers only, own (no LLM) | **0.692** | 0.156 | **0.94** | 0.44 | 0.721 | 27.2 |
| Numbers only, wrong (no LLM) | 0.564 | 0.184 | 1.15 | 0.32 | 0.496 | 42.0 |
| Math on own 3 histories (no LLM) | 0.626 | 0.211 | 1.04 | 0.35 | 0.704 | 28.9 |
| Math on wrong 3 histories (no LLM) | 0.460 | 0.253 | 1.17 | 0.32 | 0.549 | 40.0 |

The "wrong" examiner is another examiner from the same art unit. The wording is identical, so the model cannot tell it
is the wrong one.

## 2. The 7 comparisons

Each cell gives the difference "first minus second" on the same 100 cases. The 95% interval comes from 1,000 bootstrap
draws. **Bold** means clear: the interval does not contain 0. A "+" is good for C-index and accuracy; a "−" is good for
IBS, MAE and days.

| # | Comparison | Disp C | Disp IBS | Rounds MAE | Rounds acc | Next C | Next MAE days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | own card − no examiner | **+0.178** [+0.093, +0.258] | **−0.093** [−0.138, −0.048] | −0.03 | +0.04 | **+0.168** [+0.085, +0.251] | **−10.8** [−15.8, −5.8] |
| 2 | own card − wrong card | +0.077 [−0.013, +0.161] | **−0.048** [−0.091, −0.004] | −0.14 | **+0.11** [+0.01, +0.22] | **+0.242** [+0.147, +0.329] | **−16.1** [−22.1, −9.5] |
| 3 | own card − numbers only | −0.020 [−0.054, +0.008] | −0.001 | +0.02 | +0.01 | +0.006 [−0.008, +0.024] | −0.7 [−1.8, +0.3] |
| 4 | own histories − no examiner | **+0.147** [+0.064, +0.221] | **−0.061** [−0.101, −0.024] | −0.01 | +0.01 | +0.008 [−0.061, +0.084] | −1.8 [−5.9, +2.1] |
| 5 | own histories − wrong histories | **+0.122** [+0.034, +0.204] | −0.025 [−0.056, +0.007] | 0.00 | −0.01 | +0.010 [−0.055, +0.077] | −0.6 [−4.1, +2.7] |
| 6 | **own histories − math on same 3 histories** (main) | +0.015 [−0.053, +0.081] | −0.023 [−0.057, +0.010] | −0.06 | +0.07 | **−0.136** [−0.215, −0.061] | **+6.7** [+1.4, +11.7] |
| 7 | own histories − own card (descriptive) | −0.031 [−0.099, +0.031] | **+0.033** [+0.006, +0.059] | +0.02 | −0.03 | **−0.160** [−0.239, −0.076] | **+9.0** [+4.5, +13.6] |

## 3. Copy check: does the LLM just repeat a number it can read?

| Setup | Compared with | Days exactly equal | Within 3 days | Rank corr with that number | Rank corr with truth |
| --- | --- | --- | --- | --- | --- |
| LLM + own card | card's median days | **86%** | 91% | 0.983 | 0.601 |
| LLM + wrong card | card's median days | 88% | 91% | 0.989 | −0.040 |
| LLM + own histories | math median of the same 3 histories | 0% | 9% | 0.275 | 0.219 |
| LLM + wrong histories (97 cases with histories) | math median of the same 3 histories | 2% | 9% | 0.110 | 0.196 |
| Numbers only, own (no LLM) | — | — | — | — | 0.592 |
| Math on own histories (no LLM) | — | — | — | — | 0.565 |

- With the card, the LLM's "days to the next letter" is the card's median in 86 of 100 cases.
- The LLM's 24-month allowance has a rank correlation of 0.971 with the card's "allowed within 24 months".
- With the histories, all 100 rationales mention the past applications. Still, the predicted days barely follow them.

Spread of the predicted days (median, middle 50%):

| Source | Median | Middle 50% | SD |
| --- | --- | --- | --- |
| Truth | 65 | 29–97 | — |
| LLM, no examiner block | 75 | 60–90 | 19.5 |
| LLM + own histories | 60 | 60–75 | 16.6 |
| Math on the same 3 histories | 61.5 | 30–88 | 33.8 |
| LLM + own card | 63 | 32–88 | 29.7 |

## 4. What this means, in plain words

1. **The card helps a lot, and it is about this examiner (comparisons 1 and 2).**
   - Without the card, the LLM ranks next-letter timing about as well as a coin flip (C 0.560).
   - With the own examiner's card it reaches 0.727, and the average error falls from 37.3 to 26.5 days.
   - The wrong examiner's card does not help (C 0.485, 42.6 days).
   - So the gain comes from information about this examiner, not from "having more text".
2. **But the LLM adds nothing beyond the card's numbers (comparison 3).**
   - "Numbers only" uses the card's numbers with no LLM: each is blended with the art-unit pool, with K estimated from the
     data. It scores the same as the LLM + card on all 6 metrics; none of the differences is clear.
   - The copy check explains why: the LLM writes down the card's median days in 86% of cases.
   - So the LLM is acting as a reader of the card, not as a reasoner about it.
3. **The 3 full histories help Disposition only (comparisons 4 and 5).**
   - Disposition: C-index rises from 0.493 to 0.641, IBS falls from 0.248 to 0.188. This gain is about this examiner: own
     beats wrong by +0.122 in C-index.
   - Timing and rounds: no change. Next C-index is 0.568 vs 0.560, MAE 35.6 vs 37.3 days.
   - Why Disposition and not timing: each history ends with a status line ("allowed (notice of allowance mailed …)"), so
     the outcome can be read directly. The LLM uses it: its average 24-month allowance rises from 0.54 to 0.65. Timing,
     by contrast, has to be worked out by subtracting dates.
4. **Main question: with the same 3 histories, plain math beats the LLM on timing (comparison 6).**
   - The fixed rule "median of the 3 waiting times" gets next-letter C 0.704 and 28.9 days.
   - The LLM, reading the same events, gets C 0.568 and 35.6 days. Both differences are clear: C −0.136, +6.7 days.
   - On Disposition and Rounds the two are tied (no clear difference).
   - The LLM's predicted days bunch around "about 2 months" (60 days; middle 50% 60–75). The math follows each
     examiner (middle 50% 30–88), like the truth (29–97).
   - The LLM's days have a rank correlation of only 0.275 with the math median of the histories it was shown.
5. **Card vs 3 histories (comparison 7).** The card is clearly better for timing (C +0.160, 9.0 days) and for IBS.
   - Note this is not a fair "format" test: the card summarizes all past applications (13060040: 30), while the history
     block shows only 3.
   - The fair format test is comparison 6, against math on the same 3 histories.

**One-sentence summary:** GPT-5-mini gets the examiner's habits when someone has already turned them into numbers, and
then it mostly repeats those numbers. Given the raw dated events, it reads the outcomes but does not work out the
examiner's speed, and simple math on the same events does better.

## 5. Worked example: case 13060040 (own examiner)

- **Truth:** next letter after **73** days; **4** further rejections.
- **3 past applications.** Waits from the first reply to the next letter: 21, 31, 25 days. Rejections after the first
  reply: 1, 3, 1.
- **Math on the 3 histories:** median of 21, 31, 25 → **25 days**; rounds: median of 1, 3, 1 → **1**.
- **Numbers only:** card median 33 days (n = 26), pool 74, Z = 26 / (26 + 1.8) = 0.935 → **35 days**.
- **LLM + own card:** **33 days**, the card's median, copied.
- **LLM + own histories:** **60 days**. Its reason: "Examiner's recent practice (examples in the examiner-history) and the
  complexity of the rejections make a single additional action most probable within ~2 months after the applicant's
  2014-09-26 filing." It cites the histories, but 60 is not what the histories show (21–31 days).
- In this one case the LLM's 60 happens to be closer to the truth (73). Over 100 cases, though, its ordering of fast vs
  slow cases is much worse than the math's (C 0.568 vs 0.704).

## 6. Splits (descriptive)

- **RCE in the true path** (65 cases with 0 RCEs, 35 with 1+): every method's rounds error is about 3–4 times larger
  when an RCE follows.
  - LLM + own histories: 0.48 vs 1.91.
  - Math: 0.65 vs 1.77.
  - Numbers only: 0.60 vs 1.57.
  - LLM + own card: 0.45 vs 1.91.
  - KM: 0.58 vs 1.74.
  - The LLM setups do best without an RCE and worst with one. Numbers only does best with one.
- **Number of past applications shown:** own 99 cases with 3, 1 with 1; wrong 96 with 3, 1 with 2, 3 with none. These
  groups are too small to split.

## 7. K for "numbers only" (Bühlmann–Straub)

The run re-estimated K and got exactly the frozen values (credibility_k.json sha1 `ca0aad33…`).

| Statistic | K | 95% interval | Sensitivity: K vs overall mean |
| --- | --- | --- | --- |
| Days to next letter (log) | 1.8 | 1.4–2.3 | 1.7 |
| Allowed within 24 months | 3.3 | 2.4–4.5 | 3.6 |
| Abandoned within 24 months | 8.4 | 6.0–13.2 | 7.9 |
| Rounds | 4.5 | 3.3–6.5 | 3.5 |

## 8. Limits

- One model (GPT-5-mini), one run per setting, 100 cases.
- The 3 past applications were picked by text similarity, not at random.
- In 81 of 100 cases the art-unit pool (used by numbers only, and the source of the wrong examiner) is one other
  examiner.
- The math baseline counts still-pending past applications with what is known so far: 93 own and 63 wrong applications
  were still open at the cutoff.
- The history block gives the LLM 3 applications, while the card summarizes all of them. Comparison 6 holds the
  information fixed; comparison 7 does not.

## 9. Files

| File | What |
| --- | --- |
| `outputs/D/{trajectory,rounds_next}_predictions_gpt-5-mini_state_profile_{own,mismatched}.jsonl` | LLM + card (2026-11-03) |
| `outputs/D/{trajectory,rounds_next}_predictions_gpt-5-mini_state_history_{own,mismatched}.jsonl` | LLM + 3 histories (2026-11-05) |
| `outputs/D/{trajectory,rounds_next}_predictions_prior_{own,mismatched,artunit}.jsonl` | numbers only |
| `outputs/D/{trajectory,rounds_next}_predictions_history_math_{own,mismatched}.jsonl` | math on the 3 histories |
| `metrics/D/phase2_metrics.json`, `results/phase2_table.csv` | scores, 7 comparisons, splits |
| `results/phase2_copy_check.csv` | copy check table |
| `metrics/D/credibility_k.json`, `metrics/D/examiner_prior_metrics.*` | K and numbers-only metrics |
| `metrics/D/{trajectory,rounds_next}_metrics.*` | standard scorer output, all methods |
| `logs/D/D_phase2_run_executed_2026-11-05.ipynb` | the notebook as run, with its outputs |
