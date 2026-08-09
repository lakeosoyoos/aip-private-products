"""DRP (Dairy Revenue Protection, plan code 83) data loader: offers, price discovery,
settled quarterly prices, milk yields, FMMO factors, subsidy, availability.

Feeds a DRP declaration optimizer the way src/prfdata.py feeds the PRF interval optimizer.

WHERE THE DATA IS
-----------------
Everything is a BULK zip; there is no DRP API and no per-item fallback is needed.

1. RMA livestock ADM tree (same server and rollover rules lrp_signal.py already uses for
   LRP), https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{RY}/ :
     {RY}_A00831_ADMDrpDraw_Quarterly_{YYYYMMDD}.zip         5,000 uniform draws / state / qtr
     {RY}_A00832_ADMDrpMilkYield_Quarterly_{YYYYMMDD}.zip    state expected/actual milk yield
     {RY}_A00833_ADMDrpDailyPrice_Daily_{YYYYMMDD}.zip       expected prices + sigmas (daily)
     {RY}_A00834_ADMDrpActualPrice_Quarterly_{YYYYMMDD}.zip  settled AMS prices
     {RY}_A00835_ADMDrpFmmoPricingFactor_Yearly_{YYYYMMDD}.zip  FMMO make allowances/yields
   Each zip holds ONE pipe-delimited member with a header row, named with 'AdmDrp' (mixed
   case) even though the zip says 'ADMDrp'. Files exist from RY2019 (DRP's first year).
   Record layouts are documented in the ADM layout PDF (data/cache/adm/AdmLayout.pdf,
   sections 'Drp Draw' / 'Drp Milk Yield' / 'Drp Daily Price' / 'Drp Actual Price' /
   'Drp Fmmo Pricing Factor').

2. Crop ADM, https://pubfs-rma.fpac.usda.gov/pub/References/actuarial_data_master/{RY}/
   {RY}_ADM_YTD.zip, for the dimension tables the livestock files only reference by id:
     A00030 InsuranceOffer  -> plan 83 offers (state x quarter x pricing option)
     A00070 SubsidyPercent  -> plan 83 subsidy by coverage level
     A00510 Practice / A00540 Type / A00480 Interval / A00520 State -> code names
   The YTD zip is ~2.7 GB and A00030 alone is ~345 MB uncompressed, so this module reuses
   connectors/rma_adm.py's HTTP range-read machinery AND stream-filters plan 83 while
   inflating: ~52 MB moves over the wire and only the ~800 matching rows are ever written
   to data/cache/drp/. Nothing large lands on disk.

WHY THERE IS NO drp_rate TABLE
------------------------------
RMA publishes no DRP premium rate table, and none exists to publish. M13 exhibit P18-1
(Plan 83, Premium Calculation) defines premium as a 5,000-iteration Monte Carlo:
    SimulatedLoss[seq]   = Round(MAX(ExpectedRevenueGuarantee
                                     - SimulatedRevenueAmount[seq], 0.00), 2)
    SimulatedLossAverage = ROUND(MAX(SUM(SimulatedLoss[seq]) / 5000.00,
                                     0.02 * DeclaredCoveredMilkProduction / 100.00), 2)
    TotalPremiumAmount   = ROUND(ROUND(SimulatedLossAverage * DeclaredShare
                                       * ProtectionFactor, 0) * LoadingFactor, 0)
    ProducerPremiumAmount= MAX(Round(TotalPremiumAmount - SubsidyAmount, 0), 1)
Every input is public and every input is loaded here, so premium is reproducible — it is
just not a lookup. Rates quoted by an AIP's system are that simulation, not a filed table.

GRAIN
-----
DRP is sold STATEWIDE: every plan-83 ADM offer carries County Code 998, so there is no
county table (the fact sheet's "available in all counties in all 50 states" is implemented
as one statewide offer per state). RY2026 has exactly 800 offers = 50 states x 8 quarterly
endorsements x 2 pricing options.

CLI:
    .venv/bin/python -m src.drpdata --rates --prices [--year 2026] [--force]
    .venv/bin/python -m src.drpdata --all --years 2019-2027
    .venv/bin/python -m src.drpdata --draws --year 2026      # heavy, opt-in (~1.25M rows)
"""
from __future__ import annotations

import csv
import io
import re
import struct
import zipfile
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

from . import config, db, http
from .connectors.rma_adm import http_range_zip, parse_pipe_table

LIVESTOCK_BASE = "https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{year}/"
DRP_CACHE_DIR = config.CACHE_DIR / "drp"

DRP_PLAN_CODE = "83"
DRP_COMMODITY_CODE = "0830"          # 'Milk', verified in ADM A00420
DRP_FIRST_YEAR = 2019                # DRP's first reinsurance year

# ADM A00540 Type, commodity 0830 (verified verbatim):
#   831|Class Price Option|CLPROP     832|Component Price Option|CMPROP
PRICING_OPTIONS = {"831": "Class", "832": "Component"}

