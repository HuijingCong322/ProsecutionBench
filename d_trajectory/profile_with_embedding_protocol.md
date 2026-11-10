# D protocol: profile_with_embedding (week of 2026-11-09)

Owner: D (Nancy Hu). Tasks: Disposition, Remaining Rounds, Time to Next Action.

Cases: the same 100 test_core cases as all D tables. Each case is cut at its A1 cutoff, the applicant's first reply.
Nothing dated after the cutoff is used.

Why this run: at the 2026-11-05 meeting the mentor asked for three changes.
1. Retrieve past applications by their **patent content** (title / abstract / claims), using an **embedding**, not
   TF-IDF.
2. Report the **average of the top-3 related past applications** first (no LLM).
3. Give the LLM the **retrieved applications themselves**, not a summary.

B finished the search on 2026-11-05 (`B_shared_BGE_M3_dense_v1_2026_11_05`). This run builds D's part on it.

## 1. What the examiner block is (definitions used from this run on)

| Setup | What the LLM sees about the examiner | Uses B's search? |
| --- | --- | --- |
| **card** | **Statistics only**, computed from **all** of the examiner's past applications before the cutoff (the team's frozen statistics text, with its reading notes). No past-application examples | No |
| **paths** | The **3 past applications most similar** to this case: their dated events and their status at the cutoff. No statistics | Yes |
| **fulldoc** | The same 3 past applications **in full**: abstract, claims, every document before the cutoff, then their dated events and status. No statistics | Yes |

The earlier card (2026-11-03) also carried 3 short "reply → next letter" excerpts picked by the old TF-IDF search.
Those excerpts are dropped: the past applications are now picked by B's search on patent content and shown in paths /
fulldoc, and the 11-04 test showed the excerpts added nothing beyond the statistics. The 11-03 card results are
therefore not reused; the card is run again with statistics only.

## 2. Questions

- **A (standard RAG).** Given the 3 most similar past applications **in full**, does the LLM forecast better than
  without them? Is that because of this examiner? Does it beat the top-3 average of the same 3 applications, and the
  statistics card?
- **B (paths).** Given only the dated events of the same 3 applications, the same questions.
- **C (card).** Does the statistics card help the LLM, is that about this examiner, and does the LLM add anything to
  the card's numbers?
- **N (no LLM).** Is the top-3 average of the most similar past applications better than the examiner's full-history
  numbers?

## 3. Setups and output tags

M = GPT-5-mini (Azure, reasoning_effort low; 8192 → 16384 → 32768 token retry rule), case record + A's state (A_v1),
frozen *_profile.txt prompts. Only the examiner block in `{profile}` differs between the LLM setups.

**LLM, this run (each for the own examiner and a wrong examiner):**

| Setup | Output tag |
| --- | --- |
| card | `{M}_state_profile_with_embedding_card_{own,mismatched}` |
| paths | `{M}_state_profile_with_embedding_paths_{own,mismatched}` |
| fulldoc | `{M}_state_profile_with_embedding_fulldoc_{own,mismatched}` |

The notebook treats a setup as finished when both of its output files hold all 100 cases answered with the frozen
prompt and this blocks file; a finished setup is not run again.

**Reference runs, reused:**

| Run | Output tag |
| --- | --- |
| LLM, no examiner block | `{M}_state` |
| LLM, paths of the old TF-IDF top-3 (2026-11-05) | `{M}_state_history_own` |

**No LLM:**

| Method | Output tag | Status |
| --- | --- | --- |
| top-3 average, own / wrong examiner | `emb_top3_math_{own,mismatched}` | computed (`topk_math.py`) |
| full-history numbers: the statistics card's numbers blended with the art-unit pool | `prior_own` | done 2026-11-05, reused |
| top-3 average of the old TF-IDF top-3 | `history_math_own` | done 2026-11-05, reused |
| plain average | `km` | done, reused |

"Wrong examiner" (mismatched) = another examiner of the same art unit. The block has identical wording, so the model
cannot tell it is the wrong examiner.

## 4. What is frozen

