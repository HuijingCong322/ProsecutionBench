# D phase 2: definitions, in plain words (for the week notes)

Same 100 test_core cases as all D tables. Each case is cut at its **cutoff** = the day the applicant filed the first
reply (A1). Nothing dated after the cutoff is used anywhere.
Worked example throughout: case **13060040** (cutoff 2014-09-26; art unit 3777). Truth: next examiner letter after
**73 days**; **4** further rejections; abandoned 2016-10-31 (766 days after the cutoff).

## 1. The three tasks and how each is scored

| Task | What is predicted | Score |
| --- | --- | --- |
| Time to Next Action | days from the cutoff to the examiner's next letter | **MAE** = average of \|predicted days − true days\| over the 100 cases (lower is better). **C-index** = over all pairs of cases, the share where the case predicted to be faster really was faster (0.5 = coin flip, 1 = perfect order) |
| Remaining Rounds | number of further non-final + final rejections before allowance or abandonment (0, 1, 2, 3, 4+) | **MAE** = average \|predicted − true\|; **accuracy** = share predicted exactly right |
| Disposition | two curves for months 1–24 after the cutoff: P(allowed by month m), P(abandoned by month m) | **C-index** (IPCW, up to 730 days) = over pairs of cases, the share where the case predicted more likely to have ended (allowed or abandoned) by month 24 really ended sooner; **IBS** (integrated Brier score) = average squared gap between the predicted curves and what happened, over the 24 months (lower is better). Both handle cases still open at the end of the data |

Comparisons between two methods use the same cases. Uncertainty: draw 100 cases with replacement 1,000 times (seed
20261010), recompute the difference each time, take the middle 95%. "Clear" = that interval does not contain 0.

## 2. What the LLM gets

All LLM setups get the same case documents up to the cutoff + A's predicted state. They differ only in one block
about the examiner:

| Setup | Examiner block |
| --- | --- |
| No examiner block | nothing |
| **Full card**, own / wrong examiner (run 2026-11-03, reused) | the examiner's statistics from **all** past applications (13060040: 30 applications), e.g. "Days from a reply to the next letter: median 33", "allowed within 24 months 65%; abandoned within 24 months 26%", "Further rejections after the first reply: 0: 26%, 1: 43%, 2: 8%, 3+: 23%", plus 3 short past episodes (one reply and the next letter only, with "N days after reply") |
| **3 full histories**, own / wrong examiner (new) | the dated event list of 3 past applications, only events before the cutoff, and each one's status at the cutoff. **No numbers calculated for the model** |

13060040, own examiner, past application 1 in the history block:

```
- 2012-06-18 examiner mailed a restriction requirement
- 2012-08-13 examiner mailed a non-final rejection
- 2012-12-13 applicant filed a reply to a non-final rejection
- 2013-01-03 examiner mailed a final rejection
- 2013-03-07 applicant filed a reply to a final rejection
- 2013-04-01 examiner mailed a notice of allowance
Status on 2014-09-26: allowed (notice of allowance mailed 2013-04-01).
```

**Own** = this case's examiner. **Wrong (mismatched)** = another examiner in the same art unit, with exactly the same
wording, so the model cannot tell. If the LLM really uses the examiner's habits, own should beat wrong.

Each LLM setup has a baseline **without an LLM that uses the same information**: the full card ↔ **numbers only**
(section 5); the 3 histories ↔ **math on the 3 histories** (section 4).

## 3. How the 3 past applications are chosen

Not random, and the same 3 for the card's short episodes and for the history block. From the examiner's past
applications (before the cutoff, other patent families), the team's retrieval picks the 3 whose text is most similar
to this case:
1. Text of each past candidate = the examiner's office action + the applicant's reply in that application.
2. Text of this case = its office actions, replies, remarks and claims up to the cutoff.
3. Similarity = TF-IDF cosine: each text becomes a list of word and 2-word-phrase weights (common words removed, rare
   shared words count more), and the cosine measures how much the two lists point the same way. So "similar" = uses
   the same words and phrases (claim language, cited art, rejection wording).
4. Top 3, at most one per application and per patent family. Own: 99 cases get 3 applications, 1 gets 1. Mismatched:
   96 get 3, 1 gets 2, 3 get none.

## 4. Math on the same 3 histories (no LLM)

