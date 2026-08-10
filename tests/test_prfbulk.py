"""Tests for src/prfbulk.py — the bulk PRF data path. No live calls.

Everything here runs against fixtures built in tmp_path: a miniature VI/RI zip and a
miniature ADM chain (A00520/A00440/A00810/A01130/A01135). The one function that would
touch the network (ensure_bulk_zip) is never reached, because every loader call passes
an explicit zip_path / adm_dir.
"""

import io
import zipfile

import pytest

from src import db, prfbulk, prfdata, prfopt

BULK_HEADER = ("grid_id|InsurancePlanCode|Commodity0088|Commodity1191|Year|"
               "PracticeCode|ActualIndex")


# ---------------------------------------------------------------------------
# The pipe parse
# ---------------------------------------------------------------------------

def test_parse_index_line_happy_path():
    assert prfbulk.parse_index_line("10020|13|1|1|1948|625|0.755") == (
        10020, 1948, "JAN-FEB", 0.755)
    # trailing CRLF (the file ships with DOS line endings)
    assert prfbulk.parse_index_line("10020|13|1|1|2024|635|1.234\r\n") == (
        10020, 2024, "NOV-DEC", 1.234)


@pytest.mark.parametrize("line, why", [
    (BULK_HEADER, "header row"),
    ("", "blank line"),
    ("10020|13|1", "too few fields"),
    ("H1234|13|1|1|1948|625|0.755", "Hawaii-system grid id"),
    ("K1234|13|1|1|1948|625|0.755", "other non-numeric grid id"),
    ("10020|14|1|1|1948|625|0.755", "not insurance plan 13"),
    ("10020|13|0|1|1948|625|0.755", "not commodity 0088 (PRF)"),
    ("10020|13|1|1|1948|999|0.755", "unknown interval/practice code"),
    ("10020|13|1|1|1948|625|", "blank index value"),
    ("10020|13|1|1|abcd|625|0.755", "unparseable year"),
    ("10020|13|1|1|1948|625|x", "unparseable index"),
])
def test_parse_index_line_drops_bad_rows(line, why):
    assert prfbulk.parse_index_line(line) is None, why


def test_parse_index_line_year_window():
    ok = "10020|13|1|1|2005|625|0.5"
    assert prfbulk.parse_index_line(ok) is not None
    assert prfbulk.parse_index_line(ok, min_year=2006) is None
    assert prfbulk.parse_index_line(ok, max_year=2004) is None
    assert prfbulk.parse_index_line(ok, min_year=2000, max_year=2010) is not None


# ---------------------------------------------------------------------------
# Interval-code mapping
# ---------------------------------------------------------------------------

def test_interval_codes_are_the_eleven_sequential_bimonthly_intervals():
    codes = sorted(prfbulk.INTERVAL_BY_CODE)
    assert codes == [str(c) for c in range(625, 636)]
    # 625..635 map onto JAN-FEB..NOV-DEC IN ORDER, matching ADM A00480 and the
    # order the optimizer enumerates intervals in.
    assert [prfbulk.INTERVAL_BY_CODE[c] for c in codes] == list(prfopt.INTERVALS)
    assert prfbulk.INTERVAL_BY_CODE["625"] == "JAN-FEB"
    assert prfbulk.INTERVAL_BY_CODE["635"] == "NOV-DEC"
    assert prfbulk.INTERVAL_BY_CODE == prfdata.INTERVALS


# ---------------------------------------------------------------------------
# Fixtures: a miniature bulk zip and a miniature ADM chain
# ---------------------------------------------------------------------------

GRIDS = (101, 102)
# Mirrors prfsweep.YEARS: 20 years, 2006..2025.
YEARS = tuple(range(2006, 2026))
CODES = tuple(str(c) for c in range(625, 636))


def _index_value(grid, year, k):
    """Deterministic, varied enough that the optimizer finds real winners/losers."""
    return round(0.70 + 0.05 * ((year + k + grid) % 12), 3)


@pytest.fixture()
def bulk_zip(tmp_path):
    lines = [BULK_HEADER]
    for grid in GRIDS:
        for year in YEARS:
            for k, code in enumerate(CODES):
                lines.append(f"{grid}|13|1|1|{year}|{code}|{_index_value(grid, year, k)}")
    # rows the loader must drop: Hawaii grid, non-PRF commodity, other plan
    lines += ["H0101|13|1|1|2006|625|0.900",
              "103|13|0|1|2006|625|0.900",
              "104|12|1|1|2006|625|0.900"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Rainfall_Index_HistoricData2026CY.txt",
                    "\r\n".join(lines) + "\r\n")
    path = tmp_path / "bulk.zip"
    path.write_bytes(buf.getvalue())
    return path


