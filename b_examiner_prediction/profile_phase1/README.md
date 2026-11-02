# B examiner profiles — reviewed v4 update

Latest handoff: [reviewed_v4/README.md](reviewed_v4/README.md). The D/C-scope technical review requested by the user is complete; it is attributed to Codex, not a new human signature from D/C. The reviewed snapshot has 300 profiles with actual k recorded (293 k3, one k2, one k1, five statistics-only), source-card hashes unchanged, contact/handling-examiner attribution corrected, and censoring-tail interpretation qualified.

Use [reviewed_v4/RELEASE_MANIFEST.json](reviewed_v4/RELEASE_MANIFEST.json) and [reviewed_v4/profile_manifest.csv](reviewed_v4/profile_manifest.csv) to identify the exact team-only payload. Raw source texts, extractive profile JSONs and complete review ZIPs are intentionally not published in this public repository. Next step: 3–5 task-specific dev format checks; production phase 2 has not started.

The sections below document the earlier provisional builder. Their pending-D/C status describes that older draft, not the reviewed v4 handoff. The new integration entry point is `b_profile_integrate_v4.py`, with source data and team candidate paths passed explicitly using its command-line options.

---

# B phase 1 examiner profile drafts

Builds own-examiner, same-art-unit mismatched-examiner, and available-art-unit reference profiles from A's profile_corpus_v2 and the original data_v1_share benchmark.

## Status and scope

This is the B draft builder, not the final shared-profile freeze. D's verified episodes and statistics and C's independent review/final prompt are still pending. Statistics remain null and every profile is explicitly marked draft_pending_D_and_C.

Provisional pairs include only CTNF/CTFR with verified signatures on both prior and next actions. NOA and ambiguous episodes are excluded pending D. Missing reply text is explicitly flagged; no response strategy is inferred. Some variants can contain fewer than three eligible distinct applications/families, recorded in retrieved_k.

All historical sources are filtered strictly before each case's own cutoff. cases.csv supplies authoritative examiner IDs and same-art-unit controls. Retrieval uses pre-outcome OA/reply text only; future target labels, outcome text and current-status metadata are not ranking features. The 8,000-token cap uses o200k_base.

## Setup and run

Python 3.11+ is required. Install dependencies in your environment:

```sh
python -m pip install -r b_examiner_prediction/profile_phase1/requirements.txt
python -m pytest b_examiner_prediction/profile_phase1/tests -q
```

Download and unpack the reference corpus and benchmark separately from the team's shared Drive. Raw data, generated profiles, and ZIP archives are not included in this code upload. Pass all three paths explicitly because this repository uses a different layout from the original working project:

```sh
python b_examiner_prediction/profile_phase1/b_profile_phase1.py \
  --corpus /path/to/profile_corpus \
  --dataset /path/to/data_v1_share \
  --output /path/to/new_B_phase1_output
```

The output directory must not already exist. The tokenizer vocabulary must be available from its official source or in TIKTOKEN_CACHE_DIR for offline use. This builder makes no language-model/API calls.

## Outputs

- profiles/own, profiles/mismatched, profiles/artunit: per-case draft JSON files.
- episodes_B_provisional.jsonl: provisional pairs, two-line extractive summaries and source evidence.
- retrieval_audit.csv and leak_check_B.csv: ranking, cutoff checks and per-profile SHA1.
- examiner_identity_changes.csv and application_pair_audit.csv: identity and source coverage.
- C_review/index.html and profile_review_C.csv: ten cases with all three variants, source text and pending human-review fields.
- build_summary.json: counts, source hashes, limits and dependency status.

Regenerate the full eligible episode pool and retrieval after D delivers adjudicated episodes, rather than treating the rejection-only drafts as final by simply adding statistics. C must review and freeze the final prompt before phase 2.

The accompanying b_prediction.py supplies shared serialization and safe-path helpers from the original B pilot. Upload source: capstonetest commit 2515ba1a93101b51d12476b2dadd9dc75781dc5d.

