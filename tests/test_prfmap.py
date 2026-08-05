"""Tests for the PRF map data-payload builder (src/prfmap.py)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db
from src.prfmap import build_prf_payload


def _insert(conn, **kw):
    cols = ("year", "state", "county_fips", "county_name", "intended_use",
            "irrigation_practice", "organic_practice", "county_base_value", "source")
    vals = tuple(kw.get(c) for c in cols)
    conn.execute(
        "INSERT INTO prf_county (year, state, county_fips, county_name, intended_use, "
        "irrigation_practice, organic_practice, county_base_value, source) "
        "VALUES (?,?,?,?,?,?,?,?,?)", vals)


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def populated(conn):
    # Two counties x Grazing/Haying x Irrigated/Non-Irrigated, distinct CBVs.
    _insert(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Grazing", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=12.50, source="synthetic")
    _insert(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Grazing", irrigation_practice="Irrigated",
            organic_practice="Conventional", county_base_value=85.00, source="synthetic")
    _insert(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Haying", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=40.00, source="synthetic")
    _insert(conn, year=2026, state="MT", county_fips="30001", county_name="Beaverhead",
            intended_use="Grazing", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=7.25, source="synthetic")
    conn.commit()
    return conn


def test_empty_db_is_graceful(conn):
    p = build_prf_payload(conn)
    assert p["counties"] == {}
    assert p["uses"] == [] and p["practices"] == [] and p["years"] == []
    assert p["min_cbv"] is None and p["max_cbv"] is None
    assert p["row_count"] == 0 and p["value_count"] == 0
    assert "generated" in p


def test_missing_table_is_graceful():
    conn = sqlite3.connect(":memory:")  # no schema at all
    conn.row_factory = sqlite3.Row
    p = build_prf_payload(conn)
    assert p["counties"] == {} and p["min_cbv"] is None
    conn.close()


def test_payload_shape(populated):
    p = build_prf_payload(populated)
    # county_fips -> use -> practice -> organic -> year -> cbv
    okg = p["counties"]["53047"]["Grazing"]
    assert okg["Non-Irrigated"]["Conventional"][2026] == 12.50
    assert okg["Irrigated"]["Conventional"][2026] == 85.00
    assert p["counties"]["53047"]["Haying"]["Non-Irrigated"]["Conventional"][2026] == 40.00
    assert p["counties"]["30001"]["Grazing"]["Non-Irrigated"]["Conventional"][2026] == 7.25


def test_axes_and_names(populated):
    p = build_prf_payload(populated)
    assert p["uses"] == ["Grazing", "Haying"]
    assert p["practices"] == ["Irrigated", "Non-Irrigated"]
    assert p["organics"] == ["Conventional"]
    assert p["years"] == [2026]
    assert p["county_names"]["53047"] == "Okanogan"
    assert p["county_names"]["30001"] == "Beaverhead"


def test_min_max_over_values(populated):
    p = build_prf_payload(populated)
    assert p["min_cbv"] == 7.25
    assert p["max_cbv"] == 85.00
    assert p["value_count"] == 4


def test_fips_zero_padded(conn):
    # A leading-zero FIPS supplied as a 4-char/int-ish string must pad to 5.
    _insert(conn, year=2026, state="CT", county_fips="9001", county_name="Hartford",
            intended_use="Grazing", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=30.0, source="synthetic")
    conn.commit()
    p = build_prf_payload(conn)
    assert "09001" in p["counties"]


def test_null_cbv_keeps_axis_but_no_value(conn):
    # A row with NULL CBV should register its use/practice axis but store no value.
    _insert(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Haying", irrigation_practice="Irrigated",
            organic_practice="Conventional", county_base_value=None, source="synthetic")
    conn.commit()
    p = build_prf_payload(conn)
    assert "Haying" in p["uses"] and "Irrigated" in p["practices"]
    assert p["value_count"] == 0
    assert p["counties"] == {}  # nothing shadable
    assert p["min_cbv"] is None


def test_multiple_years(conn):
    _insert(conn, year=2025, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Grazing", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=10.0, source="synthetic")
    _insert(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
            intended_use="Grazing", irrigation_practice="Non-Irrigated",
            organic_practice="Conventional", county_base_value=13.0, source="synthetic")
    conn.commit()
    p = build_prf_payload(conn)
    assert p["years"] == [2025, 2026]
    cell = p["counties"]["53047"]["Grazing"]["Non-Irrigated"]["Conventional"]
    assert cell[2025] == 10.0 and cell[2026] == 13.0
