# D · Trajectory Forecasting (Disposition, Remaining Rounds, Time to Next Action)

> **In this repo:** D's part of ProsecutionBench: the three purple Trajectory Forecasting rows of the task table.
> Last updated 2026-10-22. All three tasks are finished on test_core (100 cases) with KM, Cox and four AI runs.
> Data (`data_v1_share` v1.2) is not in the repo; get it from the shared Drive. A's predicted A1 state, used by the
> "state + history" runs, is `a_state_response/outputs/state_predictions.jsonl` (copy it to `inputs/state_predictions_A.jsonl`).
> The repo `.gitignore` ignores `outputs/`; the committed `d_trajectory/outputs/D/` files were added on purpose.

## The three tasks

All three start at the same cutoff: the day the applicant files the first reply (A1). Nothing after it is used.

| Task | Question | Label | Metrics |
|---|---|---|---|
| Disposition | When does the case end, and how (allowed / abandoned)? | (T, δ), right-censored | C-index, IBS, Brier@12, Brier@24 |
| Remaining Rounds | How many more rejections (non-final + final) before the case ends? | N = 0, 1, 2, ... | MAE, Accuracy |
| Time to Next Action | How many days until the examiner's next letter? | days | C-index, MAE (days) |

Training: 478 cases with A1 before 2014 (censored at 2013-12-31). Test: test_core, 100 cases, one per family.

## Results (test_core, 100 cases, 0 failures in every run)

| Approach | Disp. C-index | IBS ↓ | Brier@12 ↓ | Brier@24 ↓ | Rounds MAE ↓ | Rounds Acc | Next C-index | Next MAE (days) ↓ |
|---|---|---|---|---|---|---|---|---|
| Marginal (KM, no covariates) | 0.50 | 0.19 | 0.20 | 0.11 | 0.99 | 0.37 | 0.50 | 36.3 |
| Cox proportional hazards | 0.54 | 0.19 | 0.21 | 0.11 | 1.14 | 0.27 | 0.52 | 37.1 |
| GPT-5-mini, history only | 0.55 | 0.22 | 0.24 | 0.15 | 0.96 | 0.44 | 0.56 | 37.1 |
| GPT-5-mini, state + history | 0.49 | 0.25 | 0.28 | 0.18 | 0.99 | 0.41 | 0.56 | 37.3 |
| Qwen3.6-27B, history only | 0.53 | 0.18 | 0.20 | 0.10 | 1.10 | 0.43 | 0.58 | 48.0 |
| Qwen3.6-27B, state + history | 0.59 | 0.19 | 0.18 | 0.11 | 0.96 | 0.49 | 0.56 | 48.4 |

The paper's appendix table (`tab:forecasting`) with these rows: `results/forecasting_table.tex`.
95% intervals and paired tests: `metrics/D/trajectory_metrics.csv`, `metrics/D/paired_*.json`,
`metrics/D/rounds_next_metrics.csv`, `results/rounds_next_paired.csv`. Full write-up: `week_report_2026-10-22.md`.

Main points:
- The AI runs are better than the baselines at one thing: telling "the reply will be accepted soon" from "more rounds
  are coming" (Qwen state allowance AUROC 0.74; AUROC 0.64–0.74 for "no more rejections" in all four runs).
- No AI run is clearly closer than KM on any "how close" score (IBS, Rounds MAE, days). GPT is too slow on Disposition;
  Qwen is too optimistic about allowance and about a month too slow on the next letter.
- Nobody predicts the long cases: 27 cases had 2+ further rejections (mostly after an RCE); no AI run guesses 2+.

## Run everything (Mac / Linux)

```bash
pip install "scikit-survival==0.28.0" "scikit-learn==1.9.1" openai matplotlib pandas
cd code
# Disposition
python build_trajectory_data.py --data ../../data_v1_share --out ..
python baselines_trajectory.py --root ..
python run_trajectory_llm.py --root .. --data ../../data_v1_share --split core      # or Colab: D_trajectory_run.ipynb / D_trajectory_qwen.ipynb
python score_trajectory.py --root .. && python compare_trajectory_models.py --root .. && python plot_trajectory.py --root ..
python analyze_disposition_extra.py --root ..        # per-ending AUROC, calibration + log loss, month-6/12 ranking check
# Remaining Rounds + Time to Next Action
python build_rounds_next_data.py --data ../../data_v1_share --out ..
python baselines_rounds_next.py --root ..
python run_rounds_next_llm.py --root .. --data ../../data_v1_share                  # or Colab: D_rounds_next_run.ipynb
python score_rounds_next.py --root .. && python analyze_rounds_next.py --root ..
python build_forecasting_table.py --root ..          # results/forecasting_table.tex
```
LLM runs need Azure keys in the environment (see the notebooks). `--mock` runs the LLM path with a fake model, no cost.

## Folder map

```
forecast_protocol.md         Disposition rules (endpoint, 24-month horizon, repair rules), frozen before scoring
rounds_next_protocol.md      Remaining Rounds + Time to Next Action rules, worked examples, results
week_report_2026-10-22.md    full report: results, graphs, explanations, limits, Q&A
trajectory_label_audit.csv   Disposition labels vs A's (100/100 match)
rounds_next_label_audit.csv  rounds / next-letter labels vs A's remaining_oas / target (100/100 on test_core)
gold/                        answer keys (never model input): trajectory_gold*.csv, rounds_next_gold*.csv
inputs/                      model inputs, training labels, test features, time grid
prompts/                     trajectory_forecast.txt (Disposition), rounds_next_forecast.txt (the other two)
code/                        build, baselines, LLM runners + Colab notebooks, scorers, analysis, plots, paper table
outputs/D/                   per-case predictions for every run, Cox weights, run manifest
metrics/D/                   all scores with 95% intervals, paired tests, Disposition extras
results/                     paper table, breakdown tables, figures (.png/.pdf)
```

Older files from the week-3 Table 3 merge (`results/table3_pilot.*`, `results/submissions/`, `results/weekly_summary.md`,
`code/build_table3.py`) and the O2 review form (`review/`) are kept for history; they are no longer part of D's tasks.
