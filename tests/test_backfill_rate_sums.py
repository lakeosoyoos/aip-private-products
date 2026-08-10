"""Tests for scripts/backfill_rate_sums.py.

The backfill is a one-shot repair for the ~195k prf_opt_best rows written before
best_win_rate_sum / best_net_rate_sum existed. It must agree EXACTLY with
src/prfsweep.rate_sum (which computes the same number for new rows) — otherwise a
county's commission would change depending on when its grid happened to be swept.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from src import db, prfsweep

REPO = Path(__file__).resolve().parents[1]


def _load():
    """Import the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "backfill_rate_sums", REPO / "scripts" / "backfill_rate_sums.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = _load()


@pytest.fixture()
def catalog(tmp_path):
    conn = db.connect(tmp_path / "cat.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _rate(conn, grid, use, cov, interval, rate, year=2026):
    conn.execute("INSERT OR REPLACE INTO prf_grid_rate VALUES (?,?,?,?,?,?,?,?)",
                 (grid, year, use, interval, cov, rate, "test", "t"))


def _best(conn, grid, use="Grazing", cov=0.9, win_combo='["JAN-FEB"]', win_props="[100]",
          net_combo='["JUL-AUG"]', net_props="[100]"):
    conn.execute(
        "INSERT INTO prf_opt_best (grid_id, intended_use, coverage_level, max_pct, "
        "best_win_rate, best_win_combo, best_win_props, best_net, best_net_combo, "
        "best_net_props) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (grid, use, cov, 60, 0.5, win_combo, win_props, 0.1, net_combo, net_props))


# ------------------------------------------------------------------ arithmetic

def test_rate_sum_matches_the_sweep_exactly():
    """Same inputs, same number — a backfilled row must be indistinguishable
    from one the sweep wrote itself."""
    rates = {"JAN-FEB": 0.18, "JUL-AUG": 0.3488, "AUG-SEP": 0.3368, "NOV-DEC": 0.2201}
    for combo, props in (
            (["JAN-FEB", "JUL-AUG"], [40, 60]),
            (["JAN-FEB", "JUN-JUL"], [50, 50]),           # JUN-JUL unrated -> None
            (["AUG-SEP"], [100]),
            (["JAN-FEB", "AUG-SEP", "NOV-DEC"], [30, 35, 35])):
        assert bf.rate_sum(combo, props, rates) == prfsweep.rate_sum(combo, props, rates)
    assert bf.rate_sum(["JAN-FEB", "JUL-AUG"], [40, 60], rates) == pytest.approx(0.28128)


def test_parse_list_reads_both_stored_formats():
    assert bf.parse_list('["JUN-JUL", "AUG-SEP"]') == ["JUN-JUL", "AUG-SEP"]
    assert bf.parse_list("['JAN-FEB', 'JUL-AUG']") == ["JAN-FEB", "JUL-AUG"]
    assert bf.parse_list("[60, 40]") == [60, 40]
    assert bf.parse_list(None) == [] and bf.parse_list("junk") == []


# --------------------------------------------------------------- rate lookup

def test_load_grid_rates_takes_the_newest_year_per_use(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.10, year=2025)
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.20, year=2026)
    catalog.commit()
    rates = bf.load_grid_rates(catalog, 1)
    assert rates[("Grazing", "0.9")] == {"JAN-FEB": 0.20}   # 2026, not the stale 2025


def test_load_grid_rates_keys_use_and_coverage_separately(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.20)
    _rate(catalog, 1, "Grazing", 0.7, "JAN-FEB", 0.05)
    _rate(catalog, 1, "Haying", 0.9, "JAN-FEB", 0.20)
    catalog.commit()
    rates = bf.load_grid_rates(catalog, 1)
    assert rates[("Grazing", "0.9")]["JAN-FEB"] == 0.20
    assert rates[("Grazing", "0.7")]["JAN-FEB"] == 0.05
    assert ("Haying", "0.9") in rates


# ------------------------------------------------------------------ backfill

def test_backfill_fills_both_columns(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.18)
    _rate(catalog, 1, "Grazing", 0.9, "JUL-AUG", 0.3488)
    _best(catalog, 1, win_combo='["JAN-FEB", "JUL-AUG"]', win_props="[40, 60]",
          net_combo='["JUL-AUG"]', net_props="[100]")
    catalog.commit()

    stats = bf.backfill(catalog, log=lambda *a: None)
    assert stats["visited"] == 1 and stats["filled_both"] == 1
    r = catalog.execute("SELECT * FROM prf_opt_best").fetchone()
    assert r["best_win_rate_sum"] == pytest.approx(0.28128)
    assert r["best_net_rate_sum"] == pytest.approx(0.3488)


def test_backfill_leaves_null_when_the_grid_has_no_rates_for_that_use(catalog):
    """Never guess: a grid rated for Grazing but not Haying keeps Haying NULL."""
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.18)
    _best(catalog, 1, use="Grazing", win_combo='["JAN-FEB"]', win_props="[100]",
          net_combo='["JAN-FEB"]', net_props="[100]")
    _best(catalog, 1, use="Haying", win_combo='["JAN-FEB"]', win_props="[100]",
          net_combo='["JAN-FEB"]', net_props="[100]")
    catalog.commit()

    stats = bf.backfill(catalog, log=lambda *a: None)
    assert stats["no_rates"] == 1 and stats["filled_both"] == 1
    rows = {r["intended_use"]: r for r in catalog.execute("SELECT * FROM prf_opt_best")}
    assert rows["Grazing"]["best_net_rate_sum"] == pytest.approx(0.18)
    assert rows["Haying"]["best_net_rate_sum"] is None


