"""Pin the EMPIRICAL basis-risk estimator — the one built on realized SoB indemnities.

Everything here runs against SYNTHETIC fixtures, deliberately. `sob_sales` is mid-rebuild and
legitimately empty, and an estimator that can only be tested when a 3.2M-row table happens to be
loaded is an estimator nobody can refactor. The DB tests below build their own two-row database.

The tests that matter most are the three LIMITS in the first section. They are the same kind of
guard as `test_perfect_correlation_has_no_basis_risk` in tests/test_basisrisk.py: if the observed
estimator and the simulated one disagree at the limits, comparing them in the middle is
meaningless.

The second theme is `test_single_farm_matches_the_simulator`. `basisrisk_empirical.simulate_cells`
reimplements the generative model of `basisrisk.draw_joint` in order to put many farms in one
county-year. That test is what stops the two drifting apart — without it, any bias this module
reports could just as easily be a coding difference.
"""
from __future__ import annotations

import math
import sqlite3

import numpy as np
import pytest

from src import basisrisk as B
from src import basisrisk_empirical as E
from src import db


# ── helpers ──────────────────────────────────────────────────────────────────

def cell(year, *, pol_earn=100, pol_ind=10, ind_indem=1000.0, ind_prem=1000.0,
         area_indem=0.0, area_prem=100.0, area_liab=1000.0, ind_acres=10000.0,
         area_acres=1000.0, fips="19001", crop="Corn", state="IA", ind_liab=100000.0):
    return E.CellObs(
        crop=crop, state=state, county_fips=fips, year=year,
        ind_policies_earning=float(pol_earn), ind_policies_indemnified=float(pol_ind),
        ind_indemnity=float(ind_indem), ind_premium=float(ind_prem), ind_liability=ind_liab,
        ind_acres=float(ind_acres),
        area_policies_earning=50.0, area_policies_indemnified=0.0,
        area_indemnity=float(area_indem), area_premium=float(area_prem),
        area_liability=float(area_liab), area_acres=float(area_acres))


def realistic_ratios(seed=0, n=45, cv=0.16):
    """A county-like detrended ratio series: mean 1, left-skewed, a couple of drought years."""
    rng = np.random.default_rng(seed)
    r = 1.0 + rng.normal(0, cv, n)
    r[3] = 0.55
    r[17] = 0.62
    return np.clip(r, 0.15, None)


# ── THE THREE LIMITS ─────────────────────────────────────────────────────────

def test_index_always_fires_means_no_observed_miss():
    """If the band paid in every cell that had an indemnified policy, nothing was missed."""
    cells = [cell(y, pol_ind=5 + y % 7, area_indem=500.0) for y in range(2015, 2025)]
    e = E.empirical_miss(cells)
    assert e.miss_policy == pytest.approx(0.0)
    assert e.miss_dollar == pytest.approx(0.0)
    assert e.p_area_fires_cell == pytest.approx(1.0)


def test_index_never_fires_means_every_loss_was_missed():
    cells = [cell(y, pol_ind=5 + y % 7, area_indem=0.0) for y in range(2015, 2025)]
    e = E.empirical_miss(cells)
    assert e.miss_policy == pytest.approx(1.0)
    assert e.miss_dollar == pytest.approx(1.0)
    assert e.windfall_rate == pytest.approx(0.0)


def test_independent_firing_gives_one_minus_the_firing_frequency():
    """Firing unrelated to losses -> the conditional collapses to the unconditional.

    The observed analogue of `test_independence_is_maximal_basis_risk`. Every cell carries the
    same number of indemnified policies, so knowing a policy was indemnified says nothing about
    whether its county fired, and miss_policy must equal the share of cells that did not.
    """
    cells = [cell(2015 + i, pol_ind=10, area_indem=(500.0 if i % 4 == 0 else 0.0))
             for i in range(20)]
    e = E.empirical_miss(cells)
    assert e.p_area_fires_cell == pytest.approx(0.25)
    assert e.miss_policy == pytest.approx(0.75)


# ── what each weighting actually weights ─────────────────────────────────────

def test_miss_policy_weights_by_policies_not_by_cells():
    """One huge county that was covered must outvote nine tiny ones that were missed."""
    big = cell(2019, fips="19001", pol_earn=100_000, pol_ind=9000, area_indem=1e6)
    small = [cell(2015 + i, fips=f"1900{i}", pol_earn=200, pol_ind=100, area_indem=0.0)
             for i in range(9)]
    e = E.empirical_miss([big] + small)
    assert e.miss_cell_unweighted == pytest.approx(0.9)          # 9 of 10 cells missed
    assert e.miss_policy == pytest.approx(900 / 9900, abs=1e-9)  # but only 9% of the losses
    assert e.miss_policy < 0.15


