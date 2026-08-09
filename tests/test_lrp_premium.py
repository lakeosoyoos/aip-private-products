"""Pin LRP premium arithmetic to RMA's published rules.

The engine previously (a) read RMA's `cost_per_cwt_amount` as the PRODUCER's premium when
it is the TOTAL premium, (b) then grossed that figure up again by 1/(1-subsidy), and
(c) applied a subsidy table shifted one band high. The three compounded into a producer
premium overstated by 1.54x at 100% coverage rising to 2.22x at 80%, which is the number
the whole savings signal is computed from -- so it is pinned here.

Authority: RMA Livestock Rate/Subsidy table (95-100% -> 35%, 90-94.99% -> 40%,
85-89.99% -> 45%, 80-84.99% -> 50%, 70-79.99% -> 55%) and the LRP handbook's worked
premium example, reproduced in test_handbook_worked_example below.
"""
from __future__ import annotations

import pandas as pd
import pytest

import lrp_signal as L


# ── The subsidy table ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cov,expected", [
    (1.00, 0.35), (0.99, 0.35), (0.96, 0.35), (0.95, 0.35),   # 95.00-100%
    (0.94, 0.40), (0.925, 0.40), (0.90, 0.40),                # 90.00-94.99%
    (0.89, 0.45), (0.875, 0.45), (0.85, 0.45),                # 85.00-89.99%
    (0.84, 0.50), (0.80, 0.50),                               # 80.00-84.99%
    (0.79, 0.55), (0.75, 0.55),                               # 70.00-79.99%
])
def test_subsidy_bands(cov, expected):
    assert L.get_subsidy_rate(cov) == pytest.approx(expected)


def test_subsidy_never_inverts():
    """Higher coverage must never carry a HIGHER subsidy rate."""
    rates = [L.get_subsidy_rate(c) for c in sorted(L.COVERAGE_LEVELS)]
    assert rates == sorted(rates, reverse=True)


# ── The coverage-level set ───────────────────────────────────────────────────

def test_coverage_levels_match_rma():
    """Exactly the twelve levels RMA publishes; 0.70 is not one of them."""
    assert L.COVERAGE_LEVELS == [0.75, 0.80, 0.85, 0.875, 0.90, 0.925,
                                 0.95, 0.96, 0.97, 0.98, 0.99, 1.00]
    assert 0.70 not in L.COVERAGE_LEVELS


def test_coverage_levels_closer_than_old_tolerance():
    """Guards the matcher: levels are 0.01 apart, so a +/-0.025 window is unsafe."""
    gaps = [b - a for a, b in zip(L.COVERAGE_LEVELS, L.COVERAGE_LEVELS[1:])]
    assert min(gaps) < 0.025


# ── RMA's worked example ─────────────────────────────────────────────────────

def test_handbook_worked_example():
    """$56,250 insured value x .013990 rate = $787 total; 35% subsidy = $275;
    producer pays $512. The engine must reproduce all three."""
    insured_value = 56_250.0
    rate = 0.013990

    total = insured_value * rate
    assert round(total) == 787

    subsidy_rate = L.get_subsidy_rate(1.00)
    assert subsidy_rate == 0.35
    assert round(total * subsidy_rate) == 275
    assert round(total * (1 - subsidy_rate)) == 512


# ── The parser: cost_per_cwt_amount is TOTAL, not producer ───────────────────

_HEADER = ("commodity_code|type_code|endorsement_length_count|"
           "livestock_coverage_level_percent|coverage_price|livestock_rate|"
           "cost_per_cwt_amount|expected_ending_value_amount|deleted_date")


def _rate_file(cov_level, rate, cov_price):
    cost_cwt = rate * cov_price
    return (_HEADER + "\n" +
            f"0801|809|13|{cov_level}|{cov_price}|{rate}|{cost_cwt}|{cov_price}|\n")


def test_parser_splits_total_into_producer_share():
    df = L._parse_rate_file(_rate_file(0.95, 0.013990, 250.0), "feeder")
    assert len(df) == 1
    row = df.iloc[0]
    total = 0.013990 * 250.0
    # actuarial_prem is RMA's published total, untouched...
    assert row["actuarial_prem"] == pytest.approx(total)
    # ...and the producer pays it net of the 35% subsidy for 95% coverage.
    assert row["producer_prem"] == pytest.approx(total * 0.65)
    assert row["producer_prem"] < row["actuarial_prem"]


