"""Classifier tests — the stack layers must be assigned by rule, never forced."""
from src.stack import classify


def test_private_band_analogs():
    assert classify("ECO+", "private", "private_nonreinsured", None, None) == ("private_band", "ECO")
    assert classify("MyECO and MySCO", "private", "private_nonreinsured", None, None)[0] == "private_band"
    assert classify("MyMCO", "private", "private_nonreinsured", None, None) == ("private_band", "MCO")
    assert classify("Great American Plus (GAP)", "private", "private_nonreinsured",
                    "revenue", "supplemental") == ("private_band", "ECO")
    assert classify("Personal Enhanced Coverage Option (PECO)", "private",
                    "private_nonreinsured", None, "supplemental") == ("private_band", "ECO")


def test_named_peril_and_endorsement():
    assert classify("Crop Hail", "private", "private_nonreinsured", "hail", "named-peril")[0] == "named_peril"
    assert classify("Green Snap", "private", "private_nonreinsured", "wind", None)[0] == "named_peril"
    assert classify("Replant Premier", "private", "private_nonreinsured", "replant", None)[0] == "endorsement"
    assert classify("Extra Harvest Expense", "private", "private_nonreinsured", None, None)[0] == "endorsement"


def test_federal_layers():
    assert classify("Supplemental Coverage Option (SCO)", "508h", "federal_farm_bill",
                    None, None) == ("federal_band", "SCO")
    assert classify("Enhanced Coverage Option (ECO)", "508h", "federal_508h",
                    None, None) == ("federal_band", "ECO")
    assert classify("Post-Application Coverage Endorsement (PACE)", "508h", "federal_508h",
                    None, "endorsement")[0] == "federal_endorsement"
    assert classify("Margin Protection (MP)", "508h", "federal_508h", None, None)[0] == "federal_plan"


def test_unmatched_stays_other():
    assert classify("Contingent Business Interruption", "private", "private_nonreinsured",
                    None, None)[0] == "other"