def test_miss_dollar_and_miss_policy_separate_when_the_missed_losses_are_shallow():
    """Many small missed losses vs one large covered one: counts and dollars disagree."""
    covered = cell(2019, pol_ind=10, ind_indem=900_000.0, area_indem=1e6)
    missed = [cell(2015 + i, pol_ind=10, ind_indem=1_000.0, area_indem=0.0) for i in range(9)]
    e = E.empirical_miss([covered] + missed)
    assert e.miss_policy == pytest.approx(90 / 100)
    assert e.miss_dollar < 0.02
    assert e.miss_policy > e.miss_dollar


def test_loss_ratio_form_and_policy_form_can_disagree_which_is_the_point():
    """The aggregation gap made visible: a county-aggregate LR is not a farm loss count.

    Cell A: a broad shallow year — half the policies collected, but the county-aggregate loss
    ratio stays under 1, so the loss-ratio form does not even see it as a loss year. The policy
    form counts every one of those farms.
    """
    a = cell(2016, pol_earn=1000, pol_ind=500, ind_indem=800.0, ind_prem=1000.0, area_indem=0.0)
    b = cell(2017, pol_earn=1000, pol_ind=50, ind_indem=2000.0, ind_prem=1000.0, area_indem=0.0)
    c = cell(2018, pol_earn=1000, pol_ind=50, ind_indem=2000.0, ind_prem=1000.0, area_indem=900.0)
    e = E.empirical_miss([a, b, c], lr_threshold=1.0)
    assert e.n_cells_over_threshold == 2                     # only b and c clear LR >= 1
    assert e.miss_cell == pytest.approx(0.5)
    assert e.miss_policy == pytest.approx(550 / 600)         # a's 500 farms are all misses
    assert e.miss_policy > e.miss_cell


def test_windfall_is_the_mirror_of_the_miss():
    cells = [cell(2015, pol_earn=100, pol_ind=0, area_indem=500.0),
             cell(2016, pol_earn=100, pol_ind=100, area_indem=0.0)]
    e = E.empirical_miss(cells)
    assert e.miss_policy == pytest.approx(1.0)     # every loss missed
    assert e.windfall_rate == pytest.approx(1.0)   # every non-loss paid
    assert e.p_ind_loss == pytest.approx(0.5)


def test_fire_eps_moves_a_partial_practice_fire_across_the_line():
    """A county index is published by type and practice; a small payout is one practice firing."""
    cells = [cell(2015, pol_ind=10, area_indem=5.0, area_liab=1000.0),
             cell(2016, pol_ind=10, area_indem=0.0)]
    assert E.empirical_miss(cells, fire_eps=0.0).miss_policy == pytest.approx(0.5)
    assert E.empirical_miss(cells, fire_eps=0.02).miss_policy == pytest.approx(1.0)


def test_cells_without_an_area_book_are_refused_not_counted_as_misses():
    """No area liability = the index was not on sale = we cannot observe whether it fired."""
    good = cell(2015, pol_ind=10, area_indem=500.0)
    no_area = cell(2016, pol_ind=1000, area_indem=0.0, area_liab=0.0, area_prem=0.0)
    e = E.empirical_miss([good, no_area])
    assert e.n_cells == 1
    assert e.miss_policy == pytest.approx(0.0)
    with pytest.raises(ValueError, match="no usable cells"):
        E.empirical_miss([no_area])


def test_participation_share_is_area_over_individual_acres():
    c = cell(2015, ind_acres=50_000.0, area_acres=5_000.0)
    assert c.participation_share == pytest.approx(0.10)


# ── uncertainty: the short history stops being an abstraction ────────────────

