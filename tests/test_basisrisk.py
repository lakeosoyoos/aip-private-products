"""Pin the basis-risk estimator.

The two tests that matter most are `test_perfect_correlation_has_no_basis_risk` and
`test_independence_is_maximal_basis_risk`. They are the limits the whole construction has to
respect: an index that IS the farm can never miss it, and an index independent of the farm
misses it exactly as often as the index happens not to pay. Everything else in this module is
an interpolation between those two, so if either breaks, no number the module produces means
anything.

The second theme is that DETRENDING is not cosmetic. `test_trend_is_not_risk` is the guard: a
county yield series with a strong technology trend and almost no year-to-year risk must come
out of `detrend` as almost no risk. Skip the detrend and the same series looks like a
catastrophe.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from src import basisrisk as B

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "catalog.db"


# ── Detrending ───────────────────────────────────────────────────────────────

def test_ols_removes_an_exact_linear_trend():
    years = list(range(1980, 2025))
    values = [100.0 + 2.0 * (y - 1980) for y in years]
    fit = B.detrend(years, values, "ols")
    assert fit.slope == pytest.approx(2.0)
    assert fit.ratio == pytest.approx(np.ones(len(years)))
    assert fit.cv == pytest.approx(0.0, abs=1e-9)


def test_trend_is_not_risk():
    """A strong trend with small noise must detrend to small risk — the whole point of step 1.

    Raw CV here is ~0.30 because yields nearly tripled over the period. The actual year-to-year
    risk is 5%. Treating the first number as risk would inflate every downstream probability.
    """
    rng = np.random.default_rng(0)
    years = list(range(1980, 2025))
    trend = np.array([60.0 + 2.5 * (y - 1980) for y in years])
    values = trend * (1 + rng.normal(0, 0.05, len(years)))
    raw_cv = float(np.std(values, ddof=1) / np.mean(values))
    fit = B.detrend(years, values, "ols")
    assert raw_cv > 0.25
    assert fit.cv < 0.08
    assert fit.cv < raw_cv / 3


def test_pct_per_year_is_a_share_not_a_bushel():
    years = list(range(1980, 2025))
    values = [100.0 + 2.0 * (y - 1980) for y in years]
    fit = B.detrend(years, values, "ols")
    assert fit.slope == pytest.approx(2.0)
    assert 0.01 < fit.pct_per_year < 0.02      # 2 bu on a ~144 bu mean fitted yield


def test_theilsen_is_less_moved_by_a_disaster_year_than_ols():
    years = list(range(1980, 2025))
    values = [100.0 + 2.0 * (y - 1980) for y in years]
    values[2] = 5.0                                   # a total crop failure early in the series
    ols = B.detrend(years, values, "ols")
    ts = B.detrend(years, values, "theilsen")
    assert abs(ts.slope - 2.0) < abs(ols.slope - 2.0)


def test_mean_method_leaves_the_trend_in():
    years = list(range(1980, 2025))
    values = [100.0 + 2.0 * (y - 1980) for y in years]
    assert B.detrend(years, values, "mean").cv > 0.15
    assert B.detrend(years, values, "ols").cv == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("years,values,method", [
    ([1, 2], [10, 11], "ols"),                       # too short
    ([1, 2, 3], [10, 0, 11], "ols"),                 # non-positive yield
    ([1, 2, 3], [10, 11, 12], "sorcery"),            # unknown method
])
def test_detrend_refuses_bad_input(years, values, method):
    with pytest.raises(ValueError):
        B.detrend(years, values, method)


def test_detrend_sorts_by_year():
    a = B.detrend([1990, 1980, 1985], [30.0, 10.0, 20.0], "ols")
    b = B.detrend([1980, 1985, 1990], [10.0, 20.0, 30.0], "ols")
    assert a.ratio == pytest.approx(b.ratio)


# ── Bands ────────────────────────────────────────────────────────────────────

def test_eco_band_is_fixed_regardless_of_coverage_level():
    assert B.band_bounds("ECO95", 0.85) == (0.86, 0.95)
    assert B.band_bounds("ECO95", 0.70) == (0.86, 0.95)
    assert B.band_bounds("ECO90", 0.85) == (0.86, 0.90)


def test_sco_band_width_depends_on_the_producer():
    """SCO exits at the underlying level, so at 85% RP it is one coverage point wide."""
    assert B.band_bounds("SCO86", 0.85) == (0.85, 0.86)
    assert B.band_bounds("SCO86", 0.70) == (0.70, 0.86)


def test_sco_is_refused_when_it_has_no_width():
    with pytest.raises(ValueError, match="nothing to buy"):
        B.band_bounds("SCO86", 0.86)


def test_unknown_band_is_refused():
    with pytest.raises(ValueError):
        B.band_bounds("ECO99", 0.85)


# ── Coverage levels: the producer's deductible, not the band's trigger ───────
#
# The whole point of this block is that TWO different percentages are called "coverage level"
# and they enter the joint distribution on opposite sides (src/basisrisk.py, Step 5b). The
# band's TRIGGER is compared against the county; the producer's ELECTION is compared against
# the farm. Getting them the wrong way round inverts every conclusion, so the direction is
# pinned here rather than described.

def test_published_levels_are_real_rma_elections():
    assert set(B.PUBLISHED_COVERAGE_LEVELS) <= set(B.COVERAGE_LEVELS)
    assert B.MODAL_COVERAGE_LEVEL in B.PUBLISHED_COVERAGE_LEVELS
    assert list(B.PUBLISHED_COVERAGE_LEVELS) == sorted(B.PUBLISHED_COVERAGE_LEVELS)
    # RMA sells buy-up in 5-point steps from 0.50 to 0.85. Anything else is not a policy.
    assert B.COVERAGE_LEVELS == (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)


def test_cl_key_makes_arithmetic_and_literals_the_same_row():
    assert B.cl_key(0.7000000001) == B.cl_key(0.70) == 0.70
    assert B.cl_key(0.65 + 1e-12) == 0.65


def test_nearest_published_level_snaps_up_not_to_nearest():
    """Snapping UP over-states basis risk, which is the safe direction.

    0.71 is nearer 0.70 than 0.75, and we still go up: the rule is never to quote a producer a
    LOWER miss rate than the grid can support for them.
    """
    assert B.nearest_published_level(0.50) == 0.65
    assert B.nearest_published_level(0.60) == 0.65
    assert B.nearest_published_level(0.71) == 0.75      # nearest would be 0.70 — we go up
    assert B.nearest_published_level(0.75) == 0.75      # already on the grid: unchanged
    assert B.nearest_published_level(0.90) == 0.85      # clamps to the worst case


@pytest.mark.parametrize("mix", [B.ELECTION_MIX, B.SCO_ELECTION_MIX])
def test_election_mixes_are_distributions_over_real_elections(mix):
    for crop, m in mix.items():
        assert set(m) <= set(B.COVERAGE_LEVELS), crop
        assert sum(m.values()) == pytest.approx(1.0, abs=0.005), crop
        assert all(v >= 0 for v in m.values()), crop


def test_the_top_election_is_a_small_minority_of_the_book():
    """The measured claim the whole coverage-level change rests on, kept beside the constants."""
    assert B.ELECTION_MIX["ALL"][0.85] < 0.20
    assert B.SCO_ELECTION_MIX["ALL"][0.85] < 0.05
    assert max(B.SCO_ELECTION_MIX["ALL"], key=B.SCO_ELECTION_MIX["ALL"].get) == 0.75
    assert B.SHARE_AT_MAX_LEVEL == B.ELECTION_MIX["ALL"][0.85]
    assert B.SHARE_AT_MAX_LEVEL_SCO == B.SCO_ELECTION_MIX["ALL"][0.85]


def test_election_weights_lose_no_acres_off_the_grid():
    w = B.election_weights("Corn", book="all")
    assert set(w) == set(B.PUBLISHED_COVERAGE_LEVELS)
    assert sum(w.values()) == pytest.approx(1.0)
    # The sub-0.65 tail is folded UP into 0.65, not dropped.
    raw = B.ELECTION_MIX["Corn"]
    assert w[0.65] == pytest.approx(raw[0.50] + raw[0.55] + raw[0.60] + raw[0.65], abs=1e-9)


def test_election_weights_fall_back_to_the_all_crop_mix():
    assert B.election_weights("Sunflowers") == B.election_weights("ALL")


def test_blend_sits_between_the_extremes_and_near_the_mode():
    by_cl = {0.65: 0.02, 0.70: 0.03, 0.75: 0.05, 0.80: 0.09, 0.85: 0.13}
    blend = B.blend_over_coverage_levels(by_cl, "Corn", book="sco")
    assert min(by_cl.values()) < blend < max(by_cl.values())
    # Half of SCO buyers sit at 0.75, so the blend must land much nearer 0.75 than 0.85.
    assert abs(blend - by_cl[0.75]) < abs(blend - by_cl[0.85])


def test_blend_ignores_missing_levels_rather_than_returning_nan():
    assert B.blend_over_coverage_levels({0.75: 0.05, 0.85: None}) == pytest.approx(0.05)
    assert math.isnan(B.blend_over_coverage_levels({}))


def test_unknown_election_book_is_refused():
    with pytest.raises(ValueError):
        B.election_weights("Corn", book="everyone")


# ── The two limits that define the metric ────────────────────────────────────

def _county_sample(n=200_000, cv=0.18, seed=3):
    """A left-skewed county yield ratio sample with a realistic CV."""
    rng = np.random.default_rng(seed)
    x = rng.gamma(shape=4.0, scale=1.0, size=n)
    x = 1.0 - (x - 4.0) / 4.0 * (cv / 0.5)             # reflect: left tail, mean 1
    return np.clip(x, 0.0, None)


def test_perfect_correlation_has_no_basis_risk():
    """The index IS the farm. It cannot fail to pay a farm that lost. This must be exactly 0."""
    c = _county_sample()
    for band in ("ECO95", "ECO90", "SCO86"):
        m = B.metrics_from_draws(c, c, band=band, coverage_level=0.80)
        assert m.miss_rate == 0.0, band
        assert m.p_hard_miss == 0.0, band
        assert m.uncovered_share == pytest.approx(0.0, abs=1e-12), band


def test_independence_is_maximal_basis_risk():
    """Independent farm and county: knowing the farm lost says nothing about the county.

    So P(no pay | farm loss) collapses to the unconditional P(no pay). That identity is the
    upper limit of basis risk and it is what "high" means here — for ECO at a 95% trigger it
    lands near two thirds of loss years going unpaid.
    """
    c = _county_sample(seed=3)
    f = _county_sample(seed=99)                         # same law, independent draw
    m = B.metrics_from_draws(f, c, band="ECO95", coverage_level=0.85)
    assert m.miss_rate == pytest.approx(1.0 - m.p_band_pays, abs=0.01)
    assert m.miss_rate > 0.4
    assert m.uncovered_share > 0.4


def test_basis_risk_is_monotone_in_rho():
    c = _county_sample(n=20_000)
    rates = [B.basis_risk(c, rho=r, n_draws=60_000, seed=5, plan_type="YP").miss_rate
             for r in (0.98, 0.90, 0.80, 0.70, 0.60, 0.50)]
    assert rates == sorted(rates), rates
    assert rates[0] < 0.10                              # near-perfect tracking: almost no miss
    assert rates[-1] > rates[0] + 0.15                  # and it grows materially as rho falls


def test_rho_one_through_the_full_simulation_is_zero_basis_risk():
    c = _county_sample(n=20_000)
    for plan in ("YP", "RP"):
        m = B.basis_risk(c, rho=1.0, plan_type=plan, n_draws=60_000, seed=5)
        assert m.miss_rate == pytest.approx(0.0, abs=1e-12), plan
        assert m.farm_cv == pytest.approx(m.county_cv)


def test_revenue_trigger_carries_less_basis_risk_than_yield_trigger():
    """Price is national, so the price leg of an RP band cannot miss anybody.

    A producer buying the YIELD-triggered variant (ECO-YP / SCO-YP) is buying almost pure
    basis risk — the cheap part of the product is exactly the part that can fail them.
    """
    c = _county_sample(n=20_000)
    rp = B.basis_risk(c, rho=0.70, plan_type="RP", n_draws=120_000, seed=5)
    yp = B.basis_risk(c, rho=0.70, plan_type="YP", n_draws=120_000, seed=5)
    assert rp.miss_rate < yp.miss_rate


def test_sco_misses_more_often_than_eco():
    """SCO's trigger sits 9 points lower, so it fires far less often and misses far more."""
    c = _county_sample(n=20_000)
    eco = B.basis_risk(c, rho=0.70, coverage_level=0.75, band="ECO95", n_draws=80_000, seed=5)
    sco = B.basis_risk(c, rho=0.70, coverage_level=0.75, band="SCO86", n_draws=80_000, seed=5)
    assert sco.miss_rate > eco.miss_rate
    assert sco.p_band_pays < eco.p_band_pays


