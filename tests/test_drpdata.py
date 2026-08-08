"""Unit tests for src/drpdata.py parsing + mapping — no live calls.

Fixtures are VERBATIM rows lifted from the real RMA files (header line + a couple of data
lines), so a layout change on RMA's side shows up here rather than as silently wrong numbers:
  2026_A00833_AdmDrpDailyPrice_Daily_20260401.txt   (offer 36010017, WI, Component, Q4 2026)
  2026_A00835_AdmDrpFmmoPricingFactor_Yearly_20250625.txt
  2025_A00834_AdmDrpActualPrice_Quarterly_20260722.txt
  2026_A00832_AdmDrpMilkYield_Quarterly_*.txt
  2026_A00030_InsuranceOffer_YTD.txt (plan-83 rows)
  2026_A00070_SubsidyPercent_YTD.txt (plan-83 rows)
"""
from __future__ import annotations

import sqlite3

import pytest

from src import db, drpdata


# ---------------------------------------------------------------------------
# fixtures — verbatim RMA rows
# ---------------------------------------------------------------------------

DAILY_HEADER = (
    "Record Type Code|Record Category Code|Adm Drp Daily Price ID|ADM Insurance Offer ID|"
    "Reinsurance Year|Loading Factor|Month1 Expected Class III Price|"
    "Month2 Expected Class III Price|Month3 Expected Class III Price|"
    "Month1 Expected Class IV Price|Month2 Expected Class IV Price|"
    "Month3 Expected Class IV Price|Month1 Expected Butter Price|"
    "Month2 Expected Butter Price|Month3 Expected Butter Price|"
    "Month1 Expected Cheese Price|Month2 Expected Cheese Price|"
    "Month3 Expected Cheese Price|Month1 Expected Dry Whey Price|"
    "Month2 Expected Dry Whey Price|Month3 Expected Dry Whey Price|"
    "Month1 Class III Sigma|Month2 Class III Sigma|Month3 Class III Sigma|"
    "Month1 Class IV Sigma|Month2 Class IV Sigma|Month3 Class IV Sigma|"
    "Month1 Butter Sigma|Month2 Butter Sigma|Month3 Butter Sigma|"
    "Month1 Cheese Sigma|Month2 Cheese Sigma|Month3 Cheese Sigma|"
    "Month1 Dry Whey Sigma|Month2 Dry Whey Sigma|Month3 Dry Whey Sigma|"
    "Expected Class III Price|Expected Class IV Price|Expected Butterfat Price|"
    "Expected Protein Price|Expected Other Solids Price|Adm Drp Milk Yield ID|"
    "Adm Drp Actual Price ID|Adm Drp Fmmo Pricing Factor ID|Sales Effective Date|"
    "Month1 Expected Nonfat Dry Milk Price|Month2 Expected Nonfat Dry Milk Price|"
    "Month3 Expected Nonfat Dry Milk Price|Month1 Nonfat Dry Milk Sigma|"
    "Month2 Nonfat Dry Milk Sigma|Month3 Nonfat Dry Milk Sigma|"
    "Expected Nonfat Solids Price|Component Price Weighting Factor Restricted Value|"
    "Class Price Weighting Factor Restricted Value|Released Date|Filing Date"
)

# A COMPONENT-priced offer: class3/class4 blank, butter/cheese/whey/NFDM populated.
DAILY_COMPONENT = (
    "A00833|01|909299|36010017|2026|1.0967|||||||1.9950|2.0350|2.0100|1.8060|"
    "1.7900|1.7500|0.7053|0.7100|0.7000|||||||0.1770|0.1882|0.1987|0.1503|"
    "0.1509|0.1554|0.1617|0.1722|0.1815|||2.1630|2.6578|0.4515|11329|67|9|"
    "20260401|1.5562|1.5263|1.5095|0.1923|0.2047|0.2117|1.2784|||20260401|"
    "20250430"
)

