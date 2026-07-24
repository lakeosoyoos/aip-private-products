"""ACE American Insurance Company — markets crop insurance as Rain and Hail LLC (Chubb).

rainhail.com serves its private menu server-rendered, but not in the heading+detail-link layout the
default parse expects: each product is an accordion block (div.rh-toggle-div holding an h3
"+ Name" toggle and a CSS-hidden div.rh-toggle-content description) with no per-product detail
page. We override parse() to walk the accordions; doc_url is therefore the listing page itself.
The base Crop-Hail (CH) product appears separately as an h2 with a trailing "(XX)" plan letter code
(which distinguishes it from section headers like "Crop-Hail Endorsements"). The MPCI pages on the
same site are federal plans and are deliberately not listed here.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _guess_coverage, _guess_peril

# "Crop-Hail (CH)" is a product; "Crop-Hail Endorsements" is a section header.
_H2_PRODUCT = re.compile(r"\([A-Z]{2,3}\)$")


class RainHail(SiteAdapter):
    aip_name = "ACE American Insurance Company"
    aip_code = "RH"  # RMA AipCode per task spec (Rain and Hail LLC / Chubb)
    product_pages = [
        "https://www.rainhail.com/d/ps/coverages/crop-hail",      # Crop-Hail + endorsements
        "https://www.rainhail.com/d/ps/coverages/stand-alone",    # private stand-alone programs
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[Product] = []
        seen: set[str] = set()

        def add(name: str, desc: str) -> None:
            name = " ".join(name.split()).lstrip("+ ").strip()
            if len(name) < 3 or name.lower() in seen:
                return
            seen.add(name.lower())
            desc = " ".join(desc.split())[:300]
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
                doc_url=page_url,  # accordion blocks have no per-product detail page
                notes=(desc or None),
                crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                raw={"aip": self.aip_name, "name": name, "desc": desc, "href": page_url},
            ))

        # 1. Base product h2s carrying a "(XX)" plan letter code, e.g. "Crop-Hail (CH)".
        for h2 in soup.find_all("h2"):
            name = " ".join(h2.get_text(" ", strip=True).split())
            if _H2_PRODUCT.search(name):
                p = h2.find_next("p")
                add(name, p.get_text(" ", strip=True) if p else "")

        # 2. Accordion products: div.rh-toggle-div -> h3 name + rh-toggle-content description.
        for block in soup.select("div.rh-toggle-div"):
            h3 = block.find("h3")
            if h3 is None:
                continue
            content = block.select_one("div.rh-toggle-content")
            desc = ""
            if content is not None:
                paras = [p.get_text(" ", strip=True) for p in content.find_all("p")
                         if "fine-print" not in (p.get("class") or [])]
                desc = " ".join(t for t in paras if t)
            add(h3.get_text(" ", strip=True), desc)

        return products


ADAPTERS.append(RainHail())