def test_a_lower_producer_coverage_level_misses_less():
    """THE direction test for the coverage-level dimension. Monotone, on every band.

    A LOWER election is a BIGGER deductible, so the losses that qualify as "a farm loss" are
    fewer and DEEPER — and a deep farm loss is far more likely to have come from weather the
    whole county shared, which is exactly when the county index fires. So miss_rate FALLS as
    the election falls.

    This is the sign that decides whether the shipped 0.85-only table was over- or
    under-discounting the opportunity map. It over-discounts: 0.85 is the top of the grid and
    therefore the worst case, while the book's mode is 0.75.
    """
    c = _county_sample(n=20_000)
    for band in ("ECO95", "ECO90", "SCO86"):
        rates = [B.basis_risk(c, band=band, coverage_level=cl, rho=0.70,
                              n_draws=80_000, seed=5).miss_rate
                 for cl in B.PUBLISHED_COVERAGE_LEVELS]
        assert rates == sorted(rates), (band, rates)
        assert rates[-1] > rates[0] + 0.05, (band, rates)   # and it is a material spread


def test_the_joint_annual_frequency_of_a_hard_miss_falls_too():
    """miss_rate is a conditional; p_hard_miss is the unconditional. Both must move together."""
    c = _county_sample(n=20_000)
    ms = [B.basis_risk(c, coverage_level=cl, rho=0.70, n_draws=80_000, seed=5)
          for cl in B.PUBLISHED_COVERAGE_LEVELS]
    assert [m.p_hard_miss for m in ms] == sorted(m.p_hard_miss for m in ms)
    assert [m.p_farm_loss for m in ms] == sorted(m.p_farm_loss for m in ms)


