"""Tests for src/lgm.py — LGM (plan 82), the margin leg. No network, no live DB.

The spine of this file is RMA's OWN worked example, reproduced verbatim from "Livestock
Gross Margin for Cattle Insurance Policy — Step by Step Instructions to Calculate Premium"
(July 2020): a February-to-December yearling period, a ten-month marketing plan, ten
published simulated-margin rows, and RMA's printed intermediate results at every step
(EGM $156,136.00, first SGM $137,431.00, the ten simulated losses, and — once the mean of
ALL 5,000 losses is supplied as $23,415.01 — total premium $24,117.46 and producer premium
$19,776 at the 18% subsidy for a $0 deductible with pooled coverage).

Three tests exist because getting them wrong yields plausible numbers rather than an error,
which is the failure mode that matters:

    test_zero_deductible_is_subsidised_at_18pct  — the claim this module was built to check
    test_unpooled_zeroes_subsidy_at_every_deductible — where the real zero-subsidy cliff is
    test_net_gain_optimum_is_interior            — the whole economic argument
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from src import db, lgm


# ---------------------------------------------------------------------------
# RMA's published worked example (LGM-Cattle Premium Calculation, July 2020)
# ---------------------------------------------------------------------------

# p(2)..p(11), March through December, $/head.
RMA_EXPECTED = [223.45, 240.92, 211.39, 191.38, 160.89, 163.84, 144.31, 165.78,
                207.88, 239.65]

# h(2)..h(11), the marketing plan.
RMA_MARKETINGS = [100, 100, 0, 0, 200, 200, 0, 0, 100, 100]

# The first ten rows of simulated gross margins RMA prints.
RMA_DRAWS = np.array([
    [205.37, 195.27, 142.79, 97.53, 114.66, 166.39, 167.11, 191.83, 206.49, 205.08],
    [321.92, 392.24, 302.19, 226.54, 183.38, 177.96, 160.96, 203.15, 244.06, 279.25],
    [263.05, 333.50, 254.45, 183.00, 123.76, 105.15, 149.90, 231.11, 366.45, 502.48],
    [210.06, 233.27, 190.16, 155.14, 172.88, 240.44, 262.79, 302.11, 362.70, 410.95],
    [196.37, 225.38, 195.71, 167.13, 125.11, 127.18, 101.19, 125.10, 166.66, 190.04],
    [331.21, 348.83, 389.50, 432.60, 401.84, 409.69, 399.11, 418.66, 502.10, 577.80],
    [212.36, 194.63, 119.39, 53.76, 68.24, 117.30, 89.74, 121.30, 90.05, 44.64],
    [271.75, 365.53, 318.38, 275.75, 145.88, 62.66, 33.34, 88.89, 215.26, 336.78],
    [190.92, 154.99, 177.38, 211.29, 202.91, 222.23, 195.45, 187.58, 152.99, 103.48],
    [189.70, 169.43, 160.98, 161.36, 213.89, 303.59, 325.81, 314.48, 313.11, 309.09],
])

RMA_SGM = [137431.00, 196015.00, 192330.00, 204362.00, 128303.00,
           338300.00, 91276.00, 160640.00, 145266.00, 201629.00]
RMA_LOSSES = [18705.00, 0.00, 0.00, 0.00, 27833.00, 0.00, 64860.00, 0.00, 10870.00, 0.00]
RMA_EGM = 156136.00
RMA_MEAN_LOSS_ALL_DRAWS = 23415.01
RMA_TOTAL_PREMIUM = 24117.46
RMA_PRODUCER_PREMIUM = 19776


def test_expected_total_gross_margin_matches_rma():
    assert lgm.expected_total_gross_margin(RMA_EXPECTED, RMA_MARKETINGS) == RMA_EGM


def test_gross_margin_guarantee_at_zero_deductible_equals_egm():
    assert lgm.gross_margin_guarantee(RMA_EGM, 0.0, RMA_MARKETINGS) == RMA_EGM


def test_gross_margin_guarantee_bites_on_total_marketed_quantity():
    # 800 head marketed across the period; $10/head takes $8,000 off the guarantee.
    assert sum(RMA_MARKETINGS) == 800
    assert lgm.gross_margin_guarantee(RMA_EGM, 10.0, RMA_MARKETINGS) == RMA_EGM - 8000.0


def test_simulated_total_gross_margins_match_rma():
    sgm = lgm.simulated_total_gross_margins(RMA_DRAWS, RMA_MARKETINGS)
    assert list(sgm) == RMA_SGM


def test_simulated_losses_match_rma():
    sgm = lgm.simulated_total_gross_margins(RMA_DRAWS, RMA_MARKETINGS)
    losses = lgm.simulated_losses(RMA_EGM, sgm)
    assert list(losses) == RMA_LOSSES


def test_total_premium_matches_rma_when_given_the_full_draw_mean():
    """Steps 4-5 against RMA's printed $23,415.01 average of all simulated losses."""
    losses = np.full(5000, RMA_MEAN_LOSS_ALL_DRAWS)
    assert lgm.premium_from_losses(losses) == RMA_MEAN_LOSS_ALL_DRAWS
    # Step 5 rounds to whole dollars; RMA prints the unrounded 24,117.46.
    assert lgm.LOADING_FACTOR * RMA_MEAN_LOSS_ALL_DRAWS == pytest.approx(
        RMA_TOTAL_PREMIUM, abs=0.005)
    assert lgm.total_premium_from_losses(losses) == round(RMA_TOTAL_PREMIUM)


