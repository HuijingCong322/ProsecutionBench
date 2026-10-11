# Reviewing C's 5 generated Office Actions (D, due Mon 10/12 18:00)

C sends you, for at least 5 cases: the input history, the generated OA, the real O2, and the judge scores.
You read each one **on your own first**, fill one row of `oa_review_D.csv`, and only then look at the judge score.
Plan about 20–30 minutes per case.

## For each case, step by step
1. **Read the real O2 first** (the summary page and the rejection sections). Write down:
   - its type (non-final or final rejection) and whether it is final;
   - each ground (101 / 102 / 103 / 112(a) / 112(b) / double patenting / objection) with its claims;
   - the references for each ground.
2. **Read the generated OA** and make the same list.
3. **Score 1–5 on each dimension**, using the judge's rubric (1 = no agreement, 5 = full agreement):
   - *Disposition*: same type and finality?
   - *Grounds*: same grounds on the same claims? List what is missing and what is extra.
   - *Evidence*: same references and passages? Does it cite anything **not** in the inputs? That is an unsupported citation.
   - *Reasoning*: does it answer A1's actual arguments? Does it treat the claims **as amended in A1**? If it rejects the old,
     pre-amendment claim text, mark `wrong_claim_version = Y`.
   - *Overall*: could it stand in for the real O2?
4. **Now compare with the judge.** Fill `agree_with_judge` (Y / partly / N) and one line on any disagreement.
5. **Main error source:** `data` (a bad input, such as an OCR or claim-listing problem), `model` (it generated the wrong thing), or
   `scoring` (the judge or ROUGE got it wrong).

## Rules
- Judge agreement with the **real O2**, not legal correctness. Do not use anything dated after the cutoff except the O2 itself.
- Do not change C's scores. Record disagreements; C merges them into `generation_human_review.csv`.
- When something can't be checked from the materials you have, write `unknown`; don't guess.
