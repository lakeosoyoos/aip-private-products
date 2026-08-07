#!/usr/bin/env bash
#
# Sweep the PRF optimizer across the FULL use x coverage matrix, nationwide.
#
# PRF is sold for three intended uses at five coverage levels; the first national run
# scored only Grazing @ 90%. Every other combination is pure local compute — the bulk
# indices and all 15 rate sets are already in the DB, so this makes ZERO network calls.
#
#   3 uses x 5 coverage levels = 15 combos, ~56 min each at --jobs 6  (~13 h total)
#
# Resumable at every level: prfsweep skips grids already scored for a (use, coverage),
# so re-running after an interruption costs only what is genuinely missing. Combos
# already complete are detected and skipped outright.
#
#   nohup ./scripts/full_matrix_sweep.sh > output/full_matrix_sweep.log 2>&1 &
#
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
JOBS="${JOBS:-6}"
TOTAL_GRIDS=$(sqlite3 data/catalog.db "SELECT COUNT(DISTINCT grid_id) FROM prf_grid_county;")

say() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# Wait out any sweep already running so two runs never fight over the same rows.
while pgrep -f "src.prfsweep --bulk" >/dev/null 2>&1; do
  say "another sweep running; waiting 5 min..."
  sleep 300
done

say "=== full matrix sweep starting (jobs=$JOBS, $TOTAL_GRIDS grids per combo) ==="

for USE in Grazing Haying Haying-Irrigated; do
  for COV in 0.70 0.75 0.80 0.85 0.90; do
    have=$(sqlite3 data/catalog.db \
      "SELECT COUNT(*) FROM prf_opt_best WHERE intended_use='$USE' AND ABS(coverage_level-$COV)<1e-9;")
    # A combo is 'done' when it has a row for (nearly) every rated grid. Haying is
    # offered on fewer grids than Grazing, so compare against what actually rated.
    rated=$(sqlite3 data/catalog.db \
      "SELECT COUNT(DISTINCT grid_id) FROM prf_grid_rate WHERE intended_use='$USE' AND ABS(coverage_level-$COV)<1e-9;")
    if [ "${have:-0}" -ge "${rated:-1}" ] && [ "${have:-0}" -gt 0 ]; then
      say "skip  $USE @ $COV — already complete ($have/$rated grids)"
      continue
    fi
    say "sweep $USE @ $COV  (have $have of $rated rated grids)"
    $PY -u -m src.prfsweep --bulk --use "$USE" --coverage "$COV" --jobs "$JOBS" \
      || say "WARN: $USE @ $COV exited nonzero (resumable; continuing)"
    now=$(sqlite3 data/catalog.db "SELECT COUNT(*) FROM prf_opt_best;")
    say "done  $USE @ $COV — prf_opt_best now $now rows"
  done
done

say "=== full matrix sweep complete: $(sqlite3 data/catalog.db 'SELECT COUNT(*) FROM prf_opt_best;') rows ==="