def test_producer_premium_matches_rma():
    s = lgm.subsidy_rate("0803", 0.0, pooled=True)
    assert s == 0.18
    assert lgm.producer_premium(RMA_TOTAL_PREMIUM, s) == RMA_PRODUCER_PREMIUM


def test_premium_divides_by_the_draws_supplied_not_by_5000():
    """The published ADM file carries 500 draws; the instructions say 5,000."""
    losses = np.array([100.0] * 500)
    assert lgm.premium_from_losses(losses) == 100.0
    assert lgm.premium_from_losses(np.array([100.0] * 5000)) == 100.0
    assert lgm.premium_from_losses(np.array([0.0, 200.0])) == 100.0


# ---------------------------------------------------------------------------
# The subsidy structure — the claim this module exists to settle
# ---------------------------------------------------------------------------

def test_zero_deductible_is_subsidised_at_18pct_not_zero():
    """A $0 deductible draws the BOTTOM rung of the ladder, not no subsidy at all."""
    for cc in ("0803", "0815", "0847"):
        assert lgm.subsidy_rate(cc, 0.0, pooled=True) == 0.18


def test_subsidy_is_keyed_on_deductible_and_rises_monotonically_to_a_cap():
    for cc in ("0803", "0815", "0847"):
        grid = lgm.deductible_grid(cc)
        rates = [lgm.subsidy_rate(cc, d) for d in grid]
        assert rates == sorted(rates), cc
        assert rates[0] == 0.18 and rates[-1] == 0.50, cc
        # The cap is reached strictly before the top of the grid, which is what makes the
        # net-gain optimum interior.
        assert rates.index(0.50) < len(grid) - 1, cc


def test_unpooled_zeroes_subsidy_at_every_deductible():
    """The real zero-subsidy cliff is the marketing plan, not the deductible."""
    for cc in ("0803", "0815", "0847"):
        for d in lgm.deductible_grid(cc):
            assert lgm.subsidy_rate(cc, d, pooled=False) == 0.0, (cc, d)


def test_is_pooled_needs_two_months_of_target_marketings():
    assert lgm.is_pooled([1, 1, 0, 0]) is True
    assert lgm.is_pooled([0, 5, 0, 0]) is False
    assert lgm.is_pooled([0, 0, 0, 0]) is False
    assert lgm.is_pooled(RMA_MARKETINGS) is True


def test_beginning_farmer_ladder():
    base = lgm.subsidy_rate("0803", 0.0)
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=1) == pytest.approx(base + 0.15)
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=2) == pytest.approx(base + 0.15)
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=3) == pytest.approx(base + 0.13)
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=4) == pytest.approx(base + 0.11)
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=5) == pytest.approx(base + 0.10)
    # Without the OBBBA ladder it is the flat policy s5(f) 10 points at every year.
    assert lgm.subsidy_rate("0803", 0.0, bfr_year=1, obbba=False) == pytest.approx(
        base + 0.10)
    # An unpooled BFR is still unsubsidised: eligibility gates before the bump.
    assert lgm.subsidy_rate("0803", 0.0, pooled=False, bfr_year=1) == 0.0
    with pytest.raises(ValueError):
        lgm.subsidy_rate("0803", 0.0, bfr_year=0)


def test_subsidy_refuses_a_deductible_off_the_filed_grid():
    with pytest.raises(ValueError):
        lgm.subsidy_rate("0803", 15.0)          # cattle steps in $10
    with pytest.raises(ValueError):
        lgm.subsidy_rate("0815", 3.0)           # swine steps in $2
    with pytest.raises(ValueError):
        lgm.subsidy_rate("0847", 0.15)          # dairy steps in $0.10
    with pytest.raises(KeyError):
        lgm.subsidy_rate("0999", 0.0)


