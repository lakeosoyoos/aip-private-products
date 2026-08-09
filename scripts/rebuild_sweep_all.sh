#!/usr/bin/env bash
#
# Re-score every PRF use x coverage combo from scratch. ~26 min each, ~6.5 h total.
#
# This is the FULL rebuild path, distinct from monthly_update.sh's incremental one:
#   monthly  -> --changed-only --keep-hashes, re-scoring only grids whose index window moved
#   here     -> --force, every grid, because prf_opt_best is empty after a rebuild
#
# All fifteen combos are shipped, so all fifteen must exist or the app serves a coverage the
# sweep never scored. Intended use does not move a PRF premium rate (it is a function of the
# grid's rainfall distribution, the interval and the coverage level), so most combos come out
# identical -- scripts/build_app_db.py collapses that redundancy behind a view at ship time.
# They are still scored separately here because which grids are RATED does vary: Haying is
# offered on fewer, and 31 grid/coverage pairs genuinely differ.
#
# Hashes are stamped ONCE at the end. prf_index_hash is keyed by GRID ONLY, so letting the
# first combo stamp them would make combos 2..15 see "nothing changed" and skip everything
# while still reporting success.
#
#     nohup ./scripts/rebuild_sweep_all.sh > output/rebuild_sweep.log 2>&1 &
#
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

say() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$1"; }

say "=== full PRF re-score starting: 3 uses x 5 coverages ==="
rc=0
for USE in Grazing Haying Haying-Irrigated; do
  for COV in 0.70 0.75 0.80 0.85 0.90; do
    say "--- $USE @ $COV ---"
    $PY -u -m src.prfsweep --bulk --force --keep-hashes \
        --use "$USE" --coverage "$COV" --jobs 6 \
      || { rc=1; say "WARN: $USE @ $COV exited nonzero (resumable; continuing)"; }
    n=$(sqlite3 data/catalog.db "SELECT COUNT(*) FROM prf_opt_best;" 2>/dev/null)
    say "    prf_opt_best now ${n:-?} rows"
  done
done

say "stamping index hashes once, now that every combo has been scored"
$PY -m src.prfbulk --hashes || say "WARN: hash stamp failed (next run re-scores; safe)"

say "=== done (rc=$rc) ==="
exit $rc
