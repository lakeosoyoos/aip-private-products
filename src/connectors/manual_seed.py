"""Manually-maintained private products for AIPs whose sites block automated fetch.

Some AIP menus are public but unscrapable (e.g. COUNTRY Financial sits behind Cloudflare TLS
fingerprinting — every requests-based client gets HTTP 403). Rather than pretend those AIPs have
no products or ship an adapter that always returns zero, this connector loads
data/seed/private_products_manual.csv: rows verified by a human in a real browser, each carrying
the source_url and a note explaining why it is manual. source_type='manual_seed' keeps the
provenance distinction visible in exports.
"""
from __future__ import annotations

import csv

from .. import config
from ..models import Product
from .base import Connector, ConnectorResult, Context

SEED_FILE = config.SEED_DIR / "private_products_manual.csv"


class ManualSeed(Connector):
    name = "manual_seed"
    bucket = "private"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        if not SEED_FILE.exists():
            result.status = "skipped"
            result.coverage.append("manual_seed: no manual seed file present")
            return result

        by_aip: dict[str, int] = {}
        with open(SEED_FILE, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name") or "").strip()
                aip = (row.get("aip_code") or "").strip() or None
                if not name:
                    continue
                by_aip[aip or "?"] = by_aip.get(aip or "?", 0) + 1
                result.products.append(Product(
                    bucket="private",
                    program="private_nonreinsured",
                    name=name,
                    source_type="manual_seed",
                    aip_code=aip,
                    peril_type=(row.get("peril_type") or "").strip() or None,
                    coverage_type=(row.get("coverage_type") or "").strip() or None,
                    source_url=(row.get("source_url") or "").strip() or None,
                    verified=str(row.get("verified", "0")).strip() in {"1", "true", "yes"},
                    notes=(row.get("notes") or "").strip() or None,
                    crops=[c.strip() for c in (row.get("crops") or "").split(";") if c.strip()],
                    states=[s.strip() for s in (row.get("states") or "").split(";") if s.strip()],
                    raw=dict(row),
                ))

        per = ", ".join(f"{k}:{v}" for k, v in sorted(by_aip.items()))
        result.coverage.append(
            f"manual_seed: {len(result.products)} browser-verified products for bot-walled AIP "
            f"sites ({per}) — maintained by hand, see CSV notes"
        )
        return result
