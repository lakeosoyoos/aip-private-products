"""Tests for src/rowcropprospects.py — the opportunity x basis-risk join."""
import pathlib
import sqlite3

import pytest

from src.rowcropprospects import (
    DEFAULT_MAX_MISS,
    axes,
    basis_variants,
    find_prospects,
)

_APP_DB = pathlib.Path(__file__).resolve().parents[1] / "data" / "catalog_app.db"
skip_no_app_db = pytest.mark.skipif(not _APP_DB.exists(), reason="catalog_app.db not built")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE rowcrop_unclaimed (state TEXT, county_fips TEXT, crop TEXT, "
              "band TEXT, unsold_acres REAL, penetration REAL, sub_per_acre REAL, "
              "unclaimed_subsidy REAL)")
    c.execute("CREATE TABLE basis_risk_county (county_fips TEXT, crop TEXT, band TEXT, "
              "coverage_level REAL, plan_type TEXT, miss_rate REAL, "
              "miss_rate_rho_lo REAL, grade TEXT)")
    c.execute("CREATE TABLE prf_grid_county (grid_id INTEGER, state TEXT, county_fips TEXT, "
              "county_name TEXT, source TEXT)")
    yield c
    c.close()


def _cell(c, fips="19001", crop="Corn", band="ECO", acres=10_000, pen=0.4,
          spa=25.0, unclaimed=250_000.0, state="IA"):
    c.execute("INSERT INTO rowcrop_unclaimed VALUES (?,?,?,?,?,?,?,?)",
              (state, fips, crop, band, acres, pen, spa, unclaimed))


def _basis(c, fips="19001", crop="Corn", band="ECO95", miss=0.10, miss_lo=0.25, grade="A"):
    c.execute("INSERT INTO basis_risk_county VALUES (?,?,?,?,?,?,?,?)",
              (fips, crop, band, 0.75, "RP", miss, miss_lo, grade))


def test_the_band_vocabularies_must_be_bridged():
    """rowcrop_unclaimed says ECO; basis_risk_county says ECO95/ECO90. Joining the raw
    strings returns zero rows SILENTLY — which is exactly what happened the first time this
    query was written by hand."""
    assert basis_variants("ECO")[0] == "ECO95"
    assert basis_variants("SCO") == ("SCO86",)
    assert basis_variants("MCO") == ()          # genuinely unmeasured
    assert basis_variants("nonsense") == ()


def test_a_cell_with_no_basis_estimate_is_excluded_by_default_and_never_called_low_risk(conn):
    """MCO has no published basis risk. 'We did not measure it' must not be presentable as
    'it is fine' — so it is dropped unless explicitly asked for, and carries None either way.
    """
    _cell(conn, band="MCO")
    conn.commit()
    assert find_prospects(conn).rows == []
    kept = find_prospects(conn, include_unknown_basis=True).rows
    assert len(kept) == 1
    assert kept[0].miss_rate_rho_lo is None and kept[0].basis_known is False
    assert kept[0].basis_band is None


def test_the_screen_uses_the_pessimistic_correlation(conn):
    """A cell that looks fine at rho 0.70 and fails at rho 0.35 must be screened OUT. The one
    empirical check available says the real miss rate sits at the pessimistic end, so
    screening on the reference figure passes the cells most likely to disappoint."""
    _cell(conn)
    _basis(conn, miss=0.08, miss_lo=0.55)       # great at the reference, bad at the floor
    conn.commit()
    assert find_prospects(conn, max_miss=0.30).rows == []
    assert len(find_prospects(conn, max_miss=None).rows) == 1


def test_conservative_takes_the_worse_trigger_variant(conn):
    """ECO sells at 95% and 90% with materially different basis risk, and the Summary of
    Business does not record which a county bought. Default is the representative ECO95;
    conservative=True reads the ECO90 floor."""
    _cell(conn)
    _basis(conn, band="ECO95", miss=0.10, miss_lo=0.25)
    _basis(conn, band="ECO90", miss=0.20, miss_lo=0.48)
    conn.commit()
    default = find_prospects(conn, max_miss=None).rows[0]
    worst = find_prospects(conn, max_miss=None, conservative=True).rows[0]
    assert default.basis_band == "ECO95" and default.miss_rate_rho_lo == 0.25
    assert worst.basis_band == "ECO90" and worst.miss_rate_rho_lo == 0.48
    # and the screen actually bites differently
    assert find_prospects(conn, max_miss=0.30).rows
    assert not find_prospects(conn, max_miss=0.30, conservative=True).rows


def test_missing_values_sort_last_in_both_directions(conn):
    """A None is not a good score. Ascending sorts (penetration, miss) must not float
    unknowns to the top where they read as the best prospects."""
    _cell(conn, fips="19001", pen=0.9, unclaimed=100.0)
    _cell(conn, fips="19003", pen=None, unclaimed=200.0)
    _basis(conn, fips="19001")
    _basis(conn, fips="19003")
    conn.commit()
    rows = find_prospects(conn, min_acres=0, sort="penetration").rows
    assert [r.county_fips for r in rows] == ["19001", "19003"]


def test_filters_compose(conn):
    _cell(conn, fips="19001", state="IA", crop="Corn", acres=10_000)
    _cell(conn, fips="20001", state="KS", crop="Wheat", acres=10_000)
    _basis(conn, fips="19001", crop="Corn")
    _basis(conn, fips="20001", crop="Wheat")
    conn.commit()
    assert len(find_prospects(conn, states=["KS"]).rows) == 1
    assert len(find_prospects(conn, crops=["Corn"]).rows) == 1
    assert find_prospects(conn, min_acres=50_000).rows == []
    assert find_prospects(conn, max_penetration=0.10).rows == []


def test_missing_tables_degrade_instead_of_raising():
    """The sub-tab must not take Row Crop down on a DB that lacks the opportunity tables."""
    c = sqlite3.connect(":memory:")
    res = find_prospects(c)
    assert res.rows == [] and res.total_cells == 0
    assert axes(c) == {"states": [], "crops": [], "bands": []}
    c.close()


@skip_no_app_db
def test_against_the_shipped_database():
    """The screen must return a usable shortlist on real data — not everything, not nothing.

    Taking the WORST trigger variant returned 1 row out of 19,102, which is why the default
    is the representative one. This pins that the default stays useful.
    """
    c = sqlite3.connect(f"file:{_APP_DB}?mode=ro", uri=True)
    try:
        res = find_prospects(c, limit=100_000)
        if res.total_cells == 0:
            pytest.skip("rowcrop_unclaimed not in the shipped DB")
        assert 50 < len(res.rows) < res.total_cells, (
            f"{len(res.rows)} of {res.total_cells} — the default screen is useless at this "
            f"size; check the band-variant choice")
        for p in res.rows:
            assert p.miss_rate_rho_lo is not None and p.miss_rate_rho_lo <= DEFAULT_MAX_MISS
            assert p.unsold_acres >= 5_000
    finally:
        c.close()
