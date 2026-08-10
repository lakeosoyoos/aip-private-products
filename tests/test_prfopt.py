"""Tests for src/prfopt.py — PRF interval-allocation optimizer.

Enumeration rules were reverse-engineered from the ground-truth workbooks
(27663_{Blaine,Camas,Lincoln}_grazing.xlsx, 59,536 rows each) and proven by
exact set-equality; these tests pin the rules structurally so they cannot
drift.
"""

import math
import os
import sqlite3
from collections import Counter

import pandas as pd
import pytest

from src.prfopt import (
    INTERVALS,
    INTERVAL_INDEX,
    compare_to_workbook,
    enumerate_combinations,
    enumerate_policies,
    export_workbook,
    interval_year_nets,
    load_workbook,
    rank_by_avg_net_return,
    rank_by_win_rate,
    score_policies,
    simulate,
    simulate_from_source_workbook,
    solve_interval_values,
)


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

def test_interval_list():
    assert len(INTERVALS) == 11
    assert INTERVALS[0] == "JAN-FEB" and INTERVALS[-1] == "NOV-DEC"


def test_combination_counts_by_size():
    combos = enumerate_combinations()
    by_size = Counter(len(c) for c in combos)
    # C(12-k, k) non-adjacent subsets of 11 linear slots
    assert by_size == {2: 45, 3: 84, 4: 70, 5: 21}
    assert len(combos) == 220


def test_no_adjacent_intervals_and_month_order():
    for combo in enumerate_combinations():
        ii = [INTERVAL_INDEX[m] for m in combo]
        assert ii == sorted(ii)
        assert all(b - a >= 2 for a, b in zip(ii, ii[1:]))


def test_policy_count_matches_workbooks():
    pols = enumerate_policies()
    assert len(pols) == 59_536
    by_size = Counter(len(c) for c, _ in pols)
    assert by_size == {2: 225, 3: 7_560, 4: 30_730, 5: 21_021}
    # no duplicates
    assert len(set(pols)) == 59_536


def test_allocation_rules():
    for _, props in enumerate_policies():
        assert sum(props) == 100
        for p in props:
            assert 10 <= p <= 60 and p % 5 == 0


def test_known_pairs_present_and_absent():
    pols = set(enumerate_policies())
    # first row of the ground-truth workbook
    assert (("JAN-FEB", "MAR-APR"), (40, 60)) in pols
    # last row of the ground-truth workbook
    assert (
        ("MAR-APR", "MAY-JUN", "JUL-AUG", "SEP-OCT", "NOV-DEC"),
        (20, 25, 10, 30, 15),
    ) in pols
    # adjacent intervals are excluded
    assert (("JAN-FEB", "FEB-MAR"), (50, 50)) not in pols
    # allocations outside [10, 60] are excluded
    assert (("JAN-FEB", "MAR-APR"), (65, 35)) not in pols
    assert (("JAN-FEB", "MAR-APR", "MAY-JUN"), (80, 10, 10)) not in pols
    # single-interval policies are excluded
    assert not any(len(c) < 2 for c, _ in pols)


# ---------------------------------------------------------------------------
# Simulation math (tiny synthetic fixture)
# ---------------------------------------------------------------------------

@pytest.fixture()
def tiny_inputs():
    # Two intervals, three years, index base 100, coverage 90% -> trigger 90.
    index = {
        "JAN-FEB": {2020: 45.0, 2021: 90.0, 2022: 120.0},
        "MAR-APR": {2020: 100.0, 2021: 67.5, 2022: 80.0},
    }
    rates = {"JAN-FEB": 0.10, "MAR-APR": 0.20}
    subsidy = 0.51
    return index, rates, subsidy


def test_interval_year_nets_formula(tiny_inputs):
    index, rates, subsidy = tiny_inputs
    nets, years = interval_year_nets(
        index, rates, subsidy, coverage_level=0.90, protection=100.0
    )
    assert years == [2020, 2021, 2022]
    # JAN-FEB: net premium = round(0.10*100*0.49, 2) = 4.90
    #   2020: payout (90-45)/90 = 0.5 -> indem 50.00 -> net 45.10
    #   2021: index == trigger -> payout 0 -> net -4.90
    #   2022: index above trigger -> payout 0 -> net -4.90
    assert nets["JAN-FEB"] == [45.10, -4.90, -4.90]
    # MAR-APR: net premium = round(0.20*100*0.49, 2) = 9.80
    #   2020: payout 0 -> -9.80
    #   2021: (90-67.5)/90 = 0.25 -> indem 25.00 -> net 15.20
    #   2022: (90-80)/90 -> indem round(11.1111,2)=11.11 -> net 1.31
    assert nets["MAR-APR"] == [-9.80, 15.20, 1.31]


