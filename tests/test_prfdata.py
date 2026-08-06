"""Unit tests for src/prfdata.py parsing + fetch-API shapes — no live calls."""
from __future__ import annotations

import sqlite3

import pytest

from src import db, prfdata


# ---------------------------------------------------------------------------
# fixtures (trimmed real PrfWebApi payloads for grid 27663)
# ---------------------------------------------------------------------------

INDEX_PAYLOAD = {
    "HistoricalIndexRows": [
        {"Year": 1948, "HistoricalIndexDataColumns": [
            {"Year": 1948, "IntervalCode": "625", "PercentOfNormal": 0.798,
             "IntervalMeasurement": 623.2246913902,
             "AverageIntervalMeasurement": 780.5718508232, "GridId": 27663},
            {"Year": 1948, "IntervalCode": "635", "PercentOfNormal": 1.169,
             "IntervalMeasurement": 952.8332546338,
             "AverageIntervalMeasurement": 815.1256269585, "GridId": 27663},
        ]},
        {"Year": 2026, "HistoricalIndexDataColumns": [
            {"Year": 2026, "IntervalCode": "625", "PercentOfNormal": 0.549,
             "GridId": 27663},
            # unreleased current-year interval -> null -> dropped
            {"Year": 2026, "IntervalCode": "630", "PercentOfNormal": None,
             "GridId": 27663},
            # unknown interval code -> dropped
            {"Year": 2026, "IntervalCode": "999", "PercentOfNormal": 1.0,
             "GridId": 27663},
        ]},
    ]
}

RATE_PAYLOAD = {
    "validatedIntervals": [
        {"IntervalCode": "625", "PremiumRate": 0.1800, "IntervalIsValid": True},
        {"IntervalCode": "626", "PremiumRate": 0.1890, "IntervalIsValid": True},
        {"IntervalCode": "635", "PremiumRate": 0.2201, "IntervalIsValid": True},
        # invalid interval -> dropped
        {"IntervalCode": "630", "PremiumRate": 0.0, "IntervalIsValid": False},
    ]
}

LOCATION_PAYLOAD = {
    "locationData": [
        {"StateName": "Idaho", "StateCode": "16", "CountyName": "Blaine",
         "CountyCode": "013", "GridId": 27663, "GridName": "27663"},
        {"StateName": "Idaho", "StateCode": "16", "CountyName": "Camas",
         "CountyCode": "025", "GridId": 27663, "GridName": "27663"},
    ]
}


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# interval map
# ---------------------------------------------------------------------------

def test_interval_map_is_the_11_bimonthly_intervals():
    assert len(prfdata.INTERVALS) == 11
    assert prfdata.INTERVALS["625"] == "JAN-FEB"
    assert prfdata.INTERVALS["635"] == "NOV-DEC"
    assert prfdata.INTERVAL_ORDER[0] == "JAN-FEB"
    assert prfdata.INTERVAL_ORDER[-1] == "NOV-DEC"
    assert len(set(prfdata.INTERVAL_ORDER)) == 11


# ---------------------------------------------------------------------------
# payload parsing
# ---------------------------------------------------------------------------

def test_parse_index_payload():
    rows = prfdata.parse_index_payload(INDEX_PAYLOAD)
    assert (1948, "JAN-FEB", 0.798) in rows
    assert (1948, "NOV-DEC", 1.169) in rows
    assert (2026, "JAN-FEB", 0.549) in rows
    # null PercentOfNormal and unknown interval codes are dropped
    assert len(rows) == 3


def test_parse_rate_payload():
    rates = prfdata.parse_rate_payload(RATE_PAYLOAD)
    assert rates == {"JAN-FEB": 0.1800, "FEB-MAR": 0.1890, "NOV-DEC": 0.2201}


def test_parse_location_payload():
    locs = prfdata.parse_location_payload(LOCATION_PAYLOAD)
    assert locs[0] == ("16", "013", "Idaho", "Blaine")
    assert len(locs) == 2


def test_parse_empty_payloads():
    assert prfdata.parse_index_payload({}) == []
    assert prfdata.parse_rate_payload({}) == {}
    assert prfdata.parse_location_payload({}) == []