def test_the_producer_level_never_touches_the_county_side_of_an_eco_band():
    """ECO's exit is fixed at 0.86, so its purely county-side outputs cannot move with CL.

    This is the mechanical proof of Step 5b's claim about which side each percentage lives on.
    SCO is the exception — its exit IS the producer's level — so the same quantities must move
    there, and the second half asserts that too. If a future change makes the ECO numbers move,
    something has leaked from the farm side into the county side.
    """
    d = B.draw_joint(_county_sample(n=20_000), rho=0.70, n_draws=60_000, seed=5)
    county_side = ("p_band_pays", "uncovered_share", "payout_corr",
                   "expected_payment_per_dollar")

    ref = None
    for cl in B.PUBLISHED_COVERAGE_LEVELS:
        m = B.metrics_from_draws(d.farm_ratio, d.county_ratio, band="ECO95", coverage_level=cl)
        got = tuple(getattr(m, k) for k in county_side)
        if ref is None:
            ref = got
        assert got == pytest.approx(ref), cl
        assert m.trigger == 0.95 and m.exit == 0.86

    sco = [B.metrics_from_draws(d.farm_ratio, d.county_ratio, band="SCO86", coverage_level=cl)
           for cl in (0.65, 0.85)]
    assert sco[0].exit == 0.65 and sco[1].exit == 0.85          # the exit IS the election
    assert sco[0].expected_payment_per_dollar != sco[1].expected_payment_per_dollar


