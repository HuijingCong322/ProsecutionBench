# State tracking — error examples (gpt-5-mini, prompt p3, reasoning_effort low; human gold, 10 apps x O1/A1)

Scores: Claim (claim-version accuracy) O1 0.633 / A1 0.777; Rej (rejection-status macro-F1) O1 1.000 / A1 0.997.
Error counts below are over gold claim records (517); one record can fail several components.

| stage | list | wrong component | records |
|---|---|---|---|
| O1 | entered | status (often original vs previously_presented) | 32 (16 status only + 16 version+status) |
| O1 | entered | claim missing from output (withdrawn claims dropped) | 12 |
| O1 | entered | version only | 10 |
| A1 | proposed | version only | 28 |
| A1 | entered | version (+status/text) | 21 |
| O1/A1 | both | text only (similarity < 0.90) | 35 |

## 1. Version confusion: "first canceled" vs "latest listing" (14420580)
Claims 1-10 were canceled by the same-day preliminary amendment I5ZFW6ZCPXXIFW1 (O1 line 90: "Claims 1-10 were cancelled.").
Gold: 1-10 canceled [I5ZFW6ZCPXXIFW1]. Model: canceled [IJA916JSPXXIFW1] (the A1 listing that only repeats "(Canceled)").
Claims 11-20 were added by the same preliminary amendment, so claim 12 (previously presented at A1) has version I5ZFW6ZCPXXIFW1;
the model gives I5YEDV85PXXIFW3 (the original claim set). This one app accounts for 57 of the wrong records.

## 2. Withdrawn claims dropped (14838440, 14460009, O1)
14838440 O1: gold includes 14-23 withdrawn [as_filed] (restriction, O1 line 5); the model lists only 1-13.
14460009 O1: claim 21 (added 2016-01-22, withdrawn by O1) is missing from the model output.

## 3. Status label at O1 (14460009)
The latest listing before O1 (2016-05-04) labels claims 1-7, 11-19 "Previously Presented"; the model outputs "original".

## 4. Version given to an unchanged claim (14031839 A1, claim 20)
Claim 20 is withdrawn and never amended, so its version stays as_filed; the model assigns the A1 listing I6O2B53SPXXIFW3.

## 5. Text: OCR of struck-through words (13151341 A1, claims 3-5)
Gold (adjudicated on the PDF): "The cleaning system according to claim 1, wherein the wear plate is ..."
Model: "... according to claim 1, characterized in that the wear plate ..." (keeps the deleted words), similarity 0.57-0.74.

## Amendment-entry errors
None observed in the gold set: every A1 listing is kept in proposed_claims and never moved into entered_claims.
