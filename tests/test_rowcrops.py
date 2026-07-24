"""rowcrops matching: commodity codes and free-text keywords."""
from src import rowcrops


def test_row_crop_codes():
    assert rowcrops.is_row_crop_code("0041")          # corn
    assert rowcrops.is_row_crop_code("41")            # zero-padding tolerated
    assert rowcrops.crop_for_code("0081") == "Soybeans"
    assert not rowcrops.is_row_crop_code("0211")      # not a row crop
    assert rowcrops.crop_for_code("9999") is None


def test_keyword_matching():
    text = "Supplemental hail coverage for corn and soybeans in the Midwest."
    crops = rowcrops.match_crops(text)
    assert "Corn" in crops and "Soybeans" in crops
    assert "Wheat" not in crops


def test_generic_rowcrop_phrase():
    assert rowcrops.mentions_row_crops("Covers all row crops in the county.")
    assert not rowcrops.mentions_row_crops("Covers apples and cherries.")


def test_extra_crops_config():
    crops = rowcrops.match_crops("Coverage for triticale acres.", extra=["Triticale"])
    assert "Triticale" in crops
