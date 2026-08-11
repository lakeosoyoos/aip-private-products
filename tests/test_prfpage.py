"""Tests for the merged PRF page (src/prfpage.py).

Replaces tests/test_prfmap.py + tests/test_prfoptmap.py, which covered the two
payload builders when PRF was two separate tabs. Every case they asserted is
carried over (re-keyed onto the shared use axis where the shape changed), plus
the new merge behaviour: the use mapping, the composed payload, and the
per-acre metric's inputs.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from pathlib import Path

from src import db
from src.prfpage import (
    _cov_key, _fips5, _parse_list, build_cbv_payload, build_opt_payload,
    build_prf_page_payload, load_aip_commission, render_prf_page_html, use_key,
)


def grids_of(payload: dict, cell: dict) -> list[dict]:
    """Resolve a county cell's grid references back to full detail dicts.

    build_opt_payload stores each grid's detail ONCE in payload["grid_detail"]
    and references it by index (a grid serves ~2.3 counties, so inlining
    duplicated the whole sweep). This is what the page's JS does to build a
    tooltip; tests read through it so they assert what the user actually sees.
    """
    return [payload["grid_detail"][i] for i in cell["g"]]


def policy_of(payload: dict, ix: int):
    """[interval codes, % allocations] for an interned policy index (-1 -> None)."""
    return None if ix is None or ix < 0 else payload["policies"][ix]


def _cbv(conn, **kw):
    cols = ("year", "state", "county_fips", "county_name", "intended_use",
            "irrigation_practice", "organic_practice", "county_base_value", "source")
    conn.execute(
        "INSERT INTO prf_county (year, state, county_fips, county_name, intended_use, "
        "irrigation_practice, organic_practice, county_base_value, source) "
        "VALUES (?,?,?,?,?,?,?,?,?)", tuple(kw.get(c) for c in cols))


def _grid_county(conn, grid_id, county_fips, county_name="X", state="WA"):
    conn.execute(
        "INSERT INTO prf_grid_county (grid_id, state, county_fips, county_name, source) "
        "VALUES (?,?,?,?,?)", (grid_id, state, county_fips, county_name, "synthetic"))


def _opt(conn, grid_id, use="Grazing", cov=0.9, *, max_pct=60, win=None, win_combo=None,
         win_props=None, win_net=None, net=None, net_combo=None, net_props=None,
         net_win=None, median_net=None, pct_positive=None,
         win_rate_sum=None, net_rate_sum=None):
    conn.execute(
        "INSERT INTO prf_opt_best (grid_id, intended_use, coverage_level, max_pct, year_min, "
        "year_max, n_policies, best_win_rate, best_win_combo, best_win_props, "
        "best_win_avg_net, best_net, best_net_combo, best_net_props, "
        "best_net_win_rate, median_net, pct_positive, best_win_rate_sum, "
        "best_net_rate_sum, top_json, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (grid_id, use, cov, max_pct, 2006, 2025, 59536, win,
         json.dumps(win_combo) if isinstance(win_combo, list) else win_combo,
         json.dumps(win_props) if isinstance(win_props, list) else win_props,
         win_net, net,
         json.dumps(net_combo) if isinstance(net_combo, list) else net_combo,
         json.dumps(net_props) if isinstance(net_props, list) else net_props,
         net_win, median_net, pct_positive, win_rate_sum, net_rate_sum,
         None, "synthetic", "2026-08-05"))


def _write_commission(tmp_path, rows, comments=True):
    """A stand-in data/seed/aip_commission.csv. `rows` are (code, name, pct, notes)."""
    p = tmp_path / "aip_commission.csv"
    lines = ["# hand-maintained; commission_pct is a percent of TOTAL premium"] if comments else []
    lines.append("aip_code,aip_name,commission_pct,notes")
    lines += [",".join("" if v is None else str(v) for v in r) for r in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()


# ------------------------------------------------------------------ helpers

def test_use_key_joins_the_two_cbv_dimensions_to_the_optimizer_vocabulary():
    # The whole merge rests on this: prf_county's (use, practice) pair collapses
    # onto prf_opt_best's single intended_use value.
    assert use_key("Grazing", "Non-Irrigated") == "Grazing"
    assert use_key("Haying", "Non-Irrigated") == "Haying"
    assert use_key("Haying", "Irrigated") == "Haying-Irrigated"
    # tolerant of label punctuation/casing variants seen in ADM extracts
    assert use_key("Haying", "irrigated") == "Haying-Irrigated"
    assert use_key("Grazing", "Non Irrigated") == "Grazing"
    assert use_key(" Grazing ", None) == "Grazing"
    # a combination the map has never seen gets its own key, not silently merged
    assert use_key("Grazing", "Irrigated") == "Grazing-Irrigated"


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


# ------------------------------------------------------------- CBV payload

@pytest.fixture
def cbv_populated(conn):
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=12.50, source="synthetic")
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Haying", irrigation_practice="Irrigated",
         organic_practice="Conventional", county_base_value=85.00, source="synthetic")
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Haying", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=40.00, source="synthetic")
    _cbv(conn, year=2026, state="MT", county_fips="30001", county_name="Beaverhead",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=7.25, source="synthetic")
    conn.commit()
    return conn


def test_cbv_empty_db_is_graceful(conn):
    p = build_cbv_payload(conn)
    assert p["counties"] == {}
    assert p["uses"] == [] and p["organics"] == [] and p["years"] == []
    assert p["min"] is None and p["max"] is None
    assert p["row_count"] == 0 and p["value_count"] == 0


def test_cbv_missing_table_is_graceful():
    conn = sqlite3.connect(":memory:")  # no schema at all
    conn.row_factory = sqlite3.Row
    p = build_cbv_payload(conn)
    assert p["counties"] == {} and p["min"] is None
    conn.close()


def test_cbv_payload_shape_is_keyed_by_use_key(cbv_populated):
    p = build_cbv_payload(cbv_populated)
    # county_fips -> use_key -> organic -> year -> cbv (practice folded into the key)
    ok = p["counties"]["53047"]
    assert ok["Grazing"]["Conventional"][2026] == 12.50
    assert ok["Haying-Irrigated"]["Conventional"][2026] == 85.00
    assert ok["Haying"]["Conventional"][2026] == 40.00
    assert p["counties"]["30001"]["Grazing"]["Conventional"][2026] == 7.25


def test_cbv_axes_names_and_use_map(cbv_populated):
    p = build_cbv_payload(cbv_populated)
    assert p["uses"] == ["Grazing", "Haying", "Haying-Irrigated"]
    assert p["use_map"]["Haying-Irrigated"] == {
        "intended_use": "Haying", "irrigation_practice": "Irrigated"}
    assert p["use_map"]["Grazing"] == {
        "intended_use": "Grazing", "irrigation_practice": "Non-Irrigated"}
    assert p["organics"] == ["Conventional"]
    assert p["years"] == [2026]
    assert p["county_names"]["53047"] == "Okanogan"
    assert p["county_names"]["30001"] == "Beaverhead"


def test_cbv_min_max_over_values(cbv_populated):
    p = build_cbv_payload(cbv_populated)
    assert p["min"] == 7.25 and p["max"] == 85.00
    assert p["value_count"] == 4


def test_cbv_fips_zero_padded(conn):
    _cbv(conn, year=2026, state="CT", county_fips="9001", county_name="Hartford",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=30.0, source="synthetic")
    conn.commit()
    assert "09001" in build_cbv_payload(conn)["counties"]


def test_cbv_null_value_keeps_axis_but_no_value(conn):
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Haying", irrigation_practice="Irrigated",
         organic_practice="Conventional", county_base_value=None, source="synthetic")
    conn.commit()
    p = build_cbv_payload(conn)
    assert p["uses"] == ["Haying-Irrigated"]
    assert p["value_count"] == 0
    assert p["counties"] == {}      # nothing shadable
    assert p["min"] is None


def test_cbv_multiple_years(conn):
    _cbv(conn, year=2025, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=10.0, source="synthetic")
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=13.0, source="synthetic")
    conn.commit()
    p = build_cbv_payload(conn)
    assert p["years"] == [2025, 2026]
    cell = p["counties"]["53047"]["Grazing"]["Conventional"]
    assert cell[2025] == 10.0 and cell[2026] == 13.0


def test_cbv_organics_are_tracked_per_use(conn):
    # Grazing carries Conventional only; Haying also carries Organic. The page
    # rebuilds its Organic dropdown per use so no dead combination is offered.
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=12.0, source="synthetic")
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Haying", irrigation_practice="Non-Irrigated",
         organic_practice="Organic", county_base_value=60.0, source="synthetic")
    conn.commit()
    p = build_cbv_payload(conn)
    assert p["organics"] == ["Conventional", "Organic"]
    assert p["organics_by_use"] == {"Grazing": ["Conventional"], "Haying": ["Organic"]}


# ------------------------------------------------------- optimizer payload

def test_opt_empty_db_is_graceful(conn):
    p = build_opt_payload(conn)
    assert p["counties"] == {}
    assert p["uses"] == [] and p["coverages"] == []
    assert p["min_win"] is None and p["max_win"] is None
    assert p["min_net"] is None and p["max_net"] is None
    assert p["row_count"] == 0 and p["mapping_rows"] == 0
    assert p["county_count"] == 0 and p["unmatched_grids"] == 0


def test_opt_missing_tables_are_graceful():
    conn = sqlite3.connect(":memory:")  # no schema at all
    conn.row_factory = sqlite3.Row
    p = build_opt_payload(conn)
    assert p["counties"] == {} and p["row_count"] == 0
    conn.close()


def test_opt_partial_swept_grid_without_county_mapping(conn):
    # Sweep row landed before its grid->county mapping: counted, not shaded.
    _opt(conn, 27663, win=0.84, win_combo=["JUN-JUL", "AUG-SEP"],
         win_props=[50, 50], win_net=0.10, net=0.12)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["row_count"] == 1
    assert p["counties"] == {}
    assert p["unmatched_grids"] == 1
    assert p["uses"] == ["Grazing"] and p["coverages"] == ["0.9"]


def test_opt_multi_grid_county_takes_best_per_metric(conn):
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
    g = grids_of(p, cell)
    assert len(g) == 2
    # detail sorted best-win-rate first
    assert g[0]["grid"] == 200
    assert policy_of(p, g[0]["wp"]) == [["JUN-JUL", "AUG-SEP"], [50, 50]]
    assert policy_of(p, g[1]["np"]) == [["JUL-AUG", "SEP-OCT"], [60, 40]]
    assert g[1]["net_win"] == 0.55


def test_opt_grid_spanning_two_counties_serves_both(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _grid_county(conn, 100, "53007", "Chelan")
    _opt(conn, 100, win=0.7, net=0.09)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["counties"]["53047"]["Grazing"]["0.9"]["win"] == 0.7
    assert p["counties"]["53007"]["Grazing"]["0.9"]["win"] == 0.7
    assert p["county_count"] == 2
    assert p["county_names"] == {"53047": "Okanogan", "53007": "Chelan"}


def test_opt_null_metric_left_none_other_kept(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=None, net=0.04)
    conn.commit()
    cell = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["win"] is None and cell["net"] == 0.04


def test_opt_min_max_over_aggregated_county_values(conn):
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


def test_opt_uses_and_coverages_axes(conn):
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


def test_opt_two_coverages_keyed_independently(conn):
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
    assert policy_of(p, grids_of(p, cell90)[0]["wp"]) == [["JUN-JUL", "AUG-SEP"], [50, 50]]
    assert policy_of(p, grids_of(p, cell70)[0]["wp"]) == [["JAN-FEB", "NOV-DEC"], [60, 40]]
    assert p["min_win"] == 0.40 and p["max_win"] == 0.80
    assert p["min_net"] == -0.02 and p["max_net"] == 0.10


def test_opt_fips_zero_padded_in_mapping(conn):
    _grid_county(conn, 100, "9001", "Hartford", state="CT")
    _opt(conn, 100, win=0.5, net=0.01)
    conn.commit()
    assert "09001" in build_opt_payload(conn)["counties"]


def test_opt_python_repr_combos_from_db(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=0.7, net=0.05,
         win_combo="['JUN-JUL', 'AUG-SEP']", win_props="[50, 50]")
    conn.commit()
    p = build_opt_payload(conn)
    d = grids_of(p, p["counties"]["53047"]["Grazing"]["0.9"])[0]
    assert policy_of(p, d["wp"]) == [["JUN-JUL", "AUG-SEP"], [50, 50]]
    assert policy_of(p, d["np"]) is None      # no net combo stored -> -1


def test_opt_grid_detail_stored_once_and_policies_interned(conn):
    # Grid 100 serves two counties and both coverages share one allocation:
    # 2 sweep rows -> 2 detail records (not 4), 1 interned policy (not 4).
    _grid_county(conn, 100, "53047", "Okanogan")
    _grid_county(conn, 100, "53007", "Chelan")
    _opt(conn, 100, cov=0.9, win=0.8, net=0.10,
         win_combo=["JUN-JUL", "AUG-SEP"], win_props=[50, 50],
         net_combo=["JUN-JUL", "AUG-SEP"], net_props=[50, 50])
    _opt(conn, 100, cov=0.7, win=0.4, net=0.02,
         win_combo=["JUN-JUL", "AUG-SEP"], win_props=[50, 50],
         net_combo=["JUN-JUL", "AUG-SEP"], net_props=[50, 50])
    conn.commit()
    p = build_opt_payload(conn)
    assert len(p["grid_detail"]) == 2
    assert p["policies"] == [[["JUN-JUL", "AUG-SEP"], [50, 50]]]
    # both counties reference the SAME detail record for a given coverage
    a = p["counties"]["53047"]["Grazing"]["0.9"]["g"]
    b = p["counties"]["53007"]["Grazing"]["0.9"]["g"]
    assert a == b and len(a) == 1
    assert grids_of(p, p["counties"]["53047"]["Grazing"]["0.7"])[0]["win"] == 0.4


def test_opt_metrics_rounded_below_display_precision(conn):
    # The sweep's full float repr costs ~12 bytes/value across ~200k rows; the
    # page shows win to 0.1% and net to $0.001, so rounding changes nothing
    # visible. Assert the rounding actually happens and stays well inside that.
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, win=0.42105263157894735, net=0.33313671111111115)
    conn.commit()
    p = build_opt_payload(conn)
    d = grids_of(p, p["counties"]["53047"]["Grazing"]["0.9"])[0]
    assert d["win"] == 0.4211 and d["net"] == 0.33314
    assert abs(d["win"] - 0.42105263157894735) < 5e-5
    assert abs(d["net"] - 0.33313671111111115) < 5e-6


def test_opt_intended_use_already_uses_the_shared_key(conn):
    _grid_county(conn, 100, "53047", "Okanogan")
    _opt(conn, 100, use="Haying-Irrigated", win=0.7, net=0.05)
    conn.commit()
    p = build_opt_payload(conn)
    assert p["uses"] == ["Haying-Irrigated"]
    assert p["counties"]["53047"]["Haying-Irrigated"]["0.9"]["net"] == 0.05


# ----------------------------------------------------------- merged payload

@pytest.fixture
def merged(conn):
    """Both datasets, deliberately overlapping on 53047 but not on every use."""
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=12.50, source="synthetic")
    _cbv(conn, year=2026, state="WA", county_fips="53047", county_name="Okanogan",
         intended_use="Haying", irrigation_practice="Irrigated",
         organic_practice="Conventional", county_base_value=200.00, source="synthetic")
    _cbv(conn, year=2026, state="MT", county_fips="30001", county_name="Beaverhead",
         intended_use="Grazing", irrigation_practice="Non-Irrigated",
         organic_practice="Conventional", county_base_value=7.25, source="synthetic")
    _grid_county(conn, 100, "53047", "Okanogan")
    _grid_county(conn, 100, "30001", "Beaverhead", state="MT")
    for use in ("Grazing", "Haying", "Haying-Irrigated"):
        for cov in (0.7, 0.9):
            _opt(conn, 100, use=use, cov=cov, win=0.7, net=0.10,
                 win_combo=["JUN-JUL", "AUG-SEP"], win_props=[50, 50],
                 net_combo=["JUL-AUG", "SEP-OCT"], net_props=[60, 40], net_win=0.6,
                 win_rate_sum=0.25, net_rate_sum=0.30)
    conn.commit()
    return conn


def test_merged_payload_shares_one_use_axis(merged):
    p = build_prf_page_payload(merged)
    # union of both datasets' use keys — CBV has no "Haying" row here, the
    # sweep does, and both appear (each metric family simply renders neutral
    # where its own dataset has nothing).
    assert p["uses"] == ["Grazing", "Haying", "Haying-Irrigated"]
    assert p["cbv"]["uses"] == ["Grazing", "Haying-Irrigated"]
    assert p["opt"]["uses"] == ["Grazing", "Haying", "Haying-Irrigated"]
    # Same use key indexes both trees for the same county.
    assert p["cbv"]["counties"]["53047"]["Haying-Irrigated"]["Conventional"][2026] == 200.0
    assert p["opt"]["counties"]["53047"]["Haying-Irrigated"]["0.9"]["net"] == 0.10


def test_merged_payload_carries_both_domains_and_names(merged):
    p = build_prf_page_payload(merged)
    assert p["cbv"]["min"] == 7.25 and p["cbv"]["max"] == 200.0
    assert p["opt"]["min_win"] == 0.7 and p["opt"]["max_net"] == 0.10
    assert p["county_names"]["53047"] == "Okanogan"
    assert p["county_names"]["30001"] == "Beaverhead"
    assert p["opt"]["coverages"] == ["0.7", "0.9"]
    assert "generated" in p


def test_merged_payload_declares_the_productivity_election_range(merged):
    p = build_prf_page_payload(merged)
    # RMA allows 60–150%; the page defaults to 100% (a no-op multiplier).
    assert p["prod"] == {"min": 60, "max": 150, "default": 100}
    assert p["default_coverage"] == "0.9"


def test_per_acre_inputs_are_all_present_for_a_county(merged):
    """The four factors of best_net x CBV x coverage x productivity are all
    reachable from the payload with ONE use key — this is what the client
    multiplies, so assert the arithmetic the page will do."""
    p = build_prf_page_payload(merged)
    net = p["opt"]["counties"]["53047"]["Grazing"]["0.9"]["net"]
    cbv = p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026]
    assert net * cbv * 0.90 * 1.00 == pytest.approx(1.125)
    # 150% productivity scales it by exactly 1.5
    assert net * cbv * 0.90 * 1.50 == pytest.approx(1.6875)
    # coverage participates too: same county at 0.70
    net70 = p["opt"]["counties"]["53047"]["Grazing"]["0.7"]["net"]
    assert net70 * cbv * 0.70 * 1.00 == pytest.approx(0.875)


def test_per_acre_needs_both_datasets(merged):
    """A use with a swept grid but no CBV yields no per-acre value — the page
    must render it neutral rather than invent a County Base Value."""
    p = build_prf_page_payload(merged)
    assert "Haying" in p["opt"]["counties"]["53047"]
    assert "Haying" not in p["cbv"]["counties"]["53047"]


def test_merged_empty_db_is_graceful(conn):
    p = build_prf_page_payload(conn)
    assert p["uses"] == []
    assert p["cbv"]["counties"] == {} and p["opt"]["counties"] == {}
    assert p["cbv"]["row_count"] == 0 and p["opt"]["row_count"] == 0
    assert p["county_names"] == {}


def test_merged_missing_tables_are_graceful():
    conn = sqlite3.connect(":memory:")  # no schema at all
    conn.row_factory = sqlite3.Row
    p = build_prf_page_payload(conn)
    assert p["uses"] == [] and p["cbv"]["counties"] == {} and p["opt"]["counties"] == {}
    conn.close()


# --------------------------------------------------------------------- html

def test_render_embeds_payload_and_assets(merged):
    p = build_prf_page_payload(merged)
    html = render_prf_page_html(p, d3_js="var d3js=1;", topojson_js="var tj=1;",
                                atlas={"objects": {}})
    assert "var d3js=1;" in html and "var tj=1;" in html
    assert '"53047"' in html
    assert "__PAYLOAD__" not in html and "__ATLAS__" not in html
    assert "__D3__" not in html and "__TOPOJSON__" not in html


def test_render_offers_all_four_metrics_and_the_shared_controls(merged):
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    # The four producer metrics are no longer static <option> markup — the Show list is
    # built from the LENS map when a lens is chosen — so assert they are OFFERED rather than
    # that they are hardcoded in the HTML.
    for key in ("cbv", "win", "net", "acre"):
        assert f'"{key}"' in html and f"{key}:" in html
    assert 'var LENS = { buy: ["cbv", "win", "net", "acre"]' in html
    assert 'id="mSel"' in html            # the metric dropdown
    assert 'id="lensSeg"' in html         # ...and the lens that fills it
    assert 'id="fUse"' in html            # one intended-use control
    assert 'id="covSeg"' in html          # coverage level
    assert 'id="fOrganic"' in html and 'id="fYear"' in html
    assert 'id="fProd"' in html           # productivity factor
    assert 'min="60"' in html and 'max="150"' in html and 'value="100"' in html
    # dual-thumb slider with value bubbles, readout and reset (prfmap's pattern)
    for el in ('id="rMin"', 'id="rMax"', 'id="rBubbleLo"', 'id="rBubbleHi"',
               'id="rReadout"', 'id="rReset"'):
        assert el in html


def test_render_states_the_per_acre_formula(merged):
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert "best net (per $1 of protection) &times; County Base Value" in html
    assert "coverage level &times; productivity factor" in html


def test_render_is_self_contained_no_network(merged):
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="var d3js=1;", topojson_js="var tj=1;",
                                atlas={"objects": {}})
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html and "<link rel" not in html


def test_render_rejects_script_closing_assets(conn):
    p = build_prf_page_payload(conn)
    with pytest.raises(ValueError):
        render_prf_page_html(p, d3_js="</script><script>evil()", topojson_js="",
                             atlas={})


# ------------------------------------------------- commission rates (seed CSV)

def test_commission_csv_parses_rates_and_skips_comment_lines(tmp_path):
    p = _write_commission(tmp_path, [
        ("NA", "NAU Country Insurance Company", 12.5, "2026 agreement"),
        ("RH", "ACE American (Rain and Hail)", None, ""),
    ])
    c = load_aip_commission(p)
    by_code = {a["code"]: a for a in c["aips"]}
    assert by_code["NA"]["pct"] == 12.5
    assert by_code["NA"]["notes"] == "2026 agreement"
    # BLANK IS NOT ZERO: an unentered rate must stay unknown, or the map would
    # confidently shade every county $0.00/acre and look like a real answer.
    assert by_code["RH"]["pct"] is None
    assert c["with_rate"] == 1 and c["row_count"] == 2
    assert c["path"] == str(p)


def test_commission_csv_all_blank_is_the_shipped_state(tmp_path):
    p = _write_commission(tmp_path, [("NA", "NAU", None, ""), ("EF", "RCIS", None, "")])
    c = load_aip_commission(p)
    assert c["row_count"] == 2 and c["with_rate"] == 0
    assert all(a["pct"] is None for a in c["aips"])


def test_commission_csv_rejects_junk_and_out_of_range(tmp_path):
    p = _write_commission(tmp_path, [
        ("A", "Alpha", "tbd", ""),      # not a number
        ("B", "Bravo", -5, ""),         # negative share of premium
        ("C", "Charlie", 150, ""),      # >100% of premium
        ("D", "Delta", "12.5%", ""),    # a human typed the % sign
        ("E", "Echo", 0, ""),           # a genuine, deliberate zero
    ])
    by_code = {a["code"]: a for a in load_aip_commission(p)["aips"]}
    assert by_code["A"]["pct"] is None
    assert by_code["B"]["pct"] is None
    assert by_code["C"]["pct"] is None
    assert by_code["D"]["pct"] == 12.5
    assert by_code["E"]["pct"] == 0.0   # entered zero IS a rate; blank is not


def test_commission_csv_missing_file_is_graceful(tmp_path):
    c = load_aip_commission(tmp_path / "nope.csv")
    assert c["aips"] == [] and c["with_rate"] == 0 and c["row_count"] == 0


def test_shipped_seed_rates_are_labelled_as_a_regulatory_CEILING():
    """The committed file lists AIPs, and every rate it carries is labelled for what it is.

    This guard has moved twice, and the reason is the same each time: a plausible unlabelled
    rate is indistinguishable from a negotiated one and would be quoted to a producer as real.
    First it forbade committing any rate at all. Then it allowed rates that were marked SAMPLE.
    The file now ships neither — it ships the SRA compensation CEILING, 80% of A&O, which is
    documented and citable but is an UPPER BOUND rather than an estimate of what the agency
    earns. So the label it must carry is that one.
    """
    c = load_aip_commission()
    assert c["row_count"] >= 10
    assert c["path"] == "data/seed/aip_commission.csv"

    raw = (Path(__file__).resolve().parents[1] / "data/seed/aip_commission.csv").read_text()
    up = raw.upper()
    assert "CEILING" in up or "UPPER BOUND" in up, "shipped rates must be marked as a ceiling"
    assert "80 PERCENT" in up or "80%" in up, "the cap's basis must be stated"
    assert "III(A)(4)(B)" in up, "cite the SRA provision the number comes from"
    # and every rated AIP still carries a note saying where its number came from
    for a in c["aips"]:
        if a["by_region"] or a["pct"] is not None:
            assert a["notes"], f"{a['code']} carries a rate with no provenance note"


def test_the_rate_table_is_still_per_AIP_and_per_region(tmp_path):
    """A rate is a cell in an AIP x region x product table, not a property of any one axis.

    The SHIPPED card is uniform across AIPs and regions, because a regulatory ceiling does not
    vary by either — so asserting variation in the shipped file would now be asserting that
    the ceiling is wrong. What must still hold is that the MECHANISM carries variation, since
    the whole point of the file is that an agency replaces the ceiling with its real,
    negotiated, per-AIP and per-region card.
    """
    c = load_aip_commission()
    assert c["regions"], "no region columns parsed from the seed CSV"
    assert [a for a in c["aips"] if a["by_region"]], "no AIP carries a per-region rate"

    csv_path = tmp_path / "real.csv"
    csv_path.write_text(
        "aip_code,aip_name,product,Pacific,Mountain,Central,Eastern,notes\n"
        "A1,Alpha,PRF,20,18,16,14,negotiated\n"
        "B2,Beta,PRF,19,17,15,13,negotiated\n")
    got = load_aip_commission(str(csv_path), product="PRF")
    rated = [a for a in got["aips"] if a["by_region"]]
    assert len(rated) == 2
    # varies WITHIN an AIP across regions...
    assert all(len(set(a["by_region"].values())) > 1 for a in rated)
    # ...and BETWEEN AIPs in the same region
    assert len({a["by_region"]["Pacific"] for a in rated}) == 2


def test_rate_sum_travels_with_the_best_net_grid(conn):
    """The county's premium must come from the SAME grid that won on net.

    A county spanning grids takes the best net; commission is the commission on
    THAT policy, so pairing the winning net with another grid's premium would
    price a policy nobody is being recommended.
    """
    _grid_county(conn, 1, "53047")
    _grid_county(conn, 2, "53047")
    _opt(conn, 1, net=0.05, net_rate_sum=0.90, win=0.4)   # expensive, poorer net
    _opt(conn, 2, net=0.20, net_rate_sum=0.10, win=0.9)   # cheap, better net
    conn.commit()
    cell = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["net"] == 0.20
    assert cell["nrs"] == 0.10           # grid 2's rate, not grid 1's, and not the max
    assert build_opt_payload(conn)["grid_detail"][cell["ni"]]["grid"] == 2


def test_rate_sum_null_when_the_sweep_never_stored_one(conn):
    _grid_county(conn, 1, "53047")
    _opt(conn, 1, net=0.20, net_rate_sum=None)
    conn.commit()
    cell = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["nrs"] is None           # never 0 — a missing rate is not a free policy


def test_rate_sum_column_absent_is_graceful():
    """A catalog.db predating the rate-sum columns must still render."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE prf_opt_best (grid_id INTEGER, intended_use TEXT, "
        "coverage_level REAL, best_win_rate REAL, best_win_combo TEXT, "
        "best_win_props TEXT, best_win_avg_net REAL, best_net REAL, "
        "best_net_combo TEXT, best_net_props TEXT, best_net_win_rate REAL)")
    conn.execute("CREATE TABLE prf_grid_county (grid_id INTEGER, state TEXT, "
                 "county_fips TEXT, county_name TEXT, source TEXT)")
    conn.execute("INSERT INTO prf_grid_county VALUES (1,'WA','53047','Okanogan','x')")
    # NO max_pct here on purpose: this table is the LEGACY shape, and the point of the
    # test is that a catalog.db predating a column still renders. Named columns rather
    # than positional, so the row cannot silently re-align if the shape changes again.
    conn.execute("INSERT INTO prf_opt_best (grid_id, intended_use, coverage_level, "
                 "best_win_rate, best_win_combo, best_win_props, best_win_avg_net, "
                 "best_net, best_net_combo, best_net_props, best_net_win_rate) "
                 "VALUES (1,'Grazing',0.9,0.5,'[]','[]',0,0.2,"
                 "'[\"JUL-AUG\"]','[100]',0.4)")
    conn.commit()
    cell = build_opt_payload(conn)["counties"]["53047"]["Grazing"]["0.9"]
    assert cell["net"] == 0.2 and cell["nrs"] is None
    conn.close()