# A CLASS-priced offer from the same file: the mirror image.
DAILY_CLASS = (
    "A00833|01|909102|35994534|2026|1.0638|18.8000|18.8900|18.9500|19.7500|"
    "19.5500|19.4200||||||||||0.1285|0.1372|0.1440|0.1670|0.1713|0.1898||||||"
    "||||18.8800|19.5700||||11231|66|9|20260401||||||||||20260401|20250430"
)

DAILY_FIXTURE = "\n".join([DAILY_HEADER, DAILY_COMPONENT, DAILY_CLASS])

FMMO_FIXTURE = "\n".join([
    "Record Type Code|Record Category Code|Adm Drp Fmmo Pricing Factor ID|Reinsurance Year|"
    "Butter Manufacturing Yield|Nonfat Dry Milk Manufacturing Yield|"
    "Dry Whey Manufacturing Yield|Cheese Manufacturing Yield Casein|"
    "Cheese Manufacturing Yield Butterfat|Butterfat Retention Rate|"
    "Butterfat To Protein Ratio|Butter Make Allowance|Nonfat Dry Milk Make Allowance|"
    "Dry Whey Make Allowance|Cheese Make Allowance|Released Date|Filing Date",
    "A00835|01|9|2026|1.2110|0.9900|1.0300|1.3830|1.5890|0.9100|1.1700|"
    "0.2272|0.2393|0.2668|0.2519|20250625|20250430",
])

ACTUAL_FIXTURE = "\n".join([
    "Record Type Code|Record Category Code|Adm Drp Actual Price ID|Reinsurance Year|"
    "Month1 Actual Butter Price|Month2 Actual Butter Price|Month3 Actual Butter Price|"
    "Month1 Actual Cheese Price|Month2 Actual Cheese Price|Month3 Actual Cheese Price|"
    "Month1 Actual Dry Whey Price|Month2 Actual Dry Whey Price|Month3 Actual Dry Whey Price|"
    "Month1 Actual Nonfat Dry Milk Price|Month2 Actual Nonfat Dry Milk Price|"
    "Month3 Actual Nonfat Dry Milk Price|Actual ClassIII Price|Actual ClassIV Price|"
    "Actual Butterfat Price|Actual Protein Price|Actual Other Solids Price|"
    "Actual Nonfat Solids Price|Released Date|Filing Date",
    # settled
    "A00834|01|61|2025|1.7707|1.6311|1.6227|1.6427|1.6577|1.5642|0.6443|0.6396|0.6428|"
    "1.7788|2.0809|1.9327|16.5700|21.1700|1.7531|2.5740|0.3867|1.6746|20260722|20240430",
    # filed but not yet settled — every price column blank
    "A00834|01|62|2025|||||||||||||||||||20250119|20240430",
])

MILK_YIELD_FIXTURE = "\n".join([
    "Record Type Code|Record Category Code|Adm Drp Milk Yield ID|Reinsurance Year|"
    "State Code|Expected Yield|Actual Yield|Expected Yield Standard Deviation|"
    "Released Date|Filing Date",
    "A00832|01|21721|2027|01|5578||129.3513|20260723|20260430",
    "A00832|01|21755|2027|55|6012|6100|87.7703|20260723|20260430",
])

