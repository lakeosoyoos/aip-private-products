"""PRF (Pasture, Rangeland, Forage) County Base Value connector (opt-in, heavy).

Populates `prf_county` — RMA's per-county **County Base Value ($/acre)** for the PRF
rainfall-index program (plan code 13, commodity 0088 "Pasture,Rangeland,Forage") — by
county x intended use (Grazing/Haying) x irrigation practice (Irrigated/Non-Irrigated)
x organic practice (Conventional/Organic/Transitional). The CBV is the dollar value that
scales PRF protection (acres x productivity factor x coverage level x CBV), so it is the
number the app's PRF county heat map colors on.

Where the number lives (verified against the 2026 ADM Record Layout, AdmLayout.pdf):
  Record A00810 "Price", field 34 "County Base Value" (Numeric 7, format 9999.99). The
  Price record is keyed by Commodity Code (f6), Insurance Plan Code (f7), State/County
  (f8/f9), Intended Use Code (f21), Irrigation Practice Code (f22), and Organic Practice
  Code (f24) — exactly the grain we need. PRF Price rows are Record Category 03 (Sub
  County / grid), so the same county CBV repeats across a county's grids; we reduce to one
  row per (county, use, irrigation, organic).

Code meanings come from the ADM reference tables (also verified live):
  Intended Use  (A00470): 007=Grazing, 030=Haying          -> we keep only these two.
  Irrigation    (A00490): 002=Irrigated, 003=Non-Irrigated, 997=No Practice Specified.
                          Grazing carries 997 (there is no irrigated/non-irrigated split
                          for grazing) -> mapped to Non-Irrigated, matching how RMA's PRF
                          grid locator presents a single grazing base value.
  Organic       (A00500): 001=Organic(Certified)->Organic, 002=Organic(Transitional)->
                          Transitional, 997=No Practice Specified->Conventional.

Apiculture (commodity 1191) and Annual Forage (commodity 0332) also ride the rainfall
index but are NOT pasture/rangeland/forage grazing & haying, so they are excluded by the
commodity filter (0088 only).

Reuse: the heavy remote-zip plumbing (range-read the 2.7 GB YTD zip's central directory,
extract + inflate just the members we need, cache under data/cache/adm/) is rma_adm's.
This connector borrows RmaAdm._resolve_year / _get_member and the RangeZip helpers rather
than re-implementing the download. Gated behind --force like rma_adm: without it the
connector only resolves the source file and reports what it would do.
"""
from __future__ import annotations

import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .base import Connector, ConnectorResult, Context
from .rma_adm import (
    ADM_CACHE_DIR,
    RmaAdm,
    http_range_zip,
    parse_pipe_table,
)

# What we pull out of the PRF slice of the Price record.
PRF_PLAN_CODE = "13"          # Rainfall Index / PRF
PRF_COMMODITY_CODE = "0088"   # Pasture,Rangeland,Forage (excludes Apiculture 1191, Annual Forage 0332)

# YTD zip members (matched by substring, same convention as rma_adm).
PRICE_MEMBER = "A00810_Price"
COUNTY_MEMBER = "A00440_County"
STATE_MEMBER = "A00520_State"

# ADM code -> readable string. None (via .get) means "drop this row".
USE_MAP = {"007": "Grazing", "030": "Haying"}
IRRIGATION_MAP = {"002": "Irrigated", "003": "Non-Irrigated", "997": "Non-Irrigated"}
ORGANIC_MAP = {"997": "Conventional", "001": "Organic", "002": "Transitional"}

