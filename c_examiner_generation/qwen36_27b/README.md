# Qwen3.6-27B Examiner Generation

Fixed 50-case gen_core; same GPT-derived state and frozen generation prompt as the GPT baseline.

Generator: Qwen3.6-27B, Azure Global Managed Compute, provider-default thinking/sampling, max_tokens 8192 / one length retry 16384, JSON prompt only.
Judge: GPT-5-mini-2025-08-07, low, 8192 / one length retry 16384, same frozen rubric.

| Metric | Value | Scored / eligible |
|---|---:|---:|
| R-L | 0.14527440366538436 | 44/50 |
| MET. | 0.11242277459542982 | 44/50 |
| Judge | 2.5 | 44/50 |

Means are over scored cases. See metrics/C for failure counts, schema checks and paired Qwen-minus-GPT comparisons on the same valid cases.
No claim that Qwen defaults equal GPT low. All model text and failures are preserved. GPT self-preference and missing independent prior-art evidence remain evaluation limitations.
Qwen compute is billed by GPU time, not the GPT token rate; billing reconciliation is pending unless actual costs are supplied.
A's prior support/edit review is not repeated for this model. Qwen OA student review is a separate optional review and must not be marked completed using GPT ratings.
The original GPT experiment is unchanged. Stored keys are not part of this archive.