# --------------------------------------------------- commission arithmetic

def commission_per_acre(cbv, coverage, productivity, rate_sum, pct):
    """The page's client-side formula, mirrored so the test asserts the arithmetic.

        protection/acre = CBV x coverage x productivity
        premium/acre    = protection/acre x SUM(allocation x rate)
        commission/acre = premium/acre x pct/100
    """
    if cbv is None or rate_sum is None or pct is None:
        return None
    return cbv * coverage * productivity * rate_sum * pct / 100.0


def test_commission_arithmetic_is_a_percent_of_total_premium(merged):
    p = build_prf_page_payload(merged)
    cell = p["opt"]["counties"]["53047"]["Grazing"]["0.9"]
    cbv = p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026]
    assert (cbv, cell["nrs"]) == (12.50, 0.30)
    # protection 12.50 x 0.90 x 1.00 = 11.25/ac; premium 11.25 x 0.30 = 3.375/ac
    assert cbv * 0.90 * 1.00 * cell["nrs"] == pytest.approx(3.375)
    # commission at 12.5% of TOTAL premium (subsidised portion included)
    assert commission_per_acre(cbv, 0.90, 1.00, cell["nrs"], 12.5) == pytest.approx(0.421875)


def test_commission_scales_linearly_with_the_rate(merged):
    """Doubling the commission rate doubles commission per acre — nothing else moves."""
    p = build_prf_page_payload(merged)
    cell = p["opt"]["counties"]["53047"]["Grazing"]["0.9"]
    cbv = p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026]
    one = commission_per_acre(cbv, 0.90, 1.00, cell["nrs"], 10.0)
    two = commission_per_acre(cbv, 0.90, 1.00, cell["nrs"], 20.0)
    assert two == pytest.approx(2 * one)


