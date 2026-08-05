"""deepen.py: the deny-list / allow-lexicon filter is the whole ballgame - if it lets
administrative filing titles through, the review CSV fills with junk products. These tests pin the
rejection of admin titles, the recovery of real product cores from decorated titles, dedup against
the existing catalog (incl. the short-token safety rule), and the brochure prose guard."""
from src import db, deepen, models


# --------------------------------------------------------------------------- deny / admin titles
def test_pure_admin_titles_are_rejected():
    # None of these name a product: filing-type words, bare years, glued admin blobs, endorsement #.
    for title in [
        "Rate Filing", "2024 IL Form Filing", "RRF", "2024-IA Rate, Rule & Form Filing",
        "2026", "2020STPFILING", "IACHFILING2021", "IASTPFORMFILING2021",
        "endorsement 457", "2025 MN rate page correction", "2026 MN Form Logo Update",
        "Policy Jacket filing", "Form Filing Fee",
    ]:
        name, conf = deepen.product_from_filing(title)
        assert name is None, f"admin title leaked a product: {title!r} -> {name!r}"


def test_crop_hail_refile_titles_yield_the_clean_core_not_the_messy_string():
    # "Crop Hail Forms" / "...Rates, Rules and Forms" are administrative re-files of the Crop Hail
    # PRODUCT: we recover the clean core "Crop Hail" (deduped downstream for AIPs that already list
    # it) and never emit the decorated filing string itself.
    for title in ["Crop Hail Forms", "Crop Hail Rates, Rules and Forms"]:
        assert deepen.product_from_filing(title)[0] == "Crop Hail"


def test_admin_decoration_is_stripped_to_the_product_core():
    # "2022 Crop Hail - F" is an admin re-file title; we must NOT emit the messy string. We emit the
    # clean core "Crop Hail" (which then dedups away for AIPs that already list Crop Hail).
    name, conf = deepen.product_from_filing("2022 Crop Hail - F")
    assert name == "Crop Hail"
    name, conf = deepen.product_from_filing("2026 IL NP-Replant F (NEW)")
    assert name == "Named Peril Replant"


def test_real_products_are_recovered():
    cases = {
        "Magnum Yield Protection": "Magnum Yield Protection",
        "2026 IA Revenue Boost R/F (NEW)": "Revenue Boost",
        "2026 IA PECO": "Personal Enhanced Coverage Option (PECO)",
        "RPowerD": "RPowerD",
        "APCO & REVCO FORM": "APCO",
        "2011 BYA Form Filing": "Biotech Yield Assurance",
        "PRODUCTION COST INSURANCE POLICY": "Production Cost Insurance Policy",
        "2021 IA Select Programs": "Select Programs",
        "2016 TRC Buy up endorsement": "Total Revenue Coverage",
    }
    for title, expected in cases.items():
        name, conf = deepen.product_from_filing(title)
        assert name == expected, f"{title!r} -> {name!r}, expected {expected!r}"
        assert conf in ("high", "low")


def test_confidence_high_for_named_products():
    assert deepen.product_from_filing("Magnum Yield Protection")[1] == "high"
    # a bare peril re-file is low confidence (could be an endorsement / variant)
    assert deepen.product_from_filing("2026 MN NP-Fire RRF (NEW)")[1] == "low"


# --------------------------------------------------------------------------- normalization
def test_normalize_strips_year_state_and_filing_codes():
    assert deepen.normalize_title("2026 IA Crop Hail RRF") == "crop hail"
    assert deepen.normalize_title("2025 MN AAIC Rate/Rule Filing") == ""
    assert deepen.normalize_title("2024-IN Rate, Rule & Form Filing") == ""


# --------------------------------------------------------------------------- dedup
def test_dedup_against_existing_catalog():
    existing = {"WN": {deepen.norm_key("Crop Hail"), deepen.norm_key("BAND"), "band"}}
    # already catalogued -> duplicate
    assert deepen._is_dup("Crop Hail", existing["WN"]) is True
    # genuinely new -> not a duplicate
    assert deepen._is_dup("Magnum Yield Protection", existing["WN"]) is False


