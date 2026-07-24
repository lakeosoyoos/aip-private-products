"""Rural Community Insurance Company (RCIS, a Zurich company) — private product adapter.

rcis.com is an Angular SPA: the marketing URL (https://www.rcis.com/home/pages/products/private)
serves only a JS shell, so the default heading/link parse sees nothing. But the SPA hydrates each
page from a static HTML fragment under /home/assets/content/ (route -> fragment mapping lives in
/home/assets/json/top_navigation.json), and those fragments are plain public HTML that requests can
read directly. So we scrape the fragment (products_private.html) and point doc_url at the
human-viewable SPA page.

Layout: private products are <li> items inside <div class="card-body"> season cards
(Plant / California Named Peril / Grow / Harvest), grouped under h2/h3 section headings.
There are no per-product detail pages. A "Reasons farmers may want private products" bullet list
sits outside the cards and is excluded structurally. Several options repeat across season cards
(e.g. Replant Option in both Plant and Grow), so we dedupe by normalized name.

Everything on this page is private/named-peril (the federal MPCI menu is a separate
products_federal.html fragment, which we deliberately do not scrape).
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from .base import ADAPTERS, SiteAdapter, _guess_coverage, _guess_peril

# Human-viewable SPA route that renders the scraped fragment.
_HUMAN_PAGE = "https://www.rcis.com/home/pages/products/private"


class Rcis(SiteAdapter):
    aip_name = "Rural Community Insurance Company"
    aip_code = "EF"  # RMA AipCode for Rural Community Insurance Company
    product_pages = [
        # Content fragment behind https://www.rcis.com/home/pages/products/private (JS-rendered).
        "https://www.rcis.com/home/assets/content/products_private.html",
    ]

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        # The fragment is UTF-8 but served as bare `text/html` (no charset), so requests decodes it
        # as ISO-8859-1 and en-dashes arrive mojibake ("â\x80\x93"). Round-trip repairs it.
        if "Ã" in html or "â" in html:
            try:
                html = html.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass  # not actually mis-decoded; keep as-is
        soup = BeautifulSoup(html, "html.parser")
        products: list[Product] = []
        seen: set[str] = set()

        for card in soup.select("div.card-body"):
            for ul in card.find_all("ul"):
                # Section heading = nearest preceding h2/h3 that is inside this same card
                # ("Plant", "Crop Hail Options", "Endorsements to Hail Policies", ...).
                section = ""
                head = ul.find_previous(["h2", "h3"])
                if head is not None and card in head.parents:
                    section = " ".join(head.get_text(" ", strip=True).split())

                for li in ul.find_all("li"):
                    if li.find("ul") is not None:
                        continue  # structural wrapper around a nested list, not a product
                    name = " ".join(li.get_text(" ", strip=True).split())
                    if not name or len(name) < 3:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue  # same option repeats across season cards
                    seen.add(key)

                    blob = f"{name} {section}"
                    products.append(Product(
                        bucket="private",
                        program="private_nonreinsured",
                        name=name,
                        source_type="aip_site",
                        aip_code=self.aip_code,
                        peril_type=_guess_peril(blob),
                        coverage_type=_guess_coverage(blob),
                        source_url=page_url,
                        doc_url=_HUMAN_PAGE,  # no per-product pages; this page shows the list
                        notes=(f"RCIS private products page, section: {section}" if section
                               else "RCIS private products page"),
                        crops=rowcrops.match_crops(blob, cfg.rowcrops_extra),
                        raw={"aip": self.aip_name, "name": name, "section": section,
                             "content_fragment": page_url, "rendered_page": _HUMAN_PAGE},
                    ))
        return products


ADAPTERS.append(Rcis())
