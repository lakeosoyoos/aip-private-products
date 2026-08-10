"""Tests for src/lgmpage.py — the LGM tab. No network, no live DB, no Streamlit runtime.

The page's job is to make src/lgm.py reachable WITHOUT softening it, so most of what is
asserted here is that the honest parts survived the trip to the UI:

    test_unpooled_ladder_is_uniformly_value_destroying — the marketing-months trap
    test_ladder_rows_mark_all_three_argmaxes           — the three objectives disagree
    test_objective_summary_measures_the_blind_plateau  — where return-per-$1 goes blind
    test_optimum_moves_with_the_spread                 — no cached constant

Everything is exercised against pure functions; `render()` is checked for wiring only,
because a Streamlit render needs a running script context (the AppTest pass over the whole
app is run by hand — see the module docstring of tests/test_webapp.py's neighbours).
"""
from __future__ import annotations

import ast
import zipfile
from pathlib import Path

import numpy as np
import pytest

from src import lgm, lgmpage

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures — a structurally real cattle case, same construction as test_lgm.py
# ---------------------------------------------------------------------------

@pytest.fixture
def cattle_curve():
    """A cattle curve whose three argmaxes are all DIFFERENT, which is the interesting case.

    The spread is chosen deliberately. Real RY2026/RY2027 cattle panels put the net-gain
    argmax at $70, the same rung `per_dollar` picks (the cheapest rung reaching the 0.50
    cap), and the two objectives then agree by coincidence rather than in principle. At a
    slightly tighter spread the net-gain peak sits one rung below the cap — the shape
    docs/lgm.md §2.2 describes as "at, or one rung below" — and the fixture can then assert
    the disagreement rather than assuming it.
    """
    expected, draws = lgmpage.scenario_draws(450.0, 10, spread=0.25, n_draws=2000)
    h = lgmpage.marketing_plan(10, 10, 100.0)
    return lgm.deductible_curve("0803", "808", "19", expected, draws, h)


@pytest.fixture
def unpooled_curve():
    expected, draws = lgmpage.scenario_draws(450.0, 10, spread=0.30, n_draws=2000)
    h = lgmpage.marketing_plan(10, 1, 100.0)
    return lgm.deductible_curve("0803", "808", "19", expected, draws, h)


# ---------------------------------------------------------------------------
# The marketing plan and the pooling gate
# ---------------------------------------------------------------------------

def test_marketing_plan_puts_exposure_in_the_first_k_months():
    assert lgmpage.marketing_plan(10, 3, 100.0) == [100.0] * 3 + [0.0] * 7
    assert sum(lgmpage.marketing_plan(10, 3, 100.0)) == 300.0


def test_marketing_plan_clamps_rather_than_raising():
    assert lgmpage.marketing_plan(5, 99, 1.0) == [1.0] * 5
    assert lgmpage.marketing_plan(5, 0, 1.0) == [0.0] * 5
    assert lgmpage.marketing_plan(5, -3, 1.0) == [0.0] * 5


@pytest.mark.parametrize("k,pooled", [(1, False), (2, True), (10, True)])
def test_marketing_plan_drives_the_subsidy_eligibility_gate(k, pooled):
    """One month is the whole cliff: lgm.is_pooled counts months, not quantity."""
    assert lgm.is_pooled(lgmpage.marketing_plan(10, k, 1_000_000.0)) is pooled


def test_unpooled_ladder_is_uniformly_value_destroying(unpooled_curve):
    """The trap, end to end: zero subsidy at EVERY rung and a negative net gain at each."""
    assert not any(c.pooled for c in unpooled_curve)
    assert all(c.subsidy == 0.0 for c in unpooled_curve)
    assert all(c.net_expected_gain <= 0 for c in unpooled_curve)
    # ...and the loss is exactly the 1.03 load, at every deductible.
    for c in unpooled_curve:
        if c.total_premium:
            assert (-c.net_expected_gain / c.total_premium ==
                    pytest.approx(lgm.break_even_subsidy(), abs=1e-9))


