"""Tests for src/prfsweep.py — state-wide PRF optimizer sweep. No live calls."""

import json
import math
import sqlite3

import pytest

from src import db, prfopt, prfsweep
from src.prfsweep import (
    SweepSkip,
    compute_grid_best,
    county_names,
    grid_county_rows,
    list_state_grids,
    state_codes,
    upsert_best,
    upsert_grid_counties,
)

# ---------------------------------------------------------------------------
# Tiny ADM fixture (A00810 rc03 layout: field 10 = Sub County Code = grid id,
# field 7 = plan, field 8/9 = state/county, field 21 = intended use code)
# ---------------------------------------------------------------------------

A00810_HEADER = "|".join(["h"] * 82)


def _price_row(grid, state, county, use_code="007", plan="13", rc="03"):
    f = [""] * 82
    f[0], f[1], f[3] = "A00810", rc, "2026"
    f[6], f[7], f[8], f[9], f[20] = plan, state, county, str(grid), use_code
    return "|".join(f)


@pytest.fixture()
def adm_dir(tmp_path):
    rows = [
        A00810_HEADER,
        _price_row(101, "16", "013"),           # ID Blaine
        _price_row(101, "16", "013"),           # duplicate interval row
        _price_row(101, "30", "001"),           # same grid also touches MT
        _price_row(102, "16", "025"),           # ID Camas
        _price_row(103, "16", "025", use_code="030"),   # Haying only
        _price_row(201, "30", "001"),           # MT-only grid
        _price_row(999, "16", "013", plan="12"),        # not PRF
        _price_row(998, "16", "013", rc="01"),          # wrong record category
    ]
    (tmp_path / "2026_A00810_Price_YTD.txt").write_text("\n".join(rows) + "\n")
    (tmp_path / "2026_A00520_State_YTD.txt").write_text(
        "hdr\n"
        "A00520|01|2026|16|Idaho|ID|10|Spokane|||\n"
        "A00520|01|2026|30|Montana|MT|10|Billings|||\n")
    (tmp_path / "2026_A00440_County_YTD.txt").write_text(
        "hdr\n"
        "A00440|01|2026|16|013|Blaine|||\n"
        "A00440|01|2026|16|025|Camas|||\n"
        "A00440|01|2026|30|001|Big Horn|||\n")
    return tmp_path


def test_state_codes_and_county_names(adm_dir):
    assert state_codes(adm_dir)["ID"] == "16"
    assert county_names(adm_dir)[("16", "013")] == "Blaine"


def test_list_state_grids_filters_state_use_plan_rc(adm_dir):
    assert list_state_grids("ID", "Grazing", adm_dir) == [101, 102]
    assert list_state_grids("MT", "Grazing", adm_dir) == [101, 201]
    assert list_state_grids("ID", "Haying", adm_dir) == [103]
    with pytest.raises(ValueError):
        list_state_grids("XX", "Grazing", adm_dir)


def test_grid_county_rows_cross_state(adm_dir):
    rows = grid_county_rows([101, 102], "Grazing", adm_dir)
    assert (101, "ID", "16013", "Blaine") in rows
    assert (101, "MT", "30001", "Big Horn") in rows   # border grid: both states
    assert (102, "ID", "16025", "Camas") in rows
    assert len(rows) == 3                              # dupes collapsed


# ---------------------------------------------------------------------------
# Catalog DB fixture (real schema from src/db.py, seeded synthetically)
# ---------------------------------------------------------------------------

GRID = 101
YEARS = list(range(2006, 2025))


