#!/bin/zsh
# v1.1 examiner profiles: backfill pre-cutoff profile apps + family check, then rebuild examples and package
set -e
cd ~/examinerbench
source ~/.zshrc
caffeinate -i python3 scripts/v1_profiles_backfill.py --only-test
python3 scripts/v1_profiles_build.py
python3 scripts/v1_package.py
echo "ALL DONE"
