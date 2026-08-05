"""SERFF Filing Access connector (truly-private products: crop-hail / named-peril / supplemental).

State insurance filings are where the non-federal, non-reinsured products live (TOI 02.1 Crop;
the Crop-Hail split appears per filing as sub-TOI 02.1000/02.1001/02.1002). This connector is the
IMPORT side of a two-piece design:

  1. src/connectors/serff_browser.py (Playwright, run manually / on a slow rotation) drives the
     filingaccess.serff.com portal and writes per-state JSON payloads to data/cache/serff/
     (<ST>_filings.json). The portal is a PrimeFaces/JSF app behind a WAF that challenges
     sustained automation, so live extraction is deliberately NOT part of the normal refresh:
       .venv/bin/python -m src.connectors.serff_browser --state IA --no-details
  2. This connector (part of the normal refresh) loads whatever payloads exist into the
     serff_filings table — filing grain, one row per (tracking number, state) — and maps portal
     company names to AIP codes. States with no payload yet fall back to a reachability probe and
     an honest "pending" coverage line. No filings are ever fabricated.

Filings deliberately do NOT become `products` rows: an AIP re-files rates/forms for the same
product every year (FMH alone has 144 Iowa filings), so the filing record is regulatory history,
not a product menu. The xlsx export gives serff_filings its own sheet.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .. import config
from . import serff_states
from .base import Connector, ConnectorResult, Context

CACHE_DIR = config.CACHE_DIR / "serff"


def _norm_company(name: str) -> str:
    """Normalize portal company-name variants for matching against the aips table."""
    n = name.lower().strip()
    n = re.sub(r"\s*-\s*crop division$", "", n)   # "Great American ... - Crop Division"
    n = re.sub(r",\s*si$", "", n)                 # "Farmers Mutual Hail Insurance Company, SI"
    n = re.sub(r"\bco\.?\b", "company", n)
    n = re.sub(r"\bins\.?\b", "insurance", n)
    n = re.sub(r"[.,]", "", n)
    return re.sub(r"\s+", " ", n)


# Portal names that still differ from the AIP legal name after normalization (group affiliates
# filing under a shorter or sibling name). Values are aips.aip_code.
ALIASES = {
    "farmers mutual hail insurance company": "FH",  # files without "of Iowa" in some states
    "great american insurance company of new york": "GA",  # GA affiliate entity
}
# Portal placeholders that intentionally map to no single AIP (multi-company filings).
UNMAPPABLE = {"multiple"}


def _aip_map(conn) -> dict[str, str]:
    m = {
        _norm_company(r["name"]): r["aip_code"]
        for r in conn.execute("SELECT aip_code, name FROM aips")
    }
    m.update(ALIASES)
    return m


class Serff(Connector):
    name = "serff"
    bucket = "private"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        states = [s.upper() for s in (ctx.states or ctx.cfg.serff_states)]
        ua = ctx.cfg.serff_user_agent
        aip_by_name = _aip_map(ctx.conn)

        imported, probed, custom, down = [], [], [], []
        total_rows = 0
        now = datetime.now(timezone.utc).isoformat()

        for st in states:
            payload_path = CACHE_DIR / f"{st}_filings.json"
            if payload_path.exists():
                payload = json.loads(payload_path.read_text())
                rows = 0
                unmapped: set[str] = set()
                for f in payload.get("filings", []):
                    aip_code = aip_by_name.get(_norm_company(f.get("company_name", "")))
                    if aip_code is None:
                        unmapped.add(f.get("company_name", "?"))
                    ctx.conn.execute(
                        """INSERT INTO serff_filings (serff_tracking_number, state, filing_id,
                               company_name, aip_code, naic_company_code, product_name, toi,
                               sub_toi, filing_type, filing_status, disposition_status,
                               submission_date, disposition_date, filing_url, fetched_at, raw)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(serff_tracking_number, state) DO UPDATE SET
                               filing_status=excluded.filing_status,
                               disposition_status=excluded.disposition_status,
                               submission_date=COALESCE(excluded.submission_date,
                                                        serff_filings.submission_date),
                               disposition_date=COALESCE(excluded.disposition_date,
                                                         serff_filings.disposition_date),
                               aip_code=COALESCE(excluded.aip_code, serff_filings.aip_code),
                               fetched_at=excluded.fetched_at, raw=excluded.raw""",
                        (
                            f.get("serff_tracking_number"), st, f.get("filing_id"),
                            f.get("company_name"), aip_code, f.get("naic_company_code"),
                            f.get("product_name"), f.get("toi"), f.get("sub_toi"),
                            f.get("filing_type"), f.get("filing_status"),
                            f.get("disposition_status"), f.get("submission_date_iso"),
                            f.get("disposition_date_iso"), f.get("filing_url"),
                            f.get("fetched_at") or now, json.dumps(f),
                        ),
                    )
                    rows += 1
                ctx.conn.commit()
                total_rows += rows
                imported.append(st)
                gen = payload.get("generated_at", "?")[:10]
                line = f"serff[{st}]: {rows} filings imported (payload {gen})"
                if unmapped:
                    line += f" — unmapped companies: {', '.join(sorted(unmapped))}"
                result.coverage.append(line)
                continue

            # No payload — fall back to the honest reachability probe.
            url = serff_states.portal_url(st)
            if not serff_states.is_shared(st):
                custom.append(st)
                result.coverage.append(
                    f"serff[{st}]: custom state portal ({url}) — pending dedicated adapter"
                )
                continue
            try:
                resp = ctx.client.get(url, headers={"User-Agent": ua})
                if resp.status_code == 200:
                    probed.append(st)
                    result.coverage.append(
                        f"serff[{st}]: portal reachable, no payload yet — run "
                        f"`python -m src.connectors.serff_browser --state {st} --no-details`"
                    )
                else:
                    down.append(st)
                    result.coverage.append(f"serff[{st}]: HTTP {resp.status_code} at {url}")
            except Exception as exc:
                down.append(st)
                result.coverage.append(f"serff[{st}]: unreachable ({exc})")

        n_total = ctx.conn.execute("SELECT COUNT(*) FROM serff_filings").fetchone()[0]
        result.http_status = 200
        result.status = "ok"
        result.message = (
            f"imported {total_rows} filings from {len(imported)} state payload(s); "
            f"probe-only={len(probed)} custom={len(custom)} down={len(down)}"
        )
        result.coverage.append(
            f"serff: SUMMARY — serff_filings table now {n_total} rows "
            f"(filing grain, not products). Payloads: {', '.join(imported) or 'none'}; "
            f"pending: {', '.join(probed + custom) or 'none'}"
        )
        return result

    @staticmethod
    def search_url_hint(state: str) -> str:
        """Entry point the browser extractor opens for a shared-portal state."""
        return serff_states.portal_url(state)
