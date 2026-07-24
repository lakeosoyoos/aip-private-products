"""enrich extraction functions: crops (row + specialty), states (incl. ZIP false
positive), peril/coverage fill."""
from src import enrich


def test_crop_extraction_specialty_and_row():
    text = ("Coverage is available for citrus, wine grapes, processing tomatoes, "
            "corn and soybeans in select counties.")
    crops = enrich.extract_crops(text)
    assert {"Citrus", "Grapes", "Tomatoes", "Corn", "Soybeans"} <= set(crops)
    assert "Wheat" not in crops


def test_seed_corn_masked_from_row_crop_pass():
    crops = enrich.extract_crops("Protection designed specifically for seed corn growers.")
    assert "Seed Corn" in crops
    assert "Corn" not in crops          # "seed corn" must not double-tag plain Corn
    # ...but a doc naming both still gets both.
    both = enrich.extract_crops("Covers field corn and seed corn acres.")
    assert {"Corn", "Seed Corn"} <= set(both)


def test_state_extraction_ignores_zip_address_lines():
    text = ("This endorsement is offered in Iowa, Minnesota and South Dakota.\n"
            "Home Office: 123 Main Street, Madison, Wisconsin 53703")
    states, nationwide = enrich.extract_states(text)
    assert states == ["IA", "MN", "SD"]   # Wisconsin sits on a ZIP-coded address line
    assert not nationwide


def test_state_abbreviation_lists_and_nationwide():
    states, nw = enrich.extract_states("Available in IA, IL, NE and MN for the 2026 crop year.")
    assert set(states) == {"IA", "IL", "NE", "MN"} and not nw
    # Oxford ", and" before the last code must not drop it.
    states_ox, _ = enrich.extract_states("Available in AZ, CO, WI, and WY.")
    assert set(states_ox) == {"AZ", "CO", "WI", "WY"}
    # A lone two-letter word must not match ("IN" the preposition, capitalized headers).
    states2, _ = enrich.extract_states("COVERAGE IN EVERY COUNTY")
    assert states2 == []
    states3, nw3 = enrich.extract_states("This product is available nationwide.")
    assert states3 == [] and nw3
    # "West Virginia" must not also yield Virginia.
    states4, _ = enrich.extract_states("Sold in West Virginia only.")
    assert states4 == ["WV"]


def test_scope_to_product_on_shared_listing_page():
    text = ("Our Coverages\n"
            "Tobacco Theft (TT)\n"
            "Covers theft of harvested tobacco.\n"
            "Availability: Kentucky and Tennessee\n"
            "Winter Wheat Replant (WW)\n"
            "Covers replanting winter wheat.\n"
            "Availability: Oregon and Washington\n")
    scoped = enrich.scope_to_product(text, "Tobacco Theft (TT)",
                                     ["Winter Wheat Replant (WW)"])
    crops = enrich.extract_crops(scoped)
    states, _ = enrich.extract_states(scoped)
    assert crops == ["Tobacco"] and states == ["KY", "TN"]   # sibling's WA/OR/wheat excluded
    # Name absent from the doc -> whole text returned (no guessing about sections).
    assert enrich.scope_to_product(text, "Not On Page", ["Tobacco Theft (TT)"]) == text


def test_peril_and_coverage_fill():
    assert enrich.extract_peril("Crop Hail Advantage", "") == "hail"
    assert enrich.extract_peril("Freeze Protection", "") == "freeze"
    assert enrich.extract_peril("Mystery Product", "Covers loss caused by wind events.") == "wind"
    assert enrich.extract_peril("Mystery Product", "No perils named here.") is None
    assert enrich.extract_coverage("", "An endorsement to your underlying MPCI policy.") == "endorsement"
    assert enrich.extract_coverage("", "Nothing relevant.") is None
