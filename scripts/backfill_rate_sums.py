#!/usr/bin/env python3
"""Backfill prf_opt_best.best_win_rate_sum / best_net_rate_sum from prf_grid_rate.

WHY: the map's "commission per acre" metric needs the PREMIUM of the recommended policy,
and premium is protection x rate:

    premium/acre = CBV x coverage_level x productivity x SUM(allocation_i x rate_i)

The rates live in prf_grid_rate (2.1M rows), which scripts/build_app_db.py DROPS from the
shipped app DB — too big for the size budget, and the app only ever needs the one weighted
number per stored allocation. So the weighted sum is precomputed ONCE here and stored on the
prf_opt_best row; the app then does the cheap multiplication client-side.

This is a PURE LOOKUP over data that already exists — it does NOT re-run the optimizer (the
full 15-combo sweep is ~15 hours and would change nothing about which allocation won). For
each prf_opt_best row it parses the stored best_win_combo/props and best_net_combo/props and
computes, per allocation:

    rate_sum = SUM(props_i / 100 x premium_rate_i)

reading rates at that row's (grid_id, intended_use, coverage_level) for the NEWEST rate year
stored for that grid+use — which is exactly the vintage src/prfdata.rates_for() (and hence
the sweep itself) used.

HONESTY RULES
  * A grid with no rates for the row's use/coverage leaves BOTH columns NULL.
  * An allocation naming an interval that has no rate leaves THAT column NULL — a partial
    sum would understate the premium, so nothing is guessed.
  * Props that do not sum to 100 are still weighted by props_i/100 (the stored allocation is
    reported as-is); rows whose props are missing or the wrong length are skipped as
    unparseable rather than assumed uniform.

IDEMPOTENT + RESUMABLE: by default only rows where BOTH columns are NULL are visited, and
each grid's rate table is read once and reused across that grid's rows. Interrupt it and
re-run; already-filled rows are skipped. --force revisits every row (use after a rate
refresh).

    .venv/bin/python scripts/backfill_rate_sums.py [--db data/catalog.db]
                                                   [--force] [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BATCH = 5000  # rows per commit — bounded memory, and an interrupt loses at most this many


def parse_list(text):
    """Parse a combo/props column into a plain list ([] when unparseable).

    Mirrors src/prfpage._parse_list: the sweep writes JSON, but the optimizer's older
    export path wrote Python reprs with single quotes, so fall back to literal_eval.
    """
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        return list(text)
    s = str(text).strip()
    if not s:
        return []
    try:
        val = json.loads(s)
    except ValueError:
        try:
            val = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


def rate_sum(combo, props, rates: dict) -> float | None:
    """SUM(props_i/100 x rates[combo_i]), or None if anything is missing.

    None — not a partial sum — whenever an interval in the allocation carries no rate:
    a premium computed over some of the intervals is wrong, not approximate.
    """
    if not combo or not props or len(combo) != len(props):
        return None
    total = 0.0
    for interval, pct in zip(combo, props):
        rate = rates.get(interval)
        if rate is None:
            return None
        try:
            total += (float(pct) / 100.0) * float(rate)
        except (TypeError, ValueError):
            return None
    return total


def load_grid_rates(conn: sqlite3.Connection, grid_id: int) -> dict:
    """{(use, cov_key): {interval: rate}} for one grid, newest rate year per use.

    One query per grid rather than per row: a grid has 15 prf_opt_best rows (3 uses x 5
    coverages) that all read the same rate block. The year is picked per (grid, use) to
    match src/prfdata.rates_for()'s MAX(year) default — the vintage the sweep scored on.
    """
    latest: dict[str, int] = {}
    for use, year in conn.execute(
            "SELECT intended_use, MAX(year) FROM prf_grid_rate WHERE grid_id = ? "
            "GROUP BY intended_use", (grid_id,)):
        latest[use] = year

    out: dict = {}
    for r in conn.execute(
            "SELECT intended_use, year, coverage_level, interval_code, premium_rate "
            "FROM prf_grid_rate WHERE grid_id = ?", (grid_id,)):
        use = r["intended_use"]
        if r["year"] != latest.get(use):
            continue  # older vintage still in the table — ignore
        key = (use, "%g" % float(r["coverage_level"]))
        out.setdefault(key, {})[r["interval_code"]] = r["premium_rate"]
    return out


def backfill(conn: sqlite3.Connection, force: bool = False, limit: int | None = None,
             dry_run: bool = False, log=print) -> dict:
    """Fill the two rate-sum columns. Returns a stats dict; safe to re-run."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prf_opt_best)")}
    missing = [c for c in ("best_win_rate_sum", "best_net_rate_sum") if c not in cols]
    if missing:
        raise SystemExit(
            f"prf_opt_best is missing {missing} — run "
            "`.venv/bin/python -m src.db --init` first (db.apply_migrations adds them).")

    where = "" if force else (" WHERE best_win_rate_sum IS NULL "
                              "AND best_net_rate_sum IS NULL")
    total = conn.execute(f"SELECT COUNT(*) FROM prf_opt_best{where}").fetchone()[0]
    if limit:
        total = min(total, limit)
    log(f"rows to visit: {total:,}{'' if force else ' (NULL rate-sums only)'}")

    stats = {"visited": 0, "filled_win": 0, "filled_net": 0, "filled_both": 0,
             "no_rates": 0, "unparseable": 0, "partial": 0, "grids": 0}
    cur_grid, rates_by_key = None, {}
    t0 = time.monotonic()

    # KEYSET PAGINATION over the primary key rather than one long-lived cursor: the UPDATEs
    # below rewrite the very columns the (non-force) filter tests, and stepping a SELECT
    # while rewriting its own table is undefined in SQLite. Paging by (grid_id,
    # intended_use, coverage_level) makes each batch a closed read, so the walk is
    # deterministic and an interrupt simply resumes at the next unfilled row.
    page_sql = (
        "SELECT grid_id, intended_use, coverage_level, best_win_combo, best_win_props, "
        "best_net_combo, best_net_props FROM prf_opt_best "
        + ("WHERE" if not where else where + " AND")
        + " (grid_id, intended_use, coverage_level) > (?, ?, ?) "
        "ORDER BY grid_id, intended_use, coverage_level LIMIT ?")
    last = (-1, "", -1.0)

    while True:
        take = BATCH if not limit else min(BATCH, limit - stats["visited"])
        if take <= 0:
            break
        batch = conn.execute(page_sql, (*last, take)).fetchall()
        if not batch:
            break
        updates: list[tuple] = []
        for r in batch:
            stats["visited"] += 1
            last = (r["grid_id"], r["intended_use"], r["coverage_level"])
            gid = r["grid_id"]
            if gid != cur_grid:
                cur_grid = gid
                rates_by_key = load_grid_rates(conn, gid)
                stats["grids"] += 1
            key = (r["intended_use"], "%g" % float(r["coverage_level"]))
            rates = rates_by_key.get(key)
            if not rates:
                stats["no_rates"] += 1   # leave both NULL — never guess a rate
                continue

            wc, wp = parse_list(r["best_win_combo"]), parse_list(r["best_win_props"])
            nc, np_ = parse_list(r["best_net_combo"]), parse_list(r["best_net_props"])
            win_sum = rate_sum(wc, wp, rates)
            net_sum = rate_sum(nc, np_, rates)
            if win_sum is None and net_sum is None:
                stats["unparseable"] += 1
                continue
            if win_sum is None or net_sum is None:
                stats["partial"] += 1     # one allocation named an unrated interval
            stats["filled_win"] += win_sum is not None
            stats["filled_net"] += net_sum is not None
            stats["filled_both"] += (win_sum is not None and net_sum is not None)
            updates.append((win_sum, net_sum, gid, r["intended_use"],
                            r["coverage_level"]))

        if updates and not dry_run:
            conn.executemany(
                "UPDATE prf_opt_best SET best_win_rate_sum = ?, best_net_rate_sum = ? "
                "WHERE grid_id = ? AND intended_use = ? AND coverage_level = ?", updates)
            conn.commit()
        log(f"  {stats['visited']:>8,}/{total:,} rows ({time.monotonic() - t0:.0f}s)")

    stats["elapsed_s"] = time.monotonic() - t0
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "data" / "catalog.db"))
    ap.add_argument("--force", action="store_true",
                    help="revisit rows that already have rate-sums (after a rate refresh)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="compute but do not write")
    args = ap.parse_args()

    from src import db as dbmod

    conn = dbmod.connect(args.db)
    added = dbmod.apply_migrations(conn)
    if added:
        print(f"migrated: added {', '.join(added)}")
    stats = backfill(conn, force=args.force, limit=args.limit, dry_run=args.dry_run)
    conn.close()

    print(f"\nvisited      {stats['visited']:>10,}  ({stats['grids']:,} grids, "
          f"{stats['elapsed_s']:.0f}s)")
    print(f"filled both  {stats['filled_both']:>10,}")
    print(f"filled win   {stats['filled_win']:>10,}")
    print(f"filled net   {stats['filled_net']:>10,}")
    print(f"one-sided    {stats['partial']:>10,}  (an allocation named an unrated interval)")
    print(f"no rates     {stats['no_rates']:>10,}  (left NULL — grid has no rates "
          f"for that use/coverage)")
    print(f"unparseable  {stats['unparseable']:>10,}  (no usable stored allocation)")
    if args.dry_run:
        print("\n(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
