"""Pin the NASS Quick Stats loader — above all, WHICH UNIT each crop is loaded in.

This connector's job is a one-pass filter over a 10 GB text file, and almost every way it can
go wrong is loud: a missing column raises, a suppression flag returns None, a bad year is
skipped. There is exactly ONE failure mode that is silent, and it is the reason this file
exists: loading a crop at the WRONG UNIT.

Cotton and rice report LB / ACRE; corn, soybeans and wheat report BU / ACRE. Nothing
downstream can catch a mix-up, because src/basisrisk.py detrends every series into a unitless
ratio and is therefore exactly scale-invariant — a cotton series read as bushels produces the
same CV, the same skew and the same miss rate as the correct one, and the map looks fine.
(tests/test_basisrisk.py::test_a_fifty_fold_unit_error_changes_no_risk_metric_at_all proves
that.) So the unit has to be right HERE, at load, and it is pinned here rather than trusted.

The hazard is not hypothetical. NASS carries cotton at both 'LB / ACRE' and
'LB / NET PLANTED ACRE', and the second series' county values run 10-50x smaller than the
first (Merced CA 1987: 119.3 against roughly 1,150). Both load, deliberately and separately;
what must never happen is one being served where the other was asked for.
"""
from __future__ import annotations

import gzip

import pytest

from src import basisrisk as B
from src.connectors import nass_yield as N

HEADER = [
    "SOURCE_DESC", "SECTOR_DESC", "GROUP_DESC", "COMMODITY_DESC", "CLASS_DESC",
    "PRODN_PRACTICE_DESC", "UTIL_PRACTICE_DESC", "STATISTICCAT_DESC", "UNIT_DESC",
    "SHORT_DESC", "DOMAIN_DESC", "DOMAINCAT_DESC", "AGG_LEVEL_DESC", "STATE_ANSI",
    "STATE_FIPS_CODE", "STATE_ALPHA", "STATE_NAME", "ASD_CODE", "ASD_DESC", "COUNTY_ANSI",
    "COUNTY_CODE", "COUNTY_NAME", "REGION_DESC", "ZIP_5", "WATERSHED_CODE", "WATERSHED_DESC",
    "CONGR_DISTRICT_CODE", "COUNTRY_CODE", "COUNTRY_NAME", "LOCATION_DESC", "YEAR",
    "FREQ_DESC", "BEGIN_CODE", "END_CODE", "REFERENCE_PERIOD_DESC", "WEEK_ENDING",
    "LOAD_TIME", "VALUE", "CV_%",
]
IX = {name: i for i, name in enumerate(HEADER)}


def _row(**kw):
    """One NASS bulk row with realistic defaults; override only what a test is about."""
    r = [""] * len(HEADER)
    base = {
        "SOURCE_DESC": "SURVEY", "SECTOR_DESC": "CROPS", "GROUP_DESC": "FIELD CROPS",
        "COMMODITY_DESC": "CORN", "CLASS_DESC": "ALL CLASSES",
        "PRODN_PRACTICE_DESC": "ALL PRODUCTION PRACTICES",
        "UTIL_PRACTICE_DESC": "GRAIN", "STATISTICCAT_DESC": "YIELD", "UNIT_DESC": "BU / ACRE",
        "DOMAIN_DESC": "TOTAL", "AGG_LEVEL_DESC": "COUNTY", "STATE_FIPS_CODE": "19",
        "STATE_ALPHA": "IA", "ASD_CODE": "10", "COUNTY_ANSI": "169", "COUNTY_NAME": "STORY",
        "YEAR": "2020", "VALUE": "195.0",
    }
    base.update(kw)
    for k, v in base.items():
        r[IX[k]] = v
    return r


def _gz(tmp_path, rows, name="qs.txt.gz"):
    path = tmp_path / name
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(HEADER) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return path


def _load(tmp_path, rows):
    """(crop, class, unit, loc, year, value) tuples the connector would insert."""
    return [(t[0], t[2], t[4], t[6], t[11], t[12]) for t in N.iter_rows(_gz(tmp_path, rows))]


