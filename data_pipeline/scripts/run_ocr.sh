#!/bin/zsh
# Text extraction + OCR fallback on the Mac. Safe to run while v1_fetch.py is still downloading:
# it repeats every 10 minutes and does a final pass after the download has finished.
cd "$(dirname "$0")/.."
for t in tesseract pdftoppm; do
  command -v $t >/dev/null || { echo "installing tesseract/poppler with Homebrew ..."; brew install tesseract poppler; break; }
done
python3 -c "import lxml" 2>/dev/null || pip3 install lxml
JOBS=$(( $(sysctl -n hw.ncpu) - 2 ))
while true; do
  python3 -u scripts/v1_text.py --ocr --jobs=$JOBS
  if grep -q "^done:" v1_run.log; then python3 -u scripts/v1_text.py --ocr --jobs=$JOBS; echo "OCR FINISHED"; break; fi
  echo "waiting 10 min for more downloads ..."; sleep 600
done
