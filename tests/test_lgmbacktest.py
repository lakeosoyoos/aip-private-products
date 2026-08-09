"""Tests for src/lgmbacktest.py — the MEASURED LGM deductible ladder. No network, no DB.

The module's whole claim is that an LGM indemnity is reconstructible from published data
with no modelling, so the spine of this file is the two cases where the right answer is
known without arithmetic:

    test_indemnity_is_zero_at_every_rung_when_the_margin_never_falls_short
    test_indemnity_is_positive_at_every_rung_when_the_margin_always_falls_short

Everything else guards a step where being wrong produces PLAUSIBLE numbers rather than an
error — the failure mode that actually happens here:

    the two A00600 layouts               a LONG file read as WIDE yields empty months
    earliest-expected / latest-actual    reading the back-filled expected re-states the
                                         guarantee to a date the producer could not buy
    the state collapse                   50 identical rows counted as 50 observations
    one observation per sales month      weekly re-quotes counted as new outcomes
    non-overlapping blocks               autocorrelated periods counted as independent
    the three draw dialects              a leg column read from the wrong prefix silently
                                         prices corn as a margin
"""
from __future__ import annotations

import gzip

import numpy as np
import pytest

from src import lgm, lgmbacktest as B


# ---------------------------------------------------------------------------
# Fixtures: hand-written ADM members in each published layout
# ---------------------------------------------------------------------------

WIDE_HEADER = (
    "Record Type Code|Record Category Code|Reinsurance Year|Commodity Year|Commodity Code|"
    "Insurance Plan Code|State Code|County Code|Type Code|Practice Code|Market Symbol Code|"
    + "|".join(f"Month{m} Expected Gross Margin Amount" for m in range(2, 12)) + "|"
    + "|".join(f"Month{m} Actual Gross Margin Amount" for m in range(2, 12))
    + "|Sales Effective Date")

LONG_HEADER = (
    "Record Type Code|Record Category Code|Reinsurance Year|Commodity Year|Commodity Code|"
    "Insurance Plan Code|State Code|County Code|Type Code|Practice Code|Market Symbol Code|"
    "Calendar Month Number|Expected Gross Margin Amount|Actual Gross Margin Amount|"
    "Sales Effective Date")


def wide_row(*, state="19", commodity="0815", type_code="804", sed="20230126",
             expected=None, actual=None, symbol="", ry=2023) -> str:
    e = expected if expected is not None else [100.0] * 5 + [None] * 5
    a = actual if actual is not None else [None] * 10
    cell = lambda v: "" if v is None else f"{v:.4f}"        # noqa: E731
    return "|".join(["A00600", "01", str(ry), str(ry), commodity, "82", state, "998",
                     type_code, "805", symbol]
                    + [cell(v) for v in e] + [cell(v) for v in a] + [sed])


def wide_file(rows) -> str:
    return "\n".join([WIDE_HEADER, *rows])


def long_file(*, state="19", commodity="0815", type_code="804", sed="20210729",
              expected, actual, symbol="", ry=2022) -> str:
    out = [LONG_HEADER]
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e is None and a is None:
            continue
        out.append("|".join(
            ["A00600", "01", str(ry), str(ry), commodity, "82", state, "998", type_code,
             "805", symbol, str(i + 2),
             "" if e is None else f"{e:.4f}", "" if a is None else f"{a:.4f}", sed]))
    return "\n".join(out)


def draw_file(prefixes, n_draws=4, months=range(2, 12), *, commodity="0815",
              type_code="804", state="19", symbol_rows=None, value=1.0) -> str:
    """A00610 in whichever dialect the caller asks for.

    `prefixes` builds prefixed leg columns ("Corn ", ...); `symbol_rows` instead emits one
    row per Market Symbol Code sharing the generic MonthN columns, which is how RY2022 and
    earlier publish component commodities.
    """
    cols = []
    for p in prefixes:
        cols += [f"{p}Month{m} Margin Draw Amount" for m in months]
    header = ("Record Type Code|Reinsurance Year|Commodity Code|Insurance Plan Code|"
              "State Code|Type Code|Market Symbol Code|Margin Draw Number|"
              + "|".join(cols))
    rows = []
    for n in range(1, n_draws + 1):
        for sym in (symbol_rows or [""]):
            vals = []
            for p in prefixes:
                base = value * (1.0 + 0.1 * n) if not sym else _SYM_BASE[sym] * (1 + 0.1 * n)
                vals += [f"{base:.2f}"] * len(list(months))
            rows.append("|".join(["A00610", "2023", commodity, "82", state, type_code,
                                  sym, str(n)] + vals))
    return "\n".join([header, *rows])