The same 3 event lists, turned into numbers with fixed rules. For each past application:
- **start** = its first applicant reply after its first rejection (the same point as our cutoff);
- **next days** = days from that reply to the examiner's next letter;
- **rounds** = rejections after that reply until allowance or abandonment;
- **allowed / abandoned within 24 months** of that reply (yes / no).
Still-pending applications count with what is known so far.

Prediction: Next action = **median** of the 3 next-days values; Rounds = **median** of the 3 round counts; Disposition =
the average curve of all training cases, stretched so that month 24 equals the share allowed and the share abandoned
among the 3. The median is used because the scores are absolute errors and the median minimizes the expected absolute
error.

13060040: next days 21, 31, 25 → **25 days** (truth 73); rounds 1, 3, 1 → **1** (truth 4); 2 of 3 allowed, 1 of 3
abandoned within 24 months → curves end at 67% allowed / 33% abandoned.

## 5. Numbers only (no LLM): the card's numbers

The examiner's statistics card from **all** past applications before the cutoff (13060040: 30 applications), e.g. median
33 days to the next letter, 65% allowed / 26% abandoned within 24 months. Each number is blended with the art-unit pool,
because an examiner with few cases gives noisy numbers:

    estimate = Z × examiner number + (1 − Z) × pool number,   Z = n / (n + K)

n = the examiner's number of episodes behind that number. **K comes from the data**, by Bühlmann–Straub credibility:

    K = EPV / VHM
    EPV = how much one examiner's own past episodes scatter              ("noise")
    VHM = how much true examiner averages differ from their art unit's   ("signal")

Lots of noise and little real difference → big K → lean on the pool; the reverse → small K → trust the examiner. This
K gives the smallest expected squared error of the blend. Estimated from the phase-1 episodes, each cut at its case's
cutoff (one group = one case: its examiner + its art-unit pool examiners); no test answers used:

    EPV = Σ_i Σ_j (x_ij − x̄_i)² / Σ_i (n_i − 1)
    VHM = [ Σ_g Σ_(i in g) n_i (x̄_i − x̄_g)² − EPV × Σ_g (r_g − 1) ] / Σ_g ( n_g − Σ_(i in g) n_i² / n_g )

(i = examiner with n_i episodes and average x̄_i; g = group with r_g examiners, n_g episodes and average x̄_g.)

| Statistic | EPV | VHM | K (95% interval) | Z at n = 20 |
| --- | --- | --- | --- | --- |
| days to next letter (log) | 0.373 | 0.210 | 1.8 (1.4–2.3) | 0.92 |
| allowed within 24 months | 0.120 | 0.037 | 3.3 (2.4–4.5) | 0.86 |
| abandoned within 24 months | 0.094 | 0.011 | 8.4 (6.0–13.2) | 0.70 |
| rounds | 0.788 | 0.177 | 4.5 (3.3–6.5) | 0.82 |

Reading: speed is a strong personal habit of an examiner (small K); abandonment is mostly the applicant's decision, so
examiners differ little (big K).

13060040: days: examiner 33 (n = 26), pool 74, Z = 26 / 27.8 = 0.935 → exp(0.935 × ln 33 + 0.065 × ln 74) = **35 days**.
Allowed within 24 months: 65.2% (n = 20), pool 59.1%, Z = 0.858 → **64.3%**. Abandoned: 26.1%, pool 23.9%, Z = 0.704 →
**25.5%**. Rounds shares 27 / 47 / 6 / 6 / 13% → median **1**.

Times are skewed (a few very long waits), so days are blended on the log scale (a weighted geometric mean).

## 6. What each comparison answers

| # | Comparison | Question |
| --- | --- | --- |
| 1 | LLM + own card vs LLM, no examiner block | Does the card help the LLM? |
| 2 | LLM + own card vs LLM + wrong card | Is it about this examiner? |
| 3 | LLM + own card vs numbers only | Does the LLM add anything beyond the card's numbers? |
| 4 | LLM + own histories vs LLM, no examiner block | Do the 3 histories help the LLM? |
| 5 | LLM + own histories vs LLM + wrong histories | Is it about this examiner? |
| 6 | **LLM + own histories vs math on the same 3 histories** | **Does the LLM reason better than plain math on the same information?** (main) |
| 7 | LLM + own histories vs LLM + own card | 3 histories vs the full card (descriptive) |
