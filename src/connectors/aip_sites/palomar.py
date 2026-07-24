"""Palomar Specialty Insurance Company — private/supplemental product adapter.

Palomar (RMA AipCode PS) is the newest federal crop AIP; its crop program is publicly marketed
under the "Palomar Crop" brand at palomarcrop.com. The program began as a multi-year fronting
partnership with Advanced AgProtection (AAP), a Texas crop-insurance MGA that runs underwriting,
risk management and claims (agent portal still lives at aapcrop.com); Palomar took a strategic
stake in AAP in 2023 and agreed in 2025 to acquire it outright. The Private Products page lists
the non-federal menu as heading blocks WITHOUT product-detail links (currently a single product,
Crop Hail Insurance), so the default child-link pairing finds nothing; parse() falls back to
extracting content headings directly when no detail links exist.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _guess_coverage, _guess_peril


class Palomar(SiteAdapter):
    aip_name = "Palomar Specialty Insurance Company"
    aip_code = "PS"  # RMA AipCode for Palomar (verify against rma_aip_listing SRA feed)
    product_pages = [
        "https://palomarcrop.com/private-products/",
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        # Try the standard heading+detail-link layout first (future-proof if they add pages).
        products = super().parse(html, page_url, cfg)
        if products:
            return products

        # Fallback: linkless heading blocks. Strip site chrome, then treat each h2/h3 in the
        # remaining content as a product name with the next paragraph as its description.
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        for h in soup.find_all(["h2", "h3"]):
            name = " ".join(h.get_text(" ", strip=True).split())
            if not name or len(name) < 3:
                continue
            desc_el = h.find_next(["p", "li"])
            desc = " ".join(desc_el.get_text(" ", strip=True).split())[:300] if desc_el else ""
            blob = f"{name} {desc}"
            products.append(Product(
                bucket="private",
                program="private_nonreinsured",
                name=name,
                source_type="aip_site",
                aip_code=self.aip_code,
                peril_type=_guess_peril(blob),
                coverage_type=_guess_coverage(blob),
                source_url=page_url,
                doc_url=page_url,  # no per-product detail pages exist on this site
                notes=(desc or None),
                crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                raw={"aip": self.aip_name, "name": name, "desc": desc, "href": page_url,
                     "brand": "Palomar Crop / Advanced AgProtection (MGA)"},
            ))
        return products


ADAPTERS.append(Palomar())