# ADM A00030 InsuranceOffer, plan-83 rows (verbatim, RY2026). Insurance Plan Code is
# field 7; the last row is a plan-13 PRF offer that must be filtered out.
OFFER_HEADER = (
    "Record Type Code|Record Category Code|ADM Insurance Offer ID|Reinsurance Year|"
    "Commodity Year|Commodity Code|Insurance Plan Code|State Code|County Code|Type Code|"
    "Practice Code|WA Number|Commodity Type Code|Class Code|Sub Class Code|"
    "Intended Use Code|Irrigation Practice Code|Cropping Practice Code|"
    "Organic Practice Code|Interval Code|Unit Of Measure Abbreviation|Program Type Code|"
    "Beta ID|Quality ID|Unit Discount ID|Historical Yield Trend ID|Draw ID|"
    "Optional Unit Allowed Flag|Basic Unit Allowed Flag|Enterprise Unit Allowed Flag|"
    "Whole Farm Unit Allowed Flag|Type Practice Use Code|Private 508H Flag|Hip Rate ID|"
    "Pace Date ID|Pace Rate ID|Last Released Date|Released Date|Deleted Date|Filing Date"
)
OFFER_FIXTURE = "\n".join([
    OFFER_HEADER,
    "A00030|01|36005417|2026|2026|0830|83|04|998|832|804||832|997|997|997|997|997|997|"
    "104|DOL|P||||||N|N|N|N|T|Y||||20250428|20250821||20250430",
    "A00030|01|36011020|2026|2026|0830|83|25|998|831|802||831|997|997|997|997|997|997|"
    "102|DOL|P||||||N|N|N|N|T|Y||||20250428|20250821||20250430",
    "A00030|01|35991476|2026|2026|0830|83|54|998|831|807||831|997|997|997|997|997|997|"
    "107|DOL|P||||||N|N|N|N|T|Y||||20250428|20250821||20250430",
    "A00030|01|99999999|2026|2026|0088|13|53|047|997|007||997|997|997|997|997|997|997|"
    "630|ACR|P||||||N|N|N|N|T|N||||20250428|20250821||20250430",
])

SUBSIDY_FIXTURE = "\n".join([
    "Record Type Code|Record Category Code|Reinsurance Year|Commodity Code|"
    "Unit Structure Code|Insurance Plan Code|Coverage Level Percent|Coverage Type Code|"
    "Deductible Amount|Endorsement Length Code|Endorsement Length Count|"
    "Insurance Option Code|Range Type Code|Range Low Value|Range High Value|"
    "Subsidy Percent|Last Released Date|Released Date|Deleted Date",
    "A00070|04|2026|||83|0.80|A||||||||0.550|20250428|20250822|",
    "A00070|04|2026|||83|0.85|A||||||||0.490|20250428|20250822|",
    "A00070|04|2026|||83|0.90|A||||||||0.440|20250428|20250822|",
    "A00070|04|2026|||83|0.95|A||||||||0.440|20250428|20250822|",
    # a deleted row and a different plan — both must be dropped
    "A00070|04|2026|||83|0.75|A||||||||0.590|20250428|20250822|20250901",
    "A00070|04|2026|||13|0.90|A||||||||0.510|20250428|20250822|",
])

STATE_ABBREV = {"01": "AL", "04": "AZ", "25": "MA", "54": "WV", "55": "WI"}
INTERVAL_NAMES = {
    "102": "Jan - Mar/Yr2 - Qtr1", "104": "Jul - Sep/Yr2 - Qtr3",
    "107": "Apr - Jun/Yr3 - Qtr2",
}


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    yield c
    c.close()


def _rows(text):
    return list(drpdata.parse_member(text))


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def test_num_treats_blank_as_not_published():
    # Blank is RMA's "not published for this pricing option", not zero.
    assert drpdata.num("17.4300") == pytest.approx(17.43)
    assert drpdata.num("") is None
    assert drpdata.num("   ") is None
    assert drpdata.num(None) is None
    assert drpdata.num("n/a") is None
    assert drpdata.num("0.0000") == 0.0


def test_iso_date():
    assert drpdata.iso_date("20260401") == "2026-04-01"
    assert drpdata.iso_date("") is None
    assert drpdata.iso_date("2026") is None
    assert drpdata.iso_date("2026041") is None
    assert drpdata.iso_date("abcdefgh") is None


def test_reinsurance_year_rolls_on_july_1():
    from datetime import date
    assert drpdata.reinsurance_year(date(2026, 6, 30)) == 2026
    assert drpdata.reinsurance_year(date(2026, 7, 1)) == 2027
    assert drpdata.reinsurance_year(date(2026, 12, 31)) == 2027
    assert drpdata.reinsurance_year(date(2027, 1, 1)) == 2027


def test_livestock_url_matches_rma_naming():
    assert drpdata.livestock_url(2027, "A00833", "DrpDailyPrice", "Daily", "20260805") == (
        "https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/2027/"
        "2027_A00833_ADMDrpDailyPrice_Daily_20260805.zip")