def test_skewed_idiosyncratic_raises_basis_risk_above_normal():
    """A symmetric farm shock understates basis risk; the docstring promises this direction."""
    c = _county_sample(n=20_000)
    normal = B.basis_risk(c, rho=0.70, idio="normal", plan_type="YP", n_draws=120_000, seed=5)
    skewed = B.basis_risk(c, rho=0.70, idio="skewed", plan_type="YP", n_draws=120_000, seed=5)
    assert skewed.miss_rate > normal.miss_rate


def test_windfall_is_reported_not_hidden():
    c = _county_sample(n=20_000)
    m = B.basis_risk(c, rho=0.70, plan_type="YP", n_draws=80_000, seed=5)
    assert 0.0 < m.windfall_rate < 1.0
    assert 0.0 < m.windfall_share < 1.0


def test_seed_makes_it_reproducible():
    c = _county_sample(n=5_000)
    a = B.basis_risk(c, rho=0.7, n_draws=40_000, seed=42)
    b = B.basis_risk(c, rho=0.7, n_draws=40_000, seed=42)
    assert a.miss_rate == b.miss_rate


@pytest.mark.parametrize("rho", [0.0, -0.2, 1.5])
def test_bad_rho_is_refused(rho):
    with pytest.raises(ValueError):
        B.basis_risk(_county_sample(n=1_000), rho=rho, n_draws=1_000)


def test_bad_plan_type_is_refused():
    with pytest.raises(ValueError):
        B.basis_risk(_county_sample(n=1_000), plan_type="XX", n_draws=1_000)


def test_metrics_refuse_mismatched_samples():
    with pytest.raises(ValueError):
        B.metrics_from_draws(np.ones(10), np.ones(11))


# ── Smoothed bootstrap ───────────────────────────────────────────────────────

def test_smoothed_bootstrap_preserves_mean_and_variance():
    """Variance correction is the reason this is not a plain kernel smooth."""
    rng = np.random.default_rng(1)
    sample = rng.normal(1.0, 0.15, 40)
    drawn = B.smoothed_bootstrap(rng, sample, 400_000)
    assert drawn.mean() == pytest.approx(sample.mean(), abs=0.005)
    assert drawn.std(ddof=1) == pytest.approx(sample.std(ddof=1), rel=0.05)


def test_smoothed_bootstrap_is_not_just_the_sample_values():
    rng = np.random.default_rng(1)
    sample = rng.normal(1.0, 0.15, 30)
    drawn = B.smoothed_bootstrap(rng, sample, 5_000)
    assert len(np.unique(drawn)) > 4_000


def test_smoothed_bootstrap_of_a_constant_series_is_constant():
    rng = np.random.default_rng(1)
    drawn = B.smoothed_bootstrap(rng, np.ones(20), 1_000)
    assert drawn == pytest.approx(np.ones(1_000))


# ── Uncertainty carries the length of the series ─────────────────────────────

def test_a_short_county_series_gets_a_wider_interval_than_a_long_one():
    """12 usable years and 45 usable years do not support the same claim, and the output says so."""
    rng = np.random.default_rng(7)
    def series(n):
        yrs = list(range(2025 - n + 1, 2026))
        trend = np.array([100.0 + 1.5 * (y - 1980) for y in yrs])
        return yrs, list(trend * (1 + rng.normal(0, 0.18, n)))

    short_y, short_v = series(12)
    long_y, long_v = series(45)
    _, slo, shi = B.bootstrap_miss_rate(short_y, short_v, n_boot=120, n_draws=6_000,
                                        rho=0.7, plan_type="YP")
    _, llo, lhi = B.bootstrap_miss_rate(long_y, long_v, n_boot=120, n_draws=6_000,
                                        rho=0.7, plan_type="YP")
    assert (shi - slo) > (lhi - llo)


def test_grade_reflects_series_length():
    assert B.grade_for(45) == "A"
    assert B.grade_for(30) == "A"
    assert B.grade_for(25) == "B"
    assert B.grade_for(15) == "C"
    assert B.grade_for(11) is None


# ── Aggregation scaling (the independent check on rho) ───────────────────────

