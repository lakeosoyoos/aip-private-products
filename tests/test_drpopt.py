"""Tests for src/drpopt.py — the DRP risk-shape optimizer. No network, no live DB.

The fixture builds a small but STRUCTURALLY REAL DRP database in memory: real ADM column
semantics, a real 5,000-row draw set per quarter, two parallel RY2025-style settlement
series, two milk-yield generations for one sales date, and both a pinned and a free
weighting factor. Every rule the engine has to respect is therefore exercised against
data shaped the way RMA actually ships it, not against mocks.

Two of these tests exist because getting them wrong produces plausible-looking numbers
rather than an error, which is the failure mode that matters here:

    test_protection_factor_collapses_out          — the 84-not-1848 search space
    test_restricted_weighting_factor_is_binding   — declarations that can be filed
"""
from __future__ import annotations

import math
import sqlite3

import numpy as np
import pytest

from src import db, drpopt


# ---------------------------------------------------------------------------
# Fixture: a synthetic-but-structurally-real DRP database
# ---------------------------------------------------------------------------

FMMO = {
    "reinsurance_year": 2026, "fmmo_factor_id": 9,
    "butter_mfg_yield": 1.211, "nfdm_mfg_yield": 0.99, "dry_whey_mfg_yield": 1.03,
    "cheese_mfg_yield_casein": 1.383, "cheese_mfg_yield_butterfat": 1.589,
    "butterfat_retention_rate": 0.91, "butterfat_to_protein_ratio": 1.17,
    "butter_make_allowance": 0.2272, "nfdm_make_allowance": 0.2393,
    "dry_whey_make_allowance": 0.2668, "cheese_make_allowance": 0.2519,
}

STATE = "55"
ABBREV = "WI"

# Eight settled quarters, 2024Q1..2025Q4, so quarter 0 clears MIN_OBS (8 >= 4) and each
# of quarters 1..4 gets exactly 2 observations (below MIN_OBS, so they must NOT appear).
QUARTERS = [(2024, 1), (2024, 2), (2024, 3), (2024, 4),
            (2025, 1), (2025, 2), (2025, 3), (2025, 4)]


def _draw_rows(ry, milk_yield_id, state_code, rng):
    """5,000 uniform draw rows in RMA's own shape (4-decimal uniforms in (0,1))."""
    u = np.round(rng.uniform(0.0001, 0.9999, size=(drpopt.N_DRAWS, 19)), 4)
    return [(ry, milk_yield_id, i + 1, state_code, *[float(x) for x in u[i]])
            for i in range(drpopt.N_DRAWS)]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    _build(c)
    return c


