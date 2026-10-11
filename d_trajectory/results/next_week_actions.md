# Next-week actions (draft by D; others add their items)

## To confirm with the mentors
1. **Censoring weights for C-idx and IBS.** The plan says to estimate them from the training labels. test_core has no censored case, so we use
   weight 1 for every case and report the training-weight version as a sensitivity check (IBS ≈ 0.19 vs ≈ 0.27).
   OK to keep this as the primary choice?
2. **Abandonment date:** the date the notice was mailed (now, matching "recorded abandonment") or the legal abandonment date
   (the day after the reply deadline, often several weeks earlier)?
3. **Revived abandonments** (3 of 24 in test_core) stay "abandonment" under the first-event rule. Keep this, or treat revival as continued prosecution?
4. **Scope of the trajectory task in the paper:** Table 3 scores the time to the first disposition of either kind. Do we also need
   cause-specific scores (allowance vs abandonment) and the Remaining Rounds / Time-to-Next-Action columns of the appendix forecasting table?
   The data already has a `remaining_oas` label.

## Data and evaluation work before the formal experiment
0. **GPT-5-mini forecasts are too slow and do not beat the training curve** (IBS 0.22–0.25 vs 0.19; C-idx 0.49–0.55, all intervals include 0.5),
   and adding A's state did not help. Ideas to test on dev cases only: give the model the training-curve base rates (share allowed / abandoned by
   12 and 24 months), ask for the hazard per 6-month block instead of 24 monthly numbers, or average 3 samples to
   reduce the run-to-run noise (risk scores of the two runs correlate only 0.23).
5. Done 10/10: the trajectory task was run with A's predicted A1 state (main setting) and with history only.
6. **Training cohort shift:** training cutoffs (2008–2013) resolve more slowly than test cutoffs (2014–2017).
   Options: move the training information cutoff later and test on later cutoffs, or add calendar year as a covariate to the reference models.
7. **Score the 300-case extension** (299 eligible) once the core results are final, for tighter intervals (Cox C-idx interval width drops from ±0.07 to ±0.04).
8. **PDF check of NOA/ABN notices:** A checks 2 trajectory labels (14031839, 14400543) against the notice PDFs, which are not downloaded yet.
9. **Family-clustered bootstrap:** fine as is for test_core (one case per family). Make it explicit once later rounds (t > 1) add several examples per application.
10. **Memorization check:** the LLM may recognize issued patents. Compare scores on cases whose application number is masked in the text vs left in
    (a small ablation on about 20 cases).

## Process
11. Each member saves metrics in the shared template (`results/metrics_submission_template.csv` → `results/submissions/<X>_metrics.csv`),
    so Table 3 merges automatically (`code/build_table3.py`).
