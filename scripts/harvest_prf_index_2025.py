#!/usr/bin/env python3
"""harvest_prf_index_2025.py -- add the 2025 rainfall indices to prf_grid_index.

WHY A SEPARATE SCRIPT FROM src/prfbulk.py
-----------------------------------------
prfbulk loads the whole country from ONE published zip:

    .../VI_RI_Data/Rainfall_Index_HistoricData2026CY.zip

That file is the canonical ranking input -- every grid scored against one internally
consistent index release. But its Last-Modified is 2025-08-25 and it stops at 2024, and RMA
has not yet published a 2027CY vintage. So the bulk path cannot supply 2025 today.

The PRF support-tool API can: GetIndexValues returns 2025 complete, 11 of 11 intervals
non-null and final (verified on grid 25032). That costs one request per grid rather than one
download for the country, which is why this is a narrow top-up script and not a change to
prfbulk. WHEN THE 2027CY ZIP APPEARS, PREFER IT: re-running prfbulk against that vintage
replaces these rows from the canonical release and this script becomes unnecessary.

The rows it writes are tagged source='PrfWebApi 2025 top-up' precisely so a later bulk load
can tell them apart from canonical rows and overwrite them.

    .venv/bin/python scripts/harvest_prf_index_2025.py            # all CONUS grids
    .venv/bin/python scripts/harvest_prf_index_2025.py --limit 20 # smoke test
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src.prfdata import API_BASE, parse_index_payload  # noqa: E402

YEAR = 2025
UA = "aip-products/1.0 (crop-insurance catalog research; contact via repo)"
# Polite: a handful of connections and a small per-request pause. This is a public USDA
# service and 13,626 requests is already a lot to ask of it.
WORKERS = 4
DELAY_S = 0.15

_lock = threading.Lock()


def fetch_one(sess: requests.Session, grid_id: int) -> list[tuple[int, str, float]]:
    r = sess.get(f"{API_BASE}/PrfExternalIndexes/GetIndexValues",
                 params={"intervalType": "BiMonthly", "sampleYearMinimum": YEAR,
                         "sampleYearMaximum": YEAR, "gridId": grid_id}, timeout=120)
    r.raise_for_status()
    time.sleep(DELAY_S)
    return parse_index_payload(r.json())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--limit", type=int, help="only the first N grids (smoke test)")
    ap.add_argument("--progress", type=int, default=250)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db, check_same_thread=False)
    grids = [r[0] for r in conn.execute(
        "SELECT DISTINCT grid_id FROM prf_grid_index ORDER BY grid_id")]
    if args.limit:
        grids = grids[:args.limit]
    have = conn.execute("SELECT COUNT(DISTINCT grid_id) FROM prf_grid_index WHERE year = ?",
                        (YEAR,)).fetchone()[0]
    print(f"  {len(grids):,} grids to fetch for {YEAR} ({have:,} already present)")

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    done = {"n": 0, "rows": 0, "fail": 0}
    t0 = time.time()

    def work(gid: int):
        try:
            rows = fetch_one(sess, gid)
        except Exception:
            with _lock:
                done["fail"] += 1
                done["n"] += 1
            return
        payload = [(gid, y, iv, v, "PrfWebApi 2025 top-up", now)
                   for (y, iv, v) in rows if y == YEAR and v is not None]
        with _lock:
            if payload:
                conn.executemany(
                    "INSERT OR REPLACE INTO prf_grid_index "
                    "(grid_id, year, interval_code, index_value, source, fetched_at) "
                    "VALUES (?,?,?,?,?,?)", payload)
                done["rows"] += len(payload)
            done["n"] += 1
            if done["n"] % args.progress == 0:
                conn.commit()
                el = time.time() - t0
                rate = done["n"] / el if el else 0
                eta = (len(grids) - done["n"]) / rate / 60 if rate else 0
                print(f"    {done['n']:,}/{len(grids):,} grids  {done['rows']:,} rows  "
                      f"{done['fail']} failed  {rate:.1f}/s  ETA {eta:.0f} min", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, grids))
    conn.commit()

    n_grids, n_rows = conn.execute(
        "SELECT COUNT(DISTINCT grid_id), COUNT(*) FROM prf_grid_index WHERE year = ?",
        (YEAR,)).fetchone()
    print(f"\n  {YEAR}: {n_grids:,} grids, {n_rows:,} rows  ({done['fail']} fetch failures)")
    full = conn.execute(
        "SELECT COUNT(*) FROM (SELECT grid_id FROM prf_grid_index WHERE year = ? "
        "GROUP BY grid_id HAVING COUNT(*) = 11)", (YEAR,)).fetchone()[0]
    print(f"  grids with all 11 intervals: {full:,}")
    conn.close()
    return 0 if done["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
