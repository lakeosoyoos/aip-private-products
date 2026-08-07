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
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Raw optimizer/fetcher inputs the app never queries. Everything else ships.
DROP_TABLES = [
    "prf_grid_index",   # ~11.5M rows: the VI/RI national index history (optimizer input)
    "prf_grid_rate",    # ~740k rows: per-grid premium rates (optimizer input)
    "prf_index_hash",   # change-detection bookkeeping for the monthly re-score
    "url_cache",        # HTTP cache bookkeeping
    "_xcheck_api",      # scratch table from the bulk-vs-API vintage cross-check
]

# Heavy columns the app never reads: blanked (not dropped, so the schema stays identical
# and a local working copy can still be used interchangeably). prf_opt_best.top_json holds
# the top-10 leaderboards per grid — ~37 MB across 13,462 grids — while the map only needs
# the two winning policies already stored in their own columns.
BLANK_COLUMNS = [
    ("prf_opt_best", "top_json"),      # ~37 MB of top-10 leaderboards; map shows only the 2 winners
    ("serff_filings", "raw"),          # ~6 MB of original portal JSON; the table's own columns ship
    ("products", "raw"),               # original scraped blob; provenance lives in source_url
]

# Tables the app genuinely reads — refuse to ship a DB missing any of them.
REQUIRED = [
    "aips", "products", "product_crops", "product_states", "product_counties",
    "serff_filings", "sob_sales", "prf_county", "prf_opt_best", "prf_grid_county",
    "documents", "fetch_log",
]


def build(src: Path, out: Path) -> dict:
    if not src.exists():
        sys.exit(f"source DB not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    shutil.copy2(src, out)

    conn = sqlite3.connect(out)
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
    conn.execute("VACUUM")
    conn.commit()

    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [t for t in REQUIRED if t not in have]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in REQUIRED if t in have}
    conn.close()

    if missing:
        sys.exit(f"REFUSING: app DB is missing required tables: {missing}")

    mb = out.stat().st_size / 1e6
    if mb > 90:
        print(f"WARNING: app DB is {mb:.0f} MB — GitHub's hard limit is 100 MB per file.")
    return {"dropped": dropped, "blanked": blanked, "counts": counts, "mb": mb,
            "src_mb": src.stat().st_size / 1e6}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(REPO / "data" / "catalog.db"))
    ap.add_argument("--out", default=str(REPO / "data" / "catalog_app.db"))
    args = ap.parse_args()

    res = build(Path(args.src), Path(args.out))
    print(f"working DB : {res['src_mb']:,.0f} MB")
    print(f"app DB     : {res['mb']:,.1f} MB  -> {args.out}")
    print(f"dropped    : {', '.join(res['dropped']) or '(none)'}")
    print(f"blanked    : {', '.join(res['blanked']) or '(none)'}")
    print("shipped rows:")
    for t, n in res["counts"].items():
        print(f"  {t:20s} {n:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
