#!/usr/bin/env bash
#
# Monthly auto-update — runs on the 10th via launchd (com.aipcatalog.monthly).
# RMA releases/revises rainfall-index data monthly (with new reinsurance-year rates,
# CBVs, and the climate-base recompute landing annually), so:
#
#   every month : product-catalog refresh (AIP sites, cached SERFF payloads, seeds, enrich)
#                 + PRF optimizer re-score of only the grids whose 2006-2024 index
#                   window actually MOVED (src.prfsweep --bulk --changed-only)
#   January only: heavy annual pulls — ADM county availability, PRF CBVs, Summary of Business
#
# ANNUAL VI/RI VINTAGE REFRESH (the one manual-ish step):
#   RMA republishes Rainfall_Index_HistoricData<YYYY>CY.zip once a year — the new crop
#   year's file appears in the fall and is final in January, when the previous year's
#   indices become complete. That is when the whole optimizer must be re-based:
#
#       .venv/bin/python -m src.prfbulk --indices --rates --force   # ~2 min, ONE download
#       .venv/bin/python -m src.prfsweep --bulk --jobs 6 --force    # ~1 h, all CONUS
#
#   Point src/prfbulk.BULK_URL at the new crop year first. Between vintages the monthly
#   --changed-only pass below is nearly free: RMA's within-year revisions touch a handful
#   of grids, so almost nothing needs re-scoring.
#
# Ends with ./publish.command (regenerate map+xlsx, pytest gate, commit only if changed,
# push -> Streamlit Cloud redeploys). Log: output/monthly_log.txt.
#
#   ./scripts/monthly_update.sh          # full run (what launchd invokes)
#   ./scripts/monthly_update.sh --check  # verify prerequisites only, no work
#
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=output/monthly_log.txt

say() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG"; }

if [ "${1:-}" = "--check" ]; then
  ok=1
  [ -x "$PY" ] || { echo "MISSING venv"; ok=0; }
  git remote get-url origin >/dev/null 2>&1 || { echo "MISSING origin remote"; ok=0; }
  $PY -c "import src.prfsweep, src.prfbulk, src.prfdata, src.refresh" 2>/dev/null || { echo "IMPORT FAILURE"; ok=0; }
  sqlite3 data/catalog.db "SELECT 1 FROM prf_index_hash LIMIT 1;" >/dev/null 2>&1 \
    || echo "NOTE: prf_index_hash empty — the next --changed-only pass re-scores everything once"
  [ "$ok" = 1 ] && echo "check OK: venv, remote, modules all present"
  exit $((1 - ok))
fi

say "=== monthly update starting ==="

# Never overlap a manual sweep/refresh already in progress.
if pgrep -f "src.prfsweep|src.refresh" >/dev/null 2>&1; then
  say "SKIP: a sweep/refresh process is already running; exiting."
  exit 0
fi

# 1. Product catalog refresh (polite scrapes + cached SERFF payload import + seeds + enrich).
say "[1/4] product-catalog refresh (--source all)"
$PY -m src.refresh --source all >>"$LOG" 2>&1 || say "WARN: catalog refresh exited nonzero (continuing)"

# 2. January only: heavy annual pulls (new reinsurance-year ADM / CBV / SoB).
if [ "$(date +%m)" = "01" ]; then
  say "[2/4] January: annual ADM + PRF CBV + SoB refresh"
  $PY -m src.refresh --source rma_adm,prf_adm,rma_sob --force --no-enrich >>"$LOG" 2>&1 \
    || say "WARN: annual refresh exited nonzero (continuing)"
else
  say "[2/4] skipped (annual pulls run in January)"
fi

# 3. PRF optimizer: re-score only the grids whose index window moved (no network at all).
#    Replaces the old per-state `--force` re-sweep, which refetched every grid from the
#    PrfWebApi (~6 requests x 13,462 grids) and rescored the whole country every month.
#    prf_index_hash makes the no-change case a few seconds instead of hours.
#    ALL 15 use x coverage combos are shipped, so all 15 must be re-scored — otherwise
#    fourteen of them silently drift out of step with the one that updated.
#    prf_index_hash is keyed by GRID ONLY, so each combo must run with --keep-hashes:
#    letting the first combo stamp the hashes would make combos 2..15 see "nothing
#    changed" and skip everything while still reporting success. Hashes are stamped
#    once, after the loop, with `prfbulk --hashes`.
NGRIDS=$(sqlite3 data/catalog.db "SELECT COUNT(*) FROM prf_grid_county;" 2>/dev/null)
if [ "${NGRIDS:-0}" -gt 0 ]; then
  say "[3/4] PRF re-score: bulk, changed grids only, all 15 use x coverage combos"
  rescore_rc=0
  for USE in Grazing Haying Haying-Irrigated; do
    for COV in 0.70 0.75 0.80 0.85 0.90; do
      say "      re-score $USE @ $COV"
      $PY -u -m src.prfsweep --bulk --changed-only --force --keep-hashes \
          --use "$USE" --coverage "$COV" --jobs 4 >>"$LOG" 2>&1 \
        || { rescore_rc=1; say "WARN: $USE @ $COV exited nonzero (resumable; continuing)"; }
    done
  done
  # Stamp the window hashes once, now that every combo has seen this month's changes.
  $PY -m src.prfbulk --hashes >>"$LOG" 2>&1 \
    || say "WARN: hash stamp exited nonzero — next run re-scores the same grids (safe)"
  [ "$rescore_rc" = 0 ] && say "      all 15 combos re-scored" || say "      some combos warned (see log)"
else
  say "[3/4] prf_grid_county empty — run 'python -m src.prfbulk --indices --rates' first"
fi

# 4. Regenerate artifacts, test gate, commit-if-changed, push (Streamlit Cloud redeploys).
say "[4/4] publish"
./publish.command >>"$LOG" 2>&1
rc=$?
if [ $rc -eq 0 ]; then say "=== monthly update complete ==="; else say "=== publish FAILED (rc=$rc) — see log ==="; fi
exit $rc
