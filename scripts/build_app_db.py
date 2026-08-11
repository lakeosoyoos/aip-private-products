#!/usr/bin/env python3
"""Build the slim database the web app ships with.

The working catalog (data/catalog.db) grew past 1.2 GB once src/prfbulk.py loaded RMA's
national rainfall-index file: prf_grid_index alone holds ~11.5M rows (every grid x year x
interval, 1948-2024).  That is the OPTIMIZER'S raw input -- the Streamlit app never reads it.
GitHub hard-rejects files over 100 MB, so committing the working DB is impossible.

This script writes data/catalog_app.db: a copy with the bulk-input tables dropped and
VACUUMed.  The app reads it (streamlit_app.py prefers it when present); the working DB stays
local and gitignored.  Re-run after any refresh/sweep -- publish.command does this for you.

    .venv/bin/python scripts/build_app_db.py [--src data/catalog.db] [--out data/catalog_app.db]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Raw optimizer/fetcher inputs the app never queries. Everything else ships.
DROP_TABLES = [
    "prf_grid_index",   # ~11.5M rows: the VI/RI national index history (optimizer input)
    "prf_grid_rate",    # ~740k rows: per-grid premium rates (optimizer input)
    "prf_index_hash",   # change-detection bookkeeping for the monthly re-score
    # The pre-cap snapshot of prf_opt_best, kept locally so the actuarial-cap change can be
    # measured against what it replaced. 194,725 rows of superseded results: useful to have,
    # never something the app should read or a user should be able to reach.
    "prf_opt_best_pre_cap",
    # DRP's two bulk inputs -- the exact analogue of prf_grid_index/prf_grid_rate above.
    # Together they are ~610 MB of the working DB and 99.5% of DRP's footprint; the app
    # would be unshippable with either. The DRP tab must read the dimension tables that DO
    # ship (drp_offer, drp_state, drp_subsidy, drp_milk_yield, drp_fmmo_factor,
    # drp_actual_price) plus the optimizer's own output -- never these two.
    "drp_daily_price",  # 671k rows x ~40 cols: raw daily futures quotes + sigmas (241 MB)
    "drp_draw",         # 1.25M rows: RMA's fixed 5,000 uniform Monte Carlo draws per
                        # state x quarter (302 MB). Premium is a 5,000-iteration simulation
                        # per P18-1, so these are the simulation's INPUT, never a result.
    # Summary of Business county detail, 1989 forward at
    # county x crop x plan x coverage-type x coverage-level: ~3M rows / ~400 MB, and the same
    # call as prf_grid_index above. The app reads the national rollup (sob_national) plus the
    # state-grain unit-structure table (sob_unit), both of which ship; the county detail stays
    # in the local working DB for anyone doing county-level returns work.
    "sob_sales",
    # Its state-grain sibling, for the same reason: 300k rows of
    # state x crop x plan x coverage-level x UNIT STRUCTURE cost 45 MB with their index —
    # more than the whole remaining headroom. sob_unit_national is its rollup and ships.
    "sob_unit",
    # NASS county yield history: 2.54M rows, 433 MB plus 362 MB of indexes. The INPUT to the
    # basis-risk estimator (src/basisrisk.py), same category as prf_grid_index and drp_draw
    # above -- detrended and reduced offline into basis_risk_county, which is 5.5 MB and DOES
    # ship. Shipping the raw series would add ~795 MB to a 100 MB budget.
    "nass_county_yield",
    "url_cache",        # HTTP cache bookkeeping
    "_xcheck_api",      # scratch table from the bulk-vs-API vintage cross-check
]

# Heavy columns the app never reads: blanked (not dropped, so the schema stays identical
# and a local working copy can still be used interchangeably). prf_opt_best.top_json holds
# the top-10 leaderboards per grid — ~37 MB across 13,462 grids — while the map only needs
# the two winning policies already stored in their own columns.
BLANK_COLUMNS = [
    ("prf_opt_best", "top_json"),      # ~37 MB of top-10 leaderboards; map shows only the 2 winners
    # Same call for DRP: ~5 MB of top-10 risk-shape leaderboards across 2,000 rows, while
    # src/drppage.py reads only the two winning shapes already in their own columns.
    ("drp_opt_best", "top_json"),
    ("serff_filings", "raw"),          # ~6 MB of original portal JSON; the table's own columns ship
    ("products", "raw"),               # original scraped blob; provenance lives in source_url
]

# Tables the app genuinely reads — refuse to ship a DB missing any of them.
REQUIRED = [
    "aips", "products", "product_crops", "product_states", "product_counties",
    # sob_national is the Summary-of-Business table that ships: the national rollup of the
    # (dropped) sob_sales county detail, carrying realized loss ratio and indemnity per $1 of
    # producer premium by year x crop x plan x coverage level. sob_year is its load manifest and
    # marks which crop years have settled — a query that forgets to exclude the open years gets
    # a loss ratio of 0, so never ship one without the other.
    "serff_filings", "sob_national", "sob_unit_national", "sob_year",
    "prf_county", "prf_opt_best", "prf_grid_county",
    "documents", "fetch_log",
    # The DRP tab (src/drppage.py) reads exactly these two: the optimizer's output and
    # the statewide availability rollup. Its two simulation INPUTS are in DROP_TABLES
    # above, so shipping without drp_opt_best would leave the tab with nothing at all
    # rather than a stale map.
    "drp_opt_best", "drp_state",
    # Row-crop opportunity map (src/rowcroppage.py) reads rowcrop_unclaimed; its Summary-of-
    # Business input is dropped above, so this precomputed rollup is all the map has.
    # basis_risk_county ships alongside it even though nothing reads it YET: it is the
    # per-county farm-vs-index shortfall frequency, and it is the term that decides whether an
    # unsold county is genuinely an opportunity or a county where an area-triggered band
    # rationally should not be sold. Shipping it is what makes that join possible in the app
    # rather than only offline. 5.5 MB.
    "rowcrop_unclaimed", "basis_risk_county",
]

# Columns the app cannot work without, checked because they are easy to lose by accident.
# The rate-sums are the ONLY premium information that survives dropping prf_grid_rate above
# — without them the map's "commission per acre" metric has no premium to take a percentage
# of. Two REALs over ~195k rows is ~3 MB, so they ship; never add them to BLANK_COLUMNS.
REQUIRED_COLUMNS = [
    ("prf_opt_best", "best_win_rate_sum"),
    ("prf_opt_best", "best_net_rate_sum"),
    # The DRP equivalents, and for the same reason. DRP has NO rate table at all —
    # premium is a 5,000-iteration Monte Carlo (M13 P18-1) over drp_daily_price and
    # drp_draw, both dropped above — so these two columns are the only premium
    # information that survives into the app. best_net_prem is the producer premium per
    # $1 of liability on the recommended declaration; best_net_liability_cwt turns any
    # per-$1 metric into dollars on a hundredweight. Two REALs over 2,000 rows is
    # nothing; never add them to BLANK_COLUMNS.
    ("drp_opt_best", "best_net_prem"),
    ("drp_opt_best", "best_net_liability_cwt"),
    # miss_rate is the ONLY column that tempers the row-crop opportunity map. Without it every
    # county renders "basis risk unknown" — which is honest, but SILENTLY so: a DB built without
    # running the basis-risk estimator would otherwise pass every guard here and ship a map
    # whose whole point (that an unsold county may be unsold for good reason) has quietly
    # evaporated. Checking the column makes that failure loud at build time instead.
    ("basis_risk_county", "miss_rate"),
]


# Payload columns whose equality decides whether one intended_use is a true alias of another.
# Deliberately excludes intended_use itself, and the bookkeeping columns (source, fetched_at,
# top_json) that differ without meaning anything.
_ALIAS_COLS = ["year_min", "year_max", "n_policies", "best_win_rate", "best_win_combo",
               "best_win_props", "best_win_avg_net", "best_net", "best_net_combo",
               "best_net_props", "best_net_win_rate", "median_net", "pct_positive",
               "best_win_rate_sum", "best_net_rate_sum"]


def shrink_prf_max_pct(conn) -> dict:
    """Collapse prf_max_pct to the grain the APP reads. ~34 MB.

    The harvested table is county x intended-use x irrigation x INTERVAL -- 142,125 rows --
    because that is the grain RMA publishes the cap at, and the sweep wants it that way. But
    every row also carries the full statement_text, and there are only EIGHT distinct
    statements in the country, so the shipped copy was storing the same sentence 142,125
    times: 28 MB of table plus 6 MB of index, more than a third of the whole artifact.

    src/prfpage.py reads exactly one thing from it:

        SELECT state_code || county_code, MIN(max_pct) ... GROUP BY state_code, county_code

    so the shipped copy is that rollup -- one row per county, 3,071 of them -- plus the
    conditional flag and statement id for provenance. The full-grain table stays in the
    working DB, which is where the sweep reads it.

    MIN, matching the reader and src/prfsweep.grid_caps(): where a county's cap varies by
    interval, the conservative value is the one that keeps a recommendation buyable.
    """
    before = conn.execute("SELECT COUNT(*) FROM prf_max_pct").fetchone()[0]
    conn.executescript("""
        CREATE TABLE _prf_max_pct_county AS
            SELECT state_code, county_code, MIN(max_pct) AS max_pct,
                   MAX(is_conditional) AS is_conditional,
                   MIN(statement_id)   AS statement_id,
                   MIN(reinsurance_year) AS reinsurance_year
              FROM prf_max_pct
             GROUP BY state_code, county_code;
        DROP TABLE prf_max_pct;
        ALTER TABLE _prf_max_pct_county RENAME TO prf_max_pct;
        CREATE INDEX ix_prf_max_pct_county ON prf_max_pct(state_code, county_code);
    """)
    after = conn.execute("SELECT COUNT(*) FROM prf_max_pct").fetchone()[0]
    # The reader's own query must still return every county it did before.
    if after < 3000:
        sys.exit(f"REFUSING: prf_max_pct rolled up to {after} counties, expected ~3,071. "
                 f"Check scripts/build_app_db.py:shrink_prf_max_pct.")
    return {"before": before, "after": after}


def dedupe_prf_opt_best(conn) -> dict:
    """Collapse prf_opt_best's redundant intended_use rows behind a view. ~36 MB.

    A PRF premium rate is a function of the grid's rainfall distribution, the interval and the
    coverage level -- NOT of what the forage is used for -- so the per-$1 results are identical
    across intended uses for almost every grid. Measured on the current data: Haying-Irrigated
    matches Grazing on 67,310 of 67,310 (grid, coverage) pairs, and Haying matches on 60,074,
    differing on 31 (five grids, where Haying has fewer rated intervals).

    So Grazing is stored once as canonical, and the other two uses are RECONSTRUCTED by a view
    named prf_opt_best. Every reader -- src/prfpage.py included -- sees the identical table it
    saw before; nothing downstream changes.

    TWO CORRECTNESS TRAPS, both guarded here rather than trusted:

    1. THE 31 EXCEPTIONS ARE REAL. Haying genuinely differs on those pairs (win rates up to 5.3
       points apart, different recommended allocations). They are stored as real rows and
       override the alias.

    2. HAYING IS ABSENT FROM 7,205 PAIRS -- it simply is not offered on those grids. The
       obvious implementation ("if no Haying row, use Grazing") would silently invent Haying
       availability on 1,441 grids and recommend a policy the producer CANNOT BUY. That is a
       correctness regression disguised as a space saving, so presence is stored explicitly
       and the view returns nothing where Haying was never offered.

    EVERY JOIN HERE MATCHES ON max_pct AS WELL. prf_opt_best gained the actuarial cap in its
    key, so a grid straddling a cap boundary has two or three rows per (grid, coverage). Left
    on the old two-column join these queries cross-product across cap variants and compare
    Grazing-at-50% against Haying-Irrigated-at-60%: the guard reported 6,410 differences where
    the true number is ZERO. It refused to dedupe rather than alias bad data, which is the
    behaviour wanted -- but the comparison itself was wrong, not the data.

    Refuses rather than guesses if the alias assumption stops holding on future data.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(prf_opt_best)")]
    if not cols or "intended_use" not in cols:
        return {"skipped": "no prf_opt_best"}
    payload = [c for c in _ALIAS_COLS if c in cols]
    eq = " AND ".join(f"(a.{c} IS b.{c})" for c in payload)

    # GUARD: Haying-Irrigated must be a perfect alias of Grazing. If RMA ever rates them apart
    # this stops being lossless, and we must not find that out silently.
    bad = conn.execute(
        f"SELECT COUNT(*) FROM prf_opt_best a JOIN prf_opt_best b"
        f"  ON a.grid_id=b.grid_id AND a.coverage_level=b.coverage_level AND a.max_pct=b.max_pct"
        f" WHERE a.intended_use='Grazing' AND b.intended_use='Haying-Irrigated'"
        f"   AND NOT ({eq})").fetchone()[0]
    if bad:
        sys.exit(f"REFUSING to dedupe prf_opt_best: Haying-Irrigated differs from Grazing on "
                 f"{bad} pairs, so aliasing it would lose data. Review "
                 f"scripts/build_app_db.py:dedupe_prf_opt_best.")

    before = conn.execute("SELECT COUNT(*) FROM prf_opt_best").fetchone()[0]
    collist = ", ".join(cols)

    conn.executescript(f"""
        CREATE TABLE _prf_canon AS
            SELECT {collist} FROM prf_opt_best WHERE intended_use='Grazing';
        -- Haying rows that genuinely differ from Grazing: stored, not aliased.
        CREATE TABLE _prf_hay_exc AS
            SELECT b.* FROM prf_opt_best b JOIN prf_opt_best a
              ON a.grid_id=b.grid_id AND a.coverage_level=b.coverage_level AND a.max_pct=b.max_pct
                 AND a.intended_use='Grazing'
             WHERE b.intended_use='Haying' AND NOT ({eq});
        -- Where Haying is OFFERED at all. Absence here means "not sold", never "same as Grazing".
        CREATE TABLE _prf_hay_has AS
            SELECT grid_id, coverage_level, max_pct FROM prf_opt_best WHERE intended_use='Haying';
        DROP TABLE prf_opt_best;
        CREATE INDEX _prf_canon_ix   ON _prf_canon(grid_id, coverage_level, max_pct);
        CREATE INDEX _prf_hay_has_ix ON _prf_hay_has(grid_id, coverage_level, max_pct);
        CREATE INDEX _prf_hay_exc_ix ON _prf_hay_exc(grid_id, coverage_level, max_pct);
    """)

    def relabel(use):
        return ", ".join(f"'{use}' AS intended_use" if c == "intended_use" else f"c.{c}"
                         for c in cols)

    conn.executescript(f"""
        CREATE VIEW prf_opt_best AS
            SELECT {collist} FROM _prf_canon
          UNION ALL
            SELECT {relabel('Haying-Irrigated')} FROM _prf_canon c
          UNION ALL
            SELECT {relabel('Haying')} FROM _prf_canon c
             WHERE EXISTS (SELECT 1 FROM _prf_hay_has h
                            WHERE h.grid_id=c.grid_id AND h.coverage_level=c.coverage_level AND h.max_pct=c.max_pct)
               AND NOT EXISTS (SELECT 1 FROM _prf_hay_exc e
                            WHERE e.grid_id=c.grid_id AND e.coverage_level=c.coverage_level AND e.max_pct=c.max_pct)
          UNION ALL
            SELECT {collist} FROM _prf_hay_exc;
    """)
    after = conn.execute("SELECT COUNT(*) FROM prf_opt_best").fetchone()[0]
    if after != before:
        sys.exit(f"REFUSING: dedupe changed the visible row count {before} -> {after}. "
                 f"The view must reconstruct the table exactly.")
    stored = conn.execute("SELECT COUNT(*) FROM _prf_canon").fetchone()[0] + \
        conn.execute("SELECT COUNT(*) FROM _prf_hay_exc").fetchone()[0]
    return {"visible": after, "stored": stored,
            "exceptions": conn.execute("SELECT COUNT(*) FROM _prf_hay_exc").fetchone()[0]}