def test_lgm_subsidy_ladders_differ_from_the_lrp_and_drp_coverage_level_ladders():
    """The head-to-heads are between different KINDS of schedule, not just numbers."""
    assert set(lgm.SUBSIDY_BY_DEDUCTIBLE) == {"0803", "0815", "0847"}
    # LRP and DRP are keyed on coverage level in [0,1]; LGM on dollars of deductible.
    assert max(lgm.LRP_SUBSIDY_BY_COVERAGE) <= 1.0
    assert max(lgm.DRP_SUBSIDY_BY_COVERAGE) <= 1.0
    assert max(lgm.SUBSIDY_BY_DEDUCTIBLE["0803"]) == 150.0
    # LGM's ceiling (0.50) is below DRP's floor-level best (0.55 at 0.80 coverage) and
    # equal to LRP's 0.80-coverage rate.
    assert max(lgm.SUBSIDY_BY_DEDUCTIBLE["0803"].values()) == 0.50
    assert lgm.DRP_SUBSIDY_BY_COVERAGE[0.80] == 0.55
    assert lgm.LRP_SUBSIDY_BY_COVERAGE[0.800] == 0.50


# ---------------------------------------------------------------------------
# The economics
# ---------------------------------------------------------------------------

def test_return_per_producer_dollar_identity():
    assert lgm.return_per_producer_dollar(1.0, 0.50) == pytest.approx(2.0)
    assert lgm.return_per_producer_dollar(1.0, 0.18) == pytest.approx(1.0 / 0.82)
    assert lgm.return_per_producer_dollar(1.0, 0.0) == pytest.approx(1.0)


def test_net_expected_gain_accounts_for_the_103_loading():
    """The 3% load means break-even is a 2.91% subsidy, not a 0% one."""
    assert lgm.break_even_subsidy() == pytest.approx(1.0 - 1.0 / 1.03)
    assert lgm.break_even_subsidy() == pytest.approx(0.029126, abs=1e-6)
    # An unsubsidised (unpooled) LGM purchase is value-destroying by exactly the load.
    assert lgm.net_expected_gain(10_000.0, 0.0) == pytest.approx(
        10_000.0 * (1 / 1.03 - 1.0))
    assert lgm.net_expected_gain(10_000.0, 0.0) < 0
    # A $0-deductible pooled purchase is still positive, contra "no federal advantage".
    assert lgm.net_expected_gain(10_000.0, 0.18) > 0


def test_net_expected_gain_honours_a_realized_loss_ratio():
    assert lgm.net_expected_gain(100.0, 0.50, loss_ratio=1.0) == pytest.approx(50.0)
    assert lgm.net_expected_gain(100.0, 0.50, loss_ratio=0.5) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# The deductible curve
# ---------------------------------------------------------------------------

def _panel(scale: float = 2.0, common: float = 0.30, idio: float = 0.10,
           n: int = 2000, seed: int = 20260808):
    """A structurally real cattle panel: 10 months of CORRELATED margin draws.

    The correlation matters and is not cosmetic. RMA's real draws share one price path
    across the whole insurance period, so the TOTAL margin stays volatile; independent
    monthly draws would diversify most of that away and put premium at ~3% of expected
    total margin instead of the ~12-24% the published ADM draws actually produce. Since
    the deductible's bite is measured against that spread, an uncorrelated fixture moves
    the optimum all the way to $0 and would quietly test the wrong shape.

    `scale` lifts RMA's 2020 worked-example margins toward the 2026 level.
    """
    rng = np.random.default_rng(seed)
    expected = np.array(RMA_EXPECTED, float) * scale
    z = (rng.normal(0.0, common, size=(n, 1))
         + rng.normal(0.0, idio, size=(n, expected.size)))
    draws = expected * np.exp(z - 0.5 * (common ** 2 + idio ** 2))
    return expected, draws


@pytest.fixture
def cattle_panel():
    return _panel()


def test_deductible_curve_premium_falls_and_subsidy_rises(cattle_panel):
    expected, draws = cattle_panel
    h = lgm.uniform_marketings(len(expected), 100)
    curve = lgm.deductible_curve("0803", "808", "19", expected, draws, h)
    assert [c.deductible for c in curve] == lgm.deductible_grid("0803")
    prem = [c.total_premium for c in curve]
    subs = [c.subsidy for c in curve]
    assert prem == sorted(prem, reverse=True)
    assert subs == sorted(subs)
    assert all(c.pooled for c in curve)
    # The guarantee shrinks as the deductible grows.
    ret = [c.guarantee_retained for c in curve]
    assert ret == sorted(ret, reverse=True)
    assert curve[0].guarantee_retained == pytest.approx(1.0)