# ---------------------------------------------------------------------------
# subsidy schedule
# ---------------------------------------------------------------------------

def test_subsidy_schedule_matches_adm_a00070_plan13():
    # ADM RY2026 A00070 rc04 plan 13: 70/75 -> .590, 80/85 -> .550, 90 -> .510, CAT=1.0
    s = prfdata.SUBSIDY_SCHEDULE
    assert s[0.70] == 0.590 and s[0.75] == 0.590
    assert s[0.80] == 0.550 and s[0.85] == 0.550
    assert s[0.90] == 0.510
    assert s[0.65] == 1.000


def test_ensure_subsidy_idempotent(conn):
    prfdata.ensure_subsidy(conn)
    prfdata.ensure_subsidy(conn)
    got = prfdata.subsidy_schedule(conn)
    assert got == prfdata.SUBSIDY_SCHEDULE


# ---------------------------------------------------------------------------
# DB round-trip + fetch API shapes (no network: rows inserted directly)
# ---------------------------------------------------------------------------

def _seed(conn, grid=27663, year=2026, use="Grazing"):
    conn.executemany(
        "INSERT INTO prf_grid_index VALUES (?,?,?,?,?,?)",
        [(grid, y, iv, 0.5 + 0.01 * i, "test", "t")
         for y in range(1999, 2026)
         for i, iv in enumerate(prfdata.INTERVAL_ORDER)])
    conn.executemany(
        "INSERT INTO prf_grid_rate VALUES (?,?,?,?,?,?,?,?)",
        [(grid, year, use, iv, cov, 0.10 + 0.01 * i + cov / 10, "test", "t")
         for cov in prfdata.COVERAGE_LEVELS
         for i, iv in enumerate(prfdata.INTERVAL_ORDER)])
    conn.commit()


def test_indices_matrix_shape(conn):
    _seed(conn)
    m = prfdata.indices_matrix(27663, conn)
    assert set(m) == set(range(1999, 2026))
    assert set(m[2000]) == set(prfdata.INTERVAL_ORDER)
    assert m[2000]["JAN-FEB"] == pytest.approx(0.5)


def test_rates_for(conn):
    _seed(conn)
    r = prfdata.rates_for(27663, "Grazing", 0.90, conn)
    assert set(r) == set(prfdata.INTERVAL_ORDER)
    assert r["JAN-FEB"] == pytest.approx(0.10 + 0.09)
    # year defaults to the latest stored; explicit year gives the same here
    assert prfdata.rates_for(27663, "Grazing", 0.90, conn, year=2026) == r
    # missing grid/use/coverage -> empty dict, not an error
    assert prfdata.rates_for(11111, "Grazing", 0.90, conn) == {}
    assert prfdata.rates_for(27663, "Haying", 0.90, conn) == {}


def test_ensure_grid_skips_when_populated(conn):
    """A populated DB satisfies ensure_grid with no HTTP client and no cache files."""
    _seed(conn)
    s = prfdata.ensure_grid(27663, conn, client=None)
    assert "index_rows_fetched" not in s          # nothing was fetched
    assert "rate_rows_fetched" not in s
    assert s["index_rows"] == 27 * 11
    assert s["rate_rows"] == 5 * 11
    assert s["index_years"] == (1999, 2025)


def test_ensure_grid_rejects_unknown_use(conn):
    with pytest.raises(ValueError):
        prfdata.ensure_grid(27663, conn, use="Mowing")


def test_have_indices_requires_complete_years(conn):
    # 24 complete years is not enough; partial years don't count
    conn.executemany(
        "INSERT INTO prf_grid_index VALUES (?,?,?,?,?,?)",
        [(1, y, iv, 1.0, "t", "t") for y in range(2001, 2025)
         for iv in prfdata.INTERVAL_ORDER])
    conn.execute("INSERT INTO prf_grid_index VALUES (1, 2025, 'JAN-FEB', 1.0, 't', 't')")
    assert not prfdata._have_indices(conn, 1)
    conn.executemany(
        "INSERT INTO prf_grid_index VALUES (?,?,?,?,?,?)",
        [(1, 2000, iv, 1.0, "t", "t") for iv in prfdata.INTERVAL_ORDER])
    assert prfdata._have_indices(conn, 1)