# ── The unit map: per crop, and the single source of truth ──────────────────

def test_the_unit_map_is_per_crop_and_comes_from_the_estimator():
    """Two copies of 'what unit is cotton in' would drift. There must be exactly one."""
    assert N.KEEP_YIELD_UNITS["Cotton"] == {"LB / ACRE", "LB / NET PLANTED ACRE"}
    assert N.KEEP_YIELD_UNITS["Corn"] == {"BU / ACRE", "BU / NET PLANTED ACRE"}
    assert set(N.KEEP_YIELD_UNITS) == set(N.COMMODITIES.values())
    for crop, units in N.KEEP_YIELD_UNITS.items():
        assert units == {B.CROP_YIELD_UNIT[crop], B.CROP_PLANTED_YIELD_UNIT[crop]}


def test_cotton_is_loaded_and_it_is_loaded_in_pounds(tmp_path):
    got = _load(tmp_path, [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND", UNIT_DESC="LB / ACRE",
             UTIL_PRACTICE_DESC="ALL UTILIZATION PRACTICES",
             STATE_FIPS_CODE="48", STATE_ALPHA="TX", COUNTY_ANSI="303", VALUE="912.0"),
    ])
    assert got == [("Cotton", "UPLAND", "LB / ACRE", "48303", 2020, 912.0)]


def test_a_crop_is_refused_in_another_crops_unit(tmp_path):
    """THE GUARD. Cotton in bushels and corn in pounds are both nonsense and both plausible.

    A blanket unit set — the obvious way to write this filter — would accept both, and no
    number computed from either would ever look wrong.
    """
    rows = [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND", UNIT_DESC="BU / ACRE",
             VALUE="18.2"),                                   # cotton, "in bushels"
        _row(COMMODITY_DESC="CORN", UNIT_DESC="LB / ACRE", VALUE="10920.0"),   # corn, "in lb"
    ]
    assert _load(tmp_path, rows) == []


def test_cottons_net_planted_series_loads_separately_and_does_not_masquerade(tmp_path):
    """Both cotton series load, at their own unit — the 10-50x gap must stay visible.

    Keeping them apart is what lets `load_series` ask for one and be sure of what it got.
    """
    got = _load(tmp_path, [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND", UNIT_DESC="LB / ACRE",
             STATE_FIPS_CODE="06", STATE_ALPHA="CA", COUNTY_ANSI="047", VALUE="1150.0"),
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND",
             UNIT_DESC="LB / NET PLANTED ACRE",
             STATE_FIPS_CODE="06", STATE_ALPHA="CA", COUNTY_ANSI="047", VALUE="119.3"),
    ])
    assert {(u, v) for _, _, u, _, _, v in got} == {
        ("LB / ACRE", 1150.0), ("LB / NET PLANTED ACRE", 119.3)}


def test_corn_silage_is_still_excluded(tmp_path):
    """TONS / ACRE is silage, not the insured grain crop — the per-crop map must keep dropping it."""
    assert _load(tmp_path, [
        _row(UNIT_DESC="TONS / ACRE", UTIL_PRACTICE_DESC="SILAGE", VALUE="21.0")]) == []


def test_area_harvested_is_in_acres_for_every_crop(tmp_path):
    """The per-crop yield unit must not accidentally apply to the area rows."""
    got = _load(tmp_path, [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND",
             STATISTICCAT_DESC="AREA HARVESTED", UNIT_DESC="ACRES", VALUE="21,500"),
        _row(STATISTICCAT_DESC="AREA HARVESTED", UNIT_DESC="ACRES", VALUE="88,000"),
        _row(STATISTICCAT_DESC="AREA HARVESTED", UNIT_DESC="LB / ACRE", VALUE="5"),
    ])
    assert [g[5] for g in got] == [21500.0, 88000.0]


# ── Pima: a different insured commodity, dropped at load ────────────────────