def test_scaling_recovers_a_known_exponent():
    areas = {"COUNTY": 1e5, "DISTRICT": 1e6, "STATE": 1e7, "NATIONAL": 1e9}
    variances = {k: [0.04 * (a / 1e5) ** -0.5] for k, a in areas.items()}
    fit = B.aggregation_scaling(variances, areas)
    assert fit.exponent == pytest.approx(-0.5, abs=1e-6)
    assert fit.r2 == pytest.approx(1.0, abs=1e-9)


def test_scaling_implies_a_correlation_below_one():
    areas = {"COUNTY": 1e5, "DISTRICT": 1e6, "STATE": 1e7}
    variances = {k: [0.04 * (a / 1e5) ** -0.4] for k, a in areas.items()}
    fit = B.aggregation_scaling(variances, areas, farm_acres=500, county_acres=100_000)
    assert 0.0 < fit.implied_rho < 1.0
    # A smaller farm is a worse match for its county.
    assert fit.rho_for(200, 100_000) < fit.rho_for(5_000, 100_000)


def test_scaling_needs_two_levels():
    with pytest.raises(ValueError):
        B.aggregation_scaling({"COUNTY": [0.04]}, {"COUNTY": 1e5})


# ── The farm calculator ──────────────────────────────────────────────────────

def _county_history(n=45, cv=0.18, seed=11, start=1981):
    rng = np.random.default_rng(seed)
    years = list(range(start, start + n))
    trend = np.array([100.0 + 1.5 * (y - start) for y in years])
    return years, list(trend * (1 + rng.normal(0, cv, n))), trend


def test_a_farm_that_tracks_its_county_exactly_has_no_basis_risk():
    """A farm whose yields are a fixed multiple of the county's is the county, scaled.

    rho comes out at 0.999 rather than exactly 1 because the farm's 12-year series is
    detrended at the county's %/year rate anchored on its OWN mean, while the county is
    detrended by OLS over all 45 years — the two fitted lines are not identical over the
    12-year window. That residue is real and is the right behaviour: it is what a producer
    with a short series actually faces.
    """
    cy, cvals, _ = _county_history()
    farm_years = cy[-12:]
    farm_vals = [v * 0.9 for v in cvals[-12:]]         # same shape, lower absolute yield
    r = B.farm_basis_risk(farm_years, farm_vals, cy, cvals, band="ECO95", coverage_level=0.85,
                          plan_type="YP", n_draws=40_000)
    assert r.rho_measured > 0.99
    assert r.modelled.miss_rate < 0.02
    assert r.historical_miss_years == []


def test_a_farm_only_loosely_tied_to_its_county_shows_far_more_basis_risk():
    """Same county, two farms. The one that tracks it is served; the one that does not is not.

    This is the whole point of the farm calculator: the county is identical, the subsidy is
    identical, the 5x headline return is identical — and the honest recommendation differs.
    """
    cy, cvals, _ = _county_history(seed=11)
    fit = B.detrend(cy, cvals, "ols")
    ratio = dict(zip([int(y) for y in fit.years], fit.ratio))
    farm_years = cy[-25:]
    rng = np.random.default_rng(404)

    def farm_for(weight, noise):
        base = np.array([100.0 + 1.5 * (y - cy[0]) for y in farm_years])
        r = 1.0 + weight * (np.array([ratio[y] for y in farm_years]) - 1.0)
        return list(base * r * (1 + rng.normal(0, noise, len(farm_years))))

    tracker = B.farm_basis_risk(farm_years, farm_for(1.0, 0.02), cy, cvals, band="ECO95",
                                coverage_level=0.85, plan_type="YP", n_draws=60_000)
    loner = B.farm_basis_risk(farm_years, farm_for(0.3, 0.22), cy, cvals, band="ECO95",
                              coverage_level=0.85, plan_type="YP", n_draws=60_000)

    assert tracker.rho_measured > 0.9
    assert 0.0 < loner.rho_measured < 0.7
    assert loner.modelled.miss_rate > tracker.modelled.miss_rate + 0.15
    assert loner.farm_cv > tracker.farm_cv


def test_historical_misses_name_the_actual_years():
    """The producer's own record: which years did they lose and get nothing?"""
    years = list(range(2006, 2026))
    county = [100.0] * 20                              # a county that never has a bad year
    farm = [100.0] * 20
    farm[5] = 50.0                                     # one farm-specific disaster
    r = B.farm_basis_risk(years, farm, years, county, band="ECO95", coverage_level=0.85,
                          detrend_method="mean", farm_detrend="none",
                          plan_type="YP", n_draws=20_000)
    assert 2011 in r.farm_shortfall_years
    assert r.historical_miss_years == [2011]
    assert r.historical_pay_years == []


def test_county_windfall_years_are_named_too():
    years = list(range(2006, 2026))
    county = [100.0] * 20
    county[3] = 70.0                                   # county-wide bad year
    farm = [100.0] * 20                                # farm was fine
    r = B.farm_basis_risk(years, farm, years, county, band="ECO95", coverage_level=0.85,
                          detrend_method="mean", farm_detrend="none",
                          plan_type="YP", n_draws=20_000)
    assert r.historical_windfall_years == [2009]
    assert r.farm_shortfall_years == []


