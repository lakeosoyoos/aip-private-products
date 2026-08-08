"""Tests for the DRP page (src/drppage.py) — state-level choropleth. No network.

The DRP map is deliberately NOT a copy of the PRF map, and most of what is asserted here
is the difference: the grain stops at the state (DRP's plan-83 offers all carry county
code 998), the drill-down says so instead of implying a county level, and the protection
factor is a display-time multiplier that must never reach the payload.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src import db
from src.drppage import (
    _cov_key, _f, _fips2, build_drp_page_payload, render_drp_page_html, ring_clockwise,
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    return c


def _best(conn, state_code="55", abbrev="WI", option="Class", quarter=0, cov=0.90, *,
          win=0.20, win_w=0.35, win_net=0.004, win_prem=0.002,
          net=0.006, net_w=0.00, net_win=0.13, net_prem=0.0021, liab=16.5336,
          median=0.0001, pos=0.52, n_obs=30, n_shapes=21, n_pinned=0,
          q0="2019Q1", q1="2026Q2", draw_ry=2026, top=None):
    conn.execute(
        "INSERT INTO drp_opt_best (state_code, state_abbrev, pricing_option, quarter,"
        " coverage_level, quarter_min, quarter_max, n_obs, n_shapes, n_pinned,"
        " best_win_rate, best_win_weight, best_win_net, best_win_prem, best_net,"
        " best_net_weight, best_net_win_rate, best_net_prem, best_net_liability_cwt,"
        " median_net, pct_positive, premium_draw_ry, top_json, source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'synthetic')",
        (state_code, abbrev, option, quarter, cov, q0, q1, n_obs, n_shapes, n_pinned,
         win, win_w, win_net, win_prem, net, net_w, net_win, net_prem, liab,
         median, pos, draw_ry, json.dumps(top or {})))


def _state(conn, state_code="55", abbrev="WI", name="Wisconsin", ry=2026):
    conn.execute(
        "INSERT INTO drp_state (reinsurance_year, state_code, state_abbrev, state_name,"
        " n_quarters, n_pricing_options) VALUES (?,?,?,?,8,2)",
        (ry, state_code, abbrev, name))


@pytest.fixture()
def populated(conn):
    _state(conn, "55", "WI", "Wisconsin")
    _state(conn, "06", "CA", "California")
    _state(conn, "16", "ID", "Idaho")          # offered, but never swept
    for option in ("Class", "Component"):
        for q in (0, 1, 2, 3, 4):
            for cov in (0.80, 0.90):
                _best(conn, "55", "WI", option, q, cov,
                      win=0.10 + 0.01 * q, net=0.001 * (q + 1), liab=16.0 + cov)
                _best(conn, "06", "CA", option, q, cov,
                      win=0.20 + 0.01 * q, net=0.002 * (q + 1), liab=16.0 + cov)
    conn.commit()
    return conn


# --------------------------------------------------------------------- pure

def test_fips2_pads_and_passes_through():
    assert _fips2(6) == "06"
    assert _fips2("6") == "06"
    assert _fips2("55") == "55"
    assert _fips2(None) == ""
    assert _fips2("  ") == ""


def test_cov_key_canonical():
    assert _cov_key(0.9) == _cov_key(0.90) == "0.9"
    assert _cov_key(0.95) == "0.95"
    assert _cov_key("junk") == "junk"


def test_f_rounds_and_refuses_nan():
    assert _f(1.23456, 2) == 1.23
    assert _f(None) is None
    assert _f("x") is None
    # A NaN is a metric that could not be computed, and must not reach the page as 0.
    assert _f(float("nan"), 4) is None


def test_ring_clockwise_reverses_a_counter_clockwise_ring():
    """d3-geo's interior is LEFT of travel, so a CCW ring floods the viewport."""
    ccw = [[-100, 40], [-99, 40], [-99, 41], [-100, 41], [-100, 40]]
    cw = list(reversed(ccw))
    assert ring_clockwise(ccw) == cw
    assert ring_clockwise(cw) == cw          # already clockwise: untouched
    assert ring_clockwise(ring_clockwise(ccw)) == ring_clockwise(ccw)  # idempotent
    assert ring_clockwise([[0, 0], [1, 1]]) == [[0, 0], [1, 1]]        # degenerate


# ------------------------------------------------------------------ payload

def test_empty_db_is_graceful(conn):
    p = build_drp_page_payload(conn)
    assert p["states"] == {} and p["row_count"] == 0 and p["state_count"] == 0
    assert p["min_win"] is None and p["max_net"] is None
    assert p["options"] == ["Class"] and p["quarters"] == ["0"]
    assert p["coverages"] == []
    assert "generated" in p


def test_missing_tables_are_graceful():
    c = sqlite3.connect(":memory:")          # no schema at all
    c.row_factory = sqlite3.Row
    p = build_drp_page_payload(c)
    assert p["states"] == {} and p["avail"] == {} and p["row_count"] == 0
    c.close()


