#!/bin/bash
# Runs text extraction + OCR fallback repeatedly while v1_fetch.py is downloading, then once more at the end.
cd "$(dirname "$0")/.."
while true; do
  python3 -u scripts/v1_text.py --ocr --jobs=4 > v1_text_last.log 2>&1
  if grep -q "^done:" v1_run.log; then python3 -u scripts/v1_text.py --ocr --jobs=4 > v1_text_last.log 2>&1; echo finished > v1_text.done; break; fi
  sleep 600
done
