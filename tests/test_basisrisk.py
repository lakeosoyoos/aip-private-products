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
