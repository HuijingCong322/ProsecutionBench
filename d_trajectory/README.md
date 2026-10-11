# D · Trajectory Forecasting + Table 3 integration (week of 2026-10-08)

> **In this repo:** D's part of the week-3 Table 3 pilot (Trajectory Forecasting + Table 3 merge).
> Data (`data_v1_share` v1.2) is not in the repo; get it from the shared Drive. A's predicted state
> (`inputs/state_predictions_A.jsonl`, used for the "state + history" run) comes from A's `week3/output/state_predictions.jsonl`.
> Note: the repo `.gitignore` ignores `outputs/`; the committed `d_trajectory/outputs/D/` files were added on purpose.


Everything for D's part of the week plan (sections 10–14). It needs `data_v1_share` **v1.2** (A's latest, 10/10) next to it (or a path to it).

## Status
| Plan item | Due | Status | File |
|---|---|---|---|
| 5 outcome examples | Fri 10/9 | done | `trajectory_examples_5.md/.csv` |
| Freeze labels, eligible IDs, time grid | Sat 10/10 | done | `gold/trajectory_gold.csv`, `trajectory_eligible_ids.csv`, `inputs/time_grid.json`, `forecast_protocol.md` |
| Label audit + feasibility | Sat 10/10 | done (100/100 match A) | `trajectory_label_audit.csv`, `trajectory_feasibility.md` |
| Leak-free model inputs | Sat 10/10 | done (hash = A's for all 100) | `inputs/trajectory_inputs.jsonl` |
| KM / Aalen–Johansen + Cox reference, metrics, plot | Sun 10/11 | done | `metrics/D/trajectory_metrics.json`, `results/trajectory_survival_plot.pdf` |
| GPT-5-mini forecasts (history only + state with history) | Sun 10/11 | done 10/10 (100/100 scored each, ≈ $2.4) | `outputs/D/trajectory_predictions_gpt-5-mini*.jsonl`, `logs/D/usage_log.jsonl` |
| Review 5 of C's OAs | Mon 10/12 | **waiting for C** (form ready) | `review/oa_review_D.csv`, `review/HOW_TO_REVIEW_OA.md` |
| Merge Table 3, task status | Mon–Wed | A and D filled; B and C pending | `code/build_table3.py`, `results/table3_pilot.*`, `results/task_status.csv` |
| Weekly summary, next-week actions | Wed 10/14 | drafts with D's part filled | `results/weekly_summary.md`, `results/next_week_actions.md` |

`trajectory_label_audit_test_core.csv` from Friday is replaced by `trajectory_label_audit.csv`; the content is the same, with more columns.

## What you still do (in order)
1. **Run GPT-5-mini** in Colab: open `code/D_trajectory_run.ipynb`, set the two paths and your 3 Colab Secrets, and run all cells.
   About 15 minutes and about $1–2. It runs the connection test, then the 3 dev cases, then the 100 test cases, then scores and redraws the plot.
2. **Send the teammates** `results/metrics_submission_template.csv`. Each fills one row per Table 3 column and saves it as
   `results/submissions/A_metrics.csv` (B_, C_).
3. **When A's state arrives:** run notebook section 5 (same 100 cases, state + history).
4. **When C sends 5 OAs (Sun):** fill `review/oa_review_D.csv` following `review/HOW_TO_REVIEW_OA.md`.
5. **Wed noon:** `python code/build_table3.py --root .` → check `results/merge_problems.txt` and `task_status.csv`,
   then fill the [A]/[B]/[C] lines in `results/weekly_summary.md`.

## Run everything locally (Mac / Linux)
```bash
pip install "scikit-survival==0.28.0" "scikit-learn==1.9.1" openai matplotlib pandas
cd code
python build_trajectory_data.py --data ../../data_v1_share --out ..   # labels, audit, inputs (already done)
python baselines_trajectory.py --root ..                            # KM + Cox reference
export AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... AZURE_OPENAI_DEPLOYMENT=gpt-5-mini
python run_trajectory_llm.py --root .. --data ../../data_v1_share --ping
python run_trajectory_llm.py --root .. --data ../../data_v1_share --split dev
python run_trajectory_llm.py --root .. --data ../../data_v1_share --split core
python score_trajectory.py --root ..  &&  python plot_trajectory.py --root ..
python build_table3.py --root ..
```
`--mock` runs the whole LLM path with a fake model (no key, no cost). It was used to test parsing, retries, caching, scoring and plotting.

## Folder map
```
forecast_protocol.md        frozen rules (labels, grid, inputs, output repair, metrics, deviations from plan)
trajectory_feasibility.md   counts and support checks behind the 24-month window
trajectory_label_audit.csv  independent re-derivation of all 100 labels from USPTO transactions
trajectory_eligible_ids*.csv
gold/                       scoring-only labels (never model input)
inputs/                     model inputs (core / dev / test300), training labels, test features, time grid
prompts/                    trajectory_forecast.txt (hash 8fa99d848c11, frozen)
code/                       build, baselines, LLM runner + Colab notebook, scorer, plot, Table 3 merge
outputs/D/                  per-case predictions (KM, Cox; LLM after your run), raw cache, model manifest
logs/D/                     usage_log.jsonl (created on the first LLM call)
metrics/D/                  trajectory_metrics.json/.csv (+ _test300)
results/                    plot, Table 3 pilot files, task_status, weekly summary, next actions, submission template
review/                     OA review form + how-to
```