def _price_row(offer, grid, state, county, use="007", irr="997", org="997",
               interval="625", plan="13", commodity="0088", rc="03", ry="2026"):
    f = [""] * 82
    f[0], f[1], f[2], f[3] = "A00810", rc, str(offer), ry
    f[5], f[6] = commodity, plan
    f[7], f[8], f[9] = state, county, str(grid)
    f[20], f[21], f[23], f[24] = use, irr, org, interval
    return "|".join(f)


def _cov_row(offer, grid, coverage, rate_id, covtype="A", ry="2026", rc="05"):
    f = [""] * 17
    f[0], f[1], f[2], f[3], f[4] = "A01130", rc, ry, str(offer), str(grid)
    f[6], f[7], f[12] = f"{coverage:.2f}", covtype, str(rate_id)
    return "|".join(f)


def _rate_row(rate_id, base_rate, ry="2026"):
    f = [""] * 9
    f[0], f[1], f[2], f[3], f[5] = "A01135", "01", ry, str(rate_id), f"{base_rate:.4f}"
    return "|".join(f)


# One offer per (county x use x interval) -- the real ADM grain -- covering BOTH grids,
# so the tests exercise the county-offer -> per-grid fan-out that A01130 performs.
def _base_rate(grid, k, coverage):
    return round(0.05 + 0.01 * k + 0.02 * (coverage - 0.70) * 10 + 0.001 * (grid - 101), 4)


@pytest.fixture()
def adm_dir(tmp_path):
    d = tmp_path / "adm"
    d.mkdir()
    price, cov, rate = ["hdr"], ["hdr"], ["hdr"]
    rid = 900000
    for k, code in enumerate(CODES):
        offer = 500000 + k
        for grid in GRIDS:                       # both grids sit in county 16/013
            price.append(_price_row(offer, grid, "16", "013", interval=code))
            for c in prfdata.COVERAGE_LEVELS:
                rid += 1
                cov.append(_cov_row(offer, grid, c, rid))
                rate.append(_rate_row(rid, _base_rate(grid, k, c)))
    # grid 101 also reaches into Montana (border grid) through a second county offer
    price.append(_price_row(500000, 101, "30", "001", interval="625"))
    # rows that must be ignored
    price.append(_price_row(700001, 999, "16", "013", plan="12"))       # not PRF
    price.append(_price_row(700002, 998, "16", "013", rc="01"))         # wrong category
    cov.append(_cov_row(500000, 101, 0.65, 999999, covtype="C"))        # CAT
    cov.append(_cov_row(500000, 101, 0.90, 888888))                     # dangling rate id

    (d / "2026_A00810_Price_YTD.txt").write_text("\n".join(price) + "\n")
    (d / "daily250825_2026_A01130_AreaCoverageLevel_Daily.txt").write_text(
        "\n".join(cov) + "\n")
    (d / "daily250825_2026_A01135_AreaRate_Daily.txt").write_text("\n".join(rate) + "\n")
    (d / "2026_A00520_State_YTD.txt").write_text(
        "hdr\n"
        "A00520|01|2026|16|Idaho|ID|10|Spokane|||\n"
        "A00520|01|2026|30|Montana|MT|10|Billings|||\n")
    (d / "2026_A00440_County_YTD.txt").write_text(
        "hdr\n"
        "A00440|01|2026|16|013|Blaine|||\n"
        "A00440|01|2026|30|001|Big Horn|||\n")
    return d


@pytest.fixture()
def catalog(tmp_path):
    conn = db.connect(tmp_path / "cat.db")
    db.init_db(conn)
    yield conn
    conn.close()


class _Cfg:
    reinsurance_year = 2026
    user_agent = "test"
    timeout_seconds = 5


# ---------------------------------------------------------------------------
# load_indices
# ---------------------------------------------------------------------------

def test_load_indices(catalog, bulk_zip):
    res = prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(),
                               log=lambda *a: None)
    assert res["grids"] == len(GRIDS)
    assert res["rows"] == len(GRIDS) * len(YEARS) * 11
    assert res["years"] == (min(YEARS), max(YEARS))
    # Hawaii / non-PRF / other-plan rows were dropped, not loaded
    assert res["non_prf_or_hawaii_lines"] == 3
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_grid_index WHERE grid_id IN (103,104)"
    ).fetchone()[0] == 0
    row = catalog.execute(
        "SELECT index_value, source FROM prf_grid_index WHERE grid_id=101 "
        "AND year=2006 AND interval_code='JAN-FEB'").fetchone()
    assert row[0] == _index_value(101, 2006, 0)
    assert row[1] == prfbulk.INDEX_SOURCE