def _build(conn, ry: int = 2026):
    rng = np.random.default_rng(7)

    conn.execute(
        "INSERT INTO drp_state (reinsurance_year, state_code, state_abbrev, state_name,"
        " n_quarters, n_pricing_options) VALUES (?,?,?,?,?,?)",
        (ry, STATE, ABBREV, "Wisconsin", 8, 2))

    conn.execute(
        "INSERT INTO drp_fmmo_factor ({}) VALUES ({})".format(
            ", ".join(FMMO), ", ".join("?" * len(FMMO))), tuple(FMMO.values()))

    # RY2019 filed six coverage levels; RY2020+ filed four. Both are present so the
    # per-year read is exercised.
    for cov, pct in ((0.70, 0.59), (0.75, 0.55), (0.80, 0.55), (0.85, 0.49),
                     (0.90, 0.44), (0.95, 0.44)):
        conn.execute("INSERT INTO drp_subsidy (reinsurance_year, coverage_level,"
                     " subsidy_pct) VALUES (?,?,?)", (2019, cov, pct))
    for cov, pct in ((0.80, 0.55), (0.85, 0.49), (0.90, 0.44), (0.95, 0.44)):
        conn.execute("INSERT INTO drp_subsidy (reinsurance_year, coverage_level,"
                     " subsidy_pct) VALUES (?,?,?)", (ry, cov, pct))

    draw_cols = ("reinsurance_year, milk_yield_id, draw_number, state_code, "
                 + ", ".join(drpopt.DRAW_COLS))
    n_draw_cols = 4 + len(drpopt.DRAW_COLS)

    offer_id = 1000
    daily_id = 1
    actual_id = 1
    yield_id = 1
    # One draw set per quarter NUMBER, exactly as RMA publishes (five consecutive
    # quarters => every number covered). These ids belong to the newest RY.
    draw_yield_ids = {}
    for q in (1, 2, 3, 4):
        yield_id += 1
        draw_yield_ids[q] = yield_id
        conn.execute(
            "INSERT INTO drp_milk_yield (reinsurance_year, milk_yield_id, state_code,"
            " state_abbrev, expected_yield, expected_yield_sd) VALUES (?,?,?,?,?,?)",
            (ry, yield_id, STATE, ABBREV, 6400.0, 60.0))
        conn.executemany(
            f"INSERT INTO drp_draw ({draw_cols}) VALUES ({','.join('?' * n_draw_cols)})",
            _draw_rows(ry, yield_id, STATE, rng))
        # A daily row pointing at it, so draw_sets() can resolve id -> quarter.
        offer_id += 1
        conn.execute(
            "INSERT INTO drp_offer (reinsurance_year, offer_id, state_code, state_abbrev,"
            " county_code, type_code, pricing_option, practice_code, quarter_year,"
            " quarter, plan_code) VALUES (?,?,?,?,'998','831','Class',?,?,?,'83')",
            (ry, offer_id, STATE, ABBREV, str(800 + q), ry + 1, q))
        daily_id += 1
        conn.execute(
            "INSERT INTO drp_daily_price (reinsurance_year, sales_date, offer_id,"
            " daily_price_id, loading_factor, milk_yield_id) VALUES (?,?,?,?,?,?)",
            (ry, "2026-04-23", offer_id, daily_id, 1.0638, yield_id))

    # The settled observations. Each quarter gets a Class and a Component offer, quoted
    # on TWO sales dates so --lead last / first has something to choose between.
    for i, (qy, q) in enumerate(QUARTERS):
        actual_id += 1
        this_actual = actual_id
        conn.execute(
            "INSERT INTO drp_actual_price (reinsurance_year, actual_price_id,"
            " actual_class3, actual_class4, actual_butterfat, actual_protein,"
            " actual_other_solids, actual_nonfat_solids, settled)"
            " VALUES (?,?,?,?,?,?,?,?,1)",
            (ry, this_actual, 17.0 + 0.5 * (i % 4) - (2.0 if i in (2, 5) else 0.0),
             18.0 + 0.4 * (i % 3), 2.90, 2.05, 0.21, 1.10))
        # A SECOND, parallel settlement series for the same quarter under a different
        # FMMO regime -- the RY2025 ids 49-56 / 57-62 trap. Nothing may reach it, because
        # no daily row points at it.
        actual_id += 1
        conn.execute(
            "INSERT INTO drp_actual_price (reinsurance_year, actual_price_id,"
            " actual_class3, actual_class4, actual_butterfat, actual_protein,"
            " actual_other_solids, actual_nonfat_solids, settled)"
            " VALUES (?,?,?,?,?,?,?,?,1)",
            (ry, actual_id, 99.0, 99.0, 9.9, 9.9, 9.9, 9.9))

        # Two milk-yield generations for this quarter: NASS restates. The daily rows
        # point at the OLDER one; the newer carries a wildly different expectation so a
        # "latest row for the state" join would be unmistakable.
        yield_id += 1
        as_of_yield = yield_id
        conn.execute(
            "INSERT INTO drp_milk_yield (reinsurance_year, milk_yield_id, state_code,"
            " state_abbrev, expected_yield, actual_yield, expected_yield_sd)"
            " VALUES (?,?,?,?,?,?,?)",
            (ry, as_of_yield, STATE, ABBREV, 6400.0, 6350.0, 60.0))
        yield_id += 1
        conn.execute(
            "INSERT INTO drp_milk_yield (reinsurance_year, milk_yield_id, state_code,"
            " state_abbrev, expected_yield, actual_yield, expected_yield_sd)"
            " VALUES (?,?,?,?,?,?,?)",
            (ry, yield_id, STATE, ABBREV, 9999.0, 9999.0, 60.0))

        for option, type_code in (("Class", "831"), ("Component", "832")):
            offer_id += 1
            conn.execute(
                "INSERT INTO drp_offer (reinsurance_year, offer_id, state_code,"
                " state_abbrev, county_code, type_code, pricing_option, practice_code,"
                " quarter_year, quarter, plan_code) VALUES (?,?,?,?,'998',?,?,?,?,?,'83')",
                (ry, offer_id, STATE, ABBREV, type_code, option, str(800 + q), qy, q))
            for sales_date, tag in (("2023-01-10", "first"), ("2023-06-20", "last")):
                daily_id += 1
                _insert_daily(conn, ry, sales_date, offer_id, daily_id, option,
                              as_of_yield, this_actual, i, tag)
    conn.commit()