def test_trap_text_carries_the_citation_and_the_break_even():
    body = lgmpage.TRAP_BODY.format(be=lgm.break_even_subsidy())
    assert "FCIC-20080" in body and "21 D(8)" in body
    assert "two (2) or more months" in body
    assert "2.91%" in body                    # the honest break-even, not 0%
    assert "1.03" in body
    assert "value-destroying" in body
    assert "EVERY deductible" in lgmpage.TRAP_HEADLINE


def test_pooled_note_names_the_month_count_and_the_downside():
    note = lgmpage.POOLED_NOTE.format(k=4, be=lgm.break_even_subsidy())
    assert "4 months" in note and "2.91%" in note


# ---------------------------------------------------------------------------
# The ladder table
# ---------------------------------------------------------------------------

def test_ladder_rows_cover_every_filed_rung(cattle_curve):
    rows = lgmpage.ladder_rows(cattle_curve)
    assert [r["Deductible"] for r in rows] == lgm.deductible_grid("0803")


def test_ladder_rows_mark_all_three_argmaxes(cattle_curve):
    """Showing only the net-gain peak would be advice; showing three is the decision."""
    rows = lgmpage.ladder_rows(cattle_curve)
    marks = " ".join(r[""] for r in rows)
    assert "max net gain" in marks
    assert "max return per $1" in marks
    assert "max protection" in marks
    # Protection is always the $0 rung, and it is NOT the net-gain peak.
    protection_row = next(r for r in rows if "max protection" in r[""])
    assert protection_row["Deductible"] == 0.0
    assert "max net gain" not in protection_row[""]


def test_ladder_rows_are_empty_for_an_empty_curve():
    assert lgmpage.ladder_rows([]) == []


def test_curve_frame_rows_carry_both_curves_and_their_product(cattle_curve):
    rows = lgmpage.curve_frame_rows(cattle_curve)
    assert len(rows) == len(cattle_curve)
    rates = [r["Subsidy rate"] for r in rows]
    base = [r["Total premium"] for r in rows]
    assert rates == sorted(rates)                    # the rate rises
    assert base == sorted(base, reverse=True)        # the base falls


# ---------------------------------------------------------------------------
# The interior optimum, and the metric that goes blind
# ---------------------------------------------------------------------------

def test_objective_summary_optimum_is_interior(cattle_curve):
    s = lgmpage.objective_summary(cattle_curve)
    assert s["gain"].deductible not in (cattle_curve[0].deductible,
                                        cattle_curve[-1].deductible)
    assert s["gain"].net_expected_gain > cattle_curve[0].net_expected_gain
    assert s["gain"].net_expected_gain > cattle_curve[-1].net_expected_gain
    assert s["uplift_vs_zero"] > 1.0


def test_objective_summary_three_objectives_disagree(cattle_curve):
    s = lgmpage.objective_summary(cattle_curve)
    assert s["protection"].deductible == 0.0
    assert s["protection"].deductible < s["gain"].deductible < s["per_dollar"].deductible


def test_objective_summary_measures_the_blind_plateau(cattle_curve):
    """Return per producer dollar is 1/(1-subsidy), so it cannot rank the cap plateau."""
    s = lgmpage.objective_summary(cattle_curve)
    plateau = s["plateau"]
    assert len(plateau) > 1
    assert len({round(c.return_per_producer_dollar, 9) for c in plateau}) == 1
    assert s["plateau_subsidy"] == 0.50
    assert s["plateau_return_per_dollar"] == pytest.approx(
        lgm.return_per_producer_dollar(1 / lgm.LOADING_FACTOR, 0.50))
    # Net gain, over that same interval where the metric is flat, falls a long way.
    assert s["plateau_gain_fall"] > 0.5


def test_objective_summary_rejects_an_empty_curve():
    with pytest.raises(ValueError):
        lgmpage.objective_summary([])