# Policy parameter domains — the dials a producer declares, and therefore what an optimizer
# enumerates. Coverage levels also live in the DB (ADM A00070); these constants are the
# POLICY-documented domains, quoted from the 26-DRP Basic Provisions unless noted.
#   coverage level      26-DRP 3(c)(4): "between 80 and 95 percent, in increments of
#                       5 percentage points" — note DRP has no 0.70/0.75 and no CAT.
#   protection factor   26-DRP 3(c)(6): "between 1.00 and 1.5 in 0.05 increments"
#                       (P18 field 29: "A value of 1.00 to 1.50 in .05 increments.
#                       Default is 1.00"). P18-1 gives only the 9.99 format, so the bound
#                       is policy-derived, not ADM-derived.
#   class weighting     26-DRP 3(c)(1)(i)(A): "between 0 percent and 100 percent, in
#                       5 percentage point increments" — the Class III / Class IV split.
#   component weighting 26-DRP 3(c)(1)(ii)(C): same 0-100% in 5-point steps.
#   butterfat/protein   26-DRP 3(c)(1)(ii): butterfat "no less than 4.00 pounds and no more
#                       than 6.0 pounds, in 0.05-pound increments"; protein "no less than
#                       3.20 pounds and no more than 4.5 pounds". CAUTION: these WIDENED for
#                       2026 — the 2025 handbook's 3.25-5.50 / 2.75-4.50 no longer apply.
#   declared share      P18 field 26: "greater than zero and less than or equal to 1.0000".
# Declared covered milk production has NO purchase-time cap; it is trued up at indemnity by
# the 85%-of-marketings test (FCIC-20400U 28 D(1)(a)), and premium is not refunded for it.
COVERAGE_LEVELS = (0.80, 0.85, 0.90, 0.95)
PROTECTION_FACTORS = tuple(round(1.00 + 0.05 * i, 2) for i in range(11))   # 1.00 .. 1.50
WEIGHTING_FACTORS = tuple(round(0.05 * i, 2) for i in range(21))           # 0.00 .. 1.00
BUTTERFAT_TESTS = tuple(round(4.00 + 0.05 * i, 2) for i in range(41))      # 4.00 .. 6.00
PROTEIN_TESTS = tuple(round(3.20 + 0.05 * i, 2) for i in range(27))        # 3.20 .. 4.50

# The eight quarterly endorsements: ADM practice code = interval code + 700 (verified 1:1
# for RY2025 and RY2026). Interval names are relative ("Apr - Jun/Yr3 - Qtr2"); Yr1/Yr2/Yr3
# resolve to reinsurance_year - 1 / reinsurance_year / reinsurance_year + 1.
INTERVAL_RE = re.compile(r"Yr(\d)\s*-\s*Qtr(\d)", re.I)
QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without network)
# ---------------------------------------------------------------------------

def reinsurance_year(d: date | None = None) -> int:
    """RMA reinsurance year for a date: rolls on July 1 (same rule as lrp_signal.py)."""
    d = d or sales_today()
    return d.year + 1 if d.month >= 7 else d.year


def sales_today() -> date:
    """RMA sales 'today' in Central Time — the app may run on a UTC host."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        return date.today()


def num(v: str | None) -> float | None:
    """ADM numeric field -> float, with '' / whitespace meaning 'not published' (NULL)."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def iso_date(v: str | None) -> str | None:
    """ADM CCYYMMDD -> 'YYYY-MM-DD'; blank/garbage -> None."""
    v = (v or "").strip()
    if len(v) != 8 or not v.isdigit():
        return None
    return f"{v[:4]}-{v[4:6]}-{v[6:]}"


def resolve_quarter(interval_name: str, ry: int) -> tuple[int | None, int | None,
                                                          str | None, str | None]:
    """'Apr - Jun/Yr3 - Qtr2', RY2026 -> (2027, 2, '2027-04-01', '2027-06-30').

    The ADM states quarters relative to the reinsurance year: Yr1 = RY-1, Yr2 = RY,
    Yr3 = RY+1. Verified against sales behavior — for RY2026, interval 104
    'Jul - Sep/Yr2 - Qtr3' was the NEAREST quarter offered on the 2026-04-01 sales date,
    i.e. Jul-Sep 2026 = the RY itself.
    """
    m = INTERVAL_RE.search(interval_name or "")
    if not m:
        return None, None, None, None
    yr_rel, qtr = int(m.group(1)), int(m.group(2))
    if yr_rel not in (1, 2, 3) or qtr not in QUARTER_MONTHS:
        return None, None, None, None
    year = ry + (yr_rel - 2)
    m0, m1 = QUARTER_MONTHS[qtr]
    start = date(year, m0, 1)
    end = date(year + (m1 == 12), (m1 % 12) + 1, 1) - timedelta(days=1)
    return year, qtr, start.isoformat(), end.isoformat()


def parse_member(text: str) -> Iterator[dict[str, str]]:
    """Yield dict rows from a pipe-delimited ADM member (first line = header)."""
    return parse_pipe_table(io.StringIO(text))


def livestock_url(ry: int, record: str, name: str, cadence: str, stamp: str) -> str:
    """e.g. (2027, 'A00833', 'DrpDailyPrice', 'Daily', '20260805') -> the zip URL."""
    return (LIVESTOCK_BASE.format(year=ry)
            + f"{ry}_{record}_ADM{name}_{cadence}_{stamp}.zip")


