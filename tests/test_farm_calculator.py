"""Tests for the PER-FARM basis-risk calculator (src/rowcroppage.py, bottom section).

WHAT IS BEING PROTECTED HERE. Everything else in the row-crop stack is county-typical, and
county-typical rests on ONE imported number: a farm-to-county yield correlation of 0.70
applied to every county in the United States (src/basisrisk.RHO_REF). That assumption swings
the answer roughly 2x. This calculator lets a producer replace it with a measurement from
their own APH schedule, so the tests fall into three groups:

  * IT MEASURES THE RIGHT THING — a farm that IS its county has almost no basis risk, a farm
    unrelated to its county has a lot, and the two are told apart from yields alone.
  * IT DETRENDS AND ALIGNS FIRST — a raw correlation of two trending series is nearly
    meaningless, so a farm on a pure trend with no shared weather must NOT come out correlated.
  * IT REFUSES RATHER THAN GUESSES — too few years, a bad paste, no county history, an
    unusable correlation. Each of those has an exact, visible behaviour, because the failure
    mode of this page is not a traceback, it is a confident number a producer acts on.

No network, no real DB: every county history here is synthetic and built in-process.
"""
from __future__ import annotations

import math
import sqlite3

import numpy as np
import pytest

from src import basisrisk as B, db
from src.rowcroppage import (
    COUNTY_SERIES_TABLE, FARM_BANDS, FARM_MIN_YEARS, FARM_POINT_YEARS, CountySeries,
    build_county_yield_series, confidence_for, county_choices, farm_report,
    load_county_series, parse_aph_series, published_basis_risk, typical_miss_by_band,
)

DRAWS = 30_000          # enough for stable 2-decimal probabilities, fast enough for CI


# --------------------------------------------------------------------- fixtures

def county_history(n: int = 45, cv: float = 0.18, seed: int = 11, start: int = 1981):
    """A synthetic county: a linear technology trend plus multiplicative weather."""
    rng = np.random.default_rng(seed)
    years = list(range(start, start + n))
    trend = np.array([100.0 + 1.5 * (y - start) for y in years])
    return years, [float(v) for v in trend * (1 + rng.normal(0, cv, n))]


def series_for(years, values, *, crop="Corn", fips="19153") -> CountySeries:
    return CountySeries(
        crop=crop, county_fips=fips, state="IA", county_name="POLK",
        years=list(years), values=list(values),
        class_used="ALL CLASSES", practice_used="ALL PRODUCTION PRACTICES",
        corr_national=0.6, source="test")


def tracking_farm(years, values, farm_years, *, scale=0.9):
    """A farm whose yields are a fixed multiple of the county's: it IS the county, scaled."""
    ix = {y: v for y, v in zip(years, values)}
    return {y: ix[y] * scale for y in farm_years}


def loner_farm(years, values, farm_years, *, weight=0.3, noise=0.22, seed=404):
    """A farm that shares only `weight` of its county's weather and has its own on top.

    weight=1.0 with no noise is the county; weight=0.0 is a farm with nothing in common with
    it. The interesting cases live between, and a real "loner" is a weak POSITIVE correlation
    rather than a zero one — two farms in the same county do share some weather.
    """
    fit = B.detrend(years, values, "ols")
    ratio = dict(zip([int(y) for y in fit.years], fit.ratio))
    rng = np.random.default_rng(seed)
    base = np.array([100.0 + 1.5 * (y - years[0]) for y in farm_years]) * 0.9
    shape = 1.0 + weight * (np.array([ratio[y] for y in farm_years]) - 1.0)
    vals = base * shape * (1 + rng.normal(0, noise, len(farm_years)))
    return {y: float(v) for y, v in zip(farm_years, vals)}


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    return c


