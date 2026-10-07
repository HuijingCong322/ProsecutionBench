# Updated classification briefing: LR-content

We retained the original 32-training / 25-test time and family split. In addition to LR-time, we ran a fixed exploratory LR-content configuration with seven features: the two date intervals, four indicators for explicit O1 rejection language under Sections 101, 102, 103 and 112, and the normalized O1 body character count. Only O1 texts matched to the recorded document IDs and dates were used; no next-action text entered the features.

| Method | N | Accuracy | Positive F1 | Brier ↓ |
|---|---:|---:|---:|---:|
| Majority prior | 25 | 0.68 | 0.8095 | 0.2206 |
| LR-time | 25 | 0.60 | 0.7500 | 0.2576 |
| LR-content — exploratory | 25 | 0.32 | 0.4516 | 0.4164 |
| LLM zero-shot | 25 planned | pending | pending | pending |

Adding this fixed feature set did not improve performance on this test set. We did not change the split, C=1, solver, iteration limit, seed or threshold, and did not tune after observing the new scores. Because the original test results had already been inspected, the extension is exploratory; these small-sample scores do not establish that content features are generally ineffective or identify the cause of the decrease. All preprocessing was fitted on the training cases only.

The statute indicators are rule-based and omit grounds such as nonstatutory double patenting. Zero statute flags do not imply an absence of rejections. Majority predicts every case as positive, so its 68% accuracy reflects the positive fraction of this test set.

Next, score C's LLM on the same 25 IDs. Keep Majority, LR-time and LLM as the originally planned main comparison; report LR-content as an additional exploratory row. Generation and uncalibrated judge results remain pending.
