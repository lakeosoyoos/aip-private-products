"""RMA AIP listing connector (live JSON API).

Populates the `aips` table from RMA's public AIP service — the authoritative list of Approved
Insurance Providers (the ~12 companies that hold a Standard Reinsurance Agreement). Endpoints were
confirmed from the AipListing app's own JavaScript:

  current reinsurance year : GET /Api/ReinsuranceYear/v1/CurrentYear            -> e.g. 2027
  AIPs under an agreement   : GET /Api/AIP/v1/CurrentReinsuranceYear/{type}     -> [ {AipCode,...} ]

We use agreement type SRA (multi-peril crop; LPRA is livestock and out of scope for row crops).
"""
from __future__ import annotations

from .. import models
from .base import Connector, ConnectorResult, Context

API_BASE = "https://public-rma.fpac.usda.gov/Api"
AGREEMENT_TYPE = "SRA"


class RmaAipListing(Connector):
    name = "rma_aip_listing"
    bucket = "aips"

    def fetch(self, ctx: Context) -> ConnectorResult:
        url = f"{API_BASE}/AIP/v1/CurrentReinsuranceYear/{AGREEMENT_TYPE}"
        resp = ctx.client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        rows = resp.json() or []

        # The service returns one row per AIP-underwriting-state; collapse to one row per AipCode.
        by_code: dict[str, models.AIP] = {}
        for r in rows:
            code = (r.get("AipCode") or "").strip()
            if not code:
                continue
            if code not in by_code:
                by_code[code] = models.AIP(
                    aip_code=code,
                    name=(r.get("AipName") or "").strip(),
                    agreement_type=r.get("AgreementTypeCode"),
                    reinsurance_year=int(r["ReinsuranceYear"]) if r.get("ReinsuranceYear") else None,
                    city=r.get("CityName"),
                    state=r.get("AddressStateAbbreviation"),
                    phone=r.get("TollFreePhoneNumber") or r.get("PhoneNumber"),
                    website=r.get("WebSiteAddress") or r.get("Website"),
                    source_url=url,
                )

        result = ConnectorResult(
            aips=list(by_code.values()),
            http_status=resp.status_code,
        )
        result.coverage.append(f"rma_aip_listing: {len(by_code)} AIPs ({AGREEMENT_TYPE})")
        return result