def test_parse_listing_picks_one_record_type_in_date_order():
    html = (
        '<a href="2027_A00833_ADMDrpDailyPrice_Daily_20260805.zip">x</a>'
        '<a href="2027_A00833_ADMDrpDailyPrice_Daily_20260701.zip">x</a>'
        '<a href="2027_A00834_ADMDrpActualPrice_Quarterly_20260624.zip">x</a>'
        '<a href="2027_ADMLivestockLrp_Daily_20260805.zip">x</a>'
    )
    assert drpdata.parse_listing(html, 2027, "A00833") == [
        "2027_A00833_ADMDrpDailyPrice_Daily_20260701.zip",
        "2027_A00833_ADMDrpDailyPrice_Daily_20260805.zip",
    ]
    assert drpdata.parse_listing(html, 2027, "A00834") == [
        "2027_A00834_ADMDrpActualPrice_Quarterly_20260624.zip"]
    assert drpdata.parse_listing(html, 2026, "A00833") == []


# ---------------------------------------------------------------------------
# quarter resolution — the Yr1/Yr2/Yr3 -> calendar-year mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,ry,expected", [
    # Yr1 = RY-1, Yr2 = RY, Yr3 = RY+1.
    ("Oct - Dec/Yr1 - Qtr4", 2026, (2025, 4, "2025-10-01", "2025-12-31")),
    ("Jan - Mar/Yr2 - Qtr1", 2026, (2026, 1, "2026-01-01", "2026-03-31")),
    ("Apr - Jun/Yr2 - Qtr2", 2026, (2026, 2, "2026-04-01", "2026-06-30")),
    ("Jul - Sep/Yr2 - Qtr3", 2026, (2026, 3, "2026-07-01", "2026-09-30")),
    ("Jul - Sep/Yr3 - Qtr3", 2026, (2027, 3, "2027-07-01", "2027-09-30")),
    # same interval name, next reinsurance year -> shifts a year
    ("Oct - Dec/Yr1 - Qtr4", 2027, (2026, 4, "2026-10-01", "2026-12-31")),
])
def test_resolve_quarter(name, ry, expected):
    assert drpdata.resolve_quarter(name, ry) == expected


def test_resolve_quarter_rejects_garbage():
    assert drpdata.resolve_quarter("", 2026) == (None, None, None, None)
    assert drpdata.resolve_quarter("no interval here", 2026) == (None, None, None, None)
    assert drpdata.resolve_quarter("Jan - Mar/Yr9 - Qtr1", 2026) == (None, None, None, None)


def test_quarter_end_is_last_day_including_december():
    assert drpdata.resolve_quarter("Oct - Dec/Yr2 - Qtr4", 2026)[3] == "2026-12-31"
    assert drpdata.resolve_quarter("Jan - Mar/Yr2 - Qtr1", 2028)[3] == "2028-03-31"  # leap yr


# ---------------------------------------------------------------------------
# row builders
# ---------------------------------------------------------------------------

def test_offer_row_maps_type_and_practice_and_filters_other_plans():
    recs = _rows(OFFER_FIXTURE)
    built = [drpdata.offer_row(r, 2026, STATE_ABBREV, INTERVAL_NAMES, "t") for r in recs]
    assert built[-1] is None, "plan 13 (PRF) must not be treated as a DRP offer"
    rows = [b for b in built if b]
    assert len(rows) == 3

    az = rows[0]
    assert az[1] == 36005417
    assert az[2] == "0830" and az[3] == "83"
    assert az[4] == "04" and az[5] == "AZ"
    assert az[6] == "998", "DRP is statewide — county code is always 998"
    assert az[7] == "832" and az[8] == "Component"
    assert az[9] == "804" and az[10] == "104"
    assert (az[12], az[13], az[14], az[15]) == (2026, 3, "2026-07-01", "2026-09-30")

    ma = rows[1]
    assert (ma[5], ma[8], ma[9]) == ("MA", "Class", "802")
    assert (ma[12], ma[13]) == (2026, 1)

    wv = rows[2]
    assert (wv[5], wv[8]) == ("WV", "Class")
    assert (wv[12], wv[13]) == (2027, 2), "Yr3 must resolve to reinsurance_year + 1"


