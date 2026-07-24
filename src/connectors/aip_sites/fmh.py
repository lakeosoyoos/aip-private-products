"""Farmers Mutual Hail Insurance Company of Iowa — private product adapter (fmh.com).

fmh.com renders its private listings server-side as card grids (div.feature-box: h3 product name,
description paragraph, and a "LEARN MORE" link to the detail page). The default slug-pairing parse
drops cards whose heading doesn't match the URL slug ("CROP FIRE" links to .../grain-fire;
"Extra Harvest Expense" links to .../wind-with-extra-harvest-allowance), so we override parse() to
walk the cards directly. The MPCI sections of the site are federal plans and are not listed here.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _guess_coverage, _guess_peril


class FarmersMutualHail(SiteAdapter):
    aip_name = "Farmers Mutual Hail Insurance Company of Iowa"
    aip_code = "FH"  # RMA AipCode per task spec
    product_pages = [
        "https://www.fmh.com/insurance/crop-hail/crop-hail-products",   # Crop Hail, Production Plan
        "https://www.fmh.com/insurance/crop-hail/wind-and-greensnap",   # Wind, Green Snap, EHE
        "https://www.fmh.com/insurance/crop-hail/private-products",     # ECO+/SCO+, fires, replant
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[Product] = []
        seen: set[str] = set()
        for card in soup.select("div.feature-box"):
            h3 = card.find("h3")
            a = card.find("a", href=True)
            if h3 is None or a is None:
                continue
            name = " ".join(h3.get_text(" ", strip=True).split())
            if len(name) < 3 or name.lower() in seen:
                continue
            seen.add(name.lower())
            if name.isupper() and " " in name:   # "CROP FIRE" -> "Crop Fire" (ECO+/SCO+ untouched)
                name = name.title()
            href = urljoin(page_url, a["href"])
            if urlparse(href).netloc != urlparse(page_url).netloc:
                continue
            p = card.find("p")
            desc = " ".join(p.get_text(" ", strip=True).split())[:300] if p else ""
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
                doc_url=href,
                notes=(desc or None),
                crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                raw={"aip": self.aip_name, "name": name, "desc": desc, "href": href},
            ))
        return products


ADAPTERS.append(FarmersMutualHail())