# Columns we read out of the Price record (by ADM header name).
_NEEDED_COLUMNS = (
    "Commodity Code", "Insurance Plan Code", "State Code", "County Code",
    "Intended Use Code", "Irrigation Practice Code", "Organic Practice Code",
    "County Base Value", "Deleted Date",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pure mapping/aggregation (unit-tested without any download)
# ---------------------------------------------------------------------------

def map_use(code: str) -> str | None:
    return USE_MAP.get(str(code).zfill(3))


def map_irrigation(code: str) -> str | None:
    return IRRIGATION_MAP.get(str(code).zfill(3))


def map_organic(code: str) -> str:
    return ORGANIC_MAP.get(str(code).zfill(3), "Conventional")


def build_prf_rows(dict_rows: Iterable[dict[str, str]],
                   county_name: dict[str, str],
                   state_abbrev: dict[str, str],
                   year: int,
                   source: str,
                   fetched_at: str | None = None) -> list[tuple]:
    """Reduce Price-record dict rows to prf_county tuples.

    Filters to PRF (plan 13, commodity 0088), maps use/irrigation/organic codes to the
    readable strings, drops non-Grazing/Haying uses, and collapses the sub-county (grid)
    rows to one CBV per (county, use, irrigation, organic) via the median (only Hawaii's
    grazing is genuinely grid-priced; everywhere else the value is already constant).

    Returns tuples matching the prf_county column order:
      (year, state, county_fips, county_name, intended_use, irrigation_practice,
       organic_practice, county_base_value, source, fetched_at)
    """
    fetched_at = fetched_at or _now_iso()
    groups: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for r in dict_rows:
        if r.get("Deleted Date"):
            continue
        if str(r.get("Commodity Code", "")).zfill(4) != PRF_COMMODITY_CODE:
            continue
        if str(r.get("Insurance Plan Code", "")).zfill(2) != PRF_PLAN_CODE:
            continue
        use = map_use(r.get("Intended Use Code", ""))
        if use is None:
            continue
        irrigation = map_irrigation(r.get("Irrigation Practice Code", ""))
        if irrigation is None:
            continue
        organic = map_organic(r.get("Organic Practice Code", ""))
        raw_cbv = str(r.get("County Base Value", "")).strip()
        if not raw_cbv:
            continue
        try:
            cbv = float(raw_cbv)
        except ValueError:
            continue
        if cbv <= 0:
            continue
        fips = str(r.get("State Code", "")).zfill(2) + str(r.get("County Code", "")).zfill(3)
        groups[(fips, use, irrigation, organic)].append(cbv)

    out: list[tuple] = []
    for (fips, use, irrigation, organic), vals in groups.items():
        cbv = round(statistics.median(vals), 2)
        out.append((year, state_abbrev.get(fips[:2], fips[:2]), fips,
                    county_name.get(fips), use, irrigation, organic, cbv,
                    source, fetched_at))
    out.sort(key=lambda t: (t[2], t[4], t[5], t[6]))
    return out


def iter_price_prf_rows(path: Path) -> Iterator[dict[str, str]]:
    """Stream just the PRF (plan 13, commodity 0088) rows of the big Price file as dicts.

    A fast positional prefilter: the Price file is ~5.5M rows across every commodity, so we
    split each line, cheaply test the commodity/plan columns, and build a dict only for the
    ~2.2M PRF rows. Column positions are read from the header (robust to column reordering).
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        header = next(fh).rstrip("\r\n").split("|")
        idx = {name: header.index(name) for name in _NEEDED_COLUMNS if name in header}
        ci, pi = idx["Commodity Code"], idx["Insurance Plan Code"]
        for line in fh:
            parts = line.rstrip("\r\n").split("|")
            if len(parts) <= pi:
                continue
            if parts[ci].zfill(4) != PRF_COMMODITY_CODE:
                continue
            if parts[pi].zfill(2) != PRF_PLAN_CODE:
                continue
            yield {name: parts[i] for name, i in idx.items() if i < len(parts)}


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class PrfAdm(Connector):
    name = "prf_adm"
    bucket = "prf"

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        adm = RmaAdm()  # reuse its source-resolution + member-extract machinery
        want_year = ctx.year or ctx.cfg.reinsurance_year

        resolved = adm._resolve_year(ctx, want_year)
        if resolved is None:
            result.status = "error"
            result.message = f"no ADM YTD zip found for {want_year} or {want_year - 1}"
            result.coverage.append(f"prf_adm: ERROR — {result.message}")
            return result
        year, zip_url = resolved
        source = f"adm_{year}_ytd"

        if not ctx.force:
            result.status = "skipped"
            result.message = f"resolved {zip_url}; skipped download (use --force)"
            result.coverage.append(
                f"prf_adm: resolved {zip_url} — NOT downloaded. Run "
                f"`refresh --source prf_adm --force` to range-extract the Price record "
                f"(~150 MB) and populate prf_county."
            )
            return result

        # Range-extract the members we need; fall back to a full download only if the
        # server stops honoring Range requests (mirrors rma_adm).
        try:
            rz = http_range_zip(ctx.client.session, zip_url, ctx.cfg.timeout_seconds)
            price_path = adm._get_member(rz, year, PRICE_MEMBER)
            county_path = adm._get_member(rz, year, COUNTY_MEMBER)
            state_path = adm._get_member(rz, year, STATE_MEMBER)
        except RuntimeError:  # no Range support: heavy full-zip path via url_cache
            local = ctx.client.download(zip_url, force=ctx.force)
            with zipfile.ZipFile(local) as zf:
                def _extract(sub: str) -> Path:
                    name = next(n for n in zf.namelist() if sub in n)
                    dest = ADM_CACHE_DIR / Path(name).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(dest, "wb") as out:
                        while chunk := src.read(1 << 16):
                            out.write(chunk)
                    return dest
                price_path = _extract(PRICE_MEMBER)
                county_path = _extract(COUNTY_MEMBER)
                state_path = _extract(STATE_MEMBER)

        # Lookups: state code -> abbrev, 5-digit fips -> county name.
        with open(state_path, encoding="utf-8", errors="replace") as fh:
            state_abbrev = {r["State Code"].zfill(2): r["State Abbreviation"]
                            for r in parse_pipe_table(fh)}
        with open(county_path, encoding="utf-8", errors="replace") as fh:
            county_name = {r["State Code"].zfill(2) + r["County Code"].zfill(3):
                           r["County Name"] for r in parse_pipe_table(fh)}

        rows = build_prf_rows(iter_price_prf_rows(price_path), county_name,
                              state_abbrev, year, source)

        # Idempotent (re)populate: this connector owns prf_county for this year, so
        # clear-and-insert keeps stale county/use/practice rows from lingering, and the
        # ON CONFLICT keeps a re-run stable if the DELETE and INSERT are ever split.
        ctx.conn.execute("DELETE FROM prf_county WHERE year = ?", (year,))
        ctx.conn.executemany(
            """INSERT INTO prf_county
                   (year, state, county_fips, county_name, intended_use,
                    irrigation_practice, organic_practice, county_base_value,
                    source, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(year, county_fips, intended_use, irrigation_practice,
                           organic_practice) DO UPDATE SET
                 state=excluded.state, county_name=excluded.county_name,
                 county_base_value=excluded.county_base_value,
                 source=excluded.source, fetched_at=excluded.fetched_at""",
            rows)
        ctx.conn.commit()

        # Coverage report.
        counties = {t[2] for t in rows}
        by_use: dict[str, set] = defaultdict(set)
        for t in rows:
            by_use[t[4]].add(t[2])
        cbvs = sorted(t[7] for t in rows)
        lo, mid, hi = cbvs[0], statistics.median(cbvs), cbvs[-1]
        use_bits = ", ".join(f"{u} {len(c):,}" for u, c in sorted(by_use.items()))
        result.coverage.append(
            f"prf_adm: {len(counties):,} counties x 2 uses (Grazing/Haying), "
            f"CBV ${lo:,.2f}–${hi:,.2f}/ac (median ${mid:,.2f}) ({year}) — "
            f"{len(rows):,} rows [{use_bits} counties]"
        )
        result.status = "ok"
        result.message = (f"prf_county: {len(rows):,} rows, {len(counties):,} counties "
                          f"from {source} ({price_path.name})")
        return result
