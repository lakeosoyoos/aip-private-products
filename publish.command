#!/usr/bin/env bash
#
# One-command update for the live Streamlit app on Streamlit Community Cloud.
#
# The app serves data/catalog.db (the map is rebuilt in-memory from it at runtime),
# so "updating the app" = commit the current catalog + assets and push to GitHub.
# Streamlit Cloud watches the repo and auto-redeploys on push. This script regenerates
# the local artifacts, runs the tests as a safety gate, commits only what changed, and pushes.
#
#   ./publish.command                    # regenerate + commit + push current catalog
#   ./publish.command --refresh          # re-run all scrapers first, then publish
#   ./publish.command --dry-run          # do everything except commit/push (preview)
#   ./publish.command --remote=origin    # push target (default: origin)
#   ./publish.command --no-test          # skip the pytest gate (not recommended)
#
# First-time setup (once): push this repo to GitHub, connect it at share.streamlit.io
# (main file: streamlit_app.py), and set app_passcode in the app's Secrets. See DEPLOY.md.
#
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

REFRESH=0
DRYRUN=0
RUNTESTS=1
REMOTE=origin
STATES=IA,IL,NE,MN,IN
for arg in "$@"; do
  case "$arg" in
    --refresh)     REFRESH=1 ;;
    --dry-run)     DRYRUN=1 ;;
    --no-test)     RUNTESTS=0 ;;
    --remote=*)    REMOTE="${arg#*=}" ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed -n '2,20p'
      exit 0 ;;
    *) echo "unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

step() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }

# 0. sanity ---------------------------------------------------------------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not a git repo."; exit 1; }
[ -x "$PY" ] || { echo "Missing venv at $PY — create it and pip install -r requirements-pipeline.txt"; exit 1; }
if [ "$DRYRUN" -eq 0 ] && ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "No '$REMOTE' remote yet. Add it once (see DEPLOY.md):"
  echo "  git remote add $REMOTE https://github.com/<user>/<repo>.git"
  exit 1
fi

# 1. optional: re-run the data pipeline -----------------------------------
if [ "$REFRESH" -eq 1 ]; then
  step "Refreshing catalog from all sources (this hits the network)…"
  $PY -m src.refresh --source all --states "$STATES" --export
fi

# 2. regenerate derived artifacts from the current DB ---------------------
step "Regenerating interactive map + Excel workbook from catalog.db…"
$PY -m src.webmap
$PY -m src.refresh --export-only

# 3. safety gate ----------------------------------------------------------
if [ "$RUNTESTS" -eq 1 ]; then
  step "Running test suite…"
  $PY -m pytest -q
fi

# 4. stage — .gitignore keeps data/cache, secrets, and .venv out ----------
step "Staging changes…"
git add -A
# Guard: never let a secret or the huge ADM cache slip in.
if git diff --cached --name-only | grep -Eq 'secrets\.toml$|^data/cache/'; then
  echo "REFUSING: a secret or data/cache path is staged. Check .gitignore."
  git reset -q
  exit 1
fi

if git diff --cached --quiet; then
  step "Nothing changed — catalog is already published."
  exit 0
fi

echo
git diff --cached --stat

if [ "$DRYRUN" -eq 1 ]; then
  step "Dry run — unstaging and stopping before commit/push."
  git reset -q
  exit 0
fi

# 5. commit + push --------------------------------------------------------
STAMP=$(date +%Y-%m-%d)
NPROD=$(sqlite3 data/catalog.db "SELECT COUNT(*) FROM products" 2>/dev/null || echo "?")
step "Committing…"
git commit -q -m "Update catalog data ($STAMP): ${NPROD} products"
step "Pushing to '$REMOTE' (GitHub may prompt for username + a personal access token)…"
git push "$REMOTE" HEAD:main
step "Done. Streamlit Cloud redeploys automatically in ~1–2 min."
