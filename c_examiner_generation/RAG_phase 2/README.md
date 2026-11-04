# C Phase 2: Examiner Generation with Reviewed v4 Profiles

This experiment tests whether examiner profiles improve Office Action generation on the fixed 50-case `gen_core` split. Qwen3.6-27B improved on ROUGE-L with the correct profile relative to its own no-profile baseline. GPT-5-mini showed no clear paired improvement.

## Experimental setup

The runner reuses the [frozen C inputs, prompts, adapters and baseline scores](https://github.com/HuijingCong322/ProsecutionBench/tree/b1df977eb63ad04fcb736de7574643fb07a343a0/c_examiner_generation). The profile release is `B_D_C_v4_reviewed_2026_11_02`, distributed as `B_D_C_phase1_v4_reviewed.zip` in the shared Drive.

| Condition | Input |
|---|---|
| `noprof` | A1 state and case history. Reuses each model's archived baseline. |
| `prof` | Same input plus the correct examiner's reviewed profile. |
| `mismatch` | Same input plus the assigned mismatched examiner's reviewed profile. |

Only `profile_text` is appended for the two profile conditions. The generation request excludes the gold next Office Action (O2). All 50 correct profiles contain three retrieved examples. In the mismatched condition, 47 contain three examples and three contain statistics only. All 50 cases remain eligible. Art-unit profiles are optional and were not run.

GPT-5-mini uses the frozen low reasoning setting with no temperature override. Qwen3.6-27B uses the original provider-default settings. Both use the original 8,192-token completion limit and one retry at 16,384 if truncated. The same frozen GPT-5-mini Judge and rubric score both generators. Three separate dev cases with synthetic profile fixtures were used for format checks and excluded from all reported results.

## Results

Each mean is over the valid cases for that model and condition. The denominator is 50; cases with invalid outputs are retained in the failure counts.

| Model | Condition | Scored | R-L | MET. | Judge |
|---|---|---:|---:|---:|---:|
| GPT-5-mini | No profile | 39/50 | 0.1678 | 0.2202 | 2.0513 |
| GPT-5-mini | Correct profile | 37/50 | 0.1675 | 0.2189 | 2.3784 |
| GPT-5-mini | Mismatched profile | 33/50 | 0.1652 | 0.2141 | 2.3333 |
| Qwen3.6-27B | No profile | 44/50 | 0.1453 | 0.1124 | 2.5000 |
| Qwen3.6-27B | Correct profile | 47/50 | 0.1644 | 0.1177 | 2.5319 |
| Qwen3.6-27B | Mismatched profile | 48/50 | 0.1404 | 0.1062 | 2.2292 |

The primary effect is the mean case-level difference between correct profile and no profile, computed on cases scored in both conditions. The 95% intervals use 1,000 case-paired bootstrap draws with seed `20261010`.

| Model | Paired cases | ΔR-L, correct profile minus no profile | 95% CI |
|---|---:|---:|---:|
| GPT-5-mini | 34 | +0.0004 | [-0.0063, +0.0075] |
| Qwen3.6-27B | 43 | +0.0201 | [+0.0042, +0.0358] |

Qwen's correct profile also improved R-L relative to mismatch on 47 scored pairs (Δ +0.0249, 95% CI [+0.0093, +0.0432]). The direction held when both profiles had three retrieved examples (44 scored pairs, Δ +0.0235, 95% CI [+0.0057, +0.0396]). MET. and Judge did not show clear gains over the no-profile baseline for either model. The R-L gains indicate higher overlap with the reference text on the scored pairs. They do not establish better legal reasoning or factual support.

The supplemental statistics-only prior predicts the next action type without generating Office Action text. It made a prediction in 49 of 50 cases, with 36 correct predictions. Its action accuracy is reported separately from R-L, MET. and Judge.

## Table 3 handoff

| File | Use |
|---|---|
| [`submissions/C_metrics.csv`](submissions/C_metrics.csv) | Correct-profile R-L, MET. and Judge rows for both models, including coverage and failures. |
| [`gpt5mini/comparison.json`](gpt5mini/comparison.json) | GPT-5-mini condition means, paired contrasts, failure counts and retrieval coverage. |
| [`qwen36_27b/comparison.json`](qwen36_27b/comparison.json) | Qwen condition means, paired contrasts, failure counts and retrieval coverage. |
| [`statistics_prior_diagnostic.json`](statistics_prior_diagnostic.json) | Supplemental statistics-only action prediction summary. |

For Table 3's **ΔR-L**, use `paired.prof_minus_noprof["R-L"]` in each comparison report. Subtracting the displayed condition means can give a different value because the sets of scored cases differ. Keep the original no-profile rows and the `state_with_history+profile` label on the new correct-profile rows.

## Reproduce the run

Use [`c_phase2.py`](c_phase2.py) from this directory and a separate checkout of the frozen inputs at commit `b1df977eb63ad04fcb736de7574643fb07a343a0`. Extract the reviewed release from the team's shared Drive. Set `SOURCE_REPO` to the checkout, `RELEASE_DIR` to the extracted directory containing `RELEASE_MANIFEST.json`, and `RUN_DIR` to an output directory outside Git.

```bash
python -m pip install -r "$SOURCE_REPO/c_examiner_generation/qwen36_27b/runtime_requirements.txt"
python -m nltk.downloader wordnet

phase2() {
  python c_phase2.py "$@" --repo "$SOURCE_REPO" --release "$RELEASE_DIR" --out "$RUN_DIR"
}

phase2 offline
phase2 preflight --model gpt5mini
phase2 dev --model gpt5mini
# Inspect both dev conditions and their Judge results before approving.
phase2 approve-dev --model gpt5mini
phase2 core --model gpt5mini
phase2 judge --model gpt5mini
# Repeat preflight through judge with --model qwen36_27b.
phase2 score --model both
```

Before live calls, set `AZURE_OPENAI_API_KEY` for GPT-5-mini and the shared Judge, and `QWEN_AZURE_API_KEY` for Qwen. Set the endpoint and deployment overrides for your Azure resources if needed. Keep secrets out of Git. The `offline`, `preflight` and `score` stages do not call either model.

The runner verifies the release, profile hashes and frozen inputs, records per-request provenance, and keeps the two models' outputs in separate directories. Use the same run directory and configuration to resume. The full profile bundle, raw generations, Judge outputs and logs are retained on the shared Drive.
