# D results: profile_with_embedding (run 2026-11-09/10)

Tasks: Disposition, Remaining Rounds, Time to Next Action. The same 100 test_core cases as all D tables, each cut at its
A1 cutoff (the applicant's first reply). Setup and frozen items: `profile_with_embedding_protocol.md`.

## 1. What was run

The mentor asked (2026-11-05) for three things: pick past applications by patent content with an embedding, report the
average of the top 3 first (no LLM), and give the LLM the past applications themselves, not a summary. B built the
search (BGE-M3, abstract + claims, top 3 per case). D ran three ways of giving GPT-5-mini the examiner's past, each with
the case's own examiner and, as a control, a wrong examiner of the same art unit:

| Setup | What the LLM sees about the examiner |
| --- | --- |
| **card** | statistics only, from all of the examiner's past applications before the cutoff (e.g. "Days from a reply to the next letter: median 33") |
| **paths** | the 3 most similar past applications: their dated events and status at the cutoff |
| **fulldoc** | the same 3 past applications in full: abstract, claims, every letter and reply before the cutoff, then their events (the standard RAG) |

Everything else in the prompt (the case's own documents, A's state, the prompt text) is the same in every run.

Run facts:
- 1,200 calls (3 setups × own/wrong × 2 prompts × 100 cases), all answered: 100/100 in every file.
- No answer had to be retried and none was cut off.
- Prompt size: card median ~40k tokens; fulldoc median ~86k, largest 202k (limit 272k).
- Cost about $18. Scores recomputed outside Colab from the output files: identical to the Colab run.

## 2. All methods (100 cases)

C = C-index (higher is better); IBS and MAE: lower is better.

| Method | Disp C | Disp IBS | Rounds MAE | Rounds acc | Next C | Next MAE (days) |
| --- | --- | --- | --- | --- | --- | --- |
| Plain average (KM, no LLM) | 0.500 | 0.188 | 0.99 | 0.37 | 0.500 | 36.3 |
| GPT, no examiner block | 0.493 | 0.248 | 0.99 | 0.41 | 0.560 | 37.3 |
| **Full-history numbers** (no LLM; the card's numbers blended with the art unit) | **0.692** | **0.156** | **0.94** | **0.44** | 0.721 | 27.2 |
| **Top-3 average** (no LLM; math on the 3 most similar) | 0.621 | 0.185 | 1.05 | 0.38 | 0.718 | 28.3 |
| GPT + card, own | 0.680 | 0.159 | 0.96 | 0.43 | **0.723** | **26.7** |
| GPT + card, wrong examiner | 0.561 | 0.201 | 1.04 | 0.40 | 0.497 | 42.0 |
| GPT + paths, own | 0.604 | 0.193 | 1.02 | 0.38 | 0.639 | 31.6 |
| GPT + paths, wrong examiner | 0.591 | 0.193 | 0.99 | 0.45 | 0.541 | 35.9 |
| GPT + fulldoc, own | 0.612 | 0.202 | 1.00 | 0.40 | 0.598 | 33.3 |
| GPT + fulldoc, wrong examiner | 0.603 | 0.196 | 1.07 | 0.34 | 0.519 | 38.0 |
| *Reference: old top-3 average (TF-IDF pick, 11-05)* | 0.626 | 0.211 | 1.04 | 0.35 | 0.704 | 28.9 |
| *Reference: GPT + old paths (TF-IDF pick, 11-05)* | 0.641 | 0.188 | 0.98 | 0.42 | 0.568 | 35.6 |

## 3. Comparisons fixed before the run

Difference = first method minus second, on the same 100 cases; 1,000 paired bootstraps (seed 20261010). **Clear** = the
95% interval does not include 0. Only clear results are listed; everything else showed no clear difference.

**A. fulldoc (the standard RAG)**

| # | Question | Clear results |
| --- | --- | --- |
| A1 | Does it help, vs no examiner block? | Disp C +0.119 [+0.030, +0.202]; Disp IBS −0.047 [−0.085, −0.007] (better). Rounds and next action: not clear |
| A2 | Is it about this examiner (own − wrong)? | Next C +0.079 [+0.001, +0.149]; Next MAE −4.7 days [−8.2, −1.1] (better). Disposition: not clear |
| **A3** | **Does the LLM beat the top-3 average of the same 3 applications? (main)** | **No. Next C −0.120 [−0.200, −0.036] (worse). Nothing clear in its favour** |
| A4 | Do the documents add anything beyond the dated events (fulldoc − paths)? | Nothing clear |
| A5 | fulldoc − card | Disp IBS +0.043 [+0.010, +0.077], Next C −0.125 [−0.200, −0.047], Next MAE +6.5 days [+2.0, +10.9] (all worse) |

**B. paths**

| # | Question | Clear results |
| --- | --- | --- |
| B1 | Own − wrong | Next C +0.098 [+0.027, +0.176]; Next MAE −4.4 days [−8.3, −0.9] (better) |
| B2 | LLM − top-3 average of the same 3 | Nothing clear |
| B3 | paths − card | Disp C −0.077, Disp IBS +0.034, Next C −0.084, Next MAE +4.9 days (all worse) |
| B4 | New search − old TF-IDF search | Next C +0.072 [+0.008, +0.131]; Next MAE −4.0 days [−7.2, −0.8] (better) |

**C. card**

| # | Question | Clear results |
| --- | --- | --- |
| C1 | Does it help, vs no examiner block? | Disp C +0.187, Disp IBS −0.089, Next C +0.164, Next MAE −10.6 days (all better) |
| C2 | Own − wrong | Disp C +0.120 [+0.021, +0.209]; Next C +0.227 [+0.129, +0.316]; Next MAE −15.2 days [−21.0, −8.7] |
| C3 | Does the LLM add anything beyond the card's numbers (no LLM)? | Nothing clear |

**N. no LLM**

| # | Question | Clear results |
| --- | --- | --- |
| N1 | Top-3 average − full-history numbers (mentor's hypothesis) | Disp C −0.071 [−0.126, −0.018]; Disp IBS +0.029 [+0.005, +0.051] (worse). Timing: equal |
| N2 | Top-3 average, own − wrong | Next C +0.231 [+0.141, +0.316]; Next MAE −16.5 days [−23.1, −9.4] |
| N3 | Top-3 average, new search − old search | Nothing clear |

## 4. Does the LLM just copy a number?

For Time to Next Action: how often the LLM's days equal a number it can read or work out from its block.

| Run | Compared with | Exactly equal | Within 3 days | Rank agreement with that number | Rank agreement with the true days |
| --- | --- | --- | --- | --- | --- |
| card, own | the card's median days | **92%** | 93% | 0.99 | 0.60 |
| card, wrong | the card's median days | 92% | 95% | 0.99 | 0.00 |
| paths, own | the top-3 average's days | 1% | 10% | 0.28 | 0.42 |
| fulldoc, own | the top-3 average's days | 4% | 11% | 0.23 | 0.31 |
| paths, wrong | the top-3 average's days | 1% | 4% | 0.21 | 0.13 |
| fulldoc, wrong | the top-3 average's days | 5% | 9% | 0.31 | 0.06 |

With the card, GPT writes down the card's median almost every time. With the 3 past applications it makes its own
guess, and that guess follows the truth less well than the plain median of the same 3 applications.

## 5. One case: 13060040

Truth: next examiner letter after 73 days; 4 more rejections; still pending at month 24 (abandoned on day 766).
The examiner's past work is optical body sensors; this case is a drug-delivery device. The 3 most similar past
applications score 0.71, 0.70 and 0.67, about the same as the wrong examiner's best matches (0.70, 0.70, 0.69).

| Method | Days to next letter | Rounds | Allowed by month 24 | Abandoned by month 24 |
| --- | --- | --- | --- | --- |
| Plain average | 62 | 1 | 64% | 15% |
| Full-history numbers | 35 | 1 | 64% | 25% |
| Top-3 average | 40 | 1 | 67% | 0% |
| GPT, no examiner block | 90 | 1 | 16% | 50% |
| GPT + card, own | 33 (= the card's median) | 1 | 65% | 26% |
| GPT + paths, own | 90 | 1 | 46% | 20% |
| GPT + fulldoc, own | 120 | 1 | 23% | 17% |

GPT + fulldoc's own explanation: the examiner "historically issues further actions before allowance", and "based on the
prosecution rhythm in the record (several months between reply and next examiner communication)" it gave ~120 days.
No method predicted the 4 rejections. One case proves nothing; the comparisons above use all 100.

## 6. What this says (the mentor's "prove it works, or explain why not")

1. **Personalization works at the level of the examiner's whole history.** The statistics card, with or without the
   LLM, is the best way we have found to use the examiner. Own beats wrong examiner clearly in the card, on Disposition
   and on timing.
2. **The examiner's speed is a personal habit.** In every setup (card, paths, fulldoc, top-3 average) the own examiner
   beats the wrong one on Time to Next Action.
3. **Similar-case retrieval adds nothing on top.** The 3 most similar past applications are worse than the full history
   on Disposition (N1) and equal on timing; giving them to the LLM, as dated events or in full, is clearly worse than
   the card (A5, B3).
4. **The LLM does not use the full documents well.** Given the same 3 applications, it ranks timing worse than a median
   of 3 numbers (A3), and the full documents add nothing beyond the dated events (A4). Its Disposition gain over no
   examiner block (A1) also appears with the wrong examiner's documents (A2), so it is a general effect, not this
   examiner's.

Why the retrieval does not help, from the data:
- **"Most similar" is not really similar.** All of an examiner's past applications score in a narrow band (median best
  0.75, median worst 0.58), and the wrong examiner's best matches score as high. Examiners in an art unit work on
  related technology, so a similar invention does not point to a specific behaviour.
- **3 applications are a small, noisy sample** next to ~30 in the full history; that shows on Disposition.
- **Long text, no arithmetic.** With fulldoc the prompt is ~86k tokens; the LLM reads the letters but does not turn
  them into a reliable estimate of waiting time or outcome.

## 7. Limits

- One model (GPT-5-mini), one run per setting, 100 cases; intervals are wide.
- The search compares abstract + claims only (no dated title), and only past applications that have them (for
  13060040: 19 of 30).
- B's raw top 3 is used for every case (B's hand review covered only 10 cases).
- In 81 of 100 cases the art-unit pool is one other examiner, the same one used as the wrong examiner.
- The card's statistics come from up to 30 past applications per examiner (A's download cap).

## 8. Files

| What | Where |
| --- | --- |
| Predictions, 12 LLM files | `outputs/D/{trajectory,rounds_next}_predictions_gpt-5-mini_state_profile_with_embedding_{card,paths,fulldoc}_{own,mismatched}.jsonl` |
| Top-3 average | `outputs/D/{trajectory,rounds_next}_predictions_emb_top3_math_{own,mismatched}.jsonl` |
| All comparisons, copy check | `metrics/D/profile_with_embedding_metrics.json`, `results/profile_with_embedding_table.csv`, `results/profile_with_embedding_copy_check.csv` |
| Standard scorer output (all methods) | `metrics/D/trajectory_metrics.*`, `metrics/D/rounds_next_metrics.*` |
| The notebook as run | `logs/D/D_profile_with_embedding_run_executed_2026-11-10.ipynb` |
