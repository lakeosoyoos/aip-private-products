"""NASS Quick Stats county yield history — the input to the basis-risk estimator (opt-in, heavy).

WHY WE NEED IT. SCO, ECO, MCO and STAX settle on a COUNTY index; individual MPCI settles on
the producer's own unit. Whether the county trigger fires when a given farm actually loses money
is the entire farm-specific content of a row-crop recommendation, and answering it needs a
county yield HISTORY, which this repo did not hold. This connector loads it.

SOURCE. USDA NASS Quick Stats, the bulk file at
    https://www.nass.usda.gov/datasets/qs.crops_YYYYMMDD.txt.gz
Free, public, no key. (The Quick Stats *API* at quickstats.nass.usda.gov/api needs a personal
key — it answers 401 to an unauthenticated request — so the keyless bulk file is the honest
automatable path. The filename carries the build date and changes, so the connector reads the
directory index and takes the newest `qs.crops_*.txt.gz` rather than hard-coding a URL.)

SIZE. 1.13 GB gzipped / ~10 GB raw / ~24M rows, of which we keep ~1M. The download lands in
data/cache via http.Client (url_cache freshness gate + polite delay, same as every other
connector); the gzip is streamed and filtered in one pass, so nothing but the cached original
is ever written to disk. Gated behind --force like rma_adm/prf_adm: without it the connector
resolves the source file, reports what it would do, and stops.

WHAT WE KEEP, and why each filter is there
------------------------------------------
SOURCE_DESC = SURVEY        CENSUS yields exist only every 5 years — useless for a time series.
SECTOR/GROUP = CROPS/FIELD CROPS
STATISTICCAT_DESC in YIELD, AREA HARVESTED
                            AREA HARVESTED is loaded because the aggregation-scaling
                            calibration (below) needs the ACRES behind each reporting unit.
DOMAIN_DESC = TOTAL         drops the economic-class / area-operated breakouts.
COMMODITY_DESC in CORN, SOYBEANS, WHEAT, COTTON
                            The grain three, plus upland cotton — which is here because it is
                            the crop STAX settles on, and STAX cannot be estimated without it.
UNIT_DESC   PER CROP, from basisrisk.CROP_YIELD_UNIT / CROP_PLANTED_YIELD_UNIT, plus 'ACRES'
                            for area. The harvested-acre unit is the default; the NET PLANTED
                            variant includes abandonment and loads as the robustness check.
                            THE UNIT IS NOT THE SAME FOR EVERY CROP and must never be
                            hard-coded: corn, soybeans and wheat are BU / ACRE, COTTON IS
                            LB / ACRE. Accepting a blanket set of units instead of a per-crop
                            one is the one loading bug in this file that produces no error and
                            no implausible number — the estimator detrends into a unitless
                            ratio, so a 50x scale error leaves every CV and every probability
                            bit-identical. See src/basisrisk.py, section "UNITS".
                            The per-crop unit also drops corn SILAGE (TONS / ACRE), which is
                            not the insured grain crop.
AGG_LEVEL_DESC in COUNTY, AGRICULTURAL DISTRICT, STATE, NATIONAL
                            COUNTY is the series the endorsements settle on. The other three
                            are loaded because the model needs the farm/county variance ratio,
                            and how variance decays with aggregation area is the only public
                            evidence on it (src/basisrisk.py: aggregation_scaling).

WHAT WE DROP, deliberately
--------------------------
* COUNTY_CODE 998 "OTHER (COMBINED) COUNTIES" — NASS's residual bucket for counties whose
  individual estimate is suppressed. It is not a county, has no FIPS, and its composition
  changes year to year, so a time series built from it is meaningless.
* Non-numeric VALUEs: '(D)' withheld-disclosure, '(NA)', '(X)', '(Z)'. Never coerced to zero —
  a suppressed year is a MISSING year, and a zero would read as a total crop failure.
* Rows whose CLASS/PRACTICE grain we do not collapse: nothing is dropped here, it is stored.
* PIMA cotton (CLASS_DESC='PIMA'). A different insured commodity from upland — ADM 0022
  "Cotton Ex Long Staple" against upland's 0021 — and STAX does not cover it at all
  (16-STAX-0021 §2(a): "the insured crop will be all upland cotton"). It has 10 counties with
  a usable series, which supports nothing. Dropping it at load means `crop='Cotton'` in
  nass_county_yield means UPLAND cotton and only upland cotton, so a query that forgets to
  filter on class cannot silently blend two crops.

NOT collapsed, on purpose: wheat has no single county series (WINTER / SPRING, (EXCL DURUM) /
SPRING, DURUM / ALL CLASSES all appear, and which exists varies by county), and the Plains
split NON-IRRIGATED into CONTINUOUS CROP vs FOLLOWING SUMMER FALLOW — an RMA practice split.
Choosing one series per county is a modelling decision, so it happens downstream in
scripts/analysis/build_basis_risk.py and is recorded in basis_risk_county.class_used.

Cotton keeps CLASS_DESC='UPLAND' rather than being rewritten to 'ALL CLASSES': it is what NASS
says, and cotton genuinely has no ALL CLASSES county series to be confused with.
"""
from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from pathlib import Path