def test_commission_tracks_coverage_and_productivity(merged):
    p = build_prf_page_payload(merged)
    g = p["opt"]["counties"]["53047"]["Grazing"]
    cbv = p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026]
    base = commission_per_acre(cbv, 0.90, 1.00, g["0.9"]["nrs"], 12.5)
    assert commission_per_acre(cbv, 0.90, 1.50, g["0.9"]["nrs"], 12.5) == pytest.approx(1.5 * base)
    # coverage enters BOTH the protection and (via its own rate row) the stored rate-sum;
    # here the fixture uses the same rate-sum, so only the protection factor moves.
    assert commission_per_acre(cbv, 0.70, 1.00, g["0.7"]["nrs"], 12.5) == pytest.approx(
        base * 0.70 / 0.90)


def test_commission_is_none_without_a_rate_a_cbv_or_a_premium(merged):
    p = build_prf_page_payload(merged)
    cell = p["opt"]["counties"]["53047"]["Grazing"]["0.9"]
    cbv = p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026]
    assert commission_per_acre(cbv, 0.90, 1.00, cell["nrs"], None) is None   # no AIP rate
    assert commission_per_acre(None, 0.90, 1.00, cell["nrs"], 12.5) is None  # no CBV
    assert commission_per_acre(cbv, 0.90, 1.00, None, 12.5) is None          # no rate-sum