def test_payload_is_keyed_state_option_quarter_coverage(populated):
    p = build_drp_page_payload(populated)
    cell = p["states"]["55"]["Class"]["0"]["0.9"]
    assert cell["win"] == pytest.approx(0.10)
    assert cell["net"] == pytest.approx(0.001)
    assert cell["liab"] == pytest.approx(16.9)
    assert cell["n"] == 30 and cell["sh"] == 21 and cell["pin"] == 0
    assert cell["q0"] == "2019Q1" and cell["q1"] == "2026Q2" and cell["dry"] == 2026
    assert p["state_count"] == 2
    assert p["row_count"] == 2 * 2 * 5 * 2


def test_axes_are_sorted_with_the_pooled_quarter_first(populated):
    p = build_drp_page_payload(populated)
    assert p["options"] == ["Class", "Component"]
    assert p["quarters"] == ["0", "1", "2", "3", "4"]
    assert p["coverages"] == ["0.8", "0.9"]
    assert p["quarter_labels"]["0"] == "All quarters"
    assert p["quarter_labels"]["3"] == "Jul–Sep"


def test_global_metric_domains_cover_every_stored_value(populated):
    p = build_drp_page_payload(populated)
    assert p["min_win"] == pytest.approx(0.10)
    assert p["max_win"] == pytest.approx(0.24)
    assert p["min_net"] == pytest.approx(0.001)
    assert p["max_net"] == pytest.approx(0.010)


def test_state_codes_are_zero_padded(conn):
    _best(conn, state_code="6", abbrev="CA")
    conn.commit()
    assert "06" in build_drp_page_payload(conn)["states"]


def test_availability_distinguishes_unswept_from_unoffered(populated):
    """A state DRP is sold in but the sweep has not reached is not 'not offered'."""
    p = build_drp_page_payload(populated)
    assert "16" in p["avail"] and p["avail"]["16"]["ab"] == "ID"
    assert p["avail"]["16"] == {"q": 8, "o": 2, "ab": "ID"}
    assert "16" not in p["states"]           # offered, never scored
    assert p["state_names"]["16"] == "Idaho"
    assert p["avail_ry"] == 2026


def test_availability_uses_the_newest_reinsurance_year(conn):
    _state(conn, "55", "WI", "Wisconsin", ry=2025)
    _state(conn, "55", "WI", "Wisconsin", ry=2027)
    _state(conn, "06", "CA", "California", ry=2025)   # dropped in the newest year
    conn.commit()
    p = build_drp_page_payload(conn)
    assert p["avail_ry"] == 2027
    assert set(p["avail"]) == {"55"}


def test_payload_carries_no_protection_factor_only_the_election_range(populated):
    """PF collapses out of every stored metric, so it must not be baked into one.

    Storing a PF-scaled value would be storing the same map eleven times over, and would
    quietly contradict src/drpopt.py's whole normalization. The page multiplies at
    display time; the payload ships only the range of the election.
    """
    p = build_drp_page_payload(populated)
    cell = p["states"]["55"]["Class"]["0"]["0.9"]
    assert "pf" not in cell and "protection" not in cell
    assert set(cell) == {"win", "net", "prem", "liab", "nw", "ww", "wnet", "nwin",
                         "med", "pos", "n", "pin", "sh", "dry", "q0", "q1"}
    assert p["decl"]["pf_min"] == 1.00 and p["decl"]["pf_max"] == 1.50
    assert p["decl"]["pf"] == 1.00       # a no-op multiplier by default
    assert p["decl"]["share"] == 100


def test_the_dollar_formula_inputs_are_all_reachable(populated):
    """$/cwt = best net (per $1 of liability) x liability/cwt x share x PF."""
    p = build_drp_page_payload(populated)
    cell = p["states"]["06"]["Class"]["0"]["0.9"]
    per_cwt = cell["net"] * cell["liab"]
    assert per_cwt == pytest.approx(0.002 * 16.9)
    # protection factor and share are a pure multiplier on the dollars ...
    assert per_cwt * 1.50 * 0.60 == pytest.approx(0.002 * 16.9 * 0.9)
    # ... and never touch the win rate, which is what makes them display-time inputs
    assert cell["win"] == pytest.approx(0.20)
    # whole-declaration dollars: production is POUNDS, divided by 100 against $/cwt
    assert per_cwt * 1_000_000 / 100 == pytest.approx(0.002 * 16.9 * 10_000)


def test_pinned_weighting_factor_count_survives_into_the_payload(conn):
    _best(conn, option="Component", n_pinned=26, n_obs=30)
    conn.commit()
    cell = build_drp_page_payload(conn)["states"]["55"]["Component"]["0"]["0.9"]
    assert cell["pin"] == 26 and cell["n"] == 30