def test_farm_detrend_county_uses_the_county_trend_rate():
    cy, cvals, _ = _county_history()
    farm_years = cy[-10:]
    farm_vals = [90.0 + 1.35 * i for i in range(10)]
    r = B.farm_basis_risk(farm_years, farm_vals, cy, cvals, farm_detrend="county",
                          n_draws=10_000)
    county_fit = B.detrend(cy, cvals, "ols")
    assert r.farm_trend_pct_per_year == pytest.approx(county_fit.pct_per_year)


def test_short_farm_series_is_flagged_as_anecdote():
    cy, cvals, _ = _county_history()
    r = B.farm_basis_risk(cy[-5:], [100, 110, 95, 120, 105], cy, cvals, n_draws=10_000)
    assert any("overlapping years" in w for w in r.warnings)


def test_negative_correlation_is_flagged_as_a_data_problem():
    years = list(range(2006, 2026))
    county = [100 + 10 * (i % 2) for i in range(20)]
    farm = [100 - 10 * (i % 2) for i in range(20)]     # perfectly anti-correlated
    r = B.farm_basis_risk(years, farm, years, county, detrend_method="mean",
                          farm_detrend="none", n_draws=10_000)
    assert r.rho_measured < 0
    assert any("NEGATIVE" in w for w in r.warnings)
    assert r.rho_used == B.RHO_REF                     # falls back, and says it is not farm-specific
    assert any("NOT farm-specific" in w for w in r.warnings)


def test_farm_calculator_reports_a_confidence_interval_on_rho():
    cy, cvals, _ = _county_history()
    rng = np.random.default_rng(5)
    farm_years = cy[-10:]
    base = np.array([cvals[cy.index(y)] for y in farm_years])
    farm_vals = list(base * (1 + rng.normal(0, 0.12, 10)))
    r = B.farm_basis_risk(farm_years, farm_vals, cy, cvals, n_draws=20_000)
    assert r.rho_ci_lo < r.rho_measured < r.rho_ci_hi
    assert r.rho_ci_hi - r.rho_ci_lo > 0.10            # 10 APH years buys a wide interval
    assert r.modelled_rho_hi.miss_rate <= r.modelled_rho_lo.miss_rate


def test_farm_calculator_needs_overlapping_years():
    cy, cvals, _ = _county_history(start=1981, n=30)
    with pytest.raises(ValueError, match="overlap"):
        B.farm_basis_risk([2050, 2051, 2052], [100, 110, 120], cy, cvals)


def test_unknown_farm_detrend_is_refused():
    cy, cvals, _ = _county_history()
    with pytest.raises(ValueError):
        B.farm_basis_risk(cy[-10:], cvals[-10:], cy, cvals, farm_detrend="vibes")


# ── Against the real loaded data ─────────────────────────────────────────────

pytestmark_db = pytest.mark.skipif(
    not DB.exists(), reason="data/catalog.db not present (local working DB)")


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.execute("PRAGMA busy_timeout = 30000")
    return c


def _has_table(conn, name) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


@pytestmark_db
def test_loaded_county_series_are_live_and_detrendable():
    conn = _conn()
    if not _has_table(conn, "nass_county_yield"):
        pytest.skip("nass_county_yield not loaded (run the nass_yield connector)")
    rows = conn.execute(
        "SELECT DISTINCT loc_key FROM nass_county_yield WHERE crop='Corn' AND stat='YIELD' "
        "AND agg_level='COUNTY' ORDER BY loc_key LIMIT 40").fetchall()
    if not rows:
        pytest.skip("no county corn yields loaded")
    checked = 0
    for (loc,) in rows:
        s = B.load_series(conn, "Corn", loc, min_year=1975, max_year=2025)
        if s is None:
            continue
        years, values, cls, prac = s
        assert max(years) >= B.DEFAULT_MIN_LAST_YEAR       # never score a dead series
        fit = B.detrend(years, values, "ols")
        assert 0.0 < fit.cv < 1.0
        assert fit.mean_yield > 0
        checked += 1
    assert checked > 0, "load_series returned nothing for any corn county"


@pytestmark_db
def test_wheat_falls_back_off_the_dead_all_classes_series():
    """NASS stopped publishing county wheat at ALL CLASSES after 2007; we must not pick it."""
    conn = _conn()
    if not _has_table(conn, "nass_county_yield"):
        pytest.skip("nass_county_yield not loaded")
    rows = conn.execute(
        "SELECT DISTINCT loc_key FROM nass_county_yield WHERE crop='Wheat' AND stat='YIELD' "
        "AND agg_level='COUNTY' AND year >= 2020 ORDER BY loc_key LIMIT 25").fetchall()
    if not rows:
        pytest.skip("no recent county wheat yields loaded")
    picked = []
    for (loc,) in rows:
        s = B.load_series(conn, "Wheat", loc, min_year=1975, max_year=2025)
        if s:
            picked.append(s[2])
            assert max(s[0]) >= B.DEFAULT_MIN_LAST_YEAR
    assert picked, "load_series returned nothing for any wheat county"
    assert "ALL CLASSES" not in picked