def parse_listing(html: str, ry: int, record: str) -> list[str]:
    """File names for one record type out of a pubfs directory listing, sorted by date."""
    pat = re.compile(rf"{ry}_{record}_ADM[A-Za-z]+_[A-Za-z]+_(\d{{8}})\.zip")
    return sorted({m.group(0) for m in pat.finditer(html)},
                  key=lambda n: n.rsplit("_", 1)[1])


def offer_row(rec: dict[str, str], ry: int, state_abbrev: dict[str, str],
              interval_name: dict[str, str], source: str) -> tuple | None:
    """One ADM A00030 plan-83 record -> a drp_offer tuple (None if not a DRP offer)."""
    if str(rec.get("Insurance Plan Code", "")).strip() != DRP_PLAN_CODE:
        return None
    state = str(rec["State Code"]).zfill(2)
    type_code = str(rec["Type Code"]).strip()
    practice = str(rec["Practice Code"]).strip()
    interval = str(rec.get("Interval Code", "")).strip()
    name = interval_name.get(interval, "")
    qy, q, qs, qe = resolve_quarter(name, ry)
    return (ry, int(rec["ADM Insurance Offer ID"]),
            str(rec.get("Commodity Code", "")).zfill(4), DRP_PLAN_CODE,
            state, state_abbrev.get(state), str(rec.get("County Code", "")).strip(),
            type_code, PRICING_OPTIONS.get(type_code), practice, interval, name,
            qy, q, qs, qe, iso_date(rec.get("Deleted Date")), source, _now_iso())


def daily_price_row(rec: dict[str, str], source: str) -> tuple:
    """One A00833 record -> a drp_daily_price tuple.

    Class-priced offers publish class3/class4 and leave the component columns blank;
    component-priced offers do the reverse. Blank means 'not published for this option',
    which `num` maps to NULL — it is RMA's encoding, not missing data.
    """
    g = rec.get
    months = lambda base: (num(g(f"Month1 {base}")), num(g(f"Month2 {base}")),
                           num(g(f"Month3 {base}")))
    return (
        int(g("Reinsurance Year")), iso_date(g("Sales Effective Date")),
        int(g("ADM Insurance Offer ID")), int(g("Adm Drp Daily Price ID")),
        num(g("Loading Factor")),
        *months("Expected Class III Price"), *months("Expected Class IV Price"),
        *months("Class III Sigma"), *months("Class IV Sigma"),
        *months("Expected Butter Price"), *months("Expected Cheese Price"),
        *months("Expected Dry Whey Price"), *months("Expected Nonfat Dry Milk Price"),
        *months("Butter Sigma"), *months("Cheese Sigma"),
        *months("Dry Whey Sigma"), *months("Nonfat Dry Milk Sigma"),
        num(g("Expected Class III Price")), num(g("Expected Class IV Price")),
        num(g("Expected Butterfat Price")), num(g("Expected Protein Price")),
        num(g("Expected Other Solids Price")), num(g("Expected Nonfat Solids Price")),
        num(g("Component Price Weighting Factor Restricted Value")),
        num(g("Class Price Weighting Factor Restricted Value")),
        int(g("Adm Drp Milk Yield ID")) if g("Adm Drp Milk Yield ID", "").strip() else None,
        int(g("Adm Drp Actual Price ID")) if g("Adm Drp Actual Price ID", "").strip() else None,
        int(g("Adm Drp Fmmo Pricing Factor ID")) if g("Adm Drp Fmmo Pricing Factor ID", "").strip() else None,
        iso_date(g("Released Date")), iso_date(g("Filing Date")), source, _now_iso(),
    )


def actual_price_row(rec: dict[str, str], source: str) -> tuple:
    """One A00834 record -> a drp_actual_price tuple. `settled` flags a finished quarter."""
    g = rec.get
    months = lambda base: (num(g(f"Month1 Actual {base} Price")),
                           num(g(f"Month2 Actual {base} Price")),
                           num(g(f"Month3 Actual {base} Price")))
    c3, c4 = num(g("Actual ClassIII Price")), num(g("Actual ClassIV Price"))
    bf = num(g("Actual Butterfat Price"))
    return (
        int(g("Reinsurance Year")), int(g("Adm Drp Actual Price ID")),
        *months("Butter"), *months("Cheese"), *months("Dry Whey"), *months("Nonfat Dry Milk"),
        c3, c4, bf, num(g("Actual Protein Price")), num(g("Actual Other Solids Price")),
        num(g("Actual Nonfat Solids Price")),
        1 if (c3 is not None or bf is not None) else 0,
        iso_date(g("Released Date")), iso_date(g("Filing Date")), source, _now_iso(),
    )


def milk_yield_row(rec: dict[str, str], state_abbrev: dict[str, str], source: str) -> tuple:
    g = rec.get
    state = str(g("State Code", "")).zfill(2)
    return (int(g("Reinsurance Year")), int(g("Adm Drp Milk Yield ID")), state,
            state_abbrev.get(state), num(g("Expected Yield")), num(g("Actual Yield")),
            num(g("Expected Yield Standard Deviation")),
            iso_date(g("Released Date")), iso_date(g("Filing Date")), source, _now_iso())