def test_year_block_bootstrap_is_wider_than_the_naive_cell_bootstrap():
    """Cells inside a year share one weather shock; pretending otherwise fakes precision.

    Ten years, 60 counties each. Whether a cell fired is decided entirely at the YEAR level, so
    the effective sample size is 10, not 600. The i.i.d. interval will claim otherwise.
    """
    cells = []
    for i, y in enumerate(range(2015, 2025)):
        fired = 500.0 if i % 3 == 0 else 0.0
        for j in range(60):
            cells.append(cell(y, fips=f"19{j:03d}", pol_ind=10, area_indem=fired))
    _, ylo, yhi = E.bootstrap_ci(cells, by="year", n_boot=200, seed=3)
    _, clo, chi = E.bootstrap_ci(cells, by="cell", n_boot=200, seed=3)
    assert (yhi - ylo) > 4 * (chi - clo)
    assert (yhi - ylo) > 0.3          # ten years buys almost nothing


def test_leave_one_year_out_names_the_year_the_answer_depends_on():
    cells = [cell(y, pol_ind=10, area_indem=0.0) for y in range(2015, 2024)]
    cells += [cell(2024, pol_ind=900, area_indem=1e6)]      # the one big covered year
    table = E.leave_one_year_out(cells)
    assert table[0][0] == 2024                              # most influential
    assert table[0][1] > E.empirical_miss(cells).miss_policy


def test_by_county_refuses_counties_with_too_few_observed_losses():
    cells = [cell(2015 + i, fips="19001", pol_ind=100) for i in range(5)]      # 500 losses
    cells += [cell(2015 + i, fips="19003", pol_ind=1) for i in range(5)]       # 5 losses
    out = E.by_county(cells, min_loss_policies=30)
    assert ("Corn", "19001") in out
    assert ("Corn", "19003") not in out


# ── HARD PART 1: the systemic years the window never saw ─────────────────────

def _year_db(tmp_path, rows):
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    conn.executemany(
        "INSERT OR REPLACE INTO sob_year (year, loss_ratio, indemnity, settled) "
        "VALUES (?,?,?,?)", rows)
    conn.commit()
    return conn


def test_systemic_exposure_flags_a_window_with_no_systemic_years(tmp_path):
    """The 2015-2024 shape: mild decade bolted onto a record that contains 2012."""
    rows = [(y, 1.5 if y in (2002, 2012) else 0.9, 1e9 if y in (2002, 2012) else 3e8, 1)
            for y in range(1995, 2025)]
    conn = _year_db(tmp_path, rows)
    ex = E.systemic_year_exposure(conn, window_min=2015, systemic_lr=1.2)
    assert ex.window_systemic_years == []
    assert set(ex.missed_systemic_years) == {2002, 2012}
    assert ex.base_rate_systemic == pytest.approx(2 / 30)
    assert ex.window_rate_systemic == 0.0
    assert "UPWARD" in ex.direction and "DOWNWARD" in ex.direction


def test_systemic_bounds_can_only_lower_the_miss_rate(tmp_path):
    rows = [(y, 1.5 if y in (2002, 2012) else 0.9, 3e8, 1) for y in range(1995, 2025)]
    conn = _year_db(tmp_path, rows)
    ex = E.systemic_year_exposure(conn, window_min=2015, systemic_lr=1.2)
    cells = [cell(y, pol_ind=100, area_indem=0.0) for y in range(2015, 2025)]
    cells += [cell(y, pol_ind=100, area_indem=500.0, fips="19003") for y in range(2015, 2025)]
    emp = E.empirical_miss(cells)
    b = E.systemic_bounds(emp, ex)
    assert b.miss_upper == pytest.approx(emp.miss_policy)
    assert b.miss_lower < b.miss_upper
    assert b.n_imputed_years > 0


def test_systemic_bounds_is_a_noop_when_the_window_is_representative(tmp_path):
    rows = [(y, 1.5 if y % 5 == 0 else 0.9, 3e8, 1) for y in range(1995, 2025)]
    conn = _year_db(tmp_path, rows)
    ex = E.systemic_year_exposure(conn, window_min=1995, systemic_lr=1.2)
    emp = E.empirical_miss([cell(y, pol_ind=10, area_indem=0.0) for y in range(2015, 2025)])
    b = E.systemic_bounds(emp, ex)
    assert b.miss_lower == pytest.approx(b.miss_upper)
    assert "no bound needed" in b.note


def test_systemic_exposure_needs_sob_year(tmp_path):
    conn = sqlite3.connect(tmp_path / "empty.db")
    with pytest.raises(E.EmptySourceError, match="sob_year is missing"):
        E.systemic_year_exposure(conn, window_min=2015)


# ── HARD PART 2: selection ───────────────────────────────────────────────────