_SYM_BASE = {"DA": 20.0, "C": 5.0, "SM": 0.4, "LE": 180.0, "GF": 200.0}


# ---------------------------------------------------------------------------
# THE CLAIM: the indemnity reconstruction
# ---------------------------------------------------------------------------

def _period(expected, actual, commodity="0847", type_code="997"):
    months = lgm.INSURED_MONTHS[commodity]
    return B.SettledPeriod(2024, commodity, type_code, "20240125", months,
                           np.array(expected, float), np.array(actual, float),
                           lgm.DECLARED_RATION.get((commodity, type_code)))


def _flat_draws(period, level):
    return np.full((100, len(period.months)), float(level))


def _spread_draws(period, level, spread=4.0, n=100):
    """Draws centred on `level` and wide enough that RMA's Step 4 premium is not zero.

    A flat draw set prices every rung at zero, which is fine for testing the indemnity but
    makes a loss ratio a division by zero — so anything that needs a denominator uses this.
    """
    rng = np.random.default_rng(0)
    return level + rng.normal(0.0, spread, size=(n, len(period.months)))


def test_indemnity_is_zero_at_every_rung_when_the_margin_never_falls_short():
    """Actual margin above the $0 guarantee => no rung can pay. The floor case.

    A $0 deductible is the LARGEST guarantee LGM sells, so if the realized margin clears it
    then every higher deductible clears by more. Any positive indemnity here would mean the
    MAX(0, ...) or the sign of the deductible is wrong.
    """
    p = _period([15.0] * 10, [22.0] * 10)
    cells = B.realised_curve(p, _flat_draws(p, 15.0))
    assert len(cells) == len(lgm.deductible_grid("0847"))
    assert all(c.indemnity == 0.0 for c in cells)
    assert all(c.loss_ratio == 0.0 for c in cells)
    assert B.is_degenerate(B.pool(cells))
    # And net is exactly minus the producer premium at every rung.
    assert all(c.net_realised == pytest.approx(-c.producer_premium) for c in cells)


def test_indemnity_is_positive_at_every_rung_when_the_margin_always_falls_short():
    """A collapse below even the top deductible's guarantee => every rung pays. The cap case."""
    p = _period([15.0] * 10, [1.0] * 10)
    cells = B.realised_curve(p, _flat_draws(p, 15.0))
    assert all(c.indemnity > 0.0 for c in cells)
    assert not B.is_degenerate(B.pool(cells))
    # Indemnity falls by exactly the deductible times total marketings between rungs.
    by_d = {c.deductible: c.indemnity for c in cells}
    assert by_d[0.0] - by_d[1.0] == pytest.approx(1.0 * 10)


def test_indemnity_is_monotone_non_increasing_in_the_deductible():
    p = _period([15.0] * 10, [9.0] * 10)
    cells = B.realised_curve(p, _flat_draws(p, 15.0))
    ind = [c.indemnity for c in sorted(cells, key=lambda c: c.deductible)]
    assert ind == sorted(ind, reverse=True)


def test_realised_indemnity_matches_rma_step_1b_by_construction():
    """GMG comes from src.lgm, not from a second copy of the formula."""
    h = [1.0] * 10
    egm = lgm.expected_total_gross_margin([15.0] * 10, h)
    gmg = lgm.gross_margin_guarantee(egm, 0.9, h)
    assert B.realised_indemnity(egm, 100.0, 0.9, h) == pytest.approx(gmg - 100.0)
    assert B.realised_indemnity(egm, gmg + 1.0, 0.9, h) == 0.0