def fmmo_row(rec: dict[str, str], source: str) -> tuple:
    g = rec.get
    return (int(g("Reinsurance Year")), int(g("Adm Drp Fmmo Pricing Factor ID")),
            num(g("Butter Manufacturing Yield")), num(g("Nonfat Dry Milk Manufacturing Yield")),
            num(g("Dry Whey Manufacturing Yield")), num(g("Cheese Manufacturing Yield Casein")),
            num(g("Cheese Manufacturing Yield Butterfat")), num(g("Butterfat Retention Rate")),
            num(g("Butterfat To Protein Ratio")), num(g("Butter Make Allowance")),
            num(g("Nonfat Dry Milk Make Allowance")), num(g("Dry Whey Make Allowance")),
            num(g("Cheese Make Allowance")),
            iso_date(g("Released Date")), iso_date(g("Filing Date")), source, _now_iso())


def draw_row(rec: dict[str, str], source: str) -> tuple:
    g = rec.get
    months = lambda base: (num(g(f"Month1 {base} Draw")), num(g(f"Month2 {base} Draw")),
                           num(g(f"Month3 {base} Draw")))
    return (int(g("Reinsurance Year")), int(g("Adm Drp Milk Yield ID")),
            int(g("Drp Draw Number")), str(g("State Code", "")).zfill(2),
            *months("ClassIII Price"), *months("ClassIV Price"),
            *months("Butter Price"), *months("Cheese Price"),
            *months("Dry Whey Price"), *months("Nonfat Dry Milk Price"),
            num(g("DRP Yield Draw Quantity")), source)


def subsidy_row(rec: dict[str, str], source: str) -> tuple | None:
    """One ADM A00070 record -> a drp_subsidy tuple, or None if not a plan-83 row."""
    if str(rec.get("Insurance Plan Code", "")).strip() != DRP_PLAN_CODE:
        return None
    if str(rec.get("Deleted Date", "")).strip():
        return None
    cov, pct = num(rec.get("Coverage Level Percent")), num(rec.get("Subsidy Percent"))
    if cov is None or pct is None:
        return None
    return (int(rec["Reinsurance Year"]), round(cov, 4),
            (rec.get("Coverage Type Code") or "").strip() or None, round(pct, 4),
            source, _now_iso())


# ---------------------------------------------------------------------------
# Fetch plumbing
# ---------------------------------------------------------------------------

def _client(conn) -> http.Client:
    return http.Client(config.load(), conn)


def _cache_path(name: str) -> Path:
    DRP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DRP_CACHE_DIR / name


def list_files(client: http.Client, ry: int, record: str) -> list[str]:
    """Directory listing of one DRP record type for a reinsurance year (bulk index)."""
    cache = _cache_path(f"listing_{ry}.html")
    if not cache.exists():
        resp = client.get(LIVESTOCK_BASE.format(year=ry))
        resp.raise_for_status()
        cache.write_text(resp.text, encoding="utf-8", errors="replace")
    return parse_listing(cache.read_text(encoding="utf-8", errors="replace"), ry, record)


def fetch_member(client: http.Client, ry: int, filename: str, *,
                 force: bool = False) -> str:
    """Download one DRP zip (cached under data/cache/drp/) and return its member text."""
    dest = _cache_path(filename)
    if force or not dest.exists():
        url = LIVESTOCK_BASE.format(year=ry) + filename
        path = client.download(url, force=force)
        dest.write_bytes(Path(path).read_bytes())
    with zipfile.ZipFile(dest) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        return zf.read(name).decode("utf-8", "replace")


def stream_adm_member(client: http.Client, ry: int, member_substring: str,
                      keep: Callable[[list[str]], bool] = lambda f: True) -> list[str]:
    """Stream-filter one member of the giant crop-ADM YTD zip, keeping matching lines.

    Reads the remote zip's central directory over HTTP Range (connectors/rma_adm.py),
    inflates the member chunk by chunk, and applies `keep(fields)` per line so only the
    handful of plan-83 rows are ever materialized. Returns [header, *kept lines].

    rma_adm.RangeZip.extract() writes a whole member to disk, which for A00030 is ~345 MB
    of which we want ~800 rows — so this walks the same _read/_stream primitives itself and
    filters mid-inflate. ~52 MB crosses the wire and nothing large touches disk.
    """
    cfg = client.cfg
    url = cfg.rma_adm_base_url.format(year=ry) + f"{ry}_ADM_YTD.zip"
    rz = http_range_zip(client.session, url, cfg.timeout_seconds)
    m = rz.find(member_substring)
    lh = rz._read(m.header_offset, m.header_offset + 29)
    nlen, elen = struct.unpack("<HH", lh[26:30])
    start = m.header_offset + 30 + nlen + elen

    dec = zlib.decompressobj(-15)
    buf = b""
    out: list[str] = []
    header_done = False

    def _handle(raw: bytes) -> None:
        nonlocal header_done
        line = raw.rstrip(b"\r").decode("utf-8", "replace")
        if not line:
            return
        if not header_done:
            out.append(line)
            header_done = True
        elif keep(line.split("|")):
            out.append(line)

    for chunk in rz._stream(start, start + m.csize - 1):
        buf += dec.decompress(chunk)
        *lines, buf = buf.split(b"\n")
        for raw in lines:
            _handle(raw)
    buf += dec.flush()
    for raw in buf.split(b"\n"):
        _handle(raw)
    return out


