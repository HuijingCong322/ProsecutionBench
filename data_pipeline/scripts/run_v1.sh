#!/bin/zsh
# One overnight run: main dataset (1000 eligible applications), then examiner profiles.
cd "$(dirname "$0")/.." && source ~/.zshrc
python3 scripts/v1_fetch.py --target 1000 && python3 scripts/v1_profiles.py
