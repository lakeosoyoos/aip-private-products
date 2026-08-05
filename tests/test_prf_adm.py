"""Unit tests for the prf_adm parsing/mapping helpers — no network, no big downloads."""
from __future__ import annotations

import io

from src.connectors import prf_adm


COUNTY_NAME = {"46025": "Day", "48365": "Panola", "15001": "Hawaii"}
STATE_ABBREV = {"46": "SD", "48": "TX", "15": "HI"}


def _row(commodity="0088", plan="13", state="46", county="025", use="030",
         irr="003", org="997", cbv="322.00", deleted="") -> dict[str, str]:
    """One Price-record dict as parse_pipe_table would yield it."""
    return {
        "Commodity Code": commodity, "Insurance Plan Code": plan,
        "State Code": state, "County Code": county, "Intended Use Code": use,
        "Irrigation Practice Code": irr, "Organic Practice Code": org,
        "County Base Value": cbv, "Deleted Date": deleted,
    }


# ---------------------------------------------------------------------------
# code -> string maps
# ---------------------------------------------------------------------------

def test_use_map():
    assert prf_adm.map_use("007") == "Grazing"
    assert prf_adm.map_use("030") == "Haying"
    assert prf_adm.map_use("7") == "Grazing"          # zero-pad tolerant
    assert prf_adm.map_use("016") is None             # Grain -> dropped
    assert prf_adm.map_use("026") is None             # Silage -> dropped


def test_irrigation_map():
    assert prf_adm.map_irrigation("002") == "Irrigated"
    assert prf_adm.map_irrigation("003") == "Non-Irrigated"
    # Grazing carries 997 (no irrigated/non-irrigated split) -> Non-Irrigated.
    assert prf_adm.map_irrigation("997") == "Non-Irrigated"
    assert prf_adm.map_irrigation("001") is None


def test_organic_map():
    assert prf_adm.map_organic("997") == "Conventional"
    assert prf_adm.map_organic("001") == "Organic"
    assert prf_adm.map_organic("002") == "Transitional"
    assert prf_adm.map_organic("") == "Conventional"   # unknown defaults conventional


# ---------------------------------------------------------------------------
# build_prf_rows: filtering, mapping, aggregation
# ---------------------------------------------------------------------------

def test_excludes_apiculture_annual_forage_and_wrong_plan():
    rows = [
        _row(commodity="1191"),           # Apiculture -> out
        _row(commodity="0332"),           # Annual Forage -> out
        _row(plan="02"),                  # not PRF plan -> out
        _row(),                           # keeper
    ]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert len(out) == 1
    assert out[0][2] == "46025"


def test_grazing_maps_to_non_irrigated_and_conventional():
    rows = [_row(use="007", irr="997", org="997", cbv="47.30")]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    (year, state, fips, cname, use, irr, org, cbv, source, _) = out[0]
    assert (use, irr, org) == ("Grazing", "Non-Irrigated", "Conventional")
    assert (year, state, fips, cname, cbv, source) == (
        2026, "SD", "46025", "Day", 47.30, "adm_2026_ytd")


def test_organic_certified_yields_distinct_row():
    # Real 2026 shape: 46025 Haying Non-Irrigated — Organic CBV higher than Conventional.
    rows = [
        _row(use="030", irr="003", org="997", cbv="322.00"),   # Conventional
        _row(use="030", irr="003", org="001", cbv="386.00"),   # Organic (certified)
        _row(use="030", irr="003", org="002", cbv="322.00"),   # Transitional
    ]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    by_org = {r[6]: r[7] for r in out}
    assert by_org == {"Conventional": 322.00, "Organic": 386.00, "Transitional": 322.00}


