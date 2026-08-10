"""Tests for the row-crop opportunity page (src/rowcroppage.py). No network.

The page is a thin, honest renderer over the precomputed `rowcrop_unclaimed` table, so what
is asserted here is mostly what it must NOT do: read sob_sales at runtime (it is dropped from
the shipped DB), invent a dollar figure where the precompute recorded none, lose the
observed-vs-fitted label, hide the eligibility caveats, or reproduce the two d3 bugs the PRF
map already paid for.
"""
from __future__ import annotations

import json
import re
import sqlite3

import pytest

from src import db
from src.rowcroppage import (
    ALL_CROPS, BAND_ORDER, BASIS_LABELS, _county_names, build_rowcrop_page_payload,
    render_rowcrop_page_html, ring_clockwise,
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    return c


def _row(conn, *, year=2026, fips="31041", state="NE", crop="Corn", band="ECO",
         base=1000.0, band_acres=500.0, sub_pa=24.0, prem_pa=30.0, evidence=2,
         basis="county", pen=None, capped=0, policies=12, ret=5.0):
    if pen is None:
        pen = min(1.0, band_acres / base) if base else 0.0
    unsold = base * (1 - pen)
    pprem_pa = None if (sub_pa is None or prem_pa is None) else prem_pa - sub_pa
    unclaimed_sub = None if sub_pa is None else unsold * sub_pa
    unclaimed_prem = None if prem_pa is None else unsold * prem_pa
    conn.execute(
        "INSERT OR REPLACE INTO rowcrop_unclaimed (year, state, county_fips, crop, band, "
        " base_acres, base_liability, base_policies, band_acres, penetration, pen_capped, "
        " unsold_acres, sub_per_acre, prem_per_acre, pprem_per_acre, return_per_dollar, "
        " value_basis, evidence, unclaimed_subsidy, unclaimed_premium, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'synthetic','2026-08-07')",
        (year, state, fips, crop, band, base, base * 600, policies, band_acres, pen, capped,
         unsold, sub_pa, prem_pa, pprem_pa, ret, basis, evidence,
         unclaimed_sub, unclaimed_prem))


@pytest.fixture()
def populated(conn):
    for crop, base in ((ALL_CROPS, 1500.0), ("Corn", 1000.0), ("Soybeans", 500.0)):
        _row(conn, crop=crop, band="ECO", base=base, band_acres=base / 2)
        _row(conn, crop=crop, band="SCO", base=base, band_acres=base / 4)
    # A second county with NO band sales at all: fitted figures, state-level evidence.
    for crop, base in ((ALL_CROPS, 2000.0), ("Corn", 2000.0)):
        _row(conn, fips="31043", crop=crop, band="ECO", base=base, band_acres=0.0,
             basis="state", evidence=1)
    conn.commit()
    return conn


# --------------------------------------------------------------------- pure

def test_ring_clockwise_reverses_a_counter_clockwise_ring():
    """d3-geo's interior is LEFT of travel, so a CCW ring floods the viewport."""
    ccw = [[-100, 40], [-99, 40], [-99, 41], [-100, 41], [-100, 40]]
    cw = list(reversed(ccw))
    assert ring_clockwise(ccw) == cw
    assert ring_clockwise(cw) == cw                                     # already CW: untouched
    assert ring_clockwise(ring_clockwise(ccw)) == ring_clockwise(ccw)   # idempotent
    assert ring_clockwise([[0, 0], [1, 1]]) == [[0, 0], [1, 1]]         # degenerate


def test_basis_labels_are_the_payload_wire_format():
    """Cells carry the INDEX, so the order of these labels is load-bearing, not cosmetic."""
    assert BASIS_LABELS[0] == "county"
    assert set(BASIS_LABELS) == {"county", "state", "national", "mixed"}


# ------------------------------------------------------------------ payload

def test_missing_table_is_graceful():
    """A DB without the precompute must render a neutral map, not raise."""
    c = sqlite3.connect(":memory:")                     # no schema at all
    c.row_factory = sqlite3.Row
    p = build_rowcrop_page_payload(c)
    assert p["counties"] == {} and p["row_count"] == 0 and p["years"] == []
    assert p["year"] is None
    assert p["crops"] == [ALL_CROPS]
    assert "generated" in p
    c.close()


def test_empty_table_is_graceful(conn):
    p = build_rowcrop_page_payload(conn)
    assert p["counties"] == {} and p["county_count"] == 0
    assert p["bands"] == list(BAND_ORDER) and p["bands_present"] == []


def test_payload_never_reads_sob_sales(populated):
    """sob_sales is DROPPED from the shipped app DB; a query against it would ship broken."""
    populated.execute("DROP TABLE sob_sales")
    populated.commit()
    p = build_rowcrop_page_payload(populated)
    assert p["row_count"] > 0 and p["county_count"] == 2


def test_payload_cell_shape_and_indices(populated):
    p = build_rowcrop_page_payload(populated)
    assert p["crops"][0] == ALL_CROPS                   # the rollup is always index 0
    ci = str(p["crops"].index("Corn"))
    bi = str(p["bands"].index("ECO"))
    cell = p["counties"]["31041"][ci][bi]
    assert len(cell) == 6
    base, band_acres, sub_pa, prem_pa, evidence, basis_ix = cell
    assert (base, band_acres) == (1000, 500)
    assert sub_pa == 24.0 and prem_pa == 30.0
    assert evidence == 2
    assert p["basis"][basis_ix] == "county"


def test_crops_are_ordered_by_acreage_after_the_rollup(populated):
    p = build_rowcrop_page_payload(populated)
    assert p["crops"][0] == ALL_CROPS
    assert p["crops"][1:] == ["Corn", "Soybeans"]       # 1000 ac before 500 ac
    # The remap must have followed: Corn's cells are under Corn's NEW index.
    ci = str(p["crops"].index("Corn"))
    assert p["counties"]["31041"][ci][str(p["bands"].index("ECO"))][0] == 1000


def test_a_fitted_county_keeps_its_label(populated):
    p = build_rowcrop_page_payload(populated)
    ci = str(p["crops"].index("Corn"))
    cell = p["counties"]["31043"][ci][str(p["bands"].index("ECO"))]
    assert p["basis"][cell[5]] == "state"
    assert cell[4] == 1                                 # evidence: state, not county


def test_a_missing_per_acre_figure_stays_none_and_never_becomes_zero(conn):
    """'we could not compute this' and '$0.00' are different claims."""
    _row(conn, sub_pa=None, prem_pa=None, basis=None)
    conn.commit()
    p = build_rowcrop_page_payload(conn)
    cell = p["counties"]["31041"][str(p["crops"].index("Corn"))][str(p["bands"].index("ECO"))]
    assert cell[2] is None and cell[3] is None
    assert cell[5] == -1                                # no basis label either


def test_rows_with_no_eligible_acres_are_dropped(conn):
    _row(conn, base=0.0, band_acres=0.0)
    conn.commit()
    p = build_rowcrop_page_payload(conn)
    assert p["counties"] == {}


def test_year_defaults_to_the_newest_and_can_be_overridden(conn):
    _row(conn, year=2025, base=100.0, band_acres=10.0)
    _row(conn, year=2026, base=200.0, band_acres=20.0)
    conn.commit()
    p = build_rowcrop_page_payload(conn)
    assert p["years"] == [2025, 2026] and p["year"] == 2026
    ci, bi = str(p["crops"].index("Corn")), str(p["bands"].index("ECO"))
    assert p["counties"]["31041"][ci][bi][0] == 200
    older = build_rowcrop_page_payload(conn, year=2025)
    assert older["year"] == 2025
    assert older["counties"]["31041"][ci][bi][0] == 100
    # An unknown year falls back to the newest rather than rendering an empty map.
    assert build_rowcrop_page_payload(conn, year=1999)["year"] == 2026


def test_band_summary_flags_a_first_book_year(conn):
    """A brand-new endorsement reads as all-unclaimed for calendar reasons, not opportunity."""
    _row(conn, year=2025, crop=ALL_CROPS, band="ECO", base=1000.0, band_acres=500.0)
    _row(conn, year=2026, crop=ALL_CROPS, band="ECO", base=1000.0, band_acres=600.0)
    _row(conn, year=2026, crop=ALL_CROPS, band="MCO", base=1000.0, band_acres=10.0)
    conn.commit()
    s = build_rowcrop_page_payload(conn)["band_summary"]
    assert s["MCO"]["new"] is True and s["MCO"]["pen"] == pytest.approx(0.01)
    assert s["ECO"]["new"] is False and s["ECO"]["pen"] == pytest.approx(0.6)


def test_band_summary_claims_nothing_when_there_is_no_prior_year(conn):
    """With one year loaded, every band would look new — so none may be called new."""
    _row(conn, year=2026, crop=ALL_CROPS, band="MCO", base=1000.0, band_acres=10.0)
    conn.commit()
    assert build_rowcrop_page_payload(conn)["band_summary"]["MCO"]["new"] is False


def test_commission_seeds_are_loaded_from_the_prf_model(populated):
    """The AIP x region model is REUSED, not reinvented — same loaders, same files."""
    p = build_rowcrop_page_payload(populated)
    assert "aips" in p["comm"] and "path" in p["comm"]
    assert p["comm"]["path"].endswith("aip_commission.csv")
    assert "zones" in p["commzone"]
    assert p["state_zone"]["31"] == "Central"           # Nebraska, for the county above


def test_commission_csv_override(populated, tmp_path):
    csv = tmp_path / "rates.csv"
    csv.write_text("# a comment\naip_code,aip_name,commission_pct\nX1,Test AIP,11.5\n")
    p = build_rowcrop_page_payload(populated, commission_csv=str(csv))
    assert [a["name"] for a in p["comm"]["aips"]] == ["Test AIP"]
    assert p["comm"]["aips"][0]["pct"] == 11.5


def test_county_names_come_from_whatever_table_exists(conn):
    conn.execute("INSERT INTO prf_grid_county (grid_id, state, county_fips, county_name) "
                 "VALUES (1, 'NE', '31041', 'Custer')")
    conn.commit()
    assert _county_names(conn)["31041"] == "Custer"
    c2 = sqlite3.connect(":memory:")                    # neither table present
    assert _county_names(c2) == {}
    c2.close()


def test_capped_cells_are_carried_to_the_page(conn):
    _row(conn, base=100.0, band_acres=150.0, pen=1.0, capped=1)
    conn.commit()
    assert build_rowcrop_page_payload(conn)["capped_cells"] == 1


# ----------------------------------------------------------------- rendering

@pytest.fixture()
def html(populated):
    return render_rowcrop_page_html(
        build_rowcrop_page_payload(populated), "var d3=1;", "var topojson=1;",
        {"type": "Topology", "objects": {}})


def test_render_is_self_contained_and_substitutes_every_token(html):
    for token in ("__PAYLOAD__", "__ATLAS__", "__D3__", "__TOPOJSON__", "__GENERATED__",
                  "__YEAR__"):
        assert token not in html
    assert html.startswith("<!DOCTYPE html>")
    # Zero network: no external fetches of any kind.
    assert "http://" not in html and "https://" not in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html


def test_render_refuses_js_that_would_break_out_of_the_script_tag(populated):
    payload = build_rowcrop_page_payload(populated)
    with pytest.raises(ValueError):
        render_rowcrop_page_html(payload, "</script><script>alert(1)</script>", "", {})


def test_payload_json_is_escaped_for_inline_embedding(populated):
    payload = build_rowcrop_page_payload(populated)
    payload["county_names"]["31041"] = "</script><b>x"
    out = render_rowcrop_page_html(payload, "", "", {})
    assert "</script><b>x" not in out
    assert "<\\/script>" in out


def test_zoom_transitions_apply_instantly_in_a_hidden_tab(html):
    """rAF is suspended in a background tab, so an animated zoom there freezes mid-flight."""
    assert "document.hidden" in html
    m = re.search(r"function applyTransform\(t, dur\) \{\s*(.+?)\n", html)
    assert m and "document.hidden" in m.group(1)
    assert "svg.call(zoom.transform, t)" in m.group(1)


def test_the_clockwise_winding_rule_is_recorded_for_the_next_contributor(html):
    """No rings are built here, so the rule has to survive as a written rule."""
    assert "CLOCKWISE" in html


def test_drilldown_chrome_is_present(html):
    for hook in ('id="crumb"', 'id="zoomBox"', 'id="zSlider"', 'id="detail"',
                 "function drillOut", "function drillTo", "kToSlider", "sliderToK"):
        assert hook in html


def test_detail_panel_is_shown_with_block_not_empty_string(html):
    """#detail is display:none in CSS, so '' falls back through to hidden — a 0x0 panel."""
    assert 'detail.style.display = "block"' in html
    assert 'detail.style.display = ""' not in html


def test_every_metric_has_a_note_and_the_agency_ones_are_marked_assumed(html):
    for m in ("total", "acre", "pen", "prodac", "ret", "commac", "commtot", "gap"):
        assert f'data-m="{m}"' in html
    # The commission-based metrics must carry the ASSUMED marker and name the seed file.
    assert "ASSUMED" in html
    assert "SAMPLE data" in html
    assert "aip_commission.csv" in html


def test_the_page_states_the_eligibility_caveats_itself(html):
    """The honesty requirement is that these appear ON THE PAGE, not only in the docs."""
    assert "not automatically opportunity" in html
    # ARC: the bar on SCO was real through CY2025 and OBBBA sec.10303(b) repealed it for CY2026
    # (docs/rowcrop_endorsement_stacking.md verifies this against statute, bulletin and
    # handbook). The page must state BOTH halves — rowcrop_unclaimed carries RY2025 rows that
    # are still subject to the old rule, and an RY2026 reader must not be told the bar applies.
    assert "ARC" in html and "could not buy SCO" in html
    assert "repealed the ARC bar for CY2026" in html
    assert "STAX cannot carry SCO" in html
    assert "basisrisk.py" in html.lower() or "basis risk" in html.lower()
    assert "mutually exclusive" in html          # SCO/STAX
    assert "CAT" in html                         # why CAT acres are not in the denominator


def test_the_page_carries_the_metric_definition(html):
    assert "eligible acres" in html and "penetration" in html
    assert "1506(n)(2)" in html                  # the statutory target loss ratio it leans on


def test_payload_round_trips_through_json(populated):
    p = build_rowcrop_page_payload(populated)
    assert json.loads(json.dumps(p))["county_count"] == 2


# ------------------------------------------------------- the basis-risk join, on the page
#
# The page's job here is narrow and mostly negative: carry the joined term through without
# inventing one, and make the THIRD state — basis risk unknown — visible in the legend, the
# tooltip and the ranking rather than letting it collapse into either of the other two.

# cov defaults to the level the module PUBLISHES, not a literal — see the same fixture in
# tests/test_rowcropopt.py. A hardcoded level silently stops matching when it moves.
def _br(conn, *, fips="31041", crop="Corn", band="ECO95", plan="RP", cov=None, miss=0.20,
        grade="A"):
    if cov is None:
        from src.rowcropopt import BASIS_COVERAGE_LEVEL
        cov = BASIS_COVERAGE_LEVEL
    conn.execute(
        "INSERT OR REPLACE INTO basis_risk_county (crop, county_fips, state, county_name, "
        " band, plan_type, coverage_level, n_years, miss_rate, miss_rate_rho_lo, "
        " miss_rate_rho_hi, deep_miss_rate, uncovered_share, windfall_rate, grade, source, "
        " fetched_at) VALUES (?,?,'NE','TEST',?,?,?,40,?,?,?,?,?,?,?,'synthetic','2026-08-07')",
        (crop, fips, band, plan, cov, miss, miss + 0.10, max(0.0, miss - 0.10),
         miss * 0.7, 0.35, 0.25, grade))


@pytest.fixture()
def with_basis(populated):
    _br(populated, fips="31041", crop="Corn", band="ECO95", miss=0.20)
    _br(populated, fips="31041", crop="Soybeans", band="ECO95", miss=0.40)
    _br(populated, fips="31041", crop="Corn", band="SCO86", miss=0.50)
    populated.commit()
    return populated


def test_basis_cell_order_is_the_wire_format():
    """The template indexes these positionally, so the order is load-bearing, not cosmetic."""
    from src.rowcroppage import BASIS_CELL, BASIS_WIRE_TERMS
    from src.rowcropopt import BASIS_TERMS
    assert BASIS_CELL[0] == "miss_rate"
    assert BASIS_CELL[-2:] == ("grade_ix", "cover_share")
    assert set(BASIS_WIRE_TERMS) <= set(BASIS_TERMS)     # the wire is a SUBSET of the table


def test_payload_carries_the_joined_basis_risk(with_basis):
    p = build_rowcrop_page_payload(with_basis)
    ci = p["crops"].index("Corn")
    bi = BAND_ORDER.index("ECO")
    cell = p["basis_risk"]["31041"][str(ci)][str(bi)]
    assert cell[0] == pytest.approx(0.20)               # miss_rate
    assert cell[-1] == pytest.approx(1.0)               # cover_share: a direct per-crop match
    assert p["basis_meta"]["loaded"] is True
    assert p["basis_meta"]["variant"]["ECO"] == "ECO95"
    assert p["basis_meta"]["variant"]["MCO"] is None


def test_an_unmeasured_cell_is_ABSENT_from_the_payload_not_zero(with_basis):
    """Absence is the wire format for unknown: there is no sentinel to coerce into 'low'."""
    p = build_rowcrop_page_payload(with_basis)
    bi_mco, bi_sco = BAND_ORDER.index("MCO"), BAND_ORDER.index("SCO")
    ci_soy = p["crops"].index("Soybeans")
    by_crop = p["basis_risk"].get("31041", {})
    for cells in by_crop.values():
        assert str(bi_mco) not in cells                  # MCO has no estimator at all
    assert str(bi_sco) not in by_crop.get(str(ci_soy), {})   # no SCO86 row for Soybeans
    # ...and the county with no basis rows at all has no entry whatsoever.
    assert "31043" not in p["basis_risk"]
    assert p["basis_meta"]["counts"]["unknown"] > 0


def test_the_rollup_row_gets_an_acre_weighted_partial_estimate(with_basis):
    """(all crops) = 1000 ac Corn at 0.20 + 500 ac Soybeans at 0.40 over 1500 eligible acres."""
    p = build_rowcrop_page_payload(with_basis)
    bi = BAND_ORDER.index("ECO")
    cell = p["basis_risk"]["31041"]["0"][str(bi)]        # index 0 is always (all crops)
    assert p["crops"][0] == ALL_CROPS
    assert cell[0] == pytest.approx((1000 * 0.20 + 500 * 0.40) / 1500, abs=1e-3)
    assert cell[-1] == pytest.approx(1.0)


def test_an_absent_basis_table_degrades_to_unknown_not_to_a_traceback(populated):
    populated.execute("DROP TABLE basis_risk_county")
    populated.commit()
    p = build_rowcrop_page_payload(populated)
    assert p["basis_risk"] == {}
    assert p["basis_meta"]["loaded"] is False
    assert p["basis_meta"]["counts"]["covered"] == 0


def test_basis_metrics_are_offered_and_carry_their_own_notes(html):
    for key in ("adjtotal", "adjacre", "miss", "bgap"):
        assert 'data-m="' + key + '"' in html            # every metric has a formula note
        assert key + ":" in html or '"' + key + '"' in html
    assert "BASIS-ADJUSTED unclaimed subsidy" in html
    assert "basis-risk rank penalty" in html.lower()


def test_the_page_says_unknown_is_not_low_in_the_legend_and_the_tooltip(html):
    """The one sentence the whole coverage-gap requirement reduces to."""
    assert html.lower().count("unknown is not low") >= 2
    assert "basis risk unknown" in html.lower()
    assert "UNKNOWN_FILL" in html and "brUnknown" in html   # hatched, never tinted


def test_unknown_counties_are_hatched_rather_than_shaded(html):
    """A tint puts a county somewhere on the ramp, and every position is a claim we lack."""
    assert 'attr("id", "brUnknown")' in html
    assert "if (basisUnknown(fips)) { unknown++; return UNKNOWN_FILL; }" in html


def test_the_adjustment_is_stated_as_a_formula_on_the_page(html):
    assert "1 &minus; miss rate" in html
    assert "P(the band pays NOTHING | the farm has a loss beyond its own" in html


def test_the_raw_metric_survives_the_adjustment(html):
    """Adjusted is ADDED, never substituted: both must remain selectable."""
    assert "Unclaimed subsidy — total $" in html
    assert "BASIS-ADJUSTED unclaimed subsidy — total $" in html
    assert '"total", "acre", "pen"' in html and '"adjtotal", "adjacre", "miss", "bgap"' in html


def test_one_band_never_borrows_another_bands_basis_risk(html):
    """SCO, ECO, MCO and STAX are different products; MCO's trigger is not even modelled."""
    assert "s.br = null; s.adjSub = null; s.adjPrem = null;" in html
    assert "MARGIN" in html


def test_the_ranking_view_shows_raw_adjusted_and_the_basis_term(html):
    assert "Top counties" in html
    assert "<th>raw</th><th>basis-adj</th><th>miss</th>" in html
    assert "NOT RANKED &mdash; basis risk unknown" in html


def test_the_page_states_the_legitimate_causes_of_low_penetration_uncollapsed(html):
    """Requirement: prominent ON THE PAGE. It lives in the <summary>, which never collapses."""
    head = html.split("<div class=\"c-body\">")[0]
    assert "not a list of people to sell to" in head
    assert "ineligible" in head and "rationally declined on basis risk" in head


def test_the_page_never_reads_a_dropped_table(with_basis):
    """nass_county_yield and sob_sales are BOTH dropped from the shipped app DB."""
    seen = []
    with_basis.set_trace_callback(seen.append)
    build_rowcrop_page_payload(with_basis)
    with_basis.set_trace_callback(None)
    sql = " ".join(seen).lower()
    assert "sob_sales" not in sql and "nass_county_yield" not in sql
    assert "basis_risk_county" in sql and "rowcrop_unclaimed" in sql


# ---------------------------------------- against the SHIPPED slim DB, if it is here
#
# An earlier bug in this project took the whole app down by reading a table that
# scripts/build_app_db.py drops, and every test passed because the tests use the WORKING
# catalog. This one opens data/catalog_app.db itself — the artifact that actually deploys,
# where sob_sales and nass_county_yield are absent — and builds the real payload against it.

_APP_DB = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "catalog_app.db"
skip_no_app_db = pytest.mark.skipif(
    not _APP_DB.exists(), reason="data/catalog_app.db not built")


@skip_no_app_db
def test_payload_builds_against_the_shipped_app_db():
    c = sqlite3.connect(f"file:{_APP_DB}?mode=ro", uri=True)
    try:
        have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # The premise of this test: these two really are gone from the shipped artifact.
        assert "sob_sales" not in have and "nass_county_yield" not in have
        assert {"rowcrop_unclaimed", "basis_risk_county"} <= have
        p = build_rowcrop_page_payload(c)
    finally:
        c.close()
    assert p["row_count"] > 0 and p["county_count"] > 0
    counts = p["basis_meta"]["counts"]
    assert p["basis_meta"]["loaded"] is True
    assert counts["covered"] > 0
    # And the coverage gap is real and carried, not quietly closed.
    assert counts["unknown"] > 0
    # Every row that made it into the map is classified into exactly one of the three states.
    assert 0 < sum(counts.values()) <= p["row_count"]


@skip_no_app_db
def test_the_optimism_caveat_is_emitted_by_the_real_farm_report_render():
    """BASIS_OPTIMISM_NOTE was first wired only into render_rowcrop_page_html, which
    streamlit_app.py never calls -- that page is a standalone generated artifact. The result
    was a caveat that existed, passed its own test, and was invisible to every user of the app.

    This drives the actual render with a real FarmReport built from the shipped DB and a
    recording stand-in for `st`, rather than grepping the source: the question is whether a
    producer looking at their own band table sees the qualification, and only running the
    function answers that.
    """
    import random
    import sqlite3

    from src import rowcroppage as R

    class _Col:
        def metric(self, *a, **k): pass

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __getattr__(self, n): return lambda *a, **k: None

    class _St:
        def __init__(self): self.calls = []
        def __getattr__(self, name):
            if name == "columns":
                return lambda n, *a, **k: [_Col() for _ in
                                           range(n if isinstance(n, int) else len(n))]
            if name == "expander":
                return lambda *a, **k: _Ctx()
            if name == "tabs":
                return lambda labels, *a, **k: [_Ctx() for _ in labels]
            def rec(*a, **k):
                self.calls.append((name, a[0] if a else ""))
            return rec

    conn = sqlite3.connect(f"file:{_APP_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT county_fips FROM basis_risk_county WHERE crop='Corn' LIMIT 1").fetchone()
    if row is None:
        import pytest
        pytest.skip("no Corn rows in basis_risk_county")
    fips = row[0]
    series = R.load_county_series(conn, "Corn", fips)
    rng = random.Random(3)
    farm = {y: v * (0.9 + 0.2 * rng.random()) for y, v in zip(series.years, series.values)}
    report = R.farm_report(
        series, farm, coverage_level=0.85, plan_type="RP", farm_detrend="county",
        published=R.published_basis_risk(conn, "Corn", fips),
        national=R.typical_miss_by_band(conn))

    st = _St()
    R._render_farm_report(st, report)
    assert any("optimistic" in str(v) for _, v in st.calls), (
        "a producer reading their own band table must see the optimism caveat; it reached "
        "only the standalone opportunity page once"
    )


def test_the_app_renders_the_farm_calculator_and_not_the_standalone_page():
    """Pins the reachability fact the test above depends on, so that if the opportunity map is
    ever wired into the app the pairing gets revisited deliberately rather than by surprise."""
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    text = app.read_text()
    assert "render_farm_calculator" in text
    assert "render_rowcrop_page_html" not in text, (
        "the opportunity map is now in the app -- check that it carries the optimism note too"
    )


def test_the_rho_swing_sentence_is_read_from_the_data_not_typed_in():
    """The farm calculator's opening paragraph quotes how far the rho assumption moves the
    answer. It used to say "about 2x ... 0.455 at a correlation of 0.55 and 0.235 at 0.85",
    typed in by hand -- so when RHO_LO moved 0.55 -> 0.35 the sentence went on citing the
    retired floor, on the page whose entire argument is that rho is the weakest number here.

    Two things are asserted: the live constants appear in the sentence, and the retired 0.55
    does not appear as a correlation anywhere in the calculator's source.
    """
    import inspect

    from src import basisrisk as B
    from src import rowcroppage

    s = rowcroppage._rho_swing_sentence()
    assert f"{B.RHO_LO:g}" in s and f"{B.RHO_HI:g}" in s, s
    assert "SCO86" in s

    src = inspect.getsource(rowcroppage.render_farm_calculator)
    assert "0.455" not in src and "correlation of 0.55" not in src, (
        "the swing figures must come from _rho_swing_sentence(), not be typed into the prose"
    )


def test_the_rho_swing_sentence_degrades_instead_of_raising():
    """It renders inside the first paragraph of the page. If basis_risk_county is missing or
    its bound columns are NULL, the paragraph must still make its point rather than take the
    tab down -- the claim "rho matters" does not depend on being able to quantify it here.
    """
    from src import rowcroppage

    s = rowcroppage._rho_swing_sentence(band="NOT_A_BAND")
    assert s and s.endswith(".")


@skip_no_app_db
def test_no_map_prose_hardcodes_the_rho_band_or_the_crop_list():
    """Three separate strings in the generated page quoted "0.55-0.85" or "Corn, Soybeans and
    Wheat" as literal text. All three sat beside values computed from the live constants, so
    widening RHO_LO and adding Cotton left the page confidently stating retired facts next to
    correct numbers -- the failure mode that is hardest to notice, because nothing looks broken.

    The band label now comes from BMETA via rhoBand(). This asserts the literals are gone from
    the rendered HTML and that the live floor appears in the payload.
    """
    import json
    import sqlite3

    from src import basisrisk as B
    from src.rowcroppage import build_rowcrop_page_payload

    conn = sqlite3.connect(f"file:{_APP_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    payload = build_rowcrop_page_payload(conn)

    meta = payload["basis_meta"]
    assert meta["rho_lo"] == B.RHO_LO and meta["rho_hi"] == B.RHO_HI
    assert "Cotton" in meta["crop_note"]

    blob = json.dumps(payload)
    assert "0.55&ndash;0.85" not in blob
    assert "Corn, Soybeans and Wheat" not in blob