def _load_nass(conn, crop, fips, years, values, *, state="IA", name="POLK",
               cls="ALL CLASSES", prac="ALL PRODUCTION PRACTICES"):
    conn.executemany(
        "INSERT OR REPLACE INTO nass_county_yield (crop, stat, class_desc, practice, unit, "
        " agg_level, loc_key, state, county_fips, county_name, year, value, source, fetched_at) "
        "VALUES (?, 'YIELD', ?, ?, 'BU / ACRE', 'COUNTY', ?, ?, ?, ?, ?, ?, 'test', '2026-08-08')",
        [(crop, cls, prac, fips, state, fips, name, int(y), float(v))
         for y, v in zip(years, values)])
    conn.commit()


def _load_basis_row(conn, crop, fips, band, *, miss=0.30, cl=0.85, grade="A"):
    conn.execute(
        "INSERT OR REPLACE INTO basis_risk_county (crop, county_fips, state, county_name, band, "
        " plan_type, coverage_level, n_years, year_min, year_max, class_used, practice_used, "
        " detrend_method, county_cv, corr_national, rho_ref, miss_rate, grade, source, fetched_at) "
        "VALUES (?,?,'IA','POLK',?, 'RP', ?, 45, 1981, 2025, 'ALL CLASSES', "
        " 'ALL PRODUCTION PRACTICES', 'ols', 0.18, 0.6, 0.70, ?, ?, 'test', '2026-08-08')",
        (crop, fips, band, cl, miss, grade))
    conn.commit()


# =============================================================================
# 1. INPUT — an agent typing what a producer reads off a schedule
# =============================================================================

def test_year_labelled_pairs_in_every_shape_a_paste_arrives_in():
    for text in (
        "2016: 178\n2017: 201\n2018: 165",
        "2016,178\n2017,201\n2018,165",
        "2016\t178\n2017\t201\n2018\t165",
        "2016 = 178\n2017 = 201\n2018 = 165",
        "2016: 178; 2017: 201; 2018: 165",
    ):
        farm, problems = parse_aph_series(text)
        assert farm == {2016: 178.0, 2017: 201.0, 2018: 165.0}, text
        assert problems == [], text


def test_a_bare_list_needs_the_oldest_year_and_says_why():
    farm, problems = parse_aph_series("178, 201, 165")
    assert farm == {}
    assert any("oldest" in p for p in problems)

    farm, problems = parse_aph_series("178, 201, 165", 2016)
    assert farm == {2016: 178.0, 2017: 201.0, 2018: 165.0}
    assert problems == []


def test_a_blank_year_holds_its_slot_instead_of_shifting_the_series():
    """The failure this prevents is silent: every later year lines up against the wrong one."""
    farm, _ = parse_aph_series("178, NA, 165, -, 190", 2016)
    assert farm == {2016: 178.0, 2018: 165.0, 2020: 190.0}
    assert 2017 not in farm and 2019 not in farm


def test_a_blank_in_a_labelled_pair_is_simply_a_year_not_grown():
    farm, problems = parse_aph_series("2016: 178\n2017: NA\n2018: 165")
    assert farm == {2016: 178.0, 2018: 165.0}
    assert problems == []


def test_pasting_only_years_is_caught_rather_than_read_as_yields():
    farm, problems = parse_aph_series("2016, 2017, 2018, 2019")
    assert farm == {}
    assert any("look" in p and "year" in p for p in problems)


def test_a_year_in_the_yield_column_is_refused_not_averaged_in():
    farm, problems = parse_aph_series("2016: 178\n2017: 2017\n2018: 165")
    assert farm == {2016: 178.0, 2018: 165.0}
    assert any("looks like a year" in p for p in problems)


def test_zero_and_absurd_yields_are_dropped_with_a_reason():
    farm, problems = parse_aph_series("2016: 178\n2017: 0\n2018: 41000\n2019: 165")
    assert farm == {2016: 178.0, 2019: 165.0}
    assert any("total crop failure" in p for p in problems)
    assert any("implausibly high" in p for p in problems)


def test_a_spreadsheet_paste_with_a_header_and_thousands_commas_survives():
    farm, _ = parse_aph_series("Year\tYield\n2016\t178\n2017\t201\n2018\t1,650")
    assert farm[2016] == 178.0 and farm[2017] == 201.0
    assert 2018 not in farm                       # 1650 bu/ac is refused, not silently kept


