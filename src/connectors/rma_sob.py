"""RMA Summary of Business connector — the MARKET-REALITY dimension (opt-in, gated).

Populates `sob_sales`: which FEDERAL insurance plans actually SOLD, WHERE (state x county),
on WHICH crop, and HOW MUCH (net acres, liability, premium, subsidy, indemnity, policies), from
RMA's public "State/County/Crop with Coverage Level" file, `sobcov_<year>.zip`. Where the ADM
(rma_adm) answers *where a plan is offered*, this answers *where it was bought and for how much*.

Grain: the source file is one row per
    state x county x crop x plan x coverage-category x delivery-type x coverage-level.
We AGGREGATE up to the catalog's grain — year x state x county x crop x plan — summing the
dollar / acre / policy measures. Plan codes join the catalog's federal products via
products.plan_code (semicolon lists), REUSING rma_adm's plan/crop mapping (plan_map_for_products,
crop_for_offer, ADM_ROW_CROP_CODES, SUPPLEMENTAL_PLAN_CODES) so the row-crop gate, the Spring-Wheat
relabel for MP/MCO, and the WFRP whole-farm pseudo-crop stay identical across the two RMA
connectors. Non-row-crop commodities and plan codes not present in the catalog are dropped.

AIP grain: this public file carries NO AIP / company identifier, so `sob_sales` is PLAN grain,
not AIP grain. RMA does not publish AIP-identified Summary of Business at county x crop x plan
granularity, so which AIP wrote each dollar is not recoverable from this source.

Acres: base plans (YP/RP/...) report insured acres in "Net Reported Quantity"; the area /
endorsement plans this catalog tracks (SCO/STAX/ECO/MCO) report theirs in "Endorsed/Companion
Acres" and leave Net Reported Quantity at 0. `sob_net_acres` takes the net when present, else the
endorsed acres, so net_acres is meaningful for both kinds.

Cost: `sobcov_<year>.zip` is ~3 MB (~32 MB / ~176k rows uncompressed). Like rma_adm the download is
gated behind --force: without --force the connector only resolves the source file and reports what
it would do. The [sources] toggle `rma_sob = off` keeps it out of `--source all` unless enabled.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .. import config
from .base import Connector, ConnectorResult, Context
# Reuse the ADM connector's (pure, unit-tested) plan/crop mapping so the two RMA connectors agree.
from .rma_adm import (
    SUPPLEMENTAL_PLAN_CODES,
    crop_for_offer,
    plan_map_for_products,
)

SOB_CACHE_DIR = config.CACHE_DIR / "sob"

# Positional column layout of sobcov_<year>.txt (pipe-delimited, NO header row). Verified against
# RMA's "Crop Insurance Experience with Coverage Level (1989 Forward)" record layout, 28 fields.
SOBCOV_FIELDS = [
    "commodity_year", "state_code", "state_abbrev", "county_code", "county_name",
    "commodity_code", "commodity_name", "plan_code", "plan_abbrev", "coverage_category",
    "delivery_type", "coverage_level", "policies_sold", "policies_earning_premium",
    "policies_indemnified", "units_earning_premium", "units_indemnified", "quantity_type",
    "net_reported_quantity", "endorsed_companion_acres", "liability", "total_premium",
    "subsidy", "state_private_subsidy", "additional_subsidy", "efa_premium_discount",
    "indemnity", "loss_ratio",
]


# ---------------------------------------------------------------------------
# Pure parsing / aggregation helpers (unit-tested without network)
# ---------------------------------------------------------------------------

def _to_float(v: str | None) -> float:
    v = (v or "").strip()
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def _to_int(v: str | None) -> int:
    return int(_to_float(v))


def parse_sob_rows(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """Yield dict rows from a pipe-delimited sobcov file (positional, no header)."""
    for line in lines:
        line = line.rstrip("\r\n")
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < len(SOBCOV_FIELDS):
            continue
        yield dict(zip(SOBCOV_FIELDS, parts))


def sob_net_acres(row: dict[str, str]) -> float:
    """Insured acres for one sobcov row.

    Base plans carry them in Net Reported Quantity (only when the quantity type is Acres — some
    crops report tons/colonies/trees); endorsements (SCO/STAX/ECO/MCO) leave that 0 and carry the
    insured acreage in Endorsed/Companion Acres.
    """
    is_acres = "Acres" in (row.get("quantity_type") or "")
    net = _to_float(row.get("net_reported_quantity")) if is_acres else 0.0
    if net > 0:
        return net
    return _to_float(row.get("endorsed_companion_acres"))


@dataclass
class _Agg:
    plan_abbrev: str = ""
    commodity_code: str = ""
    net_acres: float = 0.0
    liability: float = 0.0
    total_premium: float = 0.0
    subsidy: float = 0.0
    indemnity: float = 0.0
    policies_sold: int = 0


def aggregate_sob(rows: Iterable[dict[str, str]],
                  plan_to_pid: dict[str, int],
                  product_crop_set: set[tuple[int, str]],
                  year: int,
                  source: str) -> list[tuple]:
    """Reduce sobcov rows to sob_sales tuples at (year, state, county_fips, crop, plan_code) grain.

    Filters to plan codes present in the catalog's federal products (plan_to_pid) and to row crops
    (via crop_for_offer). Returns tuples ready for INSERT (without fetched_at):
        (year, state, county_fips, crop, commodity_code, plan_code, plan_abbrev,
         net_acres, liability, total_premium, subsidy, indemnity, policies_sold, source)
    """
    aggs: dict[tuple, _Agg] = {}
    for row in rows:
        plan_code = str(row.get("plan_code", "")).strip().zfill(2)
        pid = plan_to_pid.get(plan_code)
        if pid is None:
            continue
        crop = crop_for_offer(pid, plan_code, row.get("commodity_code", ""), product_crop_set)
        if crop is None:
            continue
        state = (row.get("state_abbrev") or "").strip()
        fips = str(row.get("state_code", "")).zfill(2) + str(row.get("county_code", "")).zfill(3)
        key = (year, state, fips, crop, plan_code)
        agg = aggs.get(key)
        if agg is None:
            agg = aggs[key] = _Agg()
        if not agg.plan_abbrev:
            agg.plan_abbrev = (row.get("plan_abbrev") or "").strip()
        if not agg.commodity_code:
            agg.commodity_code = str(row.get("commodity_code", "")).zfill(4)
        agg.net_acres += sob_net_acres(row)
        agg.liability += _to_float(row.get("liability"))
        agg.total_premium += _to_float(row.get("total_premium"))
        agg.subsidy += _to_float(row.get("subsidy"))
        agg.indemnity += _to_float(row.get("indemnity"))
        agg.policies_sold += _to_int(row.get("policies_sold"))

    out: list[tuple] = []
    for (yr, state, fips, crop, plan_code), a in aggs.items():
        out.append((yr, state, fips, crop, a.commodity_code, plan_code, a.plan_abbrev,
                    round(a.net_acres, 2), round(a.liability, 2), round(a.total_premium, 2),
                    round(a.subsidy, 2), round(a.indemnity, 2), a.policies_sold, source))
    return out


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class RmaSob(Connector):
    name = "rma_sob"
    bucket = "508h"   # informational; the SoB is federal-plan grain, not AIP-specific

    # -- source resolution -------------------------------------------------
    def _resolve_year(self, ctx: Context, year: int) -> tuple[int, str] | None:
        """Return (year, sobcov_zip_url), falling back one year if the requested year isn't posted."""
        base = ctx.cfg.rma_sob_base_url
        if not base.endswith("/"):
            base += "/"
        for y in (year, year - 1):
            url = f"{base}sobcov_{y}.zip"
            try:
                listing = ctx.client.get(base).text
            except Exception:
                listing = ""
            if f"sobcov_{y}.zip" in listing:
                return y, url
        return None

    def _extract_txt(self, ctx: Context, zip_url: str, year: int) -> Path:
        """Download the (small) zip through the url_cache and extract its single txt member."""
        local = ctx.client.download(zip_url, force=ctx.force)
        with zipfile.ZipFile(local) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
            dest = SOB_CACHE_DIR / Path(member).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.exists() and dest.stat().st_size > 0):
                with zf.open(member) as src, open(dest, "wb") as out:
                    while chunk := src.read(1 << 16):
                        out.write(chunk)
        return dest

    # -- main --------------------------------------------------------------
    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        want_year = ctx.year or ctx.cfg.reinsurance_year

        resolved = self._resolve_year(ctx, want_year)
        if resolved is None:
            result.status = "error"
            result.message = f"no sobcov zip found for {want_year} or {want_year - 1}"
            result.coverage.append(f"rma_sob: ERROR — {result.message}")
            return result
        year, zip_url = resolved
        source = f"sobcov_{year}"

        if not ctx.force:
            result.status = "skipped"
            result.message = f"resolved {zip_url}; skipped download (use --force)"
            result.coverage.append(
                f"rma_sob: resolved {zip_url} — NOT downloaded. Run "
                f"`refresh --source rma_sob --force` to fetch (~3 MB) and populate sob_sales.")
            return result

        # Federal products -> plan map (endorsements without a plan code are skipped, same as ADM).
        prods = [dict(r) for r in ctx.conn.execute(
            "SELECT product_id, name, plan_code FROM products "
            "WHERE bucket != 'private' ORDER BY product_id")]
        plan_to_pid, skipped = plan_map_for_products(prods)
        pid_name = {p["product_id"]: p["name"] for p in prods}
        product_crop_set = {(r["product_id"], r["crop"]) for r in ctx.conn.execute(
            "SELECT product_id, crop FROM product_crops")}

        txt_path = self._extract_txt(ctx, zip_url, year)
        with open(txt_path, encoding="utf-8", errors="replace") as fh:
            rows = aggregate_sob(parse_sob_rows(fh), plan_to_pid, product_crop_set, year, source)

        # Idempotent (re)populate: this connector owns sob_sales, so clear this year's rows and
        # reinsert. Re-runs leave the row count stable and never orphan a plan that stopped selling.
        fetched_at = _now_iso()
        ctx.conn.execute("DELETE FROM sob_sales WHERE year = ?", (year,))
        ctx.conn.executemany(
            """INSERT INTO sob_sales
                   (year, state, county_fips, crop, commodity_code, plan_code, plan_abbrev,
                    net_acres, liability, total_premium, subsidy, indemnity, policies_sold,
                    source, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(year, state, county_fips, crop, plan_code) DO UPDATE SET
                 commodity_code=excluded.commodity_code, plan_abbrev=excluded.plan_abbrev,
                 net_acres=excluded.net_acres, liability=excluded.liability,
                 total_premium=excluded.total_premium, subsidy=excluded.subsidy,
                 indemnity=excluded.indemnity, policies_sold=excluded.policies_sold,
                 source=excluded.source, fetched_at=excluded.fetched_at""",
            [r + (fetched_at,) for r in rows])
        ctx.conn.commit()

        # Coverage report: per federal product, county-row count + liability across states.
        by_pid: dict[int, dict] = {}
        for r in rows:
            pid = plan_to_pid[r[5]]            # plan_code -> product_id
            d = by_pid.setdefault(pid, {"rows": 0, "states": set(), "crops": set(), "lia": 0.0})
            d["rows"] += 1
            d["states"].add(r[1])
            d["crops"].add(r[3])
            d["lia"] += r[8]
        for pid in sorted(by_pid):
            d = by_pid[pid]
            short = re.search(r"\(([^)]+)\)$", pid_name[pid])
            label = short.group(1) if short else pid_name[pid]
            result.coverage.append(
                f"rma_sob: {label} — {d['rows']:,} county rows, ${d['lia']:,.0f} liability, "
                f"{len(d['states'])} states ({year})")
        if skipped:
            result.coverage.append(
                "rma_sob: skipped (no plan code — endorsements follow underlying policy): "
                + ", ".join(skipped))

        result.status = "ok"
        result.message = (f"sob_sales: {len(rows):,} rows from {source} "
                          f"(AIP grain not public — plan grain only)")
        return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