def test_optimum_moves_with_the_spread():
    """$70 is a fact about this year's price spread, not a constant of LGM-Cattle.

    The page must never cache an optimum and present it as fixed; this pins the
    directionality the scenario slider exists to expose.
    """
    def argmax(spread):
        e, d = lgmpage.scenario_draws(450.0, 10, spread=spread, n_draws=3000)
        curve = lgm.deductible_curve("0803", "808", "19", e, d,
                                     lgmpage.marketing_plan(10, 10, 100.0))
        return lgm.optimal_deductible(curve, "gain").deductible

    assert argmax(0.45) > argmax(0.15)


def test_scenario_draws_are_correlated_across_months():
    """Independent monthly draws would diversify the period risk away and move the
    optimum to $0 — the fixture's correlation is load-bearing, not cosmetic."""
    _, draws = lgmpage.scenario_draws(450.0, 10, spread=0.30, idio=0.10, n_draws=4000)
    corr = np.corrcoef(draws[:, 0], draws[:, -1])[0, 1]
    assert corr > 0.7


def test_scenario_draws_preserve_the_expected_margin():
    expected, draws = lgmpage.scenario_draws(300.0, 6, spread=0.30, n_draws=20000)
    assert list(expected) == [300.0] * 6
    assert draws.mean() == pytest.approx(300.0, rel=0.02)


def test_scenario_draws_reject_a_degenerate_period():
    with pytest.raises(ValueError):
        lgmpage.scenario_draws(300.0, 0)


# ---------------------------------------------------------------------------
# The subsidy ladder source
# ---------------------------------------------------------------------------

def test_subsidy_ladder_falls_back_to_the_constant_and_says_so():
    table, source = lgmpage.subsidy_ladder_source(None, 2027)
    assert table is lgm.SUBSIDY_BY_DEDUCTIBLE
    assert "module constant" in source


def test_subsidy_ladder_prefers_loaded_adm_rows(tmp_path):
    import sqlite3

    from src import db

    path = tmp_path / "cat.db"
    conn = sqlite3.connect(path)
    db.init_db(conn)
    lgm.upsert_subsidy(conn, [(2027, "0803", 0.0, 0.99)])
    conn.commit()
    conn.close()

    table, source = lgmpage.subsidy_ladder_source(str(path), 2027)
    assert table is not lgm.SUBSIDY_BY_DEDUCTIBLE
    assert table["0803"][0.0] == 0.99
    assert "A00070" in source and "2027" in source


def test_subsidy_ladder_survives_a_missing_database():
    table, source = lgmpage.subsidy_ladder_source("/nonexistent/nope.db", 2027)
    assert table is lgm.SUBSIDY_BY_DEDUCTIBLE and "module constant" in source


# ---------------------------------------------------------------------------
# ADM reading — synthetic files, no network
# ---------------------------------------------------------------------------

DAIRY_MONTHS = lgm.INSURED_MONTHS["0847"]


def _gm_text() -> str:
    head = (["Reinsurance Year", "Commodity Code", "Type Code", "State Code",
             "Insurance Plan Code", "Sales Effective Date", "Market Symbol Code",
             "Liability Price"]
            + [f"Month{m} Expected Gross Margin Amount" for m in DAIRY_MONTHS])
    rows = [head]
    for sym, val in (("DA", 18.0), ("C", 4.5), ("SM", 320.0)):
        rows.append(["2026", "0847", "997", "55", "82", "20260416", sym, "17.13"]
                    + [f"{val:.4f}"] * len(DAIRY_MONTHS))
    return "\n".join("|".join(r) for r in rows)


def _draw_text(n: int = 4) -> str:
    prefixes = ["Dairy ", "Corn ", "SoyM "]
    head = (["Reinsurance Year", "Commodity Code", "Type Code", "State Code",
             "Insurance Plan Code", "Sales Effective Date"]
            + [f"{p}Month{m} Margin Draw Amount"
               for p in prefixes for m in DAIRY_MONTHS])
    rows = [head]
    rng = np.random.default_rng(7)
    for _ in range(n):
        vals = []
        for base in (18.0, 4.5, 320.0):
            vals += [f"{base * float(rng.normal(1.0, 0.05)):.4f}"
                     for _ in DAIRY_MONTHS]
        rows.append(["2026", "0847", "997", "55", "82", "20260416"] + vals)
    return "\n".join("|".join(r) for r in rows)