from ..basisrisk import CROP_PLANTED_YIELD_UNIT, CROP_YIELD_UNIT
from .base import Connector, ConnectorResult, Context

INDEX_URL = "https://www.nass.usda.gov/datasets/"
FILE_RE = re.compile(r"qs\.crops_(\d{8})\.txt\.gz")

# NASS COMMODITY_DESC -> canonical catalog crop name (src/rowcrops.py spelling).
COMMODITIES = {"CORN": "Corn", "SOYBEANS": "Soybeans", "WHEAT": "Wheat", "COTTON": "Cotton"}

# NASS CLASS_DESC values to drop outright, per crop. See "WHAT WE DROP" above.
DROP_CLASSES = {"Cotton": {"PIMA"}}

# The YIELD units we keep FOR EACH CROP — never a single blanket set. src/basisrisk.py is the
# one place these are declared, because it is the module whose every output is scale-invariant
# and therefore cannot detect getting them wrong. AREA HARVESTED is in acres for every crop.
KEEP_YIELD_UNITS = {
    crop: {CROP_YIELD_UNIT[crop], CROP_PLANTED_YIELD_UNIT[crop]} for crop in CROP_YIELD_UNIT
}
AREA_UNITS = {"ACRES"}

# NASS AGG_LEVEL_DESC -> our short label.
AGG_LEVELS = {
    "COUNTY": "COUNTY",
    "AGRICULTURAL DISTRICT": "DISTRICT",
    "STATE": "STATE",
    "NATIONAL": "NATIONAL",
}

# NASS's residual "everything we had to suppress" bucket — not a real county.
OTHER_COUNTIES_CODE = "998"

BATCH = 20_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_value(raw: str) -> float | None:
    """NASS VALUE -> float, or None when the cell is a suppression flag.

    NASS writes '(D)' (withheld to avoid disclosing an individual operation), '(NA)', '(X)'
    and '(Z)' in the same column as numbers, and thousands separators in the numbers. A
    suppressed year must come back None so the caller drops it; coercing to 0 would enter a
    total crop failure into the history.
    """
    v = (raw or "").strip().replace(",", "")
    if not v or v.startswith("("):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def loc_key(agg: str, state_fips: str, asd: str, county_ansi: str) -> str | None:
    """Stable location key per aggregation level, or None when the row is unusable."""
    if agg == "NATIONAL":
        return "US"
    if not state_fips:
        return None
    if agg == "STATE":
        return state_fips.zfill(2)
    if agg == "DISTRICT":
        return f"{state_fips.zfill(2)}-{asd.zfill(2)}" if asd else None
    if agg == "COUNTY":
        if not county_ansi or county_ansi.zfill(3) == OTHER_COUNTIES_CODE:
            return None
        return state_fips.zfill(2) + county_ansi.zfill(3)
    return None