@pytestmark_db
def test_precomputed_table_is_internally_consistent():
    conn = _conn()
    if not _has_table(conn, "basis_risk_county"):
        pytest.skip("basis_risk_county not built (run scripts/analysis/build_basis_risk.py)")
    n = conn.execute("SELECT COUNT(*) FROM basis_risk_county").fetchone()[0]
    if n == 0:
        pytest.skip("basis_risk_county is empty")
    bad = conn.execute(
        "SELECT COUNT(*) FROM basis_risk_county WHERE miss_rate < 0 OR miss_rate > 1 "
        "OR county_cv <= 0 OR n_years < ?", (B.MIN_YEARS,)).fetchone()[0]
    assert bad == 0
    # Lower rho must never produce LESS basis risk than higher rho.
    inverted = conn.execute(
        "SELECT COUNT(*) FROM basis_risk_county "
        "WHERE miss_rate_rho_lo IS NOT NULL AND miss_rate_rho_hi IS NOT NULL "
        "AND miss_rate_rho_lo < miss_rate_rho_hi - 1e-9").fetchone()[0]
    assert inverted == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM basis_risk_county WHERE grade NOT IN ('A','B','C')"
    ).fetchone()[0] == 0
    # Every coverage level in the table must be a real RMA buy-up election, and if more than
    # one was built the direction must hold in the DATA, not only in the simulator: a lower
    # election is a bigger deductible, so it must not show MORE basis risk.
    levels = sorted(B.cl_key(r[0]) for r in conn.execute(
        "SELECT DISTINCT coverage_level FROM basis_risk_county") if r[0] is not None)
    assert levels and set(levels) <= set(B.COVERAGE_LEVELS), levels
    for lo, hi in zip(levels, levels[1:]):
        inverted = conn.execute(
            """SELECT COUNT(*) FROM basis_risk_county a JOIN basis_risk_county b
                 ON a.crop=b.crop AND a.county_fips=b.county_fips AND a.band=b.band
                AND a.plan_type=b.plan_type
               WHERE a.coverage_level=? AND b.coverage_level=?
                 AND a.miss_rate > b.miss_rate + 0.02""", (lo, hi)).fetchone()[0]
        assert inverted == 0, f"CL {lo} shows more basis risk than CL {hi} in {inverted} rows"


# ── The builder, end to end, on a synthetic county history ──────────────────

def _fixture_db(tmp_path, counties=3, seed=17):
    """A minimal working DB: nass_county_yield with a few trended, noisy corn counties.

    Small enough to run in a test and complete enough to exercise the real build path —
    series selection, detrending, the national correlation, the multi-level write and the
    primary key. The estimator's real input table is 2.5M rows; this is the same shape.
    """
    from src import db as dbmod

    path = tmp_path / "fixture.db"
    conn = dbmod.connect(path)
    dbmod.init_db(conn)
    rng = np.random.default_rng(seed)
    years = list(range(1975, 2026))
    rows = []
    nat = np.zeros(len(years))
    for i in range(counties):
        base, slope, cv = 90.0 + 10 * i, 1.6 + 0.1 * i, 0.10 + 0.03 * i
        shock = rng.standard_normal(len(years))
        nat += shock / counties
        for j, y in enumerate(years):
            v = (base + slope * (y - 1975)) * (1 + cv * shock[j])
            rows.append(("Corn", "YIELD", "ALL CLASSES", "ALL PRODUCTION PRACTICES", "BU / ACRE",
                         "COUNTY", f"1900{i}", "IA", f"1900{i}", "10", f"County {i}", y,
                         max(5.0, v), "fixture", "2026-01-01"))
    for j, y in enumerate(years):
        rows.append(("Corn", "YIELD", "ALL CLASSES", "ALL PRODUCTION PRACTICES", "BU / ACRE",
                     "NATIONAL", "US", None, None, None, None, y,
                     (100 + 1.7 * (y - 1975)) * (1 + 0.07 * nat[j]), "fixture", "2026-01-01"))
    conn.executemany(
        "INSERT OR REPLACE INTO nass_county_yield (crop, stat, class_desc, practice, unit, "
        "agg_level, loc_key, state, county_fips, asd_code, county_name, year, value, source, "
        "fetched_at) VALUES (" + ",".join("?" * 15) + ")", rows)
    conn.commit()
    return conn


class _Args:
    """Stand-in for the argparse namespace build() reads."""
    def __init__(self, **kw):
        self.crops = ["Corn"]
        self.bands = ["ECO95", "SCO86"]
        self.coverage_levels = [0.70, 0.80, 0.85]
        self.plan_type = "RP"
        self.detrend = "ols"
        self.rho, self.rho_lo, self.rho_hi = B.RHO_REF, B.RHO_LO, B.RHO_HI
        self.idio = "normal"
        self.draws = 20_000
        self.boot = 0
        self.boot_draws = 2_000
        self.min_year, self.max_year = 1975, 2025
        self.seed = 7
        self.limit = None
        self.progress = 0
        self.dry_run = False
        self.__dict__.update(kw)


