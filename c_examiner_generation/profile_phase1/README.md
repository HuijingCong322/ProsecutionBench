# C phase 1: examiner-profile review and prompt

This package completes the source-based, automated part of C's phase-1 review and supplies a proposed integration of A's corpus, B's retrieval approach, and D's verified episodes and statistics. It makes no model calls.

**Status: integrated candidate, not frozen.** Crissy's human review is still required. The generated files do not claim that a student or patent expert has approved them. B should adopt one shared integration for the team before phase 2; members should not build separate profile sets.

## Start here

1. Extract this ZIP on a computer.
2. Open `START_HERE_ZH.md` for instructions.
3. Double-click `review/index.html` in Chrome or Edge. It is self-contained and works offline.
4. Review the original 10 cases, with own, mismatched, and art-unit versions for each. Enter your judgments in the page and export `profile_review_C_done.csv`.
5. Return the CSV and this exact candidate package to B, and copy D on the statistics and attribution notes in `C_PHASE1_FINDINGS.md`.

The review form keeps the original CSV column names. It records the hash of the actual integrated candidate being reviewed, rather than B's earlier draft. Review values are `yes`, `qualified`, `no`, or `unknown`; verdicts are `pass`, `pass_with_limits`, `needs_fix`, or `unknown`. The blank `profile_review_C.csv` is an alternative for manual CSV editing; the HTML page is easier to use.

## What has been completed

- Verified A's manifest: 79,531 files, all sizes and SHA1 hashes matched.
- Rebuilt D's `episodes.csv`, `case_episodes.csv`, `stats_cards.jsonl`, and `leak_check.csv` from A's raw corpus. All four outputs were byte-identical to D's handoff.
- Independently recomputed D's principal counts, communication shares, KM next-letter medians, first-reply outcomes, cumulative incidence at the stated horizons, and RCE frequencies for all 300 cards.
- Recreated B's 100 retrieval-query hashes and replayed the original 30 review retrievals before integration.
- Assembled 300 new candidates, using D's per-case episode boundaries and cutoffs. Retrieval includes allowances and other eligible communications, rather than only signed rejections.
- Checked all 300 candidates against A and D: dates, declared benchmark-family separation, pool metadata, source hashes, extractive spans, transaction events, and episode alignment passed.
- Prepared the final proposed wording in `prompts/profile_block.txt`, a self-contained source review page, and separate AI-assisted observations.

These checks establish artifact consistency within the supplied corpus and family definition. They do not establish complete examiner attribution, legal correctness, causal response effects, or human review completion.

## Files

| File or directory | Use |
| --- | --- |
| `review/index.html` | Human review interface with current cutoff-visible records, historical sources, D cards, and CSV export |
| `profile_review_C.csv` | Original 10-case / 30-version review table, deliberately left pending |
| `prompts/profile_block.txt` | Proposed common profile-block template |
| `candidate_profiles/{own,mismatched,artunit}/` | 100 candidate JSONs per version; only `profile_text` belongs in the model prompt |
| `profile_manifest.csv` | Candidate paths and external file SHA1s, text hashes, cutoff and retrieval coverage |
| `retrieval_audit.csv` | The 897 retrieved slots, including source applications, dates and attribution status |
| `build_summary.json` | Coverage and build status; not a human approval record |
| `C_PHASE1_FINDINGS.md` | Findings, integration changes and decisions for B/D |
| `audit/integrated_source_checks_300.csv` | Output-to-source checks for every candidate |
| `audit/integrated_verification_summary.json` | Source-check counts, A manifest result and D rebuild hashes |
| `audit/AI_assisted_review_observations.csv` | Machine/AI-assisted observations, explicitly separate from student labels |
| `code/validate_package.py` | Read-only package and completed-review validator; Python standard library only |
| `code/rebuild_candidates.py` | Optional reproducible candidate builder for B; requires NumPy and scikit-learn |

The A, B, D and benchmark source ZIPs are not duplicated here. Review sources for the fixed 10 cases are embedded in the HTML. Raw source text can contain public names or OCR artifacts; it is for inspection, not prompt input.

## Shared integration rules

1. Use the A1 cutoff and examiner identity in A v2 `cases.csv` for these B/C/D profiles. The fallback case `14353039` remains explicitly qualified. State-tracking tasks at O1 need separately cut profiles; these A1 profiles must not be reused there as-is.
2. Start from D `case_episodes.csv` for each `(sample_id, variant)`. Only observed next events with `next_signed_ok=True` enter retrieval. This flag includes notices whose signatures are unverified; it is not itself proof of a signature.
3. The proposed source gate additionally excludes known other-signer prior CTNF/CTFR actions and candidates without readable pre-outcome retrieval context. The change is logged and must be adopted consistently if this set is used.
4. Rank using B's TF-IDF settings on the prior action and available reply text only. Do not use the next notice or current target outcome as a ranking feature. Select up to three distinct applications and families, with deterministic episode-ID tie-breaking.
5. Summaries are deterministic extracts with explicit clipping. Missing reply bodies or notice text remain missing. A transaction-only allowance establishes the communication type and date, not the reasoning for allowance.
6. Preserve D's numeric statistics and original `card_sha1`. The candidate rendering labels raw and already-delivered adjusted values separately, and labels D's observed subgroup medians as upper medians. The rendered text receives its own hash.
7. Use only `profile_text` as the added model block. Do not pass JSON metadata containing `setting`, examiner hashes, review notes or the control labels to the model. Every prediction should record the external profile-file hash from `profile_manifest.csv`.

There are 298 full k=3 profiles. `13484627/own` has one example and `13627444/mismatched` has two. They are retained and flagged. No cases were replaced, no examples were copied, and no family/date rule was relaxed.

The largest block is 5,794 UTF-8 bytes. This is a conservative byte bound below the 8,000-token ceiling for the byte-level tokenizers under consideration, not an exact GPT or Qwen tokenizer measurement. Actual request token usage should still be logged in phase 2.

## Optional validation

From this directory, with Python 3:

```bash
python code/validate_package.py
python code/validate_package.py --review profile_review_C_done.csv
```

The second command returns exit code 2 for complete but unresolved human judgments, and 1 for missing fields or integrity errors. It never changes or freezes profiles. It accepts honest `unknown`/`needs_fix` judgments and reports them for follow-up.

For B to reproduce in a new directory:

```bash
python code/rebuild_candidates.py \
  --a /path/to/profile_corpus \
  --b /path/to/B_phase1_v2 \
  --d /path/to/D_phase1_v1 \
  --benchmark-zip /path/to/data_v1_share.zip \
  --output /path/to/NEW_C_candidate_output \
  --work-dir /path/to/private_build_work
```

The builder refuses to overwrite a nonempty output directory. Its dependencies and supplied prompt template must be available. The private build work includes review contexts; the portable builder produces candidates and machine-readable review data, not a fresh copy of the HTML interface.

## After human review

B and D should resolve `needs_fix`/`unknown` rows and explicitly record acceptance of coverage and attribution limitations. If a profile or prompt changes, recompute its hashes and review the affected version again. Preserve reviewed candidate bytes; store approval separately rather than editing a `C_review_status` field inside an already hashed JSON.

Before phase 2, record one shared release manifest and prompt hash, then perform the planned 3–5 dev format checks. This corpus supplies test-case examiner histories; it does not provide examiner histories for arbitrary dev cases. Use dev-specific histories or clearly labeled empty/synthetic format fixtures, without attaching later test histories to earlier dev examples.

No baseline reruns, new model scores, statistical significance claims or phase-2 executions are included. Applicant Response remains archived and is not restored to Table 3.