def test_adm_index_reads_only_the_expected_margin_member():
    idx = lgmpage.adm_index(_gm_text())
    assert idx == {("0847", "997"): ["55"]}


def test_adm_index_skips_rows_from_other_plans():
    text = _gm_text().replace("|82|", "|83|")
    assert lgmpage.adm_index(text) == {}


def test_leg_price_paths_rebuilds_what_build_panels_discards():
    """MarginPanel keeps only the composite, so ration_divergence's risk layer needs this."""
    legs = lgmpage.leg_price_paths(_gm_text(), _draw_text(6), "0847", "997", "55")
    assert legs is not None
    expected, draws = legs
    assert set(expected) == {"output", "corn", "soybean_meal"}
    assert expected["output"].tolist() == [18.0] * len(DAIRY_MONTHS)
    assert draws["corn"].shape == (6, len(DAIRY_MONTHS))
    assert draws["soybean_meal"].mean() == pytest.approx(320.0, rel=0.05)


def test_leg_price_paths_is_none_for_swine():
    """Swine publishes one composite row with no Market Symbol Code — no legs exist."""
    assert "0815" not in lgm.COMPONENT_LEGS
    assert lgmpage.leg_price_paths(_gm_text(), _draw_text(), "0815", "805", "55") is None


def test_leg_price_paths_is_none_when_a_component_row_is_missing():
    text = "\n".join(l for l in _gm_text().splitlines() if "|SM|" not in l)
    assert lgmpage.leg_price_paths(text, _draw_text(), "0847", "997", "55") is None