def test_commission_ranks_counties_by_premium_not_by_cbv(conn):
    """The point of the metric: the biggest CBV is not the biggest commission.

    Premium rates vary several-fold between grids, so a modest-CBV county on an
    expensive grid out-earns a high-CBV county on a cheap one.
    """
    for fips, name, cbv, rate in (("53047", "Okanogan", 12.50, 0.90),
                                  ("30001", "Beaverhead", 85.00, 0.05)):
        _cbv(conn, year=2026, state="WA", county_fips=fips, county_name=name,
             intended_use="Grazing", irrigation_practice="Non-Irrigated",
             organic_practice="Conventional", county_base_value=cbv, source="synthetic")
    _grid_county(conn, 1, "53047")
    _grid_county(conn, 2, "30001", state="MT")
    _opt(conn, 1, net=0.1, net_rate_sum=0.90)
    _opt(conn, 2, net=0.1, net_rate_sum=0.05)
    conn.commit()
    p = build_prf_page_payload(conn)

    def comm(fips):
        return commission_per_acre(
            p["cbv"]["counties"][fips]["Grazing"]["Conventional"][2026], 0.90, 1.00,
            p["opt"]["counties"][fips]["Grazing"]["0.9"]["nrs"], 12.5)

    # CBV ranking says Beaverhead ($85) beats Okanogan ($12.50)...
    assert (p["cbv"]["counties"]["30001"]["Grazing"]["Conventional"][2026]
            > p["cbv"]["counties"]["53047"]["Grazing"]["Conventional"][2026])
    # ...but commission ranking reverses it — premium, not CBV, is what commission follows.
    assert comm("53047") > comm("30001")


