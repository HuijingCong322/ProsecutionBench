# C phase-1 findings and shared-release handoff

Review scope: A `profile_corpus_v2`, B `B_phase1_v2_draft_handoff`, D `D_phase1_v1_handoff`, the examiner-profile team plan, and the benchmark `data_v1_share` manifest and cutoff-visible inputs. No model APIs were called and no new task scores were produced.

The source checks and integration are complete. Student review and team adoption are pending. This report is an AI-assisted audit, not expert validation or a claim that Crissy has already reviewed the profiles.

## Source and arithmetic checks

| Check | Result | Scope |
| --- | --- | --- |
| A manifest | 79,531 / 79,531 files match | Size and SHA1 against the supplied manifest |
| D rebuild from A | 4 / 4 files byte-identical | Master episodes, case-cut episodes, cards, leak report |
| B retrieval queries | 100 / 100 hashes recreated | Same cutoff-visible query construction |
| Original fixed-sample retrieval | 30 / 30 replayed | Original B draft ranking, before integration |
| D principal arithmetic | 300 / 300 cards pass | Counts, shares, KM median, first-reply cumulative incidence at the reported horizons and RCE frequency |
| Integrated candidate sources | 300 / 300 profiles pass | Date, family metadata, pool identity, D episode boundaries, source hashes, extractive spans and next-event transactions |
| Selected source checks | 2,779 file-hash references; 1,437 extracted spans | Repeated appearances count separately; not unique-file counts |
| Complete retrieval coverage | 298 / 300 profiles | Three distinct applications and families |
| Original fixed human sample | 10 cases; 30 versions retained | No substitutions; all student labels remain pending |

Family separation is assessed against A's supplied continuity-root definition and the 1,000-row benchmark manifest, not an independent reconstruction of every worldwide patent family. D's grounds counts remain approximate text-rule outputs: reproducing the code and source hashes does not validate each legal ground semantically.

## Changes needed before reviewing the original B draft

**D integration is substantive.** B's supplied profiles have `statistics=null` and use provisional signed-rejection pairs. Adding statistics to those files alone would retain an outcome-biased retrieval pool. The candidate set instead retrieves from D's complete per-case episode table, including allowances and other eligible next communications.

**Use one reply boundary.** Thirty-six selected references in the original 300 B drafts do not agree with D's episode/date definition. This count includes repeated appearances of an episode. Two occur in the fixed review sample:

| Original B profile / historical application | B draft | D definition |
| --- | --- | --- |
| `13986738/own`, app `13573120` | Reply 2013-10-24; 83 days | Reply 2013-04-08; 282 days |
| `13334748/own`, app `13386776` | Reply 2013-05-06; 74 days | Reply 2013-05-10; 70 days |

The candidate consistently uses D's first-reply transaction rule and re-ranks the resulting pool. It is a new version with new hashes, not a silent correction of the old files. Some former examples no longer appear after re-ranking.

**Respect known signer exclusions.** In addition to D's `next_signed_ok` filter, the candidate excludes episodes whose prior CTNF/CTFR is known to have another signer. This follows A's stated rule for historical examples. The exclusion audit records 168 case/variant-level exclusions for this rule and 505 for absent readable pre-outcome retrieval context. These are not counts of unique applications. B should adopt this policy once for the shared set if using this integration.

## Statistical wording clarified without changing D's numbers

1. D delivers shrinkage estimates in JSON for own/mismatched profiles, but its original `card_text` reports raw values without identifying the stored adjustment. The candidate displays both with separate labels and retains the original card text and `card_sha1` for traceability. If the team prefers adjusted-only text, D should supply a single agreed renderer and C should recheck the affected text.
2. D's observed allowance/rejection subgroup medians use the upper-middle observation for an even sample size. In 239 card/subgroup fields this differs from averaging the two middle values; 23 such fields occur in the review sample. This is a convention that needs a label, not a reason to declare all medians incorrect. The candidate explicitly says **upper median** and leaves the numbers unchanged. Overall KM medians are a separate checked statistic.
3. The candidate distinguishes next-action signature checks from application-level outcome and rounds histories. In the supplied data, no included first-reply rounds trajectory was found to contain a later CTNF/CTFR explicitly flagged as another signer before its cutoff. This does not establish authorship for unsigned notices or every later event.