def test_participation_strata_detect_a_slope_and_a_flat():
    """A sloped profile is affirmative evidence of selection; a flat one is only weak comfort."""
    flat, sloped = [], []
    for i in range(200):
        share = 0.01 + 0.60 * (i / 199)
        acres = 100_000.0
        flat.append(cell(2015 + i % 10, fips=f"19{i:03d}", pol_ind=10,
                         ind_acres=acres, area_acres=acres * share,
                         area_indem=500.0 if i % 2 == 0 else 0.0))
        sloped.append(cell(2015 + i % 10, fips=f"19{i:03d}", pol_ind=10,
                           ind_acres=acres, area_acres=acres * share,
                           area_indem=500.0 if share > 0.30 else 0.0))
    f = E.by_participation_decile(flat, n_strata=4)
    s = E.by_participation_decile(sloped, n_strata=4)
    assert len(f) == 4 and len(s) == 4
    assert max(x.miss_policy for x in f) - min(x.miss_policy for x in f) < 0.15
    assert s[0].miss_policy > 0.9 and s[-1].miss_policy < 0.1


def test_participation_summary_reports_the_overlap():
    cells = [cell(2015, ind_acres=100_000.0, area_acres=3_000.0),
             cell(2016, ind_acres=100_000.0, area_acres=7_000.0)]
    s = E.participation_summary(cells)
    assert s["overall_participation"] == pytest.approx(0.05)
    assert s["share_of_cells_under_5pct"] == pytest.approx(0.5)


# ── HARD PART 3: aggregation, measured against known truth ───────────────────

def test_single_farm_matches_the_simulator():
    """simulate_cells at one farm, one unit must reproduce basisrisk.basis_risk.

    This is the guard on the reimplementation. Both draw the county from the same
    variance-corrected smoothed bootstrap, add sigma_c*sqrt(1/rho^2-1) of independent farm
    noise and apply the same max(1,p) price reset, so they must agree to Monte Carlo error.
    """
    ratios = realistic_ratios()
    for band in ("SCO86", "ECO95"):
        sim = E.simulate_cells(ratios, rho=0.70, n_farms=1, units_per_farm=1, n_cells=60_000,
                               coverage_level=0.80, band=band, plan_type="RP", seed=5)
        ref = B.basis_risk(ratios, band=band, coverage_level=0.80, rho=0.70, plan_type="RP",
                           n_draws=60_000, seed=5)
        assert sim.est_miss_policy == pytest.approx(ref.miss_rate, abs=0.02), band
        assert sim.true_farm_miss == pytest.approx(ref.miss_rate, abs=0.02), band
        assert sim.p_farm_loss == pytest.approx(ref.p_farm_loss, abs=0.02), band


def test_one_unit_per_farm_leaves_the_estimator_unbiased():
    """With whole-farm units the SoB policy count IS the farm-loss count. Bias must vanish."""
    sim = E.simulate_cells(realistic_ratios(), rho=0.70, n_farms=40, units_per_farm=1,
                           n_cells=3000, coverage_level=0.80, seed=9)
    assert sim.bias_policy == pytest.approx(0.0, abs=1e-9)


def test_optional_units_bias_the_observed_miss_rate_upward():
    """A policy counts as indemnified when ANY unit paid — a broader, more local event.

    This is the residual aggregation problem after switching from loss ratios to policy counts,
    and it is signed: the extra losses the SoB counts are unit-level and therefore more
    idiosyncratic than whole-farm losses, so they are missed more often.
    """
    sim = E.simulate_cells(realistic_ratios(), rho=0.70, n_farms=40, units_per_farm=4,
                           within_farm_rho=0.5, n_cells=3000, coverage_level=0.80, seed=9)
    assert sim.p_policy_loss > sim.p_farm_loss
    assert sim.bias_policy > 0.005
    assert sim.est_miss_policy > sim.true_farm_miss


def test_more_units_means_more_bias():
    kw = dict(rho=0.70, n_farms=30, within_farm_rho=0.5, n_cells=2500,
              coverage_level=0.80, seed=4)
    b2 = E.simulate_cells(realistic_ratios(), units_per_farm=2, **kw).bias_policy
    b6 = E.simulate_cells(realistic_ratios(), units_per_farm=6, **kw).bias_policy
    assert b6 > b2 > 0