def test_unpooled_marketing_plan_zeroes_the_subsidy_at_every_rung():
    """The LGM cliff survives into the measured ladder: it is a plan property, not a rung."""
    p = _period([15.0] * 10, [1.0] * 10)
    h = [1.0] + [0.0] * 9
    cells = B.realised_curve(p, _flat_draws(p, 15.0), h)
    assert all(c.pooled is False for c in cells)
    assert all(c.subsidy == 0.0 for c in cells)
    assert all(c.producer_premium == pytest.approx(c.total_premium) for c in cells)


# ---------------------------------------------------------------------------
# Parsing both layouts
# ---------------------------------------------------------------------------

def test_wide_and_long_layouts_parse_to_the_same_record():
    e = [10.0, 11.0, 12.0, 13.0, 14.0] + [None] * 5
    a = [9.0, 9.5, 10.0, 10.5, 11.0] + [None] * 5
    wide = B.parse_gross_margin(wide_file([wide_row(expected=e, actual=a)]))
    long = B.parse_gross_margin(long_file(expected=e, actual=a, sed="20230126"))
    assert len(wide) == len(long) == 1
    assert wide[0].expected == long[0].expected == tuple(e)
    assert wide[0].actual == long[0].actual == tuple(a)


def test_a_long_file_with_no_sales_date_column_falls_back_to_the_file_stamp():
    text = long_file(expected=[10.0] * 5 + [None] * 5, actual=[None] * 10)
    stripped = "\n".join(line.rsplit("|", 1)[0] for line in text.split("\n"))
    rows = B.parse_gross_margin(stripped, file_stamp="20180727")
    assert rows and rows[0].sales_effective_date == "20180727"


def test_rows_from_other_plans_are_ignored():
    row = wide_row().replace("|82|", "|83|", 1)
    assert B.parse_gross_margin(wide_file([row])) == []


def test_blank_is_not_zero():
    """RMA's encoding for 'not published' is empty, and swine really does stop at month 6."""
    rows = B.parse_gross_margin(wide_file([wide_row()]))
    assert rows[0].expected[5:] == (None,) * 5
    assert rows[0].expected[:5] == (100.0,) * 5


# ---------------------------------------------------------------------------
# The merge: earliest expected, latest actual
# ---------------------------------------------------------------------------

def _batch(stamp, **kw):
    return (stamp, B.parse_gross_margin(wide_file([wide_row(**kw)])))


def test_merge_keeps_the_at_sale_guarantee_and_the_settled_actual():
    """The guarantee is the earliest publication; the settlement is the latest.

    RMA's back-fill delta RE-STATES the expected vector alongside the new actuals, so a
    naive last-wins merge would silently accept whatever expected value the settlement file
    happened to carry. That is the guarantee under test, so it must come from the snapshot
    published on the sales date.
    """
    e0 = [10.0] * 5 + [None] * 5
    e1 = [99.0] * 5 + [None] * 5              # a restated expected in the back-fill
    a1 = [7.0] * 5 + [None] * 5
    merged = B.merge_rows([_batch("20230126", expected=e0),
                           _batch("20231201", expected=e1, actual=a1)])
    (row,) = merged.values()
    assert row.expected[:5] == [10.0] * 5
    assert row.actual[:5] == [7.0] * 5
    assert row.settled


def test_merge_is_order_independent():
    e0 = [10.0] * 5 + [None] * 5
    a1 = [7.0] * 5 + [None] * 5
    forward = B.merge_rows([_batch("20230126", expected=e0),
                            _batch("20231201", expected=e0, actual=a1)])
    backward = B.merge_rows([_batch("20231201", expected=e0, actual=a1),
                             _batch("20230126", expected=e0)])
    assert {k: (v.expected, v.actual) for k, v in forward.items()} == \
           {k: (v.expected, v.actual) for k, v in backward.items()}


