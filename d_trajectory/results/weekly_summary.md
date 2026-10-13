# ProsecutionBench, Table 3 pilot: weekly summary (week of 2026-10-08)

> DRAFT by D. Lines marked **[A]**, **[B]** or **[C]** are filled by that owner. All numbers are pilot results on small samples, not benchmark findings.

## 1. What we ran, on what
- Data: `data_v1_share` v1.2 (A). One example = one application at t = 1. The cutoff is the A1 filing date, and no document dated after it is a model input.
- Samples: `test_core` 100 (all 26 data_v0 test cases included), `gen_core` 50 (all 17 data_v0 generation cases), `gold_subset` 10.
  Training information cutoff 2013-12-31; families disjoint between train and test.
- Data alignment: members use the same `data_v1_share` v1.2 snapshot and A's `sample_manifest.csv`. D verified that the `input_hash` values match the manifest for all 100 `test_core` cases. Prompts and model-input payloads depend on the task and input condition; matching dataset hashes do not imply identical full model inputs.
- Model: GPT-5-mini on each member's own Azure deployment, `reasoning_effort = low` (team decision 10/10). Main input setting: structured state (A's predicted A1 state) + history; history-only reported as a comparison.

## 2. Table 3 status (15 columns)
See `results/task_status.csv` and `results/table3_pilot.tex`.

| Category | Columns | Status | N |
|---|---|---|---|
| Examiner Prediction (B) | Occ., Type, Grnd. | **[B]** | |
| Examiner Generation (C) | R-L 0.1678, MET. 0.2202, Judge 2.0513/5 | 39 scored / 50 eligible |
| Applicant Response (A) | Strat. 0.52, Edit 0.16, Supp. 0.53 (judge uncalibrated until the 10-unit A/C labels are done) | 10 gold |
| Trajectory (D) | C-idx 0.49, IBS 0.25 (state + history); history only 0.55 / 0.22 | 100 |
| State Tracking (A) | Claim 0.78, Rej. 1.00 at A1 cutoff (O1: 0.63 / 1.00); objections excluded | 10 gold |
| Personalized (B) | ΔOcc., ΔR-L | **[B]** | |

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
- Evidence / generation (C): the model often carries forward earlier rejections instead of updating its assessment after A1. For example, in `14723918_t1`, the generated action maintains the 102/103 rejections, whereas actual O2 (`IWNJSWTWRXEAPX5`) withdraws the rejections, allows claims 1–9, and raises only an informality objection to claim 10. Among the 39 schema-valid cases, the model predicts CTNF in 37 cases, compared with 4 CTNF reference codes; overall code agreement is 6/39 (15.4%). This measures agreement with document codes, not substantive allowance/rejection accuracy. Citation-location checks match 181/314 passages (57.6%) to their named input documents; matching establishes location, not evidential support. Eleven outputs fail schema validation because of unsupported ground categories or ambiguous combined labels/statuses. Conservative format normalization recovers none. Examples: `c_examiner_generation/results/generation_examples.md`.
- Prediction: **[B]**
- Trajectory: the model predicts prosecution as too slow (fast allowances are missed); it seldom predicts abandonment after a substantive reply; adding the state did not help.

## 5. Cost (GPT-5-mini)
| Member | Calls | Tokens in / out | Cost (USD) |
|---|---|---|---|
| A | (see A/model_manifest.json) | | $5.69 state (incl. prompt variants) + $1.78 response, as logged by A |
| B | | | **[B]** |
| C | 103 logged model responses (including dev and retries) | 4.866M / 0.337M | ≈ $1.882 logged estimate; check the Azure bill |
| D | 203 (3 dev + 2 × 100 test), 0 cut-off answers | 8.22M / 0.19M | ≈ $2.4 at list price ($0.25 / $2.00 per 1M); check the Azure bill |

## 6. Extra models
- A: not run (N/A this week).
- **[B]**,
- C: not run. The pilot uses GPT-5-mini for both generation and judging; cross-model comparisons are deferred to the next phase.
- D: not run; GPT-5-mini results came in Saturday night and the extra deployments were not set up.

## 7. What the formal experiment still needs
See `results/next_week_actions.md`.