def test_net_gain_optimum_is_interior(cattle_panel):
    """The whole economic argument: the product of a rising rate and a falling base peaks
    strictly inside the grid, at neither end."""
    expected, draws = cattle_panel
    h = lgm.uniform_marketings(len(expected), 100)
    curve = lgm.deductible_curve("0803", "808", "19", expected, draws, h)
    best = lgm.optimal_deductible(curve, "gain")
    assert best.deductible != curve[0].deductible
    assert best.deductible != curve[-1].deductible
    assert best.net_expected_gain > curve[0].net_expected_gain
    assert best.net_expected_gain > curve[-1].net_expected_gain


def test_the_three_objectives_disagree(cattle_panel):
    """Maximising return per producer dollar, net dollars, and protection are three
    different questions with three different answers."""
    expected, draws = cattle_panel
    h = lgm.uniform_marketings(len(expected), 100)
    curve = lgm.deductible_curve("0803", "808", "19", expected, draws, h)
    gain = lgm.optimal_deductible(curve, "gain")
    per_dollar = lgm.optimal_deductible(curve, "per_dollar")
    protection = lgm.optimal_deductible(curve, "protection")
    assert protection.deductible == 0.0
    assert per_dollar.subsidy == 0.50
    assert per_dollar.return_per_producer_dollar == pytest.approx(
        lgm.return_per_producer_dollar(1 / lgm.LOADING_FACTOR, 0.50))
    assert gain.deductible < per_dollar.deductible
    assert protection.deductible < gain.deductible
    # per_dollar picks the CHEAPEST deductible that reaches the cap, not the most expensive.
    assert per_dollar.deductible == min(
        c.deductible for c in curve if c.subsidy == 0.50)


def test_return_per_producer_dollar_is_blind_above_the_cap(cattle_panel):
    """The repo's usual metric cannot rank the top of the LGM grid at all.

    Once the ladder caps at 0.50, return per producer dollar is pinned at 1.94 for every
    remaining deductible while net expected gain falls away — so a producer optimising the
    familiar metric gets no signal that they are giving up most of the benefit.
    """
    expected, draws = cattle_panel
    h = lgm.uniform_marketings(len(expected), 100)
    curve = lgm.deductible_curve("0803", "808", "19", expected, draws, h)
    plateau = [c for c in curve if c.subsidy == 0.50]
    assert len(plateau) > 1
    assert len({round(c.return_per_producer_dollar, 9) for c in plateau}) == 1
    # Net gain, by contrast, falls monotonically across that same plateau.
    gains = [c.net_expected_gain for c in plateau]
    assert gains == sorted(gains, reverse=True)
    assert gains[-1] < 0.6 * gains[0]


def test_optimum_depends_on_the_margin_spread_not_on_a_constant():
    """$70 is not a property of LGM-Cattle; it is a property of this year's price spread.

    Widen the simulated margin distribution and the optimal deductible rises, because the
    guarantee stays in the money further out. This is why the module recomputes the curve
    per (commodity, type, state, sales date) instead of shipping a hardcoded answer.
    """
    tight = lgm.optimal_deductible(
        lgm.deductible_curve("0803", "808", "19", *_panel(common=0.18),
                             marketings=lgm.uniform_marketings(10, 100)), "gain")
    wide = lgm.optimal_deductible(
        lgm.deductible_curve("0803", "808", "19", *_panel(common=0.45),
                             marketings=lgm.uniform_marketings(10, 100)), "gain")
    assert wide.deductible > tight.deductible


def test_unpooled_curve_is_uniformly_value_destroying(cattle_panel):
    expected, draws = cattle_panel
    h = [0.0] * len(expected)
    h[0] = 100.0
    curve = lgm.deductible_curve("0803", "808", "19", expected, draws, h)
    assert not any(c.pooled for c in curve)
    assert all(c.subsidy == 0.0 for c in curve)
    assert all(c.net_expected_gain <= 0 for c in curve)
    assert all(c.return_per_producer_dollar < 1.0 for c in curve)


def test_curve_scales_linearly_with_marketed_quantity(cattle_panel):
    """Premium and gain are pure size; only the deductible changes the shape."""
    expected, draws = cattle_panel
    a = lgm.deductible_curve("0803", "808", "19", expected, draws,
                             lgm.uniform_marketings(len(expected), 100))
    b = lgm.deductible_curve("0803", "808", "19", expected, draws,
                             lgm.uniform_marketings(len(expected), 200))
    for ca, cb in zip(a, b):
        assert cb.total_premium == pytest.approx(2 * ca.total_premium, rel=1e-3)
        assert cb.subsidy == ca.subsidy
        assert cb.return_per_producer_dollar == pytest.approx(ca.return_per_producer_dollar)


def test_optimal_deductible_rejects_nonsense():
    with pytest.raises(ValueError):
        lgm.optimal_deductible([])
    with pytest.raises(ValueError):
        lgm.optimal_deductible([object()], "sideways")  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# The ration — LGM's basis risk