def test_null_metrics_stay_none_rather_than_zero(conn):
    _best(conn, net=None, net_prem=None, liab=None)
    conn.commit()
    cell = build_drp_page_payload(conn)["states"]["55"]["Class"]["0"]["0.9"]
    assert cell["net"] is None and cell["prem"] is None and cell["liab"] is None
    assert cell["win"] is not None
    assert build_drp_page_payload(conn)["min_net"] is None


# --------------------------------------------------------------------- html

def test_render_embeds_payload_and_assets(populated):
    p = build_drp_page_payload(populated)
    html = render_drp_page_html(p, d3_js="var d3js=1;", topojson_js="var tj=1;",
                                atlas={"objects": {}})
    assert "var d3js=1;" in html and "var tj=1;" in html
    assert '"55"' in html
    for token in ("__PAYLOAD__", "__ATLAS__", "__D3__", "__TOPOJSON__", "__GENERATED__"):
        assert token not in html


def test_render_offers_all_five_metrics_and_the_controls(populated):
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    for value in ('value="win"', 'value="net"', 'value="cwt"', 'value="prem"',
                  'value="policy"'):
        assert value in html
    assert 'id="mSel"' in html
    for el in ('id="optSeg"', 'id="qSeg"', 'id="covSeg"',
               'id="fShare"', 'id="fPf"', 'id="fProd"'):
        assert el in html
    # dual-thumb range slider, same pattern as the PRF page
    for el in ('id="rMin"', 'id="rMax"', 'id="rBubbleLo"', 'id="rBubbleHi"',
               'id="rReadout"', 'id="rReset"'):
        assert el in html


def test_render_carries_the_drilldown_chrome(populated):
    """Breadcrumb + log-scaled zoom slider with +/- buttons, lifted from prfpage."""
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    for el in ('id="crumb"', 'id="zoomBox"', 'id="zSlider"', 'id="zLabel"',
               'id="zIn"', 'id="zOut"'):
        assert el in html
    assert "d3.zoom()" in html
    # log-scaled: equal thumb travel is an equal PROPORTIONAL change
    assert "Math.log(k / K_MIN)" in html and "Math.pow(K_MAX / K_MIN" in html


def test_zoom_transitions_apply_instantly_in_a_hidden_tab(populated):
    """rAF is suspended in a background tab, so an animated zoom started there freezes.

    This is the bug prfpage hit; the guard is the fix and it must not be optimized away.
    """
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    assert "function applyTransform(t, dur)" in html
    assert "if (dur === 0 || document.hidden) svg.call(zoom.transform, t);" in html
    # the slider takes the same precaution
    assert "if (document.hidden) svg.call(zoom.scaleTo, kk);" in html


def test_render_documents_the_clockwise_winding_rule(populated):
    """DRP synthesizes no geometry, so the rule ships as a rule rather than a bug."""
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    assert "CLOCKWISE in (lon, lat)" in html
    assert "LEFT of the" in html


def test_breadcrumb_stops_at_the_state_and_says_why(populated):
    """DRP has no county grain; the crumb must not imply one exists."""
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    assert "county code 998" in html
    assert "DRP is sold statewide, so that is the finest grain" in html
    assert "counties share this value" in html
    # and no PRF-style third level
    assert "grid cells" not in html


def test_render_states_the_protection_factor_collapse(populated):
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    assert "The protection factor cannot move this number" in html
    assert "liability per cwt &times; share &times; protection factor" in html
    assert "declared covered milk production &divide; 100" in html


def test_render_says_the_premium_is_simulated_not_a_rate(populated):
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="", topojson_js="", atlas={})
    assert "no premium rate" in html
    assert "P18-1" in html
    assert "5,000" in html


def test_render_is_self_contained_no_network(populated):
    html = render_drp_page_html(build_drp_page_payload(populated),
                                d3_js="var d3js=1;", topojson_js="var tj=1;",
                                atlas={"objects": {}})
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html and "<link rel" not in html


def test_render_rejects_script_closing_assets(conn):
    p = build_drp_page_payload(conn)
    with pytest.raises(ValueError):
        render_drp_page_html(p, d3_js="</script><script>evil()", topojson_js="",
                             atlas={})


def test_empty_sweep_still_renders_with_an_honest_note(conn):
    html = render_drp_page_html(build_drp_page_payload(conn), d3_js="", topojson_js="",
                                atlas={})
    assert "drp_opt_best table is empty" in html
    assert "python -m src.drpopt --all" in html


def test_module_exposes_the_streamlit_entry_point():
    """streamlit_app.py calls drppage.render(); the contract is the name."""
    from src import drppage

    assert callable(drppage.render)
    assert callable(drppage.build_drp_page_payload)
    assert callable(drppage.render_drp_page_html)
