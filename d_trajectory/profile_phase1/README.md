# D phase 1: examiner episodes, stats cards, leak check (2026-10-29)

Owner: D. Input: A's `profile_corpus_v2` (cases.csv sha1 3191368…, profile_index.csv 4cbe10c…, actions.csv d129a0f…).
Code: `code/d_profile_phase1.py` (no API calls, runs in about 7 seconds). Status: **D_verified_v1**, ready for B to merge.

## 1. What is in this folder

| File | Rows | What it is |
| --- | --- | --- |
| `episodes.csv` | 8,364 | Every "applicant reply → examiner's next letter" in the 5,369 profile applications, with document ids, text paths, signature basis and how the case ended. Not cut per case. |
| `case_episodes.csv` | 14,056 | The same episodes **cut again at each case's own cutoff**, per (sample_id, variant). Use this, not `episodes.csv`, for any case. |
| `stats_cards.jsonl` | 300 | One card per case × version (own, mismatched, artunit): numbers with denominators, raw and shrunk, plus `card_text` (the lines for the prompt) and `card_sha1`. |
| `leak_check.csv` | 300 | Every rule checked per case × version. **300 / 300 pass.** |
| `build_summary.json` | | Counts and input sha1s. |

## 2. Rules (the same codes as our gold labels for the 3 trajectory tasks)

