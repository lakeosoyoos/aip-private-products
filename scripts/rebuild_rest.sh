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
# NB: drpopt takes NO --jobs. Its module docstring advertises "--all [--jobs 4]" and
# that is wrong — passing it aborts the stage on an argparse error, which is exactly
# what happened on the first overnight run and left drp_opt_best empty.
step "DRP optimizer"            $PY -m src.drpopt --all
say "drp_opt_best: $(rows drp_opt_best) rows"

# --- NASS county yields -> the farm-vs-county basis-risk estimator.
#     --force is REQUIRED, not tidiness: the loader gained cotton, per-crop yield units and
#     Pima-dropping since the last load, so a cached table would be silently stale AND wrong.
step "NASS county yields"       $PY -m src.refresh --source nass_yield --force --no-enrich
say "nass_county_yield: $(rows nass_county_yield) rows"

# COTTON UNIT GUARD. NASS carries cotton at both LB/ACRE and LB/NET PLANTED ACRE, the second
# 10-50x smaller. Detrending makes every risk metric EXACTLY scale-invariant, so a wrong-scale
# series yields bit-identical CV, skew and miss rate -- no risk metric can detect it. mean_yield
# is the only non-scale-invariant number, so it is the only possible check.
say "cotton unit guard"
$PY - <<'PYEOF' || say "WARN: cotton unit guard could not run"
import sqlite3
c = sqlite3.connect("data/catalog.db")
row = c.execute(
    "SELECT COUNT(*), AVG(value) FROM nass_county_yield "
    "WHERE crop='Cotton' AND unit='LB / ACRE'").fetchone()
n, mean = row[0], row[1] or 0
# Upland cotton runs ~700-1,100 lb/acre. A NET-PLANTED-ACRE series lands an order of
# magnitude below that.
verdict = "OK" if n == 0 or 300 <= mean <= 2000 else "*** UNIT ERROR — mean is implausible ***"
print(f"  Cotton rows {n:,}, mean yield {mean:,.1f} lb/acre  {verdict}")
PYEOF

step "basis risk (4 crops x 4 bands x 5 coverage levels)" \
                                $PY scripts/analysis/build_basis_risk.py
say "basis_risk_county: $(rows basis_risk_county) rows"

# --- Row-crop opportunity: needs sob_sales above; basis risk is joined at page-build time.
step "row-crop opportunity"     $PY -m src.rowcropopt
say "rowcrop_unclaimed: $(rows rowcrop_unclaimed) rows"

# --- County yield series for the "My Farm" calculator. WITHOUT THIS THE TAB IS INERT: it needs
#     county history year-by-year, and nass_county_yield (795 MB) is dropped from the shipped
#     DB. This ~2 MB rollup is what actually travels. It is a plain function, not a CLI, which
#     is exactly why it was missing from this script on the first pass.
say "county yield series (My Farm calculator)"
$PY - <<'PYEOF' || FAILED="$FAILED\n  - county yield series"
import sqlite3, src.rowcroppage as R
conn = sqlite3.connect("data/catalog.db")
n = R.build_county_yield_series(conn)
conn.commit()
print(f"  county_yield_series: {n:,} rows")
PYEOF
say "county_yield_series: $(rows county_yield_series) rows"

# --- Reship. This REFUSES if any required table or column is missing, so it doubles as the
#     end-to-end check that every stage above actually produced something.
step "rebuild shipped DB"       $PY scripts/build_app_db.py

say "SUMMARY"
printf '  working DB : %s\n' "$(du -h data/catalog.db 2>/dev/null | cut -f1)"
printf '  shipped DB : %s  (guard 95 MB, GitHub hard limit 100 MB)\n' \
       "$(du -h data/catalog_app.db 2>/dev/null | cut -f1)"

# --- Readiness checks for the things that must be done BY HAND afterwards, because they are
#     source edits rather than data steps. Printing them here is the handoff.
printf '\n  POST-REBUILD, BY HAND:\n'
n75=$(sqlite3 data/catalog.db \
      "SELECT COUNT(*) FROM basis_risk_county WHERE coverage_level=0.75;" 2>/dev/null || echo 0)
if [ "${n75:-0}" -gt 0 ]; then
  printf '  1. READY — flip src/rowcropopt.BASIS_COVERAGE_LEVEL from 0.85 to 0.75.\n'
  printf '     %s rows now exist at 0.75. Only 2.3%% of SCO acres elect 0.85; 50.7%% elect\n' "$n75"
  printf '     0.75, so the shipped map currently describes ~1 buyer in 44. Do NOT flip\n'
  printf '     before this count is non-zero or every county renders "unknown".\n'
else
  printf '  1. NOT READY — no basis_risk_county rows at coverage_level 0.75. Leave\n'
  printf '     src/rowcropopt.BASIS_COVERAGE_LEVEL at 0.85.\n'
fi
nlgm=$(sqlite3 data/catalog.db \
       "SELECT COUNT(*) FROM sob_unit WHERE plan_code='82';" 2>/dev/null || echo 0)
printf '  2. LGM rows now in sob_unit: %s (0 means the livestock gate did not take)\n' "${nlgm:-0}"
printf '  3. Re-run the suite, then review the app before merging to main.\n'

if [ -n "$FAILED" ]; then printf '\n  FAILED STAGES:%b\n' "$FAILED"; exit 1; fi
printf '\n  all stages OK\n'
