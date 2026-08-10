"""Tests for scripts/harvest_prf_max_pct.py — the actuarial percent-of-value cap."""
import importlib.util
import pathlib
import sqlite3

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_hmp", _ROOT / "scripts" / "harvest_prf_max_pct.py")
_hmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hmp)

_DB = _ROOT / "data" / "catalog.db"
skip_no_db = pytest.mark.skipif(not _DB.exists(), reason="data/catalog.db not built")


@pytest.mark.parametrize("text,expected", [
    ("In accordance with Section 2 of the crop provisions, the maximum percent of value "
     "allowed is 50%.", (50, None)),
    ("Per the crop provisions, the maximum percent of value allowed in any one index "
     "interval is 40%.", (40, None)),
    # conditional: BOTH numbers captured, the lower one enforced
    ("Per the crop provisions, the maximum percent of value allowed in any one index "
     "interval is 40% except for growing seasons 10, 11, and 12 which is 50%.", (40, 50)),
    ("Per the crop provisions, the maximum percent of value allowed in any one index "
     "interval is 45% except for growing seasons 10, 11, and 12 which is 50%.", (45, 50)),
    ("This statement is about something else entirely.", None),
])
def test_parse_caps(text, expected):
    assert _hmp.parse_caps(text) == expected


def test_a_conditional_statement_enforces_the_lower_cap():
    """Erring low can only refuse an allocation that might have been legal. Erring high
    recommends one the producer cannot bind — which is the failure that matters."""
    lo, hi = _hmp.parse_caps(
        "the maximum percent of value allowed in any one index interval is 40% except for "
        "growing seasons 10, 11, and 12 which is 50%.")
    assert lo == 40 and hi == 50


@skip_no_db
def test_the_cap_is_not_a_national_constant():
    """The whole point. src/prfopt.py used MAX_PCT = 60 everywhere; the actuarial documents
    publish 40/45/50/60/70 and nine states are not uniform across their own counties."""
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    caps = {r[0] for r in conn.execute("SELECT DISTINCT max_pct FROM prf_max_pct")}
    if not caps:
        pytest.skip("prf_max_pct not harvested")
    assert caps == {40, 45, 50, 60, 70}, caps
    nonuniform = conn.execute(
        "SELECT COUNT(*) FROM (SELECT state_code FROM prf_max_pct "
        "GROUP BY state_code HAVING COUNT(DISTINCT max_pct) > 1)").fetchone()[0]
    assert nonuniform == 9, f"expected 9 non-uniform states, got {nonuniform}"


@skip_no_db
def test_the_retired_constant_was_wrong_in_both_directions():
    """Guards the finding itself: 60 was too permissive in far more counties than it was too
    restrictive, so the dominant error was recommending unbuyable allocations."""
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT SUM(max_pct < 60), SUM(max_pct > 60) FROM "
        "(SELECT DISTINCT state_code, county_code, max_pct FROM prf_max_pct)").fetchone()
    if row[0] is None:
        pytest.skip("prf_max_pct not harvested")
    too_high, too_low = row
    assert too_high > 0 and too_low > 0
    assert too_high > too_low
