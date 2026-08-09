"""RMA Summary of Business connector — the REALIZED-EXPERIENCE dimension (opt-in, gated).

Where the ADM (rma_adm) answers *where a plan is offered*, this answers *what was bought, at
which coverage level and unit structure, and what it actually paid back*. It is the empirical
foundation for row-crop returns work: liability / premium / subsidy / indemnity by
year x state x county x crop x plan x coverage-type x coverage-level (+ unit structure).

TWO SOURCE FILES, because RMA splits the two decision dials across them
--------------------------------------------------------------------
* ``sobcov_<year>.zip`` — "Crop Insurance Experience with Coverage Level", 1989 forward.
  28 pipe-delimited fields, no header. Carries COVERAGE LEVEL, coverage category (CAT vs
  buy-up), and the POLICY / UNIT COUNTS. Carries no unit structure. Crop programs only:
  the livestock plans (81 LRP, 82 LGM, 83 DRP) are absent from it.
* ``sobtpu_<year>.zip`` — "Crop Insurance Experience: Coverage Level / Type / Practice /
  Unit Structure", 1999 forward. 27 fields. Carries coverage level AND UNIT STRUCTURE
  (OU/BU/EU/WU/UA/UD) plus type and practice, and it does include the livestock plans.
  It carries no policy or unit counts.
  Gotcha: its records are separated by a BARE CR (\\r), not \\n — ``for line in f`` sees the
  whole 92 MB file as one line. ``iter_records`` handles CR, LF and CRLF.

Verified against RMA's own record layouts (SOB_State_County_Crop_with_Coverage_Level_
1989_Forward.pdf and SOBTPU_External_All_Years.pdf, both in the same public directory) and
cross-checked plan-by-plan for 2015 and 2024: every crop plan's liability agrees to the
dollar between the two files; the only differences are the livestock plans, which sobcov
omits and the row-crop gate here drops anyway.

WHAT RMA DOES NOT PUBLISH HERE
------------------------------
* No AIP / company identifier at all. `sob_sales` is PLAN grain, never AIP grain — which
  company wrote each dollar is not recoverable from any public Summary of Business file.
* No unit structure before 1999 (sobtpu starts there), so `sob_unit` starts in 1999 and
  `sob_sales` rows carry no unit dimension.
* No policy or unit counts in the type/practice/unit file, so counts live only in the
  coverage-level tables (`sob_sales`, `sob_national`), never in `sob_unit`.
* Indemnity for an unsettled crop year is 0 by construction; 2026 (and much of 2025) has
  not run out yet, so realized-return math must exclude the open years.

TABLES (this connector owns all five)
-------------------------------------
* ``sob_sales``    county x crop x plan x coverage-type x coverage-level, from sobcov.
                   The detail table — millions of rows, LOCAL ONLY (build_app_db drops it).
* ``sob_national`` national rollup of the same, + policy/unit counts and the two ratios.
                   Small; this is what ships in data/catalog_app.db.
* ``sob_unit``     state x crop x plan x coverage-type x coverage-level x UNIT STRUCTURE,
                   from sobtpu (1999+). ~45 MB, so LOCAL ONLY as well.
* ``sob_unit_national`` its national rollup — the unit-structure table that ships.
* ``sob_year``     one row per crop year: what got loaded, whether it has finished developing
                   (`settled`), and its headline loss ratio. Provenance and smoke test in one.

The two ratios, on every rollup:
    loss_ratio                    = indemnity / total_premium
    indemnity_per_producer_dollar = indemnity / (total_premium - subsidy)
The second is the row-crop analogue of the per-$1 normalization the PRF and LRP work uses.
It is meaningless for CAT rows (coverage_type 'C'): CAT premium is 100% subsidised and the
producer pays only an administrative fee that appears nowhere in these files, so the
denominator collapses to ~0 and the ratio explodes. Filter to coverage_type='A' (buy-up) for
anything that compares producer economics across plans.

THE BUG THIS REPLACED
---------------------
The first version filtered every sobcov row through ``plan_map_for_products()`` — a map built
from the *catalog's* `products` table, which by design holds only the 16 privately-developed
508(h) / endorsement products (SCO, ECO, STAX, MP, MCO, PACE, HIP-WI, WFRP). Plan codes with
no catalog product — 01 YP, 02 RP, 03 RPHPE, 90 APH, 44/45 RA/CRC, 04/05 GRP/GRIP, 13 RI, ...
— hit ``plan_to_pid.get(plan_code) -> None`` and were dropped. That whitelist silently deleted
~97% of the market (2024: $104.8B of RP liability alone vs $2.0B for every 508(h) plan in the
old table combined). The catalog product map is now used only to LABEL rows (the MP/MCO
Spring-Wheat relabel), never to gate them; the only gate left is the row-crop commodity gate.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .base import Connector, ConnectorResult, Context
# Reuse the ADM connector's (pure, unit-tested) commodity mapping so the two RMA connectors
# agree on what counts as a row crop and on the WFRP whole-farm pseudo-crop.
from .rma_adm import (
    ADM_ROW_CROP_CODES,
    WFRP_COMMODITY_CODE,
    WFRP_CROP_LABEL,
    WFRP_PLAN_CODE,
    plan_map_for_products,
)

# Positional column layout of sobcov_<year>.txt (pipe-delimited, NO header row), 28 fields.
SOBCOV_FIELDS = [
    "commodity_year", "state_code", "state_abbrev", "county_code", "county_name",
    "commodity_code", "commodity_name", "plan_code", "plan_abbrev", "coverage_category",
    "delivery_type", "coverage_level", "policies_sold", "policies_earning_premium",
    "policies_indemnified", "units_earning_premium", "units_indemnified", "quantity_type",
    "net_reported_quantity", "endorsed_companion_acres", "liability", "total_premium",
    "subsidy", "state_private_subsidy", "additional_subsidy", "efa_premium_discount",
    "indemnity", "loss_ratio",
]

# Positional column layout of the sobtpu member (27 fields). Field names are deliberately
# aligned with SOBCOV_FIELDS where they mean the same thing so one canonicaliser serves both.
SOBTPU_FIELDS = [
    "commodity_year", "state_code", "state_name", "state_abbrev", "county_code",
    "county_name", "commodity_code", "commodity_name", "plan_code", "plan_abbrev",
    "coverage_category", "coverage_level", "delivery_type", "type_code", "type_name",
    "practice_code", "practice_name", "unit_structure", "unit_structure_name",
    "net_reported_quantity", "quantity_type", "liability", "total_premium", "subsidy",
    "indemnity", "loss_ratio", "endorsed_companion_acres",
]

# Coverage-category code -> label (sobcov element 10 / sobtpu element 11).
COVERAGE_TYPES = {"A": "Buy-up", "C": "CAT", "E": "Existing coverage policy", "L": "Limited"}

# Unit structure is not published before the sobtpu series begins.
UNIT_STRUCTURE_UNKNOWN = "NA"

FIRST_SOBCOV_YEAR = 1989
FIRST_SOBTPU_YEAR = 1999

# A crop year keeps developing long after harvest: claims are still being adjusted and paid for
# well over a year, so the newest years in the file understate their own indemnity. 2026 loaded at
# a 0.08 loss ratio and 2025 at 0.55 against a 0.91-0.93 mature level — including either would
# silently halve every ratio. Treat a year as settled only once it is this many years behind the
# newest crop year present (and has indemnities at all).
SETTLED_LAG_YEARS = 2


# ---------------------------------------------------------------------------
# Pure parsing helpers (unit-tested without network)
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


def iter_records(stream: Iterable[bytes]) -> Iterator[str]:
    """Yield text records from a byte stream, splitting on CR, LF or CRLF.

    sobcov uses CRLF; sobtpu uses a BARE CR. Reading the latter with ordinary line iteration
    yields one 92 MB "line", so both files go through this.
    """
    tail = ""
    for chunk in stream:
        if not chunk:
            continue
        text = tail + chunk.decode("utf-8", errors="replace")
        parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        tail = parts.pop()
        for p in parts:
            if p:
                yield p
    if tail:
        yield tail


def _read_chunks(fh, chunk_size: int = 1 << 20) -> Iterator[bytes]:
    while True:
        chunk = fh.read(chunk_size)
        if not chunk:
            return
        yield chunk


def parse_sob_rows(lines: Iterable[str],
                   fields: Sequence[str] = SOBCOV_FIELDS) -> Iterator[dict[str, str]]:
    """Yield dict rows from a pipe-delimited SoB file (positional, no header)."""
    n = len(fields)
    for line in lines:
        line = line.rstrip("\r\n")
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < n:
            continue
        yield dict(zip(fields, parts))


def sob_net_acres(row: dict[str, str]) -> float:
    """Insured acres for one SoB row.

    Base plans (YP/RP/APH/...) carry them in Net Reported Quantity, but only when the
    reporting level is acres — some commodities report tons/head/pounds/colonies/trees.
    Endorsements (SCO/STAX/ECO/MCO/MP) leave that 0 and carry the insured acreage in
    Endorsed/Companion Acres.
    """
    is_acres = "Acres" in (row.get("quantity_type") or "")
    net = _to_float(row.get("net_reported_quantity")) if is_acres else 0.0
    if net > 0:
        return net
    return _to_float(row.get("endorsed_companion_acres"))


# --- livestock (LRP 81 / LGM 82 / DRP 83) -------------------------------------------------
# These live ONLY in sobtpu: sobcov omits the livestock plans entirely (see the module
# docstring), so admitting them here can add rows to sob_unit and cannot add any to sob_sales.
LIVESTOCK_PLAN_CODES = {"81", "82", "83"}
LIVESTOCK_COMMODITY_CODES = {"0803": "Cattle", "0815": "Swine", "0847": "Dairy Cattle"}
# RMA files most recent LGM under 9999 "All Other Commodities" — 68% of 2024 and 80% of 2026
# plan-82 premium. Dropping those rows would discard four fifths of recent LGM; silently
# folding them into a named commodity would invent a split RMA did not publish. They are
# admitted under an explicit label instead, so the volume is visible and obviously
# unclassified. src.lgm.commodity_from_sob() recovers the real commodity from type code +
# quantity type for callers that need it; that recovery is deliberately NOT done here,
# because this function only sees commodity_code.
LIVESTOCK_UNCLASSIFIED_CODE = "9999"
LIVESTOCK_UNCLASSIFIED_LABEL = "Livestock (unclassified)"


def sob_crop(plan_code: str, commodity_code: str,
             plan_to_pid: dict[str, int] | None = None,
             product_crop_set: set[tuple[int, str]] | None = None) -> str | None:
    """Canonical catalog crop for one SoB row, or None to drop it.

    The ONLY gate is the row-crop commodity gate (ADM_ROW_CROP_CODES) plus the WFRP whole-farm
    pseudo-crop. `plan_to_pid` / `product_crop_set` are optional and are used for LABELLING
    only — they relabel wheat to 'Spring Wheat' for the products (MP, MCO) whose product_crops
    name spring wheat specifically. They must never be used to filter: doing that was the bug
    that hid every base plan (see the module docstring).
    """
    commodity_code = str(commodity_code).zfill(4)
    if plan_code == WFRP_PLAN_CODE:
        return WFRP_CROP_LABEL if commodity_code == WFRP_COMMODITY_CODE else None
    # Livestock is gated on the PLAN, not ADM_ROW_CROP_CODES, which has no 0803/0815/0847 —
    # so these rows used to fall through to None and vanish. LGM in particular was invisible
    # to this project entirely.
    if plan_code in LIVESTOCK_PLAN_CODES:
        if commodity_code == LIVESTOCK_UNCLASSIFIED_CODE:
            return LIVESTOCK_UNCLASSIFIED_LABEL
        return LIVESTOCK_COMMODITY_CODES.get(commodity_code)
    crop = ADM_ROW_CROP_CODES.get(commodity_code)
    if crop is None:
        return None
    if crop == "Wheat" and plan_to_pid and product_crop_set:
        pid = plan_to_pid.get(plan_code)
        if (pid is not None and (pid, "Wheat") not in product_crop_set
                and (pid, "Spring Wheat") in product_crop_set):
            return "Spring Wheat"
    return crop


@dataclass
class SobRecord:
    """One SoB row, canonicalised across the two file variants."""
    year: int
    state: str
    county_fips: str
    crop: str
    commodity_code: str
    plan_code: str
    plan_abbrev: str
    coverage_type: str          # A / C / E / L
    coverage_level: float       # 0.50 ... 0.95 (0 when the plan has none)
    unit_structure: str         # OU / BU / EU / WU / UA / UD, or 'NA' pre-1999
    net_acres: float
    liability: float
    total_premium: float
    subsidy: float
    indemnity: float
    policies_sold: int
    policies_earning_premium: int
    policies_indemnified: int
    units_earning_premium: int
    units_indemnified: int

    @property
    def producer_premium(self) -> float:
        """Premium actually paid out of pocket: total premium less the federal subsidy."""
        return self.total_premium - self.subsidy


def canonical_records(rows: Iterable[dict[str, str]], year: int, *,
                      plan_to_pid: dict[str, int] | None = None,
                      product_crop_set: set[tuple[int, str]] | None = None,
                      ) -> Iterator[SobRecord]:
    """Canonicalise parsed sobcov/sobtpu dicts, dropping non-row-crop commodities.

    Works for either variant: the two field lists share names for everything read here, and
    the fields only one variant carries (policy counts, unit structure) default sensibly.
    """
    for row in rows:
        plan_code = str(row.get("plan_code", "")).strip().zfill(2)
        crop = sob_crop(plan_code, row.get("commodity_code", ""), plan_to_pid, product_crop_set)
        if crop is None:
            continue
        yield SobRecord(
            year=year,
            state=(row.get("state_abbrev") or "").strip(),
            county_fips=(str(row.get("state_code", "")).strip().zfill(2)
                         + str(row.get("county_code", "")).strip().zfill(3)),
            crop=crop,
            commodity_code=str(row.get("commodity_code", "")).strip().zfill(4),
            plan_code=plan_code,
            plan_abbrev=(row.get("plan_abbrev") or "").strip(),
            coverage_type=(row.get("coverage_category") or "").strip() or "A",
            coverage_level=round(_to_float(row.get("coverage_level")), 4),
            unit_structure=(row.get("unit_structure") or "").strip() or UNIT_STRUCTURE_UNKNOWN,
            net_acres=sob_net_acres(row),
            liability=_to_float(row.get("liability")),
            total_premium=_to_float(row.get("total_premium")),
            subsidy=_to_float(row.get("subsidy")),
            indemnity=_to_float(row.get("indemnity")),
            policies_sold=_to_int(row.get("policies_sold")),
            policies_earning_premium=_to_int(row.get("policies_earning_premium")),
            policies_indemnified=_to_int(row.get("policies_indemnified")),
            units_earning_premium=_to_int(row.get("units_earning_premium")),
            units_indemnified=_to_int(row.get("units_indemnified")),
        )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# The three grains this connector materialises. Every element names a SobRecord attribute.
GRAIN_COUNTY = ("year", "state", "county_fips", "crop", "plan_code",
                "coverage_type", "coverage_level")
GRAIN_NATIONAL = ("year", "crop", "plan_code", "coverage_type", "coverage_level")
GRAIN_UNIT_STATE = ("year", "state", "crop", "plan_code", "coverage_type",
                    "coverage_level", "unit_structure")

_MEASURES = ("net_acres", "liability", "total_premium", "subsidy", "indemnity",
             "policies_sold", "policies_earning_premium", "policies_indemnified",
             "units_earning_premium", "units_indemnified")


class Accumulator:
    """Sum SoB measures into a chosen grain. `labels` are carried from the first row seen."""

    def __init__(self, grain: Sequence[str], labels: Sequence[str] = ("plan_abbrev",
                                                                      "commodity_code")):
        self.grain = tuple(grain)
        self.labels = tuple(labels)
        self.totals: dict[tuple, dict[str, float]] = {}
        self.tags: dict[tuple, dict[str, str]] = {}

    def add(self, rec: SobRecord) -> None:
        key = tuple(getattr(rec, g) for g in self.grain)
        tot = self.totals.get(key)
        if tot is None:
            tot = self.totals[key] = dict.fromkeys(_MEASURES, 0.0)
            self.tags[key] = {lab: getattr(rec, lab) for lab in self.labels}
        for m in _MEASURES:
            tot[m] += getattr(rec, m)

    def add_all(self, recs: Iterable[SobRecord]) -> int:
        n = 0
        for rec in recs:
            self.add(rec)
            n += 1
        return n

    def rows(self) -> Iterator[tuple[tuple, dict[str, str], dict[str, float]]]:
        for key, tot in self.totals.items():
            yield key, self.tags[key], tot

    def __len__(self) -> int:
        return len(self.totals)


def loss_ratio(indemnity: float, total_premium: float) -> float | None:
    """Realized loss ratio = indemnity / total premium (None when no premium was earned)."""
    return indemnity / total_premium if total_premium else None


def indemnity_per_producer_dollar(indemnity: float, total_premium: float,
                                  subsidy: float) -> float | None:
    """Indemnity per $1 of PRODUCER premium = indemnity / (total premium - subsidy).

    The row-crop analogue of the per-$1 normalization the PRF and LRP work uses: what the
    farmer got back for each dollar he actually paid, subsidy excluded.
    """
    producer = total_premium - subsidy
    return indemnity / producer if producer > 0 else None


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class RmaSob(Connector):
    name = "rma_sob"
    bucket = "508h"   # informational; the SoB is federal-plan grain, not AIP-specific

    # -- source resolution -------------------------------------------------
    def _listing(self, ctx: Context) -> str:
        base = ctx.cfg.rma_sob_base_url
        if not base.endswith("/"):
            base += "/"
        try:
            return ctx.client.get(base).text
        except Exception:
            return ""

    @staticmethod
    def _base(ctx: Context) -> str:
        base = ctx.cfg.rma_sob_base_url
        return base if base.endswith("/") else base + "/"

    def _years(self, ctx: Context, listing: str, prefix: str, first: int,
               end_year: int) -> list[int]:
        """Crop years whose <prefix>_<year>.zip is actually posted, oldest first."""
        start = max(first, int(getattr(ctx.cfg, f"rma_sob_{prefix}_start_year", first)))
        return [y for y in range(start, end_year + 1) if f"{prefix}_{y}.zip" in listing]

    # -- reading -----------------------------------------------------------
    def _records(self, ctx: Context, url: str, fields: Sequence[str], year: int,
                 plan_to_pid, product_crop_set) -> Iterator[SobRecord]:
        """Stream one year's records straight out of the cached zip (never extracted to disk:
        a single sobtpu member is ~92 MB of text and 28 of them would be 2.5 GB)."""
        local: Path = ctx.client.download(url, force=ctx.force)
        with zipfile.ZipFile(local) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
            with zf.open(member) as fh:
                rows = parse_sob_rows(iter_records(_read_chunks(fh)), fields)
                yield from canonical_records(rows, year, plan_to_pid=plan_to_pid,
                                             product_crop_set=product_crop_set)

    # -- writing -----------------------------------------------------------
    @staticmethod
    def _write(conn, table: str, cols: Sequence[str], acc: Accumulator, year: int,
               source: str, fetched_at: str, extra=None) -> int:
        """Idempotent per-year (re)populate: delete this year's rows, insert the new ones."""
        conn.execute(f"DELETE FROM {table} WHERE year = ?", (year,))
        payload = []
        for key, tags, tot in acc.rows():
            row = dict(zip(acc.grain, key))
            row.update(tags)
            row.update({k: round(v, 2) for k, v in tot.items()})
            row["producer_premium"] = round(row["total_premium"] - row["subsidy"], 2)
            for m in ("policies_sold", "policies_earning_premium", "policies_indemnified",
                      "units_earning_premium", "units_indemnified"):
                row[m] = int(row[m])
            if extra:
                extra(row)
            row["source"] = source
            row["fetched_at"] = fetched_at
            payload.append(tuple(row.get(c) for c in cols))
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})", payload)
        return len(payload)

    SALES_COLS = ("year", "state", "county_fips", "crop", "commodity_code", "plan_code",
                  "plan_abbrev", "coverage_type", "coverage_level", "net_acres", "liability",
                  "total_premium", "subsidy", "producer_premium", "indemnity", "policies_sold",
                  "policies_earning_premium", "policies_indemnified", "units_earning_premium",
                  "units_indemnified", "source", "fetched_at")
    NATIONAL_COLS = ("year", "crop", "commodity_code", "plan_code", "plan_abbrev",
                     "coverage_type", "coverage_level", "net_acres", "liability",
                     "total_premium", "subsidy", "producer_premium", "indemnity",
                     "policies_sold", "policies_earning_premium", "policies_indemnified",
                     "units_earning_premium", "units_indemnified", "loss_ratio",
                     "indemnity_per_producer_dollar", "source", "fetched_at")
    UNIT_COLS = ("year", "state", "crop", "commodity_code", "plan_code", "plan_abbrev",
                 "coverage_type", "coverage_level", "unit_structure", "net_acres",
                 "liability", "total_premium", "subsidy", "producer_premium", "indemnity",
                 "source", "fetched_at")

    @staticmethod
    def _ratios(row: dict) -> None:
        row["loss_ratio"] = loss_ratio(row["indemnity"], row["total_premium"])
        row["indemnity_per_producer_dollar"] = indemnity_per_producer_dollar(
            row["indemnity"], row["total_premium"], row["subsidy"])

    # -- main --------------------------------------------------------------
    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        end_year = ctx.year or ctx.cfg.reinsurance_year
        base = self._base(ctx)
        listing = self._listing(ctx)
        if not listing:
            result.status = "error"
            result.message = f"could not list {base}"
            result.coverage.append(f"rma_sob: ERROR — {result.message}")
            return result

        cov_years = self._years(ctx, listing, "sobcov", FIRST_SOBCOV_YEAR, end_year)
        tpu_years = self._years(ctx, listing, "sobtpu", FIRST_SOBTPU_YEAR, end_year)
        if not cov_years:
            result.status = "error"
            result.message = f"no sobcov zips found at {base} through {end_year}"
            result.coverage.append(f"rma_sob: ERROR — {result.message}")
            return result

        if not ctx.force:
            result.status = "skipped"
            result.message = (f"resolved sobcov {cov_years[0]}-{cov_years[-1]} "
                              f"({len(cov_years)} yrs) + sobtpu "
                              f"{tpu_years[0] if tpu_years else '-'}-"
                              f"{tpu_years[-1] if tpu_years else '-'}; "
                              f"skipped download (use --force)")
            result.coverage.append(
                f"rma_sob: resolved {len(cov_years)} sobcov + {len(tpu_years)} sobtpu files at "
                f"{base} — NOT downloaded. Run `refresh --source rma_sob --force` "
                f"(~270 MB total) to populate sob_sales / sob_national / sob_unit.")
            return result

        # Catalog product map — LABELLING ONLY (Spring-Wheat relabel for MP/MCO). Never a gate.
        prods = [dict(r) for r in ctx.conn.execute(
            "SELECT product_id, name, plan_code FROM products "
            "WHERE bucket != 'private' ORDER BY product_id")]
        plan_to_pid, _ = plan_map_for_products(prods)
        product_crop_set = {(r["product_id"], r["crop"]) for r in ctx.conn.execute(
            "SELECT product_id, crop FROM product_crops")}

        fetched_at = _now_iso()
        per_year: list[dict] = []

        for year in cov_years:
            source = f"sobcov_{year}"
            county = Accumulator(GRAIN_COUNTY)
            natl = Accumulator(GRAIN_NATIONAL)
            n_raw = 0
            for rec in self._records(ctx, f"{base}sobcov_{year}.zip", SOBCOV_FIELDS, year,
                                     plan_to_pid, product_crop_set):
                county.add(rec)
                natl.add(rec)
                n_raw += 1
            n_sales = self._write(ctx.conn, "sob_sales", self.SALES_COLS, county, year,
                                  source, fetched_at)
            n_natl = self._write(ctx.conn, "sob_national", self.NATIONAL_COLS, natl, year,
                                 source, fetched_at, extra=self._ratios)
            tot = _totals(natl)
            ctx.conn.execute(
                """INSERT OR REPLACE INTO sob_year
                       (year, sob_sales_rows, sob_national_rows, sob_unit_rows, plans,
                        liability, total_premium, subsidy, indemnity, loss_ratio,
                        settled, source, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (year, n_sales, n_natl, 0, len({k[2] for k in natl.totals}),
                 tot["liability"], tot["total_premium"], tot["subsidy"], tot["indemnity"],
                 loss_ratio(tot["indemnity"], tot["total_premium"]),
                 0, source, fetched_at))   # settled is set once every year is in (below)
            ctx.conn.commit()
            per_year.append({"year": year, "raw": n_raw, "sales": n_sales, "natl": n_natl,
                             **tot})

        for year in tpu_years:
            source = f"sobtpu_{year}"
            unit = Accumulator(GRAIN_UNIT_STATE)
            for rec in self._records(ctx, f"{base}sobtpu_{year}.zip", SOBTPU_FIELDS, year,
                                     plan_to_pid, product_crop_set):
                unit.add(rec)
            n_unit = self._write(ctx.conn, "sob_unit", self.UNIT_COLS, unit, year,
                                 source, fetched_at)
            rollup_unit_national(ctx.conn, year, source=source, fetched_at=fetched_at)
            ctx.conn.execute("UPDATE sob_year SET sob_unit_rows = ? WHERE year = ?",
                             (n_unit, year))
            ctx.conn.commit()

        mark_settled_years(ctx.conn)
        n_sales = ctx.conn.execute("SELECT COUNT(*) FROM sob_sales").fetchone()[0]
        n_unit = ctx.conn.execute("SELECT COUNT(*) FROM sob_unit").fetchone()[0]
        settled = [r["year"] for r in ctx.conn.execute(
            "SELECT year FROM sob_year WHERE settled = 1")]

        result.coverage.append(
            f"rma_sob: sob_sales {n_sales:,} rows over {len(cov_years)} crop years "
            f"({cov_years[0]}-{cov_years[-1]}); sob_unit {n_unit:,} rows over "
            f"{len(tpu_years)} years ({tpu_years[0] if tpu_years else '-'}-"
            f"{tpu_years[-1] if tpu_years else '-'}, unit structure not published earlier)")
        for p in per_year[-6:]:
            lr = loss_ratio(p["indemnity"], p["total_premium"])
            result.coverage.append(
                f"rma_sob: {p['year']} — {p['sales']:,} county rows, "
                f"${p['liability'] / 1e9:,.1f}B liability, "
                f"${p['total_premium'] / 1e9:,.2f}B premium, loss ratio "
                + (f"{lr:.2f}" if lr else "n/a")
                + ("" if p["year"] in settled else "  (still developing — excluded from ratios)"))
        result.coverage.append(
            "rma_sob: no AIP identifier is published in any Summary of Business file — "
            "plan grain only, never company grain.")

        result.status = "ok"
        result.message = (f"sob_sales {n_sales:,} rows, {len(cov_years)} crop years "
                          f"({len(settled)} settled); sob_unit {n_unit:,} rows")
        return result


def rollup_unit_national(conn, year: int, *, source: str, fetched_at: str) -> int:
    """Sum one year of sob_unit's state rows into sob_unit_national. Idempotent per year.

    Done in SQL off the table that was just written rather than from a second accumulator, so
    the shipped national numbers cannot drift from the local state detail they summarise.
    """
    conn.execute("DELETE FROM sob_unit_national WHERE year = ?", (year,))
    cur = conn.execute(
        """INSERT INTO sob_unit_national
               (year, crop, commodity_code, plan_code, plan_abbrev, coverage_type,
                coverage_level, unit_structure, net_acres, liability, total_premium, subsidy,
                producer_premium, indemnity, loss_ratio, indemnity_per_producer_dollar,
                source, fetched_at)
           SELECT year, crop, MIN(commodity_code), plan_code, MIN(plan_abbrev), coverage_type,
                  coverage_level, unit_structure,
                  ROUND(SUM(net_acres), 2), ROUND(SUM(liability), 2),
                  ROUND(SUM(total_premium), 2), ROUND(SUM(subsidy), 2),
                  ROUND(SUM(producer_premium), 2), ROUND(SUM(indemnity), 2),
                  CASE WHEN SUM(total_premium) > 0
                       THEN SUM(indemnity) / SUM(total_premium) END,
                  CASE WHEN SUM(producer_premium) > 0
                       THEN SUM(indemnity) / SUM(producer_premium) END,
                  ?, ?
           FROM sob_unit WHERE year = ?
           GROUP BY year, crop, plan_code, coverage_type, coverage_level, unit_structure""",
        (source, fetched_at, year))
    return cur.rowcount


def mark_settled_years(conn, lag: int = SETTLED_LAG_YEARS) -> list[int]:
    """Flag which crop years are mature enough to measure returns from. Returns the open years.

    Idempotent and safe to re-run: it recomputes the whole column from the years present.
    """
    newest = conn.execute("SELECT MAX(year) FROM sob_year").fetchone()[0]
    if newest is None:
        return []
    conn.execute("UPDATE sob_year SET settled = CASE WHEN year <= ? AND indemnity > 0 "
                 "THEN 1 ELSE 0 END", (newest - lag,))
    conn.commit()
    return [r[0] for r in conn.execute(
        "SELECT year FROM sob_year WHERE settled = 0 ORDER BY year")]


def _totals(acc: Accumulator) -> dict[str, float]:
    out = dict.fromkeys(("net_acres", "liability", "total_premium", "subsidy", "indemnity"), 0.0)
    for _key, _tags, tot in acc.rows():
        for k in out:
            out[k] += tot[k]
    return out


# ---------------------------------------------------------------------------
# Reporting helpers (read the shipped national table; pure SQL, unit-tested)
# ---------------------------------------------------------------------------

def _settled_clause(settled_only: bool) -> str:
    # An unsettled crop year has no indemnities yet, so including it drags every ratio to 0.
    return ("AND year IN (SELECT year FROM sob_year WHERE settled = 1)"
            if settled_only else "")


def rows_per_year(conn) -> list[dict]:
    """Per-crop-year load summary straight out of sob_year."""
    return [dict(r) for r in conn.execute(
        "SELECT year, sob_sales_rows, sob_national_rows, sob_unit_rows, plans, liability, "
        "total_premium, subsidy, indemnity, loss_ratio, settled "
        "FROM sob_year ORDER BY year")]


def experience_by(conn, dimension: str, *, year_min: int | None = None,
                  year_max: int | None = None, settled_only: bool = True,
                  min_premium: float = 0.0) -> list[dict]:
    """National realized experience grouped by one dimension of sob_national.

    dimension: 'plan_code', 'coverage_level', 'crop', 'coverage_type' or 'year'.
    Returns loss ratio (indemnity / total premium) and indemnity per $1 of PRODUCER premium
    (indemnity / (total premium - subsidy)) for each group.
    """
    allowed = {"plan_code", "coverage_level", "crop", "coverage_type", "year"}
    if dimension not in allowed:
        raise ValueError(f"dimension must be one of {sorted(allowed)}")
    where = ["1=1"]
    params: list = []
    if year_min is not None:
        where.append("year >= ?")
        params.append(year_min)
    if year_max is not None:
        where.append("year <= ?")
        params.append(year_max)
    sql = (f"SELECT {dimension} AS grp, "
           "       MIN(plan_abbrev) AS plan_abbrev, "
           "       COUNT(*) AS rows, MIN(year) AS year_min, MAX(year) AS year_max, "
           "       SUM(net_acres) AS net_acres, SUM(liability) AS liability, "
           "       SUM(total_premium) AS total_premium, SUM(subsidy) AS subsidy, "
           "       SUM(producer_premium) AS producer_premium, SUM(indemnity) AS indemnity, "
           "       SUM(policies_sold) AS policies_sold "
           f"FROM sob_national WHERE {' AND '.join(where)} {_settled_clause(settled_only)} "
           f"GROUP BY {dimension} ORDER BY liability DESC")
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        if d["total_premium"] < min_premium:
            continue
        d["loss_ratio"] = loss_ratio(d["indemnity"], d["total_premium"])
        d["indemnity_per_producer_dollar"] = indemnity_per_producer_dollar(
            d["indemnity"], d["total_premium"], d["subsidy"])
        d["subsidy_share"] = (d["subsidy"] / d["total_premium"]) if d["total_premium"] else None
        out.append(d)
    return out


def experience_by_unit_structure(conn, *, year_min: int | None = None,
                                 year_max: int | None = None,
                                 settled_only: bool = True,
                                 table: str = "sob_unit_national") -> list[dict]:
    """Same two ratios, grouped by unit structure (1999 forward only — see the module docstring).

    Reads the shipped national rollup by default; pass table='sob_unit' against a local working
    DB to slice the same numbers by state.
    """
    if table not in {"sob_unit", "sob_unit_national"}:
        raise ValueError("table must be sob_unit or sob_unit_national")
    where = ["1=1"]
    params: list = []
    if year_min is not None:
        where.append("year >= ?")
        params.append(year_min)
    if year_max is not None:
        where.append("year <= ?")
        params.append(year_max)
    sql = ("SELECT unit_structure AS grp, COUNT(*) AS rows, MIN(year) AS year_min, "
           "       MAX(year) AS year_max, SUM(liability) AS liability, "
           "       SUM(total_premium) AS total_premium, SUM(subsidy) AS subsidy, "
           "       SUM(producer_premium) AS producer_premium, SUM(indemnity) AS indemnity "
           f"FROM {table} WHERE {' AND '.join(where)} {_settled_clause(settled_only)} "
           "GROUP BY unit_structure ORDER BY liability DESC")
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["loss_ratio"] = loss_ratio(d["indemnity"], d["total_premium"])
        d["indemnity_per_producer_dollar"] = indemnity_per_producer_dollar(
            d["indemnity"], d["total_premium"], d["subsidy"])
        out.append(d)
    return out


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