| Item | Value |
| --- | --- |
| B's search package | `B_shared_BGE_M3_dense_v1_2026_11_05_TEAM_ONLY.zip`, sha256 `ff3db404a413b1f1d74b3f5c1b2b4c198d9ab87ef28196cfc7c32c3496e38917`. BGE-M3 revision `5617a9f6…`, dense CLS + L2 + cosine, long texts split into windows and averaged (never cut). Query = the case's abstract + claims before its cutoff; candidates = the examiner's past applications, each as abstract + claims dated no later than its first usable reply; top 3, one per family |
| Which top-3 | B's **raw** top-3 (`ranking_top3_links_before_review.csv`) for every case: own 99 cases × 3 and 1 × 1; wrong 99 × 3 and 1 × 2. B's later review removed 47 examples, but only in the 10 cases it reviewed by hand. Using the raw list keeps one rule for all 100 cases |
| Statistics card | the field `statistics_text` of each profile in B's package (sha1 checked against its `statistics_text_sha1`). It is the team's frozen statistics text, word for word the same as in `B_D_C_phase1_v4_reviewed` (checked for all 200 case × examiner rows) |
| Event and text source | A's `profile_corpus_v2.zip` (`apps/<id>/transactions.csv`, `catalog.csv`, `text/`) |
| Examiner blocks | `inputs/examiner_blocks_emb_v1.jsonl`, sha1 `963c00122fe59b8799e8214634b8899900977558`, built by `code/build_examiner_blocks_emb.py` (deterministic; the notebook rebuilds it in Colab and checks the sha1). 200 rows (100 cases × own/wrong), each with the card, paths and fulldoc blocks; 4,960 past-application documents, 41.8 M characters |
| Prompts | `trajectory_forecast_profile.txt` (`d7e75c380ac8`), `rounds_next_forecast_profile.txt` (`8656a89b9b39`), unchanged since 2026-11-03 |
| Code | `build_examiner_blocks_emb.py`, `examiner_history.py`, `run_trajectory_llm.py`, `run_rounds_next_llm.py`, `topk_math.py`, `compare_profile_with_embedding.py`, `D_profile_with_embedding_run.ipynb` (sha1 in `PROFILE_WITH_EMBEDDING_CODE_SHA1.txt`) |

Before any API call the runner checks the blocks file's sha1, each block's own sha1 and the release id, and that each
block's cutoff equals the case's cutoff. Any mismatch stops the run.

## 5. What the LLM sees

The block goes after the case record, before "Task", under the same line as before: "Examiner history reference for
this application's examiner, built only from the examiner's other applications and only from events before the
cutoff…".

**card** (case 13060040, own examiner, about 500 tokens):

```
Examiner history reference available before 2014-09-26

Historical statistics
Statistics for this examiner, other applications, events before 2014-09-26:
- 30 applications; 26 replies to a non-final rejection.
- Next letter after such a reply (25 seen, 1 still waiting): allowance 32%, final rejection 64%, non-final rejection 4%, other 0%.
- Days from a reply to the next letter: median 33 (allowances 59, rejections 31).
- After the first reply (20 applications): 11 allowed, 4 abandoned, 5 still pending; estimated allowed within 12 months 48%, within 24 months 65%; abandoned within 24 months 26%.
- Further rejections after the first reply: 0: 26%, 1: 43%, 2: 8%, 3+: 23%; RCE filed in 25%.
- Grounds in 54 rejections attributed by A to the handling examiner (...): 103 in 93%, 102 in 54%, 112 in 50%, 101 in 24%.

Reading convention: (how the numbers are defined: raw percentages, KM median, pending outcomes unknown, attribution limits)

Use this reference to inform the task while grounding the prediction in the current application's record. ...
```

**paths.** For each of the 3 past applications: its id, its dated events before the cutoff, and its status on the
cutoff date. The same renderer as 11-05.

**fulldoc.** For each of the 3 past applications:
1. its abstract and claims as published, if published before the cutoff;
2. **every document A downloaded for it, dated before the cutoff, in full, oldest first**: examiner letters (non-final
   and final rejections, restrictions, advisory actions, allowances), applicant replies, remarks and claim listings.
   Each document starts with the same header line as the case's own record, `[doc_id | code | date | role | source]`.
   It is the raw USPTO text, the same kind as the case record, with nothing summarized or shortened;
3. its dated events and its status on the cutoff date (the same lines as "paths").

Size: median ~45k tokens per block, at most ~168k. The whole prompt is at most ~240k tokens, under GPT-5-mini's 272k
input limit. Not included, because A's corpus does not hold them for past applications: the specification, the title
with a date, and forms or fee sheets.

Example (case 13060040, past application 3 = 12343838): its abstract, claims, the 2012-07-06 non-final rejection, the
2012-10-09 claims, the 2012-11-06 final rejection, the 2013-01-07 claims and the 2013-01-18 notice of allowance, all in
full; then its events and "Status on 2014-09-26: allowed".

## 6. The top-3 average, no LLM (`topk_math.py`)

The mentor asked to see this first. It takes the same 3 past applications the LLM sees in paths and fulldoc and
applies the same math as `history_math.py` (11-05) to their dated events, cut at the cutoff:
- next action = the median waiting time from first reply to next letter;
- rounds = the median count of further rejections;
- disposition = the training curves stretched to the share allowed / abandoned within 24 months.

