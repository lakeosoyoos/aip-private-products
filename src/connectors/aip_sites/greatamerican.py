"""Great American Insurance Company (crop division, greatamericancrop.com) — private products.

Server-rendered Sitefinity site; plain requests sees everything. Both listing pages present each
product as a <div|a class="card-animated"> card: name in .card-animated__title (h3), description in
.card-animated__content, and — when the card is an <a> — an href to the product's PDF brochure
under /docs/. There are no child detail pages, so the default slug-pairing parse finds nothing;
this override walks the cards instead. doc_url is the brochure PDF when the card links one,
otherwise the listing page itself.

Both pages are private/non-reinsured lines (crop-hail and named-peril); the federal menu lives on a
separate /products---policies/mpci-products page we do not scrape. The hail page's generic
"Endorsements" card (a grouping blurb, not a product) is skipped by name.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _GENERIC_LINK, _guess_coverage, _guess_peril

# Card headings that are groupings/CTAs, not products.
_NON_PRODUCT = {"endorsements", "learn more", "tech support when you need it"}


class GreatAmerican(SiteAdapter):
    aip_name = "Great American Insurance Company"
    aip_code = "GA"  # RMA AipCode for Great American Insurance Company
    product_pages = [
        "https://greatamericancrop.com/products---policies/private-products",
        "https://greatamericancrop.com/products---policies/crop-hail-products",
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[Product] = []
        seen: set[str] = set()

        for card in soup.select(".card-animated"):
            title = card.select_one(".card-animated__title") or card.find("h3")
            if title is None:
                continue
            name = " ".join(title.get_text(" ", strip=True).split())
            if not name or len(name) < 3:
                continue
            if name.lower() in _NON_PRODUCT or _GENERIC_LINK.match(name):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)

            body = card.select_one(".card-animated__content")
            desc = " ".join(body.get_text(" ", strip=True).split())[:300] if body else ""

            # Cards rendered as <a> link the product's PDF brochure.
            href = card.get("href") if card.name == "a" else None
            doc_url = urljoin(page_url, href) if href else page_url

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
                doc_url=doc_url,
                notes=(desc or None),
                crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                raw={"aip": self.aip_name, "name": name, "desc": desc, "href": doc_url},
            ))
        return products


ADAPTERS.append(GreatAmerican())