def test_a_repeated_year_keeps_the_last_and_says_so():
    farm, problems = parse_aph_series("2016: 178\n2016: 180")
    assert farm == {2016: 180.0}
    assert any("more than once" in p for p in problems)


def test_empty_input_is_empty_not_an_error():
    assert parse_aph_series("") == ({}, [])
    assert parse_aph_series("   \n\n ") == ({}, [])


# =============================================================================
# 2. UNCERTAINTY — the thresholds are arithmetic, and the page has to enforce them
# =============================================================================

def test_too_few_years_is_refused_and_the_minimum_is_stated():
    c = confidence_for(FARM_MIN_YEARS - 1)
    assert c["usable"] is False and c["show_point"] is False
    assert str(FARM_MIN_YEARS) in c["detail"]
    assert "1/sqrt(n-3)" in c["detail"]            # the reason, not just the rule


def test_a_short_series_gets_an_interval_but_no_point_estimate():
    c = confidence_for(FARM_MIN_YEARS)
    assert c["usable"] is True and c["show_point"] is False
    assert confidence_for(FARM_POINT_YEARS)["show_point"] is True


def test_the_interval_narrows_monotonically_with_years_and_stays_wide_at_ten():
    widths = [confidence_for(n)["half_width"] for n in (6, 10, 15, 20, 30)]
    assert all(a > b for a, b in zip(widths, widths[1:]))
    # A full RMA APH database is ten years. It buys an interval of about +/-0.33 around 0.70 —
    # which is the single most important honesty fact on the page.
    assert widths[1] > 0.25
    assert widths[-1] < 0.20


# =============================================================================
# 3. THE COUNTY SERIES — where it comes from, and what happens when it is absent
# =============================================================================

def test_no_county_history_anywhere_returns_none_rather_than_a_substitute(conn):
    assert load_county_series(conn, "Corn", "19153") is None


def test_the_raw_nass_table_is_read_when_it_is_there(conn):
    years, values = county_history()
    _load_nass(conn, "Corn", "19153", years, values)
    s = load_county_series(conn, "Corn", "19153")
    assert s is not None
    assert s.source == "nass_county_yield"
    assert s.years == years and s.label == "Polk County, IA"
    assert s.grade == "A"


def test_the_compact_sidecar_is_preferred_over_the_raw_table(conn):
    """The sidecar is what SHIPS; if both are present the shipped path must be the one tested."""
    years, values = county_history()
    _load_nass(conn, "Corn", "19153", years, values)
    for band in FARM_BANDS:
        _load_basis_row(conn, "Corn", "19153", band)
    assert build_county_yield_series(conn, crops=("Corn",)) == 1
    s = load_county_series(conn, "Corn", "19153")
    assert s.source == COUNTY_SERIES_TABLE
    assert s.years == years
    assert s.values == pytest.approx(values, rel=1e-4)
    assert s.corr_national == pytest.approx(0.6)
    assert s.class_used == "ALL CLASSES"


def test_the_sidecar_builder_refuses_without_its_input(conn):
    conn.execute("DROP TABLE nass_county_yield")
    with pytest.raises(RuntimeError, match="nass_county_yield"):
        build_county_yield_series(conn)


def test_the_sidecar_only_covers_counties_that_have_a_published_baseline(conn):
    """A county with no county-typical figure has nothing to measure the farm answer against."""
    years, values = county_history()
    _load_nass(conn, "Corn", "19153", years, values)
    _load_nass(conn, "Corn", "19155", years, values, name="POTTAWATTAMIE")
    _load_basis_row(conn, "Corn", "19153", "ECO95")
    assert build_county_yield_series(conn, crops=("Corn",)) == 1
    assert load_county_series(conn, "Corn", "19155") is not None      # falls back to raw NASS
    got = conn.execute(f"SELECT county_fips FROM {COUNTY_SERIES_TABLE}").fetchall()
    assert [r[0] for r in got] == ["19153"]


