# State-tracking gold (A) — final, 2026-10-10

## Files
- `state_gold.jsonl` — 20 snapshots (10 apps x {O1_cutoff, A1_cutoff}); 517 claim records, 310 rejection tuples (+42 objections, excluded from Rej by default).
- `state_gold_provenance.csv` — one row per review item (143): auto / model / rule answers, final value, decision, decision file + row, evidence doc.
- `state_gold_text_provenance.csv` — one row per claim record: status, version_id, where the text came from.
- Review files (human decisions): `state_gold_review_round1.xlsx`, `gold_review_yellow_done.xlsx`, `gold_review_v3_done.xlsx` (A, C), `gold_review_B_done.xlsx`.

## Reproduce
    cd ~/examinerbench
    python3 A/scripts/integrate_gold.py
    python3 A/scripts/score_state.py --gold A/gold/state_gold.jsonl

## How every item was decided (143 items)
| decision | n | meaning |
|---|---|---|
| auto / model / rule / fix | 30 / 12 / 3 / 20 | annotator chose that answer (or wrote the correct value) after reading the cited USPTO document / PDF |
| ok | 47 | annotator confirmed the answer on which auto and model agreed (incl. exact duplicates that inherit the decision of an identical item) |
| definitional | 20 | O1 snapshot: rejections issued at the cutoff are outstanding; no applicant reply yet, so the proposed list is empty |
| catalog_check | 10 | A1 'statuses used' = outstanding: the USPTO file-wrapper catalog has no examiner document between O1 and the A1 cutoff |
| doc_check | 1 | 14950996 A1: the reply contains no claim listing (CLM), so the proposed list is empty |
Matching is by value (app, stage, item, auto string, model string), never by row position alone.
Version protocol: annotators verify status labels; version_id = last document labelling the claim Currently Amended / New (or first Canceled), else as_filed (state_annotation_guide.md).

## Claim texts
Texts of amended/new claims on which auto and model disagreed were adjudicated against the PDF (yellow sheet, 28 + 1 in sheet A).
20 randomly sampled agreeing texts (seed 20261009) were checked against the PDF: 15 ok, 5 fixed
(page header/footer inside the text x3, OCR of struck-through text x1, Å extracted as A x1); only 1 of the 5 falls below the 0.90 similarity used by the metric.
Remaining texts (original, never-amended claims) come from the automatic reference without individual review.

## Agreement of the deterministic provenance rule with the final gold
Claim level (status + version): 477/517 = 92.3%. All 40 differences come from two causes:
OCR listing where the rule could not read every claim number (13575141, 1-12 vs 7 parsed), and a cancellation stated only in an image
of the same-day preliminary amendment (14420580 claims 1-10; O1 line 90 "Claims 1-10 were cancelled.").

## Scores (gpt-5-mini, prompt p3, reasoning_effort low) vs this gold
| stage | Claim (claim-version acc.) | Rej (status macro-F1) | n claim records | n rejection tuples |
|---|---|---|---|---|
| O1 | 0.633 | 1.000 | 177 | 155 |
| A1 | 0.777 | 0.997 | 340 | 155 |
| all | 0.727 | 0.998 | 517 | 310 |
Automatic reference vs this gold: Claim 0.776, Rej 0.977 -> automatic labels are NOT reliable enough to score Claim on test_core.
Note: at the O1 and A1 cutoffs every rejection status is 'outstanding', so Rej here reduces to (claim, ground) F1.
