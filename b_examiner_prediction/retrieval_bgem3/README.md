# B: dense retrieval and shared-profile implementation

This update publishes implementation, tests, dependency pins and aggregate status only. The completed local release is `B_shared_BGE_M3_dense_v1_2026_11_05`. Full profiles, patent source text, embeddings, source/link manifests, review records, private examples and the team ZIP are distributed separately within the team; they are not included here.

## Method

- `BAAI/bge-m3`, revision `5617a9f61b028005a4858fdac845db406aefb181`; CLS dense embeddings, 1024 dimensions, L2 normalization and cosine ranking. No E5 query/passage prefixes, sparse retrieval, ColBERT or reranker.
- Dependencies are pinned in `code/requirements.bgem3.lock.txt`. The measured local runtime used Python 3.12.14, Apple MPS, FP16, FP32 CLS transfer, SDPA, batch size 1 and four CPU threads. Normalization, chunk means and similarity use Python double-precision floats.
- Actual text lengths and local runtime were measured before freezing the contract. Inputs above 8192 total tokens use 8190 content-token windows with 128 overlap. Every token is covered; normalize each window's CLS, average windows equally, then normalize. No silent truncation or dropped windows.
- Target technical text comes from dated abstract/claims at or before the A1 cutoff. Historical text must be available by its selected reply date and strictly before the target cutoff. Current titles without historical evidence are omitted. Known SVG extraction artifacts are logged and removed; ambiguous fields containing prosecution/identity material are excluded conservatively.
- D pools are filtered by dates, identity, benchmark application/family exclusions and source eligibility before choosing the earliest fully eligible reply episode per application. Allowance remains eligible. Sort by descending cosine, then application/family/episode IDs; take up to three distinct applications/families.
- Cache keys bind actual normalized text and the full frozen contract. Provenance-only imports require identical text and all encoder-operation fields, valid checksums and recorded lineage. Failures are explicit, never zero vectors.

## Local handoff status

Three preselected cases were checked first, followed by the original fixed ten cases across all three variants; the precheck did not replace the ten. Codex technical review is not a human D/C signature. Forty-seven weak examples were withheld without replacement or reranking.

| Retained histories per profile | Profiles |
| --- | ---: |
| 3 | 275 |
| 2 | 10 |
| 1 | 5 |
| 0 (statistics only) | 10 |

All 300 final profiles passed automated date, identity, family, source, fidelity and hash checks. Semantic case-by-case review covers the fixed ten only. The final team interface contains 850 historical links. Shared art-unit profiles were built; no art-unit prediction experiment was started.

The old reviewed snapshot, statistics cards, prediction inputs, prompts and results were preserved. This phase made no GPT/Qwen prediction calls. The comparison changes both text representation and encoder, as well as review-adjusted coverage; it does not establish an encoder-only or prediction improvement.

## Interface

Only `profile_text` is model-visible. Team-only link records provide `sample_id`, `cutoff`, `variant`, `historical_app_id`, `family_id`, `episode_id`, `rank`, `rendered_rank`, `similarity`, model revision, query/document text hashes and source paths. `rank` is the original selected order; `rendered_rank` reflects withholding. Family IDs inherit the supplied family roots and their coverage limits.

## Tests and local reproduction

Run the public tests from the repository root with pytest installed:

```sh
python -m pytest b_examiner_prediction/retrieval_bgem3/code/tests -q
```

One corpus regression requires the separately shared private data and is explicitly skipped when absent. The remaining tests use synthetic temporary fixtures; no model download or prediction API is needed.

The `code/` directory mirrors the local implementation originally at `week10_11/B/`. For a full private reproduction, restore its contents to that directory in the team workspace, keeping the separately provided `week10_11/shared/` A/D packages and old reviewed release at their original paths. Source root constants in `b_sentence_sources.py` are deliberately unchanged, preserving sealed source hashes. These scripts do not reproduce a private release from this public checkout alone.

The ordered workflow is: prepare a new root; measure tokenizer lengths and runtime; freeze a new contract; encode/build/review the three precheck cases; encode/build/review the original ten; encode/build all; validate; construct the local handoff; seal once. Use the isolated pinned runtime for model operations and offline loading flags (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `TOKENIZERS_PARALLELISM=false`, `PYTORCH_ENABLE_MPS_FALLBACK=0`). Different runtime/hardware needs a distinct contract/cache namespace. Existing sealed outputs must not be overwritten.

`embedding_tools/download_pinned_model.py` downloads the pinned model; other encoding is local. `add_handoff_materials.py` builds private team materials and must be used only in that private workspace. No data files or private outputs are needed to inspect the public implementation.