# ------------------------------------------------- commission in the payload/HTML

def test_merged_payload_carries_the_commission_roster(merged):
    p = build_prf_page_payload(merged)
    assert p["comm"]["path"] == "data/seed/aip_commission.csv"
    # Ships a labelled SAMPLE rate card; see test_shipped_seed_csv_* for the guard that
    # any shipped rate is marked as sample rather than passed off as negotiated.
    assert p["comm"]["with_rate"] >= 0
    assert "commzone" in p and isinstance(p["commzone"]["zones"], dict)
    assert isinstance(p["comm"]["aips"], list)


def test_merged_payload_accepts_a_commission_csv_override(merged, tmp_path):
    p = build_prf_page_payload(
        merged, commission_csv=_write_commission(tmp_path, [("NA", "NAU", 12.5, "")]))
    assert p["comm"]["with_rate"] == 1
    assert p["comm"]["aips"][0]["pct"] == 12.5


def test_render_offers_the_commission_metric_and_its_aip_selector(merged, tmp_path):
    p = build_prf_page_payload(
        merged, commission_csv=_write_commission(tmp_path, [("NA", "NAU", 12.5, "")]))
    html = render_prf_page_html(p, d3_js="", topojson_js="", atlas={})
    assert 'sell: ["comm"]' in html        # the 5th metric, now under the agency lens
    assert 'id="fAip"' in html             # which AIP's rate to apply
    assert "NAU" in html and "12.5" in html
    # the four producer metrics are untouched, just sorted under the other lens
    assert 'buy: ["cbv", "win", "net", "acre"]' in html