def _builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_basis_risk", REPO / "scripts" / "analysis" / "build_basis_risk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builder_writes_one_row_per_coverage_level_and_keys_them(tmp_path):
    """The schema change, exercised: coverage_level is part of the key, not a build constant."""
    conn = _fixture_db(tmp_path)
    res = _builder().build(conn, _Args())
    assert res["n"] == 3 * 2 * 3                    # counties x bands x coverage levels
    got = [tuple(r) for r in conn.execute(
        "SELECT band, coverage_level, COUNT(*) FROM basis_risk_county GROUP BY 1,2 "
        "ORDER BY 1,2")]
    assert got == [("ECO95", 0.70, 3), ("ECO95", 0.80, 3), ("ECO95", 0.85, 3),
                   ("SCO86", 0.70, 3), ("SCO86", 0.80, 3), ("SCO86", 0.85, 3)]
    # A rebuild must replace, not accumulate — coverage_level is in the PRIMARY KEY.
    _builder().build(conn, _Args())
    assert conn.execute("SELECT COUNT(*) FROM basis_risk_county").fetchone()[0] == 18


def test_builder_output_falls_with_the_producer_coverage_level(tmp_path):
    """The same direction as the estimator test, but measured on written rows."""
    conn = _fixture_db(tmp_path)
    _builder().build(conn, _Args())
    for band in ("ECO95", "SCO86"):
        for fips in ("19000", "19001", "19002"):
            rates = [r[0] for r in conn.execute(
                "SELECT miss_rate FROM basis_risk_county WHERE band=? AND county_fips=? "
                "ORDER BY coverage_level", (band, fips))]
            assert len(rates) == 3
            assert rates == sorted(rates), (band, fips, rates)


def test_builder_refuses_a_degenerate_sco_band_instead_of_writing_a_zero(tmp_path):
    """SCO has no width at or above 0.86. That must be a skipped row with a reason, not a 0."""
    conn = _fixture_db(tmp_path)
    args = _Args(bands=["SCO86", "ECO95"], coverage_levels=[0.75, 0.85, 0.86])
    res = _builder().build(conn, args)
    assert conn.execute("SELECT COUNT(*) FROM basis_risk_county "
                        "WHERE band='SCO86' AND coverage_level=0.86").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM basis_risk_county "
                        "WHERE band='ECO95' AND coverage_level=0.86").fetchone()[0] == 3
    assert any("degenerate" in k for k in res["stats"]), res["stats"]


def test_builder_carries_the_rho_sensitivity_at_every_coverage_level(tmp_path):
    """rho is the single biggest uncertainty; the new dimension must not drop its band."""
    conn = _fixture_db(tmp_path)
    _builder().build(conn, _Args())
    rows = conn.execute(
        "SELECT coverage_level, rho_lo, miss_rate_rho_lo, rho_ref, miss_rate, rho_hi, "
        "miss_rate_rho_hi FROM basis_risk_county").fetchall()
    assert rows
    for cl, rlo, mlo, rref, m, rhi, mhi in rows:
        assert (rlo, rref, rhi) == (B.RHO_LO, B.RHO_REF, B.RHO_HI)
        assert mlo >= m >= mhi - 1e-9, cl      # less correlation, more basis risk


def test_report_pins_to_the_modal_election_not_the_top_of_the_grid(tmp_path, capsys):
    """Regression: the summary loop used to rebind `cl` and silently drag the drill-downs to 0.85.

    The whole point of the change is that the report stops standing on the worst-case corner, so
    the level it actually prints is worth a test rather than an eyeball.
    """
    conn = _fixture_db(tmp_path, counties=2)
    mod = _builder()
    mod.build(conn, _Args(coverage_levels=[0.70, 0.75, 0.85], bands=["ECO95"]))

    class _RArgs:
        at_coverage_level = None
    assert mod.report_coverage_level(conn, _RArgs()) == B.MODAL_COVERAGE_LEVEL

    _RArgs.at_coverage_level = 0.70
    assert mod.report_coverage_level(conn, _RArgs()) == 0.70

    mod.report(conn, _RArgs())
    out = capsys.readouterr().out
    assert "CL 0.70" in out and "COVERAGE-LEVEL BIAS" in out


def test_report_says_so_when_only_one_coverage_level_was_built(tmp_path, capsys):
    conn = _fixture_db(tmp_path, counties=2)
    mod = _builder()
    mod.build(conn, _Args(coverage_levels=[0.85], bands=["ECO95"]))
    mod.coverage_level_bias(conn)
    out = capsys.readouterr().out
    assert "only one coverage level" in out and "--coverage-levels" in out


def test_builder_records_data_grade_not_risk(tmp_path):
    """`grade` must stay a statement about years of history."""
    conn = _fixture_db(tmp_path)
    _builder().build(conn, _Args())
    for grade, n_years in conn.execute(
            "SELECT DISTINCT grade, n_years FROM basis_risk_county"):
        assert grade == B.grade_for(n_years)
        assert grade == "A"                    # the fixture gives every county 51 years