No D trajectory score, baseline, survival curve or published metric was recalculated or overwritten as part of this wording change.

## Limitations to retain in review and reporting

**Incomplete k=3.** `13484627/own` has one eligible example; `13627444/mismatched` has two. The former is in the 10-case review sample. Keep the cases, record actual `retrieved_k`, and report coverage. Any exclusion or separate complete-k=3 analysis later must use a declared common case rule, not favorable replacements.

**Examiner identity.** A v2 has three actual examiner-ID changes and one documented fallback. The changed-identity cases are `13817797`, `13986738` and `14482153`; `14353039` is the fallback because the O1 signer lacks available ODP history. Use the v2 IDs and retain the fallback limitation. A conservative independent string-to-hash check matched 43 current O1 texts; the other 57 were unresolved by that parser, not shown to have the wrong signer. The audit therefore distinguishes A's supplied signature labels from a complete independent human signature verification.

**Unverified notices.** `next_signed_ok=True` means the event is not known to have another signer. It includes assignment-attributed NOA and other notices. The fixed review sample contains 48 retrieved slots with unverified next-notice signatures and seven slots with missing reply bodies, out of 88 retrieved slots. The candidate states these limits rather than inventing response strategy or signed attribution.

**Limited art-unit pool.** The art-unit pool follows B/D's case-to-own/control examiner mapping and excludes the target examiner. It is not the art unit's full population. In 81 of 100 cases it contains only the mismatched examiner; in 86 cases its three-or-fewer retrieved episodes equal the mismatched retrieval. Keep these controls distinguishable in metadata, but do not interpret identical pools as independent examiner-versus-art-unit evidence.

**Extractive summaries.** The two lines are clipped source extracts, not adjudicated descriptions of a successful strategy. Public raw text and the supplied substantive extraction can contain OCR or extraction damage. A transaction-only NOA supports the recorded event, not why the examiner allowed the claims. Relevance still requires a reader's judgment against the current case; lexical similarity does not settle it.

**Technical relevance is uneven.** Source review found concrete weak matches: `13986738/own` retrieves perfume-container and hair-band applications alongside a flossing application; `13577408/mismatched` retrieves medical-device applications for a cardboard-box manufacturing case; `14031839/own` includes a printing/ink application for a metal-gate case; and `14482153/mismatched` retrieves sewing, book-stitching and ironing-board applications for a safety-visor case. These topic differences are visible in the historical prior-action/reply text, not just inferred from current outcomes. A procedural analogy may still exist, but the reviewer should identify it explicitly rather than approve on generic claim-editing vocabulary. The review page and AI-assisted observation CSV provide reading notes for all 30 versions. These are suggestions for checking, not student labels. Keep the TF-IDF baseline honestly labeled; any retrieval redesign should be agreed by B, developed on appropriate development data and reviewed as a new version.

**Human sample.** These ten cases were already selected by B to cover identity and coverage edge cases. They are not a new random sample for estimating a population error rate. Describe them as targeted quality review, not a calibrated expert study or a statistically representative audit.

## What each person needs next

| Owner | Concrete next action |
| --- | --- |
| C / Crissy | Read the ten fixed cases across three variants in `review/index.html`, make actual judgments, and export `profile_review_C_done.csv` |
| B | Compare this candidate with the intended final retrieval policy, adopt one shared set, and resolve any summary/relevance or integration issues reported by C |
| D | Confirm the raw/adjusted renderer and upper-median wording, and resolve any statistical or event-definition questions reported by C |
| A | No new download is required for this review; clarify the documented fallback only if the team wants stronger identity evidence |
| Team | Record acceptance of residual limitations, resolve unresolved rows, and lock the shared prompt and external file hashes before phase 2 |

The proposed final prompt wording is in `prompts/profile_block.txt`. The model should see the rendered `profile_text`, not control labels, examiner hashes, human notes, or raw review sources.

The current package is an A1-cutoff set for B/C/D. O1-cutoff state-tracking conditions require separate cutting. The team plan's Applicant Response row is superseded by the later decision to remove that task from Table 3; this package does not restore it.

After phase 1, C's next experimental work remains the existing 50-case examiner-generation comparison, adding the shared profile to the existing model-specific prompt and settings. The already completed no-profile baselines are retained. This package does not launch that experiment.
