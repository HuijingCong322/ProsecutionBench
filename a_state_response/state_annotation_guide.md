# State annotation guide (A, week-3 pilot)

Gold states describe what the record shows **at the cutoff**, read only from documents dated on or
before it. Never look at model outputs or at documents after the cutoff while annotating.

## Snapshots
| stage | cutoff | documents visible |
|---|---|---|
| `O1_cutoff` | O1 mail date | application as filed (PGPUB), preliminary amendments, O1 and anything mailed with it |
| `A1_cutoff` | A1 filing date | the above + the whole A1 reply (claim listing, remarks, other papers filed that day) |
10 gold applications x 2 stages = 20 snapshots (`gold_subset.csv`).

## Claims
- One record per claim number. `claim_id` = the number; canceled numbers stay canceled (never reused).
- `text` = clean text of that version: keep underlined (inserted) text, drop struck-through / `[[ ]]`
  (deleted) text, drop the "N. (Status)" label. For A1 listings use the reviewed markup in
  `data_v0/apps/<app>/claims_markup/<stem>.txt` (`<ins>` kept, `<del>` removed).
- `version_id` = `as_filed` for claims as filed (PGPUB, or the claims filed on the filing date when there
  is no PGPUB); otherwise the doc_id of the claim listing that last changed the claim (amended, added or
  canceled it). An Office action is never a version.
  A claim listed as "previously presented" or "original" keeps the version_id of its last change.
- `dependencies` = claim numbers it refers to ("claim 1", "any one of claims 1-3" -> [1,2,3]).
- `status` = the label in the latest listing (original, currently_amended, previously_presented, new,
  canceled, withdrawn, not_entered). **withdrawn is not canceled** (e.g. 12813013 claim 4): withdrawn
  claims are still pending but not examined (restriction).

## Entered vs proposed (entry_status) — team rule from the week-3 plan
- `O1_cutoff`: `entered_claims` = claims examined in O1 (`entry_status = entered`); `proposed_claims` = [].
- `A1_cutoff`: `entered_claims` = the same pre-A1 claims (entered). The A1 claim listing goes to
  `proposed_claims` with `entry_status = unknown`, because entry is only confirmed by a later Office
  document (after a non-final action entry is normally of right, 37 CFR 1.111; after a final action it
  is discretionary, 37 CFR 1.116 — either way the confirmation is after the cutoff).
- Argument-only reply (no claim listing, e.g. 14950996): `proposed_claims` = [].

## Rejections
- One record per (claim, ground) stated in O1. Grounds: 101, 102, 103, 112a ('first paragraph'),
  112b ('second paragraph'), 112c/112d/112f, 112 (paragraph not stated), dp (double patenting),
  objection (claim objected to, e.g. 'objected to as dependent upon a rejected base claim').
- Drawing / specification / abstract objections are **not** claim rejections: leave them out.
- A form line listing allowable claims does not create a rejection (e.g. 14723918).
- Status at `O1_cutoff`: `outstanding`.
- Status at `A1_cutoff`: still `outstanding` unless an Office document dated on or before the cutoff
  resolves it (e.g. an interview summary stating the rejection is withdrawn -> `withdrawn`). A1 canceling
  the claim is a proposal: the rejection stays `outstanding` (use `moot` only if an entered amendment
  canceled the claim before the cutoff).
  Applicant arguments or amendments alone do **not** make a rejection `overcome`; silence is not
  `withdrawn`. Use `unknown` only when the record cannot tell.
- `evidence` = O1 doc_id + a short quote of the rejection sentence (and the doc that changed it, if any).

## Review sheet
`gold/state_gold_review.csv` lists every pre-filled field with its automatic source. For each row mark
`ok` or write the correction in `corrected_value` with a note. Edge cases go to
`state_error_examples.md` if a model gets them wrong.

## Provenance rule for gold (v3, 2026-10-09)
This is the reproducible rule for the claim lists, implemented in `A/scripts/provenance.py`. A human confirmed every item.
- **entered_claims.** Start from the as-filed claims. Apply, in date order, every applicant claim listing (CLM) filed before the O1 mail date. On the same day, the as-filed claims come first and the amendment second. Then set to `withdrawn` the claims that O1 withdraws from consideration (restriction or election).
- **proposed_claims.** The entered state, updated with the claim listing in the A1 reply. It is empty at the O1 cutoff.
- **status** is the label in the latest listing that contains the claim. `original` is used for unlabelled as-filed claims.
- **version_id** is the doc_id of the latest listing that amended, added or first canceled the claim. It is `as_filed` if the claim was never changed.
- **Listings that omit claims.** A listing may omit claims that existed before. This is irregular under 37 CFR 1.121(c). The rule flags it, and the annotator decides from other documents in the record. Example: 14420580, where claims 1-10 are canceled according to both the PGPUB and the A1 listing.
- **Rejections** come from the "Claim(s) ... are rejected under ..." sentences of O1. Objections are scored separately.
- **Review protocol.**
  - The automatic reference and the model output (gpt-5-mini, frozen prompt) were compared item by item.
  - Every disagreement was adjudicated by a human against the USPTO documents (text and PDF). Agreements were confirmed by a human against the documents and against the rule-derived answer.
  - Claim texts on which both sources agree (similarity ≥ 0.90) were spot-checked: 20 random claims, seed 20261009.
- **Record per item.** Each gold item stores the candidate documents, the rule answer, the human decision and the evidence document.

## Human review protocol for versions (decided 2026-10-09)
- Annotators verify claim STATUS labels only (per listing document).
- version_id is then computed deterministically from the human-verified labels:
  version = last document in which the claim is labeled Currently Amended or New
  (or first Canceled); Original / Previously Presented / Withdrawn do not change it;
  otherwise as_filed.
- Review rows marked "状态对" = status verified by human, version left to this rule.
- Rows identical to an earlier row (same app, item, auto, model, rule; same OA) inherit
  that row's decision, recorded as "copied from row X".