def _insert_daily(conn, ry, sales_date, offer_id, daily_id, option, yield_id,
                  actual_id, i, tag):
    """One drp_daily_price row. The 'last' sales date carries the tighter sigmas."""
    sigma = 0.09 if tag == "last" else 0.20
    base3, base4 = 17.5 + 0.3 * (i % 5), 18.2 + 0.2 * (i % 4)
    common = dict(reinsurance_year=ry, sales_date=sales_date, offer_id=offer_id,
                  daily_price_id=daily_id, loading_factor=1.0638,
                  milk_yield_id=yield_id, actual_price_id=actual_id, fmmo_factor_id=9)
    if option == "Class":
        vals = {**common,
                "m1_class3": base3, "m2_class3": base3, "m3_class3": base3,
                "m1_class4": base4, "m2_class4": base4, "m3_class4": base4,
                "m1_class3_sigma": sigma, "m2_class3_sigma": sigma,
                "m3_class3_sigma": sigma, "m1_class4_sigma": sigma,
                "m2_class4_sigma": sigma, "m3_class4_sigma": sigma,
                "expected_class3": base3, "expected_class4": base4}
    else:
        b, ch, wy, nd = 2.66, 1.86, 0.47, 1.31
        bf, prot, os_, nfs = drpopt.fmmo_components(b, ch, wy, nd, FMMO)
        vals = {**common,
                "m1_butter": b, "m2_butter": b, "m3_butter": b,
                "m1_cheese": ch, "m2_cheese": ch, "m3_cheese": ch,
                "m1_dry_whey": wy, "m2_dry_whey": wy, "m3_dry_whey": wy,
                "m1_nfdm": nd, "m2_nfdm": nd, "m3_nfdm": nd,
                "m1_butter_sigma": sigma, "m2_butter_sigma": sigma,
                "m3_butter_sigma": sigma, "m1_cheese_sigma": sigma,
                "m2_cheese_sigma": sigma, "m3_cheese_sigma": sigma,
                "m1_dry_whey_sigma": sigma, "m2_dry_whey_sigma": sigma,
                "m3_dry_whey_sigma": sigma, "m1_nfdm_sigma": sigma,
                "m2_nfdm_sigma": sigma, "m3_nfdm_sigma": sigma,
                "expected_butterfat": bf, "expected_protein": prot,
                "expected_other_solids": os_, "expected_nonfat_solids": nfs}
        # Quarters 2 and 5 are RESTRICTED: only the protein + other-solids side is
        # published, so the declared weighting factor is pinned to 1.0.
        if i in (2, 5):
            vals["component_weight_restricted"] = 1.0
            vals["expected_nonfat_solids"] = None
    cols = ", ".join(vals)
    conn.execute(f"INSERT INTO drp_daily_price ({cols}) "
                 f"VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))


def _one_obs(conn, option="Class", quarter_year=2024, quarter=1, lead="last"):
    for o in drpopt.observations(conn, STATE, option, lead=lead):
        if o["quarter_year"] == quarter_year and o["quarter"] == quarter:
            return o
    raise AssertionError("observation not found")


def _score(conn, obs, covs=(0.80, 0.90, 0.95)):
    draws = drpopt.draw_sets(conn, STATE)[obs["quarter"]][1]
    subs = {c: {0.80: 0.55, 0.85: 0.49, 0.90: 0.44, 0.95: 0.44}[c] for c in covs}
    return drpopt.score_observation(obs, draws, dict(FMMO), subs)


# ---------------------------------------------------------------------------
# The two properties that must never regress
# ---------------------------------------------------------------------------

def test_protection_factor_collapses_out(conn):
    """PF (and share, and declared production) scale cost and payout IDENTICALLY.

    P18-1 puts ProtectionFactor in TotalPremiumAmount and in Liability; P28-1 puts it in
    the indemnity. It is therefore a pure sizing dial: it can change how many dollars are
    at stake and it CANNOT change a win rate or a return per dollar. That is why the
    search space is 84 risk shapes per pricing option and not 924 declarations.
    """
    cell = _score(conn, _one_obs(conn))["cells"][(0.90, 0.50)]
    base = drpopt.dollars(cell, 1_000_000)

    for pf in (1.00, 1.05, 1.25, 1.50):
        for share in (1.0, 0.6):
            for prod in (100_000, 1_000_000, 43_500_000):
                d = drpopt.dollars(cell, prod, share, pf)
                size = prod / 100.0 * share * pf
                # every DOLLAR figure scales exactly
                for k in ("liability", "premium", "producer", "indemnity", "net"):
                    assert d[k] == pytest.approx(cell[k] * size, rel=1e-12)
                # and every RATIO is untouched
                assert d["net_per_1"] == pytest.approx(base["net_per_1"], rel=1e-12)
                assert d["prem_per_1"] == pytest.approx(base["prem_per_1"], rel=1e-12)
                # sign of the net -- i.e. whether this quarter was a WIN -- is invariant
                assert (d["net"] > 0) == (base["net"] > 0)

    # And the whole scored surface is invariant, not just one cell: PF cancels in
    # net/liability by construction, so a re-scored sweep at any PF gives the same
    # win rate and the same best_net.
    surface = _score(conn, _one_obs(conn))["cells"]
    for (cov, w), c in surface.items():
        assert drpopt.dollars(c, 5_000_000, 0.85, 1.35)["net_per_1"] == \
            pytest.approx(c["net_per_1"], rel=1e-12)


def test_restricted_weighting_factor_is_binding(conn):
    """When RMA pins the weighting factor, no shape may declare anything else.

    drp_daily_price.component_weight_restricted = 1.0 means only the protein +
    other-solids side is published for that quarter, so the ONLY filable declaration
    carries weighting factor 1.0. Every risk shape must therefore be scored at 1.0 for
    that quarter -- a shape that "declares" 0.35 there is a policy that cannot be sold.
    """
    pinned = _one_obs(conn, "Component", 2024, 3)   # i == 2 -> restricted
    assert pinned["component_weight_restricted"] == 1.0
    res = _score(conn, pinned)
    assert res["pin"] == 1.0
    assert res["pin_reason"] == "component_weight_restricted"

    # Every shape's DECLARED weight is the pin ...
    assert {c["eff"] for c in res["cells"].values()} == {1.0}
    # ... so at a given coverage all 21 shapes are literally the same policy.
    at_90 = [res["cells"][(0.90, w)] for w in drpopt.WEIGHTING_FACTORS]
    assert len(at_90) == 21
    assert len({round(c["net_per_1"], 12) for c in at_90}) == 1

    # A FREE quarter must not be flattened: there the shapes genuinely differ.
    free = _one_obs(conn, "Component", 2024, 1)
    assert free["component_weight_restricted"] is None
    fres = _score(conn, free)
    assert fres["pin"] is None
    assert {c["eff"] for c in fres["cells"].values()} == set(drpopt.WEIGHTING_FACTORS)
    assert len({round(fres["cells"][(0.90, w)]["net_per_1"], 12)
                for w in drpopt.WEIGHTING_FACTORS}) > 1

    # And the pin survives into the stored row: n_pinned counts it, and the reported
    # best weight is one a producer could actually have filed.
    rows = drpopt.compute_state_rows(conn, STATE, min_obs=4)
    comp = [r for r in rows if r["pricing_option"] == "Component" and r["quarter"] == 0]
    assert comp and all(r["n_pinned"] == 2 for r in comp)
    # All 21 shapes are still SCORED (the pin collapses their values, it must not delete
    # 20 of them and leave the row looking like a one-point search on the wrong basis).
    assert all(r["n_shapes"] == 21 for r in comp)


def test_a_fully_pinned_cell_reports_the_pin_not_the_tie_break_floor(conn):
    """When every quarter is pinned, all 21 shapes tie — and only one is filable.

    A plain "lowest weight wins" tie-break would publish weighting factor 0.00 for a
    state where RMA allowed nothing but 1.00, i.e. a recommendation that cannot be
    bought. The tie-break therefore prefers the shape whose own weight was the one
    actually declared.
    """
    conn.execute("""UPDATE drp_daily_price SET component_weight_restricted = 1.0,
                       expected_nonfat_solids = NULL
                     WHERE offer_id IN (SELECT offer_id FROM drp_offer
                                         WHERE pricing_option = 'Component')""")
    conn.commit()
    rows = [r for r in drpopt.compute_state_rows(conn, STATE, min_obs=4)
            if r["pricing_option"] == "Component"]
    assert rows
    for r in rows:
        assert r["n_pinned"] == r["n_obs"] == len(QUARTERS)
        assert r["best_net_weight"] == 1.0
        assert r["best_win_weight"] == 1.0
        assert r["n_shapes"] == 21
        # every shape is the same policy, so the leaderboard is degenerate on purpose
        assert r["best_net"] == pytest.approx(r["median_net"])


# ---------------------------------------------------------------------------
# admissible_weight -- every branch of the constraint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,option,expected", [
    ({"class_weight_restricted": 1.0, "expected_class3": 17.0,
      "expected_class4": 18.0}, "Class", 1.0),
    ({"class_weight_restricted": 0.0, "expected_class3": 17.0,
      "expected_class4": 18.0}, "Class", 0.0),
    ({"class_weight_restricted": None, "expected_class3": 17.0,
      "expected_class4": 18.0}, "Class", None),
    # No published column, but only one leg has a price: still not free.
    ({"class_weight_restricted": None, "expected_class3": 17.0,
      "expected_class4": None}, "Class", 1.0),
    ({"class_weight_restricted": None, "expected_class3": None,
      "expected_class4": 18.0}, "Class", 0.0),
    ({"component_weight_restricted": 1.0, "expected_protein": 2.0,
      "expected_other_solids": 0.2, "expected_nonfat_solids": 1.1}, "Component", 1.0),
    ({"component_weight_restricted": 0.0, "expected_protein": 2.0,
      "expected_other_solids": 0.2, "expected_nonfat_solids": 1.1}, "Component", 0.0),
    ({"component_weight_restricted": None, "expected_protein": 2.0,
      "expected_other_solids": 0.2, "expected_nonfat_solids": 1.1}, "Component", None),
    # RY2019/RY2020: no nonfat-solids price published at all, and no restriction flag.
    ({"component_weight_restricted": None, "expected_protein": 2.0,
      "expected_other_solids": 0.2, "expected_nonfat_solids": None}, "Component", 1.0),
    ({"component_weight_restricted": None, "expected_protein": None,
      "expected_other_solids": None, "expected_nonfat_solids": 1.1}, "Component", 0.0),
])
def test_admissible_weight_branches(row, option, expected):
    pin, reason = drpopt.admissible_weight(row, option)
    assert pin == expected
    assert bool(reason) == (pin is not None)