def test_offer_practice_code_is_interval_plus_700():
    for r in _rows(OFFER_FIXTURE):
        if r["Insurance Plan Code"] != "83":
            continue
        assert int(r["Practice Code"]) - int(r["Interval Code"]) == 700


def test_daily_price_row_component_and_class_are_mirror_images():
    comp, cls = [drpdata.daily_price_row(r, "t") for r in _rows(DAILY_FIXTURE)]

    # Component offer: class columns NULL, component columns populated.
    assert comp[0] == 2026 and comp[1] == "2026-04-01" and comp[2] == 36010017
    assert comp[3] == 909299
    assert comp[4] == pytest.approx(1.0967)          # loading factor
    assert comp[5:11] == (None,) * 6                  # m1..m3 class3, class4
    assert comp[17:20] == pytest.approx((1.9950, 2.0350, 2.0100))   # butter
    assert comp[20:23] == pytest.approx((1.8060, 1.7900, 1.7500))   # cheese
    assert comp[23:26] == pytest.approx((0.7053, 0.7100, 0.7000))   # dry whey
    assert comp[26:29] == pytest.approx((1.5562, 1.5263, 1.5095))   # NFDM
    assert comp[41] is None and comp[42] is None      # expected class3/class4
    assert comp[43] == pytest.approx(2.1630)          # expected butterfat
    assert comp[44] == pytest.approx(2.6578)          # expected protein
    assert comp[45] == pytest.approx(0.4515)          # expected other solids
    assert comp[46] == pytest.approx(1.2784)          # expected nonfat solids
    assert (comp[49], comp[50], comp[51]) == (11329, 67, 9)  # yield/actual/fmmo ids
    assert comp[52] == "2026-04-01" and comp[53] == "2025-04-30"

    # Class offer: the reverse.
    assert cls[0] == 2026 and cls[1] == "2026-04-01" and cls[2] == 35994534
    assert cls[5:8] == pytest.approx((18.8000, 18.8900, 18.9500))   # m1..m3 class3
    assert cls[8:11] == pytest.approx((19.7500, 19.5500, 19.4200))  # m1..m3 class4
    assert cls[17:29] == (None,) * 12, "component futures blank on a class offer"
    assert cls[41] == pytest.approx(18.8800) and cls[42] == pytest.approx(19.5700)
    assert cls[43:47] == (None,) * 4
    assert (cls[49], cls[50], cls[51]) == (11231, 66, 9)


def test_daily_price_sigmas_land_in_the_right_columns():
    comp, cls = [drpdata.daily_price_row(r, "t") for r in _rows(DAILY_FIXTURE)]
    # class sigmas (cols 11-16) are set on the class row and blank on the component row
    assert cls[11:14] == pytest.approx((0.1285, 0.1372, 0.1440))    # class3 sigma
    assert cls[14:17] == pytest.approx((0.1670, 0.1713, 0.1898))    # class4 sigma
    assert comp[11:17] == (None,) * 6
    # component sigmas (cols 29-40) are the reverse
    assert comp[29:32] == pytest.approx((0.1770, 0.1882, 0.1987))   # butter sigma
    assert comp[32:35] == pytest.approx((0.1503, 0.1509, 0.1554))   # cheese sigma
    assert comp[35:38] == pytest.approx((0.1617, 0.1722, 0.1815))   # dry whey sigma
    assert comp[38:41] == pytest.approx((0.1923, 0.2047, 0.2117))   # NFDM sigma
    assert cls[29:41] == (None,) * 12