def iter_rows(path: Path):
    """Stream the gzip and yield the tuples we keep. One pass, nothing else written to disk."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        header = fh.readline().rstrip("\r\n").split("\t")
        ix = {name: i for i, name in enumerate(header)}
        need = ("SOURCE_DESC", "COMMODITY_DESC", "STATISTICCAT_DESC", "AGG_LEVEL_DESC",
                "UNIT_DESC", "CLASS_DESC", "PRODN_PRACTICE_DESC", "UTIL_PRACTICE_DESC",
                "DOMAIN_DESC", "STATE_FIPS_CODE", "STATE_ALPHA", "ASD_CODE", "COUNTY_ANSI",
                "COUNTY_NAME", "YEAR", "VALUE")
        missing = [c for c in need if c not in ix]
        if missing:
            raise ValueError(f"NASS bulk file is missing expected columns: {missing}")
        i = {c: ix[c] for c in need}
        wide = max(i.values())

        for line in fh:
            r = line.rstrip("\r\n").split("\t")
            if len(r) <= wide:
                continue
            if r[i["SOURCE_DESC"]] != "SURVEY":
                continue
            crop = COMMODITIES.get(r[i["COMMODITY_DESC"]])
            if crop is None:
                continue
            stat = r[i["STATISTICCAT_DESC"]]
            if stat not in ("YIELD", "AREA HARVESTED"):
                continue
            if r[i["DOMAIN_DESC"]] != "TOTAL":
                continue
            cls = r[i["CLASS_DESC"]] or "ALL CLASSES"
            if cls in DROP_CLASSES.get(crop, ()):        # Pima: a different insured commodity
                continue
            unit = r[i["UNIT_DESC"]]
            # PER CROP. A blanket unit set would let cotton in at BU / ACRE (it has no such
            # series, so that is merely a silent miss) or — the real hazard — let a crop's
            # order-of-magnitude-different sibling series through, which nothing downstream
            # can detect because the estimator is scale-invariant. See the module docstring.
            keep = AREA_UNITS if stat == "AREA HARVESTED" else KEEP_YIELD_UNITS[crop]
            if unit not in keep:
                continue
            agg = AGG_LEVELS.get(r[i["AGG_LEVEL_DESC"]])
            if agg is None:
                continue
            # Corn's UTIL_PRACTICE_DESC separates GRAIN from SILAGE; the BU/ACRE unit filter
            # above already removes silage, but be explicit so a future unit change is safe.
            if crop == "Corn" and r[i["UTIL_PRACTICE_DESC"]] == "SILAGE":
                continue
            value = parse_value(r[i["VALUE"]])
            if value is None or value <= 0:
                continue
            try:
                year = int(r[i["YEAR"]])
            except ValueError:
                continue
            key = loc_key(agg, r[i["STATE_FIPS_CODE"]], r[i["ASD_CODE"]], r[i["COUNTY_ANSI"]])
            if key is None:
                continue
            yield (
                crop,
                stat,
                cls,
                r[i["PRODN_PRACTICE_DESC"]] or "ALL PRODUCTION PRACTICES",
                unit,
                agg,
                key,
                (r[i["STATE_ALPHA"]] or None) if agg != "NATIONAL" else None,
                key if agg == "COUNTY" else None,
                (r[i["ASD_CODE"]].zfill(2) if r[i["ASD_CODE"]] else None),
                (r[i["COUNTY_NAME"]] or None) if agg == "COUNTY" else None,
                year,
                value,
            )


class NassYield(Connector):
    name = "nass_yield"
    bucket = ""

    def resolve_url(self, ctx: Context) -> tuple[str, str]:
        """Return (url, build_date) for the newest qs.crops_* bulk file on the index page."""
        resp = ctx.client.get(INDEX_URL)
        resp.raise_for_status()
        stamps = sorted({m.group(1) for m in FILE_RE.finditer(resp.text)})
        if not stamps:
            raise ValueError(f"no qs.crops_*.txt.gz link found at {INDEX_URL}")
        return f"{INDEX_URL}qs.crops_{stamps[-1]}.txt.gz", stamps[-1]

    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        try:
            url, stamp = self.resolve_url(ctx)
        except Exception as exc:
            result.status = "error"
            result.message = f"{type(exc).__name__}: {exc}"
            result.coverage.append(f"nass_yield: ERROR resolving source — {exc}")
            return result

        if not ctx.force:
            result.status = "skipped"
            result.coverage.append(
                f"nass_yield: SKIPPED (heavy, opt-in). Newest bulk file is "
                f"qs.crops_{stamp}.txt.gz (~1.1 GB gz). Re-run with --force to load."
            )
            return result

        path = ctx.client.download(url, force=False)   # url_cache decides; --force is the gate above
        source = f"nass_qs_crops_{stamp}"
        fetched = _now_iso()

        conn = ctx.conn
        conn.execute("DELETE FROM nass_county_yield")
        batch, n = [], 0
        for row in iter_rows(Path(path)):
            batch.append(row + (source, fetched))
            if len(batch) >= BATCH:
                n += self._flush(conn, batch)
                batch.clear()
        n += self._flush(conn, batch)
        conn.commit()

        counts = dict(conn.execute(
            "SELECT agg_level, COUNT(*) FROM nass_county_yield GROUP BY agg_level").fetchall())
        counties = conn.execute(
            "SELECT COUNT(DISTINCT loc_key) FROM nass_county_yield "
            "WHERE agg_level='COUNTY' AND stat='YIELD'").fetchone()[0]
        span = conn.execute(
            "SELECT MIN(year), MAX(year) FROM nass_county_yield").fetchone()
        result.http_status = 200
        result.coverage.append(
            f"nass_yield: {n:,} observations (yield + area) from qs.crops_{stamp}.txt.gz — "
            f"{counties:,} counties, {span[0]}-{span[1]}; by level: "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(counts.items()))
        )
        # Per crop, WITH THE UNIT AND THE MEDIAN LEVEL. The median is the point: it is the only
        # figure in this whole pipeline that would move if a crop were loaded at the wrong
        # scale, so printing it at load time is the earliest a unit regression can be seen.
        for crop, unit, ncty, med in conn.execute(
                """SELECT crop, unit, COUNT(DISTINCT loc_key), AVG(value)
                     FROM nass_county_yield
                    WHERE stat='YIELD' AND agg_level='COUNTY' AND year >= 2015
                    GROUP BY crop, unit ORDER BY crop, unit"""):
            result.coverage.append(
                f"nass_yield:   {crop:<9} {unit:<24} {ncty:>5,} counties, "
                f"mean recent yield {med:,.1f}")
        result.coverage.append(
            "nass_yield: nass_county_yield is LOCAL ONLY — build_app_db.py must drop it "
            "(basis_risk_county carries the shipped result)."
        )
        return result

    @staticmethod
    def _flush(conn, batch) -> int:
        if not batch:
            return 0
        conn.executemany(
            """INSERT OR REPLACE INTO nass_county_yield
               (crop, stat, class_desc, practice, unit, agg_level, loc_key, state,
                county_fips, asd_code, county_name, year, value, source, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            batch,
        )
        return len(batch)


def _main() -> int:
    """Standalone runner: `.venv/bin/python -m src.connectors.nass_yield --force`."""
    import argparse

    from .. import config, db, http

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="Actually load (heavy).")
    ap.add_argument("--db", help="Override DB path.")
    args = ap.parse_args()

    cfg = config.load()
    conn = db.connect(args.db)
    db.init_db(conn)
    conn.execute("PRAGMA busy_timeout = 120000")
    ctx = Context(cfg=cfg, conn=conn, client=http.Client(cfg, conn), force=args.force)
    for line in NassYield().run(ctx).coverage:
        print(line)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
