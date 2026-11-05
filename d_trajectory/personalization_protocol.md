# D phase 2 protocol: can the LLM use an examiner's past applications?

Owner: D (Nancy Hu). Tasks: Disposition, Remaining Rounds, Time to Next Action. Cases: the same 100 test_core cases as
all D tables, each cut at its A1 cutoff (the applicant's first reply). Nothing dated after the cutoff is used anywhere.

## 1. Question

Two ways to tell the LLM about the examiner, each against a baseline without an LLM that uses exactly the same
information:

| What the examiner block holds | LLM setup | Baseline without an LLM (same information) |
| --- | --- | --- |
| **Full card**: the examiner's statistics from **all** past applications + 3 short past episodes | LLM + full card | **Numbers only**: the card's numbers, blended with the art-unit pool (K estimated from the data) |
| **3 full histories**: the dated event lists of 3 past applications, **no numbers calculated** | LLM + 3 histories | **Math on the 3 histories**: medians and shares computed from the same events |

Each LLM setup is also run with **another examiner of the same art unit** (blind control, identical wording), and
compared with the LLM given no examiner block.

## 2. Setups and status

| # | Setup (output tag) | Status |
| --- | --- | --- |
| 1 | LLM, no examiner block (`{M}_state`) | done (October), reused |
| 2 | LLM + own examiner's full card (`{M}_state_profile_own`) | done 2026-11-03, reused |
| 3 | LLM + wrong examiner's full card (`{M}_state_profile_mismatched`) | done 2026-11-03, reused |
| 4 | **LLM + own examiner's 3 full histories** (`{M}_state_history_own`) | new run |
| 5 | **LLM + wrong examiner's 3 full histories** (`{M}_state_history_mismatched`) | new run |
| 6 | Numbers only (`prior_own`, `prior_mismatched`), no LLM | computed (section 6) |
| 7 | Math on the 3 histories (`history_math_own`, `history_math_mismatched`), no LLM | computed (section 5) |
| 8 | KM (plain average), no LLM | done (October) |

M = GPT-5-mini (reasoning_effort low; 8192 → 16384 → 32768 token retry rule). Qwen3.6-27B (team setting) the same way
if the team decides to run it. All LLM setups use the same prompts, case documents, A state (A_v1), answer rules and
scoring; only the examiner block differs.

## 3. What is frozen

| Item | Value |
| --- | --- |
| Profile package (full cards; which 3 past applications) | `B_D_C_phase1_v4_reviewed.zip`, sha256 `d1e6e358757ba758a17373f14894449284253da1cfe4d775a0bbac6a7b207d8f`, release `B_D_C_v4_reviewed_2026_11_02` |
| Event source for the histories | A's `profile_corpus_v2.zip`, `apps/<app_id>/transactions.csv` |
| Examiner histories | `inputs/examiner_histories_v1.jsonl`, sha1 `5e5eaaa9c839787c01895f48b0c3bb314df44fba` (200 histories = 100 cases × own/mismatched; 588 past applications; 3,437 events; 156 applications still pending at the cutoff). Built by `code/build_examiner_histories.py`; deterministic |
| Prompts | `prompts/trajectory_forecast_profile.txt` (prompt_hash `d7e75c380ac8`), `prompts/rounds_next_forecast_profile.txt` (`8656a89b9b39`); baseline prompts `trajectory_forecast.txt` `8fa99d848c11`, `rounds_next_forecast.txt` `2e8f78f097b3` |
| Credibility constants | `metrics/D/credibility_k.json`: K = 1.8 / 3.3 / 8.4 / 4.5 (section 6) |
| Code | `examiner_history.py`, `build_examiner_histories.py`, `run_trajectory_llm.py`, `run_rounds_next_llm.py`, `history_math.py`, `credibility_k.py`, `examiner_prior.py`, `compare_history_runs.py`, `copy_check_cell.py`, `D_phase2_run.ipynb` (sha1 in `PHASE2_CODE_SHA1.txt`) |

Before any API call the code checks the package release id and manifest sha256, each profile file's and profile text's
sha1, and for the histories the file's sha1 and, per case, the cutoff and that the past applications are exactly the
package's, in the same order. Any mismatch stops the run. The card setting (`--examiner-input card`) rebuilds exactly
the prompts and cache keys of the 2026-11-03 card runs (checked for all 200 cases), so those results are reused as run.

## 4. What the LLM sees

One input item after the case record, before "Task" (same wording for every setup with an examiner block):

```
- Examiner history reference for this application's examiner, built only from the examiner's other applications
  and only from events before the cutoff. It is background about the examiner; the documents above are the record
  of this application.

{examiner block}
```

**Full card** (the team's v4 profile text). Case 13060040, own examiner:

```
Historical statistics
Statistics for this examiner, other applications, events before 2014-09-26:
- 30 applications; 26 replies to a non-final rejection.
- Next letter after such a reply (25 seen, 1 still waiting): allowance 32%, final rejection 64%, ...
- Days from a reply to the next letter: median 33 (allowances 59, rejections 31).
- After the first reply (20 applications): 11 allowed, 4 abandoned, 5 still pending; estimated allowed within
  12 months 48%, within 24 months 65%; abandoned within 24 months 26%.
- Further rejections after the first reply: 0: 26%, 1: 43%, 2: 8%, 3+: 23%; RCE filed in 25%.
- Grounds in 54 rejections ...: 103 in 93%, 102 in 54%, 112 in 50%, 101 in 24%.
(reading notes)
Retrieved historical episodes
Example 1: application 12109224. Reply 2013-03-07 ... Next communication 2013-04-01: notice of allowance; 25 days
after reply; (short excerpt)
Example 2, Example 3: the same form (one reply and the next letter only)
```

**3 full histories** (no statistics, no document text): the same 3 past applications as the card's examples, with
every examiner letter (non-final MCTNF, final MCTFR, advisory MCTAV, restriction MCTRS, Ex parte Quayle MCTEQ, notice
of allowance MN/=.), abandonment notice (MABN*) and applicant action (reply to non-final A..., reply to final A.NE, RCE
RCEX) dated strictly before the case's cutoff, and the application's status at the cutoff. 13060040, own, past
application 1:

```
Past application 1: 12109224
- 2012-06-18 examiner mailed a restriction requirement
- 2012-08-13 examiner mailed a non-final rejection
- 2012-12-13 applicant filed a reply to a non-final rejection
- 2013-01-03 examiner mailed a final rejection
- 2013-03-07 applicant filed a reply to a final rejection
- 2013-04-01 examiner mailed a notice of allowance
Status on 2014-09-26: allowed (notice of allowance mailed 2013-04-01).
```

**How the 3 past applications are chosen** (team retrieval in the v4 package, reviewed by C): from the examiner's past
episodes before the cutoff, the 3 whose text (the examiner's office action + the applicant's reply) is most similar to
this case's documents by TF-IDF cosine similarity (single words and 2-word phrases, English stop words removed), at most
one per application and per patent family. Coverage: own 99 cases with 3 applications, 1 with 1; mismatched 96 with 3,
1 with 2, 3 with none.

## 5. Baseline: math on the 3 histories (`history_math.py`, no LLM)

Per past application, from exactly the events the LLM sees:
- first reply = the first applicant reply after the application's first rejection (the same point as our cutoff A1);
- next days = days from that reply to the examiner's next letter;
- rounds = non-final + final rejections after that reply, up to allowance or abandonment;
- allowed_24 / abandoned_24 = allowed / abandoned within 730 days of that reply.
A still-pending application counts with what is known so far (a lower bound); one with no first reply is skipped.
Prediction: Next action = **median** of the next days; Rounds = **median** of the rounds (rounded); Disposition = the
training KM curves stretched so month 24 equals the share allowed_24 and the share abandoned_24. No usable application →
KM. The median is used because the scores are absolute errors and the median minimizes the expected absolute error.

Example 13060040 (own): next days 21, 31, 25 → **25**; rounds 1, 3, 1 → **1**; 2 of 3 allowed, 1 of 3 abandoned within
24 months → curves reach 67% / 33% at month 24.

## 6. Baseline: numbers only (`examiner_prior.py`, no LLM)

The card's numbers, each blended with the case's art-unit pool:

    estimate = Z × examiner number + (1 − Z) × pool number,   Z = n / (n + K)

n = the examiner's number of episodes behind that number; medians are blended on the log scale. **K is estimated from
the data** with Bühlmann–Straub credibility (`credibility_k.py`), which gives the K with the smallest expected squared
error of the blend: K = EPV / VHM. EPV (expected process variance) = how much single episodes of the same examiner
scatter; VHM (variance of hypothetical means) = how much true examiner averages differ around their art-unit average.
Data: the phase-1 episodes in the frozen package (`source_D/case_episodes.csv`), each cut at its case's cutoff; one group
= one case (its own examiner + its art-unit pool examiners). No test answer is used. 95% intervals from 1,000 bootstrap
draws of the cases (seed 20261010).

| Statistic | EPV | VHM | K (95% interval) | Z at n = 20 |
| --- | --- | --- | --- | --- |
| Days to next letter (log) | 0.373 | 0.210 | 1.8 (1.4–2.3) | 0.92 |
| Allowed within 24 months | 0.120 | 0.037 | 3.3 (2.4–4.5) | 0.86 |
| Abandoned within 24 months | 0.094 | 0.011 | 8.4 (6.0–13.2) | 0.70 |
| Rounds (used for every rounds share) | 0.788 | 0.177 | 4.5 (3.3–6.5) | 0.82 |

Tasks from the blended numbers: Next action = blended median days; Rounds = median of the blended shares (0, 1, 2, 3,
4+); Disposition = training KM curves stretched to the blended 24-month allowed / abandoned shares.

## 7. Format check (before the history run)

5 fixed test_core cases, chosen for edge cases, not outcomes: 13060040 (normal, 3 applications), 13484627 (own: 1
application), 13627444 (mismatched: 2), 13577408 (mismatched: none), 14031839 (own: thin history). Own and mismatched ×
both prompts = 20 calls per model, written to `outputs/D/dev/*_formatcheck.jsonl` (never scored). **Pass** = all 20
answers parse, none cut off, the saved prompt shows the history block before "Task" with the case's cutoff date, the
block holds event lists and no statistics, and no hash error. Accuracy on these 5 is not looked at.

## 8. Comparisons (`compare_history_runs.py`)

Metrics: Disposition C-index (IPCW, τ = 730 days) and IBS; Remaining Rounds MAE and exact accuracy; Next Action C-index
and MAE in days. Paired bootstrap, 1,000 draws, seed 20261010, cases where both methods answered. "Clear" = the 95%
interval excludes 0.

| # | Comparison | Question |
| --- | --- | --- |
| 1 | LLM + own card − LLM, no examiner block | Does the card help the LLM? |
| 2 | LLM + own card − LLM + wrong card | Is it about this examiner? |
| 3 | LLM + own card − numbers only | Does the LLM add anything beyond the card's numbers? |
| 4 | LLM + own histories − LLM, no examiner block | Do the 3 histories help the LLM? |
| 5 | LLM + own histories − LLM + wrong histories | Is it about this examiner? |
| 6 | **LLM + own histories − math on the same 3 histories** | **Does the LLM reason better than plain math on the same information?** |
| 7 | LLM + own histories − LLM + own card (descriptive) | 3 histories vs the full card |

Plus the copy check (`copy_check_cell.py`): how often the LLM's days equal the card's median (card runs) or the math
median of the same histories (history runs).

**How to read 3 and 6:** clear in the LLM's favour → it gets more out of the examiner block than the numbers / the math.
Not clear → it does about what the numbers / the math do. Clear against the LLM → the numbers / the math are the better
use of the same information. 2 or 5 not clear → the effect is not examiner-specific.

## 9. Splits (descriptive, no new tests)

RCE in the true path (0 vs 1+); number of past applications shown (3 vs fewer).

## 10. Failures

A broken answer is retried once with the same prompt, then listed as failed and never filled with defaults. Qwen API
failures are kept (`--retry-failed` only as an explicit, logged resume). Paired tests use the cases both methods
answered, and the n is reported.

## 11. Limits

- 3 applications per examiner, chosen by text similarity, not at random; 100 cases; one run per setting.
- In 81 of 100 cases the art-unit pool (numbers only, and the wrong examiner) is one other examiner.
- The math baseline counts pending applications as lower bounds.
- Credibility estimate: several episodes of one application are treated as independent; the pool value is treated as
  exact; the 24-month and rounds outcomes are estimated on episodes with a known outcome.
- Examiner = the handling examiner in the contact paragraph of the office action ("should be directed to …"), not a
  verified signature.