def test_fmmo_component_prices_reproduce_from_the_futures_prices():
    """The strongest mapping check: rebuild RMA's four expected component prices from the
    monthly futures prices + the FMMO make allowances/yields (7 CFR 1000.50), per month
    then averaged over the quarter. If any column were mis-mapped this would not close."""
    comp = drpdata.daily_price_row(_rows(DAILY_FIXTURE)[0], "t")
    f = drpdata.fmmo_row(_rows(FMMO_FIXTURE)[0], "t")
    (butter_y, nfdm_y, whey_y, casein_y, chbf_y,
     bf_retention, bf_protein, butter_ma, nfdm_ma, whey_ma, cheese_ma) = f[2:13]
    R = lambda x: round(x, 4)

    bf_q = pr_q = os_q = nfs_q = 0.0
    for i in range(3):
        butter, cheese = comp[17 + i], comp[20 + i]
        whey, nfdm = comp[23 + i], comp[26 + i]
        bf = R((butter - butter_ma) * butter_y)
        cha = cheese - cheese_ma
        pr = R(R(cha * casein_y)
               + R((R(cha * chbf_y) - R(bf * bf_retention)) * bf_protein))
        bf_q += bf / 3
        pr_q += pr / 3
        os_q += R((whey - whey_ma) * whey_y) / 3
        nfs_q += R((nfdm - nfdm_ma) * nfdm_y) / 3

    assert R(bf_q) == pytest.approx(comp[43])   # expected butterfat  2.1630
    assert R(pr_q) == pytest.approx(comp[44])   # expected protein    2.6578
    assert R(os_q) == pytest.approx(comp[45])   # expected other sol. 0.4515
    assert R(nfs_q) == pytest.approx(comp[46])  # expected nonfat sol.1.2784


def test_actual_price_row_flags_settlement():
    settled, pending = [drpdata.actual_price_row(r, "t") for r in _rows(ACTUAL_FIXTURE)]
    assert settled[0] == 2025 and settled[1] == 61
    assert settled[2:5] == pytest.approx((1.7707, 1.6311, 1.6227))    # butter m1-m3
    assert settled[14] == pytest.approx(16.5700)                      # actual class III
    assert settled[15] == pytest.approx(21.1700)                      # actual class IV
    assert settled[16] == pytest.approx(1.7531)                       # actual butterfat
    assert settled[17] == pytest.approx(2.5740)                       # actual protein
    assert settled[18] == pytest.approx(0.3867)                       # actual other solids
    assert settled[19] == pytest.approx(1.6746)                       # actual nonfat solids
    assert settled[20] == 1, "settled flag"

    assert pending[1] == 62
    assert pending[14] is None and pending[16] is None
    assert pending[20] == 0, "a filed-but-unsettled quarter must not look settled"


def test_milk_yield_row():
    a, b = [drpdata.milk_yield_row(r, STATE_ABBREV, "t") for r in _rows(MILK_YIELD_FIXTURE)]
    assert a[:5] == (2027, 21721, "01", "AL", 5578.0)
    assert a[5] is None, "actual yield is NULL until the covered quarter has passed"
    assert a[6] == pytest.approx(129.3513)
    assert b[3] == "WI" and b[5] == pytest.approx(6100.0)


def test_fmmo_row_maps_every_factor():
    f = drpdata.fmmo_row(_rows(FMMO_FIXTURE)[0], "t")
    assert f[0] == 2026 and f[1] == 9
    assert f[2:13] == pytest.approx((1.2110, 0.9900, 1.0300, 1.3830, 1.5890, 0.9100,
                                     1.1700, 0.2272, 0.2393, 0.2668, 0.2519))
    assert f[13] == "2025-06-25" and f[14] == "2025-04-30"


def test_subsidy_row_filters_plan_and_deleted():
    built = [drpdata.subsidy_row(r, "t") for r in _rows(SUBSIDY_FIXTURE)]
    rows = [b for b in built if b]
    assert [(r[1], r[3]) for r in rows] == [
        (0.80, 0.55), (0.85, 0.49), (0.90, 0.44), (0.95, 0.44)]
    assert built[4] is None, "deleted 0.75 row must be dropped"
    assert built[5] is None, "plan 13 must be dropped"
    assert all(r[2] == "A" for r in rows)


