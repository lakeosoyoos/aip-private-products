#!/bin/bash
# Double-click launcher (macOS). Sets up the venv on first run, then refreshes + exports.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
./.venv/bin/python -m src.refresh --source all --export
echo
echo "Done. Spreadsheet is in ./output/  —  press Enter to close."
read -r _
