# BGE-M3 shared profiles: Qwen prediction experiment

Public update, checked 2026-11-09. Qwen own and mismatched conditions each contain **100/100 successful outputs**. The original no-profile100 baseline was verified and reused without new control requests. GPT and art-unit prediction experiments were not launched by this entry point. Previous snapshots, cards, prompts, inputs and results were preserved.

This folder contains source code, prompt templates, tests and **aggregate** results only. Full profiles, patent source texts, source/link tables, review packets, model input messages, per-case predictions, raw responses, usage logs, caches, credentials and team ZIPs remain outside this public update.

## Frozen method and interpretation

Shared release: `B_shared_BGE_M3_dense_v1_2026_11_05`. BAAI/bge-m3 revision `5617a9f61b028005a4858fdac845db406aefb181`, dense CLS only, normalized cosine, no E5 prefixes, sparse, ColBERT or reranker. The [retrieval implementation](../retrieval_bgem3/README.md) describes source eligibility, complete long-text windows and cache binding.

All300 final shared profiles passed automatic checks. Semantic review covered the original fixed ten cases/all30 variants after the separate three-case retrieval precheck; it is Codex technical review, not human D/C signoff. Forty-seven weak histories were withheld without replacement. Across own/mismatched/artunit, effective k3/k2/k1/k0 remains275/10/5/10; these totals describe300 shared profiles, while this experiment uses only own/mismatched200.

Model: Azure Qwen3.6-27B, expected response model `qwen--qwen3.6-27b`, with the unchanged frozen prediction prompt and GPT-derived state. Provider-default thinking/sampling, initial8192 output-token budget, existing truncation retry16384, original schema/model validation and no implicit API retries. This is a Qwen predictor using fixed GPT-derived state, not an end-to-end Qwen extraction pipeline. GPT/Qwen inference budgets are not claimed equivalent.

Only `profile_text` is appended to the original user message. Profile/file/text/card hashes, sample mapping, revision, embedding contract and the team-only historical-link path/hash stay in request provenance outside model messages. Controls and review notes are never appended.

The change from the old TF-IDF workflow includes technical text representation, encoder and review-adjusted coverage. These scores do not isolate an encoder-only causal effect. Gold remains automatic/unreviewed; independent human gold review is still required.

## Aggregate results

Recomputed from all saved records with the frozen scorer in a temporary directory, with **no API calls and no mutation of the saved run**. The recomputation exactly matched the existing local comparison. All three conditions succeed on100 cases; Occ./Type use99 after the original restriction exclusion, and Grnd. uses62 after unknown labels and the existing112d whole-case exclusion.

| Condition | Occ. AUROC (99) | Type macro-F1 (99) | Grnd. micro-F1 (62) |
| --- | ---: | ---: | ---: |
| No profile, reused | 0.6495 | 0.4081 | 0.2944 |
| Own BGE-M3 profile | 0.7617 | 0.4783 | 0.3884 |
| Mismatched BGE-M3 profile | 0.6382 | 0.3968 | 0.3038 |

| Paired difference | Occ. delta [95% CI] | Type delta [95% CI] | Grnd. delta [95% CI] |
| --- | --- | --- | --- |
| Own minus no profile | +0.1122 [-0.0110, 0.2412] | +0.0701 [0.0034, 0.1365] | +0.0940 [-0.0036, 0.2111] |
| Mismatched minus no profile | -0.0112 [-0.1280, 0.1131] | -0.0113 [-0.0890, 0.0611] | +0.0095 [-0.1203, 0.1441] |
| Own minus mismatched | +0.1235 [-0.0012, 0.2581] | +0.0815 [0.0153, 0.1515] | +0.0845 [-0.0315, 0.2048] |

Paired family bootstrap1000 draws, seed20261010, percentile95% intervals, using the same complete-case cohort and metric eligibility for every contrast. Supplied family IDs retain their original coverage limitations. Type intervals exclude zero for the two own contrasts; Occ./Grnd. intervals include zero. No general performance or encoder-only claim follows from this single run. Machine-readable aggregate values are in `aggregate_comparison.json`. Usage records remain separate from this performance report.

## Execution and recovery

`code/` archives exact runtime sources from the private workspace at `week10_11/B/`; the code hashes used by the sealed local experiment are not rewritten for a public path layout. To run privately, restore these files at that original location with the separately supplied A/D packages, reviewed release, base/state inputs, gold and frozen settings. This public checkout alone does **not** contain the data needed for prepare/dev/core/compare. Keep those inputs private. Never mix a changed code/dependency version into an existing prepared run.

From that private workspace, in zsh:

```zsh
read -s 'QWEN_API_KEY?week1011 resource API key (hidden): '
export QWEN_API_KEY
printf '\n'

# No API calls: current completion/cache inventory.
.venv/bin/python week10_11/B/b_bgem3_qwen_prediction.py plan

# For a new prepared experiment, first pass its own three-case live dev.
# Existing completed experiment: do not re-prepare or rerun dev merely to resume.
.venv/bin/python week10_11/B/b_bgem3_qwen_prediction.py dev --interval 5

# Resume: successful exact-match outputs are reused; failures remain explicit.
.venv/bin/python week10_11/B/b_bgem3_qwen_prediction.py core --workers 4 --interval 5
.venv/bin/python week10_11/B/b_bgem3_qwen_prediction.py compare
unset QWEN_API_KEY
```

`--workers` bounds in-flight requests; `--interval` spaces request starts. Core allows interval0; dev requires a positive interval. Shared Retry-After cooldown does not add automatic API retries. Timeouts/HTTP500 errors in the local run were resolved by explicit cached resume. Lower concurrency if needed. Stop and wait for an old process to exit before changing settings; do not launch two coordinators for the same experiment. A command lock prevents competing mutation. Re-prepare refuses an existing experiment directory.

The new three-case live dev is a format/API check on the original development cases with empty/synthetic history; it does not score or tune prompts and is distinct from the completed three-case retrieval precheck. A hash-bound new gate is mandatory even if the old TF-IDF experiment passed dev.

## Verification

Public tests, without private files, model downloads or API calls:

```sh
python -m pip install -r b_examiner_prediction/phase3_bgem3_qwen/requirements.public-tests.txt
python -m pytest b_examiner_prediction/phase3_bgem3_qwen/code/tests -q
```

Result: **33 passed,7 skipped**. The seven private-corpus integration cases explicitly skip when the original private core input is absent; all original runtime source files remain exact copies. The only test adaptation is that explicit private-fixture guard. Locally all10 new launcher tests and the focused27-test Qwen/phase-2/concurrent set pass, including two complete simulated conditions, no additional calls on resume, missing credentials, failed-dev gate invalidation, source/input tampering and command locks. Simulated tests are not model results. Independent code review found no blockers before the run.

The earlier project-default suite passed121 tests with1 skip. The expanded local B suite had153 passes and3 unrelated environment/data failures: an absent legacy C generation-score CSV and two unavailable tokenizer-download tests. These were independently reproduced without importing the new launcher; no older files were edited to suppress them. The new entry point uses frozen text and does not require a tokenizer download.

`PUBLICATION_MANIFEST.json` records the selected public files and hashes. Nothing is staged from the research workspace wholesale, and no full handoff ZIP or review packet is part of this publication.