# RY2019 — DRP's first year. SIX coverage levels, and an 18-field A00070 layout (RY2020+
# has 19: Range Low/High Count became Range Type Code + Range Low/High Value). Verbatim.
SUBSIDY_FIXTURE_2019 = "\n".join([
    "Record Type Code|Record Category Code|Reinsurance Year|Commodity Code|"
    "Unit Structure Code|Insurance Plan Code|Coverage Level Percent|Coverage Type Code|"
    "Deductible Amount|Endorsement Length Code|Endorsement Length Count|"
    "Insurance Option Code|Range Low Count|Range High Count|Subsidy Percent|"
    "Last Released Date|Released Date|Deleted Date",
    "A00070|04|2019|||83|0.70|A|||||||0.590||20180808|",
    "A00070|04|2019|||83|0.75|A|||||||0.550||20180808|",
    "A00070|04|2019|||83|0.80|A|||||||0.550||20180808|",
    "A00070|04|2019|||83|0.85|A|||||||0.490||20180808|",
    "A00070|04|2019|||83|0.90|A|||||||0.440||20180808|",
    "A00070|04|2019|||83|0.95|A|||||||0.440||20180808|",
])


def test_subsidy_survives_the_2019_to_2020_layout_drift():
    """A00070 gained a column after RY2019, so the loader must parse by column NAME.
    RY2019 also filed six coverage levels — a backtest spanning 2019 must not assume four."""
    got = {r[1]: r[3] for r in
           (drpdata.subsidy_row(x, "t") for x in _rows(SUBSIDY_FIXTURE_2019)) if r}
    assert got == {0.70: 0.59, 0.75: 0.55, 0.80: 0.55,
                   0.85: 0.49, 0.90: 0.44, 0.95: 0.44}


def test_plan_code_column_position_is_stable_across_layouts():
    """load_offers / load_subsidy stream-filter on a fixed field index to avoid building
    dicts for millions of ADM rows. That index must hold for every year we load."""
    for fixture, idx in ((SUBSIDY_FIXTURE, 5), (SUBSIDY_FIXTURE_2019, 5),
                         (OFFER_FIXTURE, 6)):
        header = fixture.splitlines()[0].split("|")
        assert header[idx] == "Insurance Plan Code"
        for line in fixture.splitlines()[1:]:
            fields = line.split("|")
            assert (fields[idx] == "83") == (fields[idx] == drpdata.DRP_PLAN_CODE)


def test_subsidy_matches_the_published_fact_sheet():
    """DRP fact sheet (JUNE 2025): 'Coverage Level % 80 85 90 95 /
    Premium Subsidy % 55 49 44 44'. The ADM must agree."""
    got = {r[1]: r[3] for r in
           (drpdata.subsidy_row(x, "t") for x in _rows(SUBSIDY_FIXTURE)) if r}
    assert got == {0.80: 0.55, 0.85: 0.49, 0.90: 0.44, 0.95: 0.44}
    assert 0.70 not in got and 0.75 not in got, "DRP has no 70/75% level"


# ---------------------------------------------------------------------------
# policy domains
# ---------------------------------------------------------------------------

def test_policy_domains_match_the_basic_provisions():
    assert drpdata.COVERAGE_LEVELS == (0.80, 0.85, 0.90, 0.95)
    assert drpdata.PROTECTION_FACTORS[0] == 1.00
    assert drpdata.PROTECTION_FACTORS[-1] == 1.50
    assert len(drpdata.PROTECTION_FACTORS) == 11
    assert drpdata.WEIGHTING_FACTORS[0] == 0.0 and drpdata.WEIGHTING_FACTORS[-1] == 1.0
    assert len(drpdata.WEIGHTING_FACTORS) == 21
    # 2026 widened these; the pre-2026 3.25-5.50 / 2.75-4.50 no longer apply.
    assert (drpdata.BUTTERFAT_TESTS[0], drpdata.BUTTERFAT_TESTS[-1]) == (4.00, 6.00)
    assert (drpdata.PROTEIN_TESTS[0], drpdata.PROTEIN_TESTS[-1]) == (3.20, 4.50)
    assert drpdata.PRICING_OPTIONS == {"831": "Class", "832": "Component"}


