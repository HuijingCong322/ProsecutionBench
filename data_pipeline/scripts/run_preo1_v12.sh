#!/bin/zsh
# v1.2: add documents between filing and O1 (and filing-day originals missed because of placeholder
# catalog rows) to the inputs; download text (XML, else PDF+OCR); rebuild examples, profiles, package,
# A's state inputs and reference drafts.
set -e
cd ~/examinerbench
source ~/.zshrc
caffeinate -i python3 scripts/v1_fetch_preo1.py
APPS=$(python3 -c "import json;print(' '.join(json.load(open('data_v1/preo1_apps.json'))))")
caffeinate -i python3 scripts/v1_text.py --ocr --jobs=4 ${=APPS}
python3 scripts/v1_build.py > /dev/null
python3 scripts/v1_profiles_build.py
python3 scripts/v1_package.py
python3 A/scripts/build_state_inputs.py
python3 A/scripts/build_state_gold_draft.py > /dev/null
python3 A/scripts/build_state_gold_draft.py --dev > /dev/null
echo "ALL DONE"