def _write_zip(tmp_path: Path, name: str = "2026_ADMLivestockLgm_Daily_20260416.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("A00600_LgmGrossMargin_20260416.txt", _gm_text())
        zf.writestr("A00610_LgmDraw_20260416.txt", _draw_text(8))
    return p


def test_read_members_tags_the_two_members(tmp_path):
    members = lgmpage.read_members(_write_zip(tmp_path))
    assert set(members) == {"A00600", "A00610"}


def test_load_case_assembles_the_composite_and_keeps_the_legs(tmp_path):
    case = lgmpage.load_case(_write_zip(tmp_path), "0847", "997", "55")
    assert case is not None
    assert case.reinsurance_year == 2026
    assert case.sales_effective_date == "20260416"
    assert case.n_draws == 8
    assert case.months == DAIRY_MONTHS
    assert case.has_leg_prices
    # margin = milk*1 - corn*0.5bu - sbm*0.002t, on the declared dairy ration.
    ration = lgm.ration_for("0847", "997")
    want = 18.0 - 4.5 * ration.corn_bu - 320.0 * ration.soybean_meal_ton
    assert case.expected[0] == pytest.approx(want)


def test_load_case_returns_none_for_a_cell_that_is_not_published(tmp_path):
    assert lgmpage.load_case(_write_zip(tmp_path), "0803", "808", "55") is None


def test_zip_reinsurance_year():
    assert lgmpage.zip_reinsurance_year("2027_ADMLivestockLgm_Daily_20260806.zip") == 2027
    assert lgmpage.zip_reinsurance_year("something_else.zip") is None


def test_cached_adm_zips_is_empty_and_quiet_when_there_is_no_cache(tmp_path):
    assert lgmpage.cached_adm_zips(tmp_path / "missing") == []


def test_cached_adm_zips_lists_newest_reinsurance_year_first(tmp_path):
    for n in ("2026_ADMLivestockLgm_Daily_20260416.zip",
              "2027_ADMLivestockLgm_Daily_20260806.zip"):
        (tmp_path / n).write_bytes(b"")
    assert [p.name for p in lgmpage.cached_adm_zips(tmp_path)][0].startswith("2027")


# ---------------------------------------------------------------------------
# Ration divergence, driven off RMA's own draws
# ---------------------------------------------------------------------------

def test_marketing_weighted_prices_average_over_the_plan(tmp_path):
    case = lgmpage.load_case(_write_zip(tmp_path), "0847", "997", "55")
    got = lgmpage.marketing_weighted_prices(
        case, lgmpage.marketing_plan(len(case.months), len(case.months), 10.0))
    assert got is not None
    prices, draws = got
    assert set(prices) == {"output_price", "corn_price", "soybean_meal_price"}
    assert prices["output_price"] == pytest.approx(18.0)
    # One observation per published draw — that is what the risk layer is measured across.
    assert all(a.shape == (case.n_draws,) for a in draws.values())


def test_marketing_weighted_prices_refuse_an_empty_plan(tmp_path):
    case = lgmpage.load_case(_write_zip(tmp_path), "0847", "997", "55")
    assert lgmpage.marketing_weighted_prices(
        case, [0.0] * len(case.months)) is None


def test_ration_divergence_through_the_page_separates_level_from_risk(tmp_path):
    """The level gap is large and offsettable; the untracked variance is the basis risk."""
    case = lgmpage.load_case(_write_zip(tmp_path), "0847", "997", "55")
    prices, draws = lgmpage.marketing_weighted_prices(
        case, lgmpage.marketing_plan(len(case.months), len(case.months), 10.0))
    heavy = lgmpage.ration_from_inputs("0847", "997",
                                       {"corn_bu": 0.9, "soybean_meal_ton": 0.0035})
    div = lgm.ration_divergence("0847", "997", heavy, prices=prices, price_draws=draws)
    assert div.eliminable                                   # both legs inside the band
    assert div.expected_margin_gap < -1.0                   # a big LEVEL gap
    assert div.unexplained_variance_share < 0.10            # a small untracked VARIANCE
    assert abs(div.expected_margin_gap) > div.residual_sd


def test_ration_from_inputs_defaults_every_leg_it_is_not_given():
    insured = lgm.ration_for("0803", "808")
    actual = lgmpage.ration_from_inputs("0803", "808", {"corn_bu": 80.0})
    assert actual.corn_bu == 80.0
    assert actual.feeder_cwt == insured.feeder_cwt
    assert actual.output_cwt == insured.output_cwt
    assert actual.soybean_meal_ton is None      # cattle is fed no soybean meal
    assert actual.electable is insured.electable


def test_ration_from_inputs_cannot_invent_a_leg_the_commodity_lacks():
    actual = lgmpage.ration_from_inputs("0847", "997", {"feeder_cwt": 6.0})
    assert actual.feeder_cwt is None            # a dairy buys no feeder animal


def test_only_swine_is_locked_so_the_page_can_say_so():
    electable = {cc for (cc, _), r in lgm.DECLARED_RATION.items() if r.electable}
    fixed = {cc for (cc, _), r in lgm.DECLARED_RATION.items() if not r.electable}
    assert fixed == {"0815"} and electable == {"0803", "0847"}
    assert "IRREDUCIBLE" in lgmpage.RATION_ELIMINABLE_NOTE
    assert "ELIMINABLE" in lgmpage.RATION_ELIMINABLE_NOTE
    assert "avoidable" in lgmpage.RATION_ELIMINABLE_NOTE
    assert "not basis risk" in lgmpage.RATION_LEVEL_VS_RISK
    assert "miss rate" in lgmpage.RATION_LEVEL_VS_RISK


# ---------------------------------------------------------------------------
# The head-to-heads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "row", list(lgmpage.HEAD_TO_HEAD_SUBSIDISED) + list(lgmpage.HEAD_TO_HEAD_ALL_SETTLED),
    ids=lambda r: f"{r['plan']}-{r['loss_ratio']}")
