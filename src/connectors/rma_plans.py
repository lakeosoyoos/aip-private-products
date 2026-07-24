"""Federal privately-developed (508(h)) plans connector — curated reference.

WHY a seed instead of a scrape: the authoritative plan x commodity x state data lives only in the
full Actuarial Data Master (~928 MB/crop-year), which is too heavy to pull on every refresh, and
RMA publishes no compact machine-readable list of *which* plans are privately developed. Just as
important, the federal menu is NOT AIP-specific: once the FCIC Board approves a 508(h) product,
every AIP may offer it. So the federal side is a shared reference list, not a per-AIP scrape.

This connector loads data/seed/federal_private_plans.csv (source-cited, each row carries a
`verified` flag). Rows are emitted as bucket='508h' products with aip_code left NULL (all AIPs).
For exact per-crop/per-state availability, enable the opt-in rma_adm deep-parse (Phase B).
"""
from __future__ import annotations

import csv

from .. import config, rowcrops
from ..models import Product
from .base import Connector, ConnectorResult, Context

SEED_FILE = config.SEED_DIR / "federal_private_plans.csv"


class RmaPlans(Connector):
    name = "rma_plans"
    bucket = "508h"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        if not SEED_FILE.exists():
            result.status = "error"
            result.message = f"seed file missing: {SEED_FILE}"
            result.coverage.append(f"rma_plans: ERROR missing seed {SEED_FILE.name}")
            return result

        n_unverified = 0
        with open(SEED_FILE, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                crops = [c.strip() for c in (row.get("crops") or "").split(";") if c.strip()]
                verified = str(row.get("verified", "0")).strip() in {"1", "true", "yes"}
                if not verified:
                    n_unverified += 1
                result.products.append(Product(
                    bucket="508h",
                    name=name,
                    source_type="rma_plans_seed",
                    program=row.get("program") or "federal_508h",
                    aip_code=None,                       # federal plans: offered by all AIPs
                    developer=(row.get("developer") or "").strip() or None,
                    plan_code=(row.get("plan_code") or "").strip() or None,
                    peril_type=(row.get("peril_type") or "").strip() or None,
                    coverage_type=(row.get("coverage_type") or "").strip() or None,
                    status=(row.get("status") or "").strip() or None,
                    source_url=(row.get("source_url") or "").strip() or None,
                    verified=verified,
                    notes=(row.get("notes") or "").strip() or None,
                    crops=crops,
                    raw=dict(row),
                ))

        n = len(result.products)
        result.coverage.append(
            f"rma_plans: {n} curated federal 508(h)/private-sector products "
            f"({n_unverified} unverified — offered through ALL AIPs)"
        )
        return result