def test_declaration_space_counts():
    s = drpdata.declaration_space()
    assert s["per_pricing_option"] == 4 * 11 * 21 == 924
    assert s["per_state_quarter_salesdate"] == 1848
    assert s["per_state_salesdate_5q"] == 9240


# ---------------------------------------------------------------------------
# DB round-trip (in-memory; no network)
# ---------------------------------------------------------------------------

def test_schema_has_no_drp_county_table(conn):
    """DRP is sold statewide (county code 998), so availability is drp_state."""
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "drp_county" not in have
    assert {"drp_offer", "drp_state", "drp_daily_price", "drp_actual_price",
            "drp_milk_yield", "drp_fmmo_factor", "drp_subsidy", "drp_draw"} <= have
    assert "drp_rate" not in have, "DRP publishes no rate table — premium is simulated"


def test_offer_and_daily_price_upserts_are_idempotent(conn):
    offers = [r for r in (drpdata.offer_row(x, 2026, STATE_ABBREV, INTERVAL_NAMES, "t")
                          for x in _rows(OFFER_FIXTURE)) if r]
    sql = ("INSERT INTO drp_offer (reinsurance_year, offer_id, commodity_code, plan_code,"
           " state_code, state_abbrev, county_code, type_code, pricing_option,"
           " practice_code, interval_code, interval_name, quarter_year, quarter,"
           " quarter_start, quarter_end, deleted_date, source, fetched_at)"
           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
           " ON CONFLICT(reinsurance_year, offer_id) DO UPDATE SET"
           " state_abbrev=excluded.state_abbrev")
    for _ in range(3):
        conn.executemany(sql, offers)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM drp_offer").fetchone()[0] == 3


def test_actual_price_upsert_never_unsettles_a_settled_quarter(conn):
    settled, pending = [drpdata.actual_price_row(r, "t") for r in _rows(ACTUAL_FIXTURE)]
    # force both onto the same key so the guard is what decides
    pending = (settled[0], settled[1]) + pending[2:]
    cols = ("reinsurance_year, actual_price_id, m1_butter, m2_butter, m3_butter, "
            "m1_cheese, m2_cheese, m3_cheese, m1_dry_whey, m2_dry_whey, m3_dry_whey, "
            "m1_nfdm, m2_nfdm, m3_nfdm, actual_class3, actual_class4, actual_butterfat, "
            "actual_protein, actual_other_solids, actual_nonfat_solids, settled, "
            "released_date, filing_date, source, fetched_at")
    sql = (f"INSERT INTO drp_actual_price ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, actual_price_id) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "actual_price_id"))
           + " WHERE excluded.settled >= drp_actual_price.settled")
    conn.execute(sql, settled)
    conn.execute(sql, pending)      # a later, still-blank republication
    conn.commit()
    row = conn.execute("SELECT actual_class3, settled FROM drp_actual_price").fetchone()
    assert row["actual_class3"] == pytest.approx(16.57)
    assert row["settled"] == 1


def test_subsidy_schedule_accessor(conn):
    rows = [r for r in (drpdata.subsidy_row(x, "t") for x in _rows(SUBSIDY_FIXTURE)) if r]
    conn.executemany(
        "INSERT INTO drp_subsidy (reinsurance_year, coverage_level, coverage_type_code,"
        " subsidy_pct, source, fetched_at) VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    assert drpdata.subsidy_schedule(conn, 2026) == {
        0.80: 0.55, 0.85: 0.49, 0.90: 0.44, 0.95: 0.44}
    assert drpdata.subsidy_schedule(conn, 2019) == {}


def test_parse_years():
    assert drpdata._parse_years(None, 2026) == [2026]
    assert drpdata._parse_years("2019-2022", 2026) == [2019, 2020, 2021, 2022]
    assert drpdata._parse_years("2025,2027", 2026) == [2025, 2027]