def test_sentinel_for_missing_rate(tiny_inputs):
    index, rates, subsidy = tiny_inputs
    rates = {"JAN-FEB": rates["JAN-FEB"]}  # MAR-APR not offered
    nets, _ = interval_year_nets(
        index, rates, subsidy, protection=100.0, sentinel_net=-10.0
    )
    assert nets["MAR-APR"] == [-10.0, -10.0, -10.0]
    nets2, _ = interval_year_nets(
        index, rates, subsidy, protection=100.0, sentinel_net=None
    )
    assert "MAR-APR" not in nets2


def test_score_policies(tiny_inputs):
    index, rates, subsidy = tiny_inputs
    nets, _ = interval_year_nets(index, rates, subsidy, protection=100.0)
    policies = [(("JAN-FEB", "MAR-APR"), (40, 60))]
    df = score_policies(policies, nets)
    assert len(df) == 1
    # per-year: .4*45.10+.6*(-9.80)=12.16 ; .4*(-4.90)+.6*15.20=7.16 ;
    #           .4*(-4.90)+.6*1.31=-1.174
    exp_years = [12.16, 7.16, -1.174]
    assert math.isclose(
        df.loc[0, "average_net_return"], sum(exp_years) / 3, abs_tol=1e-12
    )
    assert math.isclose(df.loc[0, "win rate"], 2 / 3, abs_tol=1e-12)
    assert df.loc[0, "combinations"] == "['JAN-FEB', 'MAR-APR']"
    assert df.loc[0, "proportions"] == "[40, 60]"


def test_win_rate_strictly_positive():
    nets = {"JAN-FEB": [0.0, 0.5], "MAR-APR": [0.0, -0.5]}
    df = score_policies([(("JAN-FEB", "MAR-APR"), (50, 50))], nets)
    # year 1 net == 0.0 -> not a win; year 2 net == 0.0 -> not a win
    assert df.loc[0, "win rate"] == 0.0


# ---------------------------------------------------------------------------
# simulate() against an in-memory DB with the documented interface
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_db(tiny_inputs):
    index, rates, subsidy = tiny_inputs
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE prf_grid_index (grid_id TEXT, interval TEXT, "
        "year INTEGER, index_value REAL)"
    )
    conn.execute(
        "CREATE TABLE prf_grid_rate (grid_id TEXT, intended_use TEXT, "
        "interval TEXT, rate REAL)"
    )
    conn.execute(
        "CREATE TABLE prf_subsidy (coverage_level REAL, subsidy REAL)"
    )
    for iv, by_year in index.items():
        for y, v in by_year.items():
            conn.execute("INSERT INTO prf_grid_index VALUES (?,?,?,?)",
                         ("g1", iv, y, v))
    for iv, r in rates.items():
        conn.execute("INSERT INTO prf_grid_rate VALUES (?,?,?,?)",
                     ("g1", "Grazing", iv, r))
    conn.execute("INSERT INTO prf_subsidy VALUES (0.90, 0.51)")
    conn.commit()
    yield conn
    conn.close()


def test_simulate_end_to_end(mem_db):
    policies = [(("JAN-FEB", "MAR-APR"), (40, 60)),
                (("JAN-FEB", "MAR-APR"), (60, 40))]
    df = simulate("g1", "Grazing", mem_db, protection=100.0,
                  policies=policies)
    assert len(df) == 2
    assert df.attrs["years"] == [2020, 2021, 2022]
    assert df.attrs["subsidy"] == 0.51
    row = df[df["proportions"] == "[40, 60]"].iloc[0]
    assert math.isclose(row["average_net_return"],
                        (12.16 + 7.16 - 1.174) / 3, abs_tol=1e-12)


def test_two_step_premium_rounding():
    """MAY-JUN grid 27663 case: single-step round(rate*prot*0.49, 2) gives
    2.03 but the verified two-step chain gives 2.02 (gross 4.13, subsidy
    2.11)."""
    index = {"MAY-JUN": {2020: 200.0}}
    rates = {"MAY-JUN": 0.2252}
    nets, _ = interval_year_nets(index, rates, subsidy=0.51,
                                 coverage_level=0.90, protection=18.36)
    # payout 0 -> net = -net_prem = -(4.13 - 2.11) = -2.02
    assert nets["MAY-JUN"] == [-2.02]
    assert round(0.2252 * 18.36 * 0.49, 2) == 2.03  # the wrong single-step


GROUND_TRUTH_WB = "/Users/rhondacolbert/Downloads/27663_Blaine_grazing (1).xlsx"
SOURCE_WB = "/Users/rhondacolbert/Desktop/27663 Blaine ID GZ.xlsx"


