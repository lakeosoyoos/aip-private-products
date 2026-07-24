"""Unit tests for the rma_adm parsing helpers — no network, no big downloads."""
from __future__ import annotations

import io
import zipfile

import pytest

from src.connectors import rma_adm


# ---------------------------------------------------------------------------
# zip plumbing
# ---------------------------------------------------------------------------

def _make_zip(members: dict[str, bytes], compress=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compress) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _range_zip(blob: bytes) -> rma_adm.RangeZip:
    return rma_adm.RangeZip(len(blob), lambda s, e: blob[s:e + 1])


def test_parse_eocd_and_central_directory():
    blob = _make_zip({"2026_A00030_InsuranceOffer_YTD.txt": b"a|b\n1|2\n" * 100,
                      "2026_A00520_State_YTD.txt": b"x" * 10})
    n, cd_size, cd_offset = rma_adm.parse_eocd(blob[-1000:] if len(blob) > 1000 else blob)
    # offsets from a truncated tail are relative to the blob, so re-run on full blob
    n, cd_size, cd_offset = rma_adm.parse_eocd(blob)
    assert n == 2
    members = rma_adm.parse_central_directory(blob[cd_offset:cd_offset + cd_size])
    assert set(members) == {"2026_A00030_InsuranceOffer_YTD.txt",
                            "2026_A00520_State_YTD.txt"}
    m = members["2026_A00520_State_YTD.txt"]
    assert m.usize == 10


def test_parse_eocd_rejects_non_zip():
    with pytest.raises(ValueError):
        rma_adm.parse_eocd(b"this is not a zip file at all")


@pytest.mark.parametrize("compress", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
def test_rangezip_extract_roundtrip(tmp_path, compress):
    payload = b"Record Type Code|State Code\nA00520|19\n" * 500
    blob = _make_zip({"2026_A00520_State_YTD.txt": payload}, compress)
    rz = _range_zip(blob)
    member = rz.find("A00520_State")
    out = rz.extract(member, tmp_path / "state.txt")
    assert out.read_bytes() == payload


def test_rangezip_find_missing():
    blob = _make_zip({"foo.txt": b"x"})
    with pytest.raises(KeyError):
        _range_zip(blob).find("A00030_InsuranceOffer")


# ---------------------------------------------------------------------------
# pipe-table parsing + plan/crop mapping
# ---------------------------------------------------------------------------

def test_parse_pipe_table():
    rows = list(rma_adm.parse_pipe_table(
        ["A|B|C\n", "1|2|3\n", "\n", "4|5|6"]))
    assert rows == [{"A": "1", "B": "2", "C": "3"}, {"A": "4", "B": "5", "C": "6"}]


def test_split_plan_codes():
    assert rma_adm.split_plan_codes("31;32;33") == ["31", "32", "33"]
    assert rma_adm.split_plan_codes("1; 2") == ["01", "02"]
    assert rma_adm.split_plan_codes(None) == []
    assert rma_adm.split_plan_codes("") == []


def test_plan_map_supplements_and_skips():
    products = [
        {"product_id": 3, "name": "Supplemental Coverage Option (SCO)",
         "plan_code": "31;32;33"},
        {"product_id": 8, "name": "Margin Coverage Option (MCO)", "plan_code": None},
        {"product_id": 9, "name": "Trend-Adjusted APH Yield Endorsement (TA-APH)",
         "plan_code": None},
    ]
    plan_to_pid, skipped = rma_adm.plan_map_for_products(products)
    assert plan_to_pid["31"] == 3 and plan_to_pid["33"] == 3
    assert plan_to_pid["67"] == 8 and plan_to_pid["69"] == 8   # MCO supplement
    assert skipped == ["Trend-Adjusted APH Yield Endorsement (TA-APH)"]


def test_crop_for_offer_row_crop_gate_and_relabels():
    crops = {(1, "Corn"), (1, "Spring Wheat"), (3, "Wheat"), (7, "All crops (whole-farm)")}
    # normal row crop
    assert rma_adm.crop_for_offer(3, "31", "0041", crops) == "Corn"
    # non-row-crop commodity dropped (0054 = apples)
    assert rma_adm.crop_for_offer(3, "31", "0054", crops) is None
    # ADM-verified codes, where src/rowcrops.py is wrong: 0075 = Peanuts, 0094 = Rye,
    # 0332 = Annual Forage (dropped), 0107 = Alfalfa Seed (dropped)
    assert rma_adm.crop_for_offer(3, "31", "0075", crops) == "Peanuts"
    assert rma_adm.crop_for_offer(3, "31", "0094", crops) == "Rye"
    assert rma_adm.crop_for_offer(3, "31", "0332", crops) is None
    assert rma_adm.crop_for_offer(3, "31", "0107", crops) is None
    # Spring Wheat relabel only for products without plain Wheat
    assert rma_adm.crop_for_offer(1, "16", "0011", crops) == "Spring Wheat"
    assert rma_adm.crop_for_offer(3, "31", "0011", crops) == "Wheat"
    # WFRP pseudo-crop; Micro Farm ignored
    assert rma_adm.crop_for_offer(7, "76", "0076", crops) == "All crops (whole-farm)"
    assert rma_adm.crop_for_offer(7, "76", "9110", crops) is None


def _offer(plan, commodity, state, county, deleted=""):
    return {"Insurance Plan Code": plan, "Commodity Code": commodity,
            "State Code": state, "County Code": county, "Deleted Date": deleted}


def test_build_county_rows_dedup_fips_and_names():
    plan_to_pid = {"31": 3, "32": 3}
    crops = {(3, "Corn")}
    offers = [
        _offer("31", "0041", "19", "169"),   # Story IA, SCO-YP
        _offer("32", "0041", "19", "169"),   # same county via SCO-RP -> dedup
        _offer("31", "0041", "1", "1"),      # unpadded codes -> 01001
        _offer("31", "0054", "19", "169"),   # apples -> dropped
        _offer("99", "0041", "19", "169"),   # unknown plan -> dropped
        _offer("31", "0041", "19", "001", deleted="20250101"),  # deleted -> dropped
    ]
    rows = rma_adm.build_county_rows(
        offers, plan_to_pid, crops,
        state_abbrev={"19": "IA", "01": "AL"},
        county_name={"19169": "Story", "01001": "Autauga"},
        source="adm_2026_ytd")
    assert rows == [
        (3, "Corn", "IA", "19169", "Story", "adm_2026_ytd"),
        (3, "Corn", "AL", "01001", "Autauga", "adm_2026_ytd"),
    ]