def test_load_indices_is_idempotent_and_gated(catalog, bulk_zip):
    kw = dict(zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    first = prfbulk.load_indices(catalog, **kw)
    n = catalog.execute("SELECT COUNT(*) FROM prf_grid_index").fetchone()[0]
    # without --force the whole job short-circuits
    second = prfbulk.load_indices(catalog, **kw)
    assert second["skipped_job"] and second["rows"] == 0
    # with force it reloads and upserts to the same row count (no duplicates)
    third = prfbulk.load_indices(catalog, force=True, **kw)
    assert third["rows"] == first["rows"]
    assert catalog.execute("SELECT COUNT(*) FROM prf_grid_index").fetchone()[0] == n


def test_load_indices_min_year_trims(catalog, bulk_zip):
    prfbulk.load_indices(catalog, zip_path=bulk_zip, min_year=2020, cfg=_Cfg(),
                         log=lambda *a: None)
    lo = catalog.execute("SELECT MIN(year) FROM prf_grid_index").fetchone()[0]
    assert lo == 2020


# ---------------------------------------------------------------------------
# load_rates_counties
# ---------------------------------------------------------------------------

def test_load_rates_counties(catalog, adm_dir):
    res = prfbulk.load_rates_counties(catalog, adm_dir=adm_dir, cfg=_Cfg(),
                                      uses=("Grazing",), log=lambda *a: None)
    assert res["rate_grids"] == len(GRIDS)
    assert res["rate_rows"] == len(GRIDS) * 11 * len(prfdata.COVERAGE_LEVELS)
    assert res["county_rate_conflicts"] == 0
    assert res["missing_area_rate_id"] == 1          # the dangling rate id row

    # THE JOIN THAT MATTERS: the offer is county-grain, so each grid must get its
    # OWN rate off A01130's Sub County Code rather than a copy of its neighbour's.
    got = dict(catalog.execute(
        "SELECT grid_id, premium_rate FROM prf_grid_rate WHERE interval_code='JAN-FEB' "
        "AND ABS(coverage_level - 0.90) < 1e-9"))
    assert got == {101: _base_rate(101, 0, 0.90), 102: _base_rate(102, 0, 0.90)}
    assert got[101] != got[102]

    # CAT (coverage type 'C') is not an optimizer coverage level and stays out
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_grid_rate WHERE coverage_level < 0.70"
    ).fetchone()[0] == 0

    # grid -> county, including the border grid's second state
    counties = {(g, st, fips) for g, st, fips in catalog.execute(
        "SELECT grid_id, state, county_fips FROM prf_grid_county")}
    assert (101, "ID", "16013") in counties
    assert (101, "MT", "30001") in counties          # border grid
    assert (102, "ID", "16013") in counties
    assert catalog.execute(
        "SELECT county_name FROM prf_grid_county WHERE county_fips='16013' LIMIT 1"
    ).fetchone()[0] == "Blaine"
    # the subsidy schedule comes along for free
    assert prfdata.subsidy_schedule(catalog)[0.90] == prfdata.SUBSIDY_SCHEDULE[0.90]


def test_load_rates_counties_gated(catalog, adm_dir):
    kw = dict(adm_dir=adm_dir, cfg=_Cfg(), uses=("Grazing",), log=lambda *a: None)
    prfbulk.load_rates_counties(catalog, **kw)
    again = prfbulk.load_rates_counties(catalog, **kw)
    assert again["skipped_job"] and again["rate_rows"] == 0


# ---------------------------------------------------------------------------
# Hash change-detection
# ---------------------------------------------------------------------------

def test_window_hash_covers_only_the_scoring_window(catalog, bulk_zip):
    prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    h = prfbulk.window_hash(catalog, 101)
    assert h and len(h) == 64
    # a value OUTSIDE 2006-2025 must not move the fingerprint
    catalog.execute("INSERT OR REPLACE INTO prf_grid_index VALUES "
                    "(101, 1995, 'JAN-FEB', 0.5, 's', 't')")
    catalog.commit()
    assert prfbulk.window_hash(catalog, 101) == h
    # a value INSIDE it must
    catalog.execute("UPDATE prf_grid_index SET index_value = index_value + 0.001 "
                    "WHERE grid_id=101 AND year=2010 AND interval_code='JUL-AUG'")
    catalog.commit()
    assert prfbulk.window_hash(catalog, 101) != h
    assert prfbulk.window_hash(catalog, 999) is None      # unknown grid


def test_current_hashes_matches_per_grid_window_hash(catalog, bulk_zip):
    prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    cur = prfbulk.current_hashes(catalog)
    assert set(cur) == set(GRIDS)
    for g in GRIDS:
        assert cur[g] == prfbulk.window_hash(catalog, g)
    assert cur[101] != cur[102]