# ---------------------------------------------------------------------------

def test_declared_rations_match_the_handbooks():
    """Verbatim constants from the LGM Cattle / Swine / Dairy handbooks."""
    calf = lgm.ration_for("0803", "807")
    assert (calf.feeder_cwt, calf.output_cwt, calf.corn_bu) == (5.5, 11.5, 52.0)
    assert calf.name == "Calf Finishing"
    yearling = lgm.ration_for("0803", "808")
    assert (yearling.feeder_cwt, yearling.output_cwt, yearling.corn_bu) == (7.5, 12.5, 50.0)
    assert yearling.name == "Yearling Finishing"

    f2f = lgm.ration_for("0815", "804")
    assert f2f.corn_bu == 12.0
    assert f2f.soybean_meal_ton == pytest.approx(138.55 / 2000.0)
    assert f2f.output_cwt == 2.6
    assert lgm.ration_for("0815", "805").soybean_meal_ton == pytest.approx(82.0 / 2000.0)
    assert lgm.ration_for("0815", "806").corn_bu == 9.05

    dairy = lgm.ration_for("0847", "997")
    assert dairy.soybean_meal_ton == pytest.approx(0.002)
    # 0.014 tons of corn per cwt, converted at the handbook's own 2,000/56 = 0.5 bushels.
    assert dairy.corn_bu == pytest.approx(0.5)
    assert dairy.output_cwt == 1.0


def test_only_swine_has_a_locked_ration():
    assert lgm.ration_for("0803", "807").electable is True
    assert lgm.ration_for("0847", "997").electable is True
    for t in ("804", "805", "806"):
        assert lgm.ration_for("0815", t).electable is False
        assert ("0815", t) not in lgm.RATION_BANDS


def test_ration_divergence_inside_the_band_is_eliminable():
    d = lgm.ration_divergence(
        "0803", "808",
        lgm.Ration("0803", "808", corn_bu=65.0, feeder_cwt=8.0, output_cwt=13.5))
    assert d.deltas["corn_bu"] == pytest.approx(15.0)
    assert all(d.within_band[k] for k in ("corn_bu", "feeder_cwt", "output_cwt"))
    assert d.eliminable is True
    assert "ELIMINABLE" in d.verdict


def test_ration_divergence_outside_the_band_is_irreducible():
    d = lgm.ration_divergence(
        "0803", "808",
        lgm.Ration("0803", "808", corn_bu=110.0, feeder_cwt=8.0, output_cwt=13.5))
    assert d.within_band["corn_bu"] is False
    assert d.eliminable is False
    assert "IRREDUCIBLE" in d.verdict


def test_cattle_max_gain_constraint_is_enforced():
    """Live minus feeder weight may not exceed 6 cwt for yearling finishing."""
    ok = lgm.ration_divergence(
        "0803", "808",
        lgm.Ration("0803", "808", corn_bu=60.0, feeder_cwt=9.0, output_cwt=15.0))
    assert ok.within_band["gain_cwt"] is True
    bad = lgm.ration_divergence(
        "0803", "808",
        lgm.Ration("0803", "808", corn_bu=60.0, feeder_cwt=6.5, output_cwt=15.0))
    assert bad.within_band["gain_cwt"] is False
    assert bad.eliminable is False


def test_swine_divergence_is_never_eliminable():
    d = lgm.ration_divergence(
        "0815", "804",
        lgm.Ration("0815", "804", corn_bu=15.0, soybean_meal_ton=0.08, output_cwt=2.8))
    assert d.electable is False
    assert d.eliminable is False
    assert d.within_band == {}
    assert "IRREDUCIBLE" in d.verdict


def test_ration_divergence_on_the_declared_ration_is_flat():
    same = lgm.ration_for("0847", "997")
    d = lgm.ration_divergence("0847", "997", same)
    assert all(abs(v) < 1e-12 for v in d.deltas.values())
    assert d.verdict == "on the declared ration"


def test_ration_divergence_level_gap_in_dollars():
    prices = {"output_price": 20.00, "corn_price": 4.50, "soybean_meal_price": 330.0}
    heavy = lgm.Ration("0847", "997", corn_bu=0.9, soybean_meal_ton=0.0035, output_cwt=1.0)
    d = lgm.ration_divergence("0847", "997", heavy, prices=prices)
    # Feeds more than RMA assumes, so the real margin is BELOW the insured one.
    assert d.expected_margin_gap < 0
    expected_gap = -((0.9 - 0.5) * 4.50 + (0.0035 - 0.002) * 330.0)
    assert d.expected_margin_gap == pytest.approx(expected_gap)


