"""Tests for the webmap data-payload builder (src/webmap.py)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db
from src.webmap import build_payload


def _insert_product(conn, pid, bucket, name, aip_code=None, notes=None):
    conn.execute(
        "INSERT INTO products (product_id, bucket, program, name, aip_code, "
        " source_type, notes, natural_key) VALUES (?,?,?,?,?,?,?,?)",
        (pid, bucket,
         "private_nonreinsured" if bucket == "private" else "federal_508h",
         name, aip_code, "test", notes, f"key-{pid}"))


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("INSERT INTO aips (aip_code, name) VALUES ('FH', 'Farmers Mutual Hail')")

    # 1: federal, states only, NO county rows -> county fallback pending
    _insert_product(conn, 1, "508h", "Fed No Counties")
    conn.executemany("INSERT INTO product_states VALUES (1, ?)", [("IA",), ("NE",)])
    conn.execute("INSERT INTO product_crops VALUES (1, 'Corn')")

    # 2: federal, county rows for IA only, but filed states IA+MN
    _insert_product(conn, 2, "508h", "Fed With Counties")
    conn.executemany("INSERT INTO product_states VALUES (2, ?)", [("IA",), ("MN",)])
    conn.execute("INSERT INTO product_crops VALUES (2, 'Corn')")
    conn.executemany(
        "INSERT INTO product_counties (product_id, crop, state, county_fips, county_name, source)"
        " VALUES (?,?,?,?,?,?)",
        [(2, "Corn", "IA", "19153", "Polk", "adm_2026"),
         (2, "Soybeans", "IA", "19169", "Story", "adm_2026")])

    # 3: private, statewide filings
    _insert_product(conn, 3, "private", "Private Hail", aip_code="FH")
    conn.executemany("INSERT INTO product_states VALUES (3, ?)", [("IA",), ("MN",)])

    # 4: private, no states at all -> unmapped
    _insert_product(conn, 4, "private", "Private Unmapped", aip_code="FH")

    # 5: federal nationwide by notes, no states rows
    _insert_product(conn, 5, "508h", "Fed Nationwide", notes="Available nationwide.")
    yield conn
    conn.close()


def _by_name(payload):
    return {p["name"]: p for p in payload["products"]}

def test_subsidized_flag(conn):
    prods = _by_name(build_payload(conn))
    assert prods["Fed No Counties"]["subsidized"] is True
    assert prods["Fed With Counties"]["subsidized"] is True
    assert prods["Fed Nationwide"]["subsidized"] is True
    assert prods["Private Hail"]["subsidized"] is False
    assert prods["Private Unmapped"]["subsidized"] is False


def test_private_expands_to_states_statewide_grain(conn):
    p = _by_name(build_payload(conn))["Private Hail"]
    assert p["scope"] == "mapped"
    assert p["states"] == ["IA", "MN"]
    assert p["counties"] == {}          # private = state grain, never county rows
    assert p["county_pending"] is False  # pending is a federal-only concept
    assert p["aip"] == "Farmers Mutual Hail"


def test_federal_county_fallback_logic(conn):
    prods = _by_name(build_payload(conn))

    # No county rows anywhere -> whole product pending ADM detail.
    p1 = prods["Fed No Counties"]
    assert p1["scope"] == "mapped"
    assert p1["states"] == ["IA", "NE"]
    assert p1["county_states"] == []
    assert p1["county_pending"] is True

    # County rows for IA only -> IA is county grain, MN still pending.
    p2 = prods["Fed With Counties"]
    assert p2["county_states"] == ["IA"]
    assert p2["counties"] == {"19153": ["Corn"], "19169": ["Soybeans"]}
    assert p2["county_pending"] is True  # MN has no county rows yet
    # crop filter list unions product_crops with ADM county crops
    assert p2["all_crops"] == ["Corn", "Soybeans"]

    # Nationwide federal without county rows is also pending.
    p5 = prods["Fed Nationwide"]
    assert p5["scope"] == "nationwide"
    assert p5["county_pending"] is True


def test_unmapped_and_federal_aip_label(conn):
    payload = build_payload(conn)
    prods = _by_name(payload)
    assert prods["Private Unmapped"]["scope"] == "unmapped"
    # federal products carry no AIP -> shown as offered by all AIPs
    assert prods["Fed No Counties"]["aip"] == "All AIPs"
    assert payload["county_rows"] == 2
