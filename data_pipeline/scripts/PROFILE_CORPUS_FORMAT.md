# Examiner profile corpus (v2): file format

From A, for phase 1 of the examiner-profile plan. All checks below passed before packaging (`checks.json`).

## What it is

For each of the 100 `test_core` examples, other applications by the same examiner (target: 30 usable ones), plus
the same for one **control examiner** from the same art unit (for the "wrong profile" run). The corpus is a reference
library only. It is not train or test data.

## Folder layout

```
profile_corpus/
  README.md                   this note + counts + check results
  cases.csv                   one row per test_core example
  profile_index.csv           one row per (examiner, profile application)
  actions.csv                 one row per examiner action in the profile applications, with who signed it
  checks.json                 results of the checks run before packaging (counts, warnings)
  MANIFEST.csv                sha1 and size of every file
  apps/<app_id>/
    transactions.csv          event_date, event_code, event_description   (see rule 1)
    catalog.csv               official_date, doc_code, direction, doc_id   (see rule 1)
    text/<date>_<code>_<doc_id>.txt              USPTO XML text of examiner actions and replies
    text/<date>_<code>_<doc_id>.substantive.txt  examiner actions only: form paragraphs removed (can be empty when the
                                                 examiner typed nothing beyond form paragraphs, e.g. some NOAs)
    text/<date>_<code>_<doc_id>.claims.json      claim listings (CLM): number, status, text
    text/pgpub_abstract.txt, text/pgpub_claims.json   only when the PGPUB was published before the cutoff
```

Everything in `apps/` (texts, transactions, catalog, PGPUB) is dated **before the latest cutoff of the examples that use
this examiner**; nothing later is shipped. Texts are kept for: CTNF, CTFR, NOA, CTAV, CTRS, CTEQ, CTMS, EXIN, REM, CLM, A..., A.NE,
A.AF, A.I., AMSB, RCEX.

## cases.csv

| column | meaning |
|---|---|
| sample_id | the test_core application (same id as `data_v1_share/examples/`) |
| cutoff | A1 filing date (the cutoff for B, C and D) |
| o1_mail_date | O1 mail date |
| o1_art_unit | art unit printed on O1, i.e. at the time (19 of 100 differ from today's art unit) |
| examiner_id | `ex_` + first 10 hex digits of sha1(examiner name), as in v1.2 |
| signer_source | `o1_signature`: the O1 signer is today's examiner; `o1_signature_reassigned`: the O1 signer is someone else, we use the signer; `o1_signer_not_in_odp`: the signer has no applications in ODP, so today's examiner is used |
| signer_found_by | `directed_to` ("... should be directed to NAME") or `signature_block` ("/NAME/ Primary Examiner, Art Unit ...") |
| n_own_usable_before_cutoff | this examiner's profile applications with a signed action before this cutoff |
| control_art_unit | art unit used to pick the control examiner: `o1_art_unit`, except the 2 examples whose O1 art unit is 41xx (USPTO training academy, not a technology area), which use the supervisor's art unit on O1 |
| control_examiner_id | the "wrong" examiner for this example (same art unit, never the example's own examiner) |
| control_level | `art_unit (test examiner)`: another test_core examiner; `art_unit (ODP search)`: found by an ODP art-unit search |
| n_control_usable_before_cutoff | the control examiner's usable applications before this cutoff |

For examples whose `signer_source` is not `o1_signature`, `examiner_id` can differ from the `examiner_id` in the v1.2
examples (which used today's examiner). Use the one in `cases.csv`.

## profile_index.csv

One row per (examiner_id, profile application). To get the applications of an example: filter on its `examiner_id` (or
`control_examiner_id`) and keep `first_signed_action < cutoff`.

| column | meaning |
|---|---|
| examiner_id | own or control examiner (an examiner can be both, for different examples) |
| app_id | profile application |
| family_root | min(application, continuity parents); never a family of our 1,000 examples |
| filing_date | filing date |
| art_unit_today, cpc, title | from the ODP search record; the art unit is today's value, use it for grouping only |
| pgpub_date | publication date (empty if not published); `text/pgpub_*` exists only if published before the cutoff |
| first_signed_action | first CTNF/CTFR signed by this examiner |
| n_text_docs | text documents kept |

**There is no status column on purpose.** ODP's status (patented, abandoned) is today's value. Outcomes must come from
`transactions.csv` cut at the cutoff.

## actions.csv

examiner_id, app_id, doc_id, date, code (CTNF/CTFR), signed_by_this_examiner (true / false / empty when the action has
no USPTO text). Covers every CTNF/CTFR before the cutoff. No names are written in any csv file.

## Rules for every user (same as the team plan)

1. **Cut at each example's cutoff.** Files already stop before the latest cutoff that uses the examiner. When an examiner
   serves several examples with different cutoffs (listed in `checks.json`, `examiners_used_with_several_cutoffs`), cut
   again at each example's own cutoff. Use only rows/files dated **before** the cutoff (file names start with the date;
   PGPUB: `pgpub_date`). An outcome after the cutoff = still pending at the cutoff.
2. **Other families only.** Already applied: no profile application shares a family with any of our 1,000 examples.
3. **This examiner only.** Leave out actions with `signed_by_this_examiner = false` from the examiner's numbers and
   from the similar past cases.
4. **One examiner per application.** Every application belongs to exactly one examiner_id (its ODP examiner name is
   exactly the examiner's name: ODP's name search also returns longer names, e.g. two different examiners whose names
   share a prefix; those were removed).
5. Record the sha1 of the profile file you build in every prediction (team plan).

Questions about the data: ask A.