def test_ration_divergence_risk_measure_across_draws():
    """The number that is actually basis risk: variance the policy does not track."""
    rng = np.random.default_rng(7)
    n = 4000
    draws = {"output_price": rng.normal(20.0, 2.0, n),
             "corn_price": rng.normal(4.50, 0.80, n),
             "soybean_meal_price": rng.normal(330.0, 45.0, n)}
    on_ration = lgm.ration_divergence("0847", "997", lgm.ration_for("0847", "997"),
                                      price_draws=draws)
    assert on_ration.residual_sd == pytest.approx(0.0, abs=1e-12)
    assert on_ration.tracking_corr == pytest.approx(1.0)
    assert on_ration.unexplained_variance_share == pytest.approx(0.0, abs=1e-12)

    heavy = lgm.Ration("0847", "997", corn_bu=2.0, soybean_meal_ton=0.010, output_cwt=1.0)
    off = lgm.ration_divergence("0847", "997", heavy, price_draws=draws)
    assert off.residual_sd > 0
    assert off.tracking_corr < 1.0
    assert 0.0 < off.unexplained_variance_share < 1.0
    # Feeding four times the assumed corn tracks strictly worse than feeding twice.
    mild = lgm.Ration("0847", "997", corn_bu=1.0, soybean_meal_ton=0.004, output_cwt=1.0)
    off_mild = lgm.ration_divergence("0847", "997", mild, price_draws=draws)
    assert off.unexplained_variance_share > off_mild.unexplained_variance_share


def test_ration_divergence_validates_price_draws():
    with pytest.raises(ValueError):
        lgm.ration_divergence("0847", "997", lgm.ration_for("0847", "997"),
                              price_draws={"nonsense": np.zeros(3)})
    with pytest.raises(ValueError):
        lgm.ration_divergence("0847", "997", lgm.ration_for("0847", "997"),
                              price_draws={"output_price": np.zeros(3),
                                           "corn_price": np.zeros(4)})


def test_margin_per_unit_shapes():
    cattle = lgm.margin_per_unit(lgm.ration_for("0803", "808"), output_price=225.0,
                                 feeder_price=360.0, corn_price=4.50)
    assert cattle == pytest.approx(225.0 * 12.5 - 360.0 * 7.5 - 4.50 * 50.0)
    swine = lgm.margin_per_unit(lgm.ration_for("0815", "805"), output_price=82.0,
                                corn_price=4.50, soybean_meal_price=330.0)
    assert swine == pytest.approx(82.0 * 2.6 - 4.50 * 9.0 - (82.0 / 2000.0) * 330.0)


def test_ration_for_unknown_type_raises():
    with pytest.raises(KeyError):
        lgm.ration_for("0803", "999")


# ---------------------------------------------------------------------------
# ADM parsing — structurally real, no network
# ---------------------------------------------------------------------------

GM_HEADER = ("Record Type Code|Record Category Code|Reinsurance Year|Commodity Year|"
             "Commodity Code|Insurance Plan Code|State Code|County Code|Type Code|"
             "Practice Code|Market Symbol Code|Interval Code|"
             + "|".join(f"Month{m} Expected Gross Margin Amount" for m in range(2, 12))
             + "|Corn Equivalent Default Value|Soybean Meal Equivalent Default Value|"
               "Liability Price|Sales Effective Date|Live Cattle Equivalent Default Value|"
               "Feeder Cattle Equivalent Default Value")

DRAW_HEADER = ("Record Type Code|Record Category Code|Reinsurance Year|Commodity Year|"
               "Commodity Code|Insurance Plan Code|State Code|County Code|Type Code|"
               "Practice Code|Margin Draw Number|Interval Code|"
               + "|".join(f"Month{m} Margin Draw Amount" for m in range(2, 12)) + "|"
               + "|".join(f"Corn Month{m} Margin Draw Amount" for m in range(2, 12)) + "|"
               + "|".join(f"Live Cattle Month{m} Margin Draw Amount" for m in range(2, 12))
               + "|"
               + "|".join(f"Feeder Cattle Month{m} Margin Draw Amount"
                          for m in range(2, 12))
               + "|Sales Effective Date")


def _swine_fixture():
    """Swine: composite margin published whole, five months (2..6)."""
    months = [f"{80.0 + m:.2f}" for m in range(2, 7)] + [""] * 5
    gm = [GM_HEADER,
          "A00600|01|2027|2027|0815|82|19|998|805|809||809|" + "|".join(months)
          + "|||81.73|20260806||"]
    draws = [DRAW_HEADER]
    for i, bump in enumerate((-5.0, 0.0, 5.0), start=1):
        vals = [f"{80.0 + m + bump:.2f}" for m in range(2, 7)] + [""] * 5
        draws.append(f"A00610|01|2027|2027|0815|82|19|998|805|809|{i}|809|"
                     + "|".join(vals) + "|" + "|".join([""] * 30) + "|20260806")
    return "\n".join(gm), "\n".join(draws)