def test_head_to_head_rows_satisfy_the_repos_own_identity(row):
    """indemnity per producer $ == loss_ratio / (1 - subsidy). A typo would break this."""
    assert row["per_dollar"] == pytest.approx(
        lgm.return_per_producer_dollar(row["loss_ratio"], row["subsidy"]), abs=0.02)


def test_head_to_head_carries_the_two_comparisons_the_module_was_built_for():
    subsidised = {r["plan"]: r["per_dollar"] for r in lgmpage.HEAD_TO_HEAD_SUBSIDISED}
    assert subsidised["LGM Dairy Cattle"] == 1.93 > subsidised["DRP (all)"] == 1.34
    assert subsidised["LRP (all)"] == 0.99 > subsidised["LGM Cattle"] == 0.40
    allyears = {r["plan"]: r["per_dollar"] for r in lgmpage.HEAD_TO_HEAD_ALL_SETTLED}
    # The two windows disagree on dairy, which is why both are shown.
    assert allyears["LGM Dairy Cattle"] < allyears["DRP (all)"]


def test_head_to_head_prose_flags_the_ry2027_concurrency_change():
    assert "RY2027" in lgmpage.CONCURRENT_NOTE
    assert "concurrent coverage" in lgmpage.CONCURRENT_NOTE
    assert "portfolio question" in lgmpage.CONCURRENT_NOTE
    assert "models a stacked LGM+DRP position" in lgmpage.CONCURRENT_NOTE
    assert "Neither" in lgmpage.CONCURRENT_NOTE     # i.e. neither module does


def test_head_to_head_prose_admits_the_deductible_blend():
    assert ".0000" in lgmpage.BLENDED_DEDUCTIBLE_CAVEAT
    assert "blended across whatever deductibles" in lgmpage.BLENDED_DEDUCTIBLE_CAVEAT


# ---------------------------------------------------------------------------
# Honesty text that must not quietly disappear
# ---------------------------------------------------------------------------

def test_the_page_no_longer_claims_the_ladder_cannot_be_backtested():
    """This test used to assert the OPPOSITE, and the assertion was wrong.

    sobtpu really does report Coverage Level as .0000 for every plan-82 row, so realized
    loss ratio by deductible is absent from the Summary of Business. But that is one file,
    not the world: ADM A00600 publishes actual gross margins beside expected ones, so the
    indemnity at every rung is arithmetic. The page must not tell a producer a number is
    unknowable when it has been measured two sections further down.
    """
    note = lgmpage.FORWARD_LOOKING_NOTE
    assert "cannot be backtested" not in note
    assert ".0000" in note and "sobtpu" in note, "the real sobtpu limitation still applies"
    assert "A00600" in note, "must point at the file that CAN answer it"


def test_the_measured_result_is_on_the_page_and_contradicts_the_model():
    """The forward ladder recommends $70/head for cattle. Measured over five reinsurance
    years, that rung paid nothing. Showing the model without the measurement would leave a
    recommendation standing that the data refutes."""
    note = lgmpage.BACKTEST_NOTE
    assert "A00600" in note
    for must in ("Swine", "Dairy", "Cattle"):
        assert must in note
    assert "6–11" in note or "6-11" in note, "the sample size must travel with the result"
    assert "national" in note, "50 states being one observation is the reason it is 6-11"


def test_spread_note_refuses_to_treat_the_optimum_as_a_constant():
    assert "not about the product" in lgmpage.SPREAD_NOTE
    assert "recomputes" in lgmpage.SPREAD_NOTE
    assert "no optimum is stored and reused" in lgmpage.SPREAD_NOTE


def test_scenario_warning_never_claims_to_be_rmas_rating():
    assert "not RMA's rating" in lgmpage.SCENARIO_WARNING
    assert "not a quote" in lgmpage.SCENARIO_WARNING


