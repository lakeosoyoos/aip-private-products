"""Clear Blue Insurance Company — private product adapter via Precision Risk Management (PRM).

Clear Blue is a fronting carrier and has no retail crop presence of its own. Its federal/crop
program is operated by Precision Risk Management, LLC (precisionriskmanagement.com), an MGA that
partnered with Clear Blue Insurance Group as fronting carrier for delivery of the crop insurance
program (announced July 2024; see precisionriskmanagement.com/news/precision-risk-management-
partners-with-clear-blue-insurance-group/). The PRM site's own footer copyright is held by
"Clear Blue Insurance Company", confirming the site content is the Clear Blue crop program.

PRM's private (non-federal) menu lives at /products/private/ — Crop Hail and a private Replant
Option — plus VANE, PRM's tailored/custom private coverage product, which sits at the sibling
path /products/tailored-private-vane/. product_link_pattern includes both shapes (it also keeps
the federal /products/mpci/replant/ link out of the private set, which shares the "replant"
slug). The listing page has no per-product headings, so names come from the anchor-text
fallback; the VANE nav link's anchor text is the generic "Custom Solutions", so parse() renames
that one product to its branded name from the detail page (h1 "Tailored Private", branded VANE).
"""
from __future__ import annotations

import re

from .base import ADAPTERS, SiteAdapter


class ClearBlue(SiteAdapter):
    aip_name = "Clear Blue Insurance Company"
    aip_code = "CP"  # RMA AipCode per task listing (crop program operated by PRM as MGA)
    product_pages = [
        "https://precisionriskmanagement.com/products/private/",
    ]
    # Private detail pages plus the tailored/VANE page, which is a sibling of /products/private/.
    product_link_pattern = re.compile(r"/products/(?:private/[^/]+|tailored-private-vane)/?$")

    def parse(self, html, page_url, cfg):
        products = super().parse(html, page_url, cfg)
        for p in products:
            # The VANE link's anchor text on the listing page is just "Custom Solutions";
            # use the branded name from the detail page (h1 "Tailored Private" / VANE).
            if p.doc_url.rstrip("/").endswith("tailored-private-vane"):
                p.name = "VANE (Tailored Private)"
                p.raw["name"] = p.name
        return products


ADAPTERS.append(ClearBlue())