def _cattle_fixture():
    """Cattle: three Market Symbol rows to be assembled with the ration."""
    live = [f"{220.0:.2f}"] * 10
    feeder = [f"{360.0:.2f}"] * 10
    corn = [f"{4.50:.2f}"] * 10
    gm = [GM_HEADER,
          "A00600|02|2027|2027|0803|82|19|998|808|909|LE|909|" + "|".join(live)
          + "|||224.93|20260806|12.5|",
          "A00600|02|2027|2027|0803|82|19|998|808|909|GF|909|" + "|".join(feeder)
          + "||||20260806||7.5",
          "A00600|02|2027|2027|0803|82|19|998|808|909|C|909|" + "|".join(corn)
          + "|50.0|||20260806||"]
    draws = [DRAW_HEADER]
    for i, bump in enumerate((-10.0, 0.0, 10.0), start=1):
        blank = [""] * 10
        cornv = [f"{4.50:.2f}"] * 10
        livev = [f"{220.0 + bump:.2f}"] * 10
        feedv = [f"{360.0:.2f}"] * 10
        draws.append(f"A00610|02|2027|2027|0803|82|19|998|808|909|{i}|909|"
                     + "|".join(blank) + "|" + "|".join(cornv) + "|" + "|".join(livev)
                     + "|" + "|".join(feedv) + "|20260806")
    return "\n".join(gm), "\n".join(draws)


def test_build_panels_reads_the_composite_swine_shape():
    gm, dr = _swine_fixture()
    panels = lgm.build_panels(gm, dr)
    assert len(panels) == 1
    p = panels[0]
    assert (p.commodity_code, p.type_code, p.state_code) == ("0815", "805", "19")
    assert p.months == (2, 3, 4, 5, 6)          # month 7..11 blank and dropped
    assert p.n_draws == 3
    assert p.expected.tolist() == [82.0, 83.0, 84.0, 85.0, 86.0]
    assert p.draws.shape == (3, 5)
    assert p.liability_price == 81.73


def test_build_panels_assembles_the_cattle_composite_from_three_rows():
    gm, dr = _cattle_fixture()
    panels = lgm.build_panels(gm, dr)
    assert len(panels) == 1
    p = panels[0]
    assert p.commodity_code == "0803"
    # Ration comes off the ADM row itself and matches the handbook constants.
    assert (p.ration.output_cwt, p.ration.feeder_cwt, p.ration.corn_bu) == (12.5, 7.5, 50.0)
    want = 220.0 * 12.5 - 360.0 * 7.5 - 4.50 * 50.0
    assert p.expected.tolist() == pytest.approx([want] * 10)
    # The three draws bracket the expected margin symmetrically, so their mean returns it.
    assert p.draws.mean(axis=0).tolist() == pytest.approx([want] * 10)


def test_composite_cattle_margin_is_the_ration_dot_product():
    r = lgm.ration_for("0803", "807")
    got = lgm.composite_cattle_margin([200.0, None], [350.0, 350.0], [4.0, 4.0], r)
    assert got[0] == pytest.approx(200.0 * 11.5 - 350.0 * 5.5 - 4.0 * 52.0)
    assert got[1] is None


def test_build_panels_filters():
    gm, dr = _swine_fixture()
    assert lgm.build_panels(gm, dr, commodity_code="0803") == []
    assert lgm.build_panels(gm, dr, state_code="99") == []
    assert len(lgm.build_panels(gm, dr, type_code="805")) == 1


def test_build_panels_skips_a_commodity_with_no_populated_month():
    """RMA publishes placeholder rows before a sales period opens; skip, do not raise."""
    gm = GM_HEADER + "\nA00600|01|2027|2027|0815|82|19|998|805|809||809|" \
         + "|".join([""] * 10) + "|||81.73|20260806||"
    dr = DRAW_HEADER + "\nA00610|01|2027|2027|0815|82|19|998|805|809|1|809|" \
         + "|".join([""] * 40) + "|20260806"
    assert lgm.build_panels(gm, dr) == []


def test_parse_listing_orders_oldest_first():
    html = ('<a href="2027_ADMLivestockLgm_Daily_20260806.zip">x</a>'
            '<a href="2027_ADMLivestockLgm_Daily_20260702.zip">y</a>'
            '<a href="2027_ADMLivestockLrp_Daily_20260806.zip">z</a>')
    assert lgm.parse_listing(html, 2027) == [
        "2027_ADMLivestockLgm_Daily_20260702.zip",
        "2027_ADMLivestockLgm_Daily_20260806.zip"]
    assert lgm.parse_listing(html, 2026) == []


