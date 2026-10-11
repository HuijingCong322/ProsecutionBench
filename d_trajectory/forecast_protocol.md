# Trajectory Forecasting: protocol (frozen 2026-10-10)

Owner: D. Table 3 columns: **C-idx** and **IBS**. Data: `data_v1_share` v1.2 (inputs gained documents in 46 test_core cases vs v1.1; labels unchanged, re-checked). Week plan sections 10–11 and 13.

## 1. What is predicted
From the A1 cutoff (the day the applicant files the first reply to O1), predict **when the first disposition happens**.
The disposition is either the first mailed **Notice of Allowance** or the first mailed **abandonment notice**, whichever
comes first. The model gives two cumulative curves for months 1..24:
- `F_allowance(m)`: chance the first disposition is an allowance and has happened by month m
- `F_abandonment(m)`: same for abandonment
- `S(m) = 1 − F_allowance(m) − F_abandonment(m)`: chance that nothing has happened yet

Table 3 scores the time to the **first disposition of either kind**, using S. The two outcomes are still predicted
and reported separately (section 8), but this week is not a full competing-risks evaluation by cause.

## 2. Samples
| Set | N | Use |
|---|---:|---|
| `test_core` | 100 (76 NOA, 24 abandonment, 0 censored) | Table 3, scored |
| `test` extension | 300 → 299 eligible (218 NOA, 81 abandonment) | optional; 14756161 excluded as `incomplete_record` |
| training pool | 478 = `train` 448 + `excluded_time_boundary` 30 | Kaplan–Meier / Cox reference only; never shown to the LLM |
| dev | 11968167, 11968173, 11968176 | prompt and parsing checks only, not scored |

