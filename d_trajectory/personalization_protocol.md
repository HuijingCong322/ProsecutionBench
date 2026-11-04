# D phase 2 protocol: LLM + examiner profile (trajectory tasks)

Owner: D (Nancy Hu). Written 2026-11-03, **before any profile run**. Status: **FROZEN** once committed to the repo.
Tasks: Disposition, Remaining Rounds, Time to Next Action. Cases: the same 100 test_core cases as all earlier D tables.

## 1. What is frozen

| Item | Value |
| --- | --- |
| Profile package | `B_D_C_phase1_v4_reviewed.zip`, sha256 `d1e6e358757ba758a17373f14894449284253da1cfe4d775a0bbac6a7b207d8f` |
| Release id | `B_D_C_v4_reviewed_2026_11_02` (`RELEASE_MANIFEST.json`) |
| `profile_manifest.csv` | sha256 `33441c94fe1f1aaa243420bb8b05ef4f85cb5235209d7aeeffa552a16257f986` |
| Profile block template | sha1 `28cae91a24298803fd84c8e932f4d010e63f938a` |
| D stats cards inside it | `stats_cards.jsonl` sha1 `5d165efb31b444277eab3fced47807863b149d04` (= D's own file; all 300 card_text, card_sha1 and numbers identical, checked 2026-11-03) |
| Disposition prompt with profile | `prompts/trajectory_forecast_profile.txt`, prompt_hash `d7e75c380ac8` |
| Rounds + Next prompt with profile | `prompts/rounds_next_forecast_profile.txt`, prompt_hash `8656a89b9b39` |
| Baseline prompts (unchanged) | `trajectory_forecast.txt` `8fa99d848c11`, `rounds_next_forecast.txt` `2e8f78f097b3` |
| Code | `profile_inject.py`, `run_trajectory_llm.py`, `run_rounds_next_llm.py`, `compare_profile_runs.py`, `D_phase2_profile_run.ipynb` (sha1 in `PHASE2_CODE_SHA1.txt`) |

**The only change to the prompt** is one new input item after the record, then the profile text, before "Task":

```
- Examiner history reference for this application's examiner, built only from the examiner's other applications
  and only from events before the cutoff. It is background about the examiner; the documents above are the record
  of this application.

{profile_text}
```

The wording is the same for own and mismatched, so the model cannot tell which one it got (blind control).
Only `profile_text` from `candidate_profiles/<setting>/<sample_id>.json` goes in. Every file and text hash is checked
against `profile_manifest.csv` before any call; one mismatch stops the run.

**Everything else is the same as the no-profile runs:** same 100 cases, same A1 cutoff, same history documents, same
A state (`inputs/state_predictions_A.jsonl`, state_version `A_v1`), same models and settings (GPT-5-mini with
reasoning_effort low and the 8192 → 16384 → 32768 retry rule; Qwen3.6-27B team setting), same answer rules, same
scoring code. The no-profile code path was checked to give the same cache keys as before, so the old runs stay valid.

## 2. Runs

| # | Model | Profile | Prompts | Output tag |
| --- | --- | --- | --- | --- |
| 1 | GPT-5-mini | own | both | `gpt-5-mini_state_profile_own` |
| 2 | GPT-5-mini | mismatched | both | `gpt-5-mini_state_profile_mismatched` |
| 3 | Qwen3.6-27B | own | both | `qwen3.6-27b_state_profile_own` |
| 4 | Qwen3.6-27B | mismatched | both | `qwen3.6-27b_state_profile_mismatched` |

Reused, not re-run: `gpt-5-mini_state`, `qwen3.6-27b_state` (no profile), `prior_own`, `prior_mismatched` (numbers only), `km`.

**Not run: art-unit profile with the LLM.** The art-unit pool is the same single other examiner as the mismatched
profile in 81 of 100 cases, so it would mostly repeat run 2/4. The art-unit row stays in the numbers-only table, with
that caveat.

Expected cost: GPT about $1.3–1.5 per 100 cases per prompt, so about $6 for runs 1–2. Qwen: the October runs took
1.2–3 hours per 100 cases per prompt, so about 5–12 GPU-hours for runs 3–4 (4 runs of 100); delete the endpoint after.
GPT route: Azure, as for the baselines (`gpt-5-mini-2025-08-07`). If only OpenAI's own API is available, the same
model is used and the route is recorded in every output row and reported.

## 3. Format check (before the full runs)

There are no profiles for the 3 dev cases, so the check uses **5 fixed test_core cases**, chosen for their edge
cases, not for their outcomes:

| Case | Why |
| --- | --- |
| 13060040 | normal profile (k = 3); the example followed in the week report |
| 13484627 | own profile with only 1 retrieved example; all first-reply cases still pending |
| 13627444 | mismatched profile with 2 examples; all-censored card |
| 13577408 | mismatched profile with statistics only (k = 0) |
| 14031839 | thin own profile ("Few cases: treat these numbers as rough"); all-censored card |

For each model: own and mismatched × both prompts (20 calls). Written to `outputs/D/dev/*_formatcheck.jsonl`, which
the scorers never read. **Pass** = all 20 answers parse (status ok), no answer cut off, the saved prompt shows the
profile block in the right place with the case's cutoff date, and no hash error. Accuracy on these 5 is **not looked at**.
These calls are cached and reused by the full run (same inputs, same key).

If the check fails because of format, fix only the format, re-hash, re-run the check, and write the change here.
After the check passes, nothing in section 1 changes.

## 4. Comparisons (fixed now)

Metrics: Disposition C-index (IPCW, τ = 730 days) and IBS; Remaining Rounds MAE and exact accuracy; Next Action C-index and
MAE in days. Paired bootstrap, 1,000 draws, seed 20261010, on the cases where both methods have an answer.
"Clear" = the 95% interval does not include 0.

For each model M:

1. **Primary:** M + own profile − M without profile. Does the profile help the LLM?
2. M + own profile − M + mismatched profile. Is the gain about *this* examiner?
3. **New bar:** M + own profile − examiner numbers only (`prior_own`). Does the LLM add anything beyond copying the
   examiner's averages? (The paper's shortcut warning.)