def test_a_forward_only_file_is_not_settled():
    """A file published during the sales window proves nothing about the actual columns."""
    merged = B.merge_rows([_batch("20230126", expected=[10.0] * 5 + [None] * 5)])
    assert not next(iter(merged.values())).settled


def test_partial_actuals_are_not_settled():
    """Cattle publishes some actual legs at sale; a period is settled only when ALL are in."""
    e = [10.0] * 5 + [None] * 5
    a = [9.0, 9.0, None, None, None] + [None] * 5
    merged = B.merge_rows([_batch("20230126", expected=e, actual=a)])
    assert not next(iter(merged.values())).settled


# ---------------------------------------------------------------------------
# The three collapses that decide n
# ---------------------------------------------------------------------------

def test_state_collapse_drops_fifty_copies_of_one_observation():
    rows = [wide_row(state=f"{s:02d}") for s in range(1, 51)]
    merged = B.merge_rows([("20230126", B.parse_gross_margin(wide_file(rows)))])
    assert len(merged) == 50
    national, n_states = B.collapse_states(merged)
    assert len(national) == 1 and n_states == 50


def test_state_collapse_refuses_to_average_a_real_divergence():
    """If LGM ever gains a state basis this must fail loudly, not quietly mean it away."""
    rows = [wide_row(state="19"),
            wide_row(state="27", expected=[123.0] * 5 + [None] * 5)]
    merged = B.merge_rows([("20230126", B.parse_gross_margin(wide_file(rows)))])
    with pytest.raises(B.StateDivergence):
        B.collapse_states(merged)


def _p(sed, cc="0847", tc="997"):
    months = lgm.INSURED_MONTHS[cc]
    n = len(months)
    return B.SettledPeriod(2024, cc, tc, sed, months, np.ones(n), np.ones(n),
                           lgm.DECLARED_RATION.get((cc, tc)))


def test_one_observation_per_sales_month_takes_the_last_thursday_by_default():
    weekly = [_p(s) for s in ("20240104", "20240111", "20240118", "20240125",
                              "20240201", "20240208")]
    last = B.one_per_sales_month(weekly)
    assert [p.sales_effective_date for p in last] == ["20240125", "20240208"]
    first = B.one_per_sales_month(weekly, lead="first")
    assert [p.sales_effective_date for p in first] == ["20240104", "20240201"]


def test_independent_blocks_step_by_the_length_of_the_insurance_period():
    """Ten-month periods sold monthly overlap in nine months; only every tenth is disjoint."""
    monthly = [_p(f"2024{m:02d}25") for m in range(1, 13)] + \
              [_p(f"2025{m:02d}25") for m in range(1, 13)]
    got = B.independent_blocks(monthly)
    assert len(got) == 3                       # 24 monthly periods, ten-month periods
    assert [p.sales_effective_date for p in got] == ["20240125", "20241125", "20250925"]


def test_swine_periods_are_shorter_so_more_of_them_are_independent():
    monthly = [_p(f"2024{m:02d}25", cc="0815", tc="804") for m in range(1, 13)]
    assert len(lgm.INSURED_MONTHS["0815"]) == 5
    assert len(B.independent_blocks(monthly)) == 3


# ---------------------------------------------------------------------------
# Draw dialects
# ---------------------------------------------------------------------------

def test_composite_commodity_reads_the_generic_columns():
    months = tuple(range(2, 7))
    text = draw_file([""], months=months, value=100.0)
    mat = B.draw_matrix(text, "0815", "804", "19", months,
                        lgm.DECLARED_RATION[("0815", "804")], legs=())
    assert mat.shape == (4, 5)
    assert mat[0, 0] == pytest.approx(110.0)