def test_one_sentence_names_the_deductible_and_the_interior_optimum():
    assert "deductible" in lgmpage.ONE_SENTENCE
    assert "18%" in lgmpage.ONE_SENTENCE
    assert "single-month marketing plan" in lgmpage.ONE_SENTENCE
    assert "inside" in lgmpage.ONE_SENTENCE


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_module_exposes_the_streamlit_entry_point():
    assert callable(lgmpage.render)


def test_module_does_not_import_streamlit_at_module_scope():
    """Importing this module must stay cheap — the tests import it, and streamlit is ~2 s."""
    tree = ast.parse((REPO / "src" / "lgmpage.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("streamlit") for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("streamlit")


def test_app_registers_the_lgm_tab_and_imports_it_defensively():
    """The tab must exist, and a broken lgmpage must not take the whole app down."""
    src = (REPO / "streamlit_app.py").read_text()
    assert '"LGM"' in src
    assert "_tab_lgm()" in src
    tree = ast.parse(src)
    guarded = any(
        isinstance(n, ast.Try)
        and any(isinstance(s, ast.ImportFrom) and "lgmpage" in
                [a.name for a in s.names] for s in n.body)
        for n in tree.body)
    assert guarded, "src.lgmpage must be imported inside a try/except at module scope"


def test_app_tab_list_kept_every_previous_tab():
    src = (REPO / "streamlit_app.py").read_text()
    for label in ("Row Crop", "PRF", "LRP", "DRP", "About"):
        assert f'"{label}"' in src


def test_state_and_commodity_labels():
    assert lgmpage.state_label("19") == "19 — IA"
    assert lgmpage.state_label("99") == "99"
    assert lgmpage.commodity_label("0847") == "Dairy Cattle"
    assert lgmpage.type_label("0803", "807") == "Calf Finishing"
    assert lgmpage.type_label("0803", "zzz") == "zzz"


def test_every_selectable_commodity_has_a_ration_a_unit_and_a_size_default():
    for cc in lgmpage.COMMODITY_ORDER:
        assert cc in lgm.COMMODITY_NAMES
        assert cc in lgm.COMMODITY_UNIT
        assert cc in lgmpage.SIZE_LABEL and cc in lgmpage.DEFAULT_SIZE
        assert cc in lgm.INSURED_MONTHS
        assert any(c == cc for (c, _) in lgm.DECLARED_RATION)


def test_ladder_rows_refuse_to_recommend_a_rung_when_unpooled(unpooled_curve):
    """An unpooled curve has an arithmetic argmax and no good answer. Do not mark one."""
    rows = lgmpage.ladder_rows(unpooled_curve)
    marks = " ".join(r[""] for r in rows)
    assert "max net gain" not in marks
    assert "max return per $1" not in marks
    assert "max protection" not in marks
    assert marks.count("least-bad rung — still negative") == 1


def test_the_default_ration_is_the_declared_one_and_the_page_says_so():
    """The section opens with every box on RMA's declared ration, so the first thing a reader
    sees is gap 0.000 / correlation 1.0000 / 0.00% untracked. That is the correct identity, and
    it is visually identical to a calculator that silently failed. Two things must hold: the
    default really is the identity (so the guard fires), and the page carries an explanation.
    """
    import inspect

    from src import lgm, lgmpage

    for cc, tc in sorted(lgm.DECLARED_RATION):
        insured = lgm.ration_for(cc, tc)
        # No values supplied == what the number_inputs hold before anyone touches them.
        actual = lgmpage.ration_from_inputs(cc, tc, {})
        for field in ("corn_bu", "soybean_meal_ton", "feeder_cwt", "output_cwt"):
            assert getattr(actual, field) == getattr(insured, field), (
                f"{cc}/{tc} {field}: the default box value must be RMA's declared ration"
            )

    src = inspect.getsource(lgmpage._render_ration)
    assert "RATION_IDENTITY_NOTE" in src, "the identity case must be explained, not left bare"
    note = lgmpage.RATION_IDENTITY_NOTE
    assert "1.0000" in note and "not a failed calculation" in note