def test_a_series_too_short_to_publish_is_not_offered(conn):
    years, values = county_history(n=B.MIN_YEARS - 1)
    _load_nass(conn, "Corn", "19153", years, values)
    assert load_county_series(conn, "Corn", "19153") is None


def test_published_and_national_baselines_read_cleanly(conn):
    for band, miss in (("ECO95", 0.16), ("ECO90", 0.26), ("SCO86", 0.36)):
        _load_basis_row(conn, "Corn", "19153", band, miss=miss)
    pub = published_basis_risk(conn, "Corn", "19153")
    assert set(pub) == set(FARM_BANDS)
    assert pub["SCO86"]["miss_rate"] == pytest.approx(0.36)
    assert typical_miss_by_band(conn)["ECO95"] == pytest.approx(0.16)
    assert county_choices(conn, "Corn") == [("19153", "IA", "Polk, IA")]
    assert county_choices(conn, "Soybeans") == []


def test_every_reader_is_graceful_against_a_database_with_no_schema():
    bare = sqlite3.connect(":memory:")
    assert load_county_series(bare, "Corn", "19153") is None
    assert published_basis_risk(bare, "Corn", "19153") == {}
    assert typical_miss_by_band(bare) == {}
    assert county_choices(bare, "Corn") == []
    bare.close()


# =============================================================================
# 4. THE MEASUREMENT — the two farms this whole feature exists to tell apart
# =============================================================================

def test_a_farm_that_is_its_county_has_almost_no_basis_risk():
    years, values = county_history()
    s = series_for(years, values)
    farm = tracking_farm(years, values, years[-12:])
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)

    assert r.rho > 0.99
    assert r.outcome["ECO95"].farm_miss < 0.05
    assert r.outcome["ECO95"].hist_miss_years == []
    assert r.rho_is_measured is True


def test_a_farm_unrelated_to_its_county_carries_far_more_basis_risk():
    """Same county, same subsidy, same 5x gross. Different farm, different honest answer."""
    years, values = county_history()
    s = series_for(years, values)
    tracker = farm_report(s, tracking_farm(years, values, years[-25:]),
                          plan_type="YP", n_draws=DRAWS)
    loner = farm_report(s, loner_farm(years, values, years[-25:]),
                        plan_type="YP", n_draws=DRAWS)

    assert tracker.rho > 0.9
    assert 0.0 < loner.rho < 0.6
    assert loner.outcome["ECO95"].farm_miss > tracker.outcome["ECO95"].farm_miss + 0.2
    # Each disagrees with the assumed 0.70 in the direction its own yields say it should.
    assert loner.outcome["ECO95"].disagreement > 0.05
    assert tracker.outcome["ECO95"].disagreement < -0.05
    # ... and the county-typical figure is IDENTICAL for both, which is the point.
    assert (loner.outcome["ECO95"].assumed_miss ==
            pytest.approx(tracker.outcome["ECO95"].assumed_miss, abs=1e-9))


def test_a_farm_with_no_measurable_link_to_its_county_is_refused_not_scored():
    """A sample correlation at or below zero is not "no basis risk" — it is no measurement.

    Over a long run a farm cannot be uncorrelated with the county it sits in, so a
    non-positive sample rho means the sample is too short or the inputs are wrong. The
    estimator falls back to the assumed 0.70, which is OPTIMISTIC for a farm that visibly does
    not track — so the fallback has to be loud, and `rho_is_measured` is what the page reads
    to make it loud.
    """
    years, values = county_history()
    s = series_for(years, values)
    farm = loner_farm(years, values, years[-25:], weight=0.0, noise=0.22, seed=404)
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)
    assert r.rho <= 0.0
    assert r.rho_is_measured is False
    assert r.rho_used == pytest.approx(B.RHO_REF)
    assert any("NOT farm-specific" in w for w in r.warnings)