def test_prefixed_leg_columns_are_combined_with_the_ration():
    """RY2025+ dairy: one row, Dairy / Corn / SoyM prefixes, margin assembled here."""
    months = tuple(range(2, 12))
    text = draw_file(["Dairy ", "Corn ", "SoyM "], months=months,
                     commodity="0847", type_code="997")
    ration = lgm.DECLARED_RATION[("0847", "997")]
    mat = B.draw_matrix(text, "0847", "997", "19", months, ration, legs=("C", "DA", "SM"))
    assert mat.shape == (4, 10)
    # value defaults to 1.0 and every leg gets the same number, so the composite is
    # v*(1 - corn_bu - sbm_ton) with output_cwt = 1.
    v = 1.1
    assert mat[0, 0] == pytest.approx(
        v * ration.output_cwt - v * ration.corn_bu - v * ration.soybean_meal_ton)


def test_generic_columns_split_by_market_symbol_are_combined_the_same_way():
    """RY2022 dairy: three ROWS per draw, one per leg, all in the generic MonthN columns."""
    months = tuple(range(2, 12))
    text = draw_file([""], months=months, symbol_rows=["DA", "C", "SM"],
                     commodity="0847", type_code="997")
    ration = lgm.DECLARED_RATION[("0847", "997")]
    mat = B.draw_matrix(text, "0847", "997", "19", months, ration, legs=("C", "DA", "SM"))
    assert mat.shape == (4, 10)
    assert mat[0, 0] == pytest.approx(
        22.0 * ration.output_cwt - 5.5 * ration.corn_bu - 0.44 * ration.soybean_meal_ton)


def test_a_missing_leg_returns_none_rather_than_a_partial_margin():
    months = tuple(range(2, 12))
    text = draw_file([""], months=months, symbol_rows=["DA", "C"],
                     commodity="0847", type_code="997")
    ration = lgm.DECLARED_RATION[("0847", "997")]
    assert B.draw_matrix(text, "0847", "997", "19", months, ration,
                         legs=("C", "DA", "SM")) is None


def test_validate_draws_flags_a_mis_assembled_margin():
    p = _period([15.0] * 10, [15.0] * 10)
    good = np.full((50, 10), 15.0)
    bad = np.full((50, 10), 5.0)        # e.g. a corn price read as a margin
    assert B.validate_draws(p, good) == pytest.approx(0.0)
    assert B.validate_draws(p, bad) > 0.5


# ---------------------------------------------------------------------------
# Aggregation and the honesty guards
# ---------------------------------------------------------------------------

def test_pool_sums_realized_indemnity_against_rated_premium():
    p1 = _period([15.0] * 10, [1.0] * 10)
    p2 = _period([15.0] * 10, [22.0] * 10)
    cells = B.realised_curve(p1, _spread_draws(p1, 15.0)) + \
        B.realised_curve(p2, _spread_draws(p2, 15.0))
    rungs = B.pool(cells)
    assert {r.n_periods for r in rungs} == {2}
    zero = next(r for r in rungs if r.deductible == 0.0)
    assert zero.n_paid == 1
    assert zero.pay_rate == pytest.approx(0.5)
    assert zero.loss_ratio == pytest.approx(zero.indemnity / zero.total_premium)


def test_return_per_producer_dollar_is_the_repos_identity():
    p = _period([15.0] * 10, [8.0] * 10)
    rungs = B.pool(B.realised_curve(p, _spread_draws(p, 15.0)))
    for r in rungs:
        assert r.return_per_producer_dollar == pytest.approx(
            lgm.return_per_producer_dollar(r.loss_ratio, r.subsidy))


def test_best_rung_breaks_ties_toward_the_lower_deductible():
    rungs = [B.LadderRung("0815", "804", d, 0.5, 10, 0, 100.0, 50.0, 60.0)
             for d in (0.0, 2.0, 4.0)]
    assert B.best_rung(rungs, "net").deductible == 0.0
    assert B.best_rung(rungs, "per_dollar").deductible == 0.0


def test_best_rung_ranks_net_on_dollars_not_on_premium_normalised_dollars():
    """The two disagree, and dollars is the metric src.lgm.optimal_deductible('gain') uses.

    Total premium shrinks with the deductible, so net/premium flatters the top of the grid.
    A rung that nets $100 on $1,000 of premium beats one that nets $30 on $60 in the only
    sense a producer holding a fixed marketing plan cares about.
    """
    big = B.LadderRung("0815", "804", 0.0, 0.18, 10, 5, 1000.0, 820.0, 920.0)   # net 100
    small = B.LadderRung("0815", "804", 20.0, 0.50, 10, 1, 60.0, 30.0, 60.0)    # net 30
    assert big.net_realised > small.net_realised
    assert small.net_per_premium_dollar > big.net_per_premium_dollar
    assert B.best_rung([big, small], "net") is big


