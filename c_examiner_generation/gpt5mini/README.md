# Examiner Generation: Week 3 Pilot

This directory contains Part C of the ProsecutionBench Week 3 pilot. The task is to predict the next examiner communication after an observed applicant response, using the prosecution history available at that point and A's predicted claim state. Part C contributes the **R-L**, **MET.**, and **Judge** columns under **Examiner Generation** in Table 3\.

## Data and experimental setting

The run uses `data_v1_share.zip`, version **v1.2**, with the fixed **50-case `gen_core` subset**. The three development cases are separate from the reported core results. Earlier data snapshots are not used for this run.

Generation inputs contain the observed A1 response, documents dated on or before the A1 cutoff, and A's predicted A1 state. The actual next communication, O2, is held out from generation and used only for evaluation. A's state is a model extraction rather than gold annotation; the settings below describe C's generator and judge, not A's upstream extraction.

| Setting | Value |
| :---- | :---- |
| Provider and deployment type | Azure, Global Standard |
| Generator | `gpt-5-mini-2025-08-07` |
| Judge | `gpt-5-mini-2025-08-07` |
| Input condition | `state_with_history`, without a personalized profile |
| Reasoning effort | `low` |
| Completion limit | 8,192 tokens; one retry at 16,384 if truncated |
| Temperature | Not set |
| Prompt and rubric | Frozen after development checks |

&nbsp;

The frozen hashes and settings are recorded in [config/frozen\_protocol.json](http://config/frozen_protocol.json). Saved outputs retain the dataset `input_hash`, exact `model_input_hash`, `prompt_hash`, and `request_hash` for tracing each call. The generation prompt and judge rubric are stored under `prompts/`.

## Results

All 50 generation calls completed with `finish_reason=stop`. Of these, **39 passed the output schema and 11 were marked `invalid_output`**, giving **78% schema-valid coverage**. One case required the prescribed 16,384-token retry.

| Table 3 metric | Mean | Eligible | Scored | Unscored |
| :---- | ----: | ----: | ----: | ----: |
| R-L | 0.167773 | 50 | 39 | 11 |
| MET. | 0.220244 | 50 | 39 | 11 |
| Judge | 2.051282 / 5 | 50 | 39 | 11 |

&nbsp;

The means are calculated over the **39 scored cases**, not all 50\. The remaining cases are not assigned zero or removed from the coverage report. Scores on the usable subset may differ from performance across the complete set.

- **R-L:** ROUGE-L F1 against the full observed O2 text, with Porter stemming.  
- **MET.:** NLTK METEOR with lowercase alphanumeric tokens and WordNet (`alpha=0.9`, `beta=3`, `gamma=0.5`).  
- **Judge:** the frozen rubric's overall 1-to-5 score. The rubric also assesses disposition, grounds, evidence, and reasoning.

Full O2 text is the primary reference. Scores against the substantive-text reference and the copy-O1 baseline are separate diagnostics in the detailed metrics. Generator and judge use the same model, so the judge scores are not independent expert assessments.

The submitted values and coverage counts are in [results/C\_metrics.csv](http://results/C_metrics.csv). Detailed statistics and per-case scores are in [metrics/C/](http://metrics/C/). These paths preserve the `source_file` reference in the submission CSV.

## Failure analysis

The 11 invalid records include grounds outside the current schema (`112d`, `112f`, and unspecified `112`), combined grounds such as `102 | 103`, and combined status values. These failures mix schema coverage limitations with outputs that do not select a single permitted category. A schema failure alone does not establish that the generated prose is substantively incorrect.

A conservative surface-format normalization check was added after the first core run. It **recovered zero cases**; the original model text, prompts, settings, and 39/50 coverage remain unchanged. No unspecified Section 112 category or combined ground was reassigned by guessing. The submitted metric notes retain this postprocessing history.

Two diagnostics identify priorities for the next iteration:

- Among the 39 schema-valid cases, reference document codes are **35 CTFR and 4 CTNF**, while predictions are **2 CTFR and 37 CTNF**. Code agreement is **6/39 (15.4%)**. This is agreement with the recorded communication code, not a separate measure of allowance or rejection accuracy.  
- The token-normalized citation-location check found **181 of 314 cited passages (57.6%)** in their named input documents. The other passages require inspection. A location match does not establish evidential support, and an unmatched passage does not by itself establish fabrication.

The selected higher- and lower-scoring cases are documented in [results/generation\_examples.md](http://results/generation_examples.md). They are diagnostic examples, not expert endorsements. Quality and citation problems in structurally valid outputs remain in the scoring set.

## Team handoffs and review

| Recipient | Deliverable | Purpose |
| :---- | :---- | :---- |
| A | `C_to_A_review_return.zip` | Return the ten-unit evidence-support calibration and three-case claim-edit review, with associated agreement statistics |
| B | `C_to_B_baseline.zip` | Provide the no-profile baseline, exact inputs, frozen prompt and settings, and matching scoring code for paired personalized experiments |
| D | `C_metrics.csv` | Supply C's three Table 3 columns with coverage and failure counts |
| D | `C_to_D_5_OA_review.zip` | Supply the fixed five-case student review set, comprising four schema-valid outputs and one failure audit |

&nbsp;

The five review IDs are retained without replacing the failed case. Completed OA reviews and failure audits must be reported separately. The checked handoff snapshot does not contain D's completed ratings; the review summary should be added when her form is returned.

The A evidence-support calibration is a separate review task and does not calibrate the numeric Examiner Generation judge. Student labels, including any AI assistance, should be described according to how they were obtained. Neither student agreement nor agreement with historical O2 establishes expert legal validity.

## Files and archive

The GitHub directory contains the core generation and scoring code, frozen prompts and protocol, dependency list, metrics, and case analysis. The full experiment records and recipient-specific packages are stored in the project's shared Google Drive.

**Shared Google Drive folder:** `https://drive.google.com/drive/u/0/folders/13005JGWHe--HmMBTDgxpAbbzN30fJCnW`

The formal archive is `C_Week3_Submission.zip`. Use the shared archive for prepared inputs, held-out references, saved generation and judge outputs, and review materials. The lightweight GitHub directory alone does not contain all data needed to rerun the experiment.

To recompute metrics, use `code/score_generation.py` with the matching prepared inputs, O2 references, and saved outputs from the archive. New model calls require a separately configured Azure endpoint and a private API key. Keep the frozen protocol unchanged when reproducing this run; changes to the model, input condition, prompt, or decoding parameters should be reported as a separate experiment.

&nbsp;