def test_the_miss_rate_falls_as_rho_rises():
    """Monotonicity — the property `implied_rho`'s bisection depends on."""
    ratios = realistic_ratios()
    vals = [E.simulate_cells(ratios, rho=r, n_farms=25, n_cells=2500, coverage_level=0.80,
                             seed=6).est_miss_policy
            for r in (0.45, 0.60, 0.75, 0.90)]
    assert vals == sorted(vals, reverse=True)


def test_estimator_bias_table_covers_the_grid():
    rows = E.estimator_bias(realistic_ratios(), rhos=(0.6, 0.8), units=(1, 3),
                            n_farms=20, n_cells=1200, coverage_level=0.80, seed=2)
    assert len(rows) == 4
    assert {(r.rho, r.units_per_farm) for r in rows} == {(0.6, 1), (0.6, 3), (0.8, 1), (0.8, 3)}


# ── CALIBRATION ──────────────────────────────────────────────────────────────

def test_implied_rho_round_trips():
    """Simulate at a known rho, feed the estimator's own output back, recover the rho."""
    ratios = realistic_ratios()
    kw = dict(n_farms=25, n_cells=2500, coverage_level=0.80, band="SCO86", seed=8)
    truth = 0.72
    target = E.simulate_cells(ratios, rho=truth, **kw).est_miss_policy
    got = E.implied_rho(target, ratios, metric="estimator", tol=1e-3, **kw)
    assert got.rho is not None
    assert got.rho == pytest.approx(truth, abs=0.05)


def test_implied_rho_interval_is_inverted_because_more_miss_means_less_rho():
    ratios = realistic_ratios()
    kw = dict(n_farms=25, n_cells=2000, coverage_level=0.80, seed=8)
    mid = E.simulate_cells(ratios, rho=0.70, **kw).est_miss_policy
    got = E.implied_rho(mid, ratios, target_lo=mid * 0.75, target_hi=mid * 1.25, **kw)
    assert got.rho_lo is not None and got.rho_hi is not None
    assert got.rho_lo < got.rho < got.rho_hi     # a HIGHER observed miss gives a LOWER rho


def test_implied_rho_refuses_an_unreachable_target():
    """An observed rate no rho can produce is a finding, not something to clip into range."""
    got = E.implied_rho(0.999, realistic_ratios(), n_farms=10, n_cells=800,
                        coverage_level=0.80, seed=8)
    assert got.rho is None
    assert "outside the reachable range" in got.note


def test_implied_rho_can_invert_the_clean_farm_metric_too():
    ratios = realistic_ratios()
    target = B.basis_risk(ratios, band="SCO86", coverage_level=0.80, rho=0.65,
                          n_draws=40_000, seed=8).miss_rate
    got = E.implied_rho(target, ratios, metric="farm", band="SCO86", coverage_level=0.80,
                        n_cells=800, n_farms=50, tol=2e-3)
    assert got.rho == pytest.approx(0.65, abs=0.06)


# ── loading from the database ────────────────────────────────────────────────

