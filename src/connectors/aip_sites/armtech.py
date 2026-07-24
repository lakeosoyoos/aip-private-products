"""American Agri-Business Insurance Company (ARMtech / AgriSompo North America) — private products.

ARMtech Insurance Services rebranded as AgriSompo North America (Sompo Holdings); its old domain
armt.com no longer serves pages (connections time out / are refused) and Wayback shows it 301ing to
agrisompo.com, which is the live site. The private (non-reinsured) menu lives at
/products/private-products/ with one child detail page per product (crop-hail, named-peril,
replant-option, xtra-bundle, band) and h-tag headings that pair cleanly under the default
SiteAdapter.parse. Federal MPCI and livestock pages (/products/federal-products/,
/products/livestock-products/) are deliberately excluded — the child-of-listing link rule keeps
their nav links out of the private page's results.
"""
from __future__ import annotations

from .base import ADAPTERS, SiteAdapter


class ArmTech(SiteAdapter):
    aip_name = "American Agri-Business Insurance Company"
    aip_code = "WN"  # RMA AipCode for American Agri-Business (markets as ARMtech / AgriSompo NA)
    product_pages = [
        "https://www.agrisompo.com/products/private-products/",
    ]


ADAPTERS.append(ArmTech())