@pytest.mark.skipif(
    not (os.path.exists(GROUND_TRUTH_WB) and os.path.exists(SOURCE_WB)),
    reason="ground-truth workbooks not present on this machine",
)
def test_reproduces_ground_truth_workbook():
    wb = load_workbook(GROUND_TRUTH_WB)
    sim = simulate_from_source_workbook(SOURCE_WB, 0.90)
    res = compare_to_workbook(sim, wb)
    assert res["n"] == 59_536
    assert res["max_abs_err_avg_net_return"] < 1e-9
    # win rate: exact except float-dust ties on mathematically-zero years
    # (documented in the prfopt module docstring)
    assert res["max_abs_err_win_rate"] <= 1 / 19 + 1e-12


# ---------------------------------------------------------------------------
# Ranking and export
# ---------------------------------------------------------------------------

@pytest.fixture()
def scored():
    return pd.DataFrame(
        {
            "combinations": ["['A']", "['B']", "['C']"],
            "proportions": ["[100]"] * 3,
            "average_net_return": [1.0, 3.0, 2.0],
            "win rate": [0.5, 0.2, 0.5],
        }
    )


def test_rank_by_avg_net_return(scored):
    out = rank_by_avg_net_return(scored)
    assert out["average_net_return"].tolist() == [3.0, 2.0, 1.0]
    assert rank_by_avg_net_return(scored, top=1)["combinations"].iloc[0] == "['B']"


def test_rank_by_win_rate(scored):
    out = rank_by_win_rate(scored)
    # ties on win rate broken by average_net_return
    assert out["combinations"].tolist() == ["['C']", "['A']", "['B']"]


def test_export_workbook_format(scored, tmp_path):
    path = str(tmp_path / "out.csv")
    export_workbook(scored, path, 27663, "Blaine", "Grazing", "ID")
    back = pd.read_csv(path)
    assert back.columns.tolist() == [
        "grid_county_use", "combinations", "proportions",
        "average_net_return", "win rate", "state",
    ]
    assert back["grid_county_use"].iloc[0] == "27663_Blaine_grazing"
    assert back["state"].iloc[0] == "ID"
    xlsx = str(tmp_path / "out.xlsx")
    export_workbook(scored, xlsx, 27663, "Blaine", "Grazing", "ID")
    back2 = pd.read_excel(xlsx)
    assert len(back2) == 3


# ---------------------------------------------------------------------------
# Linear solver used for calibration
# ---------------------------------------------------------------------------

def test_solve_interval_values_recovers_truth():
    truth = {iv: (i - 5) * 0.37 for i, iv in enumerate(INTERVALS)}
    pols = enumerate_policies()[:5000]
    rows = []
    for combo, props in pols:
        avg = sum(p / 100.0 * truth[m] for m, p in zip(combo, props))
        rows.append({"_combo": combo, "_props": props,
                     "average_net_return": avg})
    wb = pd.DataFrame(rows)
    solved = solve_interval_values(wb)
    for iv in INTERVALS:
        assert math.isclose(solved[iv], truth[iv], abs_tol=1e-9)


def test_the_five_percent_grid_contains_every_vertex_of_the_feasible_set():
    """Why STEP_PCT stays at 5 even though producers may write any percentage.

    average_net_return is linear in the allocation vector, so its maximum sits at a vertex of
    {sum p = 100, MIN_PCT <= p_i <= cap}. A vertex pins all but one coordinate to a bound, so
    the free coordinate is 100 - (a sum of bounds). If MIN_PCT and every cap are multiples of
    5, that remainder is a multiple of 5 and the 5% grid already contains the optimum — a
    finer search cannot beat it, only cost 168x more.

    This test pins the PRECONDITION. If a future actuarial year introduces a cap that is not a
    multiple of 5 (or MIN_PCT moves), the argument breaks and the step must be revisited.
    """
    from src.prfopt import MIN_PCT, STEP_PCT

    assert MIN_PCT % STEP_PCT == 0
    for cap in (40, 45, 50, 60, 70):          # the RY2026 actuarial caps
        assert cap % STEP_PCT == 0, f"cap {cap} is not a multiple of the {STEP_PCT}% step"
    assert 100 % STEP_PCT == 0


def test_two_percent_is_not_a_usable_step():
    """Not a preference — enumerate_policies asserts the cap divides by the step, and the
    45% cap (Nebraska) is odd. Recorded so the option is not re-proposed."""
    import pytest

    from src.prfopt import enumerate_policies

    with pytest.raises(AssertionError):
        enumerate_policies(step=2, max_pct=45)
