"""Unit tests for the pure parsing helpers in src/connectors/serff_browser.py.

No live browser here — these exercise the HTML parsers against captured PrimeFaces
markup shaped exactly like filingaccess.serff.com renders it.
"""
from src.connectors.serff_browser import (
    looks_blocked,
    parse_filing_summary,
    parse_paginator,
    parse_results_rows,
    to_iso_date,
)

RESULTS_HTML = """
<table><thead><tr role="row"><th>Company Name</th></tr></thead><tbody>
<tr data-ri="0" data-rk="130421454" class="ui-widget-content ui-datatable-even ui-datatable-selectable" role="row" aria-selected="false">
<td role="gridcell">Farmers Mutual Hail Insurance Company of Iowa</td>
<td role="gridcell">13897</td>
<td role="gridcell">2016 Iowa Added Value Protection Rate Filing</td>
<td role="gridcell">02.1001 Crop-Hail Non-Federally Reinsured Only</td>
<td role="gridcell">Rate/Rule</td>
<td role="gridcell">Closed - Approved</td>
<td role="gridcell">FMHL-130421454</td>
</tr>
<tr data-ri="1" data-rk="134018253" class="ui-widget-content ui-datatable-odd ui-datatable-selectable" role="row">
<td>Palomar Specialty Insurance Company</td><td>20338</td>
<td>2024-IA Rate, Rule &amp; Form Filing</td>
<td>02.1001 Crop-Hail Non-Federally Reinsured Only</td>
<td>Form/Rate/Rule</td><td>Closed - Approved</td><td>PALO-134018253</td>
</tr>
</tbody></table>
<span class="ui-paginator-current">(1 of 8)</span>
"""

SUMMARY_HTML = """
<div class="row"><label class="col-sm-5 text-right">Product Name: </label><div class="col-sm-7">2016 Iowa Added Value Protection Rate Filing</div></div>
<div class="row"><label class="col-sm-5 text-right">Type Of Insurance: </label><div class="col-sm-7">02.1 Crop</div></div>
<div class="row"><label class="col-sm-5 text-right">Sub Type Of Insurance: </label><div class="col-sm-7">02.1001 Crop-Hail Non-Federally Reinsured Only</div></div>
<div class="row"><label class="col-sm-5 text-right">Filing Type: </label><div class="col-sm-7">Rate/Rule</div></div>
<div class="row"><label class="col-sm-5 text-right">SERFF Tracking Number: </label><div class="col-sm-7">FMHL-130421454</div></div>
<div class="row"><label class="col-sm-5 text-right">Submission Date: </label>
    <div class="col-sm-7">1/28/16
    </div></div>
<div class="row"><label class="col-sm-5 text-right">Filing Status: </label><div class="col-sm-7">Closed - Approved</div></div>
<div class="row"><label class="col-sm-5 text-right">SERFF Status: </label><div class="col-sm-7">Closed</div></div>
<div class="row"><label class="col-sm-5 text-right">Disposition Date: </label><div class="col-sm-7">02/12/2016</div></div>
<div class="row"><label class="col-sm-5 text-right">Disposition Status: </label><div class="col-sm-7">Approved</div></div>
"""


def test_parse_results_rows():
    rows = parse_results_rows(RESULTS_HTML)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["filing_id"] == "130421454"
    assert r0["company_name"] == "Farmers Mutual Hail Insurance Company of Iowa"
    assert r0["naic_company_code"] == "13897"
    assert r0["sub_toi"] == "02.1001 Crop-Hail Non-Federally Reinsured Only"
    assert r0["filing_type"] == "Rate/Rule"
    assert r0["filing_status"] == "Closed - Approved"
    assert r0["serff_tracking_number"] == "FMHL-130421454"
    # HTML entities are decoded
    assert rows[1]["product_name"] == "2024-IA Rate, Rule & Form Filing"


def test_parse_results_rows_empty():
    assert parse_results_rows("<table><tbody><tr><td>No records found.</td></tr></tbody></table>") == []


def test_parse_paginator():
    assert parse_paginator(RESULTS_HTML) == (1, 8)
    assert parse_paginator('<span class="ui-paginator-current">(3 of 12)</span>') == (3, 12)
    assert parse_paginator("<p>no paginator here</p>") is None


def test_parse_filing_summary():
    d = parse_filing_summary(SUMMARY_HTML)
    assert d["product_name"] == "2016 Iowa Added Value Protection Rate Filing"
    assert d["toi"] == "02.1 Crop"
    assert d["sub_toi"] == "02.1001 Crop-Hail Non-Federally Reinsured Only"
    assert d["serff_tracking_number"] == "FMHL-130421454"
    assert d["submission_date"] == "1/28/16"      # whitespace inside the cell is normalized
    assert d["disposition_date"] == "02/12/2016"
    assert d["disposition_status"] == "Approved"
    assert d["serff_status"] == "Closed"


def test_to_iso_date():
    assert to_iso_date("1/28/16") == "2016-01-28"
    assert to_iso_date("02/12/2016") == "2016-02-12"
    assert to_iso_date("12/18/24") == "2024-12-18"
    assert to_iso_date("") is None
    assert to_iso_date(None) is None
    assert to_iso_date("not a date") is None
    assert to_iso_date("13/45/2020") is None


def test_looks_blocked():
    assert looks_blocked("Please complete the reCAPTCHA to continue")
    # The AWS-WAF-style interstitial the portal actually serves under load:
    assert looks_blocked(
        "Let's confirm you are human. Complete the security check before continuing. "
        "This step verifies that you are not a bot."
    )
    assert not looks_blocked("Filing Summary Product Name 2016 Iowa CH Forms")