def test_degenerate_ladders_are_flagged_rather_than_given_an_argmax():
    rungs = [B.LadderRung("0803", "807", d, 0.5, 57, 0, 1000.0 - d, 500.0 - d / 2, 0.0)
             for d in (0.0, 70.0, 150.0)]
    assert B.is_degenerate(rungs)
    rungs[1].indemnity = 1.0
    assert not B.is_degenerate(rungs)


# ---------------------------------------------------------------------------
# The window boundary
# ---------------------------------------------------------------------------

def test_pre_2022_reinsurance_years_are_refused_by_name():
    """No Sales Effective Date means no guarantee to test. Refuse, do not guess."""
    assert B.FIRST_BACKTESTABLE_RY == 2022
    with pytest.raises(ValueError, match="Sales Effective Date"):
        B.settled_periods(2021)


def test_parse_listing_only_takes_the_asked_for_year():
    html = ("2026_ADMLivestockLgm_Daily_20250703.zip "
            "2027_ADMLivestockLgm_Daily_20260702.zip "
            "2026_ADMLivestockLgm_Daily_20250710.zip")
    assert B.parse_listing(html, 2026) == ["2026_ADMLivestockLgm_Daily_20250703.zip",
                                           "2026_ADMLivestockLgm_Daily_20250710.zip"]


def test_load_history_reads_the_gzipped_cache(tmp_path):
    p = tmp_path / "2023_ADMLivestockLgm_Daily_20230126_A00600.txt.gz"
    p.write_bytes(gzip.compress(wide_file([wide_row()]).encode()))
    merged = B.load_history(2023, tmp_path)
    assert len(merged) == 1
    assert next(iter(merged)) == ("0815", "804", "19", "", "20230126")


def test_settled_periods_drops_a_partly_published_period(tmp_path):
    """Swine must have all five insurable months, not three of them."""
    e = [10.0, 11.0, 12.0, None, None] + [None] * 5
    a = [9.0, 9.0, 9.0, None, None] + [None] * 5
    p = tmp_path / "2023_ADMLivestockLgm_Daily_20231201_A00600.txt.gz"
    p.write_bytes(gzip.compress(wide_file([wide_row(expected=e, actual=a)]).encode()))
    assert B.settled_periods(2023, tmp_path) == []


# ---------------------------------------------------------------------------
# The note that lives here because the file it applies to is not ours
# ---------------------------------------------------------------------------

def test_lgm_tab_note_still_quotes_the_sentence_it_replaces():
    """The note is a REPLACEMENT for live text; if that text moves, the note is stale.

    Same contract as src.lgm.SOB_GATE_NOTE: a constant describing a change to a file this
    module does not own is only useful while it still matches that file.
    """
    # The replacement has now BEEN APPLIED, so this guard flips: it no longer checks that
    # the stale sentence is still there to be replaced, it checks that it is gone and did
    # not come back. src/lgm.py's docstring and the LGM tab are both corrected.
    doc = " ".join(lgm.__doc__.split())
    assert "never backtested" not in doc, "the stale claim returned to src/lgm.py"
    assert "A00600" in doc, "the docstring must name the file that makes it backtestable"
    assert "lgmbacktest" in doc, "and point at the module that does it"
    # The note itself still carries the before/after so the history stays legible.
    assert "Do not simply append this" in B.LGM_TAB_NOTE


def test_lgm_tab_note_names_the_module_that_does_the_work():
    flat = " ".join(B.LGM_TAB_NOTE.split())
    assert "src/lgmbacktest.py" in flat
    assert "A00600 LgmGrossMargin" in flat
    assert "ACTUAL Gross Margin Amount" in flat