def _adm_dimension(client: http.Client, ry: int, member: str,
                   force: bool = False) -> list[dict[str, str]]:
    """Small ADM code table (Type/Practice/Interval/State), cached as text under drp/."""
    cache = _cache_path(f"{ry}_{member}.txt")
    if force or not cache.exists():
        lines = stream_adm_member(client, ry, member)
        cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list(parse_pipe_table(cache.read_text(encoding="utf-8").splitlines(True)))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_offers(conn, ry: int, *, client: http.Client | None = None,
                force: bool = False) -> int:
    """Populate drp_offer + drp_state for one reinsurance year (plan 83 only)."""
    client = client or _client(conn)
    source = f"adm_{ry}_ytd"

    states = {r["State Code"].zfill(2): r
              for r in _adm_dimension(client, ry, "A00520_State", force)}
    state_abbrev = {k: v["State Abbreviation"] for k, v in states.items()}
    intervals = {r["Interval Code"]: r["Interval Name"]
                 for r in _adm_dimension(client, ry, "A00480_Interval", force)}

    cache = _cache_path(f"{ry}_A00030_plan83.txt")
    if force or not cache.exists():
        # Field 7 (index 6) is Insurance Plan Code — checked positionally so the filter
        # runs without building a dict for all ~2.5M offer rows.
        lines = stream_adm_member(
            client, ry, "A00030_InsuranceOffer",
            keep=lambda f: len(f) > 6 and f[6] == DRP_PLAN_CODE)
        cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
    recs = list(parse_pipe_table(cache.read_text(encoding="utf-8").splitlines(True)))

    rows = [r for r in (offer_row(rec, ry, state_abbrev, intervals, source)
                        for rec in recs) if r]
    conn.executemany(
        """INSERT INTO drp_offer (reinsurance_year, offer_id, commodity_code, plan_code,
               state_code, state_abbrev, county_code, type_code, pricing_option,
               practice_code, interval_code, interval_name, quarter_year, quarter,
               quarter_start, quarter_end, deleted_date, source, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, offer_id) DO UPDATE SET
             commodity_code=excluded.commodity_code, state_code=excluded.state_code,
             state_abbrev=excluded.state_abbrev, county_code=excluded.county_code,
             type_code=excluded.type_code, pricing_option=excluded.pricing_option,
             practice_code=excluded.practice_code, interval_code=excluded.interval_code,
             interval_name=excluded.interval_name, quarter_year=excluded.quarter_year,
             quarter=excluded.quarter, quarter_start=excluded.quarter_start,
             quarter_end=excluded.quarter_end, deleted_date=excluded.deleted_date,
             source=excluded.source, fetched_at=excluded.fetched_at""", rows)

    # drp_state is a rollup of what was actually filed, not a second fetch.
    conn.executemany(
        """INSERT INTO drp_state (reinsurance_year, state_code, state_abbrev, state_name,
               n_quarters, n_pricing_options, source, fetched_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, state_code) DO UPDATE SET
             state_abbrev=excluded.state_abbrev, state_name=excluded.state_name,
             n_quarters=excluded.n_quarters, n_pricing_options=excluded.n_pricing_options,
             source=excluded.source, fetched_at=excluded.fetched_at""",
        [(ry, r["state_code"], r["state_abbrev"],
          (states.get(r["state_code"]) or {}).get("State Name"),
          r["nq"], r["npo"], source, _now_iso())
         for r in conn.execute(
             """SELECT state_code, state_abbrev, COUNT(DISTINCT practice_code) nq,
                       COUNT(DISTINCT type_code) npo
                FROM drp_offer WHERE reinsurance_year = ? GROUP BY state_code, state_abbrev""",
             (ry,))])
    conn.commit()
    return len(rows)


def load_subsidy(conn, ry: int, *, client: http.Client | None = None,
                 force: bool = False) -> int:
    """Populate drp_subsidy from ADM A00070 (record category 04, plan 83)."""
    client = client or _client(conn)
    cache = _cache_path(f"{ry}_A00070_plan83.txt")
    if force or not cache.exists():
        # Field 6 (index 5) is Insurance Plan Code in A00070.
        lines = stream_adm_member(client, ry, "A00070_SubsidyPercent",
                                  keep=lambda f: len(f) > 5 and f[5] == DRP_PLAN_CODE)
        cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
    recs = parse_pipe_table(cache.read_text(encoding="utf-8").splitlines(True))
    rows = [r for r in (subsidy_row(rec, f"adm_{ry}_ytd") for rec in recs) if r]
    conn.executemany(
        """INSERT INTO drp_subsidy (reinsurance_year, coverage_level, coverage_type_code,
               subsidy_pct, source, fetched_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, coverage_level) DO UPDATE SET
             coverage_type_code=excluded.coverage_type_code,
             subsidy_pct=excluded.subsidy_pct, source=excluded.source,
             fetched_at=excluded.fetched_at""", rows)
    conn.commit()
    return len(rows)