def test_changed_grids_lifecycle(catalog, bulk_zip):
    prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    # never hashed -> everything counts as changed (first run sweeps all)
    assert prfbulk.changed_grids(catalog) == sorted(GRIDS)

    assert prfbulk.update_hashes(catalog) == len(GRIDS)
    assert prfbulk.changed_grids(catalog) == []

    # RMA revises one grid's window -> only that grid comes back
    catalog.execute("UPDATE prf_grid_index SET index_value = 0.123 "
                    "WHERE grid_id=102 AND year=2015 AND interval_code='MAR-APR'")
    catalog.commit()
    assert prfbulk.changed_grids(catalog) == [102]
    # a revision outside the window is correctly ignored
    catalog.execute("INSERT OR REPLACE INTO prf_grid_index VALUES "
                    "(101, 1970, 'JAN-FEB', 9.9, 's', 't')")
    catalog.commit()
    assert prfbulk.changed_grids(catalog) == [102]
    # scoping to a subset, and re-hashing only what was handled
    assert prfbulk.changed_grids(catalog, grid_ids=[101]) == []
    prfbulk.update_hashes(catalog, [102])
    assert prfbulk.changed_grids(catalog) == []
    stored = prfbulk.stored_hashes(catalog)
    assert stored[102] == prfbulk.window_hash(catalog, 102)


# ---------------------------------------------------------------------------
# Synthetic end-to-end: bulk files -> DB -> sweep_bulk -> prf_opt_best
# ---------------------------------------------------------------------------

def test_end_to_end_bulk_load_then_sweep(catalog, bulk_zip, adm_dir, monkeypatch):
    from src import prfsweep

    prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    prfbulk.load_rates_counties(catalog, adm_dir=adm_dir, cfg=_Cfg(),
                                uses=("Grazing",), log=lambda *a: None)

    # No network client is ever constructed on this path -- make that a hard failure.
    monkeypatch.setattr(prfsweep.http, "Client",
                        lambda *a, **k: pytest.fail("bulk sweep must not hit the network"))

    res = prfsweep.sweep_bulk(catalog, cfg=_Cfg(), log=lambda *a: None)
    assert res["grids"] == len(GRIDS)
    assert res["swept"] == len(GRIDS) and not res["skipped"]
    assert res["per_state"]["ID"]["swept"] == 2          # border grid booked to one state

    rows = catalog.execute(
        "SELECT grid_id, n_policies, year_min, year_max, best_win_rate, source "
        "FROM prf_opt_best ORDER BY grid_id").fetchall()
    assert [r["grid_id"] for r in rows] == list(GRIDS)
    for r in rows:
        assert r["n_policies"] == 59_536              # all 11 intervals rated
        assert (r["year_min"], r["year_max"]) == (min(YEARS), max(YEARS))
        assert 0.0 <= r["best_win_rate"] <= 1.0
        assert r["source"] == "prfbulk_2026"

    # the sweep fingerprinted what it scored, so --changed-only now has nothing to do
    assert prfbulk.changed_grids(catalog) == []
    res2 = prfsweep.sweep_bulk(catalog, changed_only=True, cfg=_Cfg(),
                               log=lambda *a: None)
    assert res2["swept"] == 0

    # resumability: a plain re-run recomputes nothing
    res3 = prfsweep.sweep_bulk(catalog, cfg=_Cfg(), log=lambda *a: None)
    assert res3["swept"] == 0 and res3["resumed"] == len(GRIDS)

    # ...until an index revision lands, and then only the affected grid
    catalog.execute("UPDATE prf_grid_index SET index_value = 0.111 "
                    "WHERE grid_id=102 AND year=2012 AND interval_code='MAY-JUN'")
    catalog.commit()
    res4 = prfsweep.sweep_bulk(catalog, changed_only=True, force=True, cfg=_Cfg(),
                               log=lambda *a: None)
    assert res4["swept"] == 1 and res4["grids"] == 1


def test_sweep_bulk_state_filter_and_skips(catalog, bulk_zip, adm_dir):
    from src import prfsweep

    prfbulk.load_indices(catalog, zip_path=bulk_zip, cfg=_Cfg(), log=lambda *a: None)
    prfbulk.load_rates_counties(catalog, adm_dir=adm_dir, cfg=_Cfg(),
                                uses=("Grazing",), log=lambda *a: None)
    # only grid 101 touches Montana
    res = prfsweep.sweep_bulk(catalog, state="MT", cfg=_Cfg(), log=lambda *a: None)
    assert res["grids"] == 1 and res["swept"] == 1

    # a grid with rates but no index history is SKIPPED with a reason, never invented
    catalog.execute("INSERT OR REPLACE INTO prf_grid_county VALUES "
                    "(777, 'ID', '16013', 'Blaine', 'test')")
    catalog.commit()
    res2 = prfsweep.sweep_bulk(catalog, state="ID", cfg=_Cfg(), log=lambda *a: None)
    assert 777 in res2["skipped"]
    assert "no index data" in res2["skipped"][777]
    assert catalog.execute(
        "SELECT COUNT(*) FROM prf_opt_best WHERE grid_id=777").fetchone()[0] == 0
