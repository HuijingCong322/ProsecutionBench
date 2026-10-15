# ProsecutionBench, Table 3 pilot: weekly summary (week of 2026-10-08)

> DRAFT by D. Lines marked **[A]**, **[B]** or **[C]** are filled by that owner. All numbers are pilot results on small samples, not benchmark findings.

## 1. What we ran, on what
- Data: `data_v1_share` v1.2 (A). One example = one application at t = 1. The cutoff is the A1 filing date, and no document dated after it is a model input.
- Samples: `test_core` 100 (all 26 data_v0 test cases included), `gen_core` 50 (all 17 data_v0 generation cases), `gold_subset` 10.
  Training information cutoff 2013-12-31; families disjoint between train and test.
- Data alignment: members use the same `data_v1_share` v1.2 snapshot and A's `sample_manifest.csv`. D verified that the `input_hash` values match the manifest for all 100 `test_core` cases. Prompts and model-input payloads depend on the task and input condition; matching dataset hashes do not imply identical full model inputs.
- Main model: GPT-5-mini on each member's own Azure deployment, reasoning_effort = low (team decision 10/10). A, B and C also ran Qwen3.6-27B with provider-default thinking/sampling, using fixed GPT-derived state; these are not Qwen end-to-end runs or comparisons at matched reasoning settings. Main input setting: structured state (A's predicted A1 state) + history; D also reports history-only as a comparison.