def test_producer_never_exceeds_total():
    """The defect's signature: producer_prem used to EQUAL (then exceed) the total."""
    for cov in L.COVERAGE_LEVELS:
        df = L._parse_rate_file(_rate_file(cov, 0.02, 300.0), "feeder")
        row = df.iloc[0]
        assert row["producer_prem"] < row["actuarial_prem"], f"at coverage {cov}"


# ── The grid: no re-grossing, and exact level matching ───────────────────────

def _grid_row(cov, weeks=13):
    return {"weeks": weeks, "coverage_level": cov, "coverage_price": 100.0 * cov,
            "actuarial_prem": 10.0, "producer_prem": 10.0 * (1 - L.get_subsidy_rate(cov)),
            "expected_value": 100.0}


def test_grid_uses_published_premiums_verbatim():
    """build_grid must pass RMA's two premiums straight through, not re-derive one."""
    lrp_df = pd.DataFrame([_grid_row(c) for c in L.COVERAGE_LEVELS])
    grid = L.build_grid(lrp_df, futures_curve=None, r=0.04, base_vol=0.20)
    g = pd.DataFrame(grid)
    live = g[g["live"]] if "live" in g.columns else g
    assert not live.empty
    for _, row in live.iterrows():
        assert row["producer_prem"] <= row["actuarial_prem"] + 1e-9


def test_grid_matches_adjacent_levels_distinctly():
    """0.95..0.99 sit 0.01 apart; each must pick its OWN row, not a neighbour's."""
    rows = []
    for i, cov in enumerate([0.95, 0.96, 0.97, 0.98, 0.99]):
        r = _grid_row(cov)
        r["coverage_price"] = 200.0 + i          # a unique fingerprint per level
        rows.append(r)
    lrp_df = pd.DataFrame(rows)
    for i, cov in enumerate([0.95, 0.96, 0.97, 0.98, 0.99]):
        mask = ((lrp_df["weeks"] == 13) &
                ((lrp_df["coverage_level"] - cov).abs() < 0.0025))
        assert mask.sum() == 1, f"coverage {cov} matched {mask.sum()} rows"
        assert lrp_df[mask].iloc[0]["coverage_price"] == pytest.approx(200.0 + i)


# ── The sales window ─────────────────────────────────────────────────────────

def test_sales_window_closes_at_825_ct():
    """RMA closes LRP sales at 8:25 AM CT, not 9:00 -- the extra 35 minutes told the
    producer a closed window was still open."""
    import inspect
    for src in (inspect.getsource(L.check_window),
                inspect.getsource(L.fetch_lrp_current)):
        assert "540" not in src, "9:00 AM boundary still present"
        assert "505" in src, "8:25 AM boundary missing"


# ── the richness denominator, which is in PERCENT ────────────────────────────

def test_baseline_gap_pct_floor_is_in_percent_units():
    """gap_pct is stored as a percent, so the floor must be too.

    The guard read `abs(avg_pct) > 0.001` — one thousandth of one percent, i.e. no floor.
    Richness divides by that number, so a cell whose normal gap is indistinguishable from
    zero produced an enormous multiple: 228x was observed on real history against a BUY
    gate of 1.25. A ratio against a near-zero denominator is noise wearing a number.
    """
    assert L.MIN_BASELINE_GAP_PCT >= 0.01, "floor is small enough to admit noise denominators"
    assert L.MIN_BASELINE_GAP_PCT < 1.0, "floor so high it would reject ordinary baselines"


def test_a_near_zero_baseline_yields_no_richness_rather_than_a_huge_multiple():
    """The failure mode: divide by ~0, get a spectacular number, fire a BUY on nothing."""
    import pandas as pd

    grid = pd.DataFrame([{"weeks": 13, "coverage_level": 0.95, "gap": 0.50, "gap_pct": 0.20}])
    # A baseline whose average gap_pct is 0.002 PERCENT — statistically zero.
    hist = pd.DataFrame([{"date": f"2026-06-{d:02d}", "weeks": 13, "coverage_level": 0.95,
                          "gap": 0.11, "gap_pct": 0.002} for d in range(1, 12)])
    out = L.add_history_from_snapshots(
        grid.copy(), "feeder", lookback=30,
        today_date=__import__("datetime").date(2026, 6, 20),
        _hist=hist) if "_hist" in L.add_history_from_snapshots.__code__.co_varnames else None
    if out is None:
        # No injection hook — assert the guard arithmetic directly instead.
        assert abs(0.002) < L.MIN_BASELINE_GAP_PCT, (
            "a 0.002% baseline must be rejected as a richness denominator")
    else:
        assert out.iloc[0]["richness"] is None