def test_render_states_the_commission_formula_and_its_caveats(merged):
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert "premium rate) &times; commission %" in html
    assert "total</b> premium" in html               # not just the producer-paid share
    assert "recommended</b> (best-net) policy" in html
    assert "data/seed/aip_commission.csv" in html    # where to enter the rate
    assert "no commission rates set" in html.lower() # the empty-rates degradation


def test_render_warns_that_use_does_not_move_the_rate_metrics(merged):
    """Switching intended use leaves win-rate / return-per-$1 numerically put on
    effectively every grid (PRF rates key off rainfall, not forage use); without
    a note the control looks broken."""
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert html.count('Intended use does not move this metric') == 2   # win + net
    assert 'data-m="win"' in html and 'data-m="net"' in html


def test_fixed_unit_quantities_never_go_through_the_metric_dependent_formatter(merged):
    """fmtShort() formats according to the SELECTED metric — %, $ per $1, or $/acre. That is
    correct for the value the map is currently showing, and wrong for anything whose unit is
    fixed regardless of selection.

    The grid tooltip printed `fmtShort(gd.win)`. gd.win is a win RATE always, so a 62% win
    rate rendered as "$0.62" under $/acre, $ per $1 and commission, and as "$1" under CBV.
    Nothing looked broken — it looked like a dollar figure, because it was formatted as one.

    Asserted structurally rather than by rendering, because the bug lives in which formatter
    a call site chose, and that is exactly what the source shows.
    """
    import re

    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    for call in re.findall(r"fmtShort\(([^)]*)\)", html):
        arg = call.strip()
        assert not re.search(r"\.(win|net|win_net|net_win)\b", arg), (
            f"fmtShort({arg}) formats a fixed-unit quantity with the selected metric's units; "
            f"use fmtWin/fmtNet"
        )


