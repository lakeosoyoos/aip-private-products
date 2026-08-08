#!/usr/bin/env bash
#
# Everything the working-DB rebuild needs AFTER the PRF sweep. Waits for
# scripts/rebuild_sweep_all.sh to finish, then runs the remaining loaders and optimizers
# and rebuilds the shipped DB. Roughly 1.5-2 h once the sweep is done.
#
#     nohup ./scripts/rebuild_rest.sh > output/rebuild_rest.log 2>&1 &
#
# WHY IT WAITS RATHER THAN RUNNING ALONGSIDE: the sweep saturates six cores and writes
# continuously to catalog.db. Running a multi-gigabyte download and a second writer against
# the same SQLite file would slow both and invite lock contention, so this blocks until the
# sweep's process is gone.
#
# ORDER MATTERS:
#   rma_sob   must precede rowcropopt   (it reads sob_sales county detail)
#   nass_yield must precede basis risk  (it reads nass_county_yield)
#   everything must precede build_app_db (it ships their results and REFUSES on missing ones)
#
# Each stage is independent and non-fatal: a failure is logged and the run continues, so one
# dead download does not cost the whole night. Check the summary at the end for what failed.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
FAILED=""

say()  { printf '\n%s ===== %s =====\n' "$(date '+%H:%M:%S')" "$1"; }
step() { say "$1"; shift; "$@" || { FAILED="$FAILED\n  - $1"; say "WARN: failed, continuing"; }; }
rows() { sqlite3 data/catalog.db "SELECT COUNT(*) FROM $1;" 2>/dev/null || echo "?"; }

say "waiting for the PRF sweep to finish"
while pgrep -f "rebuild_sweep_all|src\.prfsweep" >/dev/null 2>&1; do sleep 60; done
say "sweep finished — prf_opt_best has $(rows prf_opt_best) rows"

# --- Summary of Business: county detail, 1989 forward. Feeds the row-crop opportunity map.
step "Summary of Business"      $PY -m src.refresh --source rma_sob --force --no-enrich
say "sob_sales: $(rows sob_sales) rows"

# --- DRP: dimensions + daily prices, then the 5,000-draw Monte Carlo input, then the sweep.
step "DRP data (2019-2027)"     $PY -m src.drpdata --all --years 2019-2027
step "DRP draws (RY2026)"       $PY -m src.drpdata --draws --year 2026
step "DRP optimizer"            $PY -m src.drpopt --all --jobs 4
say "drp_opt_best: $(rows drp_opt_best) rows"

# --- NASS county yields -> the farm-vs-county basis-risk estimator.
step "NASS county yields"       $PY -m src.refresh --source nass_yield --force --no-enrich
say "nass_county_yield: $(rows nass_county_yield) rows"
step "basis risk"               $PY scripts/analysis/build_basis_risk.py
say "basis_risk_county: $(rows basis_risk_county) rows"

# --- Row-crop opportunity: needs sob_sales above; basis risk is joined at page-build time.
step "row-crop opportunity"     $PY -m src.rowcropopt
say "rowcrop_unclaimed: $(rows rowcrop_unclaimed) rows"

# --- Reship. This REFUSES if any required table or column is missing, so it doubles as the
#     end-to-end check that every stage above actually produced something.
step "rebuild shipped DB"       $PY scripts/build_app_db.py

say "SUMMARY"
printf '  working DB : %s\n' "$(du -h data/catalog.db 2>/dev/null | cut -f1)"
printf '  shipped DB : %s\n' "$(du -h data/catalog_app.db 2>/dev/null | cut -f1)"
if [ -n "$FAILED" ]; then printf '  FAILED STAGES:%b\n' "$FAILED"; exit 1; fi
printf '  all stages OK\n'