4. Control: M + mismatched profile − M without profile.

How to read it (fixed now):
- Profile helps and beats the numbers-only row → the LLM uses the profile *and* the case record.
- Profile helps but does not beat numbers-only → the gain is mostly the examiner's base rate (shortcut); say so.
- Mismatched helps about as much as own → the gain is not examiner-specific (format or "any statistics" effect).

## 5. Planned splits (descriptive, no new tests)

- retrieved_k = 3 vs < 3 (own: 1 case below 3; mismatched: 4).
- RCE in the true path: 0 vs 1+ (the known weak spot for Remaining Rounds).
- The 6 all-censored cards (5 own, 1 mismatched) vs the rest. Their "3+ rounds 100%" is leftover survival tail mass,
  not an observed frequency. For numbers-only, these 5 own cards predict 4+ rounds.

## 6. Failures

Same rules as before: a broken answer is retried once with the same prompt, then listed as failed and never filled
with defaults. Qwen API failures are kept (`--retry-failed` only as an explicit, logged resume). Paired tests use the
cases both methods answered, and the n is reported.

## 7. Reporting

- Report the real coverage: own 99 with k = 3 and 1 with k = 1; mismatched 96 k = 3, 1 k = 2, 3 statistics only. Do not
  write "k = 3 for all".
- Examiner = the handling examiner in the contact paragraph ("should be directed to …"); the letter may be co-signed
  by a primary examiner or SPE. Not "signature verified".
- The profile shows raw rates; the numbers-only baseline uses rates shrunk toward the art-unit pool (k = 5). Say this
  when comparing the two.
- Profiles are cut at the A1 cutoff, the same cutoff as all three D tasks.