def test_backfill_fills_one_side_when_only_one_allocation_is_fully_rated(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.18)
    _best(catalog, 1, win_combo='["JAN-FEB", "JUL-AUG"]', win_props="[50, 50]",  # JUL-AUG unrated
          net_combo='["JAN-FEB"]', net_props="[100]")
    catalog.commit()

    stats = bf.backfill(catalog, log=lambda *a: None)
    assert stats["partial"] == 1 and stats["filled_net"] == 1 and stats["filled_win"] == 0
    r = catalog.execute("SELECT * FROM prf_opt_best").fetchone()
    assert r["best_win_rate_sum"] is None            # not a partial premium
    assert r["best_net_rate_sum"] == pytest.approx(0.18)


def test_backfill_is_idempotent_and_resumable(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.18)
    _best(catalog, 1, win_combo='["JAN-FEB"]', win_props="[100]",
          net_combo='["JAN-FEB"]', net_props="[100]")
    catalog.commit()

    first = bf.backfill(catalog, log=lambda *a: None)
    assert first["filled_both"] == 1
    # Re-run: already-filled rows are skipped, so an interrupted run just picks up.
    second = bf.backfill(catalog, log=lambda *a: None)
    assert second["visited"] == 0 and second["filled_both"] == 0
    # --force revisits and recomputes to the same value (what a rate refresh needs).
    third = bf.backfill(catalog, force=True, log=lambda *a: None)
    assert third["visited"] == 1
    assert catalog.execute(
        "SELECT best_net_rate_sum FROM prf_opt_best").fetchone()[0] == pytest.approx(0.18)


def test_backfill_dry_run_writes_nothing(catalog):
    _rate(catalog, 1, "Grazing", 0.9, "JAN-FEB", 0.18)
    _best(catalog, 1, win_combo='["JAN-FEB"]', win_props="[100]",
          net_combo='["JAN-FEB"]', net_props="[100]")
    catalog.commit()

    stats = bf.backfill(catalog, dry_run=True, log=lambda *a: None)
    assert stats["filled_both"] == 1
    assert catalog.execute("SELECT best_net_rate_sum FROM prf_opt_best").fetchone()[0] is None


def test_backfill_walks_every_row_across_many_grids(catalog):
    """Keyset paging must not skip or repeat rows as it rewrites its own filter column."""
    for g in range(1, 41):
        _rate(catalog, g, "Grazing", 0.9, "JAN-FEB", 0.01 * g)
        for cov in (0.7, 0.9):
            _rate(catalog, g, "Grazing", cov, "JAN-FEB", 0.01 * g)
            _best(catalog, g, cov=cov, win_combo='["JAN-FEB"]', win_props="[100]",
                  net_combo='["JAN-FEB"]', net_props="[100]")
    catalog.commit()

    stats = bf.backfill(catalog, log=lambda *a: None)
    assert stats["visited"] == 80 and stats["filled_both"] == 80
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_opt_best WHERE best_net_rate_sum IS NULL").fetchone()[0] == 0
    assert catalog.execute(
        "SELECT best_net_rate_sum FROM prf_opt_best WHERE grid_id = 40 AND "
        "coverage_level = 0.9").fetchone()[0] == pytest.approx(0.40)


def test_backfill_refuses_a_db_without_the_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE prf_opt_best (grid_id INTEGER)")
    with pytest.raises(SystemExit):
        bf.backfill(conn, log=lambda *a: None)
    conn.close()


# ----------------------------------------------------------------- migration

def test_apply_migrations_adds_the_columns_once(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE prf_opt_best (grid_id INTEGER PRIMARY KEY, best_net REAL)")
    conn.commit()
    conn.close()

    conn = db.connect(path)
    added = db.apply_migrations(conn)
    assert added == ["prf_opt_best.best_win_rate_sum", "prf_opt_best.best_net_rate_sum"]
    assert db.apply_migrations(conn) == []          # idempotent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prf_opt_best)")}
    assert {"best_win_rate_sum", "best_net_rate_sum"} <= cols
    conn.close()
