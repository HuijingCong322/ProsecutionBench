# Remaining Rounds and Time to Next Action: protocol (frozen 2026-10-21, results added 2026-10-22)

Owner: D. These are the 2nd and 3rd purple rows of the task table (Trajectory Forecasting), next to Disposition.
They use the same 100 test_core cases, the same cutoff (the A1 filing date), the same training cases (478, nothing
after 2013-12-31) and the same model inputs as Disposition.

## 1. What is predicted

| Task | Question | Label | Metrics |
|---|---|---|---|
| Remaining Rounds | How many more rejections will the examiner mail before the case ends? | N = 0, 1, 2, ... | MAE (lower is better), Accuracy (exactly right) |
| Time to Next Action | How many days until the examiner's next letter? | days | C-index, MAE in days |

**Counted as a round:** a mailed non-final rejection (`MCTNF`) or final rejection (`MCTFR`) after the cutoff and on or before
the first Notice of Allowance or abandonment notice (the Disposition end date). Rejections after an RCE do count, because
an RCE does not end the case. Advisory actions, restriction requirements, Quayle actions, interview summaries and
examiner's answers do **not** count.

**Next examiner letter:** the first mailed `MCTNF`, `MCTFR`, `MCTAV` (advisory), `MCTRS` (restriction), `MCTEQ` (Quayle),
`MN/=.` (allowance) or `MABN*` (abandonment) after the cutoff. Interview summaries and other letters do not count.

## 2. Worked examples (real transaction lines)

**13826133**, cutoff (A1 filed) 2014-03-04:

```
2014-03-24 MCTFR  final rejection        <- next letter, 20 days after the cutoff; round 1
2014-05-09 RCEX   applicant files an RCE (case continues)
2014-06-02 MCTNF  non-final rejection    <- round 2
2014-11-21 MCTFR  final rejection        <- round 3
2015-03-04 MCTAV  advisory action        <- not a round
2015-04-02 MN/=.  Notice of Allowance    <- case ends
```
Labels: N = 3, next action = 20 days.

**14622198**, cutoff 2016-04-21: the next letter is the Notice of Allowance on 2016-05-06. Labels: N = 0, next action = 15 days.

## 3. Label checks

- My rounds count = A's `remaining_oas` for **100/100** test_core cases. Over all 1000 examples it is 992/1000.
  In the 8 other cases (7 training, 1 in test300), A counts one extra rejection. The reason is that the USPTO document
  catalog lists the same final rejection twice on the same day (e.g. 12016339: one `MCTFR` transaction, two `CTFR` catalog rows).
  I count mailed transactions, so one action = one count. **Question for A:** should `remaining_oas` be fixed?
- My next-letter date = A's `target` date for **1000/1000** examples.
- test_core: no censored case for either task. Training: 164 of 478 rounds labels are censored (the case was still open on
  2013-12-31, so we only know "at least this many"); 30 of 478 next-letter labels are censored at 2013-12-31.

## 4. test_core facts

- Rounds: 0 → 36 cases, 1 → 37, 2 → 7, 3 → 11, 4 → 4, 5 → 4, 7 → 1 (mean 1.27).
- Next letter: final rejection 60, allowance 36, non-final rejection 3, restriction 1. Median 65 days (training median 59).

## 5. Methods

- **Marginal (KM):** one Kaplan–Meier curve from training, given to every case. Predicts N = 1 and 62 days for everyone.
  Its C-index is 0.5 by design.
- **Cox:** same 20 cutoff facts as the Disposition Cox model, ridge alpha = 1.
  - Rounds are fitted as a survival problem, so censored training cases still help. "Time" = N + 1, and a case still
    open with k rejections seen is censored at k + 0.5, which means "N is at least k".
  - P(N = k) = S(k) − S(k+1). The point prediction is the median, because the median gives the smallest average absolute error.
  - Next action: the prediction is the median day of the predicted curve; the risk score is the Cox score.