def _load_livestock(conn, ry: int, record: str, sql: str, build, *,
                    client: http.Client | None = None, force: bool = False,
                    limit: int | None = None, state_abbrev: dict | None = None) -> int:
    """Shared driver: every file of one DRP record type for a year -> upserts."""
    client = client or _client(conn)
    names = list_files(client, ry, record)
    if limit:
        names = names[-limit:]
    n = 0
    for name in names:
        text = fetch_member(client, ry, name, force=force)
        rows = [build(rec, name) if state_abbrev is None
                else build(rec, state_abbrev, name)
                for rec in parse_member(text)]
        conn.executemany(sql, rows)
        n += len(rows)
    conn.commit()
    return n


def load_daily_prices(conn, ry: int, *, client: http.Client | None = None,
                      force: bool = False, limit: int | None = None) -> int:
    """Populate drp_daily_price from every A00833 file published for the year."""
    cols = ("reinsurance_year, sales_date, offer_id, daily_price_id, loading_factor, "
            "m1_class3, m2_class3, m3_class3, m1_class4, m2_class4, m3_class4, "
            "m1_class3_sigma, m2_class3_sigma, m3_class3_sigma, "
            "m1_class4_sigma, m2_class4_sigma, m3_class4_sigma, "
            "m1_butter, m2_butter, m3_butter, m1_cheese, m2_cheese, m3_cheese, "
            "m1_dry_whey, m2_dry_whey, m3_dry_whey, m1_nfdm, m2_nfdm, m3_nfdm, "
            "m1_butter_sigma, m2_butter_sigma, m3_butter_sigma, "
            "m1_cheese_sigma, m2_cheese_sigma, m3_cheese_sigma, "
            "m1_dry_whey_sigma, m2_dry_whey_sigma, m3_dry_whey_sigma, "
            "m1_nfdm_sigma, m2_nfdm_sigma, m3_nfdm_sigma, "
            "expected_class3, expected_class4, expected_butterfat, expected_protein, "
            "expected_other_solids, expected_nonfat_solids, "
            "component_weight_restricted, class_weight_restricted, "
            "milk_yield_id, actual_price_id, fmmo_factor_id, released_date, filing_date, "
            "source, fetched_at")
    sql = (f"INSERT INTO drp_daily_price ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, sales_date, offer_id) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "sales_date", "offer_id")))
    return _load_livestock(conn, ry, "A00833", sql, daily_price_row,
                           client=client, force=force, limit=limit)


def load_actual_prices(conn, ry: int, *, client: http.Client | None = None,
                       force: bool = False) -> int:
    """Populate drp_actual_price. Files are INCREMENTAL — each quarterly release carries
    only the newly-settled records — so every file for the year must be replayed and the
    latest release wins per (reinsurance_year, actual_price_id)."""
    cols = ("reinsurance_year, actual_price_id, m1_butter, m2_butter, m3_butter, "
            "m1_cheese, m2_cheese, m3_cheese, m1_dry_whey, m2_dry_whey, m3_dry_whey, "
            "m1_nfdm, m2_nfdm, m3_nfdm, actual_class3, actual_class4, actual_butterfat, "
            "actual_protein, actual_other_solids, actual_nonfat_solids, settled, "
            "released_date, filing_date, source, fetched_at")
    sql = (f"INSERT INTO drp_actual_price ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, actual_price_id) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "actual_price_id"))
           # A later file may re-publish a record with the values still blank; never let
           # that erase a settlement we already have.
           + " WHERE excluded.settled >= drp_actual_price.settled")
    return _load_livestock(conn, ry, "A00834", sql, actual_price_row,
                           client=client, force=force)


def load_milk_yield(conn, ry: int, *, client: http.Client | None = None,
                    force: bool = False) -> int:
    client = client or _client(conn)
    state_abbrev = {r["State Code"].zfill(2): r["State Abbreviation"]
                    for r in _adm_dimension(client, ry, "A00520_State", force)}
    cols = ("reinsurance_year, milk_yield_id, state_code, state_abbrev, expected_yield, "
            "actual_yield, expected_yield_sd, released_date, filing_date, source, fetched_at")
    sql = (f"INSERT INTO drp_milk_yield ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, milk_yield_id) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "milk_yield_id")))
    return _load_livestock(conn, ry, "A00832", sql, milk_yield_row,
                           client=client, force=force, state_abbrev=state_abbrev)


def load_fmmo(conn, ry: int, *, client: http.Client | None = None,
              force: bool = False) -> int:
    cols = ("reinsurance_year, fmmo_factor_id, butter_mfg_yield, nfdm_mfg_yield, "
            "dry_whey_mfg_yield, cheese_mfg_yield_casein, cheese_mfg_yield_butterfat, "
            "butterfat_retention_rate, butterfat_to_protein_ratio, butter_make_allowance, "
            "nfdm_make_allowance, dry_whey_make_allowance, cheese_make_allowance, "
            "released_date, filing_date, source, fetched_at")
    sql = (f"INSERT INTO drp_fmmo_factor ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, fmmo_factor_id) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "fmmo_factor_id")))
    return _load_livestock(conn, ry, "A00835", sql, fmmo_row, client=client, force=force)


def load_draws(conn, ry: int, *, client: http.Client | None = None,
               force: bool = False) -> int:
    """Populate drp_draw from the LATEST A00831 file for the year. HEAVY (~1.25M rows,
    ~226 MB of text): opt-in only. Streams the zip member rather than reading it whole."""
    client = client or _client(conn)
    names = list_files(client, ry, "A00831")
    if not names:
        return 0
    name = names[-1]
    dest = _cache_path(name)
    if force or not dest.exists():
        dest.write_bytes(Path(client.download(
            LIVESTOCK_BASE.format(year=ry) + name, force=force)).read_bytes())
    cols = ("reinsurance_year, milk_yield_id, draw_number, state_code, "
            "m1_class3, m2_class3, m3_class3, m1_class4, m2_class4, m3_class4, "
            "m1_butter, m2_butter, m3_butter, m1_cheese, m2_cheese, m3_cheese, "
            "m1_dry_whey, m2_dry_whey, m3_dry_whey, m1_nfdm, m2_nfdm, m3_nfdm, "
            "yield_draw, source")
    sql = (f"INSERT INTO drp_draw ({cols}) "
           f"VALUES ({','.join('?' * len(cols.split(',')))}) "
           f"ON CONFLICT(reinsurance_year, milk_yield_id, draw_number) DO UPDATE SET "
           + ", ".join(f"{c.strip()}=excluded.{c.strip()}" for c in cols.split(",")
                       if c.strip() not in ("reinsurance_year", "milk_yield_id",
                                            "draw_number")))
    n = 0
    with zipfile.ZipFile(dest) as zf:
        member = next(m for m in zf.namelist() if m.lower().endswith(".txt"))
        with zf.open(member) as fh:
            rd = csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace"),
                                delimiter="|")
            batch = []
            for rec in rd:
                batch.append(draw_row(rec, name))
                if len(batch) >= 50_000:
                    conn.executemany(sql, batch); n += len(batch); batch = []
            if batch:
                conn.executemany(sql, batch); n += len(batch)
    conn.commit()
    return n


def load_year(conn, ry: int, *, rates: bool = True, prices: bool = True,
              draws: bool = False, force: bool = False,
              limit: int | None = None) -> dict[str, int]:
    """Load one reinsurance year. `rates` = the premium-simulation inputs and availability
    (offers, subsidy, milk yield, FMMO factors); `prices` = the expected/actual price series."""
    client = _client(conn)
    out: dict[str, int] = {}
    if rates:
        out["drp_offer"] = load_offers(conn, ry, client=client, force=force)
        out["drp_subsidy"] = load_subsidy(conn, ry, client=client, force=force)
        out["drp_milk_yield"] = load_milk_yield(conn, ry, client=client, force=force)
        out["drp_fmmo_factor"] = load_fmmo(conn, ry, client=client, force=force)
    if prices:
        out["drp_daily_price"] = load_daily_prices(conn, ry, client=client, force=force,
                                                   limit=limit)
        out["drp_actual_price"] = load_actual_prices(conn, ry, client=client, force=force)
    if draws:
        out["drp_draw"] = load_draws(conn, ry, client=client, force=force)
    return out


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def subsidy_schedule(conn, ry: int) -> dict[float, float]:
    """{0.80: 0.55, ...} for one reinsurance year."""
    return {r["coverage_level"]: r["subsidy_pct"] for r in conn.execute(
        "SELECT coverage_level, subsidy_pct FROM drp_subsidy WHERE reinsurance_year = ? "
        "ORDER BY coverage_level", (ry,))}


def offers_for(conn, ry: int, state: str, *, quarter_year: int | None = None,
               quarter: int | None = None) -> list:
    """drp_offer rows for a state (2-letter abbrev or 2-digit FIPS), newest quarter last."""
    col = "state_abbrev" if len(state) == 2 and state.isalpha() else "state_code"
    sql = (f"SELECT * FROM drp_offer WHERE reinsurance_year = ? AND {col} = ? "
           "AND deleted_date IS NULL")
    args: list = [ry, state.upper() if col == "state_abbrev" else state.zfill(2)]
    if quarter_year is not None:
        sql += " AND quarter_year = ?"; args.append(quarter_year)
    if quarter is not None:
        sql += " AND quarter = ?"; args.append(quarter)
    return list(conn.execute(sql + " ORDER BY quarter_year, quarter, pricing_option", args))


def quote_inputs(conn, ry: int, state: str, sales_date: str,
                 pricing_option: str = "Class") -> list:
    """Everything needed to price a declaration: one row per offered quarter on one sales
    date, joined across offer / daily price / milk yield / settled actuals.

    This is the optimizer's fact table — the DRP analogue of PRF's grid x interval matrix.
    """
    return list(conn.execute(
        """SELECT o.quarter_year, o.quarter, o.quarter_start, o.quarter_end,
                  o.pricing_option, o.practice_code, o.offer_id,
                  d.sales_date, d.loading_factor,
                  d.expected_class3, d.expected_class4,
                  d.expected_butterfat, d.expected_protein, d.expected_other_solids,
                  d.expected_nonfat_solids,
                  d.class_weight_restricted, d.component_weight_restricted,
                  y.expected_yield, y.actual_yield, y.expected_yield_sd,
                  a.actual_class3, a.actual_class4, a.actual_butterfat,
                  a.actual_protein, a.actual_other_solids, a.settled
             FROM drp_daily_price d
             JOIN drp_offer o
               ON o.reinsurance_year = d.reinsurance_year AND o.offer_id = d.offer_id
        LEFT JOIN drp_milk_yield y
               ON y.reinsurance_year = d.reinsurance_year AND y.milk_yield_id = d.milk_yield_id
        LEFT JOIN drp_actual_price a
               ON a.reinsurance_year = d.reinsurance_year AND a.actual_price_id = d.actual_price_id
            WHERE d.reinsurance_year = ? AND d.sales_date = ?
              AND o.state_abbrev = ? AND o.pricing_option = ?
            ORDER BY o.quarter_year, o.quarter""",
        (ry, sales_date, state.upper(), pricing_option)))


def sales_dates(conn, ry: int) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT sales_date FROM drp_daily_price WHERE reinsurance_year = ? "
        "ORDER BY sales_date", (ry,))]


