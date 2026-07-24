"""Producers Agriculture Insurance Company (ProAg) — private/supplemental product adapter.

ProAg (proag.com) lists its private menu as card links on two pages: /products/private-products/
(named-peril, supplemental, and weather products) and /products/crop-hail/ (annual hail plans and
hail endorsements). Each card is an <a class="link"> wrapping <div class="title"> (product name)
and <div class="description">, with no h2/h3 headings — so the default heading-pairing parse would
fall back to the whole card text as the name. We override parse() to read the title/description
divs directly, falling back to the base parser if the card layout ever changes.

Federal MPCI/livestock pages (/products/mpci/, /products/federal-livestock-program/) are
deliberately not listed: this adapter only scrapes the private (non-reinsured) pages, and the
child-link rule keeps cross-site nav links to other sections off these pages' results.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _guess_coverage, _guess_peril


class ProAg(SiteAdapter):
    aip_name = "Producers Agriculture Insurance Company"
    aip_code = "PL"  # RMA AipCode for Producers Agriculture Insurance Company (markets as ProAg)
    product_pages = [
        "https://www.proag.com/products/private-products/",
        "https://www.proag.com/products/crop-hail/",
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[Product] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(page_url, a["href"])
            parsed = urlparse(href)
            if parsed.netloc != urlparse(page_url).netloc:
                continue
            if not self._is_detail_href(page_url, parsed.path):
                continue
            title_el = a.find("div", class_="title")
            if title_el is None:
                continue  # nav/menu link, not a product card
            name = " ".join(title_el.get_text(" ", strip=True).split())
            if not name or len(name) < 3:
                continue
            key = parsed.path.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            desc_el = a.find("div", class_="description")
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
                doc_url=href,
                notes=(desc or None),
                crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                raw={"aip": self.aip_name, "name": name, "desc": desc, "href": href},
            ))
        if not products:  # card layout changed — fall back to the generic heading-block parse
            products = super().parse(html, page_url, cfg)
        return products


ADAPTERS.append(ProAg())