## 2. Table 3 status (15 columns)
See `results/task_status.csv` and `results/table3_pilot.tex`. Overview figure of the same values (layout of the paper's Table 3): `a_state_response/results/table3_pilot_overview.png`.

| Category | Columns | Status | N |
|---|---|---|---|
| Examiner Prediction (B, GPT) | Occ.0.5481, Type 0.1803, Grnd.0.2242 | Runs complete; automatic-gold draft; B review pending | 99 / 99 / 62 |
| Examiner Prediction (B, Qwen) | Occ. 0.6495, Type 0.4081, Grnd. 0.2944 | Runs complete; automatic-gold draft; B review pending | 99 / 99 / 62 |
| Examiner Generation (C, GPT) | R-L 0.1678, MET. 0.2202, Judge 2.0513/5 | Scored; 11 schema failures retained | 39 scored / 50 eligible |
| Examiner Generation (C, Qwen) | R-L 0.1453, MET. 0.1124, Judge 2.5000/5 | Scored; 5 schema failures and 1 API failure retained | 44 scored / 50 eligible |
| Applicant Response (A, GPT) | Strat. 0.52, Edit 0.16, Supp. 0.53 | Reported; Supp judge checked on C's 10 labels (agreement 6/10, judge lenient) | 10 gold |
| Applicant Response (A, Qwen) | Strat. 0.54, Edit 0.25, Supp. 0.48 | 10/10 replies parsed; Supp uses the same frozen GPT-5-mini judge | 10 gold |
| Trajectory (D, GPT) | C-idx 0.49, IBS 0.25 (state + history); history only 0.55 / 0.22 | Both input settings scored | 100 |
| Trajectory (D, Qwen) | C-idx 0.59, IBS 0.187 (state + history); history only 0.53 / 0.182 | Both input settings scored, 0 failures | 100 |
| State Tracking (A, GPT) | Claim 0.78, Rej. 1.00 at A1 cutoff (O1: 0.63 / 1.00) | Reported; objections excluded | 10 gold |
| State Tracking (A, Qwen) | Claim 0.43, Rej. 0.67 at A1 cutoff (O1: 0.82 / 0.91) | 6 of 20 snapshots truncated at 16384 tokens (5 at A1), scored as empty | 10 gold |
| Personalized (B) | GPT ΔOcc.−0.1111, ΔR-L−0.0063; Qwen ΔOcc.+0.2667, ΔR-L +0.0435 | Prediction pairs complete; GPT generation pairs scored; Qwen generation scored (6/8) | 14 prediction pairs; GPT/Qwen generation 6/8 each |

## 3. Trajectory Forecasting (D)
- Endpoint: days from A1 to the first mailed Notice of Allowance or abandonment notice. test_core: 76 allowances, 24 abandonments,
  0 censored. 11 cases resolve after 24 months.
- Labels re-derived independently from USPTO transactions: **100/100 match A's labels**. Traps that are documented:
  `ABN9` = an RCE entry, not abandonment; abandonment date = date the notice was mailed; 3 abandonments were later revived (they stay abandonment).
- Results on test_core (100 cases, 0 failed, 95% bootstrap intervals). Lower IBS is better.

| Method | C-idx | IBS ↓ | Brier 12m | Brier 24m |
|---|---|---|---|---|
| Kaplan–Meier / Aalen–Johansen (train, no covariates) | 0.50 (by construction) | **0.188** [0.173, 0.206] | 0.200 | 0.107 |
| Cox PH, cutoff features (supplementary) | 0.539 [0.470, 0.602] | 0.192 [0.172, 0.214] | 0.207 | 0.111 |
| GPT-5-mini, history only | **0.549** [0.477, 0.613] | 0.223 [0.196, 0.249] | 0.241 | 0.150 |
| GPT-5-mini, state + history (main setting) | 0.493 [0.427, 0.567] | 0.248 [0.217, 0.280] | 0.280 | 0.181 |

- **What the numbers say.**
  1. Ranking: no method ranks cases clearly better than chance; every C-idx interval includes 0.5. History-only GPT-5-mini is highest (0.55).
  2. Calibration: both GPT-5-mini runs predict prosecution as too slow. By 12 months they expect 52% / 50% of cases to be resolved;
     74% actually were. By 24 months they expect 76% / 70%; 89% were. So their IBS is worse than the simple training curve (0.188).
  3. By outcome: allowance is under-predicted (predicted 0.62 / 0.54 by 24 months vs 0.71 observed); abandonment is close (0.13 / 0.17 vs 0.18).
  4. Adding A's predicted state did not help: state − history = −0.056 C-idx [−0.134, 0.028] and +0.025 IBS [−0.006, 0.055].
     The difference is within noise on 100 cases. The two runs' risk scores agree only weakly (correlation 0.23), so the model's case-level signal is unstable.
- **Examples.**
  - 13752885: allowed 11 days after A1. The model gave only a 10–19% chance of any outcome within 12 months. It treats a fresh reply as the start of a long process.
  - 13816667: abandoned 923 days after A1, after 4 more Office Actions and an RCE. The state run gave 8% abandonment by 24 months. The model rarely predicts abandonment after a substantive reply.
- Context: test cases (2014–2017 cutoffs) resolve faster than training cases (2008–2013); the 24-month pending share is 0.11 observed vs 0.21 in the training curve.
  On the 300-case extension, Cox reaches C-idx 0.591 [0.554, 0.627] (LLM not run on the extension).

## 4. Most common errors (one or more sourced examples each)
- State (A): errors are mostly wrong versions or status labels of found claims, not missing claims (12 of 141 wrong records are missing claims, all at O1, mainly withdrawn claims). One app (14420580, a cancellation shown only as an image in a preliminary amendment) causes 57 of the 141. Rej ≈ 1.0 is uninformative at O1/A1 because every gold status there is `outstanding`. Objections are rarely carried to A1 (recall 0.05). Sourced examples: `a_state_response/state_error_examples.md`; analysis: `a_state_response/README.md`.
- Applicant response (A, GPT): the model proposes far fewer edits than applicants made (40 vs 182 reference limitation units; Edit recall 0.10). 14239985: the real reply amends 8 claims after an interview, the model proposes no edit and argument only. Cancellation is never predicted where it happened (13151341, 14229448) and predicted where it did not (F1 0.00). 9 of 49 cited spans do not occur verbatim in the record. Qwen proposes more edits (95 units, recall 0.19) at lower precision (0.37 vs 0.45). Sourced examples: `a_state_response/response_examples.md`.
- Evidence / generation (C, GPT): the model often carries forward earlier rejections instead of updating its assessment after A1. For example, in 14723918_t1, the generated action maintains the 102/103 rejections, whereas actual O2 (IWNJSWTWRXEAPX5) withdraws the rejections, allows claims 1–9, and raises only an informality objection to claim 10. Among the 39 schema-valid cases, the model predicts CTNF in 37 cases, compared with 4 CTNF reference codes; overall code agreement is 6/39 (15.4%). This measures agreement with document codes, not substantive allowance/rejection accuracy. Citation-location checks match 181/314 passages (57.6%) to their named input documents; matching establishes location, not evidential support. Eleven outputs fail schema validation because of unsupported ground categories or ambiguous combined labels/statuses. Conservative format normalization recovers none. Examples: c_examiner_generation/gpt5mini/results/generation_examples.md.
- Evidence / generation (C, Qwen): in 14838440_t1, Qwen predicts NOA and treats the applicant's orientation argument as persuasive, but actual O2 maintains the 103 rejections and makes the action final, including rejections of new claims 24 and 25. The cited A1 remarks are locatable, but establish the applicant's position rather than the examiner's acceptance; the correctly predicted terminal-disclaimer acceptance does not resolve the 103 grounds. In 13773735_t1, Qwen correctly predicts CTFR and the maintained 103 rejection, and its three cited spans are locatable. However, it groups independent claim 13 with dependent claims and dismisses the continuous-process preamble as nonlimiting, while actual O2 argues that Walter's process satisfies that requirement. These two selected cases have record-based AI-assisted explanations, not independent expert validation; a high judge score does not establish error-free reasoning. Review materials: the supplied Qwen_example_reading.zip and updated qwen_generation_examples.md.
- Prediction (B): GPT-5-mini predicts CTNF for 50 of 59 actual CTFR cases (Type macro-F1 0.1803); Qwen predicts CTFR for 46 of 59. Of 36 NOA cases, GPT and Qwen correctly predict 6 and 16, respectively. Gold labels remain automatic/unreviewed. Confusion matrices: b_examiner_prediction/results/*_core_metrics.draft.json. In the source-check example 14723918_t1, O2 is an objection-only CTFR: document type and substantive rejection must be distinguished. Independent human ground review is pending.
- Trajectory: the model predicts prosecution as too slow (fast allowances are missed); it seldom predicts abandonment after a substantive reply; adding the state did not help.

## 5. Cost (GPT-5-mini)
| Member | Calls | Tokens in / out | Cost (USD) |
|---|---|---|---|
| A | 476 logged GPT-5-mini calls: 297 state (incl. 5 prompt variants on 12 dev+tune apps, gold 20, test_core 90) + 179 response (gold 10, test_core 90, dev 3, retries); support judge 40 calls not logged | 9.78M / 2.85M | ≈ $7.47 logged estimate ($5.69 state + $1.78 response); check the Azure bill. Qwen: section 6 |
| B | 215 logged GPT attempts; 129 responses with usage; 86 prior HTTP429 errors; includes dev/retries and generation | 5.539572M / 0.115934M; 0.209792M cached input included | Not estimated; verify Azure bill. Core100, prediction-profile14, generation-profile6 successful |
| C | 103 logged model responses (including dev and retries) | 4.866M / 0.337M | ≈ $1.882 logged estimate; check the Azure bill |
| D | 203 (3 dev + 2 × 100 test), 0 cut-off answers | 8.22M / 0.19M | ≈ $2.4 at list price ($0.25 / $2.00 per 1M); check the Azure bill |

## 6. Extra models
- A: Qwen3.6-27B on A's own Azure deployment (same catalog model, registry version 4, non-FP8, GlobalManagedCompute, 1 x H100 80GB, and the same call settings as B and C: provider-default thinking/sampling, no reasoning_effort/temperature/response_format, max_tokens 8192 with one 16384 retry, 600 s timeout, no transport retries). Gold 10 only, with the same frozen inputs and prompts as the GPT-5-mini run; the Applicant Response input keeps the frozen GPT-derived predicted O1 state, and Supp is scored by the same frozen GPT-5-mini judge. Table 3 (A1 cutoff): Claim 0.4265, Rej. 0.6695, Strat. 0.5424, Edit 0.2527 (P/R 0.37/0.19, 95 predicted units vs 40 for GPT), Supp. 0.4783 (11/23; Qwen wrote 26 argument units vs 53). Qwen's thinking used most of the budget: all 20 state calls were cut at 8192, and 6 of 20 snapshots were still cut at 16384 (13151341 O1+A1; 14239985, 14420580, 14723918, 14838440 at A1). They are scored as empty predictions, the same rule as GPT, so A1 Claim/Rej. mainly reflect truncation. On the 14 snapshots both models parsed (diagnostic, not a Table 3 value), Claim is 0.895 for Qwen vs 0.796 for GPT (O1 0.930 vs 0.654; A1 0.863 vs 0.929) and Rej. is 1.000 for both. 10 gold apps only; no significance claim; inference settings differ from GPT low. Qwen log: 56 attempts, 1.804M input / 0.573M output tokens; GPU billed by accelerator time (US$7.91/h list price), Azure reconciliation pending. Source: `a_state_response/outputs/qwen36_27b/`.
- B: Qwen3.6-27B on Azure, with provider-default thinking and sampling rather than GPT's low reasoning effort, using the same frozen prompt and fixed GPT-derived state. All 100 core and 14 profile outputs ultimately succeeded; one ReadTimeout was resolved by explicit cached resume. Core Occ./Type/Grnd. are 0.6495/0.4081/0.2944 (N=99/99/62), versus GPT's 0.5481/0.1803/0.2242. On the same 14 Qwen pairs, profile changes Occ. from 0.4000 to 0.6667, Type from 0.2939 to 0.4474, and Grnd. from 0.2080 to 0.3802 (ground N=8), giving ΔOcc.=+0.2667. GPT's paired Occ. changes from 0.6000 to 0.4889 (ΔOcc.=−0.1111). The small conditional subset and different inference settings prevent claims of universal or statistically significant improvement. Qwen logs contain 126 attempts and 123 responses with usage: 5.948123M input and 0.324535M output tokens (including personalized generation); cost is unestimated. See `b_examiner_prediction/results/metric_provenance.json`.
- C: Qwen3.6-27B was run on the same frozen 50-case gen_core, with fixed GPT-derived state and the same generation prompt. It uses provider-default thinking/sampling and JSON prompting, with an 8192-token output limit and one 16384-token length retry. The same frozen GPT-5-mini judge scores both generators. Qwen scores 44/50 cases: R-L 0.1453, MET. 0.1124 and Judge 2.5000/5, compared with GPT's 0.1678, 0.2202 and 2.0513/5 on 39/50 cases. Five Qwen outputs fail schema validation and one has an API failure; none of these failures are replaced with zero scores or removed from the coverage report.
- D: Qwen3.6-27B on D's own Azure deployment (same team setting: registry v4 non-FP8, Global Managed Compute, 1×H100, provider-default thinking/sampling, max_tokens 8192 with one 16384 retry, JSON prompt only, 0 transport retries), same 100 test_core cases, both input settings, 100/100 valid each. Same frozen prompt and output-repair rules as GPT (curve repairs: 19–23 cases per run vs 6–7 for GPT; no case dropped).
  - State + history: C-idx 0.589 [0.532, 0.644], IBS 0.187 [0.153, 0.223], Brier 12m/24m 0.184/0.108. History only: C-idx 0.533 [0.456, 0.601], IBS 0.182 [0.146, 0.224], Brier 0.202/0.104.
  - Paired on the same 100 cases: Qwen − GPT (state + history) C-idx +0.095 [+0.012, +0.172], IBS −0.062 [−0.102, −0.014]. Qwen − GPT (history only) C-idx −0.016 [−0.120, +0.084], IBS −0.041 [−0.084, +0.008]. Qwen state − history C-idx +0.056 [−0.035, +0.153], IBS +0.005 [−0.015, +0.025].
  - Reading: Qwen with state is the only method whose C-idx interval excludes 0.5; Qwen's IBS matches the KM/AJ reference (0.188). The state does not clearly help either model. Qwen's error is the opposite of GPT's: it predicts prosecution as too fast and too favourable (resolved by 12 months 0.87–0.89 vs 0.74 observed; allowed by 24 months 0.92–0.93 vs 0.71; abandoned 0.05 vs 0.18). Thinking settings differ between models, so this compares setups, not models alone.
  - Cost: two 100-case runs + 3 dev, ≈ 4.9M + 4.1M input / 0.34M + 0.34M output tokens; billed per H100 hour ($7.91/h list), Azure bill pending.

## A: state tracking and applicant response
Figures: `a_state_response/results/A_results_plot.png` (GPT-5-mini), `A_results_plot_qwen36_27b.png` (Qwen) and `A_model_comparison.png` (both); all values are from committed files and need no API key.

- Gold: 10 human-reviewed applications x {O1, A1} cutoffs (517 claim records, 310 rejection tuples); every one of 143 review items has a recorded decision source (`a_state_response/gold/GOLD_README.md`). The automatic reference reaches only Claim 0.776 against this gold, so Claim is scored on the gold apps, not on test_core.
- GPT-5-mini: Claim 0.633 (O1) / 0.777 (A1), app-level bootstrap 95% CI [0.388, 0.875] / [0.573, 0.912]. Rej 1.000 / 0.997 is not informative at these cutoffs: every gold rejection status is `outstanding`, so Rej reduces to (claim, ground) F1. One app (14420580, a cancellation shown only as an image) causes 57 of the 141 wrong claim records.
- Applicant response (GPT-5-mini): Strat 0.52, Edit 0.16 (P/R 0.45/0.10), Supp 0.53 (26/49). Supp judge vs C's 10 labels: agreement 6/10; all 4 disagreements are judge `supported` vs C `not_supported`, so Supp is likely an upper estimate. C also confirmed the edit gold of 3 apps (`a_state_response/gold/edits_review_C_done.csv`).
- Qwen3.6-27B (section 6): Table 3 A1 values are lower mainly because 5 of 10 A1 snapshots were cut at 16,384 tokens; on the 14 snapshots both models parsed, Claim is 0.895 (Qwen) vs 0.796 (GPT), Rej 1.000 for both.

Source: `a_state_response/README.md`.

## C: paired generator comparison
The stored paired comparison uses 37 cases successfully scored for both generators. Differences are Qwen minus GPT on those same cases, not differences between the separately reported 44-case and 39-case means.

| Metric | 	Paired difference | Reported bootstrap 95% interval	| Common scored cases |
|---|---|---|---|
| R-L	| -0.0223	| [-0.0342, -0.0095]| 37|
| MET.| -0.1073	| [-0.1264, -0.0882]| 37 |
| Judge	| +0.5946 |	[+0.0811, +1.1081] |	37|

On this common valid subset, Qwen has lower text-overlap scores but a higher fixed-judge score. This mixed result does not establish an overall model winner: the sample is a small pilot selected by successful outputs, inference settings differ, and the GPT judge may favor its own model family. The intervals describe this conditional subset rather than full-benchmark performance. These model differences must not be entered into B's personalized ΔR-L column. 

Source: `c_examiner_generation/qwen36_27b/metrics/C/qwen_generation_metrics_core.json`.

C's Qwen usage log contains 67 responses and 1 API-error record across the connection check, dev cases, core calls and retries, with 3.299891M input and 0.461783M output tokens. Qwen's managed GPU deployment is billed by accelerator time, so its cost is not estimated from GPT token prices; Azure billing reconciliation remains pending. The additional GPT judge usage is listed separately above. 

Source: `c_examiner_generation/qwen36_27b/results/qwen_usage_summary.json`.

## B: baselines and review status
Using the same 99 test IDs and 445 eligible training examples with the fixed training-information cutoff of 2013-12-31, Occ. AUROC is 0.5000 for Majority, 0.5780 for LR-reply-v1.2-raw, 0.5608 for LR-time, 0.5481 for GPT, and 0.6495 for Qwen. LR uses fixed C=1 and train-only imputation/scaling, with no tuning on the current test results. Raw A1 status proxies differ from the old reviewed-markup implementation; the binary baselines do not generate Type/Grnd. predictions. 

Source: `b_examiner_prediction/results/baseline_comparison.draft.csv`.

All B metrics are **automatic-gold drafts**. B must independently review 13151341, 14229448 and 14420580 at both O1 and A1 (6 states), and manually check 5 ground-gold cases. A/C's 10-unit support calibration is separate. Ground scoring leaves 36 missing-gold cases unknown and excludes the 112d taxonomy conflict in 14012315 (original gold preserved), giving N=62. This differs from a fully verified reference with NOA ground labels explicitly empty. GPT ΔR-L is −0.0063 on 6 common valid pairs out of 8 fixed candidates: full-text R-L changes from 0.1859 to 0.1796. Two original C schema failures are retained, with no replacement or baseline rerun. All 6 new profile candidates succeeded,with one 8192→16384 truncation retry. The same C prompt, base input, Porter scoring and surface_format_v1 were used; this is a partial-coverage pilot with no significance claim. Qwen ΔR-L is +0.0435 on 6/8 valid pairs (0.1462→0.1898); two original C baseline failures are retained. Known PatEx families show no train-test overlap; 143/445 training and 25/99 test applications have unknown local family coverage, not proven global singleton status.

## 7. What the formal experiment still needs
See `results/next_week_actions.md`.


### B Qwen personalized generation update (2026-10-14)

Qwen ΔR-L = +0.0435289067: no-profile 0.1462454992 → profile 0.1897744060, on 6 common valid pairs of 8 fixed candidates. Original C baseline failures 14122074_t1 (API) and 14157613_t1 (schema) remain excluded without replacement. All 6 new profile candidates succeeded; 2 ReadTimeouts were explicitly resumed. Matching registry version 4/non-FP8 was user-confirmed; B billing/hardware is unverified. Exact C prompt/base/scoring and provider defaults were retained. GPT and Qwen valid-six subsets differ; this small pilot does not establish a significant model effect. B independent 6-state and 5-ground human reviews are still pending.
