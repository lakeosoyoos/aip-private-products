"""Tests for the row-crop opportunity precompute (src/rowcropopt.py). No network.

The metric under test is

    unclaimed subsidy = eligible acres x (1 - penetration) x subsidy captured per acre

and most of what is asserted here is the metric's HONESTY conditions, not its arithmetic:
the eligible denominator excludes what RMA's own rules exclude (CAT, area plans, a mutually
exclusive band), a per-acre dollar figure is labelled as observed or fitted, a band that is
not sold on a crop anywhere gets no row at all, and a schema that has moved under us produces
a loud error rather than a national map of zeros.
"""
from __future__ import annotations

import sqlite3

import pytest

from src import db
from src.rowcropopt import (
    ALL_CROPS, BAND_PLANS, EXCLUSIVE_PAIRS, MIN_OBS_ACRES, SobSchemaError, available_years,
    bands_offered, build, check_sob_schema, compute_rows, county_totals, eligible_base,
    fips5, rank_crops, summarize, value_ratios, write_rows,
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    return c


def _sob(conn, *, year=2026, state="NE", fips="31041", crop="Corn", plan="02",
         abbrev="RP", cov_type="A", cov=0.85, acres=1000.0, liability=600_000.0,
         premium=40_000.0, subsidy=28_000.0, policies=10):
    """One sob_sales row. producer_premium is derived so the fixtures stay self-consistent."""
    conn.execute(
        "INSERT OR REPLACE INTO sob_sales (year, state, county_fips, crop, commodity_code, "
        " plan_code, plan_abbrev, coverage_type, coverage_level, net_acres, liability, "
        " total_premium, subsidy, producer_premium, indemnity, policies_sold, source) "
        "VALUES (?,?,?,?,'0041',?,?,?,?,?,?,?,?,?,0,?,'synthetic')",
        (year, state, fips, crop, plan, abbrev, cov_type, cov, acres, liability,
         premium, subsidy, premium - subsidy, policies))


@pytest.fixture()
def populated(conn):
    """Two counties, one crop, one band, deliberately asymmetric.

    31041 sells ECO on half its acres; 31043 sells none at all, so it exercises the fitted
    path. Both carry the same liability per acre, so the fitted figure must land on the
    observed one exactly — which is the property the fit is claimed to have.
    """
    _sob(conn, fips="31041", acres=1000, liability=600_000)          # base RP
    _sob(conn, fips="31041", plan="88", abbrev="ECO-RP", acres=500,
         liability=60_000, premium=15_000, subsidy=12_000)           # ECO on half
    _sob(conn, fips="31043", acres=2000, liability=1_200_000)        # base RP, no ECO
    conn.commit()
    return conn


# --------------------------------------------------------------------- pure

def test_fips5_pads():
    assert fips5(1001) == "01001"
    assert fips5("1001") == "01001"
    assert fips5("31041") == "31041"
    assert fips5(None) == ""


def test_band_plan_codes_are_disjoint_from_base():
    from src.rowcropopt import BASE_PLAN_CODES
    every_band = {c for codes in BAND_PLANS.values() for c in codes}
    assert not every_band & set(BASE_PLAN_CODES)
    # and no plan code belongs to two bands
    flat = [c for codes in BAND_PLANS.values() for c in codes]
    assert len(flat) == len(set(flat))


def test_eligible_base_removes_a_mutually_exclusive_band_and_keeps_liability_per_acre():
    """STAX acres are not SCO's to sell, but an acre's WORTH does not change."""
    base = {"acres": 1000.0, "liability": 500_000.0, "premium": 0.0, "subsidy": 0.0,
            "pprem": 0.0, "policies": 3}
    bands = {"STAX": {"acres": 400.0, "liability": 0.0, "premium": 0.0, "subsidy": 0.0,
                      "pprem": 0.0, "policies": 0}}
    out = eligible_base(base, bands, "SCO")
    assert out["acres"] == 600.0
    assert out["liability"] / out["acres"] == pytest.approx(base["liability"] / base["acres"])
    # ECO is not in an exclusive pair, so it sees the whole denominator, untouched object.
    assert eligible_base(base, bands, "ECO") is base
    # and the relation is symmetric
    assert ("SCO", "STAX") in EXCLUSIVE_PAIRS or ("STAX", "SCO") in EXCLUSIVE_PAIRS
    assert eligible_base(base, {"SCO": {"acres": 1000.0}}, "STAX")["acres"] == 0.0


# ------------------------------------------------------------ schema guards

def test_check_sob_schema_names_the_missing_table():
    c = sqlite3.connect(":memory:")            # no schema at all
    with pytest.raises(SobSchemaError) as exc:
        check_sob_schema(c)
    msg = str(exc.value)
    assert "sob_sales" in msg
    # It must point at the WORKING catalog, because the app DB never has this table.
    assert "catalog.db" in msg and "catalog_app.db" in msg
    c.close()


def test_check_sob_schema_names_a_missing_column(conn):
    conn.execute("DROP TABLE sob_sales")
    conn.execute("CREATE TABLE sob_sales (year INTEGER, crop TEXT)")
    with pytest.raises(SobSchemaError) as exc:
        check_sob_schema(conn)
    assert "county_fips" in str(exc.value)


def test_build_refuses_an_empty_sob_sales_rather_than_writing_zeros(conn):
    """A silent zero here is indistinguishable from 'no opportunity anywhere'."""
    with pytest.raises(SobSchemaError):
        build(conn)
    assert conn.execute("SELECT COUNT(*) FROM rowcrop_unclaimed").fetchone()[0] == 0


def test_build_refuses_a_year_that_is_not_loaded(populated):
    with pytest.raises(SobSchemaError) as exc:
        build(populated, years=[1999])
    assert "1999" in str(exc.value)


def test_available_years(populated):
    assert available_years(populated) == [2026]


# ---------------------------------------------------------------- the metric

def test_county_totals_buckets_base_and_bands(populated):
    totals = county_totals(populated, 2026)
    cell = totals[("31041", "Corn")]
    assert cell["state"] == "NE"
    assert cell["base"]["acres"] == 1000
    assert cell["bands"]["ECO"]["acres"] == 500
    assert totals[("31043", "Corn")]["bands"] == {}


def test_cat_acres_are_not_eligible(conn):
    """A CAT policy cannot carry a band, so CAT acres are not in the denominator."""
    _sob(conn, plan="01", abbrev="YP", cov_type="C", acres=5000, liability=100_000)
    _sob(conn, plan="02", abbrev="RP", cov_type="A", acres=1000, liability=600_000)
    conn.commit()
    assert county_totals(conn, 2026)[("31041", "Corn")]["base"]["acres"] == 1000


def test_area_and_margin_plans_are_not_eligible(conn):
    """Neither an area plan nor standalone Margin Protection can carry a band."""
    _sob(conn, plan="02", acres=1000, liability=600_000)
    for plan, abbrev in (("04", "AYP"), ("05", "ARP"), ("16", "MP"), ("17", "MP-HPO"),
                         ("76", "WFRP"), ("37", "HIP-WI")):
        _sob(conn, plan=plan, abbrev=abbrev, acres=9999, liability=1)
    conn.commit()
    assert county_totals(conn, 2026)[("31041", "Corn")]["base"]["acres"] == 1000


def test_penetration_and_unclaimed_subsidy(populated):
    rows = {(r["county_fips"], r["crop"], r["band"]): r
            for r in compute_rows(county_totals(populated, 2026), 2026)}
    sold = rows[("31041", "Corn", "ECO")]
    assert sold["base_acres"] == 1000
    assert sold["band_acres"] == 500
    assert sold["penetration"] == pytest.approx(0.5)
    assert sold["unsold_acres"] == pytest.approx(500)
    # 12,000 subsidy over 500 band acres = $24/acre captured; 500 acres unsold.
    assert sold["sub_per_acre"] == pytest.approx(24.0)
    assert sold["unclaimed_subsidy"] == pytest.approx(500 * 24.0)
    assert sold["value_basis"] == "county"
    assert sold["evidence"] == 2


def test_return_per_dollar_is_one_over_one_minus_subsidy_share(populated):
    rows = {(r["county_fips"], r["band"]): r for r in
            compute_rows(county_totals(populated, 2026), 2026) if r["crop"] == "Corn"}
    r = rows[("31041", "ECO")]
    # premium 15,000, subsidy 12,000 -> share 0.8 -> 1/(1-0.8) = 5.0
    assert r["return_per_dollar"] == pytest.approx(5.0)
    assert r["prem_per_acre"] == pytest.approx(30.0)
    assert r["pprem_per_acre"] == pytest.approx(6.0)


def test_an_unsold_county_is_fitted_not_blank_and_says_so(populated):
    """The whole point of the map is counties with no band sales; they must get a figure."""
    rows = {(r["county_fips"], r["band"]): r for r in
            compute_rows(county_totals(populated, 2026), 2026) if r["crop"] == "Corn"}
    r = rows[("31043", "ECO")]
    assert r["penetration"] == 0 and r["unsold_acres"] == pytest.approx(2000)
    assert r["value_basis"] in ("state", "national")
    # Both counties carry $600 of base liability per acre, so the fit must reproduce the
    # observed $24/acre exactly. That equality is the fit's whole claim.
    assert r["sub_per_acre"] == pytest.approx(24.0)
    assert r["unclaimed_subsidy"] == pytest.approx(2000 * 24.0)
    # evidence 1: the band is sold in this STATE but not in this county.
    assert r["evidence"] == 1


def test_fitted_value_scales_with_the_county_s_own_liability_per_acre(conn):
    """A richer county is fitted a bigger per-acre figure — that is what makes it local."""
    _sob(conn, fips="31041", acres=1000, liability=600_000)
    _sob(conn, fips="31041", plan="88", abbrev="ECO-RP", acres=500, liability=60_000,
         premium=15_000, subsidy=12_000)
    _sob(conn, fips="31043", acres=1000, liability=1_200_000)     # twice the $/acre
    conn.commit()
    rows = {r["county_fips"]: r for r in compute_rows(county_totals(conn, 2026), 2026)
            if r["crop"] == "Corn" and r["band"] == "ECO"}
    assert rows["31043"]["sub_per_acre"] == pytest.approx(48.0)


def test_a_band_never_sold_on_a_crop_gets_no_row_at_all(populated):
    """Otherwise every wheat county reports a large, entirely fictional MCO opportunity."""
    rows = compute_rows(county_totals(populated, 2026), 2026)
    assert {r["band"] for r in rows} == {"ECO"}
    assert bands_offered(county_totals(populated, 2026)) == {"Corn": {"ECO"}}


def test_penetration_is_capped_and_the_cap_is_reported(conn):
    _sob(conn, acres=100, liability=60_000)
    _sob(conn, plan="88", abbrev="ECO-RP", acres=376, liability=40_000,
         premium=10_000, subsidy=8_000)
    conn.commit()
    r = [x for x in compute_rows(county_totals(conn, 2026), 2026)
         if x["crop"] == "Corn" and x["band"] == "ECO"][0]
    assert r["penetration"] == 1.0
    assert r["pen_capped"] == 1
    assert r["unsold_acres"] == 0
    assert r["unclaimed_subsidy"] == 0        # nothing unsold means nothing unclaimed


def test_a_tiny_band_sale_is_treated_as_noise_and_fitted_instead(conn):
    """One 5-acre policy is not a per-acre dollar figure for a whole county."""
    _sob(conn, fips="31041", acres=1000, liability=600_000)
    _sob(conn, fips="31041", plan="88", abbrev="ECO-RP", acres=500, liability=60_000,
         premium=15_000, subsidy=12_000)
    _sob(conn, fips="31043", acres=1000, liability=600_000)
    _sob(conn, fips="31043", plan="88", abbrev="ECO-RP", acres=MIN_OBS_ACRES - 1,
         liability=10, premium=9999, subsidy=9999)      # absurd $/acre if believed
    conn.commit()
    r = [x for x in compute_rows(county_totals(conn, 2026), 2026)
         if x["county_fips"] == "31043" and x["crop"] == "Corn"][0]
    assert r["value_basis"] in ("state", "national")
    assert r["sub_per_acre"] == pytest.approx(24.0, rel=0.2)
    assert r["evidence"] == 2                 # still SOLD here, just not measurably


def test_stax_and_sco_do_not_both_claim_the_same_acre(conn):
    _sob(conn, crop="Cotton", plan="02", acres=1000, liability=500_000)
    _sob(conn, crop="Cotton", plan="32", abbrev="SCO-RP", acres=600, liability=50_000,
         premium=10_000, subsidy=8_000)
    _sob(conn, crop="Cotton", plan="35", abbrev="STAX-RP", acres=300, liability=40_000,
         premium=8_000, subsidy=6_400)
    conn.commit()
    rows = {r["band"]: r for r in compute_rows(county_totals(conn, 2026), 2026)
            if r["crop"] == "Cotton"}
    assert rows["SCO"]["base_acres"] == pytest.approx(700)      # 1000 - 300 STAX acres
    assert rows["STAX"]["base_acres"] == pytest.approx(400)     # 1000 - 600 SCO acres
    # Unsold acres across the two exclusive bands cannot exceed the acres that exist.
    assert rows["SCO"]["unsold_acres"] + rows["STAX"]["unsold_acres"] <= 1000


# ------------------------------------------------------------- the rollup row

def test_rollup_equals_the_sum_of_its_crops(conn):
    for crop, acres, liab in (("Corn", 1000, 600_000), ("Soybeans", 500, 300_000)):
        _sob(conn, crop=crop, acres=acres, liability=liab)
        _sob(conn, crop=crop, plan="88", abbrev="ECO-RP", acres=acres / 2, liability=liab / 10,
             premium=acres * 30, subsidy=acres * 24)
    conn.commit()
    rows = compute_rows(county_totals(conn, 2026), 2026)
    per_crop = [r for r in rows if r["crop"] != ALL_CROPS and r["band"] == "ECO"]
    roll = [r for r in rows if r["crop"] == ALL_CROPS and r["band"] == "ECO"][0]
    assert roll["base_acres"] == pytest.approx(sum(r["base_acres"] for r in per_crop))
    assert roll["unsold_acres"] == pytest.approx(sum(r["unsold_acres"] for r in per_crop))
    assert roll["unclaimed_subsidy"] == pytest.approx(
        sum(r["unclaimed_subsidy"] for r in per_crop))
    # Per-acre comes back OUT of the sums, so it is the acre-weighted blend.
    assert roll["sub_per_acre"] == pytest.approx(
        roll["unclaimed_subsidy"] / roll["unsold_acres"])


def test_rollup_covers_crops_that_have_no_row_of_their_own(conn):
    """per-crop detail is capped at top_crops; the total must still be complete."""
    for i, crop in enumerate(["Corn", "Soybeans", "Wheat"]):
        _sob(conn, crop=crop, acres=1000 * (3 - i), liability=600_000)
        _sob(conn, crop=crop, plan="88", abbrev="ECO-RP", acres=100, liability=60_000,
             premium=3_000, subsidy=2_400)
    conn.commit()
    totals = county_totals(conn, 2026)
    rows = compute_rows(totals, 2026, top_crops=1)
    assert rank_crops(totals, bands_offered(totals), 1) == ["Corn"]
    assert {r["crop"] for r in rows} == {"Corn", ALL_CROPS}
    roll = [r for r in rows if r["crop"] == ALL_CROPS][0]
    assert roll["base_acres"] == pytest.approx(3000 + 2000 + 1000)   # every crop, not just Corn


def test_rollup_denominator_is_only_the_crops_the_band_is_offered_on(conn):
    """Wheat acres must not inflate an MCO rollup when MCO is not sold on wheat."""
    _sob(conn, crop="Corn", acres=1000, liability=600_000)
    _sob(conn, crop="Corn", plan="68", abbrev="MCO-RP", acres=100, liability=60_000,
         premium=3_000, subsidy=2_400)
    _sob(conn, crop="Wheat", acres=5000, liability=1_000_000)
    conn.commit()
    roll = [r for r in compute_rows(county_totals(conn, 2026), 2026)
            if r["crop"] == ALL_CROPS and r["band"] == "MCO"][0]
    assert roll["base_acres"] == pytest.approx(1000)


def test_rollup_basis_is_mixed_when_its_crops_disagree(conn):
    """31041 sells ECO on corn but not on soybeans, so its rollup is half observed, half fit."""
    for crop in ("Corn", "Soybeans"):                     # 31043 establishes the OFFER on both
        _sob(conn, fips="31043", crop=crop, acres=1000, liability=600_000)
        _sob(conn, fips="31043", crop=crop, plan="88", abbrev="ECO-RP", acres=500,
             liability=60_000, premium=15_000, subsidy=12_000)
    _sob(conn, fips="31041", crop="Corn", acres=1000, liability=600_000)
    _sob(conn, fips="31041", crop="Corn", plan="88", abbrev="ECO-RP", acres=500,
         liability=60_000, premium=15_000, subsidy=12_000)
    _sob(conn, fips="31041", crop="Soybeans", acres=1000, liability=600_000)   # no band here
    conn.commit()
    rolls = {r["county_fips"]: r for r in compute_rows(county_totals(conn, 2026), 2026)
             if r["crop"] == ALL_CROPS and r["band"] == "ECO"}
    assert rolls["31041"]["value_basis"] == "mixed"
    assert rolls["31043"]["value_basis"] == "county"      # both crops observed locally


# ------------------------------------------------------------------ storage

def test_write_rows_is_idempotent_per_year(populated):
    rows = compute_rows(county_totals(populated, 2026), 2026)
    write_rows(populated, rows, 2026)
    first = populated.execute("SELECT COUNT(*) FROM rowcrop_unclaimed").fetchone()[0]
    write_rows(populated, rows, 2026)
    assert populated.execute("SELECT COUNT(*) FROM rowcrop_unclaimed").fetchone()[0] == first
    assert first == len(rows)
    stored = populated.execute(
        "SELECT source, fetched_at FROM rowcrop_unclaimed LIMIT 1").fetchone()
    assert stored[0] and stored[1]


def test_write_rows_replaces_only_its_own_year(populated):
    rows = compute_rows(county_totals(populated, 2026), 2026)
    write_rows(populated, rows, 2026)
    populated.execute("INSERT INTO rowcrop_unclaimed (year, county_fips, crop, band) "
                      "VALUES (2024, '31041', 'Corn', 'ECO')")
    populated.commit()
    write_rows(populated, rows, 2026)
    assert populated.execute(
        "SELECT COUNT(*) FROM rowcrop_unclaimed WHERE year = 2024").fetchone()[0] == 1


def test_build_end_to_end(populated):
    res = build(populated)
    assert res["years"] == [2026]
    n = populated.execute("SELECT COUNT(*) FROM rowcrop_unclaimed").fetchone()[0]
    assert n == res["per_year"][2026]["rows"] > 0
    s = res["per_year"][2026]
    assert s["counties"] == 2 and s["bands"] == ["ECO"]
    assert s["unclaimed_subsidy_all_crops"] == pytest.approx(500 * 24 + 2000 * 24)


def test_summarize_counts_basis_and_evidence(populated):
    s = summarize(compute_rows(county_totals(populated, 2026), 2026))
    assert set(s["basis"]) <= {"county", "state", "national", "mixed", "None"}
    assert sum(s["evidence"].values()) == s["rows"]


def test_value_ratios_only_fit_on_counties_that_sell_the_band(populated):
    ratios = value_ratios(county_totals(populated, 2026))
    # 12,000 subsidy / (500 acres x $600 liability per acre) = 0.04
    assert ratios["sub"][("N", "Corn", "ECO")] == pytest.approx(0.04)
    assert ratios["ret"][("N", "Corn", "ECO")] == pytest.approx(5.0)


def test_cli_reports_instead_of_crashing_on_an_empty_db(tmp_path, capsys):
    from src.rowcropopt import main
    path = tmp_path / "empty.db"
    assert main(["--db", str(path)]) == 2
    assert "REFUSING TO BUILD" in capsys.readouterr().out


# ------------------------------------------------------------- the basis-risk join
#
# The join exists to stop ONE specific wrong answer: ranking a county as a prospect when the
# product cannot respond to its farms' losses. Nearly everything below asserts a refusal —
# unknown never becomes low, one band's estimate never stands in for another's, a minority of
# the acres never speaks for the county — because those are the failure modes that would look
# like a working map.

def _br(conn, *, fips="31041", crop="Corn", band="ECO95", plan="RP", cov=0.85,
        miss=0.20, rho_lo_miss=0.30, rho_hi_miss=0.10, deep=0.15, uncov=0.35,
        windfall=0.25, grade="A", n_years=40):
    conn.execute(
        "INSERT OR REPLACE INTO basis_risk_county (crop, county_fips, state, county_name, "
        " band, plan_type, coverage_level, n_years, miss_rate, miss_rate_rho_lo, "
        " miss_rate_rho_hi, miss_rate_ci_lo, miss_rate_ci_hi, deep_miss_rate, "
        " uncovered_share, windfall_rate, grade, source, fetched_at) "
        "VALUES (?,?,'NE','TEST',?,?,?,?,?,?,?,?,?,?,?,?,?,'synthetic','2026-08-07')",
        (crop, fips, band, plan, cov, n_years, miss, rho_lo_miss, rho_hi_miss,
         max(0.0, miss - 0.05), miss + 0.05, deep, uncov, windfall, grade))


def _ru(conn, *, year=2026, fips="31041", state="NE", crop="Corn", band="ECO", base=1000.0):
    """One rowcrop_unclaimed row with nothing sold — every derived column filled, as the
    precompute always fills them, so the CLI reporter sees the shape it really gets."""
    conn.execute(
        "INSERT OR REPLACE INTO rowcrop_unclaimed (year, state, county_fips, crop, band, "
        " base_acres, band_acres, penetration, pen_capped, unsold_acres, sub_per_acre, "
        " prem_per_acre, value_basis, evidence, unclaimed_subsidy, unclaimed_premium, "
        " source, fetched_at) "
        "VALUES (?,?,?,?,?,?,0,0.0,0,?,24.0,30.0,'county',1,?,?,'synthetic','2026-08-07')",
        (year, state, fips, crop, band, base, base, base * 24, base * 30))
    return {"county_fips": fips, "crop": crop, "band": band, "base_acres": base}


def test_responsiveness_is_one_minus_miss_and_never_silently_one():
    from src.rowcropopt import responsiveness
    assert responsiveness(0.2) == pytest.approx(0.8)
    assert responsiveness(0.0) == 1.0
    assert responsiveness(None) is None          # unknown must NOT become a weight of 1
    assert responsiveness("nonsense") is None
    assert responsiveness(1.4) == 0.0 and responsiveness(-0.4) == 1.0   # clamped


def test_adjust_returns_none_rather_than_the_unadjusted_value():
    """The whole point: 'no basis-risk answer' may never be rendered as 'no basis risk'."""
    from src.rowcropopt import adjust
    assert adjust(1000.0, 0.25) == pytest.approx(750.0)
    assert adjust(1000.0, None) is None          # not 1000.0, and not 0.0
    assert adjust(None, 0.25) is None


def test_band_mapping_uses_the_trigger_the_book_actually_elects(conn):
    """ECO -> ECO95: 99.0% of RY2026 ECO acres elect the 95% trigger. ECO90 is the fallback."""
    from src.rowcropopt import BASIS_BANDS, basis_for_cell, basis_variants, load_basis_risk
    assert basis_variants("ECO")[0] == "ECO95"
    assert basis_variants("SCO") == ("SCO86",)
    assert BASIS_BANDS["ECO"] == ("ECO95", "ECO90")
    _br(conn, band="ECO95", miss=0.18)
    _br(conn, band="ECO90", miss=0.44)
    conn.commit()
    hit = basis_for_cell(load_basis_risk(conn), "31041", "Corn", "ECO")
    assert hit["variant"] == "ECO95" and hit["miss_rate"] == pytest.approx(0.18)


def test_eco90_is_used_when_eco95_is_the_one_missing(conn):
    from src.rowcropopt import basis_for_cell, load_basis_risk
    _br(conn, band="ECO90", miss=0.44)
    conn.commit()
    hit = basis_for_cell(load_basis_risk(conn), "31041", "Corn", "ECO")
    assert hit["variant"] == "ECO90" and hit["miss_rate"] == pytest.approx(0.44)


def test_mco_has_no_estimator_and_borrows_nobody_else_s(conn):
    """MCO settles on a MARGIN index src/basisrisk.py does not model. Unknown, not SCO's number."""
    from src.rowcropopt import (
        BASIS_BAND_NOTE, basis_for_cell, basis_note_for, basis_variants, load_basis_risk,
    )
    _br(conn, band="SCO86", miss=0.40)
    _br(conn, band="ECO95", miss=0.18)
    conn.commit()
    index = load_basis_risk(conn)
    assert basis_variants("MCO") == ()
    assert basis_for_cell(index, "31041", "Corn", "MCO") is None
    assert "MCO" in BASIS_BAND_NOTE
    assert "not estimated" in basis_note_for("MCO") or "no estimator" in basis_note_for("MCO")


def test_stax_now_has_an_estimator_but_still_never_borrows_another_band(conn):
    """STAX gained an estimator when cotton was loaded — this test used to assert the opposite.

    It maps to STAX90 and to nothing else. The failure mode it guards is unchanged: a STAX
    county with no row of its own must stay UNKNOWN rather than quietly inheriting SCO's or
    ECO's number, which would look reasonable and be made up.
    """
    from src.rowcropopt import basis_for_cell, basis_variants, load_basis_risk

    assert basis_variants("STAX") == ("STAX90",)
    _br(conn, band="SCO86", miss=0.40)
    _br(conn, band="ECO90", miss=0.26)
    conn.commit()
    index = load_basis_risk(conn)
    # SCO86 and ECO90 rows exist for this cell; STAX90 does not. Must be None, not borrowed.
    assert basis_for_cell(index, "31041", "Corn", "STAX") is None


def test_stax_note_does_not_claim_stax_is_better_than_eco90(conn):
    """STAX90 and ECO90 share a 0.90 county trigger, and a miss rate depends only on the
    trigger — so they are identical BY ARITHMETIC, not by coincidence. The note must say so,
    or a reader will rank two bands on a number that cannot distinguish them."""
    from src.rowcropopt import basis_note_for

    note = basis_note_for("STAX").lower()
    assert "eco90" in note
    assert "identical" in note or "same" in note


def test_a_crop_outside_corn_soy_wheat_is_unknown_not_defaulted(conn):
    from src.rowcropopt import basis_for_cell, basis_note_for, load_basis_risk
    _br(conn, crop="Corn", miss=0.18)
    conn.commit()
    index = load_basis_risk(conn)
    assert basis_for_cell(index, "31041", "Cotton", "ECO") is None
    assert "Corn, Soybeans and Wheat" in basis_note_for("ECO", "Cotton")


def test_load_basis_risk_honors_plan_type_and_coverage_level(conn):
    from src.rowcropopt import BASIS_COVERAGE_LEVEL, BASIS_PLAN_TYPE, load_basis_risk
    _br(conn, plan="RP", cov=0.85, miss=0.18)
    _br(conn, plan="YP", cov=0.85, miss=0.90)
    _br(conn, plan="RP", cov=0.70, miss=0.05)
    conn.commit()
    index = load_basis_risk(conn)
    assert BASIS_PLAN_TYPE == "RP" and BASIS_COVERAGE_LEVEL == 0.85
    assert len(index) == 1
    assert index[("31041", "Corn", "ECO95")]["miss_rate"] == pytest.approx(0.18)


def test_a_missing_basis_table_is_unknown_everywhere_not_an_exception():
    """A map that says 'unknown' is right; a tab that 500s because a table moved is not."""
    from src.rowcropopt import load_basis_risk
    bare = sqlite3.connect(":memory:")
    assert load_basis_risk(bare) == {}


def test_rollup_is_acre_weighted_over_the_crops_that_have_an_estimate(conn):
    from src.rowcropopt import ALL_CROPS, join_basis_risk, load_basis_risk
    _br(conn, crop="Corn", miss=0.10)
    _br(conn, crop="Soybeans", miss=0.30)
    conn.commit()
    rows = [_ru(conn, crop="Corn", base=3000.0), _ru(conn, crop="Soybeans", base=1000.0),
            _ru(conn, crop=ALL_CROPS, base=4000.0)]
    joined = join_basis_risk(rows, load_basis_risk(conn))
    roll = joined[("31041", ALL_CROPS, "ECO")]
    # 3000 acres at 0.10 and 1000 at 0.30 -> 0.15, not the unweighted 0.20.
    assert roll["miss_rate"] == pytest.approx(0.15)
    assert roll["cover"] == "covered" and roll["cover_share"] == pytest.approx(1.0)


def test_rollup_reports_partial_coverage_rather_than_pretending_to_be_complete(conn):
    from src.rowcropopt import BASIS_PARTIAL, ALL_CROPS, join_basis_risk, load_basis_risk
    _br(conn, crop="Corn", miss=0.10)
    conn.commit()
    rows = [_ru(conn, crop="Corn", base=3000.0), _ru(conn, crop="Cotton", base=1000.0),
            _ru(conn, crop=ALL_CROPS, base=4000.0)]
    roll = join_basis_risk(rows, load_basis_risk(conn))[("31041", ALL_CROPS, "ECO")]
    assert roll["cover"] == BASIS_PARTIAL
    assert roll["cover_share"] == pytest.approx(0.75)
    assert roll["crops"] == ["Corn"]


def test_a_rollup_covering_a_minority_of_its_acres_reverts_to_unknown(conn):
    """A weighted mean over 20% of the acres describes the 20%, not the county."""
    from src.rowcropopt import ALL_CROPS, MIN_BASIS_COVER, join_basis_risk, load_basis_risk
    assert MIN_BASIS_COVER == 0.50
    _br(conn, crop="Corn", miss=0.10)
    conn.commit()
    rows = [_ru(conn, crop="Corn", base=1000.0), _ru(conn, crop="Cotton", base=4000.0),
            _ru(conn, crop=ALL_CROPS, base=5000.0)]
    joined = join_basis_risk(rows, load_basis_risk(conn))
    assert ("31041", ALL_CROPS, "ECO") not in joined     # absent == unknown, by design


def test_a_rollup_takes_the_worst_grade_among_its_crops(conn):
    from src.rowcropopt import ALL_CROPS, join_basis_risk, load_basis_risk
    _br(conn, crop="Corn", grade="A", miss=0.10)
    _br(conn, crop="Soybeans", grade="C", miss=0.10)
    conn.commit()
    rows = [_ru(conn, crop="Corn", base=1000.0), _ru(conn, crop="Soybeans", base=1000.0),
            _ru(conn, crop=ALL_CROPS, base=2000.0)]
    roll = join_basis_risk(rows, load_basis_risk(conn))[("31041", ALL_CROPS, "ECO")]
    assert roll["grade"] == "C"


def test_join_never_inner_joins_the_unmeasured_half_away(conn):
    """Half of rowcrop_unclaimed's keys have no basis-risk row; all of them keep their row."""
    from src.rowcropopt import (
        BASIS_COVERED, BASIS_UNKNOWN, basis_coverage, join_basis_risk, load_basis_risk,
    )
    _br(conn, crop="Corn", miss=0.20)
    conn.commit()
    rows = [_ru(conn, crop="Corn", band="ECO"), _ru(conn, crop="Cotton", band="ECO"),
            _ru(conn, crop="Corn", band="MCO")]
    joined = join_basis_risk(rows, load_basis_risk(conn))
    assert len(joined) == 1
    cov = basis_coverage(rows, joined)
    assert cov["total"] == {BASIS_COVERED: 1, "partial": 0, BASIS_UNKNOWN: 2}
    assert cov["by_band"]["MCO"][BASIS_UNKNOWN] == 1


def test_basis_report_names_the_unknowns_and_shows_both_columns(conn):
    from src.rowcropopt import _basis_report
    _br(conn, crop="Corn", miss=0.20)
    _ru(conn, crop="Corn", band="ECO", base=1000.0)
    _ru(conn, crop=ALL_CROPS, band="ECO", base=1000.0)
    conn.execute("UPDATE rowcrop_unclaimed SET evidence = 2")
    conn.commit()
    txt = _basis_report(conn, 2026, band="ECO", limit=5)
    assert "UNKNOWN" in txt
    assert "RAW unclaimed subsidy" in txt and "BASIS-ADJUSTED unclaimed subsidy" in txt
    assert "OVERSTATES" in txt and "UNDERSTATES" in txt


def test_basis_report_says_so_when_the_table_is_missing(conn):
    from src.rowcropopt import _basis_report
    _ru(conn, crop="Corn", band="ECO")
    conn.commit()
    txt = _basis_report(conn, 2026)
    assert "basis risk unknown" in txt.lower() and "not low" in txt.lower()


def test_report_only_runs_against_a_db_with_no_sob_sales(tmp_path, capsys):
    """The reproducer for docs/rowcrop_opportunity.md, and it has to work on the SHIPPED DB.

    `--report` builds first, and building needs sob_sales — which build_app_db.py drops. Without
    --report-only nobody can re-derive a single figure in that document from the artifact that
    actually deploys.
    """
    from src.rowcropopt import main
    path = tmp_path / "app.db"
    conn = sqlite3.connect(str(path))
    db.init_db(conn)
    conn.execute("DROP TABLE sob_sales")
    _br(conn, crop="Corn", miss=0.20)
    _ru(conn, crop="Corn", band="ECO")
    _ru(conn, crop=ALL_CROPS, band="ECO")
    conn.execute("UPDATE rowcrop_unclaimed SET evidence = 2")
    conn.commit()
    conn.close()
    assert main(["--db", str(path), "--report-only", "--band", "ECO"]) == 0
    out = capsys.readouterr().out
    assert "BASIS RISK COVERAGE" in out and "BASIS-ADJUSTED" in out


def test_report_only_refuses_an_unbuilt_table_instead_of_printing_nothing(tmp_path, capsys):
    from src.rowcropopt import main
    path = tmp_path / "app.db"
    conn = sqlite3.connect(str(path))
    db.init_db(conn)
    conn.commit()
    conn.close()
    assert main(["--db", str(path), "--report-only"]) == 2
    assert "rowcrop_unclaimed is empty" in capsys.readouterr().out