- **Reply** = transaction `A...` (response after non-final), `A.NE` (response after final) or `RCEX` (RCE). The clock starts at the **first** reply after the examiner's last letter, as our A1 cutoff does.
- **Next letter** = first mailed `MCTNF`, `MCTFR`, `MCTAV`, `MCTRS`, `MCTEQ`, `MN/=.` or `MABN*` after the reply. Allowances are included (B's draft had only rejection pairs).
- **Ending** = first mailed `MN/=.` or `MABN*`. `ABN9` is RCE bookkeeping, not an abandonment. A revived case keeps its first ending.
- **Rounds** = mailed `MCTNF` + `MCTFR` after the reply up to the ending.
- **Signature** (A's rule 3): a next CTNF/CTFR signed by someone else is dropped from the numbers (60 episodes; 93 case-level drops). CTNF/CTFR signed by the examiner = `actions_csv_verified` (3,965). NOA, advisory, restriction, Quayle and abandonment notices have no signature data = `assigned_examiner_unverified` (3,797); this is said in `signature_basis`, not hidden.
- **Cut at each case's cutoff** (A's rule 1): an application counts only if `first_signed_action < cutoff`; a reply counts only if before the cutoff; a letter or ending on or after the cutoff = "still waiting" (censored). The 16 examiners used by several cases are cut separately for each case (e.g. ex_26f484b420: 66 episodes at 2015-05-08, 59 at 2015-02-27).
- **Versions**: own = `examiner_id` in cases.csv (A's v2 ids, incl. the 3 changed signers); mismatched = `control_examiner_id`; artunit = every own/control examiner linked to the case's `control_art_unit`, minus the case's own examiner (B's pool rule).
- **Shrinkage**: own and mismatched rates are pulled toward the art-unit pool of the same case and cutoff: (n × rate + 5 × pool) / (n + 5). Medians are shrunk on the log scale. Example: 25 episodes at 32% with pool 40% → (25 × 0.32 + 5 × 0.40) / 30 = 0.33.
- **No ODP status field is used.** Every outcome comes from transactions cut at the cutoff.

## 3. What a card holds (one example, own version)

```
Statistics for this examiner, other applications, events before 2014-09-26:
- 30 applications; 26 replies to a non-final rejection.
- Next letter after such a reply (25 seen, 1 still waiting): allowance 32%, final rejection 64%, non-final rejection 4%, other 0%.
- Days from a reply to the next letter: median 33 (allowances 59, rejections 31).
- After the first reply (20 applications): 11 allowed, 4 abandoned, 5 still pending; estimated allowed within 12 months 48%, within 24 months 65%; abandoned within 24 months 26%.
- Further rejections after the first reply: 0: 26%, 1: 43%, 2: 8%, 3+: 23%; RCE filed in 25%.
- Grounds in 54 signed rejections: 103 in 93%, 102 in 54%, 112 in 50%, 101 in 24%.
```

- "Within 12 / 24 months" and the rounds shares are survival estimates: a case still pending at the cutoff counts as "at least this long", never as "never ends".
- Grounds = share of signed rejections whose full text says "rejected under 35 U.S.C. 101/102/103/112" (a text rule, approximate).
- Thin profiles: 3 own cards have fewer than 10 first-reply episodes (13086389: 9, 13484627: 6, 14031839: 5); the card then adds "Few cases: treat these numbers as rough".

Examiners really differ (own cards, 10th to 90th percentile): next letter is an allowance 8% to 77%; median days to the next letter 25 to 105; allowed within 24 months 25% to 96%.

## 4. Checks done

1. `leak_check.csv`: 300 / 300 pass: all dates used are before the cutoff (the latest event used is 1 to 3 days before it, never on it); no profile application or family is in our 1,000; the case's own family is not used; own ≠ control; the own examiner is excluded from mismatched and artunit; the number of applications per case equals A's `n_own_usable_before_cutoff` / `n_control_usable_before_cutoff` for all 200 own/mismatched rows.
2. Hand check of one application with an RCE (5 episodes) against its `transactions.csv`: all dates, types and the ABN9 rule correct.
3. B's 2,864 provisional pairs: 2,856 are in `episodes.csv` with the same next letter. The reply date differs for 98 of them: B uses the catalog date of the last reply, D the transaction date of the first reply after the letter (our A1 rule).

## 5. For B (to finish the profiles)

1. Rebuild the retrieval pool per case from `case_episodes.csv` (filter on sample_id + variant; drop `next_signed_ok == False`). It now includes allowances and other letters, so the pool is no longer biased toward rejections. The 13 short profiles in `insufficient_k3.csv` should mostly fill up.
2. Put the card's `card_text` where the draft says `{D_verified_statistics_with_denominators}`; record `card_sha1` in the profile.
3. Re-run your checks, then hand to C.

## 6. For C (review)

Check `card_text` in the 10 review cases too: the denominators are in each line; "still waiting / still pending" are cases not finished at the cutoff.

## 7. First result: examiner numbers alone, no LLM (`metrics/D/examiner_prior_metrics.json`)

The "numbers only" control from the plan, run now because it is free. test_core, 100 cases; Δ vs KM with paired 95% intervals (1,000 draws, seed 20261010).

| Method | Disp. C-idx ↑ | Disp. IBS ↓ | Rounds MAE ↓ | Rounds Acc ↑ | Next C-index ↑ | Next MAE days ↓ |
| --- | --- | --- | --- | --- | --- | --- |
| KM (average) | 0.500 | 0.188 | 0.99 | 0.37 | 0.500 | 36.3 |
| Qwen3.6-27B, state + history (best LLM so far) | 0.589 | 0.187 | 0.96 | 0.49 | 0.563 | 48.4 |
| **Own examiner's numbers** | **0.686** | **0.154** | 0.94 | 0.43 | **0.725** | **27.4** |
| Wrong examiner's numbers | 0.564 | 0.182 | 1.15 | 0.32 | 0.496 | 41.9 |
| Art-unit pool numbers | 0.574 | 0.179 | 1.12 | 0.34 | 0.501 | 41.1 |

- Own vs KM: Disp. C-idx +0.19 [+0.14, +0.24], IBS −0.034 [−0.055, −0.017], Next C-index +0.23 [+0.17, +0.28], Next MAE −8.8 days [−12.9, −4.9]. Rounds: not clearly different (MAE −0.05 [−0.25, +0.12]).
- Own vs Qwen state: Disp. C-idx +0.10 [+0.03, +0.18], Next MAE −20.9 days [−28.3, −13.6].
- Wrong examiner and art unit: no gain on next-action timing (C-index ≈ 0.50); a small Disposition C gain, about what the art unit alone gives. Shuffling the own examiners across cases (200 times) gives a next-action C-index of 0.50 (95% range 0.44 to 0.56). So the gain is this examiner, not "any examiner".
- Meaning for phase 2: the bar for every LLM + profile run is now this row, not KM. The paper's warning holds: a model can look personalized by copying the examiner's base rate. The LLM + profile run must beat the examiner numbers to show it reads the record.