def declaration_space(conn=None, ry: int | None = None) -> dict[str, int]:
    """Size of the candidate-declaration grid an optimizer enumerates — the DRP analogue of
    the PRF optimizer's 59,536 interval allocations.

    Per state x quarter x sales date:
        Class option     = coverage (4) x protection factor (11) x class weighting (21) = 924
        Component option = coverage (4) x protection factor (11) x component weighting (21) = 924
        ------------------------------------------------------------------------------ 1,848
    Times the (up to) 5 quarters offered on a sales date = 9,240 per state per sales date.

    Declared butterfat/protein tests are a further 41 x 27 = 1,107 combinations under the
    Component option. They are NOT multiplied in by default: they raise the guarantee and
    the premium together, and a producer's declaration should track their actual herd tests
    rather than be optimized freely. `with_tests` reports the full cross product for callers
    that do want to sweep them.

    Coverage-level count comes from the DB when a connection is given (ADM A00070), so a
    year where RMA filed a different set is reflected automatically.
    """
    covs = len(subsidy_schedule(conn, ry)) if conn is not None and ry is not None else 0
    covs = covs or len(COVERAGE_LEVELS)
    per_option = covs * len(PROTECTION_FACTORS) * len(WEIGHTING_FACTORS)
    per_quarter = per_option * len(PRICING_OPTIONS)
    return {
        "coverage_levels": covs,
        "protection_factors": len(PROTECTION_FACTORS),
        "weighting_factors": len(WEIGHTING_FACTORS),
        "per_pricing_option": per_option,
        "per_state_quarter_salesdate": per_quarter,
        "per_state_salesdate_5q": per_quarter * 5,
        "with_tests": per_option + per_option * len(BUTTERFAT_TESTS) * len(PROTEIN_TESTS),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_years(spec: str | None, default: int) -> list[int]:
    if not spec:
        return [default]
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(t) for t in spec.split(",") if t.strip()]


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Load RMA Dairy Revenue Protection (plan 83) data into the catalog DB.")
    ap.add_argument("--rates", action="store_true",
                    help="offers + subsidy + milk yield + FMMO factors (the premium-"
                         "simulation inputs and state availability)")
    ap.add_argument("--prices", action="store_true",
                    help="daily expected price discovery + settled quarterly prices")
    ap.add_argument("--draws", action="store_true",
                    help="RMA's 5,000 simulation draws (HEAVY: ~1.25M rows per year)")
    ap.add_argument("--all", action="store_true", help="--rates and --prices")
    ap.add_argument("--year", type=int, help="reinsurance year (default: current)")
    ap.add_argument("--years", help="range or list, e.g. 2019-2027 or 2025,2026")
    ap.add_argument("--limit", type=int,
                    help="only the N most recent daily price files (quick smoke load)")
    ap.add_argument("--force", action="store_true", help="refetch even when cached")
    ap.add_argument("--counts", action="store_true", help="print row counts and exit")
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)
    tables = ("drp_offer", "drp_state", "drp_subsidy", "drp_milk_yield",
              "drp_fmmo_factor", "drp_daily_price", "drp_actual_price", "drp_draw")

    if args.counts:
        for t in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t:18} {n:>10,}")
        conn.close()
        return

    rates = args.rates or args.all
    prices = args.prices or args.all
    if not (rates or prices or args.draws):
        rates = prices = True

    years = _parse_years(args.years, args.year or reinsurance_year())
    for ry in years:
        got = load_year(conn, ry, rates=rates, prices=prices, draws=args.draws,
                        force=args.force, limit=args.limit)
        print(f"RY{ry}: " + ", ".join(f"{k}={v:,}" for k, v in got.items()))

    print("\ntotals:")
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:18} {n:>10,}")
    for ry in years:
        subs = subsidy_schedule(conn, ry)
        if subs:
            print(f"  RY{ry} subsidy: "
                  + ", ".join(f"{int(k * 100)}%->{v:.3f}" for k, v in subs.items()))
    conn.close()


if __name__ == "__main__":
    _main()
