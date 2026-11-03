# B Examiner Prediction — completed phase 2 (reviewed v4)

Completed November 2, 2026: GPT-5-mini and Qwen3.6-27B, each with no-profile (reused), own-profile and mismatched-profile conditions. All 400 new predictions ultimately succeeded. This is B Occ./Type/Grnd. only; artunit, C generation and D trajectory are outside this run.

See [RESULTS_ANALYSIS.md](RESULTS_ANALYSIS.md), [metrics.csv](metrics.csv), [comparison.json](comparison.json), [RUN_MANIFEST.json](RUN_MANIFEST.json) and [VERIFICATION.json](VERIFICATION.json).

Own-profile Occ. AUROC improves over no-profile for both models: GPT +0.2026 (95% paired CI [0.0720, 0.3210]); Qwen +0.1362 ([0.0301, 0.2493]). Type gains are supported for GPT but Qwen's interval crosses zero. Ground gains are not established. These are exploratory results under automatic, not independently reviewed, labels; no blanket improvement or causal examiner-identity claim is made.

## Fixed scope and scoring

Occ./Type use the same 99 eligible core cases; restriction case 14572445_t1 is excluded. Grnd. uses 62 cases, preserving unknown labels and the historical whole-case 112d taxonomy exclusion for 14012315_t1. Unknown grounds are never empty sets. [eligibility.csv](eligibility.csv) enumerates all 100 inputs and reasons.

Three-class macro-F1, Occ. AUROC and claim-ground micro-F1 retain original definitions. All contrasts use the common successful cohort. Family-paired percentile bootstrap uses 1,000 draws, seed=20261010. There is no multiple-comparison correction. A provides 100 distinct family IDs for the core inputs; family coverage is not independently exhaustive.

The authoritative [reviewed phase-1 release](../profile_phase1/reviewed_v4/README.md) supplies the 300 locked profiles (293 k3, one k2, one k1, five statistics-only). Only own and mismatched are run here; incomplete-k and statistics-only variants remain included. Only JSON profile_text is appended to original fixed inputs/states. The two model-specific inference settings differ; strict budget equivalence is not claimed.

## Source archive and team-only reproduction

`code/` preserves the exact original adapters, second-phase wrapper and Qwen concurrent scheduler. `prompts/` preserves the frozen predictor and shared profile template. Tests are archived in `tests/`; they expect the original private team B directory and inputs. This public archive alone cannot rerun the model calls or independently reconstruct bootstrap distributions from aggregate scores.

To reproduce using the team package, place these source snapshots in the original `week10_11/B/` layout, retaining frozen settings, locked reviewed profiles, benchmark inputs and scoring gold. Source hashes must match RUN_MANIFEST and the private preparation locks. Do not regenerate or overwrite a completed private run merely to use this archive.

Original commands (from the team project root):

```sh
.venv/bin/python week10_11/B/b_phase2_prediction.py dev --model gpt --interval 3
.venv/bin/python week10_11/B/b_phase2_prediction.py core --model gpt --interval 3
.venv/bin/python week10_11/B/b_phase2_prediction.py dev --model qwen --interval 3
.venv/bin/python -u week10_11/B/b_qwen_phase2_concurrent.py --workers 2 --interval 3
.venv/bin/python week10_11/B/b_phase2_prediction.py compare
```

Credentials are process environment variables only. Qwen concurrency initially used four workers and was reduced to two during retries; request configurations and successful caches remain unchanged. The serial runner defaults to 65 seconds and the concurrent scheduler to zero seconds unless --interval is supplied; the commands above explicitly use three seconds. Provider Retry-After may impose a longer wait.

Live dev checks used three early dev inputs with explicitly empty/synthetic profiles: no qualifying empirical dev history was supplied. Offline mock checks were separate, unscored and never used as real model results. Both models' live dev gates passed before core.

## Publication boundary

Only source code, prompts, manifests, derived score summaries and review records are published. Profile JSONs/profile_text, patent/source excerpts, full inputs, raw API responses, per-case predictions, keys and the complete team review ZIP stay in the private team package. Returned model IDs/configurations were checked; historical GPU/template identity was not independently verified. Contact-examiner attribution, censoring-tail interpretation, approximate grounds, partial-k coverage and other phase-1 limits remain in force.
