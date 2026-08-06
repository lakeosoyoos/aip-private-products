"""Tests for the PRF Optimizer map payload builder (src/prfoptmap.py)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from src import db
from src.prfoptmap import (
    _cov_key, _fips5, _parse_list, build_opt_payload, render_opt_html,
)


def _grid_county(conn, grid_id, county_fips, county_name="X", state="WA"):
    conn.execute(
        "INSERT INTO prf_grid_county (grid_id, state, county_fips, county_name, source) "
        "VALUES (?,?,?,?,?)", (grid_id, state, county_fips, county_name, "synthetic"))


def _opt(conn, grid_id, use="Grazing", cov=0.9, *, win=None, win_combo=None,
         win_props=None, win_net=None, net=None, net_combo=None, net_props=None,
         net_win=None, median_net=None, pct_positive=None):
    conn.execute(
        "INSERT INTO prf_opt_best (grid_id, intended_use, coverage_level, year_min, "
        "year_max, n_policies, best_win_rate, best_win_combo, best_win_props, "
        "best_win_avg_net, best_net, best_net_combo, best_net_props, "
        "best_net_win_rate, median_net, pct_positive, top_json, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (grid_id, use, cov, 2006, 2024, 59536, win,
         json.dumps(win_combo) if isinstance(win_combo, list) else win_combo,
         json.dumps(win_props) if isinstance(win_props, list) else win_props,
         win_net, net,
         json.dumps(net_combo) if isinstance(net_combo, list) else net_combo,
         json.dumps(net_props) if isinstance(net_props, list) else net_props,
         net_win, median_net, pct_positive, None, "synthetic", "2026-08-05"))


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()


# ------------------------------------------------------------------ helpers

def test_cov_key_canonical():
    assert _cov_key(0.9) == "0.9"
    assert _cov_key("0.90") == "0.9"
    assert _cov_key(0.85) == "0.85"
    assert _cov_key(0.7) == "0.7"
    assert _cov_key(None) == "None"       # never raises
    assert _cov_key("weird") == "weird"


def test_fips5_pads():
    assert _fips5("9001") == "09001"
    assert _fips5(53047) == "53047"
    assert _fips5("") == ""
    assert _fips5(None) == ""


def test_parse_list_json_and_python_repr():
    assert _parse_list('["JUN-JUL","AUG-SEP"]') == ["JUN-JUL", "AUG-SEP"]
    assert _parse_list("[50, 50]") == [50, 50]
    # optimizer's historical export format: Python repr with single quotes
    assert _parse_list("['JAN-FEB', 'JUN-JUL']") == ["JAN-FEB", "JUN-JUL"]
    assert _parse_list(None) == []
    assert _parse_list("") == []
    assert _parse_list("not a list") == []
    assert _parse_list([10, 20]) == [10, 20]  # already a list passes through


# ------------------------------------------------------- empty / degraded DB

def test_empty_db_is_graceful(conn):
    p = build_opt_payload(conn)
    assert p["counties"] == {}
    assert p["uses"] == [] and p["coverages"] == []
    assert p["min_win"] is None and p["max_win"] is None
    assert p["min_net"] is None and p["max_net"] is None
    assert p["row_count"] == 0 and p["mapping_rows"] == 0
    assert p["county_count"] == 0 and p["unmatched_grids"] == 0
    assert "generated" in p


def test_missing_tables_are_graceful():
    conn = sqlite3.connect(":memory:")  # no schema at all
    conn.row_factory = sqlite3.Row
    p = build_opt_payload(conn)
    assert p["counties"] == {} and p["row_count"] == 0
    conn.close()


def test_partial_swept_grid_without_county_mapping(conn):
    # Sweep row landed before its grid->county mapping: counted, not shaded.
    _opt(conn, 27663, win=0.84, win_combo=["JUN-JUL", "AUG-SEP"],
         win_props=[50, 50], win_net=0.10, net=0.12)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["row_count"] == 1
    assert p["counties"] == {}
    assert p["unmatched_grids"] == 1
    # axes still reflect the data present
    assert p["uses"] == ["Grazing"] and p["coverages"] == ["0.9"]


# --------------------------------------------------------------- aggregation

def test_multi_grid_county_takes_best_per_metric(conn):
    # County 53047 touches grids 100 and 200. Grid 200 wins on win rate,
    # grid 100 wins on net — the county takes the best of each INDEPENDENTLY.
    _grid_county(conn, 100, "53047", "Okanogan")
    _grid_county(conn, 200, "53047", "Okanogan")
    _opt(conn, 100, win=0.60, win_combo=["JAN-FEB", "MAY-JUN"], win_props=[40, 60],
         win_net=0.02, net=0.15, net_combo=["JUL-AUG", "SEP-OCT"],
         net_props=[60, 40], net_win=0.55)
    _opt(conn, 200, win=0.80, win_combo=["JUN-JUL", "AUG-SEP"], win_props=[50, 50],
         win_net=0.05, net=0.07, net_combo=["JUN-JUL", "OCT-NOV"],
         net_props=[55, 45], net_win=0.70)
    conn.commit()
    p = build_opt_payload(conn)
    cell = p["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["win"] == 0.80          # from grid 200
    assert cell["net"] == 0.15          # from grid 100
    assert len(cell["grids"]) == 2
    # detail sorted best-win-rate first
    assert cell["grids"][0]["grid"] == 200
    assert cell["grids"][0]["win_combo"] == ["JUN-JUL", "AUG-SEP"]
    assert cell["grids"][0]["win_props"] == [50, 50]
    assert cell["grids"][1]["net_combo"] == ["JUL-AUG", "SEP-OCT"]
    assert cell["grids"][1]["net_win"] == 0.55


def test_grid_spanning_two_counties_serves_both(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _grid_county(conn, 100, "53007", "Chelan")
    _opt(conn, 100, win=0.7, net=0.09)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["counties"]["53047"]["Grazing"]["0.9"]["win"] == 0.7
    assert p["counties"]["53007"]["Grazing"]["0.9"]["win"] == 0.7
    assert p["county_count"] == 2
    assert p["county_names"] == {"53047": "Okanogan", "53007": "Chelan"}


def test_null_metric_left_none_other_kept(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=None, net=0.04)
    conn.commit()
    cell = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["win"] is None and cell["net"] == 0.04


def test_min_max_over_aggregated_county_values(conn):
    # County A: grids 1 (win .5) + 2 (win .9) -> aggregated .9;
    # County B: grid 3 (win .3). Domain must be over AGGREGATED values,
    # so min_win = .3 (county B), max_win = .9 — grid 1's .5 is not the min.
    _grid_county(conn, 1, "53047", "Okanogan")
    _grid_county(conn, 2, "53047", "Okanogan")
    _grid_county(conn, 3, "30001", "Beaverhead", state="MT")
    _opt(conn, 1, win=0.5, net=0.02)
    _opt(conn, 2, win=0.9, net=0.10)
    _opt(conn, 3, win=0.3, net=-0.04)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["min_win"] == 0.3 and p["max_win"] == 0.9
    assert p["min_net"] == -0.04 and p["max_net"] == 0.10


def test_uses_and_coverages_axes(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, use="Grazing", cov=0.9, win=0.7, net=0.05)
    _opt(conn, 100, use="Haying", cov=0.9, win=0.6, net=0.03)
    _opt(conn, 100, use="Grazing", cov=0.85, win=0.65, net=0.04)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["uses"] == ["Grazing", "Haying"]
    assert p["coverages"] == ["0.85", "0.9"]  # numeric ascending, string keys
    g = p["counties"]["53047"]
    assert g["Grazing"]["0.9"]["win"] == 0.7
    assert g["Grazing"]["0.85"]["win"] == 0.65
    assert g["Haying"]["0.9"]["win"] == 0.6


def test_two_coverages_keyed_independently(conn):
    # Same grid swept at two coverage levels: values must NOT bleed across
    # coverage keys, and both keys must be present for the client control.
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, cov=0.90, win=0.80, net=0.10,
         win_combo=["JUN-JUL", "AUG-SEP"], win_props=[50, 50])
    _opt(conn, 100, cov=0.70, win=0.40, net=-0.02,
         win_combo=["JAN-FEB", "NOV-DEC"], win_props=[60, 40])
    conn.commit()
    p = build_opt_payload(conn)
    assert p["coverages"] == ["0.7", "0.9"]
    cell90 = p["counties"]["53047"]["Grazing"]["0.9"]
    cell70 = p["counties"]["53047"]["Grazing"]["0.7"]
    assert cell90["win"] == 0.80 and cell70["win"] == 0.40
    assert cell90["grids"][0]["win_combo"] == ["JUN-JUL", "AUG-SEP"]
    assert cell70["grids"][0]["win_combo"] == ["JAN-FEB", "NOV-DEC"]
    # domain spans both coverages
    assert p["min_win"] == 0.40 and p["max_win"] == 0.80
    assert p["min_net"] == -0.02 and p["max_net"] == 0.10


def test_fips_zero_padded_in_mapping(conn):
    _grid_county(conn, 100, "9001", "Hartford", state="CT")
    _opt(conn, 100, win=0.5, net=0.01)
    conn.commit()
    p = build_opt_payload(conn)
    assert "09001" in p["counties"]


def test_python_repr_combos_from_db(conn):
    # Combos stored as Python reprs (single quotes) still parse.
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=0.7, net=0.05,
         win_combo="['JUN-JUL', 'AUG-SEP']", win_props="[50, 50]")
    conn.commit()
    d = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]["grids"][0]
    assert d["win_combo"] == ["JUN-JUL", "AUG-SEP"]
    assert d["win_props"] == [50, 50]


# --------------------------------------------------------------------- html

def test_render_embeds_payload_and_assets(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=0.7, net=0.05)
    conn.commit()
    p = build_opt_payload(conn)
    html = render_opt_html(p, d3_js="var d3js=1;", topojson_js="var tj=1;",
                           atlas={"objects": {}})
    assert "var d3js=1;" in html and "var tj=1;" in html
    assert '"53047"' in html
    assert "__PAYLOAD__" not in html and "__ATLAS__" not in html
    assert "PRF Optimizer" in html


def test_render_rejects_script_closing_assets(conn):
    p = build_opt_payload(conn)
    with pytest.raises(ValueError):
        render_opt_html(p, d3_js="</script><script>evil()", topojson_js="",
                        atlas={})