# A table may legitimately grow, or shrink a little as RMA revises. A COLLAPSE is different,
# and it is invisible: a table with a fifth of its rows renders exactly like a full one.
# This happened. config.ini listed five SERFF states while an ad-hoc harvest had loaded
# twenty-eight, so a routine refresh rebuilt serff_filings with 2,323 rows instead of 11,287
# and product_states with 373 instead of 1,253. Every test passed, the app rendered, and the
# only symptom was a map quietly showing 127 of 182 products as unmapped.
SHRINK_TOLERANCE = 0.20     # a >20% drop is a collapse, not a revision
SHRINK_FLOOR = 50           # ignore tiny tables, where one row is a large percentage


def _row_counts(db: Path) -> dict:
    """{table: rows} for an existing DB, or {} if it cannot be read."""
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        names = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
        out = {}
        for n in names:
            try:
                out[n] = c.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
            except sqlite3.Error:
                pass
        return out
    finally:
        c.close()


# Tables this script DELIBERATELY rolls up to a coarser grain on the way out. Their row count
# is supposed to fall off a cliff exactly once -- on the build that introduces the rollup -- so
# the collapse guard must not read that as data loss. Each has its own assertion inside its
# shrink function, which is a tighter check than a percentage: shrink_prf_max_pct refuses if
# the county count is not ~3,071, whereas the generic guard only knows the number went down.
INTENTIONALLY_ROLLED_UP = {
    "prf_max_pct",      # county x use x irrigation x interval -> one row per county
}