def test_short_existing_token_does_not_swallow_longer_names():
    # The short existing token 'band' must NOT dedup a distinct longer product that merely contains
    # those four letters (the bug that hid Revenue Band & Yield Band Coverage).
    existing = {"band", deepen.norm_key("BAND")}
    assert deepen._is_dup("Revenue Band & Yield Band Coverage", existing) is False


def test_acronym_and_substring_dedup_catch_variants():
    # "MyECO" is part of the catalogued "MyECO and MySCO"; VIP acronym matches its expansion.
    existing = {deepen.norm_key("MyECO and MySCO"), deepen.norm_key("Variable Interval Product"),
                "vip"}
    assert deepen._is_dup("MyECO", existing) is True
    assert deepen._is_dup("Variable Interval Product (VIP)", existing) is True


# --------------------------------------------------------------------------- brochure prose guard
def test_brochure_prose_is_not_a_product():
    # descriptive copy that merely contains a peril word must be rejected
    assert deepen._heading_to_product("Adverse weather conditions") == (None, "")
    assert deepen._heading_to_product("How Tomato Named Peril Insurance Works") == (None, "")
    assert deepen._heading_to_product("Fire") == (None, "")  # bare peril label
    # a real branded product heading is kept
    assert deepen._heading_to_product("eZ-Hail")[0] == "eZ-Hail"
    assert deepen._heading_to_product("MyYield Max")[0] == "MyYield Max"


# --------------------------------------------------------------------------- classification
def test_classify_candidate_assigns_peril_and_coverage():
    peril, coverage, layer = deepen.classify_candidate("Grain Fire (Named Peril)", "2026 Grain Fire")
    assert peril == "fire"
    peril, coverage, layer = deepen.classify_candidate("Personal Enhanced Coverage Option (PECO)")
    assert coverage == "supplemental"


# --------------------------------------------------------------------------- end-to-end + import path
def _seed_conn():
    c = db.connect(":memory:")
    db.init_db(c)
    # one existing product so dedup has something to hit
    models.upsert_product(c, models.Product(
        bucket="private", program="private_nonreinsured", name="Crop Hail",
        source_type="aip_site", aip_code="PS"))
    # a real product filing + an admin filing for the same AIP
    c.executemany(
        """INSERT INTO serff_filings (serff_tracking_number, state, aip_code, product_name)
           VALUES (?,?,?,?)""",
        [("PALO-1", "IA", "PS", "2026 IA Revenue Boost R/F (NEW)"),
         ("PALO-2", "IL", "PS", "2026 IL Form Filing"),
         ("PALO-3", "IA", "PS", "2026 IA Crop Hail RRF")])  # dups existing Crop Hail
    c.commit()
    return c


def test_build_candidates_end_to_end():
    c = _seed_conn()
    final, serff_ok, broch_ok, serff_rej, broch_rej = deepen.build_candidates(c)
    names = {cand.name for cand in final if cand.aip_code == "PS"}
    assert "Revenue Boost" in names          # real product surfaced
    assert "Crop Hail" not in names          # deduped against existing catalog
    # the pure Form Filing title was rejected outright
    assert any(t == "2026 IL Form Filing" for _, t in serff_rej)


def test_candidates_import_cleanly_as_products():
    """A reviewer imports selected candidate rows via models.upsert_product; verify a candidate maps
    to a valid Product and upserts idempotently (mirrors the manual-seed import path)."""
    c = _seed_conn()
    final, *_ = deepen.build_candidates(c)
    cand = next(x for x in final if x.name == "Revenue Boost")
    p = models.Product(
        bucket="private", program="private_nonreinsured", name=cand.name, aip_code=cand.aip_code,
        source_type="serff", peril_type=cand.peril_type, coverage_type=cand.coverage_type,
        filing_id=cand.evidence, notes="imported from derived_products_candidates.csv")
    id1 = models.upsert_product(c, p)
    id2 = models.upsert_product(c, p)
    assert id1 == id2
    row = c.execute("SELECT name, aip_code FROM products WHERE product_id=?", (id1,)).fetchone()
    assert row["name"] == "Revenue Boost" and row["aip_code"] == "PS"
