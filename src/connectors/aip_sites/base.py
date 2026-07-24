"""AIP website scraper framework + the connector that runs every registered site adapter.

Each AIP publishes its private/supplemental product menu on its own site. A SiteAdapter names the
AIP, lists the product pages to scrape, and (by default) extracts products from heading blocks
(h2/h3 with a nearby link + description) — the common pattern across these marketing sites. Add a
new AIP by dropping a module next to this one that subclasses SiteAdapter and appending it to
ADAPTERS; no other file changes needed.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ... import rowcrops
from ...models import Product
from ..base import Connector, ConnectorResult, Context

# Registered adapters (populated by importing the adapter modules; see get_adapters()).
ADAPTERS: list["SiteAdapter"] = []

# Generic anchor texts that are navigation, not product names.
_GENERIC_LINK = re.compile(
    r"^(more|read more|learn more|details?|view|back|home|next|previous|click here|"
    r"products?|contact|about)\b", re.I)


class SiteAdapter:
    aip_name: str = ""
    aip_code: str | None = None          # RMA AipCode when known (resolved/verified separately)
    product_pages: list[str] = []        # category/listing URLs to scrape
    # Optional override: regex a detail-page href must match. Default = "child of the listing page".
    product_link_pattern: re.Pattern | None = None

    def _is_detail_href(self, page_url: str, href_path: str) -> bool:
        if self.product_link_pattern is not None:
            return bool(self.product_link_pattern.search(href_path))
        page_path = urlparse(page_url).path.rstrip("/")
        # A product detail page is a deeper child of the listing (…/listing/<slug>).
        return href_path.startswith(page_path + "/") and href_path.rstrip("/") != page_path

    def parse(self, html: str, page_url: str, cfg) -> list[Product]:
        """Extract products from a listing page.

        Product detail pages appear as child links (…/listing/<slug>), but the human-readable name
        lives in a nearby heading, and the link text is often just "More". So we collect the detail
        hrefs and pair each to a heading by URL-slug match (e.g. "NAU® EASYrev®" -> nau-easyrev).
        This reliably captures branded names that share no generic keyword. Falls back to
        descriptive anchor text for sites where the product name IS the link.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. Candidate detail hrefs on this page, keyed by final URL slug.
        by_slug: dict[str, str] = {}
        anchor_text: dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(page_url, a["href"])
            if urlparse(href).netloc != urlparse(page_url).netloc:
                continue
            if not self._is_detail_href(page_url, urlparse(href).path):
                continue
            slug = urlparse(href).path.rstrip("/").rsplit("/", 1)[-1]
            by_slug.setdefault(slug, href)
            txt = " ".join(a.get_text(" ", strip=True).split())
            if txt and not _GENERIC_LINK.match(txt) and len(txt) > len(anchor_text.get(slug, "")):
                anchor_text[slug] = txt

        # 2. Pair headings to detail hrefs by slug; heading text is the product name.
        chosen: dict[str, dict] = {}   # slug -> {name, href, node}
        for h in soup.find_all(["h2", "h3", "h4"]):
            name = " ".join(h.get_text(" ", strip=True).split())
            if not name or len(name) < 3:
                continue
            hslug = _slugify(name)
            for slug, href in by_slug.items():
                if slug in hslug or hslug in slug:   # tolerant match (handles ®, (BPM) suffixes)
                    chosen.setdefault(slug, {"name": name, "href": href, "node": h})
                    break

        # 3. Fallback for sites where the link text itself is the product name.
        for slug, href in by_slug.items():
            if slug not in chosen and anchor_text.get(slug):
                chosen[slug] = {"name": anchor_text[slug], "href": href, "node": None}

        products: list[Product] = []
        for slug, slot in chosen.items():
            name, href = slot["name"], slot["href"]
            node = slot["node"]
            desc_el = node.find_next(["p", "li"]) if node is not None else None
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
        return products

    def scrape(self, ctx: Context) -> tuple[list[Product], list[str]]:
        out: list[Product] = []
        notes: list[str] = []
        ua = {"User-Agent": ctx.cfg.serff_user_agent}  # browser UA works broadly on marketing sites
        for url in self.product_pages:
            try:
                resp = ctx.client.get(url, headers=ua)
                if resp.status_code != 200:
                    notes.append(f"{self.aip_name} [{url}]: HTTP {resp.status_code}")
                    continue
                found = self.parse(resp.text, url, ctx.cfg)
                out.extend(found)
                notes.append(f"{self.aip_name} [{url.rsplit('/', 1)[-1]}]: {len(found)} products")
            except Exception as exc:
                notes.append(f"{self.aip_name} [{url}]: ERROR {exc}")
        return out, notes


def _slugify(text: str) -> str:
    """Lowercase, drop ®/™ and parenthetical abbreviations, non-alnum -> hyphen (URL-slug shape)."""
    text = re.sub(r"\([^)]*\)", " ", text)            # drop "(BPM)" etc.
    text = text.replace("®", " ").replace("™", " ").replace("©", " ")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def _guess_peril(text: str) -> str | None:
    t = text.lower()
    for kw, label in (
        ("hail", "hail"), ("wind", "wind"), ("hurricane", "wind"), ("fire", "fire"),
        ("margin", "margin"), ("revenue", "revenue"), ("replant", "replant"),
        ("named peril", "named-peril"), ("named-peril", "named-peril"),
    ):
        if kw in t:
            return label
    return None


def _guess_coverage(text: str) -> str | None:
    t = text.lower()
    if "bundle" in t:
        return "bundle"
    if "endorsement" in t:
        return "endorsement"
    if "supplement" in t or "complement" in t or "enhance" in t:
        return "supplemental"
    if "gap" in t:
        return "gap"
    if "named peril" in t or "hail" in t:
        return "named-peril"
    return None


def get_adapters() -> list[SiteAdapter]:
    """Auto-import every adapter module in this package; importing registers its adapter.

    Drop a new `<aip>.py` next to this file (subclass SiteAdapter, append an instance to ADAPTERS)
    and it is picked up automatically — no registry edits, so adapters never conflict.
    """
    if not ADAPTERS:
        import importlib
        import pkgutil
        import sys
        package = sys.modules[__package__]  # src.connectors.aip_sites
        for info in pkgutil.iter_modules(package.__path__):
            if info.name != "base":
                importlib.import_module(f"{__package__}.{info.name}")
    return ADAPTERS


class AipSites(Connector):
    name = "aip_sites"
    bucket = "private"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        adapters = get_adapters()
        for adapter in adapters:
            products, notes = adapter.scrape(ctx)
            result.products.extend(products)
            result.coverage.extend(f"aip_sites/{n}" for n in notes)
        total = len(result.products)
        wired = ", ".join(a.aip_name for a in adapters) or "none"
        result.coverage.append(
            f"aip_sites: {total} products from {len(adapters)} AIP adapter(s) [{wired}]. "
            f"Remaining AIPs pending adapters."
        )
        result.message = f"{total} products from {len(adapters)} adapters"
        return result
