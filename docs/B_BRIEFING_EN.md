# B classification pilot: English briefing (updated October 7, 2026)

We used A’s existing Drive dataset and applied an internal time split with no train/test patent-family overlap under the supplied and locally audited mappings. The training observation period ended on December 31, 2013. We used 32 applications for training and 25 for testing, and excluded one boundary case whose outcome was not yet available at the training cutoff. The test set contains 17 CTNF/CTFR events and eight notices of allowance.

We completed a majority-prior baseline and three fixed logistic regression configurations. LR-time uses two date intervals. LR-content adds four indicators for explicit O1 rejection language under Sections 101, 102, 103, and 112, plus O1 body length. LR-reply instead adds A1 remarks length, a claim-change indicator, and a canceled-status indicator to LR-time. All LR configurations use the same split, C=1, and a probability threshold of 0.5. Preprocessing is fitted only on training data.

| Method | Test N | Accuracy | Positive-class F1 | Brier score ↓ |
|---|---:|---:|---:|---:|
| Majority prior | 25 | 0.6800 | 0.8095 | 0.2206 |
| LR-reply — current LR baseline | 25 | 0.6400 | 0.7805 | 0.2645 |
| LLM zero-shot | 25 planned | pending | pending | pending |

Supplementary results:

| Configuration | Test N | Accuracy | Positive-class F1 | Brier score ↓ |
|---|---:|---:|---:|---:|
| LR-time — original baseline | 25 | 0.6000 | 0.7500 | 0.2576 |
| LR-content — exploratory | 25 | 0.3200 | 0.4516 | 0.4164 |


LR-content did not improve performance on this test set. LR-reply increased accuracy from 60% to 64% relative to LR-time, but its Brier score was worse and it still did not exceed the majority baseline. The majority model predicted positive for every case. LR-time and LR-reply also had zero NOA recall; their balanced accuracies were 0.4412 and 0.4706. Positive-class F1 alone therefore does not show that these models can distinguish allowance cases.

We read 57 native O1 texts and the A1 remarks for all 57 included applications. Reviewed claim markup was available for 56. Missing claim indicators for application 14950996 were imputed from training data, not assumed absent. Canceled status does not establish a newly canceled claim relative to O1. No next-action text was used as input. The features are coarse proxies: LR-reply uses reply content, but does not semantically model the legal arguments or account for examiner effects. Negative labels require observed NOA; pending outcomes are not evaluated, and this is not a censoring-aware model.

The content and reply extensions were proposed after inspecting the original test results, so both are exploratory. We retained their fixed specifications and did not tune against the new test scores. We use LR-reply as the current presentation baseline because it incorporates reply information, while retaining its exploratory status. This was a later presentation decision, not the originally fixed comparison. We do not claim a reliable content effect from this small sample.

The user manually verified the source documents for two cases originally selected using LR-time. For the current LR-reply presentation, the same cases remain a true positive and a false positive respectively. Application 14857422 was a true positive: O1 CTNF on April 19, 2016, reply on September 19, and next CTFR on December 7. The remarks cite O1 on PDF page 1, printed body page 6; the next-action citation page is not yet recorded. Application 14665041 was a false positive: O1 CTNF on August 24, 2016, reply on January 20, 2017, and NOA on April 4. The remarks cite O1 on PDF page 2, printed body page 10; the next-event evidence is on NOA PDF page 5. Their dates, labels, and reply relationships were confirmed. The current LR-reply positive-class probabilities are 0.8325 for 14857422 and 0.8367 for 14665041; both predictions are 1. The cases were not reselected using the new model.

The current main presentation compares Majority, LR-reply, and LLM. LR-time and LR-content are supplementary. LR-reply remains exploratory because it was introduced after the original test results had been inspected; the presentation change improves task alignment and does not establish improved performance. C has received the same 25 classification test IDs and the 17-case positive test subset for generation. We will score the LLM probabilities consistently and combine the classification table with A’s audit, C’s generation results, and the verified examples. LLM scores, generation metrics, and the uncalibrated judge results remain pending. This is an internal pilot, not an evaluation on all 58 eligible cases.
