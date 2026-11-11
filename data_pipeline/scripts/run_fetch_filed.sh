#!/bin/zsh
# v1.1: fetch as-filed SPEC/CLM/ABST where the PGPUB came out after O1, extract text (OCR only without XML),
# then rebuild examples / labels / share package and A's state inputs + reference drafts.
set -e
cd ~/examinerbench
source ~/.zshrc
python3 scripts/v1_fetch_filed.py
APPS=$(python3 -c "import json;print(' '.join(a for a,_,_ in json.load(open('data_v1/filed_docs_to_fetch.json'))))")
python3 scripts/v1_text.py --ocr --jobs=4 ${=APPS}
python3 scripts/v1_build.py > /dev/null
python3 scripts/v1_profiles_build.py
python3 scripts/v1_package.py
python3 A/scripts/build_state_inputs.py
python3 A/scripts/build_state_gold_draft.py > /dev/null
python3 A/scripts/build_state_gold_draft.py --dev > /dev/null
echo "ALL DONE"