- **LLMs** (GPT-5-mini low and Qwen3.6-27B team setting; history only and A's A1 state + history): one call per case answers
  both tasks with `prompts/rounds_next_forecast.txt`. The model returns:
  - `p_further_actions` for 0 / 1 / 2 / 3 / 4+ (summing to 1)
  - `further_actions` (a whole number, the scored point prediction)
  - `days_to_next_action` (a whole number; risk = minus the days)

  Fixed repair rules are listed in `code/run_rounds_next_llm.py`. A broken answer is retried once and is then listed as
  failed, never filled in.

## 6. Results (test_core, 100 cases, 0 failures in every run, 95% bootstrap intervals, seed 20261010)

| Method | Rounds MAE ↓ | Rounds Acc ↑ | Next C-index ↑ | Next MAE (days) ↓ |
|---|---|---|---|---|
| Marginal (KM) | 0.99 [0.77, 1.22] | 0.37 [0.27, 0.46] | 0.50 | 36.3 [29.3, 45.9] |
| Cox | 1.14 [0.93, 1.37] | 0.27 [0.18, 0.36] | 0.52 [0.45, 0.58] | 37.1 [30.0, 46.6] |
| GPT-5-mini, history only | 0.96 [0.72, 1.22] | 0.44 [0.34, 0.53] | 0.56 [0.496, 0.63] | 37.1 [29.5, 46.6] |
| GPT-5-mini, state + history | 0.99 [0.76, 1.24] | 0.41 [0.32, 0.51] | 0.56 [0.498, 0.62] | 37.3 [29.7, 47.2] |
| Qwen3.6-27B, history only | 1.10 [0.84, 1.37] | 0.43 [0.34, 0.52] | 0.58 [0.51, 0.65] | 48.0 [39.2, 58.2] |
| Qwen3.6-27B, state + history | 0.96 [0.71, 1.23] | 0.49 [0.39, 0.59] | 0.56 [0.49, 0.63] | 48.4 [40.1, 58.0] |

Main points (details and paired tests: `results/rounds_next_paired.csv`, week report of 2026-10-22):
- **Rounds:** no method clearly beats KM's "1 for everyone" on MAE. The AI runs never guess 2 or more, but 27 cases had 2+
  (mostly cases with an RCE). Their probabilities do carry signal: AUROC of P(0 more) for the 36 cases with 0 is
  0.64–0.74, all intervals above 0.5 (`results/rounds_p0_auroc.csv`). The state clearly helps Qwen (MAE −0.14 [−0.23, −0.05]).
- **Next action:** the AI runs rank a little better than chance (only Qwen history-only clears 0.5); Qwen guesses ~100
  days vs the real median 65, so its MAE is about 11 days worse than GPT and KM (clear in paired tests).
- **Cox is worse than KM** on Rounds (clear) and no better on Next action. The 20 case facts do not predict these outcomes.
- All four AI runs: 100/100 valid on the first try, 0 repairs. Same prompt for all (hash 2e8f78f097).

## 7. Files

- Code: `code/build_rounds_next_data.py` → `code/baselines_rounds_next.py` → `code/run_rounds_next_llm.py` (Colab:
  `code/D_rounds_next_run.ipynb`) → `code/score_rounds_next.py` → `code/analyze_rounds_next.py` → `code/build_forecasting_table.py`.
- Labels: `gold/rounds_next_gold.csv`, `gold/rounds_next_gold_test300.csv`, `inputs/rounds_next_train_labels.csv`,
  `rounds_next_label_audit.csv`.
- Results: `outputs/D/rounds_next_predictions_{km,cox}.jsonl`, `outputs/D/rounds_next_cox_coefficients.json`,
  `outputs/D/rounds_next_predictions_{gpt-5-mini,qwen3.6-27b}[_state].jsonl`, `metrics/D/rounds_next_metrics.json/.csv`,
  `results/forecasting_table.csv/.tex` (the paper's `tab:forecasting` rows), `results/rounds_next_paired.csv`,
  `results/rounds_confusion.csv/.png`, `results/rounds_by_group.csv`, `results/rounds_p0_auroc.csv`,
  `results/next_action_by_type.csv`, `results/rounds_next_examples.csv`, `results/rounds_distribution.png`,
  `results/next_action_scatter.png`.

## 8. Open points

1. The task table lists the Remaining Rounds input as H_t, S_t (no reply A_t). Here the cutoff is the A1 filing date, the
   same as Disposition and the paper's forecasting prompt, so the reply is in the record. Using an O1 cutoff instead would
   need new model inputs and states. This is a team / mentor decision.
2. The fix for A's `remaining_oas` (section 3).
