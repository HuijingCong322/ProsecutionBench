# ProsecutionBench — weekly classification pilot

Work for the October 5–11, 2026 revised plan, focusing on B's labels, classification baselines and C handoff. No independent training cohort or new USPTO downloads are required for this pilot.

## Completed experiment

The A-provided data has 58 classification-eligible applications. A fixed calendar boundary of 2013-12-31 yields 32 training cases (20 positive / 12 negative), 25 test cases (17 positive / 8 negative), and one boundary exclusion whose label was not yet available. Three development pilots and the restriction/other case are not scored. Training/test families were checked using A's grouping and a local PatEx continuity audit.

Positive means the next relevant notification is CTNF/CTFR; negative means NOA. CTFR does not necessarily contain a claim rejection (14723918 is a documented exception). The current presentation LR baseline is LR-reply: two date intervals plus A1 remarks length, a claim-change proxy, and a canceled-status proxy. Preprocessing is fitted only on training cases. Logistic regression is fixed at C=1, lbfgs, max_iter=1000, seed=42; decision threshold is 0.5. Majority probability is the training positive proportion, 0.625.

| Method | Test N | Accuracy | Positive F1 | Brier ↓ |
|---|---:|---:|---:|---:|
| Majority prior | 25 | 0.68 | 0.8095 | 0.220625 |
| LR-reply (current LR baseline, exploratory) | 25 | 0.64 | 0.7805 | 0.264450 |
| LLM zero-shot | 25 | pending | pending | pending |

Supplementary: LR-time = 60% accuracy / 0.7500 F1 / 0.257641 Brier; LR-content = 32% / 0.4516 / 0.416368.


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

Majority, LR-time, LR-content and LR-reply runs are complete; the current main presentation uses Majority and LR-reply. LLM classification, G0/G1/G2 generation, text/judge metrics, five-case human checks and the merged weekly presentation remain pending with C/team coordination. Related work is outside the requested scope.

No full PatEx CSVs, PDF corpus, API credentials or serialized model are committed. The small committed CSVs contain patent application IDs, dates and research annotations needed for this run. Fixtures are for code testing and must not be reported as model evaluation data.

## Exploratory O1-content extension

LR-content adds explicit O1 rejection-language indicators under Sections 101, 102, 103 and 112, plus whitespace-normalized native OA body length, to the two time intervals (seven features). The split, C=1, solver, iteration limit, seed and threshold are unchanged. All preprocessing is fitted on the 32 training cases. No next-action text is used. LR-time is retained as the original supplementary baseline. LR-reply was selected for the current presentation to incorporate reply information; the later change is transparent and remains exploratory.

The new configuration was specified after the original test scores were inspected. Its lower accuracy (32%) and higher Brier (0.416368) are exploratory observations, not evidence that content features are generally ineffective. Statute flags are rule-based and do not cover all grounds: 13293637 contains a nonstatutory double-patenting rejection, so all four fixed statute flags are zero. The extraction patterns and edge-case tests are versioned; raw O1 texts, quotations and Drive access links are not published.

```sh
python scripts/reproduce_lr_content.py
```

This verifies the saved 25 per-case probabilities and metrics using the frozen feature table, and writes a new ignored `outputs/reproduced_lr_content/` directory. It does not require access to the shared Drive. The default output directory must not already exist; use `--output-dir` for another run.

See `results/week_2026_10_05/lr_content/` for features, derived predictions, aggregate metrics, parameters and O1 content hashes, and `docs/LR_CONTENT_BRIEFING.md` for the updated presentation. LLM and generation results are still pending.

## Reply-informed LR and updated briefing

LR-reply uses five frozen features and the same 32/25 split. All 57 cases have remarks text; 56 have reviewed claim markup. The missing claim flags for 14950996 stay blank and are imputed using training medians. This is reply-informed proxy modeling, not semantic understanding or an examiner-effects model. Pending outcomes are not negative labels and are not evaluated in this observed-outcome pilot.

LR-reply has NOA recall 0 and balanced accuracy 0.4706. Its 64% accuracy is higher than LR-time, but its Brier score is worse and it does not exceed Majority. It was proposed after the original scores were inspected, so its current presentation role does not make it a prospectively specified baseline. The test IDs and threshold remain unchanged.

```sh
python scripts/reproduce_lr_reply.py
```

Reproduces the saved probabilities from committed derived features without Drive or API access. See `results/week_2026_10_05/lr_reply/`, `primary_metrics.json`, `primary_baseline.json`, and `docs/B_BRIEFING_DRAFT.md` / `docs/B_BRIEFING_EN.md`. Root `metrics.json` and `lr_predictions.csv` retain LR-time history. Raw reply/O1 text, excerpts, model binaries and source-access URLs are not added.