def test_parse_subsidy_rows_keeps_plan_82_and_reads_by_column_name():
    header = ("Record Type Code|Record Category Code|Reinsurance Year|Commodity Code|"
              "Unit Structure Code|Insurance Plan Code|Coverage Level Percent|"
              "Coverage Type Code|Deductible Amount|Endorsement Length Code|"
              "Endorsement Length Count|Insurance Option Code|Range Type Code|"
              "Range Low Value|Range High Value|Subsidy Percent")
    lines = [header,
             "A00070|05|2027|0803||82|||0.00|||||||0.180",
             "A00070|05|2027|0803||82|||70.00|||||||0.500",
             "A00070|04|2027|||83|0.90|A||||||||0.440",
             "A00070|08|2027|||81||||W|||02|0.750000|0.750000|0.550"]
    got = lgm.parse_subsidy_rows(lines)
    assert got == [(2027, "0803", 0.0, 0.18), (2027, "0803", 70.0, 0.50)]


def test_commodity_from_sob_recovers_the_9999_rollup():
    assert lgm.commodity_from_sob("807", "Head") == "0803"
    assert lgm.commodity_from_sob("808", "Head") == "0803"
    assert lgm.commodity_from_sob("804", "Head") == "0815"
    assert lgm.commodity_from_sob("997", "Hundred Weight of Milk") == "0847"
    assert lgm.commodity_from_sob("997", "Head") is None


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    yield c
    c.close()


def test_schema_creates_the_three_lgm_tables(conn):
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lgm_subsidy", "lgm_margin", "lgm_deductible_curve"} <= have


def test_subsidy_round_trip_and_table_shape(conn):
    rows = [(2027, cc, d, s)
            for cc, tbl in lgm.SUBSIDY_BY_DEDUCTIBLE.items()
            for d, s in tbl.items()]
    assert lgm.upsert_subsidy(conn, rows) == len(rows)
    tbl = lgm.subsidy_table(conn, 2027)
    assert tbl == lgm.SUBSIDY_BY_DEDUCTIBLE
    # A year with no rows falls back to the verified constant rather than returning {}.
    assert lgm.subsidy_table(conn, 1999) is lgm.SUBSIDY_BY_DEDUCTIBLE
    # Upsert is idempotent.
    assert lgm.upsert_subsidy(conn, rows) == len(rows)
    n = conn.execute("SELECT COUNT(*) FROM lgm_subsidy").fetchone()[0]
    assert n == len(rows)
    assert conn.execute(
        "SELECT commodity_name FROM lgm_subsidy WHERE commodity_code='0847' LIMIT 1"
    ).fetchone()[0] == "Dairy Cattle"


def test_panel_and_curve_round_trip(conn):
    gm, dr = _cattle_fixture()
    panels = lgm.build_panels(gm, dr)
    assert lgm.upsert_panels(conn, 2027, panels) == 1
    row = conn.execute("SELECT * FROM lgm_margin").fetchone()
    assert row["type_name"] == "Yearling Finishing"
    assert row["n_draws"] == 3
    assert row["ration_corn_bu"] == 50.0
    assert row["months"] == "2,3,4,5,6,7,8,9,10,11"

    p = panels[0]
    curve = lgm.deductible_curve(p.commodity_code, p.type_code, p.state_code,
                                 p.expected, p.draws,
                                 lgm.uniform_marketings(len(p.months), 100))
    assert lgm.upsert_curve(conn, 2027, curve) == len(curve)
    got = conn.execute(
        "SELECT deductible, subsidy_pct, pooled FROM lgm_deductible_curve "
        "ORDER BY deductible").fetchall()
    assert [r["deductible"] for r in got] == lgm.deductible_grid("0803")
    assert got[0]["subsidy_pct"] == 0.18
    assert all(r["pooled"] == 1 for r in got)


def test_curve_uses_the_db_table_when_present(conn):
    """A future ladder change must flow through the DB, not a code edit."""
    lgm.upsert_subsidy(conn, [(2030, "0803", d, 0.99)
                              for d in lgm.deductible_grid("0803")])
    tbl = lgm.subsidy_table(conn, 2030)
    assert lgm.subsidy_rate("0803", 0.0, table=tbl) == 0.99


def test_sob_gate_note_names_the_function_and_the_codes():
    """The change rma_sob.py needs is documented in code, since we cannot make it."""
    assert "sob_crop()" in lgm.SOB_GATE_NOTE
    assert "ADM_ROW_CROP_CODES" in lgm.SOB_GATE_NOTE
    for cc in ("0803", "0815", "0847"):
        assert cc in lgm.SOB_GATE_NOTE
    assert lgm.LIVESTOCK_PLAN_CODES == {"81", "82", "83"}