def test_effective_weight_substitutes_the_pin():
    assert drpopt.effective_weight(0.35, None) == 0.35
    assert drpopt.effective_weight(0.35, 1.0) == 1.0
    assert drpopt.effective_weight(0.35, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Pricing math
# ---------------------------------------------------------------------------

def test_class_weight_orientation_matches_rmas_restriction_encoding():
    """weight 1.0 is Class III -- the same orientation as class_weight_restricted."""
    assert drpopt.class_milk_price(1.0, 17.0, 20.0) == 17.0
    assert drpopt.class_milk_price(0.0, 17.0, 20.0) == 20.0
    assert drpopt.class_milk_price(0.5, 17.0, 20.0) == 18.5


def test_component_price_weights_solids_but_never_butterfat():
    """Butterfat sits in BOTH of 26-DRP's brackets, so it is algebraically unweighted."""
    bf, prot, os_, nfs = 2.9226, 2.0825, 0.2084, 1.0617
    at1 = drpopt.component_milk_price(1.0, bf, prot, os_, nfs, 4.20, 3.25, os_test=5.8)
    at0 = drpopt.component_milk_price(0.0, bf, prot, os_, nfs, 4.20, 3.25, os_test=5.8)
    assert at1 == pytest.approx(bf * 4.20 + prot * 3.25 + os_ * 5.8)
    assert at0 == pytest.approx(bf * 4.20 + nfs * (3.25 + 5.8))
    # linear in the weight, which is what makes the 21-point sweep meaningful
    assert drpopt.component_milk_price(
        0.5, bf, prot, os_, nfs, 4.20, 3.25, os_test=5.8) == pytest.approx((at1 + at0) / 2)
    # a plausible $/cwt milk price, not an order-of-magnitude error
    assert 15.0 < at1 < 30.0 and 15.0 < at0 < 30.0


def test_other_solids_test_is_read_per_reinsurance_year():
    """RMA changed the fixed other solids test from 5.7 to 5.8 for RY2026.

    19-DRP sec.1, 25-DRP sec.1 and FCIC-20400U (2025) sec.23 all read "fixed at 5.7
    pounds"; 26-DRP sec.1 and FCIC-20400U (04-2025), "2026 and Succeeding Crop Years",
    read "fixed at 5.8 pounds". The engine backtests RY2019..RY2026, so one constant for
    the whole span is wrong at one end or the other.
    """
    for ry in (2019, 2020, 2021, 2022, 2023, 2024, 2025):
        assert drpopt.other_solids_test(ry) == 5.7
    for ry in (2026, 2027):
        assert drpopt.other_solids_test(ry) == 5.8


def test_component_milk_price_requires_an_explicit_other_solids_test():
    """os_test is keyword-only with no default: a silent default caused a real bug."""
    with pytest.raises(TypeError):
        drpopt.component_milk_price(0.5, 2.9, 2.1, 0.21, 1.06, 4.20, 3.25)


# RMA's own worked examples, reproduced to the published dollar. Each is
# (label, other-solids test, weight, prices, tests, published revenue) where the revenue
# is [(P_B x Q_B + P_P x Q_P + P_OS x Q_OS) W + (P_B x Q_B + P_N x (Q_P + Q_OS))(1-W)]
# x Q / 100 with Q = 1,000,000 lb, times the yield adjustment factor where one applies.
RMA_WORKED_EXAMPLES = [
    # 26-DRP sec.3 Example 2 (Released May 2025), component pricing option.
    ("26-DRP ex.2 expected", 5.8, 0.5, (2.70, 1.90, 0.15, 0.85), (4.00, 3.20), 1.00, 181_000),
    ("26-DRP ex.2 actual", 5.8, 0.5, (2.25, 1.70, 0.12, 0.75), (4.00, 3.20), 1.02, 157_519),
    # FCIC-20400U (04-2025) sec.24.H, "2026 and Succeeding Crop Years".
    ("HB2026 24.H expected", 5.8, 0.5, (2.65, 2.75, 0.25, 1.15), (4.80, 4.00), 1.00, 245_800),
    ("HB2026 24.H actual", 5.8, 0.5, (2.25, 1.70, 0.12, 0.75), (4.80, 4.00), 1.02, 185_875),
    # FCIC-20400U (2025) -- the 5.7 regime, which is what makes the change visible.
    ("HB2025 expected", 5.7, 0.5, (2.70, 1.90, 0.15, 0.85), (3.85, 3.15), 1.00, 175_763),
    ("HB2025 actual", 5.7, 0.5, (2.25, 1.70, 0.12, 0.75), (3.85, 3.15), 1.02, 153_008),
]


@pytest.mark.parametrize("label,os_test,w,prices,tests,yield_adj,published",
                         RMA_WORKED_EXAMPLES,
                         ids=[e[0] for e in RMA_WORKED_EXAMPLES])
def test_component_milk_price_reproduces_rmas_worked_examples(
        label, os_test, w, prices, tests, yield_adj, published):
    """The formula is quoted, not inferred -- these are RMA's own published numbers.

    Each example is reproduced EXACTLY, which is what settles both the shape of the
    formula and the value of the other solids test in each regime.
    """
    butterfat, protein, other_solids, nonfat = prices
    butterfat_test, protein_test = tests
    price = drpopt.component_milk_price(
        w, butterfat, protein, other_solids, nonfat,
        butterfat_test, protein_test, os_test=os_test)
    assert price * 1_000_000 * yield_adj / 100 == pytest.approx(published, abs=0.5)


def test_the_worked_examples_would_fail_under_the_wrong_other_solids_test():
    """Guard the guard: swapping 5.7 for 5.8 must actually break the examples.

    Without this, a formula that ignored os_test entirely would still pass the
    parametrized check on whichever regime happened to match.
    """
    for label, os_test, w, prices, tests, yield_adj, published in RMA_WORKED_EXAMPLES:
        wrong = 5.7 if os_test == 5.8 else 5.8
        price = drpopt.component_milk_price(
            w, *prices, *tests, os_test=wrong)
        assert price * 1_000_000 * yield_adj / 100 != pytest.approx(published, abs=0.5)


def test_fmmo_protein_needs_the_butterfat_retention_rate():
    """The RY2026 component row that pinned this formula down.

    Butter/cheese/whey/NFDM from a real 2025-08-15 WI row; RMA's own published
    expected_butterfat / _protein / _other_solids on that row were 2.9226 / 2.0825 /
    0.2084. Dropping butterfat_retention_rate from the protein formula moves protein by
    ~0.31, so this is a real check and not a tautology.
    """
    b = (2.655 + 2.66 + 2.6067) / 3
    ch = (1.874 + 1.86 + 1.828) / 3
    wy = (0.4675 + 0.4725 + 0.4675) / 3
    nd = (1.3105 + 1.3145 + 1.3102) / 3
    bf, prot, os_, nfs = drpopt.fmmo_components(b, ch, wy, nd, FMMO)
    assert round(bf, 4) == pytest.approx(2.9226, abs=1e-4)
    assert round(prot, 4) == pytest.approx(2.0825, abs=1e-4)
    assert round(os_, 4) == pytest.approx(0.2084, abs=1e-4)
    assert nfs == pytest.approx((nd - 0.2393) * 0.99, rel=1e-12)

    no_retention = dict(FMMO, butterfat_retention_rate=1.0)
    _, wrong, _, _ = drpopt.fmmo_components(b, ch, wy, nd, no_retention)
    assert abs(wrong - prot) > 0.25


def test_fmmo_components_are_elementwise_over_arrays():
    """The same function has to serve the expected price and all 5,000 sim paths."""
    b = np.array([2.60, 2.66, 2.72])
    ch = np.array([1.84, 1.86, 1.88])
    wy = np.array([0.46, 0.47, 0.48])
    nd = np.array([1.30, 1.31, 1.32])
    scalar = [drpopt.fmmo_components(float(b[i]), float(ch[i]), float(wy[i]),
                                     float(nd[i]), FMMO) for i in range(3)]
    vector = drpopt.fmmo_components(b, ch, wy, nd, FMMO)
    for i in range(3):
        for j in range(4):
            assert vector[j][i] == pytest.approx(scalar[i][j])


def test_simulated_quarter_price_is_the_mean_of_three_lognormal_months():
    z = np.zeros((4, 3))
    got = drpopt.simulate_quarter_price([18.0, 19.0, 20.0], [0.2, 0.2, 0.2], z)
    # z = 0 -> the median path, E x exp(-sigma^2/2), averaged over the three months
    want = np.mean([18.0, 19.0, 20.0]) * math.exp(-0.02)
    assert got[0] == pytest.approx(want)
    # mean-preserving: over many draws the simulated mean returns the expected price
    rng = np.random.default_rng(1)
    z = rng.standard_normal((200_000, 3))
    big = drpopt.simulate_quarter_price([18.0, 18.0, 18.0], [0.2, 0.2, 0.2], z)
    assert big.mean() == pytest.approx(18.0, rel=5e-3)


def test_normal_from_uniform_matches_the_standard_normal_quantiles():
    got = drpopt.normal_from_uniform([0.5, 0.975, 0.025])
    assert got[0] == pytest.approx(0.0, abs=1e-12)
    assert got[1] == pytest.approx(1.959963984540054, rel=1e-12)
    assert got[2] == pytest.approx(-1.959963984540054, rel=1e-12)
    # a degenerate draw must not become an infinity
    assert np.isfinite(drpopt.normal_from_uniform([0.0, 1.0])).all()


def test_zero_weight_never_multiplies_a_missing_leg_into_nan():
    """0 * NaN is NaN. RY2019/RY2020 component rows have no NFDM strip at all."""
    price = drpopt._component_mix(1.0, 2.92, 2.08, 0.21, None, 4.20, 3.25, 5.8)
    assert price is not None and math.isfinite(price)
    assert drpopt._component_mix(0.95, 2.92, 2.08, 0.21, None, 4.20, 3.25, 5.8) is None
    assert drpopt._component_mix(0.0, 2.92, None, None, 1.10, 4.20, 3.25, 5.8) is not None


# ---------------------------------------------------------------------------
# Observation assembly -- the three joins RMA punishes
# ---------------------------------------------------------------------------

def test_observation_is_one_per_quarter_at_the_chosen_sales_date(conn):
    last = drpopt.observations(conn, STATE, "Class", lead="last")
    first = drpopt.observations(conn, STATE, "Class", lead="first")
    assert len(last) == len(QUARTERS) == len(first)
    assert {o["sales_date"] for o in last} == {"2023-06-20"}
    assert {o["sales_date"] for o in first} == {"2023-01-10"}
    assert [(o["quarter_year"], o["quarter"]) for o in last] == QUARTERS

    with pytest.raises(ValueError):
        drpopt.observations(conn, STATE, "Class", lead="middle")


def test_milk_yield_is_taken_as_of_the_sales_date(conn):
    """NASS restates; each daily row points at the generation current on its day."""
    for o in drpopt.observations(conn, STATE):
        assert o["expected_yield"] == 6400.0     # the as-of generation
        assert o["actual_yield"] == 6350.0
        assert o["expected_yield"] != 9999.0     # the later restatement


def test_actual_prices_are_reached_through_actual_price_id_not_quarter(conn):
    """One calendar quarter can carry two parallel settlement series in one RY."""
    doubles = conn.execute(
        "SELECT COUNT(*) FROM drp_actual_price WHERE actual_class3 = 99.0").fetchone()[0]
    assert doubles == len(QUARTERS), "fixture must contain the decoy series"
    for o in drpopt.observations(conn, STATE):
        assert o["actual_class3"] != 99.0
        assert o["actual_butterfat"] != 9.9


def test_unsettled_quarters_are_never_scored(conn):
    conn.execute("UPDATE drp_actual_price SET settled = 0 WHERE actual_price_id = 2")
    conn.commit()
    got = {(o["quarter_year"], o["quarter"]) for o in drpopt.observations(conn, STATE)}
    assert (2024, 1) not in got
    assert len(got) == len(QUARTERS) - 1


# ---------------------------------------------------------------------------
# Draw sets
# ---------------------------------------------------------------------------

def test_draw_sets_cover_every_quarter_number_with_full_5000_paths(conn):
    sets = drpopt.draw_sets(conn, STATE)
    assert set(sets) == {1, 2, 3, 4}
    for ry, arr in sets.values():
        assert ry == 2026
        assert arr.shape == (drpopt.N_DRAWS, len(drpopt.DRAW_COLS))
        assert arr.min() > 0.0 and arr.max() < 1.0


def test_partial_draw_set_is_refused_not_padded(conn):
    conn.execute("DELETE FROM drp_draw WHERE milk_yield_id = 2 AND draw_number > 4000")
    conn.commit()
    sets = drpopt.draw_sets(conn, STATE)
    assert 1 not in sets, "a 4,000-path set is not a 5,000-iteration simulation"


def test_empty_draw_table_raises_drpskip(conn):
    conn.execute("DELETE FROM drp_draw")
    conn.commit()
    with pytest.raises(drpopt.DrpSkip):
        drpopt.draw_sets(conn, STATE)


# ---------------------------------------------------------------------------
# Scoring / premium
# ---------------------------------------------------------------------------

def test_scored_cell_is_p18_1_arithmetic(conn):
    """liability, premium, subsidy, indemnity and net all line up by hand."""
    obs = _one_obs(conn)
    cell = _score(conn, obs)["cells"][(0.90, 1.0)]
    emp = obs["expected_class3"]
    assert cell["emp"] == pytest.approx(emp)
    assert cell["liability"] == pytest.approx(emp * 0.90)
    # producer premium = total x (1 - subsidy); RY2026 subsidy at 90% is 0.44
    assert cell["producer"] == pytest.approx(cell["premium"] * 0.56)
    assert cell["premium"] >= drpopt.MIN_LOSS_PER_CWT * obs["loading_factor"]
    indem = max(0.0, cell["liability"]
                - obs["actual_class3"] * obs["actual_yield"] / obs["expected_yield"])
    assert cell["indemnity"] == pytest.approx(indem)
    assert cell["net"] == pytest.approx(cell["indemnity"] - cell["producer"])
    assert cell["net_per_1"] == pytest.approx(cell["net"] / cell["liability"])


def test_premium_floor_is_two_cents_per_hundredweight(conn):
    """P18-1: SimulatedLossAverage = MAX(mean loss, 0.02 x DCMP/100)."""
    obs = _one_obs(conn)
    # 80% coverage on a tight-sigma quarter: the simulated loss is essentially zero,
    # so the floor is what is left.
    cell = _score(conn, obs)["cells"][(0.80, 1.0)]
    assert cell["premium"] == pytest.approx(
        drpopt.MIN_LOSS_PER_CWT * obs["loading_factor"])


def test_higher_coverage_costs_more(conn):
    cells = _score(conn, _one_obs(conn))["cells"]
    prem = [cells[(c, 1.0)]["premium"] for c in (0.80, 0.90, 0.95)]
    assert prem[0] <= prem[1] <= prem[2]
    liab = [cells[(c, 1.0)]["liability"] for c in (0.80, 0.90, 0.95)]
    assert liab[0] < liab[1] < liab[2]


def test_a_quarter_with_no_expected_yield_is_skipped_not_guessed(conn):
    obs = dict(_one_obs(conn))
    obs["expected_yield"] = None
    draws = drpopt.draw_sets(conn, STATE)[1][1]
    with pytest.raises(drpopt.DrpSkip):
        drpopt.score_observation(obs, draws, dict(FMMO), {0.90: 0.44})


# ---------------------------------------------------------------------------
# State rollup + persistence
# ---------------------------------------------------------------------------

def test_compute_state_rows_shape(conn):
    rows = drpopt.compute_state_rows(conn, STATE, min_obs=4)
    keys = {(r["pricing_option"], r["quarter"], r["coverage_level"]) for r in rows}
    # 8 settled quarters pooled clears min_obs; each individual quarter has only 2, so
    # quarters 1..4 must be absent rather than published off two outcomes.
    assert {k[1] for k in keys} == {drpopt.ALL_QUARTERS}
    assert {k[0] for k in keys} == {"Class", "Component"}
    assert {k[2] for k in keys} == {0.80, 0.85, 0.90, 0.95}, \
        "0.70/0.75 were only filed in RY2019 and have no observations here"
    for r in rows:
        assert r["n_obs"] == len(QUARTERS)
        assert r["n_shapes"] == 21
        assert r["quarter_min"] == "2024Q1" and r["quarter_max"] == "2025Q4"
        assert 0.0 <= r["best_win_rate"] <= 1.0
        assert r["best_net"] >= r["median_net"]
        assert r["best_win_rate"] >= r["best_net_win_rate"]
        assert r["best_net"] >= r["best_win_net"]
        assert r["premium_draw_ry"] == 2026
        assert r["best_net_weight"] in drpopt.WEIGHTING_FACTORS


def test_min_obs_gate_can_be_lowered_to_expose_per_quarter_rows(conn):
    rows = drpopt.compute_state_rows(conn, STATE, min_obs=2)
    assert {r["quarter"] for r in rows} == {0, 1, 2, 3, 4}
    per_q = [r for r in rows if r["quarter"] == 3]
    assert per_q and all(r["n_obs"] == 2 for r in per_q)


def test_coverage_levels_are_read_per_year_not_hardcoded(conn):
    table = drpopt.subsidy_table(conn)
    assert set(table[2019]) == {0.70, 0.75, 0.80, 0.85, 0.90, 0.95}
    assert set(table[2026]) == {0.80, 0.85, 0.90, 0.95}
    assert table[2019][0.70] == 0.59 and table[2026][0.95] == 0.44


def test_upsert_is_idempotent(conn):
    rows = drpopt.compute_state_rows(conn, STATE, min_obs=4)
    for _ in range(3):
        drpopt.upsert_best(conn, rows, source="test")
    n = conn.execute("SELECT COUNT(*) FROM drp_opt_best").fetchone()[0]
    assert n == len(rows)
    stored = conn.execute(
        "SELECT best_net, source FROM drp_opt_best WHERE pricing_option='Class' "
        "AND quarter=0 AND coverage_level=0.9").fetchone()
    assert stored["source"] == "test"
    assert stored["best_net"] == pytest.approx(
        next(r["best_net"] for r in rows if r["pricing_option"] == "Class"
             and r["quarter"] == 0 and r["coverage_level"] == 0.90))


def test_sweep_writes_and_resumes(conn):
    res = drpopt.sweep(conn, state=ABBREV, log=lambda *_: None)
    assert res["rows"] > 0 and res["resumed"] == 0
    again = drpopt.sweep(conn, state=ABBREV, log=lambda *_: None)
    assert again["rows"] == 0 and again["resumed"] == 1
    forced = drpopt.sweep(conn, state=ABBREV, force=True, log=lambda *_: None)
    assert forced["rows"] == res["rows"]


def test_sweep_records_a_skip_instead_of_aborting(conn):
    conn.execute("DELETE FROM drp_actual_price")
    conn.commit()
    res = drpopt.sweep(conn, state=ABBREV, log=lambda *_: None)
    assert res["rows"] == 0
    assert set(res["skipped"]) == {STATE}


def test_state_roster_accepts_abbrev_or_fips(conn):
    assert drpopt.state_roster(conn, "WI") == [(STATE, ABBREV, "Wisconsin")]
    assert drpopt.state_roster(conn, "55") == [(STATE, ABBREV, "Wisconsin")]
    with pytest.raises(drpopt.DrpSkip):
        drpopt.state_roster(conn, "ZZ")


def test_no_drp_rate_table_exists(conn):
    """Premium is simulated, never looked up -- there is no rate table to add."""
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "drp_opt_best" in have
    assert "drp_rate" not in have


def test_search_space_is_84_shapes_per_pricing_option():
    """4 coverage levels x 21 weighting factors -- the protection factor is NOT in it."""
    assert len(drpopt.WEIGHTING_FACTORS) == 21
    assert drpopt.WEIGHTING_FACTORS[0] == 0.0 and drpopt.WEIGHTING_FACTORS[-1] == 1.0
    assert 4 * len(drpopt.WEIGHTING_FACTORS) == 84