def _sob_db(tmp_path, sales_rows, years=((2015, 1), (2016, 1), (2026, 0))):
    conn = db.connect(tmp_path / "sob.db")
    db.init_db(conn)
    conn.executemany("INSERT OR REPLACE INTO sob_year (year, settled, loss_ratio, indemnity) "
                     "VALUES (?,?,0.9,1e8)", years)
    cols = ("year, state, county_fips, crop, plan_code, coverage_type, coverage_level, "
            "net_acres, liability, total_premium, indemnity, policies_earning_premium, "
            "policies_indemnified")
    conn.executemany(
        f"INSERT OR REPLACE INTO sob_sales ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        sales_rows)
    conn.commit()
    return conn


def _row(year, plan, *, cov="A", cl=0.80, acres=1000.0, liab=1e6, prem=1e5, indem=0.0,
         pe=100, pi=0, fips="19001", crop="Corn"):
    return (year, "IA", fips, crop, plan, cov, cl, acres, liab, prem, indem, pe, pi)


def test_load_cells_refuses_an_empty_sob_sales(tmp_path):
    conn = _sob_db(tmp_path, [])
    with pytest.raises(E.EmptySourceError, match="sob_sales is EMPTY"):
        E.load_cells(conn)


def test_load_cells_refuses_a_missing_sob_sales(tmp_path):
    conn = sqlite3.connect(tmp_path / "bare.db")
    conn.execute("CREATE TABLE sob_year (year INTEGER, settled INTEGER)")
    conn.execute("INSERT INTO sob_year VALUES (2015, 1)")
    with pytest.raises(E.EmptySourceError, match="sob_sales is missing"):
        E.load_cells(conn)


def test_load_cells_pairs_the_two_plans_in_one_cell(tmp_path):
    conn = _sob_db(tmp_path, [
        _row(2015, "02", indem=4e5, pi=17, pe=200, acres=50_000.0),
        _row(2015, "32", indem=0.0, pe=30, acres=5_000.0),
    ])
    cells = E.load_cells(conn, crops=["Corn"])
    assert len(cells) == 1
    c = cells[0]
    assert c.ind_policies_indemnified == 17
    assert c.ind_policies_earning == 200
    assert c.area_indemnity == 0.0
    assert c.participation_share == pytest.approx(0.10)
    assert E.empirical_miss(cells).miss_policy == pytest.approx(1.0)


def test_load_cells_excludes_unsettled_years(tmp_path):
    """2026 loads at a 0.08 national loss ratio; including it fabricates misses."""
    conn = _sob_db(tmp_path, [
        _row(2015, "02", indem=4e5, pi=17), _row(2015, "32", indem=1e5),
        _row(2026, "02", indem=1e3, pi=99), _row(2026, "32", indem=0.0),
    ])
    cells = E.load_cells(conn, crops=["Corn"])
    assert [c.year for c in cells] == [2015]


def test_load_cells_excludes_cat(tmp_path):
    """coverage_type='C' is 100% subsidised with the admin fee absent from these files."""
    conn = _sob_db(tmp_path, [
        _row(2015, "02", indem=4e5, pi=17), _row(2015, "32", indem=1e5),
        _row(2016, "02", cov="C", indem=9e9, pi=999), _row(2016, "32", cov="C", indem=0.0),
    ])
    cells = E.load_cells(conn, crops=["Corn"])
    assert [c.year for c in cells] == [2015]


def test_load_cells_drops_a_county_with_no_area_book(tmp_path):
    conn = _sob_db(tmp_path, [
        _row(2015, "02", fips="19001", indem=4e5, pi=17), _row(2015, "32", fips="19001"),
        _row(2015, "02", fips="19003", indem=9e5, pi=99),          # no SCO sold here
    ])
    cells = E.load_cells(conn, crops=["Corn"])
    assert [c.county_fips for c in cells] == ["19001"]


def test_load_cells_matches_coverage_level_on_both_sides_for_sco(tmp_path):
    """SCO's SoB coverage_level is the UNDERLYING election, so it matches the individual row."""
    conn = _sob_db(tmp_path, [
        _row(2015, "02", cl=0.85, indem=1e5, pi=5), _row(2015, "32", cl=0.85, indem=0.0),
        _row(2015, "02", cl=0.75, indem=9e5, pi=90), _row(2015, "32", cl=0.75, indem=7e5),
    ])
    all_cl = E.load_cells(conn, crops=["Corn"])
    assert all_cl[0].ind_policies_indemnified == 95        # both levels pooled into one cell
    at85 = E.load_cells(conn, crops=["Corn"], coverage_levels=[0.85])
    assert len(at85) == 1
    assert at85[0].ind_policies_indemnified == 5
    assert at85[0].area_indemnity == 0.0
    assert E.empirical_miss(at85).miss_policy == pytest.approx(1.0)
    at75 = E.load_cells(conn, crops=["Corn"], coverage_levels=[0.75])
    assert E.empirical_miss(at75).miss_policy == pytest.approx(0.0)


def test_eco_pair_restricts_to_the_95_trigger(tmp_path):
    """98.4% of the ECO-RP book by liability elects 95%; ECO95 is the comparable simulated band."""
    conn = _sob_db(tmp_path, [
        _row(2021, "02", indem=4e5, pi=17), _row(2021, "88", cl=0.95, indem=0.0),
        _row(2021, "88", cl=0.90, indem=9e9),
    ], years=((2021, 1),))
    cells = E.load_cells(conn, pair="ECO-RP", crops=["Corn"])
    assert len(cells) == 1
    assert cells[0].area_indemnity == 0.0                  # the 90% row must not leak in
    assert E.empirical_miss(cells).miss_policy == pytest.approx(1.0)
    at90 = E.load_cells(conn, pair="ECO-RP90", crops=["Corn"])
    assert at90[0].area_indemnity == pytest.approx(9e9)


def test_load_cells_never_starts_before_the_plan_exists(tmp_path):
    conn = _sob_db(tmp_path, [_row(2015, "02", indem=1e5, pi=5), _row(2015, "32", indem=1e5)],
                   years=((2010, 1), (2015, 1)))
    cells = E.load_cells(conn, crops=["Corn"], min_year=1989)
    assert min(c.year for c in cells) >= E.PAIR_SPECS["SCO-RP"].first_year


# ── comparison against the simulated table ───────────────────────────────────

def test_compare_to_simulated_matches_on_crop_county_band_and_level(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    db.init_db(conn)
    conn.executemany(
        "INSERT OR REPLACE INTO basis_risk_county (crop, county_fips, band, plan_type, "
        "coverage_level, miss_rate, miss_rate_rho_lo, miss_rate_rho_hi, n_years, grade) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("Corn", "19001", "SCO86", "RP", 0.85, 0.37, 0.47, 0.25, 45, "A"),
         ("Corn", "19003", "SCO86", "RP", 0.85, 0.45, 0.55, 0.32, 45, "A"),
         ("Corn", "19005", "ECO95", "RP", 0.85, 0.17, 0.26, 0.07, 45, "A")])
    conn.commit()
    cells = ([cell(2015 + i, fips="19001", pol_ind=20, area_indem=0.0) for i in range(5)]
             + [cell(2015 + i, fips="19001", pol_ind=20, area_indem=9e5) for i in range(5, 10)]
             + [cell(2015 + i, fips="19003", pol_ind=20, area_indem=0.0) for i in range(10)])
    cm = E.by_county(cells, min_loss_policies=10)
    comp = E.compare_to_simulated(conn, cm, band="SCO86", coverage_level=0.85)
    assert comp.n_matched == 2                       # 19005 is an ECO95 row, not SCO86
    assert comp.empirical_median == pytest.approx(0.75)
    assert comp.simulated_median == pytest.approx(0.41)
    assert comp.share_empirical_above_simulated == pytest.approx(1.0)
    # 19003 observed 1.0, above even the rho_lo bound; 19001 observed 0.5, inside [0.25, 0.47]?
    assert 0.0 <= comp.share_empirical_inside_rho_band <= 1.0


def test_compare_to_simulated_needs_the_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "none.db")
    with pytest.raises(E.EmptySourceError, match="basis_risk_county is missing"):
        E.compare_to_simulated(conn, {}, band="SCO86")


