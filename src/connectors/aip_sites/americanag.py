"""American Agricultural Insurance Company (AmericanAg) — private product adapter via AFBIS.

AmericanAg (aaic.com) is primarily a reinsurer affiliated with the American Farm Bureau and does
not publish a retail crop menu itself. Its crop insurance program is run by American Farm Bureau
Insurance Services, Inc. (AFBIS), the designated managing general agency that does underwriting,
claims, and marketing for AmericanAg's crop business, sold through Farm Bureau companies and
independent agents. AFBIS's public site is farmbureausellscropinsurance.com, and its
"Crop Hail/Private Products" page is the only private (non-federal) menu: Crop Hail and
Added Value Enhancement. Everything else on the site (MPCI, RI, livestock) is federal.

Layout note: the listing page lives at /insurance-plans/crop-hail-private-products/ but the
product detail pages live under a sibling path /insurance-plans/crop-hail-plans/<slug>/, so the
default "child of the listing page" href rule misses them; product_link_pattern targets the
crop-hail-plans detail paths instead. Product names come from the h3 heading blocks, which the
default parse pairs to those hrefs by slug.
"""
from __future__ import annotations

import re

from .base import ADAPTERS, SiteAdapter


class AmericanAg(SiteAdapter):
    aip_name = "American Agricultural Insurance Company"
    aip_code = "FA"  # RMA AipCode per task listing (crop program marketed/serviced by AFBIS)
    product_pages = [
        "https://www.farmbureausellscropinsurance.com/insurance-plans/crop-hail-private-products/",
    ]
    # Detail pages are under /crop-hail-plans/, a sibling of the listing path (see docstring).
    product_link_pattern = re.compile(r"/insurance-plans/crop-hail-plans/[^/]+/?$")


ADAPTERS.append(AmericanAg())