def test_the_correlation_is_measured_on_detrended_series_not_raw_ones():
    """A farm on a pure trend shares NO weather with its county. Raw, it would look correlated.

    Both series rise over the window, so their raw correlation is high; after detrending there
    is nothing left in the farm series to correlate, which is the truth.
    """
    years, values = county_history(cv=0.20)
    s = series_for(years, values)
    farm_years = years[-20:]
    farm = {y: 100.0 + 1.5 * (y - years[0]) for y in farm_years}     # trend only, no weather

    raw = float(np.corrcoef([farm[y] for y in farm_years],
                            [values[years.index(y)] for y in farm_years])[0, 1])
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)

    assert raw > 0.5                                  # the trap: raw looks like a relationship
    assert abs(r.rho) < 0.35 or math.isnan(r.rho)     # detrended, the relationship is gone


def test_a_farm_with_no_variability_at_all_cannot_be_correlated_with_anything():
    """A flat series has no correlation to measure. It must fall back loudly, not divide by 0."""
    years, values = county_history()
    s = series_for(years, values)
    farm = {y: 180.0 for y in years[-12:]}
    r = farm_report(s, farm, plan_type="YP", farm_detrend="none", n_draws=DRAWS)
    assert math.isnan(r.rho)
    assert r.rho_is_measured is False
    assert r.rho_used == pytest.approx(B.RHO_REF)
    assert any("NOT farm-specific" in w for w in r.warnings)


def test_the_confidence_interval_on_the_correlation_brackets_the_miss_rate():
    years, values = county_history()
    s = series_for(years, values)
    rng = np.random.default_rng(5)
    farm_years = years[-10:]
    base = np.array([values[years.index(y)] for y in farm_years])
    farm = {y: float(v) for y, v in zip(farm_years, base * (1 + rng.normal(0, 0.12, 10)))}

    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)
    assert r.rho_ci_lo < r.rho < r.rho_ci_hi
    assert r.rho_ci_hi - r.rho_ci_lo > 0.10           # ten APH years buys a wide interval
    for o in r.bands:
        # lo/hi are named after the MISS rate, not after rho; the inversion is deliberate.
        assert o.farm_miss_lo <= o.farm_miss <= o.farm_miss_hi + 1e-9


# =============================================================================
# 5. THE DECISION — every band on the same footing, and the comparison it answers
# =============================================================================

def test_every_band_is_scored_and_a_deeper_trigger_always_misses_more():
    """ECO95 < ECO90 < SCO86 on miss rate, for any farm: a deeper trigger fires less often."""
    years, values = county_history()
    s = series_for(years, values)
    farm = loner_farm(years, values, years[-20:])
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)

    assert [o.band for o in r.bands] == list(FARM_BANDS)
    miss = {o.band: o.farm_miss for o in r.bands}
    assert miss["ECO95"] < miss["ECO90"] < miss["SCO86"]
    assert r.best_band == "ECO95"


def test_band_geometry_is_reported_as_the_producer_would_be_sold_it():
    years, values = county_history()
    r = farm_report(series_for(years, values),
                    tracking_farm(years, values, years[-15:]),
                    coverage_level=0.75, plan_type="YP", n_draws=DRAWS)
    o = r.outcome
    assert (o["ECO95"].trigger, o["ECO95"].exit) == (0.95, 0.86)
    assert (o["ECO90"].trigger, o["ECO90"].exit) == (0.90, 0.86)
    # SCO runs from 86% DOWN to the producer's OWN coverage level, so its width is theirs.
    assert (o["SCO86"].trigger, o["SCO86"].exit) == (0.86, 0.75)
    assert o["SCO86"].width == pytest.approx(0.11)


def test_the_assumed_070_answer_is_computed_alongside_so_the_gap_is_visible():
    """The comparison that holds: same county, same deductible, only the correlation swapped."""
    years, values = county_history()
    s = series_for(years, values)
    r = farm_report(s, tracking_farm(years, values, years[-20:]), plan_type="YP", n_draws=DRAWS)
    o = r.outcome["SCO86"]
    assert o.assumed_rho == pytest.approx(B.RHO_REF)
    assert 0.0 < o.assumed_miss < 1.0
    assert o.farm_miss < o.assumed_miss               # this farm tracks better than assumed
    assert o.disagreement < 0