def test_pima_cotton_is_dropped(tmp_path):
    """ADM 0022, not 0021; STAX does not cover it (16-STAX-0021 §2(a)); 10 usable counties.

    Dropping it at load is what makes `crop='Cotton'` mean upland cotton unambiguously, so a
    query that forgets to filter on class cannot blend two crops into one series.
    """
    got = _load(tmp_path, [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="PIMA", UNIT_DESC="LB / ACRE",
             STATE_FIPS_CODE="04", STATE_ALPHA="AZ", COUNTY_ANSI="003", VALUE="1300.0"),
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND", UNIT_DESC="LB / ACRE",
             STATE_FIPS_CODE="04", STATE_ALPHA="AZ", COUNTY_ANSI="003", VALUE="1450.0"),
    ])
    assert [g[1] for g in got] == ["UPLAND"]
    assert N.DROP_CLASSES["Cotton"] == {"PIMA"}


def test_cotton_keeps_its_upland_class_rather_than_being_relabelled(tmp_path):
    """basisrisk.CLASS_PREFERENCE['Cotton'] selects on 'UPLAND'; the two must agree."""
    got = _load(tmp_path, [
        _row(COMMODITY_DESC="COTTON", CLASS_DESC="UPLAND", UNIT_DESC="LB / ACRE")])
    assert got[0][1] in B.CLASS_PREFERENCE["Cotton"]


# ── The filters that were already there, kept honest ────────────────────────

@pytest.mark.parametrize("raw", ["(D)", "(NA)", "(X)", "(Z)", "", "  ", "not a number"])
def test_suppression_flags_never_become_zero(raw):
    """A withheld year is a MISSING year. A zero would read as a total crop failure."""
    assert N.parse_value(raw) is None


def test_thousands_separators_parse():
    assert N.parse_value(" 1,234.5 ") == 1234.5


@pytest.mark.parametrize("kw", [
    {"SOURCE_DESC": "CENSUS"},              # 5-yearly, useless as a time series
    {"DOMAIN_DESC": "ECONOMIC CLASS"},      # a breakout, not the total
    {"STATISTICCAT_DESC": "AREA PLANTED"},  # neither yield nor harvested area
    {"COMMODITY_DESC": "OATS"},             # not a crop this project scores
    {"VALUE": "(D)"},                       # suppressed
    {"VALUE": "0"},                         # non-positive
    {"YEAR": "nineteen ninety"},            # unparseable
    {"COUNTY_ANSI": "998"},                 # NASS's residual "other counties" bucket
    {"COUNTY_ANSI": ""},                    # county row with no county
])
def test_rows_we_deliberately_drop(tmp_path, kw):
    assert _load(tmp_path, [_row(**kw)]) == []


def test_aggregation_levels_get_the_right_location_key(tmp_path):
    got = _load(tmp_path, [
        _row(AGG_LEVEL_DESC="NATIONAL", STATE_FIPS_CODE="", ASD_CODE="", COUNTY_ANSI=""),
        _row(AGG_LEVEL_DESC="STATE", COUNTY_ANSI=""),
        _row(AGG_LEVEL_DESC="AGRICULTURAL DISTRICT", COUNTY_ANSI=""),
        _row(AGG_LEVEL_DESC="COUNTY"),
    ])
    assert [g[3] for g in got] == ["US", "19", "19-10", "19169"]


def test_a_missing_column_raises_rather_than_loading_nonsense(tmp_path):
    path = tmp_path / "bad.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(c for c in HEADER if c != "UNIT_DESC") + "\n")
    with pytest.raises(ValueError, match="missing expected columns"):
        list(N.iter_rows(path))


def test_the_commodity_map_matches_the_estimators_crops():
    """A crop loaded but not scoreable (or vice versa) is a silent hole in the map."""
    assert set(N.COMMODITIES.values()) == set(B.CROP_YIELD_UNIT)
    assert N.COMMODITIES["COTTON"] == "Cotton"