def test_every_reported_figure_comes_from_one_policy(merged):
    """policyFor() is the single place that decides WHICH stored policy a tooltip is talking
    about, and it returns that policy's win rate, its return and its intervals together.

    That structure is the fix for two separate defects. The grid tooltip printed the best-WIN
    policy's rate next to the best-NET policy's intervals (grid 25032 at 70%: 78.9% shown for
    an allocation that actually wins 47.4%). And neither tooltip followed the metric selector,
    so choosing "Best win rate" still described the net-maximising policy.
    """
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert "function policyFor(gd)" in html
    # the selection decides which policy, not whether one happens to be stored
    assert 'var wantWin = (metric === "win");' in html
    # rate and intervals leave policyFor together, so they cannot be mismatched by a caller
    assert "win:  wantWin ? gd.win : gd.net_win," in html
    assert "pol:  pol," in html
    # and no caller reaches around it for the raw fields
    for bad in ("fmtWin(gd.win)", "comboStr(gd.np", "comboStr(gr.wp)", "comboStr(gr.np)"):
        assert bad not in html, f"{bad} bypasses policyFor and can mispair"


def test_both_win_rate_and_return_are_shown_whichever_metric_is_selected(merged):
    """The selected quantity leads, but both are always present: a win rate without its
    return, or a return without the odds of getting it, is half an answer either way."""
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert "function policyLine(gd, cbv)" in html
    # the SAME phrasing for each quantity in both views — only the order changes, so a
    # reader comparing the two views sees one difference (the policy) and not three
    assert 'var wins = "wins " + fmtWin(p.win) + " of years";' in html
    assert 'var bits = (metric === "win") ? [wins, per1] : [per1, wins];' in html
    assert "fmtAcre(acre)" in html                                      # per-acre in both
    # fmtAcre already ends in "/ac"; appending another gave "$4.43/ac/ac" on the win view
    assert 'fmtAcre(acre) + "/ac"' not in html


def test_the_two_stored_policies_really_do_differ(merged):
    """Guards the premise. If best-win and best-net always coincided the pairing would not
    matter, and this test would be the place that says so."""
    rows = merged.execute(
        "SELECT best_win_rate, best_net_win_rate FROM prf_opt_best "
        "WHERE best_win_rate IS NOT NULL AND best_net_win_rate IS NOT NULL").fetchall()
    if not rows:
        import pytest
        pytest.skip("no swept rows in this fixture")
    differ = sum(1 for w, nw in rows if abs(w - nw) > 1e-9)
    assert differ, "expected the win-maximiser and net-maximiser to differ on some grids"


def test_a_county_gets_the_row_swept_under_its_own_cap(conn):
    """prf_opt_best is keyed by max_pct, so a grid straddling a cap boundary contributes more
    than one row for the same use and coverage. The county must receive the row matching ITS
    cap — otherwise whichever row the loop happens to process last wins, and a 40%-cap county
    can be shown an allocation that is only legal in the 50%-cap county next door.
    """
    _grid_county(conn, 1, "48001", "Anderson", state="TX")
    _grid_county(conn, 1, "48003", "Andrews", state="TX")
    conn.execute("CREATE TABLE IF NOT EXISTS prf_max_pct (state_code TEXT, county_code TEXT, "
                 "max_pct INTEGER)")
    conn.executemany("INSERT INTO prf_max_pct VALUES (?,?,?)",
                     [("48", "001", 40), ("48", "003", 50)])
    # the SAME grid, swept once per cap, with deliberately different winners
    # NOTE a 40% cap forbids a two-interval policy outright: 2 x 40 < 100. The cheapest
    # legal allocation there is three intervals, which is itself a real consequence of the
    # cap and not just test scaffolding.
    _opt(conn, grid_id=1, max_pct=40, net=0.070,
         net_combo=["FEB-MAR", "JUN-JUL", "SEP-OCT"], net_props=[40, 40, 20])
    _opt(conn, grid_id=1, max_pct=50, net=0.099, net_combo=["FEB-MAR", "AUG-SEP"],
         net_props=[50, 50])
    conn.commit()

    payload = build_opt_payload(conn)
    detail = payload["grid_detail"]
    pols = payload["policies"]

    def props_for(fips):
        cell = payload["counties"][fips]["Grazing"]["0.9"]
        d = detail[cell["g"][0]]
        return cell["net"], pols[d["np"]][1]

    assert props_for("48001") == (0.07, [40, 40, 20]), "40%-cap county took the wrong row"
    assert props_for("48003") == (0.099, [50, 50]), "50%-cap county took the wrong row"
    # and neither county sees an allocation exceeding its own cap
    for fips, cap in (("48001", 40), ("48003", 50)):
        cell = payload["counties"][fips]["Grazing"]["0.9"]
        for di in cell["g"]:
            assert max(pols[detail[di]["np"]][1]) <= cap