It is set against the examiner's **full-history numbers** (`prior_own`): the statistics card's numbers blended with
the art-unit pool, as in 11-05.

## 7. Comparisons (`compare_profile_with_embedding.py`)

**Metrics:**
- Disposition: C-index (IPCW, τ = 730 days) and IBS.
- Rounds: MAE and exact accuracy.
- Next action: C-index and MAE in days.

**Method:** paired bootstrap, 1,000 draws, seed 20261010, on the cases where both methods answered. "Clear" = the 95%
interval excludes 0.

| # | Comparison | Question |
| --- | --- | --- |
| A1 | fulldoc own − no examiner block | Does the full RAG help the LLM? |
| A2 | fulldoc own − fulldoc wrong | Is it about this examiner? |
| **A3** | **fulldoc own − top-3 average own** | **Does the LLM beat the top-3 average of the same 3 applications? (main)** |
| A4 | fulldoc own − paths own | Do the documents add anything beyond the dated events? |
| A5 | fulldoc own − card own | Full RAG vs the statistics card |
| B1 | paths own − paths wrong | Is it about this examiner? |
| B2 | paths own − top-3 average own | LLM vs the top-3 average of the same 3 |
| B3 | paths own − card own | Paths vs the statistics card |
| B4 | paths own (new search) − old paths own (TF-IDF) | Does the new search help the paths setup? |
| C1 | card own − no examiner block | Does the statistics card help the LLM? |
| C2 | card own − card wrong | Is it about this examiner? |
| C3 | card own − full-history numbers (no LLM) | Does the LLM add anything beyond the card's numbers? |
| N1 | top-3 average − full-history numbers | Are the 3 most similar better than the examiner's full history? |
| N2 | top-3 average own − top-3 average wrong | Is it about this examiner? |
| N3 | top-3 average (new search) − top-3 average (old TF-IDF) | Does the new search pick better applications? |

**Copy check:** how often the LLM's days equal a number it can read or work out from its block: the card's median
days (card runs), or the top-3 average's days (paths and fulldoc runs).

**Reading A3:**
- Clear in the LLM's favour: the LLM uses the full applications better than the math does.
- Not clear: it does about what the math does.
- Clear against: the top-3 average is the better use of the same 3 applications.

## 8. Format check (before the full run)

**Cases:** 7 fixed test_core cases, chosen for edge cases and not outcomes:
- 13060040 (normal);
- 13484627 (own: 1 past application);
- 13627444 (wrong: 2);
- 13577408;
- 14031839 (thin history);
- 14506249 (the longest own fulldoc block);
- 14940084 (the longest total prompt).

**Calls:** 3 setups × own/wrong × both prompts × 7 cases = 84 calls, written to `outputs/D/dev/*_formatcheck.jsonl`
and never scored.

**Pass** = all answers parse, none is cut off, and every saved prompt meets all of these:
- the block sits before "Task" and carries the case's cutoff date;
- card blocks hold the statistics and no past application or example;
- paths and fulldoc blocks hold no statistics;
- every fulldoc document date is before the cutoff.

Accuracy on these 7 cases is not looked at.

## 9. Cost and time

The full stage makes 1,200 calls: 3 setups × own/wrong × 2 prompts × 100 cases.

| Setup | Tokens in (both prompts, own + wrong) | Cost |
| --- | --- | --- |
| fulldoc | ~38 M | ~$10 |
| paths | ~17 M | ~$4.5 |
| card | ~17 M | ~$4.5 |

Total about $20 at $0.25 / $2 per 1M tokens. Calls run one at a time to stay under the Azure tokens-per-minute limit.
The runner retries 429 errors up to 6 times, waiting up to 90 s. Results are cached per case, so a disconnect only
means running again.

## 10. Failures and limits

- A broken answer is retried once with the same prompt, then listed as failed and never filled with defaults. Paired
  tests use the cases both methods answered, and n is reported.
- There is one model and one run per setting, on 100 cases.
- The card's statistics come from up to 30 past applications per examiner (A's download cap), not the examiner's whole
  workload.
- The search compares abstract + claims only; no dated title was available. It can compare only past applications
  that have an abstract and claims, a subset of the applications the card uses (for 13060040: 19 of 30).
- For many cases the examiner's history holds nothing truly about the same invention. The scores are compressed:
  median best match 0.75, median worst 0.58, and the wrong examiner's best matches score about as high.
- In 81 of 100 cases the art-unit pool is one other examiner, the same one used as the wrong examiner.
- The math counts still-pending past applications by what is known at the cutoff (a lower bound).
