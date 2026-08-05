"""Human-approved derived products (product-DEPTH beyond each AIP's public menu).

src/deepen.py surfaces private products that don't appear on an AIP's website but do show up in
its SERFF filing titles or brochure PDFs — written to data/seed/derived_products_candidates.csv
for review. The subset a human approves is copied into data/seed/derived_products_reviewed.csv,
and THIS connector loads that reviewed file into the catalog so the depth survives a clean rebuild
(same durability pattern as manual_seed). source_type keeps 'serff_derived'/'brochure_derived' so
provenance stays visible; verified=0 because these are derived, not primary-source confirmed.
"""
from __future__ import annotations

import csv

from .. import config
from ..models import Product
from .base import Connector, ConnectorResult, Context

SEED_FILE = config.SEED_DIR / "derived_products_reviewed.csv"
_SERFF_SUMMARY = "https://filingaccess.serff.com/sfa/search/filingSummary.xhtml?filingId="


def _rows(path):
    """DictReader over the CSV, skipping the leading '#' comment lines."""
    with open(path, newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(l for l in fh if not l.startswith("#"))


class DeepenSeed(Connector):
    name = "deepen_seed"
    bucket = "private"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        if not SEED_FILE.exists():
            result.status = "skipped"
            result.coverage.append("deepen_seed: no reviewed-candidates file present")
            return result

        by_aip: dict[str, int] = {}
        for row in _rows(SEED_FILE):
            name = (row.get("name") or "").strip()
            aip = (row.get("aip_code") or "").strip() or None
            if not name:
                continue
            src = (row.get("source_type") or "serff_derived").strip()
            filing_id = (row.get("filing_id") or "").strip() or None
            doc_url = (row.get("doc_url") or "").strip() or None
            evidence = (row.get("evidence") or "").strip()
            # SERFF filing summary URL from the numeric part of the tracking number, when present.
            source_url = doc_url
            if src == "serff_derived" and filing_id and "-" in filing_id:
                source_url = _SERFF_SUMMARY + filing_id.rsplit("-", 1)[-1]
            by_aip[aip or "?"] = by_aip.get(aip or "?", 0) + 1
            result.products.append(Product(
                bucket="private",
                program="private_nonreinsured",
                name=name,
                source_type=src,
                aip_code=aip,
                peril_type=(row.get("peril_type") or "").strip() or None,
                coverage_type=(row.get("coverage_type") or "").strip() or None,
                filing_id=filing_id,
                doc_url=doc_url,
                source_url=source_url,
                verified=False,
                notes=f"Derived by deepen ({src}); evidence: {evidence}. Not primary-source verified.",
                raw=dict(row),
            ))

        per = ", ".join(f"{k}:{v}" for k, v in sorted(by_aip.items()))
        result.coverage.append(
            f"deepen_seed: {len(result.products)} human-approved derived products from SERFF "
            f"titles / brochures ({per}) — depth beyond public menus, verified=0"
        )
        return result