def test_hover_outlines_what_a_click_would_select(merged):
    """At the nation level a click on a county zooms to its STATE, so outlining the county
    there advertises a selection the click will not make. The outline follows the drill level:
    state at level 0, county at level 1, grid cell at level 2.

    Asserted structurally because the behaviour lives in one expression; it was verified in
    the browser by comparing rendered bounding boxes (nation: 148.5 wide vs the county's 7.9;
    state and grid: exact match).
    """
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert 'showHover(level === 0 ? (stateById[String(d.id).slice(0, 2)] || d) : d);' in html
    # a county with no state feature must still highlight rather than blank out
    assert "|| d)" in html


def test_the_lens_sorts_the_metrics_by_whose_money_they_describe(merged):
    """Four of the five PRF metrics describe the PRODUCER's outcome and one describes the
    AGENCY's, and they sat in a single Show dropdown together. The lens picks the question
    first; the Show list then offers only the metrics that answer it.

    The point of this test is that NOTHING WAS DROPPED in the sort. Every metric the map ever
    offered must appear under exactly one lens.
    """
    import re

    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    m = re.search(r"var LENS = \{ buy: \[([^\]]*)\], sell: \[([^\]]*)\] \}", html)
    assert m, "the lens map must be present"
    buy = re.findall(r'"(\w+)"', m.group(1))
    sell = re.findall(r'"(\w+)"', m.group(2))

    assert buy == ["cbv", "win", "net", "acre"]
    assert sell == ["comm"]
    # every metric is reachable, and none is reachable from both
    assert set(buy) | set(sell) == {"cbv", "win", "net", "acre", "comm"}
    assert not (set(buy) & set(sell))


def test_switching_lens_cannot_strand_the_map_on_a_hidden_metric(merged):
    """Selecting the agency lens while a producer metric is active must move the map to a
    metric that lens actually offers — otherwise the map keeps shading a metric the Show box
    no longer lists, and the legend and the dropdown disagree."""
    html = render_prf_page_html(build_prf_page_payload(merged),
                                d3_js="", topojson_js="", atlas={})
    assert "if (keys.indexOf(metric) < 0) {" in html
    assert "metric = keys[0];" in html


def test_a_commission_rate_is_never_borrowed_from_another_product(tmp_path):
    """Commission is negotiated PER PRODUCT LINE. Livestock (LRP/LGM/DRP) routinely sits on a
    different schedule from MPCI-family business (PRF/ROWCROP), so a rate entered against one
    product must never be returned for another. The failure this prevents is quiet and
    expensive: a map reporting commission the agency does not earn, on a screen someone plans
    a week around.
    """
    from src.prfpage import load_aip_commission

    csv = tmp_path / "rates.csv"
    csv.write_text(
        "aip_code,aip_name,product,Pacific,Mountain,Central,Eastern,notes\n"
        "X1,Test AIP,PRF,20,18,16,14,\n"
        "X1,Test AIP,LRP,9,8,7,6,\n")

    prf = load_aip_commission(str(csv), product="PRF")
    lrp = load_aip_commission(str(csv), product="LRP")
    drp = load_aip_commission(str(csv), product="DRP")   # no rows at all

    assert prf["aips"][0]["by_region"]["Pacific"] == 20
    assert lrp["aips"][0]["by_region"]["Pacific"] == 9
    assert drp["aips"] == [] and drp["with_rate"] == 0, (
        "a product with no rows must come back EMPTY, so the page says 'no rates set' "
        "instead of borrowing another product's card")


def test_every_product_carries_the_same_uniform_ceiling():
    """One rate, every product: 17.52% = 80% x 21.9%, the top of the documented A&O range.

    This is a deliberate simplification over per-plan A&O rates, and it is NOT the same as
    each plan's own ceiling — PRF's own A&O row (area plans not widely available in 2008,
    20.1%) implies 16.08%, and 16% is what an operating agency reports being paid. The uniform
    figure therefore sits ABOVE the real PRF rate. That is the intended direction for a
    ceiling, but the file has to say so rather than let a reader assume 17.52% is earned.
    """
    for prod in ("PRF", "ROWCROP", "LRP", "DRP", "LGM"):
        c = load_aip_commission(product=prod)
        assert c["with_rate"] == len(c["aips"]) > 0, f"{prod} should carry a ceiling"
        for a in c["aips"]:
            assert set(a["by_region"].values()) == {17.52}, (
                f"{prod}/{a['code']} should carry the uniform 17.52% ceiling")
            assert "80%" in a["notes"] and "21.9%" in a["notes"]

    raw = (Path(__file__).resolve().parents[1] / "data/seed/aip_commission.csv").read_text()
    up = raw.upper()
    assert "III(A)(4)(B)" in up, "cite the SRA provision the 80% comes from"
    assert "MAXIMUM" in up or "CEILING" in up
    # the override must be stated, not silent: a reader has to be able to find out that the
    # per-plan rates differ and that PRF's own row is lower
    assert "16.08" in raw, "the PRF-specific rate this overrides must be recorded"
    assert "LPRA" in up, "livestock being unverified must stay on the record"


def test_a_card_with_no_product_column_serves_whoever_asked(tmp_path):
    """A file with no product column makes no claim about products, so an explicit override
    (build_*_page_payload(commission_csv=...)) is honoured for the product that asked. The
    leak the column prevents is in the SHARED default card, which always has one."""
    from src.prfpage import load_aip_commission

    csv = tmp_path / "legacy.csv"
    csv.write_text("aip_code,aip_name,commission_pct\nX1,Test,11.5\n")
    for prod in ("PRF", "LRP"):
        assert load_aip_commission(str(csv), product=prod)["aips"][0]["pct"] == 11.5
