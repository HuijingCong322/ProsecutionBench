# Trajectory Forecasting: feasibility check (before freezing, 2026-10-10)

**Verdict: feasible as planned.** C-index and IBS with a 24-month horizon can be estimated on `test_core`, and no time
window has to be shortened.

## Counts
| | N | NOA | Abandonment | Censored | Incomplete |
|---|---:|---:|---:|---:|---:|
| test_core | 100 | 76 | 24 | 0 | 0 |
| test (300 extension) | 300 | 218 | 81 | 0 | 1 (14756161) |
| training pool (censored at 2013-12-31) | 478 | 264 | 50 | 164 | 0 |

## Event timing on test_core (days from A1 to the outcome)
| | by 12 months | by 24 months | after 24 months |
|---|---:|---:|---:|
| NOA | 67 | 71 | 5 |
| Abandonment | 7 | 18 | 6 |
| Neither yet | 26 | 11 | |

- Shortest outcome 11 days, longest 3,029 days. The grid (30 to 730 days) lies inside the observed range, which is a requirement of scikit-survival.
- Medians: NOA 130 days; abandonment 568 days. The earliest abandonment is at 7.0 months, which fits the 6-month maximum reply period.
- Comparable pairs for C-index at τ = 24 months: 4,892 of 4,950.

## Training support for the Kaplan–Meier reference
- Follow-up after censoring: median 157 days, max 1,217 days.
- Still at risk at 12 months: 106; at 24 months: 32. The training curve is usable to 24 months but thin past ~18 months.
- Censoring survival from the training data: G(12m) = 0.62, G(24m) = 0.32. This is why weights from the training data are a poor fit for the
  uncensored test set (see protocol section 9).

## Decisions taken from this check
1. Keep the 24-month horizon and the monthly grid.
2. Primary censoring weights = from the evaluation labels (no test censoring); training weights = sensitivity analysis.
3. Add `excluded_time_boundary` (30 cases) to the training pool as censored cases, to avoid selecting on future dates.
4. Score the 300-case extension only after the core results are final; 299 eligible.
