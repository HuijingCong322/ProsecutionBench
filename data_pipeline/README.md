# Data pipeline: USPTO download and text extraction

Scripts that build the shared dataset `data_v1_share/` (1,000 applications) and the examiner
library `profile_corpus/` from the USPTO Open Data Portal (Patent File Wrapper API). The data
itself is not in this repository; it is on the shared Drive.

The scripts are committed exactly as they were run. They expect to live in `scripts/` next to
the data folders (`data_v0/`, `data_full/`, `data_v1/`) and need a USPTO API key in the
environment variable `USPTO_API_KEY`. The key is never written to disk.

## Main dataset (`data_v1_share/`)

| Order | Script | What it does |
|---|---|---|
| 1 | `odp_fetch.py` | API client: document list (`catalog.csv`), event log (`transactions.csv`), metadata. Imported by the others. |
| 2 | `full_fetch.py` | Eligibility screen (utility application, filed 2008-2015, has a first Office Action and a reply) and the sampling frame order. |
| 3 | `build_rounds.py` | Finds the first Office Action, the applicant's reply and the cutoff; selects the documents dated on or before the cutoff. |
| 4 | `v1_fetch.py` | Main download. For each selected document: USPTO XML text if offered, else the published application, else the PDF (for OCR). |
| 5 | `v1_fetch_filed.py`, `v1_fetch_preo1.py` | Follow-up downloads for v1.1 (as-filed documents when the publication came out after the cutoff) and v1.2 (documents between filing and the first Office Action). |
| 6 | `v1_text.py` | XML to plain text and structured claims; OCR (tesseract) only for documents with no USPTO text. |
| 7 | `v1_build.py`, `v1_grounds.py` | Builds `examples/*.json`, labels and splits; parses rejection grounds. |
| 8 | `v1_package.py` | Assembles `data_v1_share/` with input hashes. |
| check | `pgpub_leak_audit.py` | Verifies that no publication dated after a cutoff is used as an input. |

Run scripts: `run_v1.sh`, `run_ocr.sh`, `v1_ocr_loop.sh`, `run_fetch_filed.sh`, `run_preo1_v12.sh`.

## Examiner library (`profile_corpus/`)

| Script | What it does |
|---|---|
| `v1_profiles.py`, `v1_profiles_backfill.py`, `v1_profiles_build.py` | First version of the examiner profiles (v1 / v1.1). Run script: `run_profiles_v11.sh`. |
| `v2_profile_corpus.py` | Current version: downloads each examiner's other applications, same text rules as above. |
| `v2_profile_package.py`, `verify_profile_zip.py` | Packages and verifies `profile_corpus_v2.zip`. Format: `PROFILE_CORPUS_FORMAT.md`. |

## Requirements

Python 3 with `requests`, `lxml`, `numpy`, `pandas`; `tesseract` and `poppler` (`pdftoppm`) for OCR.
