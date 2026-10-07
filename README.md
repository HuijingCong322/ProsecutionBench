# ProsecutionBench — weekly classification pilot

Work for the October 5–11, 2026 revised plan, focusing on B's labels, classification baselines and C handoff. No independent training cohort or new USPTO downloads are required for this pilot.

## Completed experiment

The A-provided data has 58 classification-eligible applications. A fixed calendar boundary of 2013-12-31 yields 32 training cases (20 positive / 12 negative), 25 test cases (17 positive / 8 negative), and one boundary exclusion whose label was not yet available. Three development pilots and the restriction/other case are not scored. Training/test families were checked using A's grouping and a local PatEx continuity audit.

Positive means the next relevant notification is CTNF/CTFR; negative means NOA. CTFR does not necessarily contain a claim rejection (14723918 is a documented exception). Features are days from filing to O1 and O1 to reply cutoff. Preprocessing is fitted only on training cases. Logistic regression is fixed at C=1, lbfgs, max_iter=1000, seed=42; decision threshold is 0.5. Majority probability is the training positive proportion, 0.625.

| Method | Test N | Accuracy | Positive F1 | Brier ↓ |
|---|---:|---:|---:|---:|
| Majority prior | 25 | 0.68 | 0.8095 | 0.220625 |
| LR-time | 25 | 0.60 | 0.75 | 0.257641 |
| LR-content (exploratory) | 25 | 0.32 | 0.4516 | 0.416368 |
| LLM zero-shot | 25 | pending | pending | pending |

These are small-sample internal holdout results, not scores on all 58 cases or evidence of benchmark-wide effectiveness. LR did not outperform Majority in this run.

## Reproduce

Python 3.11+ is required. The recorded run used scikit-learn 1.9.1; use the recorded version to reproduce the numerical checks.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[baseline,test]'
python -m pip install 'scikit-learn==1.9.1'
python scripts/reproduce_week.py
python -m pytest -m 'not live' -q
```

The reproduction script verifies saved metrics and writes a new ignored `outputs/reproduced_week/` directory. Existing output directories are not overwritten. No API key is needed for reproduction. Live ODP acquisition is separate and requires `USPTO_API_KEY` in the process environment; existing acquisition endpoints have not been validated live in this weekly run.

## Files and C handoff

- `results/week_2026_10_05/`: frozen labels, features, splits, per-case probabilities, metrics, provenance and run configuration.
- `results/week_2026_10_05/C_handoff/`: 25 classification test IDs, 17 proposed generation IDs from the held-out positives, a scoring-only gold file, and the three-method classification table with the LLM row pending.
- `docs/`: baseline and data preparation notes. Earlier large-cohort preparation is optional background, not a prerequisite for this weekly experiment.
- `src/prosecution_data/` and `tests/`: acquisition, timeline, candidate-label, family-audit and baseline utilities with fixtures.

C must score occurrence on the same 25 test IDs to compare with B. The 17 generation IDs are a proposed shared internal-test scope; generation on all 37 eligible A cases should be reported as a separate scope. Only cutoff-available inputs may enter prediction. The gold file, future target text and future label dates are for scoring only.

## Verification and outstanding work

Labels use A's reply/date correspondence verification records. `document_verified` in the experiment input records A's verification, not independent B review of every PDF. Raw records and original documents remain in the shared A dataset. Family completeness and historical source coverage remain limitations.

B's two baselines and test checks are complete. LLM classification, G0/G1/G2 generation, text/judge metrics, five-case human checks and the merged weekly presentation remain pending with C/team coordination. Related work is outside the requested scope.

No full PatEx CSVs, PDF corpus, API credentials or serialized model are committed. The small committed CSVs contain patent application IDs, dates and research annotations needed for this run. Fixtures are for code testing and must not be reported as model evaluation data.

## Exploratory O1-content extension

LR-content adds explicit O1 rejection-language indicators under Sections 101, 102, 103 and 112, plus whitespace-normalized native OA body length, to the two time intervals (seven features). The split, C=1, solver, iteration limit, seed and threshold are unchanged. All preprocessing is fitted on the 32 training cases. No next-action text is used. The original LR-time remains the primary LR baseline; no model is selected based on the test score.

The new configuration was specified after the original test scores were inspected. Its lower accuracy (32%) and higher Brier (0.416368) are exploratory observations, not evidence that content features are generally ineffective. Statute flags are rule-based and do not cover all grounds: 13293637 contains a nonstatutory double-patenting rejection, so all four fixed statute flags are zero. The extraction patterns and edge-case tests are versioned; raw O1 texts, quotations and Drive access links are not published.

```sh
python scripts/reproduce_lr_content.py
```

This verifies the saved 25 per-case probabilities and metrics using the frozen feature table, and writes a new ignored `outputs/reproduced_lr_content/` directory. It does not require access to the shared Drive. The default output directory must not already exist; use `--output-dir` for another run.

See `results/week_2026_10_05/lr_content/` for features, derived predictions, aggregate metrics, parameters and O1 content hashes, and `docs/LR_CONTENT_BRIEFING.md` for the updated presentation. LLM and generation results are still pending.