def test_grid_rows_collapse_to_one_via_median():
    # Sub-county (grid) rows repeat the same county key; a constant CBV collapses to itself.
    rows = [_row(cbv="200.00") for _ in range(5)]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert len(out) == 1 and out[0][7] == 200.00

    # Genuinely grid-priced county (Hawaii grazing): median of the grid values.
    hi = [_row(state="15", county="001", use="007", irr="997", cbv=f"{v:.2f}")
          for v in (10.0, 20.0, 60.0)]
    out2 = prf_adm.build_prf_rows(hi, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert len(out2) == 1 and out2[0][7] == 20.00


def test_drops_deleted_and_nonpositive_and_blank_cbv():
    rows = [
        _row(deleted="20250101"),         # deleted -> out
        _row(cbv=""),                     # blank CBV -> out
        _row(cbv="0.00"),                 # non-positive -> out
        _row(cbv="-5.00"),                # negative -> out
        _row(county="026", cbv="150.00"), # keeper
    ]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert len(out) == 1 and out[0][2] == "46026" and out[0][7] == 150.00


def test_grazing_below_haying_same_county():
    rows = [
        _row(use="007", irr="997", org="997", cbv="47.30"),    # Grazing
        _row(use="030", irr="003", org="997", cbv="322.00"),   # Haying Non-Irr
    ]
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    cbv = {r[4]: r[7] for r in out}
    assert cbv["Grazing"] < cbv["Haying"]


# ---------------------------------------------------------------------------
# iter_price_prf_rows: positional prefilter of the big Price file
# ---------------------------------------------------------------------------

def test_iter_price_prefilters_to_prf(tmp_path):
    header = "|".join([
        "Commodity Code", "Insurance Plan Code", "State Code", "County Code",
        "Intended Use Code", "Irrigation Practice Code", "Organic Practice Code",
        "County Base Value", "Deleted Date"])
    lines = [
        header,
        "0088|13|46|025|030|003|997|322.00|",   # PRF -> yielded
        "1191|13|46|025|030|003|997|9.99|",     # apiculture same plan -> skipped
        "0041|02|19|001|016|003|997|500.00|",   # corn -> skipped
        "0088|13|48|365|007|997|997|60.00|",    # PRF grazing -> yielded
    ]
    p = tmp_path / "price.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    got = list(prf_adm.iter_price_prf_rows(p))
    assert len(got) == 2
    assert {r["State Code"] + r["County Code"] for r in got} == {"46025", "48365"}
    # Feed straight into build_prf_rows end-to-end.
    out = prf_adm.build_prf_rows(got, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert {r[4] for r in out} == {"Haying", "Grazing"}


def test_iter_price_column_order_independent(tmp_path):
    # Header with the needed columns in a different order and extra columns interleaved.
    header = "|".join([
        "Record Type Code", "Insurance Plan Code", "Commodity Code", "State Code",
        "County Code", "Intended Use Code", "Irrigation Practice Code",
        "Organic Practice Code", "Some Other Field", "County Base Value", "Deleted Date"])
    p = tmp_path / "price.txt"
    p.write_text(header + "\n" + "A00810|13|0088|46|025|030|003|997|xx|322.00|\n",
                 encoding="utf-8")
    got = list(prf_adm.iter_price_prf_rows(p))
    assert len(got) == 1 and got[0]["County Base Value"] == "322.00"


def test_parse_pipe_table_roundtrip_into_build():
    # parse_pipe_table (borrowed from rma_adm) -> build_prf_rows, exercising the dict path.
    from src.connectors.rma_adm import parse_pipe_table
    text = (
        "Commodity Code|Insurance Plan Code|State Code|County Code|Intended Use Code|"
        "Irrigation Practice Code|Organic Practice Code|County Base Value|Deleted Date\n"
        "0088|13|46|025|030|002|997|450.00|\n"
    )
    rows = list(parse_pipe_table(io.StringIO(text)))
    out = prf_adm.build_prf_rows(rows, COUNTY_NAME, STATE_ABBREV, 2026, "adm_2026_ytd")
    assert out[0][5] == "Irrigated" and out[0][7] == 450.00