def _seed_grid(conn, grid=GRID, years=YEARS, rate_intervals=prfopt.INTERVALS,
               use="Grazing", coverage=0.90, rate=0.10):
    # deterministic synthetic indices (decimal percent-of-normal, ~prfdata)
    rows = []
    for y in years:
        for k, iv in enumerate(prfopt.INTERVALS):
            v = 0.70 + 0.05 * ((y + k) % 12)   # 0.70 .. 1.25
            rows.append((grid, y, iv, v, "test", "t"))
    conn.executemany(
        "INSERT OR REPLACE INTO prf_grid_index VALUES (?,?,?,?,?,?)", rows)
    conn.executemany(
        "INSERT OR REPLACE INTO prf_grid_rate VALUES (?,?,?,?,?,?,?,?)",
        [(grid, 2026, use, iv, coverage, rate + 0.01 * i, "test", "t")
         for i, iv in enumerate(prfopt.INTERVALS) if iv in rate_intervals])
    conn.execute("INSERT OR REPLACE INTO prf_subsidy VALUES (0.90, 0.51, 't')")
    conn.commit()


@pytest.fixture()
def catalog(tmp_path):
    conn = db.connect(tmp_path / "cat.db")
    db.init_db(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# compute_grid_best
# ---------------------------------------------------------------------------

def test_compute_grid_best_metrics(catalog):
    _seed_grid(catalog)
    row = compute_grid_best(catalog, GRID)
    assert row["n_policies"] == 59_536          # all intervals offered
    assert row["year_min"] == 2006 and row["year_max"] == 2024
    assert 0.0 <= row["best_win_rate"] <= 1.0
    assert 0.0 <= row["best_net_win_rate"] <= row["best_win_rate"]
    assert row["best_net"] >= row["best_win_avg_net"] >= row["median_net"] - 1e12
    assert math.isfinite(row["best_net"]) and math.isfinite(row["median_net"])
    assert 0.0 <= row["pct_positive"] <= 1.0
    top = json.loads(row["top_json"])
    assert set(top) == {"by_win_rate", "by_avg_net"}
    for key in top:
        assert len(top[key]) == 10
        for e in top[key]:
            assert set(e) == {"combo", "props", "avg_net", "win_rate"}
            assert sum(e["props"]) == 100
    # top-1 entries agree with the flat best_* columns
    assert top["by_win_rate"][0]["win_rate"] == row["best_win_rate"]
    assert top["by_avg_net"][0]["avg_net"] == row["best_net"]
    # combos JSON-parse to known intervals
    assert all(iv in prfopt.INTERVALS
               for iv in json.loads(row["best_win_combo"]))


def test_normalized_metrics_scale_linearly(catalog):
    """avg_net stored per $1 protection: x P equals a direct P-dollar run."""
    _seed_grid(catalog)
    row = compute_grid_best(catalog, GRID)
    P = 18.36
    combo = tuple(json.loads(row["best_net_combo"]))
    props = tuple(json.loads(row["best_net_props"]))
    idx = {iv: {y: (0.70 + 0.05 * ((y + prfopt.INTERVAL_INDEX[iv]) % 12)) * 100
                for y in YEARS} for iv in prfopt.INTERVALS}
    rates = {iv: 0.10 + 0.01 * i for i, iv in enumerate(prfopt.INTERVALS)}
    nets, _ = prfopt.interval_year_nets(
        idx, rates, 0.51, coverage_level=0.90, years=YEARS,
        protection=P, round_cents=False, sentinel_net=None)
    df = prfopt.score_policies([(combo, props)], nets)
    assert math.isclose(row["best_net"] * P,
                        df.loc[0, "average_net_return"], abs_tol=1e-9)
    assert row["best_net_win_rate"] == df.loc[0, "win rate"]  # scale-invariant


def test_skip_incomplete_index_years(catalog):
    _seed_grid(catalog, years=[y for y in YEARS if y != 2013])
    with pytest.raises(SweepSkip, match="incomplete index years.*2013"):
        compute_grid_best(catalog, GRID)


def test_skip_no_rates(catalog):
    _seed_grid(catalog)
    with pytest.raises(SweepSkip, match="no Haying rates"):
        compute_grid_best(catalog, GRID, use="Haying")


def test_skip_unrated_intervals_drop_policies(catalog):
    # only 3 rated, mutually non-adjacent intervals -> policies restricted
    _seed_grid(catalog, rate_intervals=("JAN-FEB", "MAY-JUN", "SEP-OCT"))
    row = compute_grid_best(catalog, GRID)
    assert 0 < row["n_policies"] < 59_536
    for e in json.loads(row["top_json"])["by_avg_net"]:
        assert set(e["combo"]) <= {"JAN-FEB", "MAY-JUN", "SEP-OCT"}


def test_skip_no_index_data(catalog):
    with pytest.raises(SweepSkip):
        compute_grid_best(catalog, 424242)


# ---------------------------------------------------------------------------
# Upserts: idempotent, this module owns the two tables
# ---------------------------------------------------------------------------

def test_upsert_best_idempotent(catalog):
    _seed_grid(catalog)
    row = compute_grid_best(catalog, GRID)
    upsert_best(catalog, row)
    upsert_best(catalog, row)                    # second run: update, not dup
    got = catalog.execute("SELECT * FROM prf_opt_best").fetchall()
    assert len(got) == 1
    assert got[0]["grid_id"] == GRID
    assert got[0]["best_win_rate"] == row["best_win_rate"]
    assert got[0]["n_policies"] == row["n_policies"]


def test_upsert_grid_counties_idempotent(catalog):
    rows = [(101, "ID", "16013", "Blaine"), (101, "MT", "30001", "Big Horn")]
    assert upsert_grid_counties(catalog, rows, "adm_2026") == 2
    upsert_grid_counties(catalog, rows, "adm_2026")
    got = catalog.execute(
        "SELECT COUNT(*) FROM prf_grid_county").fetchone()[0]
    assert got == 2


# ---------------------------------------------------------------------------
# sweep(): end-to-end over the fixtures, ensure_grid stubbed (no network)
# ---------------------------------------------------------------------------

class _Cfg:
    reinsurance_year = 2026


def test_sweep_end_to_end_and_resume(adm_dir, catalog, monkeypatch):
    _seed_grid(catalog, grid=101)
    _seed_grid(catalog, grid=102)
    calls = []
    monkeypatch.setattr(
        prfsweep.prfdata, "ensure_grid",
        lambda gid, conn, **kw: calls.append(gid) or {"grid_id": gid})
    logs = []
    res = prfsweep.sweep(catalog, state="ID", use="Grazing", coverage=0.90,
                         adm_dir=adm_dir, cfg=_Cfg(), client=object(),
                         delay=0, log=logs.append)
    assert res["grids"] == 2 and res["swept"] == 2 and not res["skipped"]
    assert calls == [101, 102]
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_opt_best").fetchone()[0] == 2
    # grid->county map written, cross-state row included
    fips = {r[0] for r in catalog.execute(
        "SELECT county_fips FROM prf_grid_county")}
    assert {"16013", "16025", "30001"} <= fips
    # resume: nothing recomputed
    calls.clear()
    res2 = prfsweep.sweep(catalog, state="ID", adm_dir=adm_dir, cfg=_Cfg(),
                          client=object(), delay=0, log=logs.append)
    assert res2["resumed"] == 2 and res2["swept"] == 0 and calls == []
    # force: recomputed
    res3 = prfsweep.sweep(catalog, state="ID", adm_dir=adm_dir, cfg=_Cfg(),
                          client=object(), delay=0, force=True,
                          log=logs.append)
    assert res3["swept"] == 2
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_opt_best").fetchone()[0] == 2


def test_sweep_records_skips(adm_dir, catalog, monkeypatch):
    _seed_grid(catalog, grid=101)                 # 102 left unseeded -> skip
    monkeypatch.setattr(prfsweep.prfdata, "ensure_grid",
                        lambda gid, conn, **kw: {"grid_id": gid})
    res = prfsweep.sweep(catalog, state="ID", adm_dir=adm_dir, cfg=_Cfg(),
                         client=object(), delay=0, log=lambda *a: None)
    assert res["swept"] == 1
    assert 102 in res["skipped"]
    assert "no index data" in res["skipped"][102]