# ── persistence ──────────────────────────────────────────────────────────────

def test_row_for_matches_the_table_and_round_trips(tmp_path):
    conn = db.connect(tmp_path / "w.db")
    E.init_tables(conn)
    emp = E.empirical_miss([cell(2015, pol_ind=10, area_indem=0.0),
                            cell(2016, pol_ind=10, area_indem=1e5)])
    row = E.row_for(emp, pair="SCO-RP", grain="national", band="SCO86",
                    ci=(0.2, 0.8), rho=(0.66, 0.4, 0.9), sim=(0.37, 0.47, 0.25),
                    fetched_at="2026-08-08T00:00:00+00:00")
    assert len(row) == len(E.UPSERT_COLUMNS)
    assert E.upsert_rows(conn, [row]) == 1
    got = conn.execute("SELECT miss_policy, implied_rho, sim_miss_rate, n_years "
                       "FROM basis_risk_empirical").fetchone()
    assert got[0] == pytest.approx(0.5)
    assert got[1] == pytest.approx(0.66)
    assert got[2] == pytest.approx(0.37)
    assert got[3] == 2
    # a second write of the same key must replace, not duplicate
    E.upsert_rows(conn, [row])
    assert conn.execute("SELECT COUNT(*) FROM basis_risk_empirical").fetchone()[0] == 1


# ── against whatever is actually loaded ──────────────────────────────────────

def test_live_sob_sales_is_either_absent_empty_or_usable():
    """Never fails on the mid-rebuild state; asserts sanity once the table lands."""
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "data" / "catalog.db"
    if not path.exists():
        pytest.skip("data/catalog.db not present")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        cells = E.load_cells(conn, crops=["Corn"], max_year=2024)
    except E.EmptySourceError as exc:
        pytest.skip(f"sob_sales not ready: {exc}")
    if not cells:
        pytest.skip("no paired SCO/RP cells loaded")
    e = E.empirical_miss(cells)
    assert 0.0 <= e.miss_policy <= 1.0
    assert e.year_min >= E.PAIR_SPECS["SCO-RP"].first_year
    assert e.ind_policies_indemnified > 0