All 10 `gold_subset` cases are inside `test_core`. Test families do not appear in the training pool (A's split; re-checked).

## 3. Labels (`gold/trajectory_gold.csv`)
- **Time zero** = A1 filing date (`cutoff`). `time_days` = days from cutoff to the outcome.
- `label_status`: 0 = censored, 1 = Notice of Allowance, 2 = abandonment.
- **Allowance date** = transaction `MN/=.` (Mail Notice of Allowance); source document = catalog `NOA` on that date.
- **Abandonment date** = first `MABN*` transaction (the date the abandonment notice was mailed); source document = catalog `ABN`.
  This is the "recorded abandonment" in the paper. The legal abandonment date can be weeks earlier (the day after the
  reply deadline). The internal `ABN2`/`ABN10` code and date are kept in the audit file.
- **`ABN9` is never an abandonment.** It means "Disposal for a RCE / CPA / R129" and appears once for every RCE.
- RCE, appeal, advisory action, interview, petition and further OAs are **intermediate events**: prosecution continues.
- **First event rule:** a later revival, later allowance or issued patent does not change the label.
  3 test_core abandonments were later revived and allowed (13698575, 13060040, 14400543); they stay "abandonment".
- **Censored vs incomplete:** a case is censored only if the record is followed up to the snapshot. If the record stops more
  than a year before the snapshot with no outcome, it is `incomplete_record`. It is censored at its last transaction
  and excluded from scoring, with a count reported. This affects 1 case (14756161, extension only).
- **Check:** every test_core label was re-derived independently from `transactions.csv` and `catalog.csv`. **100/100 match
  A's `labels.disposition`** (`trajectory_label_audit.csv`). The NOA/ABN PDFs themselves were not downloaded (`not_requested`).
  A re-checks 2 cases against the PDFs, as the plan requires (suggested: 14031839, 14400543).

## 4. Training labels (`inputs/trajectory_train_labels.csv`)
- Training may only use what was known on **2013-12-31**. An outcome after that date is censored at 2013-12-31:
  164 of 478 cases, including 60 abandonments that happened later.
- **Deviation from A's split, on purpose:** the 30 `excluded_time_boundary` cases are added to the training pool as censored.
  A drops them because their *next action* came after 2013. For survival, dropping them would select on a future date and
  favour fast cases. Their cutoffs are before 2013-12-31 and their families do not overlap the test set.
- After censoring: 264 NOA, 50 abandonment, 164 censored. At 24 months only 32 training cases are still at risk, so the
  training curve past ~18 months rests on few cases.

## 5. Time grid and horizon
Months 1..24, at day = round(m × 30.4375): 30, 61, 91, …, 700, 730. Horizon τ = 730 days (24 months).
Chosen before scoring, as in the plan. Feasibility is in `trajectory_feasibility.md`.

## 6. Model inputs (`inputs/trajectory_inputs.jsonl`)
- Documents = A's `examples/<id>.json` `inputs`: the application as filed (or a pre-grant publication if it was published by the cutoff), O1, the
  references-cited form, any other pre-cutoff record, and the actual A1. They are given oldest first, each with a header line.
- **The `input_hash` of every record equals A's `sample_manifest.csv` hash** (the same recipe: sha1 over doc_id + text, first 16 hex characters).
  All four of us therefore see the same inputs.
- Asserted by the build script: every document date ≤ cutoff; the target document is not an input; no label field
  (disposition, event date, remaining OAs, granted claims, next type) appears in the record.
- **Input settings:** `history_only` (runnable now) and `state_with_history` (the main setting, once A's A1 state arrives on Sat 10/10).
  Both are run and reported, each with its own label.
- Size: median ≈ 35k tokens, max ≈ 156k tokens per case (GPT-5-mini input limit 272k). Nothing is truncated.

## 7. Model run
- GPT-5-mini on D's own Azure deployment. Chat Completions with `response_format = json_object`,
  `reasoning_effort = "low"` (team decision on 10/10, replacing "minimal") and `max_completion_tokens` 8192, retried at 16384 and then 32768 if the answer is cut off (same team rule as A), raised from the
  plan's 4096 because reasoning tokens count toward the limit; no temperature.
- Prompt: `prompts/trajectory_forecast.txt`, **hash 8fa99d848c11**. It was tuned only on the 3 dev cases and is frozen before any test call.
  Besides the paper's Figure 6 wording, it adds two lines of public procedure facts (the 3–6 month reply period and the options after a
  final rejection). The application number is not added to the prompt, but it appears inside the documents, so memorization cannot be ruled out.
- Each output is cached under a key built from the model, parameters, prompt hash, input hash and state version. A rerun only calls the API for new or failed cases.
  Every call goes to `logs/D/usage_log.jsonl`.

## 8. Output rules (frozen, `code/traj_common.py::validate_curves`)
1. Both lists must contain 24 numbers. Otherwise the output is a structural failure: the same prompt is retried once, and if it fails again the case is listed as failed and is **never** filled with default probabilities.
2. Values are clipped to [0, 1].
3. Each curve is made non-decreasing with a running maximum.
4. Where `F_allowance + F_abandonment > 1`, both are divided by their sum. Steps 3–4 repeat until both hold.
5. `S = 1 − F_allowance − F_abandonment`. Every repair is counted and reported.

## 9. Metrics (`code/score_trajectory.py`, scikit-survival 0.28.0, scikit-learn 1.9.1)
- **C-idx** = `concordance_index_ipcw`, τ = 730 days, risk score = 1 − S(730).
- **IBS** = `integrated_brier_score` over the 24-point grid, using S(t). Lower is better.
- Also reported: Brier at 12 and 24 months; Harrell's C truncated at τ (a sanity check); mean predicted vs observed share
  with an outcome by 12 and 24 months; and Brier at 24 months **separately for allowance and abandonment**.
- **Censoring weights:** the plan says to estimate them from the training labels. test_core has **no censored case**,
  so the correct weight for every test case is 1. Weights from the training data are 1/G_train(t), with G_train(730) = 0.32. They
  would up-weight late outcomes for no reason and change IBS from about 0.19 to about 0.27. **Primary** = weights from the evaluation labels (all 1).
  **Sensitivity** = training weights (suffix `_trainG` in the metrics file). This is a deliberate, stated deviation.
- Each result records `eligible_n`, `scored_n`, `failed_n`, `excluded_n` and the exclusion reason. Metrics are N/A if fewer than 10 cases are scored or there are fewer than 2 events.

## 10. Reference results (no LLM)
- **KM / Aalen–Johansen** (required): one training curve for every case. Its C-index is 0.5 by construction, so it is the IBS reference.
- **Cox PH** (supplementary, specified before any test score): ridge α = 1. Features available at the cutoff: technology center,
  O1 type, log days from filing to O1, log days from O1 to A1, number of O1 grounds, and the A1 strategy flags.

## 11. Known limits
- 100 cases: a C-index difference of about 0.05 is within noise. These are pilot numbers, not benchmark findings.
- Training cohort (cutoffs 2008–2013) vs test (2014–2017): the test cases resolve faster (S(24m) is 0.11 observed vs 0.21 in the training KM).
  This shift hurts every model that leans on the training curve.
- The cohort was sampled from OARD, which ends in mid-2017. Late 2014–2015 filings with slow first OAs are therefore missing.
- The abandonment date is the date the notice was mailed, not the legal date. Revived cases count as abandonment.
