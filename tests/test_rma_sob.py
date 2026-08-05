"""Unit tests for the rma_sob parsing/mapping helpers — no network, no downloads."""
from __future__ import annotations

from src.connectors import rma_sob


def _line(*, plan, commodity, state="19", county="169", state_abbrev="IA",
          policies="1", qty_type="Acres", net="0", endorsed="0",
          liability="0", premium="0", subsidy="0", indemnity="0", plan_abbrev="XX"):
    """Build one 28-field pipe-delimited sobcov line with the fields the connector reads."""
    f = ["2026", state, state_abbrev, county, "County Name", commodity, "Crop", plan,
         plan_abbrev, "A", "RBUP", ".7500", policies, policies, "0", "0", "0", qty_type,
         net, endorsed, liability, premium, subsidy, "0", "0", "0", indemnity, ".00"]
    assert len(f) == len(rma_sob.SOBCOV_FIELDS)
    return "|".join(f)


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def test_parse_sob_rows_positional():
    rows = list(rma_sob.parse_sob_rows([_line(plan="31", commodity="0041"), "", "\n"]))
    assert len(rows) == 1
    r = rows[0]
    assert r["plan_code"] == "31"
    assert r["commodity_code"] == "0041"
    assert r["state_abbrev"] == "IA"
    assert r["liability"] == "0"


def test_parse_sob_rows_skips_short_lines():
    assert list(rma_sob.parse_sob_rows(["a|b|c"])) == []


def test_number_coercion():
    assert rma_sob._to_float("") == 0.0
    assert rma_sob._to_float(None) == 0.0
    assert rma_sob._to_float("junk") == 0.0
    assert rma_sob._to_float("1234.5") == 1234.5
    assert rma_sob._to_int("15297.0") == 15297


# ---------------------------------------------------------------------------
# net-acres rule (base plan vs endorsement vs non-acre quantity)
# ---------------------------------------------------------------------------

def test_sob_net_acres_base_plan_uses_net():
    row = {"quantity_type": "Acres", "net_reported_quantity": "11316275",
           "endorsed_companion_acres": "0"}
    assert rma_sob.sob_net_acres(row) == 11316275.0


def test_sob_net_acres_endorsement_uses_endorsed():
    row = {"quantity_type": "Acres", "net_reported_quantity": "0",
           "endorsed_companion_acres": "3338541"}
    assert rma_sob.sob_net_acres(row) == 3338541.0


def test_sob_net_acres_non_acre_quantity_is_zero():
    # Tons/Colonies/Trees rows must not leak into an "acres" total.
    row = {"quantity_type": "Tons", "net_reported_quantity": "500",
           "endorsed_companion_acres": "0"}
    assert rma_sob.sob_net_acres(row) == 0.0


# ---------------------------------------------------------------------------
# aggregation + mapping
# ---------------------------------------------------------------------------

def _std_maps():
    # SCO 31/32/33 -> product 3; MP 16/17 -> product 1 (Spring Wheat); WFRP 76 -> product 7.
    plan_to_pid = {"31": 3, "32": 3, "33": 3, "16": 1, "17": 1, "76": 7, "35": 2}
    product_crop_set = {(3, "Corn"), (3, "Wheat"), (1, "Spring Wheat"),
                        (7, "All crops (whole-farm)"), (2, "Cotton")}
    return plan_to_pid, product_crop_set


def test_aggregate_sums_and_dedups_across_coverage_levels():
    plan_to_pid, crops = _std_maps()
    lines = [
        # two coverage-level rows for the SAME county/crop/plan -> one aggregated row
        _line(plan="31", commodity="0041", endorsed="1000", liability="100", premium="20",
              policies="5"),
        _line(plan="31", commodity="0041", endorsed="500", liability="50", premium="10",
              policies="3"),
        # a different plan (32) for the same county/crop -> separate row (distinct plan_code)
        _line(plan="32", commodity="0041", endorsed="200", liability="25", premium="5",
              policies="2"),
    ]
    rows = rma_sob.aggregate_sob(rma_sob.parse_sob_rows(lines), plan_to_pid, crops,
                                 2026, "sobcov_2026")
    by_plan = {r[5]: r for r in rows}
    assert set(by_plan) == {"31", "32"}
    r31 = by_plan["31"]
    # tuple: (year, state, fips, crop, commodity, plan, abbrev, acres, lia, prem, sub, ind, pol, src)
    assert r31[0] == 2026 and r31[1] == "IA" and r31[2] == "19169" and r31[3] == "Corn"
    assert r31[4] == "0041" and r31[7] == 1500.0        # endorsed acres summed
    assert r31[8] == 150.0 and r31[9] == 30.0           # liability, premium summed
    assert r31[12] == 8                                 # policies summed
    assert r31[13] == "sobcov_2026"


def test_aggregate_drops_unknown_plan_and_non_row_crop():
    plan_to_pid, crops = _std_maps()
    lines = [
        _line(plan="90", commodity="0041"),   # plan not in catalog -> dropped
        _line(plan="31", commodity="0054"),   # apples -> dropped by row-crop gate
        _line(plan="31", commodity="0041", endorsed="10", liability="9"),  # kept
    ]
    rows = rma_sob.aggregate_sob(rma_sob.parse_sob_rows(lines), plan_to_pid, crops,
                                 2026, "sobcov_2026")
    assert len(rows) == 1 and rows[0][5] == "31" and rows[0][3] == "Corn"


def test_aggregate_spring_wheat_relabel_and_wfrp():
    plan_to_pid, crops = _std_maps()
    lines = [
        _line(plan="16", commodity="0011", net="100", liability="7"),   # MP wheat -> Spring Wheat
        _line(plan="76", commodity="0076", net="0", endorsed="0", liability="500"),  # WFRP
        _line(plan="76", commodity="9110", liability="99"),             # Micro Farm -> dropped
    ]
    rows = rma_sob.aggregate_sob(rma_sob.parse_sob_rows(lines), plan_to_pid, crops,
                                 2026, "sobcov_2026")
    crops_by_plan = {r[5]: r[3] for r in rows}
    assert crops_by_plan["16"] == "Spring Wheat"
    assert crops_by_plan["76"] == "All crops (whole-farm)"
    assert "9110" not in {r[4] for r in rows}