def test_the_published_county_typical_row_is_carried_and_labelled_with_its_coverage_level():
    years, values = county_history()
    s = series_for(years, values)
    published = {b: {"miss_rate": 0.33, "coverage_level": 0.85, "grade": "A"} for b in FARM_BANDS}
    r = farm_report(s, tracking_farm(years, values, years[-15:]), coverage_level=0.70,
                    plan_type="YP", published=published, national={"ECO95": 0.162},
                    n_draws=DRAWS)
    o = r.outcome["ECO95"]
    assert o.published_miss == pytest.approx(0.33)
    assert o.published_coverage_level == pytest.approx(0.85)
    assert o.national_typical_miss == pytest.approx(0.162)
    # The shipped row is built at 85% only; at any other deductible it is NOT comparable and
    # the report has to say so rather than let the reader line the two up.
    assert any("NOT directly comparable" in n for n in r.notes)


def test_the_gross_return_is_identical_across_bands_and_the_loss_aligned_one_is_not():
    """The sales pitch is the same 5x everywhere. What differs is where those dollars land."""
    years, values = county_history()
    r = farm_report(series_for(years, values),
                    loner_farm(years, values, years[-20:]),
                    plan_type="YP", n_draws=DRAWS)
    assert {round(o.gross_return, 6) for o in r.bands} == {5.0}
    aligned = [o.loss_aligned_return for o in r.bands]
    assert len(set(round(a, 3) for a in aligned)) > 1
    assert all(0 < a < 5.0 for a in aligned)


def test_the_producers_own_years_are_named_not_just_counted():
    years = list(range(2006, 2026))
    county = [100.0] * 20
    farm_vals = [100.0] * 20
    farm_vals[5] = 50.0                                # one farm-specific disaster, 2011
    s = series_for(years, county)
    r = farm_report(s, dict(zip(years, farm_vals)), plan_type="YP", farm_detrend="none",
                    detrend_method="mean", n_draws=DRAWS)
    o = r.outcome["ECO95"]
    assert 2011 in o.hist_loss_years
    assert o.hist_miss_years == [2011]
    assert o.hist_pay_years == []


def test_years_with_no_county_figure_are_dropped_and_the_reason_is_given():
    """NASS suppresses a county estimate when too few operations report. That is MISSING, not 0."""
    years, values = county_history()
    s = series_for(years, values)
    farm = tracking_farm(years, values, years[-12:])
    farm[years[-1] + 5] = 190.0                        # a year the county series does not have
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)
    assert r.dropped_years == [years[-1] + 5]
    assert any("suppress" in n for n in r.notes)


def test_the_alignment_the_page_shows_is_the_one_the_maths_used():
    years, values = county_history()
    s = series_for(years, values)
    farm = tracking_farm(years, values, years[-12:])
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)
    assert len(r.years) == len(r.farm_ratio) == len(r.county_ratio) == 12
    assert r.years == years[-12:]
    assert r.farm_yields == pytest.approx([farm[y] for y in r.years])
    # Detrended ratios sit around 1.0 by construction — that is what "detrended" means.
    assert 0.95 < float(np.mean(r.farm_ratio)) < 1.05
    assert abs(float(np.corrcoef(r.farm_ratio, r.county_ratio)[0, 1]) - r.rho) < 0.02


def test_too_few_overlapping_years_raises_rather_than_answering():
    years, values = county_history()
    s = series_for(years, values)
    farm = tracking_farm(years, values, years[-(FARM_MIN_YEARS - 1):])
    with pytest.raises(ValueError, match=str(FARM_MIN_YEARS)):
        farm_report(s, farm, plan_type="YP", n_draws=DRAWS)


def test_trend_adjusted_yields_are_not_detrended_a_second_time():
    years, values = county_history()
    s = series_for(years, values)
    farm = tracking_farm(years, values, years[-15:])
    r = farm_report(s, farm, plan_type="YP", farm_detrend="none", n_draws=DRAWS)
    assert r.farm_detrend == "none"
    assert r.farm_trend_pct_per_year == pytest.approx(0.0)


