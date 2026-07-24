"""NAU Country Insurance Company — private/supplemental product adapter.

NAU Country publishes its private menu as h3 product blocks under a few category pages. The default
SiteAdapter.parse handles the heading-block layout; we just point it at the pages. aip_code is set
from the RMA AIP listing (verified separately — see the verification notes / tests).
"""
from __future__ import annotations

from .base import ADAPTERS, SiteAdapter


class NauCountry(SiteAdapter):
    aip_name = "NAU Country Insurance Company"
    aip_code = "NA"  # RMA AipCode for NAU Country (verified against rma_aip_listing SRA feed)
    product_pages = [
        "https://www.naucountry.com/products/private-products",
        "https://www.naucountry.com/products/crop-hail",
        "https://www.naucountry.com/products/mpci-endorsements-and-options",
    ]


ADAPTERS.append(NauCountry())
