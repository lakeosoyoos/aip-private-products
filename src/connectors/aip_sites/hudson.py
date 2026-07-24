"""Hudson Insurance Company (markets as "Hudson Crop" / Hudson Crop & Livestock) — private products.

Hudson's crop division publishes its full product menu on hudsoncroplivestock.com/products
(hudsoninsgroup.com and hudsoncrop.com both funnel there). The page is server-rendered and
scrapable with plain requests + a browser UA. It mixes federal MPCI/livestock plans with the
private menu, so we restrict extraction with product_link_pattern:

  * /products/supplemental-and-crop-hail/<slug> — the "Crop Hail & Private" tab: Crop Hail &
    Named Peril, Band Revenue Protection, MyECO and MySCO, Variable Interval Product, Cash
    Lease Insurance Protection.
  * /mymco — MyMCO, Hudson's exclusive grower-level private complement to the federal Margin
    Coverage Option endorsement (lives at a top-level URL, not under /products/).

The page has no h2/h3 heading blocks, so the default parse falls back to anchor text, which on
this site is the clean product name. Nav duplicates (www. host variants like "ALL CROP HAIL &
PRIVATE") are dropped by the base class's same-netloc check.
"""
from __future__ import annotations

import re

from .base import ADAPTERS, SiteAdapter


class Hudson(SiteAdapter):
    aip_name = "Hudson Insurance Company"
    aip_code = "HU"  # RMA AipCode for Hudson Insurance Company
    product_pages = [
        "https://hudsoncroplivestock.com/products",
    ]
    # Only the private tab's detail pages plus the top-level MyMCO page; excludes the federal
    # MPCI (/products/multi-peril/...) and livestock (/products/livestock/...) listings.
    product_link_pattern = re.compile(
        r"/products/supplemental-and-crop-hail/[^/]+|^/mymco/?$"
    )


ADAPTERS.append(Hudson())