def test_a_farm_steadier_than_its_county_is_flagged_as_a_data_artefact():
    """A single farm cannot be less variable than the average of every farm around it."""
    years, values = county_history(cv=0.25)
    s = series_for(years, values)
    rng = np.random.default_rng(3)
    farm_years = years[-15:]
    farm = {y: float(180.0 * (1 + rng.normal(0, 0.01))) for y in farm_years}
    r = farm_report(s, farm, plan_type="YP", n_draws=DRAWS)
    assert any("steadier" in w or "TREND-ADJUSTED" in w for w in r.warnings)


# =============================================================================
# 6. WIRING — the calculator has to be REACHABLE, not merely importable
# =============================================================================
#
# Parsed rather than imported: importing streamlit_app.py starts the app, and a full
# streamlit.testing.v1.AppTest render pulls in the LRP tab's live market fetch. The wiring is
# a structural fact and AST is the right tool for it; the AppTest render is run by hand
# against a synthetic DB (see the report accompanying this change).

def _app_source() -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text()


def test_the_my_farm_subtab_exists_in_the_row_crop_tab():
    import ast

    src = _app_source()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_tab_row_crop")
    labels = [c.value for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "tabs"
              for a in n.args if isinstance(a, ast.List)
              for c in a.elts if isinstance(c, ast.Constant)]
    assert "My Farm" in labels, f"the My Farm sub-tab is gone; found {labels}"
    # ... and every sub-tab still has a body, so adding one did not orphan another.
    assert len(labels) == len([n for n in ast.walk(fn) if isinstance(n, ast.withitem)])


def test_the_subtab_calls_the_calculator_and_guards_it():
    src = _app_source()
    assert "render_farm_calculator" in src
    assert "def _tab_farm()" in src
    body = src.split("def _tab_farm()", 1)[1].split("\ndef ", 1)[0]
    # A row-crop sub-tab must not be able to take the rest of the app down with it.
    assert body.count("try:") >= 2 and "except Exception" in body


def test_no_cached_function_here_has_an_all_underscore_signature():
    """The trap tests/test_cache_keys.py exists for, asserted at this module's own door.

    st.cache_data drops underscore-prefixed arguments from the hash, so a cache-BUSTER named
    `_db_mtime` is silently ignored and the first result on a warm container is served
    forever. Every buster in this module is bare for that reason.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "rowcroppage.py").read_text()
    found = 0
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef):
            continue
        decs = [d.func if isinstance(d, ast.Call) else d for d in node.decorator_list]
        if not any(isinstance(d, ast.Attribute) and d.attr == "cache_data" for d in decs):
            continue
        found += 1
        args = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
        assert [a for a in args if not a.startswith("_")], f"{node.name}{tuple(args)}"
    assert found >= 4, "the farm calculator's cached readers vanished from the AST walk"


# =============================================================================
# 7. END TO END through the readers, the way the page runs it
# =============================================================================

def test_the_whole_path_from_a_pasted_series_to_a_scored_band(conn):
    years, values = county_history()
    _load_nass(conn, "Corn", "19153", years, values)
    for band, miss in (("ECO95", 0.16), ("ECO90", 0.26), ("SCO86", 0.36)):
        _load_basis_row(conn, "Corn", "19153", band, miss=miss)

    farm_years = years[-12:]
    text = "\n".join(f"{y}: {values[years.index(y)] * 0.9:.1f}" for y in farm_years)
    farm, problems = parse_aph_series(text)
    assert problems == [] and len(farm) == 12

    s = load_county_series(conn, "Corn", "19153")
    r = farm_report(s, farm, plan_type="YP",
                    published=published_basis_risk(conn, "Corn", "19153"),
                    national=typical_miss_by_band(conn), n_draws=DRAWS)
    assert r.county_label == "Polk County, IA"
    assert r.confidence["show_point"] is True
    assert r.outcome["ECO95"].published_miss == pytest.approx(0.16)
    assert r.outcome["ECO95"].farm_miss < r.outcome["ECO95"].published_miss