def check_no_collapse(prior: dict, now: dict, tolerance: float = SHRINK_TOLERANCE) -> list[str]:
    """Tables that lost more than `tolerance` of their rows since the last build."""
    bad = []
    for name, before in sorted(prior.items()):
        after = now.get(name)
        if name in INTENTIONALLY_ROLLED_UP:
            continue
        if after is None or before < SHRINK_FLOOR or before == 0:
            continue
        if after < before * (1.0 - tolerance):
            bad.append(f"{name}: {before:,} -> {after:,} ({(before - after) / before:.0%} lost)")
    return bad


def build(src: Path, out: Path, allow_shrink: bool = False) -> dict:
    if not src.exists():
        sys.exit(f"source DB not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Read the OUTGOING build's row counts before destroying it. The previous shipped DB is
    # the only baseline that always exists and always matches this script's own definition of
    # what ships, so it is a better reference than any checked-in fixture.
    prior = _row_counts(out) if out.exists() else {}
    if out.exists():
        out.unlink()
    # SQLite's online-backup API, not a file copy: the working DB runs in WAL mode, so its
    # committed state is split across catalog.db and catalog.db-wal and a plain copy of the
    # main file alone yields "database disk image is malformed" whenever a writer (a running
    # refresh, sweep or app) has uncheckpointed pages. backup() takes a transactionally
    # consistent snapshot and coexists with concurrent writers.
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    conn = sqlite3.connect(out)
    try:
        src_conn.backup(conn)
    finally:
        src_conn.close()

    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    dropped = []
    for t in DROP_TABLES:
        if t in have:
            conn.execute(f"DROP TABLE {t}")
            dropped.append(t)
    blanked = []
    for table, col in BLANK_COLUMNS:
        if table in have:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col in cols:
                conn.execute(f"UPDATE {table} SET {col} = NULL WHERE {col} IS NOT NULL")
                blanked.append(f"{table}.{col}")
    conn.commit()
    # Must run BEFORE the VACUUM below, so the freed pages are actually reclaimed.
    deduped = dedupe_prf_opt_best(conn) if "prf_opt_best" in have else {}
    if "prf_max_pct" in have:
        r = shrink_prf_max_pct(conn)
        print(f"  prf_max_pct: {r['before']:,} interval rows -> {r['after']:,} counties")
    conn.commit()
    # Ship in DELETE journal mode, not WAL. backup() inherits the working DB's WAL setting,
    # and a WAL-mode artifact is wrong for something that gets COMMITTED: its committed state
    # can live partly in catalog_app.db-wal, so `git add` of the .db alone can ship a database
    # missing its most recent pages -- the same split that produced "database disk image is
    # malformed" when this script used shutil.copy2. DELETE mode keeps everything in the one
    # file, leaves no -wal/-shm sidecars to gitignore, and needs no writable directory to be
    # opened read-only on the deploy host. The working DB stays WAL (sweeps need concurrency).
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.commit()

    # A VIEW satisfies REQUIRED just as a table does: prf_opt_best is now a view that
    # reconstructs the deduped intended_use rows, and every reader queries it identically.
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = [t for t in REQUIRED if t not in have]
    missing_cols = []
    filled = {}
    for table, col in REQUIRED_COLUMNS:
        if table not in have:
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            missing_cols.append(f"{table}.{col}")
        else:
            filled[f"{table}.{col}"] = conn.execute(
                f"SELECT COUNT({col}) FROM {table}").fetchone()[0]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in REQUIRED if t in have}
    conn.close()

    if missing:
        sys.exit(f"REFUSING: app DB is missing required tables: {missing}")
    if missing_cols:
        sys.exit(f"REFUSING: app DB is missing required columns: {missing_cols} — run "
                 "scripts/backfill_rate_sums.py against the working DB first.")

    collapsed = check_no_collapse(prior, _row_counts(out))
    if collapsed and not allow_shrink:
        sys.exit("REFUSING: tables collapsed since the last build —\n  "
                 + "\n  ".join(collapsed)
                 + "\nA smaller table ships and renders exactly like a full one, so this is "
                   "checked rather than eyeballed. Re-run the loader that fills them, or pass "
                   "--allow-shrink if the drop is intended.")

    mb = out.stat().st_size / 1e6
    if mb > 90:
        print(f"WARNING: app DB is {mb:.0f} MB — GitHub's hard limit is 100 MB per file.")
    return {"dropped": dropped, "blanked": blanked, "counts": counts, "mb": mb,
            "filled": filled, "deduped": deduped, "src_mb": src.stat().st_size / 1e6}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(REPO / "data" / "catalog.db"))
    ap.add_argument("--out", default=str(REPO / "data" / "catalog_app.db"))
    ap.add_argument("--allow-shrink", action="store_true",
                    help="permit a table to lose >20%% of its rows since the last build")
    args = ap.parse_args()

    res = build(Path(args.src), Path(args.out), allow_shrink=args.allow_shrink)
    print(f"working DB : {res['src_mb']:,.0f} MB")
    print(f"app DB     : {res['mb']:,.1f} MB  -> {args.out}")
    print(f"dropped    : {', '.join(res['dropped']) or '(none)'}")
    print(f"blanked    : {', '.join(res['blanked']) or '(none)'}")
    print("shipped rows:")
    for t, n in res["counts"].items():
        print(f"  {t:20s} {n:>10,}")
    if res["filled"]:
        print("required columns (non-NULL values):")
        for c, n in res["filled"].items():
            print(f"  {c:32s} {n:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
