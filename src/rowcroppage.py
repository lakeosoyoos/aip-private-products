"""Self-contained ROW-CROP OPPORTUNITY page — one county map, eight metrics.

WHAT IT ANSWERS
    "Which counties are most lucrative to work?" — for an agency deciding where to prospect,
    and, in the same picture, "what am I leaving unclaimed?" for a producer.

THE HEADLINE METRIC — UNCLAIMED SUBSIDY

    unclaimed subsidy ($) = eligible acres x (1 - penetration) x subsidy captured per acre

A producer on base MPCI alone who skips the supplemental bands leaves roughly $12-26 per acre
of FEDERAL money on the table (RY2026 book, computed from Summary of Business, not assumed:
ECO-RP $23.26/ac, MCO-RP $26.25/ac, SCO-RP $12.10/ac of subsidy per band acre sold), and the
bands return ~5.1x per producer dollar — 1/(1 - subsidy share) at FCIC's statutory target loss
ratio of 1.0 (7 U.S.C. 1506(n)(2)). Because agent commission is a percent of TOTAL premium
(subsidised portion included), the premium on those same unsold acres is the agency's
opportunity measured in the agency's own currency. One number, both audiences. See
src/rowcropopt.py for how it is computed and what is fitted rather than observed.

THE THREE FAMILIES, DELIBERATELY KEPT APART
    OPPORTUNITY  total / acre / pen  — what is unsold, in dollars and in percent
    PRODUCER     prodac / ret        — subsidy captured per acre, and return per producer $
    AGENCY       commac / commtot    — commission per acre, and unclaimed commission
    DIVERGENCE   gap                 — where those last two rank counties differently

`gap` exists because the correlation between the producer's interest and the agency's
incentive is high but not 1, and the difference is exactly the thing an honest tool should
draw rather than bury. Producer value per acre is subsidy per acre; agency value per acre is
premium per acre x a rate that varies BY REGION. `gap` is the county's percentile under the
agency metric minus its percentile under the producer metric, so a strongly positive county
is one an agency is drawn to more than a producer's own interest justifies. It is the only
metric here on a DIVERGING colour ramp, because it is the only one with a meaningful zero.

The producer's LEVERAGE (`ret`) is nearly flat nationwide, and that flatness is the finding,
not a rendering bug: the subsidy share is set in statute, not by geography. What varies from
county to county is how many dollars are at stake, never how good the deal is per dollar.

WHY THIS PAGE READS A PRECOMPUTED TABLE
    Penetration is county x crop x plan grain, and the ONLY county-grain source is `sob_sales`
    (3.23M rows). scripts/build_app_db.py DROPS it from the shipped app DB, so this page can
    never compute the metric at runtime. It reads `rowcrop_unclaimed` — exactly the pattern
    `prf_opt_best` establishes for PRF. An empty or missing table renders a valid, all-neutral
    map with a note naming the command to run, never a traceback.

DRILL-DOWN CHROME — TWO DETAILS THAT ARE NOT OPTIONAL
    Lifted from src/prfpage.py along with the #crumb breadcrumb and the log-scaled #zoomBox
    slider, because both were bugs there first:

      * ZOOM TRANSITIONS MUST APPLY INSTANTLY WHEN document.hidden. d3's transition scheduler
        is requestAnimationFrame-driven and browsers suspend rAF in a backgrounded tab, so an
        animated zoom started there never advances past CREATED: the map freezes mid-flight
        and stays frozen after you switch back. See `applyTransform` in the template.
      * POLYGON RINGS MUST BE WOUND CLOCKWISE in (lon, lat). d3-geo is spherical and takes the
        interior to be the region LEFT of the ring's travel — the opposite of GeoJSON's
        counter-clockwise-exterior convention — so a counter-clockwise ring renders as the
        whole globe minus the shape and floods the viewport. This page draws only us-atlas
        geometry, which is already wound correctly; `ring_clockwise` is exported and tested
        here anyway so the next contributor who hand-builds a ring finds the rule instead of
        rediscovering the bug.

    The drill-down stops at the COUNTY and says so. There is no lattice below it: SCO, ECO and
    STAX trigger on a COUNTY index, so the county is the finest grain RMA prices these bands
    at. Drilling into one opens its crop x band breakdown instead of inventing a sub-county
    geometry that does not exist.

WHAT THIS PAGE REFUSES TO CLAIM
    Penetration below 100% is not automatically opportunity, and the page says so on the page,
    not only in the docs — in the <summary> of the caveat block, which never collapses. An acre
    can be unsold because the producer is INELIGIBLE (STAX-designated acreage cannot carry SCO;
    through CY2025 ARC-elected acreage could not either, a bar OBBBA sec. 10303(b) repealed for
    CY2026 — see docs/rowcrop_endorsement_stacking.md), because the band is NOT OFFERED there
    (inferred from observed sales and graded in the `evidence` control, not read from ADM), or
    because the producer looked at BASIS RISK and rationally declined.

    That last one is no longer a warning: basis_risk_county is JOINED here, on county x crop x
    band, and shown as its own metric family, in every tooltip, in the legend and in the Top
    counties ranking. Half the map has no basis-risk estimate and that half is carried as an
    explicit UNKNOWN — hatched, not tinted, and excluded from the ranking rather than scored —
    because a county whose basis risk is unknown is not a county whose basis risk is low. See
    src/rowcropopt.py's join section and docs/rowcrop_opportunity.md.

    The commission rates come from data/seed/aip_commission.csv and
    data/seed/commission_by_timezone.csv via src/prfpage.py's own loaders — the same AIP x
    region model the PRF map uses, reused rather than reinvented. THE VALUES SHIPPED THERE ARE
    SAMPLE DATA. Every agency metric is labelled ASSUMED for that reason; every producer and
    opportunity metric is COMPUTED from RMA's published book.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from .prfpage import (
    STATE_TIMEZONE, load_aip_commission, load_commission_zones, seed_mtime,
)
from .rowcropopt import (
    ALL_CROPS, BAND_LABELS, BAND_ORDER, BASIS_BAND_NOTE, BASIS_COVERAGE_LEVEL, BASIS_COVERED,
    BASIS_CROP_NOTE, BASIS_GRADES, BASIS_PARTIAL, BASIS_PLAN_TYPE, BASIS_STATES, BASIS_TERMS,
    BASIS_UNKNOWN, MIN_BASIS_COVER, basis_variants, join_basis_risk, load_basis_risk,
)

__all__ = [
    "ALL_CROPS", "BAND_LABELS", "BAND_ORDER", "BASIS_CELL", "BASIS_LABELS", "BASIS_STATES",
    "STATE_TIMEZONE", "build_rowcrop_page_payload", "generate", "render",
    "render_rowcrop_page_html", "ring_clockwise", "seed_mtime",
]

# value_basis -> (short label, is it observed or fitted). Index order is the payload's wire
# format: a cell carries the INDEX, not the string, because the string repeats ~25,000 times.
BASIS_LABELS: tuple[str, ...] = ("county", "state", "national", "mixed")
BASIS_NOTE: dict[str, str] = {
    "county": "computed from this county's own band sales",
    "state": "fitted from this state's band sales and this county's liability per acre",
    "national": "fitted from national band sales and this county's liability per acre",
    "mixed": "part computed from this county's sales, part fitted (crops rolled up)",
}

# Evidence that the band is even OFFERED here. See src/rowcropopt.py.
EVIDENCE_LABELS: dict[int, str] = {
    2: "sold in this county",
    1: "sold elsewhere in this state",
    0: "not sold anywhere in this state",
}

DEFAULT_BAND = "ECO"
DEFAULT_EVIDENCE = 1        # the map opens on cells with at least state-level evidence

# Wire format for one joined basis-risk cell. Same reasoning as the opportunity cells above:
# an ARRAY of numbers, because the field names would otherwise repeat ~12,000 times. The order
# is load-bearing — the template's B_* constants index into it — and it is exported and tested
# for that reason.
#
# A county x crop x band with NO entry in `basis_risk` is UNKNOWN. Absence is the wire format
# for unknown deliberately: there is no sentinel a reader can accidentally treat as a low miss
# rate, and no default that quietly becomes one.
#
# Five of basis_risk_county's eight modelled terms ship. The two dropped from the WIRE (not
# from the table, the CLI report or docs/rowcrop_opportunity.md) are the bootstrap interval
# miss_rate_ci_lo/hi, because `grade` already carries what drives it — how many usable years
# the county series has — and windfall_rate, which is a property of the product rather than a
# term in this ranking. Each field costs ~90 KB of page across the country, against a payload
# that has to load in a Streamlit iframe.
BASIS_WIRE_DROP: frozenset[str] = frozenset(
    {"miss_rate_ci_lo", "miss_rate_ci_hi", "windfall_rate"})
# Derived by FILTERING rowcropopt.BASIS_TERMS rather than re-listed, so the wire can never
# drift out of the table's vocabulary or its order: the template indexes these positionally.
BASIS_WIRE_TERMS: tuple[str, ...] = tuple(t for t in BASIS_TERMS if t not in BASIS_WIRE_DROP)
BASIS_CELL: tuple[str, ...] = BASIS_WIRE_TERMS + ("grade_ix", "cover_share")


def ring_clockwise(ring):
    """Return `ring` wound CLOCKWISE in (lon, lat), reversing it if it is not.

    d3-geo is spherical: the interior of a polygon is the region to the LEFT of the ring's
    direction of travel, the opposite of GeoJSON's counter-clockwise convention. A
    counter-clockwise ring therefore renders as the entire globe minus the shape and floods
    the viewport with solid colour — the failure that bit src/prfpage.py the first time it
    drew PRF grid cells, and the reason src/drppage.py carries this same function.

    Orientation is the sign of the shoelace sum; positive is clockwise in the x-right / y-up
    frame that (lon, lat) is.

    This page draws only us-atlas geometry and so calls this on nothing. It is exported and
    tested regardless: row crops have no sub-county lattice to synthesize, which is exactly
    why the temptation to invent one has to be refused rather than met.
    """
    pts = list(ring)
    if len(pts) < 3:
        return pts
    area = 0.0
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        area += (x2 - x1) * (y2 + y1)
    return pts if area > 0 else pts[::-1]


def _fips5(value) -> str:
    s = str(value or "").strip()
    return s.zfill(5) if s else ""


def _f(value, nd: int | None = None):
    """float() or None, rounded — a value that could not be computed is never a 0."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v if nd is None else round(v, nd)


def _county_names(conn: sqlite3.Connection) -> dict[str, str]:
    """County display names from whatever county-grain table this DB happens to carry.

    prf_county and prf_grid_county both ship in the app DB and between them name every county
    Summary of Business reports on. Where neither has a name the template falls back to the
    us-atlas topology's own `properties.name`, so a missing row costs a nicer label and
    nothing else.
    """
    names: dict[str, str] = {}
    for table in ("prf_grid_county", "prf_county"):
        try:
            rows = conn.execute(
                f"SELECT county_fips, county_name FROM {table} "
                "WHERE county_name IS NOT NULL AND county_name != ''").fetchall()
        except sqlite3.OperationalError:
            continue
        for fips_raw, name in rows:
            fips = _fips5(fips_raw)
            if fips and fips not in names:
                names[fips] = str(name).strip()
    return names


def build_rowcrop_page_payload(conn: sqlite3.Connection, year=None,
                               commission_csv=None, timezone_csv=None) -> dict:
    """Everything the page needs, from rowcrop_unclaimed alone. Pure read; testable.

    Shape:
        counties[fips][crop_ix][band_ix]   = [base_acres, band_acres, sub_pa, prem_pa,
                                              evidence, basis_ix]
        basis_risk[fips][crop_ix][band_ix] = BASIS_CELL, or ABSENT when basis risk is UNKNOWN
        crops[crop_ix]  -> crop name, ALL_CROPS first
        bands[band_ix]  -> 'SCO' | 'ECO' | 'MCO' | 'STAX', in BAND_ORDER

    `basis_risk` is the join this page exists to make. It is a SEPARATE map rather than more
    slots on the opportunity cell because it is missing for roughly half of them — carrying
    nulls on every cell would cost more bytes than the terms themselves, and a null in a fixed
    slot is exactly the kind of thing a reader coerces to 0.

    Cells are ARRAYS of indices, not objects of strings: the same handful of crop names, band
    names and basis labels repeat across ~25,000 cells, and spelling them out every time is
    roughly 4x the payload for no extra information.

    Everything derived — unsold acres, unclaimed subsidy, per-acre figures, commission — is
    computed CLIENT-SIDE from these five numbers, because the crop, band, AIP and evidence
    controls all change it and precomputing every combination would be the same payload many
    times over.

    ONE crop year at a time, newest by default: the year axis is real (RY2026 is the first
    book under the raised SCO/ECO subsidy, so penetration jumped) but carrying several years
    multiplies the payload without changing which counties to work today. Pass `year` to look
    at an earlier book.

    A missing or empty rowcrop_unclaimed yields empty collections and None domains — a valid
    all-neutral map with an honest note, never an exception.
    """
    years: list[int] = []
    rows: list = []
    try:
        years = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT year FROM rowcrop_unclaimed ORDER BY year")]
    except sqlite3.OperationalError:
        years = []                                  # table not created yet

    # National penetration per band, and whether the band is in its FIRST book year. Both
    # matter to how the map should be read: a brand-new endorsement reads as almost entirely
    # "unclaimed" because nobody has had the chance to buy it yet, not because anyone is
    # overlooking it, and the page has to say so rather than let MCO top every ranking on its
    # debut. "New" is only claimed when the table actually holds a PRIOR year to compare
    # against — with one year loaded, every band would look new.
    band_summary: dict[str, dict] = {}
    chosen = None
    if years:
        chosen = int(year) if year is not None and int(year) in years else years[-1]
        try:
            hist = conn.execute(
                "SELECT band, year, SUM(base_acres), SUM(band_acres) FROM rowcrop_unclaimed "
                "WHERE crop = ? GROUP BY band, year", (ALL_CROPS,)).fetchall()
        except sqlite3.OperationalError:
            hist = []
        prior = [y for y in years if y < chosen]
        for b, y, base_ac, band_ac in hist:
            b = str(b or "").strip()
            slot = band_summary.setdefault(b, {"base": 0.0, "band": 0.0, "pen": None,
                                               "new": None, "prior_acres": 0.0})
            if int(y) == chosen:
                slot["base"] = _f(base_ac, 0) or 0.0
                slot["band"] = _f(band_ac, 0) or 0.0
            elif int(y) in prior:
                slot["prior_acres"] += _f(band_ac, 0) or 0.0
        for b, slot in band_summary.items():
            slot["pen"] = _f(slot["band"] / slot["base"], 4) if slot["base"] else None
            slot["new"] = (bool(prior) and slot["prior_acres"] <= 0 and slot["band"] > 0)
        rows = conn.execute(
            "SELECT county_fips, state, crop, band, base_acres, band_acres, sub_per_acre, "
            "       prem_per_acre, evidence, value_basis, penetration, pen_capped, "
            "       base_policies, return_per_dollar "
            "FROM rowcrop_unclaimed WHERE year = ?", (chosen,)).fetchall()

    # THE JOIN. basis_risk_county ships in the slim app DB alongside rowcrop_unclaimed (14,805
    # rows, ~5.5 MB), so this needs no third precomputed table — and a third table would be a
    # copy that can go stale against either parent. load_basis_risk() returns {} rather than
    # raising when the table is absent, which renders as "basis risk unknown everywhere": a
    # true statement, and the one the legend and tooltip are built to say out loud.
    br_index = load_basis_risk(conn)
    br_rows = [{"county_fips": r[0], "crop": r[2], "band": r[3], "base_acres": r[4]}
               for r in rows]
    joined = join_basis_risk(br_rows, br_index) if br_index else {}
    br_states = {s: 0 for s in BASIS_STATES}

    crop_ix: dict[str, int] = {}
    crop_list: list[str] = []

    def _crop(name: str) -> int:
        ix = crop_ix.get(name)
        if ix is None:
            ix = len(crop_list)
            crop_ix[name] = ix
            crop_list.append(name)
        return ix

    _crop(ALL_CROPS)                                # always index 0, always the default view
    band_ix = {b: i for i, b in enumerate(BAND_ORDER)}
    basis_ix = {b: i for i, b in enumerate(BASIS_LABELS)}

    counties: dict[str, dict] = {}
    basis_risk: dict[str, dict] = {}
    states: dict[str, str] = {}
    capped = 0
    bands_present: set[str] = set()
    crop_acres: dict[str, float] = {}
    grade_ix = {g: i for i, g in enumerate(BASIS_GRADES)}

    for (fips_raw, state, crop, band, base_ac, band_ac, sub_pa, prem_pa,
         evidence, basis, _pen, pen_capped, _pol, _ret) in rows:
        fips = _fips5(fips_raw)
        bi = band_ix.get(str(band or "").strip())
        if not fips or bi is None:
            continue
        base = _f(base_ac, 1)
        if not base or base <= 0:
            continue
        crop = str(crop or "").strip() or ALL_CROPS
        ci = _crop(crop)
        bands_present.add(BAND_ORDER[bi])
        capped += 1 if pen_capped else 0
        if crop != ALL_CROPS:
            crop_acres[crop] = max(crop_acres.get(crop, 0.0), 0.0) + base
        states.setdefault(fips, str(state or "").strip())
        (counties.setdefault(fips, {}).setdefault(str(ci), {}))[str(bi)] = [
            round(base),
            round(_f(band_ac, 1) or 0.0),
            _f(sub_pa, 3),
            _f(prem_pa, 3),
            int(evidence if evidence is not None else 0),
            basis_ix.get(str(basis or ""), -1),
        ]
        br = joined.get((fips, crop, BAND_ORDER[bi]))
        br_states[(br or {}).get("cover", BASIS_UNKNOWN)] += 1
        if br is not None:
            (basis_risk.setdefault(fips, {}).setdefault(str(ci), {}))[str(bi)] = (
                [_f(br.get(t), 3) for t in BASIS_WIRE_TERMS]
                + [grade_ix.get(br.get("grade"), -1), _f(br.get("cover_share"), 3)])

    # Crops in the order a user thinks of them: the rollup, then biggest acreage first. The
    # payload's cell keys are indices into `crop_list`, so the list is reordered and the map
    # from old index to new is applied to every cell rather than re-keying by name.
    tail = sorted(crop_list[1:], key=lambda c: (-crop_acres.get(c, 0.0), c))
    order = [ALL_CROPS] + tail
    remap = {str(crop_ix[c]): str(i) for i, c in enumerate(order)}
    counties = {fips: {remap[ci]: cells for ci, cells in by_crop.items()}
                for fips, by_crop in counties.items()}
    basis_risk = {fips: {remap[ci]: cells for ci, cells in by_crop.items()}
                  for fips, by_crop in basis_risk.items()}

    return {
        "generated": _dt.date.today().isoformat(),
        "year": chosen,
        "years": years,
        "crops": order,
        "all_crops": ALL_CROPS,
        "bands": list(BAND_ORDER),
        "bands_present": [b for b in BAND_ORDER if b in bands_present],
        "band_labels": dict(BAND_LABELS),
        "band_summary": band_summary,
        "basis": list(BASIS_LABELS),
        "basis_note": dict(BASIS_NOTE),
        "evidence_labels": {str(k): v for k, v in EVIDENCE_LABELS.items()},
        "default_band": DEFAULT_BAND if DEFAULT_BAND in bands_present else (
            sorted(bands_present)[0] if bands_present else DEFAULT_BAND),
        "default_evidence": DEFAULT_EVIDENCE,
        "counties": counties,
        "basis_risk": basis_risk,
        "basis_meta": {
            "cell": list(BASIS_CELL),
            "grades": list(BASIS_GRADES),
            "states": list(BASIS_STATES),
            "covered": BASIS_COVERED, "partial": BASIS_PARTIAL, "unknown": BASIS_UNKNOWN,
            "counts": br_states,
            "loaded": bool(br_index),
            "plan_type": BASIS_PLAN_TYPE,
            "coverage_level": BASIS_COVERAGE_LEVEL,
            "min_cover": MIN_BASIS_COVER,
            "variant": {b: (basis_variants(b)[0] if basis_variants(b) else None)
                        for b in BAND_ORDER},
            "band_note": dict(BASIS_BAND_NOTE),
            "crop_note": BASIS_CROP_NOTE,
        },
        "county_states": states,
        "county_names": _county_names(conn),
        "comm": load_aip_commission(commission_csv),
        "commzone": load_commission_zones(timezone_csv),
        "state_zone": dict(STATE_TIMEZONE),
        "row_count": len(rows),
        "county_count": len(counties),
        "capped_cells": capped,
    }


def _js_embed_json(obj) -> str:
    """JSON serialized for safe inline embedding inside a <script> block."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_rowcrop_page_html(payload: dict, d3_js: str, topojson_js: str,
                             atlas: dict) -> str:
    """Render the self-contained row-crop opportunity choropleth as one HTML string."""
    for blob in (d3_js, topojson_js):
        if "</script" in blob.lower():
            raise ValueError("asset JS contains '</script'; cannot inline safely")
    html = _TEMPLATE
    html = html.replace("__GENERATED__", str(payload.get("generated", "")))
    html = html.replace("__YEAR__", str(payload.get("year") or "—"))
    html = html.replace("__D3__", d3_js)
    html = html.replace("__TOPOJSON__", topojson_js)
    html = html.replace("__PAYLOAD__", _js_embed_json(payload))
    html = html.replace("__ATLAS__", _js_embed_json(atlas))
    return html


def generate(db_path=None, out_path=None, year=None):
    """Write the page to a file — the offline path, and what the tests exercise."""
    from pathlib import Path

    from . import config
    from .webmap import ensure_assets

    assets = ensure_assets()
    dbp = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload = build_rowcrop_page_payload(conn, year=year)
    finally:
        conn.close()
    html = render_rowcrop_page_html(payload, assets["d3.v7.min.js"],
                                    assets["topojson-client.min.js"],
                                    json.loads(assets["counties-10m.json"]))
    out = Path(out_path or (config.OUTPUT_DIR / "rowcrop_page.html"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB, "
          f"{payload['row_count']:,} rowcrop_unclaimed rows, "
          f"{payload['county_count']:,} counties, RY{payload['year']})")
    return out


# The Streamlit-cached helpers, built ONCE per process — same reasoning as src/drppage.py:
# a decorator re-applied on every rerun is a new function object and an easy way to defeat
# the cache it was added for.
_HELPERS: dict = {}


def _streamlit_helpers() -> dict:
    if _HELPERS:
        return _HELPERS
    import streamlit as st

    from .webmap import ensure_assets

    @st.cache_resource
    def _open(path: str):
        c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True,
                            check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    @st.cache_data(show_spinner="Building the row-crop opportunity map…")
    def _html(db_mtime: float, render_ver: float, seed_ver: float, path: str) -> str:
        # NOTE THE PARAMETER NAMES: st.cache_data drops underscore-prefixed arguments from the
        # cache key, so a cache-BUSTER must not be underscore-prefixed or the first render is
        # served forever on a warm container. seed_ver is the commission CSVs' mtime — the
        # agency metrics move when those are edited and the DB is not touched.
        assets = ensure_assets()
        payload = build_rowcrop_page_payload(_open(path))
        return render_rowcrop_page_html(payload, assets["d3.v7.min.js"],
                                        assets["topojson-client.min.js"],
                                        json.loads(assets["counties-10m.json"]))

    _HELPERS.update(open=_open, html=_html)
    return _HELPERS


def render() -> None:
    """Draw the row-crop opportunity map inside Streamlit, as rowcroppage.render().

    Opens its OWN read-only connection using the app's priority order (AIP_DB_PATH, then the
    shipped slim DB, then the working catalog), so the tab drops in without the host app
    having to hand anything over.
    """
    import os

    import streamlit as st

    from . import config

    helpers = _streamlit_helpers()
    app_db = config.DATA_DIR / "catalog_app.db"
    db_path = (os.environ.get("AIP_DB_PATH")
               or (str(app_db) if app_db.exists() else str(config.DB_PATH)))

    def _mtime(path) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    try:
        n_rows = helpers["open"](db_path).execute(
            "SELECT COUNT(*) FROM rowcrop_unclaimed").fetchone()[0]
    except Exception:
        n_rows = 0
    if not n_rows:
        st.info(
            "The row-crop opportunity table has not been built against this database yet — "
            "`rowcrop_unclaimed` is empty or absent. Run "
            "`.venv/bin/python -m src.rowcropopt` against the WORKING catalog "
            "(data/catalog.db — the county-grain `sob_sales` it reads is dropped from the "
            "shipped app DB). The map below still renders; every county will be neutral."
        )

    try:
        html = helpers["html"](_mtime(db_path), _mtime(__file__), seed_mtime(), db_path)
    except Exception as exc:                     # never take the tab down
        st.error(f"Could not build the row-crop opportunity map: {exc}")
        return
    # See the note in src/drppage.py: st.components.v1.html is past its removal date.
    st.iframe(html, height=880)


# The template uses __TOKENS__ (not str.format) so the JS braces stay literal.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Row-crop opportunity — unclaimed subsidy by county</title>
<style>
  :root {
    color-scheme: light;
    --surface: #fcfcfb; --page: #f9f9f7;
    --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --none: #ececea; --accent: #2a78d6;
  }
  * { box-sizing: border-box; margin: 0; }
  html, body { height: 100%; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink); font-size: 14px;
    display: flex; flex-direction: column;
  }
  header { padding: 12px 18px 8px; }
  header h1 { font-size: 16px; font-weight: 650; }
  header .sub { color: var(--ink-2); font-size: 12.5px; margin-top: 2px; }
  .filters {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    padding: 8px 18px 10px; border-bottom: 1px solid var(--grid);
    background: var(--surface);
  }
  .filters label { color: var(--ink-2); font-size: 12px; }
  .filters select {
    font: inherit; font-size: 13px; padding: 4px 6px; max-width: 300px;
    border: 1px solid var(--baseline); border-radius: 6px; background: var(--surface);
    color: var(--ink);
  }
  .filters select:disabled { color: var(--muted); background: var(--page); }
  #mSel { font-weight: 600; max-width: 340px; }
  .fam { font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
         border-radius: 4px; padding: 2px 6px; font-weight: 700; }
  .fam.opportunity { background: #e5f5e0; color: #1c6b35; }
  .fam.producer    { background: #e3eefc; color: #14508f; }
  .fam.agency      { background: #fdf0dd; color: #8a5300; }
  .fam.divergence  { background: #f3e8f7; color: #6b2d80; }
  .fam.basisrisk   { background: #fbe4e2; color: #9c2a1c; }
  .seg { display: inline-flex; border: 1px solid var(--baseline); border-radius: 6px;
    overflow: hidden; }
  .seg button {
    font: inherit; font-size: 12.5px; padding: 4px 11px; border: none;
    background: var(--surface); color: var(--ink-2); cursor: pointer;
  }
  .seg button + button { border-left: 1px solid var(--baseline); }
  .seg button.on { background: #238b45; color: #fff; }
  .seg button:disabled { color: var(--muted); cursor: not-allowed; }
  #formulaNote {
    padding: 7px 18px; font-size: 11.5px; color: var(--ink-2); line-height: 1.5;
    background: var(--surface); border-bottom: 1px solid var(--grid);
  }
  #formulaNote code { font-size: 11.5px; background: var(--page);
    border: 1px solid var(--grid); border-radius: 4px; padding: 0 4px; }
  #formulaNote .fn { display: none; }
  #formulaNote .fn.on { display: block; }
  #formulaNote .assumed { color: #8a5300; font-weight: 600; }
  /* The "not automatically opportunity" caveat. Collapsible, but its HEADLINE CLAIM is the
     <summary> and is therefore always on screen — the detail folds away, the warning never
     does. Collapsing it is what keeps the map itself more than a strip of the viewport. */
  #caveat {
    padding: 7px 18px; font-size: 11.5px; color: #6b4b00; line-height: 1.5;
    background: #fdf6e7; border-bottom: 1px solid #eda100;
  }
  #caveat b { color: #4d3600; }
  #caveat > summary { cursor: pointer; font-weight: 600; color: #4d3600; }
  #caveat > summary::marker { color: #eda100; }
  #caveat .c-body { margin-top: 5px; }
  .rangebar {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    padding: 24px 18px 9px; border-bottom: 1px solid var(--grid); background: var(--surface);
  }
  .rangebar > label { color: var(--ink-2); font-size: 12px; white-space: nowrap; }
  .dual { position: relative; flex: 1; min-width: 220px; max-width: 520px; height: 26px; }
  .dual .track { position: absolute; top: 11px; left: 0; right: 0; height: 4px;
    background: var(--grid); border-radius: 3px; }
  .dual .fill { position: absolute; top: 11px; height: 4px; background: #41ab5d; border-radius: 3px; }
  .dual .bubble {
    position: absolute; top: -16px; transform: translateX(-50%);
    font-size: 11px; font-variant-numeric: tabular-nums; color: var(--ink);
    background: var(--surface); border: 1px solid var(--baseline); border-radius: 4px;
    padding: 0 4px; line-height: 15px; white-space: nowrap; pointer-events: none;
  }
  .dual input[type=range] {
    position: absolute; top: 0; left: 0; width: 100%; height: 26px; margin: 0;
    -webkit-appearance: none; appearance: none; background: transparent; pointer-events: none;
  }
  .dual input[type=range]::-webkit-slider-runnable-track { height: 26px; background: transparent; }
  .dual input[type=range]::-moz-range-track { height: 26px; background: transparent; }
  .dual input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; pointer-events: auto;
    width: 16px; height: 16px; border-radius: 50%; background: var(--surface);
    border: 2px solid #238b45; box-shadow: 0 1px 3px var(--ring); cursor: pointer;
  }
  .dual input[type=range]::-moz-range-thumb {
    pointer-events: auto; width: 16px; height: 16px; border-radius: 50%;
    background: var(--surface); border: 2px solid #238b45; cursor: pointer;
  }
  .rangebar .readout { font-size: 12.5px; color: var(--ink);
    font-variant-numeric: tabular-nums; white-space: nowrap; }
  .rangebar .reset { font: inherit; font-size: 12px; color: var(--accent);
    background: none; border: none; cursor: pointer; padding: 0; }
  #main { flex: 1; display: flex; min-height: 0; }
  #mapWrap { flex: 1; position: relative; min-width: 0; }
  #map { width: 100%; height: 100%; display: block; }
  .county { stroke: var(--surface); stroke-width: 0.4; vector-effect: non-scaling-stroke; }
  .statelines { fill: none; stroke: var(--baseline); stroke-width: 0.7;
                pointer-events: none; vector-effect: non-scaling-stroke; }
  .county.hovered { stroke: var(--ink); stroke-width: 1.3; }
  .county.dimmed { opacity: 0.28; }
  .county.focused { stroke: var(--ink); stroke-width: 1.1; }
  .focusline { fill: none; stroke: var(--ink); stroke-width: 2.2; stroke-linejoin: round;
               pointer-events: none; vector-effect: non-scaling-stroke; }
  #tooltip {
    position: absolute; pointer-events: none; display: none; z-index: 5;
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.12); padding: 7px 10px; font-size: 12.5px;
    max-width: 360px;
  }
  #tooltip .t-name { font-weight: 650; }
  #tooltip .t-val { color: var(--ink-2); margin-top: 1px; }
  #tooltip .t-math { color: var(--ink-2); font-size: 11.5px; margin-top: 3px;
    font-variant-numeric: tabular-nums; }
  #tooltip .t-flag { font-size: 11px; margin-top: 4px; color: var(--muted); }
  #tooltip .t-warn { font-size: 11px; margin-top: 4px; color: #8a5300; }
  #tooltip .t-sec { margin-top: 5px; border-top: 1px solid var(--grid); padding-top: 4px; }
  #legend {
    position: absolute; left: 16px; bottom: 14px; background: var(--surface);
    border: 1px solid var(--ring); border-radius: 8px; padding: 8px 10px; font-size: 11.5px;
  }
  #legend .l-title { color: var(--ink-2); margin-bottom: 5px; }
  #legend .l-row { display: flex; align-items: center; gap: 0; }
  #legend .l-cell { width: 34px; height: 10px; }
  #legend .l-labels { display: flex; font-size: 10px; color: var(--muted); margin-top: 1px; }
  #legend .l-labels span { width: 34px; text-align: left; }
  #legend .l-none { display: flex; align-items: center; gap: 6px; margin-top: 7px; color: var(--muted); }
  #legend .l-none .sw { width: 14px; height: 10px; background: var(--none); border: 1px solid var(--grid); }
  /* "Basis risk unknown" gets its OWN swatch, hatched rather than tinted, so it cannot read
     as a low value at the pale end of the ramp. A county with unknown basis risk is not a
     county with low basis risk, and the legend has to be able to say that in one glance. */
  #legend .l-unk { display: flex; align-items: flex-start; gap: 6px; margin-top: 5px;
                   color: #9c2a1c; max-width: 250px; line-height: 1.35; }
  #legend .l-unk .sw {
    flex: none; width: 14px; height: 10px; margin-top: 2px; border: 1px solid var(--baseline);
    background: repeating-linear-gradient(45deg, #f4f3f0 0 3px, #b9bcc0 3px 5px);
  }
  #note {
    position: absolute; top: 52px; left: 16px; right: 16px; z-index: 4; display: none;
    background: #fdf6e7; border: 1px solid #eda100; border-radius: 8px;
    color: #6b4b00; padding: 8px 12px; font-size: 12.5px;
  }
  footer { padding: 6px 18px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--grid); }
  /* ---- drill-down: breadcrumb + zoom control (lifted from src/prfpage.py) ---- */
  #crumb {
    position: absolute; top: 12px; left: 16px; z-index: 4; display: flex; align-items: center;
    gap: 6px; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    padding: 5px 9px; font-size: 12px; box-shadow: 0 1px 4px rgba(11,11,11,0.06);
  }
  #crumb .c-step { color: var(--accent); cursor: pointer; }
  #crumb .c-step:hover { text-decoration: underline; }
  #crumb .c-here { color: var(--ink); font-weight: 600; }
  #crumb .c-sep { color: var(--muted); }
  #crumb .c-hint { color: var(--muted); border-left: 1px solid var(--grid); padding-left: 8px; }
  #zoomBox {
    position: absolute; right: 16px; bottom: 14px; z-index: 4; display: flex; flex-direction: column;
    align-items: center; gap: 6px; background: var(--surface); border: 1px solid var(--ring);
    border-radius: 8px; padding: 9px 7px; box-shadow: 0 1px 4px rgba(11,11,11,0.06);
  }
  #zoomBox button {
    font: inherit; font-size: 15px; line-height: 1; width: 24px; height: 22px; cursor: pointer;
    border: 1px solid var(--baseline); border-radius: 5px; background: var(--surface); color: var(--ink);
  }
  #zoomBox button:hover { border-color: var(--accent); color: var(--accent); }
  /* Vertical slider: up = closer in, which is the direction the map moves. */
  #zSlider { writing-mode: vertical-lr; direction: rtl; width: 22px; height: 104px; accent-color: var(--accent); }
  #zLabel { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  /* County drill-down panel: the crop x band breakdown, because there is no geometry below
     a county to drill into. */
  #detail {
    position: absolute; right: 16px; top: 54px; z-index: 4; width: 330px; max-height: 62%;
    overflow: auto; display: none; background: var(--surface); border: 1px solid var(--ring);
    border-radius: 8px; padding: 9px 11px; font-size: 12px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.10);
  }
  #detail h2 { font-size: 12.5px; font-weight: 650; margin-bottom: 4px; }
  #detail table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  #detail th { text-align: right; color: var(--muted); font-weight: 500; font-size: 10.5px;
               border-bottom: 1px solid var(--grid); padding: 2px 0 3px 6px; }
  #detail th:first-child, #detail td:first-child { text-align: left; padding-left: 0; }
  #detail td { text-align: right; padding: 2px 0 2px 6px; font-size: 11.5px; }
  #detail tr.sub td { color: var(--ink-2); }
  #detail tr.tot td { border-top: 1px solid var(--grid); font-weight: 650; }
  #detail .d-note { color: var(--muted); font-size: 10.5px; margin-top: 6px; line-height: 1.45; }
  #detail .d-close { float: right; color: var(--accent); cursor: pointer; font-size: 11px; }
  /* The RANKING view. Its whole reason for existing is to put raw opportunity, basis-adjusted
     opportunity and the basis-risk term in three adjacent columns, so a county that only looks
     good in the first one cannot be read without seeing the other two. */
  #rank {
    position: absolute; left: 16px; top: 54px; z-index: 4; width: 430px; max-height: 74%;
    overflow: auto; display: none; background: var(--surface); border: 1px solid var(--ring);
    border-radius: 8px; padding: 9px 11px; font-size: 12px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.10);
  }
  #rank h2 { font-size: 12.5px; font-weight: 650; margin-bottom: 3px; }
  #rank table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  #rank th { text-align: right; color: var(--muted); font-weight: 500; font-size: 10.5px;
             border-bottom: 1px solid var(--grid); padding: 3px 0 3px 6px; }
  #rank th:first-child, #rank td:first-child { text-align: left; padding-left: 0; }
  #rank td { text-align: right; padding: 2px 0 2px 6px; font-size: 11.5px; }
  #rank tr.unk td { color: #9c2a1c; }
  #rank tr:hover td { background: var(--page); }
  #rank tbody tr { cursor: pointer; }
  #rank .r-note { color: var(--muted); font-size: 10.5px; margin-top: 6px; line-height: 1.45; }
  #rank .r-close { float: right; color: var(--accent); cursor: pointer; font-size: 11px; }
  #rank .r-dn { color: #a86a00; } #rank .r-up { color: #1c6b35; }
  #rankBtn {
    font: inherit; font-size: 12.5px; padding: 4px 11px; cursor: pointer; color: var(--ink-2);
    border: 1px solid var(--baseline); border-radius: 6px; background: var(--surface);
  }
  #rankBtn.on { background: #238b45; color: #fff; border-color: #238b45; }
</style>
</head>
<body>
<header>
  <h1 id="pageTitle">Row-crop opportunity — unclaimed subsidy by county</h1>
  <div class="sub" id="pageSub">Reinsurance year __YEAR__. Generated __GENERATED__.</div>
</header>
<div class="filters">
  <span class="fam" id="famTag">opportunity</span>
  <label>Show <select id="mSel"></select></label>
  <label>Band <span class="seg" id="bandSeg"></span></label>
  <label>Crop <select id="fCrop"></select></label>
  <label>Where the band is <select id="fEvidence">
    <option value="1">sold somewhere in the state</option>
    <option value="2">sold in this county</option>
    <option value="0">show every county with eligible acres</option>
  </select></label>
  <label id="aipWrap" style="display:none">AIP <select id="fAip"></select></label>
  <button id="rankBtn" type="button" title="Rank counties: raw, basis-adjusted and the basis-risk term side by side">Top counties</button>
  <span id="countLine" style="color:var(--muted);font-size:12px;margin-left:auto"></span>
</div>
<div id="formulaNote">
  <div class="fn" data-m="total">
    <b>Unclaimed subsidy</b> =
    <code>eligible acres &times; (1 &minus; penetration) &times; subsidy captured per acre</code>.
    Eligible acres are acres on an individual, <b>additional-coverage</b> MPCI plan (YP, RP,
    RP-HPE, APH) — CAT acres are excluded because a CAT policy cannot carry a band at all.
    Penetration is that band's acres over those eligible acres. Every term is COMPUTED from
    RMA's Summary of Business; nothing here is an assumed rate.
  </div>
  <div class="fn" data-m="acre">
    <b>Unclaimed subsidy per eligible acre</b> =
    <code>subsidy captured per acre &times; (1 &minus; penetration)</code>.
    The same metric as the total, divided by the county's eligible acres — it strips out
    county SIZE, so a small county that buys nothing can outrank a big one that mostly does.
    A prospecting list wants the total; a "who most needs this conversation" list wants this.
  </div>
  <div class="fn" data-m="pen">
    <b>Band penetration</b> = <code>band acres &divide; eligible acres</code>, capped at 100%.
    Low penetration is where the unclaimed dollars are — but it is <b>not</b> a list of people
    who should be sold something: an acre can be unsold because the producer is <b>ineligible</b>,
    or because they looked at <b>basis risk</b> and rationally declined. See the amber note
    below, and the <span class="fam basisrisk">basis risk</span> metrics.
  </div>
  <div class="fn" data-m="prodac">
    <span class="fam producer">producer</span>
    <b>Value per acre to the PRODUCER</b> = the federal subsidy captured on one band acre.
    This is the money the producer does <b>not</b> pay: on the RY2026 book ECO-RP captures
    $23.26/ac, MCO-RP $26.25/ac and SCO-RP $12.10/ac nationally, and this map shows each
    county's own figure. COMPUTED from Summary of Business — no rate card involved.
  </div>
  <div class="fn" data-m="ret">
    <span class="fam producer">producer</span>
    <b>Return per producer dollar</b> = <code>total premium &divide; producer premium</code> =
    <code>1 &divide; (1 &minus; subsidy share)</code>. At FCIC's <b>statutory</b> target loss
    ratio of 1.0 (7 U.S.C. 1506(n)(2)) the expected indemnity is the whole premium, so this is
    what a producer dollar buys in expectation: about <b>5.1&times;</b> on the bands.
    Notice how flat this map is. That flatness is the finding, not a bug — the subsidy share is
    set in statute, not by geography. What varies county to county is how many dollars are at
    stake, never how good the deal is per dollar. (Statutory expectation, not realized
    experience: a band's actual loss ratio in any one county in any one year will differ.)
  </div>
  <div class="fn" data-m="commac">
    <span class="fam agency">agency</span>
    <b>Value per acre to the AGENCY</b> =
    <code>TOTAL premium per acre &times; your commission %</code>. Commission is a percent of
    the whole premium, the subsidised portion included, which is why the agency's number keys
    off premium while the producer's keys off subsidy. They correlate — both scale with
    premium — but they are not the same ranking, because the commission rate varies by region
    and the subsidy share does not. <span class="assumed">ASSUMED:</span> commission % is your
    own negotiated rate from <code>data/seed/aip_commission.csv</code> (AIP &times; region) or
    <code>data/seed/commission_by_timezone.csv</code>, and <b>the values shipped there are
    SAMPLE data</b>. Replace them before quoting any figure on this map.
  </div>
  <div class="fn" data-m="commtot">
    <span class="fam agency">agency</span>
    <b>Unclaimed commission</b> =
    <code>eligible acres &times; (1 &minus; penetration) &times; TOTAL premium per acre &times; commission %</code>.
    The prospecting number: what this county's unsold band premium is worth to your agency at
    your rate. <span class="assumed">ASSUMED:</span> the commission rate — everything to the
    left of it is computed. The SRA's 80%-of-A&amp;O cap on total agent compensation and RMA's
    schemes-or-devices rules bound real compensation and are not modelled here.
  </div>
  <div class="fn" data-m="gap">
    <span class="fam divergence">divergence</span>
    <b>Agency-minus-producer rank gap</b> = this county's percentile under
    <i>commission per acre</i> minus its percentile under <i>subsidy captured per acre</i>, in
    percentile points. <b style="color:#8a5300">Amber</b> = the agency is drawn here more than
    the producer's own interest justifies; <b style="color:#1c6b35">green</b> = the reverse,
    a county where the producer has more to gain than the agency has to earn. Grey is
    agreement. This map exists because the two rankings correlate but are not identical, and
    that difference is precisely where an agency's incentive and a producer's interest come
    apart — which is a thing to show, not to bury.
  </div>
  <div class="fn" data-m="adjtotal">
    <span class="fam basisrisk">basis risk</span>
    <b>Basis-risk-adjusted unclaimed subsidy</b> =
    <code>unclaimed subsidy &times; (1 &minus; miss rate)</code>, where
    <code>miss rate = P(the band pays NOTHING | the farm has a loss beyond its own
    deductible)</code>. The raw metric silently sets that weight to <b>1</b> everywhere — it
    assumes a county-triggered product always shows up. It does not: nationally the weight is
    <b>0.84</b> for ECO and <b>0.64</b> for SCO. This is a <b>ranking weight, not a dollar
    forecast</b>: the federal subsidy on an unsold acre is the same number whatever the county
    index does. What the weight says is how much of that money buys protection that arrives in
    the years the client needs it. Counties with <b>no</b> basis-risk estimate are hatched and
    are not ranked here — unknown is not low.
  </div>
  <div class="fn" data-m="adjacre">
    <span class="fam basisrisk">basis risk</span>
    <b>Basis-risk-adjusted unclaimed subsidy per eligible acre</b> — the adjusted total with
    county size divided out. This is the pairing that actually re-ranks counties: on the
    per-acre measure the raw and adjusted orders disagree by up to <b>&plusmn;16 percentile
    points</b>, while on the totals county size swamps everything and they barely disagree at
    all. Compare it against the unadjusted <i>$ per eligible acre</i> metric, or open
    <b>Top counties</b> to see both columns side by side.
  </div>
  <div class="fn" data-m="miss">
    <span class="fam basisrisk">basis risk</span>
    <b>Miss rate</b> = <code>P(the band pays nothing | the farm has a loss)</code>, for a
    <b>TYPICAL</b> farm in the county — <b>not</b> for any actual farm. Dark red = the band
    fails most often. The county side is MEASURED from NASS county yield history; the farm side
    is MODELLED, from that series plus <b>one</b> imported parameter, the farm-county yield
    correlation &rho; (0.70; the tooltip shows the whole 0.55&ndash;0.85 range). Published at
    plan RP and the farm's own coverage level <b>0.85</b>, which is the highest common election
    and therefore the <b>highest</b> miss rate of any of them — the discount here is
    conservative for the ~88% of the book that insures below 85%. A producer's real answer
    comes from their own APH schedule, via <code>src/basisrisk.py</code>'s farm calculator.
  </div>
  <div class="fn" data-m="bgap">
    <span class="fam divergence">divergence</span>
    <b>Basis-risk rank penalty</b> = this county's percentile under <i>raw unclaimed subsidy
    per acre</i> minus its percentile under the <i>basis-adjusted</i> version.
    <b style="color:#a86a00">Amber</b> = the raw map <b>oversells</b> this county: it ranks
    high on dollars and lower once you ask whether the product responds there.
    <b style="color:#1c6b35">Green</b> = the reverse — the raw map undersells a county where
    the band works unusually well. Grey is agreement. This is the single most useful view on
    the page for anyone deciding where to spend a week, because it is the only one that shows
    where the money and the merits point in different directions.
  </div>
</div>
<details id="caveat">
  <summary>Low penetration is not automatically opportunity, and this map is
  <b>not a list of people to sell to</b>. An unsold acre can be unsold because the producer is
  <b>ineligible</b>, or because they <b>rationally declined on basis risk</b> — these bands pay
  on a COUNTY index, and on a farm that does not track its county that is a product which
  cannot respond to the client's loss. <span id="caveatCover"></span> (expand)</summary>
  <div class="c-body">
  Each of these makes an unsold acre legitimately unsold.
  <b>(1) Eligibility:</b> acreage designated as covered by <b>STAX cannot carry SCO</b>, which
  this map does model. Through CY2025 an FSA farm number with <b>ARC</b> elected on a crop
  <b>could not buy SCO</b> on it either, and the RY2025 rows here still carry that bar; FSA's
  election is not in Summary of Business at any grain, so it cannot be netted out of those
  acres. <b>OBBBA §10303(b) repealed the ARC bar for CY2026</b> (7 U.S.C. 1508(c)(4)(C)(iv);
  RMA MGR-25-006), so on the RY2026 book ARC and PLC are neutral to SCO — see
  <code>docs/rowcrop_endorsement_stacking.md</code>. Everything else that disqualifies a unit
  is invisible: this map counts acres, not eligibility.
  <b>(2) Basis risk:</b> SCO, ECO, MCO and STAX all settle on a <b>county</b> index. A farm
  poorly correlated with its county gets a band that pays when it did not need it and fails to
  pay when it did — declining is rational, not an oversight. This is the one of the three that
  is now <b>measured</b> rather than only warned about: pick a
  <span class="fam basisrisk">basis risk</span> metric to see it, and read the
  basis-risk line in every tooltip. It is measured for Corn, Soybeans and Wheat under SCO and
  ECO only; everywhere else it is <b>unknown</b>, which is not the same as low.
  <b>(3) Availability:</b> a band is only offered where the actuarial documents offer it. This
  page does not read ADM; it infers the offer from observed sales and grades it in the
  "where the band is" control.
  <br>What <i>is</i> modelled: <b>SCO and STAX are mutually exclusive</b> on the same acre, so
  each one's eligible acres here exclude the other's. ECO's and MCO's interactions with the
  others are <b>not</b> modelled — ECO layers above SCO by design, and MCO is in its first book
  year with no primary source in hand for its stacking rules.
  Treat this as a map of <b>questions worth asking</b>, not a list of people who should be
  sold something.
  </div>
</details>
<div class="rangebar" id="rangebar">
  <label id="rangeLabel">Metric range</label>
  <div class="dual">
    <div class="track"></div>
    <div class="fill" id="rFill"></div>
    <div class="bubble" id="rBubbleLo"></div>
    <div class="bubble" id="rBubbleHi"></div>
    <input type="range" id="rMin">
    <input type="range" id="rMax">
  </div>
  <span class="readout" id="rReadout"></span>
  <button class="reset" id="rReset" type="button">reset</button>
</div>
<div id="main">
  <div id="mapWrap">
    <div id="note"></div>
    <div id="crumb"></div>
    <svg id="map" viewBox="0 0 975 610" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="zoomBox">
      <button id="zIn" type="button" title="Zoom in">+</button>
      <input type="range" id="zSlider" min="0" max="100" value="0">
      <button id="zOut" type="button" title="Zoom out">&minus;</button>
      <span id="zLabel">1&times;</span>
    </div>
    <div id="detail"></div>
    <div id="rank"></div>
    <div id="legend"></div>
    <div id="tooltip"></div>
  </div>
</div>
<footer id="pageFoot"></footer>

<script>__D3__</script>
<script>__TOPOJSON__</script>
<script>
var US_ATLAS = __ATLAS__;
var DATA = __PAYLOAD__;

(function () {
  "use strict";

  var NONE = getComputedStyle(document.documentElement).getPropertyValue("--none").trim() || "#ececea";
  // Sequential single-hue "money" green ramp (light->dark = low->high), matching the PRF map.
  var RAMP = ["#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"];
  // Diverging ramp, used by the two DIVERGENCE metrics and only because they have a meaningful
  // zero: amber = agency-favoured / raw-flattered, green = the reverse, grey = the two agree.
  var RAMP_DIV = ["#1c6b35", "#63a877", "#b7d3bf", "#e6e5e0", "#f2d6a8", "#dfa445", "#a86a00"];
  // A THIRD hue for the basis-risk term, so it can never be mistaken for one of the money
  // maps: on this one, dark is the county where the product fails most often.
  var RAMP_RISK = ["#fdece8", "#fbd5cb", "#f8b3a2", "#f08b74", "#dd6449", "#bd422a", "#8f2a17"];
  // Basis risk UNKNOWN is drawn hatched, never tinted. Any tint places it somewhere on the
  // ramp, and every position on the ramp is a claim we do not have.
  var UNKNOWN_FILL = "url(#brUnknown)";
  var UNITS = 1000;

  var COUNTIES = DATA.counties || {};
  var CROPS = DATA.crops || [];
  var BANDS = DATA.bands || [];
  var PRESENT = (DATA.bands_present && DATA.bands_present.length) ? DATA.bands_present : BANDS;
  var BASIS = DATA.basis || [];
  var BSUM = DATA.band_summary || {};
  var COMM = DATA.comm || { aips: [], with_rate: 0, path: "" };
  var CZONE = DATA.commzone || { zones: {}, with_rate: 0, path: "" };
  var ZONE_OF = DATA.state_zone || {};
  var ALL_BANDS = "*";

  // Cell layout, as written by build_rowcrop_page_payload.
  var C_BASE = 0, C_BAND = 1, C_SUB = 2, C_PREM = 3, C_EV = 4, C_BASIS = 5;

  // THE JOIN, client side. BR[fips][cropIx][bandIx] is rowcroppage.BASIS_CELL; a county x crop
  // x band ABSENT from it has UNKNOWN basis risk. Absence is the wire format for unknown on
  // purpose: there is no sentinel here for anyone to coerce into a low miss rate.
  var BR = DATA.basis_risk || {};
  var BMETA = DATA.basis_meta || {};
  var B_MISS = 0, B_RLO = 1, B_RHI = 2, B_DEEP = 3, B_UNCOV = 4, B_GRADE = 5, B_SHARE = 6;
  var BGRADES = BMETA.grades || ["A", "B", "C"];
  var BVARIANT = BMETA.variant || {};
  var BNOTE = BMETA.band_note || {};

  // Metric registry. `family` is the honesty axis: whose interest the number serves, and
  // whether any part of it rests on the SAMPLE commission rates.
  var METRICS = {
    total:   { label: "Unclaimed subsidy — total $", family: "opportunity", assumed: false,
               legend: "Unclaimed subsidy ($)",
               title: "Unclaimed subsidy — total dollars per county",
               sub: "Federal dollars available on eligible acres that do not carry this band. " +
                    "Darker = more unclaimed. This is the prospecting size of a county." },
    acre:    { label: "Unclaimed subsidy — $ per eligible acre", family: "opportunity",
               assumed: false, legend: "Unclaimed subsidy ($/eligible acre)",
               title: "Unclaimed subsidy per eligible acre",
               sub: "The same dollars with county SIZE divided out — where the average " +
                    "eligible acre is leaving the most on the table." },
    pen:     { label: "Band penetration (%)", family: "opportunity", assumed: false,
               legend: "Band penetration (%)", invert: true,
               title: "Band penetration — share of eligible acres that carry the band",
               sub: "Band acres over eligible acres. Shaded DARK where penetration is LOW, " +
                    "because low penetration is what the rest of this page is about." },
    prodac:  { label: "PRODUCER value per acre — subsidy captured ($/ac)", family: "producer",
               assumed: false, legend: "Subsidy captured ($/acre)",
               title: "Producer value per acre — federal subsidy captured on one band acre",
               sub: "What the producer does NOT pay for the coverage. Computed from this " +
                    "county's own book where the band is sold there." },
    ret:     { label: "PRODUCER return per $1 of producer premium", family: "producer",
               assumed: false, legend: "Return per producer $1",
               title: "Producer return — expected dollars back per $1 of producer premium",
               sub: "1 / (1 - subsidy share), at FCIC's statutory 1.0 target loss ratio. " +
                    "Nearly flat everywhere: the deal per dollar does not vary by geography." },
    commac:  { label: "AGENCY value per acre — commission ($/ac)", family: "agency",
               assumed: true, legend: "Commission ($/acre)", needsComm: true,
               title: "Agency value per acre — commission on one band acre",
               sub: "Total premium per acre x your negotiated rate. Commission follows TOTAL " +
                    "premium, the subsidised portion included." },
    commtot: { label: "AGENCY opportunity — unclaimed commission ($)", family: "agency",
               assumed: true, legend: "Unclaimed commission ($)", needsComm: true,
               title: "Agency opportunity — commission on the unsold band premium",
               sub: "What this county's unsold band premium is worth to your agency at your " +
                    "rate. The agency's own prospecting list." },
    gap:     { label: "DIVERGENCE — agency vs producer rank gap", family: "divergence",
               assumed: true, legend: "Agency percentile - producer percentile", diverging: true,
               needsComm: true,
               title: "Where the agency's incentive and the producer's interest diverge",
               sub: "Percentile under commission per acre minus percentile under subsidy " +
                    "captured per acre. Amber = agency-favoured, green = producer-favoured." },
    // The basis-risk family. `basis: true` is what makes a county with NO estimate render
    // HATCHED rather than fall through to the plain no-data grey — these are the only metrics
    // for which "we have no basis-risk answer here" is a distinct and load-bearing state.
    adjtotal: { label: "BASIS-ADJUSTED unclaimed subsidy — total $", family: "basisrisk",
               assumed: false, legend: "Basis-adjusted unclaimed subsidy ($)", basis: true,
               title: "Unclaimed subsidy, weighted by whether the band would actually pay",
               sub: "Unclaimed subsidy x (1 - miss rate). The raw map assumes that weight is " +
                    "1 everywhere; nationally it is 0.84 for ECO and 0.64 for SCO." },
    adjacre: { label: "BASIS-ADJUSTED unclaimed subsidy — $ per eligible acre",
               family: "basisrisk", assumed: false, basis: true,
               legend: "Basis-adjusted unclaimed subsidy ($/eligible acre)",
               title: "Basis-adjusted unclaimed subsidy per eligible acre",
               sub: "County size divided out — the measure on which the raw and adjusted " +
                    "rankings genuinely disagree, by up to 16 percentile points." },
    miss:    { label: "BASIS RISK — miss rate (%)", family: "basisrisk", assumed: false,
               legend: "Miss rate (%)", basis: true, risk: true,
               title: "Basis risk — how often the band pays nothing in a year the farm loses",
               sub: "P(band pays nothing | farm loss beyond its deductible), for a TYPICAL " +
                    "farm. County side measured, farm side modelled. Dark = the band fails most." },
    bgap:    { label: "DIVERGENCE — basis-risk rank penalty", family: "divergence",
               assumed: false, legend: "Raw percentile - adjusted percentile", diverging: true,
               basis: true,
               title: "Where the raw opportunity ranking and the basis-adjusted one disagree",
               sub: "Amber = the raw map oversells this county; green = it undersells one " +
                    "where the band works unusually well. Grey is agreement." }
  };
  var METRIC_ORDER = ["total", "acre", "pen", "prodac", "ret", "commac", "commtot", "gap",
                      "adjtotal", "adjacre", "miss", "bgap"];
  var metric = "total";
  var band = DATA.default_band || (PRESENT[0] || "ECO");
  var minEvidence = DATA.default_evidence === undefined ? 1 : DATA.default_evidence;

  // ---------------- geometry (same AlbersUSA params us-atlas pre-projects to)
  //
  // IF YOU EVER HAND-BUILD A POLYGON HERE, WIND ITS RINGS CLOCKWISE in (lon, lat).
  // d3-geo treats polygons as spherical and takes the interior to be the region LEFT of the
  // ring's travel — the opposite of GeoJSON's counter-clockwise-exterior convention — so a
  // counter-clockwise ring renders as the whole globe minus the shape and floods the whole
  // viewport with one solid fill. src/prfpage.py hit exactly this drawing PRF grid cells.
  // Everything below is us-atlas geometry, which is already wound correctly, so this page
  // builds no rings of its own; rowcroppage.ring_clockwise() is exported and tested for
  // whoever adds the first one. Row crops have no sub-county lattice to synthesize — SCO,
  // ECO and STAX all trigger on the COUNTY index — which is why the temptation to invent one
  // is refused rather than met.
  var path = d3.geoPath(d3.geoAlbersUsa().scale(1300).translate([487.5, 305]));
  var countiesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.counties).features;
  var stateMesh = topojson.mesh(US_ATLAS, US_ATLAS.objects.states, function () { return true; });
  var statesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.states).features;
  var stateById = {}; statesFC.forEach(function (s) { stateById[String(s.id)] = s; });

  var svg = d3.select("#map");
  // The "basis risk unknown" hatch. userSpaceOnUse inside the zoomed <g>, so the hatch scales
  // with the map rather than turning into a solid block when you zoom into one county.
  (function () {
    var pat = svg.append("defs").append("pattern")
        .attr("id", "brUnknown").attr("width", 6).attr("height", 6)
        .attr("patternUnits", "userSpaceOnUse").attr("patternTransform", "rotate(45)");
    pat.append("rect").attr("width", 6).attr("height", 6).attr("fill", "#f4f3f0");
    pat.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 6)
       .attr("stroke", "#b9bcc0").attr("stroke-width", 2.2);
  })();
  var g = svg.append("g");
  var gCounties = g.append("g");
  var countySel = gCounties.selectAll("path").data(countiesFC).join("path")
      .attr("class", "county").attr("d", path)
      .on("mousemove", function (ev, d) { hover.call(this, ev, d); })
      .on("mouseout", unhover)
      .on("click", function (ev, d) { ev.stopPropagation(); countyClicked(d); });
  g.append("path").attr("class", "statelines").attr("d", path(stateMesh));
  var gFocus = g.append("path").attr("class", "focusline");
  var countyById = {}; countiesFC.forEach(function (c) { countyById[String(c.id)] = c; });

  // ---------------- controls
  var mSel = document.getElementById("mSel"),
      fCrop = document.getElementById("fCrop"),
      fEvidence = document.getElementById("fEvidence"),
      fAip = document.getElementById("fAip");

  METRIC_ORDER.forEach(function (k) {
    var o = document.createElement("option");
    o.value = k; o.textContent = METRICS[k].label;
    mSel.appendChild(o);
  });
  mSel.value = metric;

  CROPS.forEach(function (name, i) {
    var o = document.createElement("option");
    o.value = String(i); o.textContent = name;
    fCrop.appendChild(o);
  });
  fCrop.value = "0";                                    // the (all crops) rollup
  fCrop.disabled = CROPS.length < 2;
  fEvidence.value = String(minEvidence);

  // Band buttons. "All bands" is offered because the bands STACK on the same acre — a
  // producer who buys SCO and ECO captures both subsidies — so summing them is the real
  // total, not double counting. Penetration is the exception and says so.
  var bandButtons = [];
  (function () {
    var seg = document.getElementById("bandSeg");
    PRESENT.concat([ALL_BANDS]).forEach(function (b) {
      var btn = document.createElement("button");
      btn.type = "button"; btn.dataset.b = b;
      btn.textContent = b === ALL_BANDS ? "All bands" : b;
      var bs = BSUM[b];
      btn.title = b === ALL_BANDS
        ? "SCO + ECO + MCO + STAX summed — the bands stack on the same acre"
        : ((DATA.band_labels && DATA.band_labels[b]) || b) +
          (bs && bs.pen !== null && bs.pen !== undefined
            ? " · " + (100 * bs.pen).toFixed(1) + "% national penetration" +
              (bs["new"] ? " · FIRST book year" : "")
            : "");
      btn.classList.toggle("on", b === band);
      btn.addEventListener("click", function () {
        if (band === b) return;
        band = b;
        bandButtons.forEach(function (x) { x.classList.toggle("on", x === btn); });
        applyMetric();
        if (level === 2) renderDetail();
      });
      seg.appendChild(btn);
      bandButtons.push(btn);
    });
  })();

  // AIP roster for the two commission metrics + the divergence metric. Every AIP in the seed
  // file is listed, rate or no rate: hiding the rate-less ones would make an unfilled file
  // look like a short list of AIPs rather than an unfilled file.
  (function () {
    COMM.aips.forEach(function (a, i) {
      var o = document.createElement("option");
      o.value = String(i);
      o.textContent = a.name + (a.pct === null || a.pct === undefined
        ? " — no rate set" : " — " + a.pct + "%");
      fAip.appendChild(o);
    });
    var first = -1;
    COMM.aips.forEach(function (a, i) {
      if (first < 0 && (a.pct !== null && a.pct !== undefined)) first = i;
    });
    if (!COMM.aips.length) {
      var o2 = document.createElement("option");
      o2.textContent = "no AIPs in " + COMM.path;
      fAip.appendChild(o2); fAip.disabled = true;
    } else {
      fAip.value = String(first >= 0 ? first : 0);
    }
  })();
  function aip() { return COMM.aips[parseInt(fAip.value, 10)] || null; }
  function zoneFor(fips) { return ZONE_OF[String(fips).slice(0, 2)] || null; }
  // Resolution, most specific first: this AIP's rate for this county's region, then the AIP's
  // flat rate, then the regional default. null, NEVER 0 — "no rate entered" and "0%
  // commission" are different claims and only one may be multiplied into a dollar figure.
  function commSource(fips) {
    var a = aip(), zone = zoneFor(fips);
    if (a && zone && a.by_region && a.by_region[zone] !== undefined) {
      return { pct: a.by_region[zone], from: a.name + " · " + zone, path: COMM.path };
    }
    if (a && a.pct !== null && a.pct !== undefined) {
      return { pct: a.pct, from: a.name + " (all regions)", path: COMM.path };
    }
    var z = zone ? CZONE.zones[zone] : undefined;
    if (z !== null && z !== undefined) {
      return { pct: z, from: zone + " region default", path: CZONE.path };
    }
    return { pct: null, from: null, path: null };
  }
  function commPct(fips) { return commSource(fips).pct; }
  function anyRateSet() { return CZONE.with_rate > 0 || COMM.with_rate > 0; }

  // ---------------- the metric, per county
  function cellsFor(fips) {
    var byCrop = COUNTIES[fips]; if (!byCrop) return [];
    var byBand = byCrop[fCrop.value]; if (!byBand) return [];
    var out = [];
    for (var i = 0; i < BANDS.length; i++) {
      var c = byBand[String(i)];
      if (!c) continue;
      if (band !== ALL_BANDS && BANDS[i] !== band) continue;
      if (c[C_EV] < minEvidence) continue;
      out.push({ band: BANDS[i], bi: i, c: c, br: brCell(fips, i) });
    }
    return out;
  }

  // The joined basis-risk cell for one county x (selected crop) x band index, or null.
  function brCell(fips, bi) {
    var byCrop = BR[fips]; if (!byCrop) return null;
    var byBand = byCrop[fCrop.value]; if (!byBand) return null;
    return byBand[String(bi)] || null;
  }

  // One county's whole arithmetic, in one place, so every metric and the tooltip read the
  // same numbers. Returns null when the county has nothing for the current selection.
  function statsFor(fips) {
    var cells = cellsFor(fips);
    if (!cells.length) return null;
    var s = { baseMax: 0, unsold: 0, bandAcres: 0, baseSum: 0,
              sub: null, prem: null, subPA: null, premPA: null,
              basis: {}, ev: 0, n: cells.length,
              br: null, brMissing: [], adjSub: null, adjPrem: null, adjSubPA: null };
    var haveSub = false, havePrem = false;
    // ---- basis-risk accumulators. Weighted by each band's own unclaimed DOLLARS, so the
    // effective miss rate reported back is exactly 1 - (adjusted total / raw total) and the
    // two never drift apart. Where a cell has no dollar figure the weight falls back to its
    // eligible acres, which is the only other thing it has.
    var brW = 0, brAcc = [0, 0, 0, 0, 0], brShare = 0, brGrade = -1, brAnyPartial = false;
    cells.forEach(function (x) {
      var c = x.c, base = c[C_BASE], bandAc = Math.min(c[C_BAND], base);
      var unsold = base - bandAc;
      // A band with no basis-risk row does NOT borrow another band's. SCO, ECO, MCO and STAX
      // are different products with different triggers — MCO settles on a MARGIN index that
      // src/basisrisk.py does not model at all — so one unknown band makes the whole selection
      // unknown rather than quietly extrapolating across products. Across CROPS within one
      // band the extrapolation is made, is bounded below by the coverage floor, and is
      // labelled `partial` wherever it happens.
      if (!x.br) {
        if (s.brMissing.indexOf(x.band) < 0) s.brMissing.push(x.band);
      } else {
        var w = (c[C_SUB] !== null && c[C_SUB] !== undefined && unsold > 0)
                ? unsold * c[C_SUB] : base;
        if (w > 0) {
          brW += w;
          for (var q = 0; q < 5; q++) brAcc[q] += w * (x.br[q] || 0);
          brShare += w * (x.br[B_SHARE] === null || x.br[B_SHARE] === undefined
                          ? 1 : x.br[B_SHARE]);
          if (x.br[B_GRADE] > brGrade) brGrade = x.br[B_GRADE];   // worst grade wins
          if (x.br[B_SHARE] !== null && x.br[B_SHARE] !== undefined && x.br[B_SHARE] < 0.999) {
            brAnyPartial = true;
          }
        }
        var aSub = (c[C_SUB] === null || c[C_SUB] === undefined)
                   ? null : unsold * c[C_SUB] * (1 - x.br[B_MISS]);
        var aPrem = (c[C_PREM] === null || c[C_PREM] === undefined)
                    ? null : unsold * c[C_PREM] * (1 - x.br[B_MISS]);
        if (aSub !== null) s.adjSub = (s.adjSub || 0) + aSub;
        if (aPrem !== null) s.adjPrem = (s.adjPrem || 0) + aPrem;
      }
      // Under "All bands" the eligible denominator is NOT the same for every band (MCO is
      // offered on far fewer crops than ECO), so the county's eligible acre count is the
      // WIDEST of them — the acres that could carry at least one band — while the dollars
      // are summed across bands. Anything else would divide one band's dollars by another
      // band's acres.
      if (base > s.baseMax) s.baseMax = base;
      s.baseSum += base;
      s.bandAcres += bandAc;
      s.unsold += unsold;
      if (c[C_EV] > s.ev) s.ev = c[C_EV];
      if (c[C_BASIS] >= 0) s.basis[BASIS[c[C_BASIS]]] = true;
      if (c[C_SUB] !== null && c[C_SUB] !== undefined) {
        s.sub = (s.sub || 0) + unsold * c[C_SUB];
        s.subPA = (s.subPA || 0) + c[C_SUB];      // stacked bands stack their subsidy
        haveSub = true;
      }
      if (c[C_PREM] !== null && c[C_PREM] !== undefined) {
        s.prem = (s.prem || 0) + unsold * c[C_PREM];
        s.premPA = (s.premPA || 0) + c[C_PREM];
        havePrem = true;
      }
    });
    if (!haveSub) { s.sub = null; s.subPA = null; }
    if (!havePrem) { s.prem = null; s.premPA = null; }
    // One missing band poisons the whole selection: see the note in the loop above.
    if (s.brMissing.length || brW <= 0) {
      s.br = null; s.adjSub = null; s.adjPrem = null;
    } else {
      s.br = {
        miss: brAcc[B_MISS] / brW, rlo: brAcc[B_RLO] / brW, rhi: brAcc[B_RHI] / brW,
        deep: brAcc[B_DEEP] / brW, uncov: brAcc[B_UNCOV] / brW,
        grade: BGRADES[brGrade] || null, share: brShare / brW,
        partial: brAnyPartial, bands: cells.length
      };
      // Report the miss rate the ADJUSTED DOLLARS actually imply, so the tooltip's arithmetic
      // reconciles under "All bands" instead of being a separate weighted average of its own.
      if (s.sub !== null && s.sub > 0 && s.adjSub !== null) s.br.miss = 1 - s.adjSub / s.sub;
    }
    s.adjSubPA = (s.adjSub === null || s.baseMax <= 0) ? null : s.adjSub / s.baseMax;
    // Penetration across several bands is an ACRE-WEIGHTED AVERAGE over the bands, not a
    // union — Summary of Business cannot tell us which acres carry both. Labelled as such.
    s.pen = s.baseSum > 0 ? s.bandAcres / s.baseSum : null;
    s.acre = (s.sub === null || s.baseMax <= 0) ? null : s.sub / s.baseMax;
    s.ret = (s.premPA === null || s.subPA === null || s.premPA - s.subPA <= 0)
      ? null : s.premPA / (s.premPA - s.subPA);
    return s;
  }

  var statCache = {};
  function stats(fips) {
    if (!(fips in statCache)) statCache[fips] = statsFor(fips);
    return statCache[fips];
  }

  function baseValue(m, fips) {
    var s = stats(fips);
    if (!s) return null;
    if (m === "total") return s.sub;
    if (m === "acre") return s.acre;
    if (m === "pen") return s.pen;
    if (m === "prodac") return s.subPA;
    if (m === "ret") return s.ret;
    if (m === "adjtotal") return s.adjSub;
    if (m === "adjacre") return s.adjSubPA;
    if (m === "miss") return s.br ? s.br.miss : null;
    var pct = commPct(fips);
    if (pct === null || pct === undefined) return null;
    if (m === "commac") return s.premPA === null ? null : s.premPA * pct / 100;
    if (m === "commtot") return s.prem === null ? null : s.prem * pct / 100;
    return null;
  }

  // Percentile of a county under a metric, over every county that HAS a value for it. Only the
  // two DIVERGENCE metrics use this, and both recompute whenever the selection changes.
  //
  // `bgap`'s two rankings are computed over the SAME county set — the counties that have a
  // basis-risk estimate — because a percentile against a different denominator is not a
  // comparable percentile. A county whose basis risk is unknown appears in neither, and so
  // has no gap, which is the correct answer rather than a zero.
  var pctlCache = null;
  function percentiles() {
    if (pctlCache) return pctlCache;
    function ranks(m, restrict) {
      var pairs = [];
      for (var f in COUNTIES) {
        if (restrict) { var st = stats(f); if (!st || !st.br) continue; }
        var v = baseValue(m, f);
        if (v !== null && v !== undefined && isFinite(v)) pairs.push([f, v]);
      }
      pairs.sort(function (a, b) { return a[1] - b[1]; });
      var out = {}, n = pairs.length;
      pairs.forEach(function (p, i) { out[p[0]] = n < 2 ? 50 : 100 * i / (n - 1); });
      return out;
    }
    pctlCache = { prod: ranks("prodac"), comm: ranks("commac"),
                  raw: ranks("acre", true), adj: ranks("adjacre", true) };
    return pctlCache;
  }
  function gapFor(fips) {
    var p = percentiles();
    var a = p.comm[fips], b = p.prod[fips];
    if (a === undefined || b === undefined) return null;
    return a - b;
  }
  // Positive = the RAW map ranks this county higher than the basis-adjusted one does, i.e. the
  // raw map oversells it. Same sign convention as `gap`: amber is the direction to watch.
  function bgapFor(fips) {
    var p = percentiles();
    var a = p.raw[fips], b = p.adj[fips];
    if (a === undefined || b === undefined) return null;
    return a - b;
  }

  function valFor(fips) {
    if (metric === "gap") return gapFor(fips);
    if (metric === "bgap") return bgapFor(fips);
    return baseValue(metric, fips);
  }

  // A county the CURRENT metric cannot rank because its basis risk is unknown — as distinct
  // from a county with no eligible acres at all. Only the basis metrics have this state.
  function basisUnknown(fips) {
    if (!METRICS[metric].basis) return false;
    var s = stats(fips);
    return !!s && !s.br;
  }

  // ---------------- formatting
  function fmtMoney(v, dp) {
    if (v === null || v === undefined) return "&mdash;";
    return "$" + v.toLocaleString(undefined,
      { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function fmtBig(v) {
    if (v === null || v === undefined) return "&mdash;";
    var a = Math.abs(v);
    if (a >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return "$" + Math.round(v / 1e3) + "k";
    return "$" + v.toFixed(0);
  }
  function fmtAc(v) {
    if (v === null || v === undefined) return "&mdash;";
    return Math.round(v).toLocaleString() + " ac";
  }
  function fmtPct(v) {
    return (v === null || v === undefined) ? "&mdash;" : (v * 100).toFixed(1) + "%";
  }
  function fmtRate(v) {
    return (v === null || v === undefined) ? "&mdash;" : (+v).toFixed(2) + "%";
  }
  function fmtFull(v) {
    if (metric === "pen" || metric === "miss") return fmtPct(v);
    if (metric === "ret") return (v === null ? "&mdash;" : v.toFixed(2) + "&times;");
    if (metric === "gap" || metric === "bgap") {
      return (v === null ? "&mdash;" : (v >= 0 ? "+" : "") + v.toFixed(0) + " pts");
    }
    if (metric === "total" || metric === "commtot" || metric === "adjtotal") return fmtBig(v);
    return fmtMoney(v, 2) + "/ac";
  }
  function fmtShort(v) {
    if (v === null || v === undefined) return "&mdash;";
    if (metric === "pen" || metric === "miss") return Math.round(v * 100) + "%";
    if (metric === "ret") return v.toFixed(2) + "x";
    if (metric === "gap" || metric === "bgap") return (v >= 0 ? "+" : "") + Math.round(v);
    if (metric === "total" || metric === "commtot" || metric === "adjtotal") return fmtBig(v);
    return "$" + (Math.abs(v) < 100 ? v.toFixed(2) : Math.round(v).toLocaleString());
  }
  function readoutSuffix() {
    if (metric === "pen" || metric === "miss") return "";
    if (metric === "ret") return " per $1";
    if (metric === "gap" || metric === "bgap") return " pts";
    if (metric === "total" || metric === "commtot" || metric === "adjtotal") return "";
    return "/ac";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ---------------- colour scale + range slider
  var lo = 0, hi = 1, hasData = false, scale = null, ramp = RAMP;
  var rMin = document.getElementById("rMin"), rMax = document.getElementById("rMax"),
      rFill = document.getElementById("rFill"), rReadout = document.getElementById("rReadout"),
      rBar = document.getElementById("rangebar"),
      bubbleLo = document.getElementById("rBubbleLo"),
      bubbleHi = document.getElementById("rBubbleHi");
  [rMin, rMax].forEach(function (r) { r.min = 0; r.max = UNITS; r.step = 1; });

  // EVERY metric here is derived from the current crop / band / evidence / AIP selection —
  // there is no "stored" metric with a fixed global domain, as there is on the PRF map — so
  // the domain is always recomputed over exactly what is on screen.
  function domainFor() {
    var min = null, max = null;
    for (var f in COUNTIES) {
      var v = valFor(f);
      if (v === null || v === undefined || !isFinite(v)) continue;
      if (min === null || v < min) min = v;
      if (max === null || v > max) max = v;
    }
    return [min, max];
  }

  function syncControls() {
    var m = METRICS[metric];
    document.getElementById("aipWrap").style.display = m.needsComm ? "" : "none";
    var tag = document.getElementById("famTag");
    tag.className = "fam " + m.family;
    tag.textContent = m.family + (m.assumed ? " · assumed rate" : " · computed");
    var notes = document.querySelectorAll("#formulaNote .fn");
    Array.prototype.forEach.call(notes, function (el) {
      el.classList.toggle("on", el.getAttribute("data-m") === metric);
    });
    document.getElementById("pageTitle").textContent = m.title;
    document.getElementById("pageSub").textContent =
      m.sub + " Reinsurance year " + (DATA.year || "—") + "; generated " + DATA.generated + ".";
    document.getElementById("pageFoot").innerHTML = footNote();
  }

  // Always on screen, inside the <summary> that never collapses: how much of this map has a
  // basis-risk answer at all. The counts are the honest scale of the caveat above them.
  (function () {
    var c = BMETA.counts || {}, el = document.getElementById("caveatCover");
    if (!el) return;
    var tot = (c.covered || 0) + (c.partial || 0) + (c.unknown || 0);
    el.innerHTML = !BMETA.loaded || !tot
      ? "Basis risk is not measured in this database at all."
      : ("Measured for " + (((c.covered || 0) + (c.partial || 0)) / tot * 100).toFixed(0) +
         "% of the county × crop × band cells here (" +
         (c.covered || 0).toLocaleString() + " fully, " + (c.partial || 0).toLocaleString() +
         " partly); " + (c.unknown || 0).toLocaleString() + " are UNKNOWN, which is not low.");
  })();

  function footNote() {
    var base = "Eligible acres = individual additional-coverage MPCI acres (YP, RP, RP-HPE, "
      + "APH); CAT acres are excluded because a CAT policy cannot carry a band. Penetration "
      + "is capped at 100% (" + (DATA.capped_cells || 0) + " cells nationally exceeded it and "
      + "were clipped). Per-acre dollars are this county's own where it sells the band, and "
      + "fitted from its liability per acre where it does not — the tooltip says which for "
      + "every county. Source: RMA Summary of Business, county grain, RY" + (DATA.year || "—")
      + "; precomputed by src/rowcropopt.py into rowcrop_unclaimed.";
    if (METRICS[metric].basis) {
      base += " BASIS RISK is joined from basis_risk_county on county x crop x band ("
        + (BVARIANT[band] ? band + " -> " + BVARIANT[band] + ", " : "")
        + (BMETA.plan_type || "RP") + " at the farm's own "
        + (100 * (BMETA.coverage_level || 0.85)).toFixed(0) + "% coverage level). Its county "
        + "side is MEASURED from NASS county yield history; its farm side is MODELLED from "
        + "that series plus one imported parameter, the farm-county yield correlation. Every "
        + "figure describes a TYPICAL farm in the county and none of them describes any actual "
        + "farm. See src/basisrisk.py, docs/basis_risk.md and docs/rowcrop_opportunity.md.";
    }
    if (METRICS[metric].needsComm) {
      base += " COMMISSION RATES ARE YOUR OWN and are hand-entered in " + esc(COMM.path)
        + " (AIP x region) or " + esc(CZONE.path) + "; the values shipped there are SAMPLE "
        + "data, not negotiated rates.";
    }
    return base;
  }

  function applyMetric() {
    statCache = {}; pctlCache = null; unkCache = null;
    var mm = domainFor();
    hasData = mm[0] !== null && mm[1] !== null;
    lo = hasData ? mm[0] : 0;
    hi = hasData ? mm[1] : 1;
    if (hi <= lo) hi = lo + 0.01;
    if (METRICS[metric].diverging) {
      // Symmetric domain so 0 lands in the middle band and the two directions are comparable.
      var m2 = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
      lo = -m2; hi = m2;
      ramp = RAMP_DIV;
    } else if (METRICS[metric].risk) {
      ramp = RAMP_RISK;
    } else {
      ramp = RAMP;
    }
    scale = d3.scaleQuantize().domain([lo, hi]).range(ramp);
    rMin.value = 0; rMax.value = UNITS;
    rBar.style.display = hasData ? "" : "none";
    document.getElementById("rangeLabel").textContent = METRICS[metric].legend + " range";
    updateRange();
    refresh();
  }

  function unitLo() { return Math.min(+rMin.value, +rMax.value); }
  function unitHi() { return Math.max(+rMin.value, +rMax.value); }
  function toVal(u) { return lo + (hi - lo) * u / UNITS; }
  function rangeLo() { return toVal(unitLo()); }
  function rangeHi() { return toVal(unitHi()); }
  function isFullRange() { return unitLo() <= 0 && unitHi() >= UNITS; }
  function updateRange() {
    var a = unitLo() / UNITS, b = unitHi() / UNITS;
    rFill.style.left = (a * 100) + "%";
    rFill.style.width = ((b - a) * 100) + "%";
    bubbleLo.innerHTML = fmtShort(rangeLo());
    bubbleLo.style.left = "calc(" + (a * 100) + "% - " + (a * 16 - 8) + "px)";
    bubbleHi.innerHTML = fmtShort(rangeHi());
    bubbleHi.style.left = "calc(" + (b * 100) + "% - " + (b * 16 - 8) + "px)";
    rReadout.innerHTML = fmtShort(rangeLo()) + " &ndash; " + fmtShort(rangeHi()) + readoutSuffix();
  }

  // `pen` shades DARK where penetration is LOW: the page is about what is unsold, so the
  // eye should land on the same counties it lands on for every other metric here.
  function colorOf(v) {
    if (v === null || v === undefined || !isFinite(v)) return NONE;
    var rlo = rangeLo(), rhi = rangeHi(), eps = Math.abs(hi - lo) * 1e-9;
    if (v < rlo - eps || v > rhi + eps) return NONE;
    return scale(METRICS[metric].invert ? (lo + hi - v) : v);
  }

  function drawLegend() {
    var el = document.getElementById("legend");
    if (!hasData && !METRICS[metric].basis) { el.style.display = "none"; return; }
    el.style.display = "";
    if (!hasData) {                       // every county unknown: say THAT, not nothing
      el.innerHTML = '<div class="l-title">' + esc(METRICS[metric].legend) + '</div>' +
        '<div class="l-unk"><span class="sw"></span><span><b>Basis risk unknown</b> for every ' +
        'county in this selection. ' + esc(unknownWhy()) + '</span></div>';
      return;
    }
    var inv = !!METRICS[metric].invert;
    var cells = ramp.map(function (c) {
      return '<div class="l-cell" style="background:' + c + '"></div>';
    });
    if (inv) cells.reverse();
    var thr = scale.thresholds();
    var labels = '<span>' + fmtShort(lo) + '</span>' +
      thr.map(function (t) { return '<span>' + fmtShort(t) + '</span>'; }).join("");
    el.innerHTML =
      '<div class="l-title">' + esc(METRICS[metric].legend) +
      (inv ? ' <span style="color:var(--muted)">(dark = low)</span>' : '') + '</div>' +
      '<div class="l-row">' + cells.join("") + '</div>' +
      '<div class="l-labels">' + labels + '</div>' +
      '<div class="l-none"><span class="sw"></span>no eligible acres, or the band is not ' +
      (minEvidence > 0 ? 'sold at this evidence level' : 'priced here') + '</div>' +
      (METRICS[metric].basis
        ? '<div class="l-unk"><span class="sw"></span><span><b>basis risk unknown</b> &mdash; ' +
          unknownCount() + ' counties, not ranked here. <b>Unknown is not low.</b></span></div>'
        : '');
  }

  // Why the current band/crop selection has no basis-risk estimate. Named reasons, from the
  // payload — never a shrug, because a shrug is what gets read as "probably fine".
  function unknownWhy() {
    var bands = (band === ALL_BANDS ? PRESENT : [band]);
    var reasons = [];
    bands.forEach(function (b) { if (BNOTE[b] && reasons.indexOf(BNOTE[b]) < 0) reasons.push(BNOTE[b]); });
    if (!reasons.length) reasons.push(BMETA.crop_note || "");
    if (band === ALL_BANDS && bands.some(function (b) { return !BVARIANT[b]; })) {
      reasons.push("Under “All bands” one unmodelled band makes the whole selection " +
                   "unknown: the bands are different products and one’s basis risk is not " +
                   "a stand-in for another’s. Pick a single band.");
    }
    return reasons.join(" ");
  }
  var unkCache = null;
  function unknownCount() {
    if (unkCache !== null) return unkCache;
    var n = 0;
    for (var f in COUNTIES) if (basisUnknown(f)) n++;
    unkCache = n;
    return n;
  }

  // ---------------- tooltip
  var tip = document.getElementById("tooltip");
  function nameFor(d) {
    return DATA.county_names[d.id] || (d.properties && d.properties.name) || "County";
  }
  function selLabel() {
    var b = band === ALL_BANDS ? "all bands" : band;
    return esc(CROPS[+fCrop.value] || "") + " · " + esc(b);
  }
  function basisLine(s) {
    var keys = Object.keys(s.basis);
    if (!keys.length) return '';
    var txt = keys.map(function (k) { return (DATA.basis_note || {})[k] || k; }).join("; ");
    var observed = keys.length === 1 && keys[0] === "county";
    return '<div class="t-flag">' + (observed ? "&#10003; " : "&#8776; ") + esc(txt) + '</div>';
  }
  function evidenceLine(s) {
    var lab = (DATA.evidence_labels || {})[String(s.ev)] || "";
    if (s.ev >= 2) return '';
    return '<div class="t-warn">Band ' + esc(lab) +
      ' — a zero here may be non-availability rather than opportunity.</div>';
  }

  // The basis-risk block. Shown on EVERY tooltip, whatever metric is selected, including — and
  // especially — when the answer is "we do not know". A dollar figure on this map without this
  // block beside it is the exact reading the whole join exists to prevent.
  function basisRiskLine(fips, s) {
    var h = '<div class="t-sec"><b>Basis risk</b> ';
    if (!BMETA.loaded) {
      return h + '&mdash; basis_risk_county is not in this database, so nothing here is ' +
             'measured. Run scripts/analysis/build_basis_risk.py.</div>';
    }
    if (!s.br) {
      var miss = s.brMissing.length ? s.brMissing.join(", ") : (band === ALL_BANDS ? "" : band);
      return h + '<b style="color:#9c2a1c">UNKNOWN</b>' +
             (miss ? ' for ' + esc(miss) : '') +
             ' &mdash; <b>not low, not zero, not ranked.</b><div class="t-flag">' +
             esc(unknownWhy()) + '</div></div>';
    }
    var b = s.br;
    h += (100 * b.miss).toFixed(0) + '% miss rate';
    if (b.grade) h += ' &middot; grade ' + esc(b.grade);
    h += '</div>';
    h += '<div class="t-math">the band pays <b>nothing</b> in ' + (100 * b.miss).toFixed(0) +
         '% of the years a typical farm here has a loss &middot; &rho; 0.55&ndash;0.85 &rarr; ' +
         (100 * b.rlo).toFixed(0) + '%&ndash;' + (100 * b.rhi).toFixed(0) + '%</div>';
    h += '<div class="t-math">' + (100 * b.uncov).toFixed(0) +
         '% of in-band loss <i>dollars</i> uncovered &middot; deep-loss miss ' +
         (100 * b.deep).toFixed(0) + '%</div>';
    if (s.sub !== null && s.adjSub !== null) {
      h += '<div class="t-math">unclaimed ' + fmtBig(s.sub) + ' &rarr; <b>' +
           fmtBig(s.adjSub) + '</b> basis-adjusted</div>';
    }
    if (b.partial) {
      h += '<div class="t-warn">PARTIAL: crops with an estimate carry ' +
           (100 * b.share).toFixed(0) + '% of the eligible acres here; the rest is assumed to ' +
           'behave like them.</div>';
    }
    h += '<div class="t-flag">typical farm, not this farm &middot; county side measured from ' +
         'NASS, farm side modelled &middot; ' + esc(BMETA.plan_type || "RP") +
         ' at the farm\'s own ' + (100 * (BMETA.coverage_level || 0.85)).toFixed(0) +
         '% coverage level, the highest common election and so the highest miss rate</div>';
    return h;
  }

  function tipHtml(d) {
    var fips = String(d.id), s = stats(fips);
    var h = '<div class="t-name">' + esc(nameFor(d)) + ' County &mdash; ' + selLabel() + '</div>';
    if (!s) {
      return h + '<div class="t-val">no eligible acres for this selection' +
        (minEvidence > 0 ? ', or the band clears no evidence bar here' : '') + '</div>';
    }
    h += '<div class="t-val">' + esc(METRICS[metric].legend) + ': <b>' +
         fmtFull(valFor(fips)) + '</b></div>';
    h += '<div class="t-math">' + fmtAc(s.baseMax) + ' eligible &middot; ' +
         fmtPct(s.pen) + ' penetration &middot; ' + fmtAc(s.unsold) + ' unsold</div>';
    h += '<div class="t-math">unclaimed subsidy ' + fmtBig(s.sub) +
         '  (' + fmtMoney(s.subPA, 2) + '/ac captured &times; ' + fmtAc(s.unsold) + ')</div>';
    h += '<div class="t-sec"><b>Producer</b>: ' + fmtMoney(s.subPA, 2) +
         '/ac of federal subsidy captured' +
         (s.ret === null ? '' : ', ' + s.ret.toFixed(2) + '&times; back per $1 of own premium') +
         '</div>';
    var src = commSource(fips), pct = src.pct;
    if (pct === null || pct === undefined) {
      h += '<div class="t-sec"><b>Agency</b>: no commission rate set for ' +
           esc(aip() ? aip().name : "this AIP") + ' or the ' + esc(zoneFor(fips) || "unknown") +
           ' region &mdash; add one in ' + esc(COMM.path) + '</div>';
    } else {
      h += '<div class="t-sec"><b>Agency</b>: ' + fmtMoney(s.premPA, 2) +
           '/ac total premium &times; ' + fmtRate(pct) + ' = ' +
           fmtMoney(s.premPA === null ? null : s.premPA * pct / 100, 2) + '/ac commission; ' +
           fmtBig(s.prem === null ? null : s.prem * pct / 100) + ' unclaimed</div>';
      h += '<div class="t-flag">rate: ' + esc(src.from) + ' (' + esc(src.path) +
           ') &mdash; SAMPLE data unless you have replaced it</div>';
    }
    var gp = gapFor(fips);
    if (gp !== null) {
      var p = percentiles();
      h += '<div class="t-math">rank: agency ' + Math.round(p.comm[fips]) +
           'th pctl &middot; producer ' + Math.round(p.prod[fips]) + 'th pctl &middot; gap ' +
           (gp >= 0 ? '+' : '') + gp.toFixed(0) + ' pts</div>';
    }
    h += basisRiskLine(fips, s);
    var bg = bgapFor(fips);
    if (bg !== null) {
      var p2 = percentiles();
      h += '<div class="t-math">rank: raw ' + Math.round(p2.raw[fips]) + 'th pctl &middot; ' +
           'basis-adjusted ' + Math.round(p2.adj[fips]) + 'th pctl &middot; ' +
           (bg >= 0 ? 'raw OVERSELLS by +' : 'raw undersells by ') + bg.toFixed(0) +
           ' pts</div>';
    }
    h += basisLine(s);
    h += evidenceLine(s);
    return h;
  }

  function hover(ev, d) {
    d3.select(this).classed("hovered", true);
    tip.style.display = "block";
    tip.innerHTML = tipHtml(d);
    var wrap = document.getElementById("mapWrap").getBoundingClientRect();
    var x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 10;
    if (x > wrap.width - 370) x -= 390;
    tip.style.left = x + "px"; tip.style.top = Math.max(0, y) + "px";
  }
  function unhover() {
    d3.select(this).classed("hovered", false);
    tip.style.display = "none";
  }

  // ---------------- drill-down: nation -> state -> county
  // TWO data levels below the nation, and no more. SCO, ECO and STAX all trigger on a COUNTY
  // index, so the county is the finest grain RMA prices these bands at: there is nothing to
  // draw underneath one. Drilling into a county therefore opens its crop x band BREAKDOWN
  // instead of a sub-county geometry that does not exist.
  var K_MIN = 1, K_MAX = 96;
  var level = 0, focusState = null, focusCounty = null, curK = 1;

  var zoom = d3.zoom().scaleExtent([K_MIN, K_MAX]).on("zoom", function (ev) {
    g.attr("transform", ev.transform);
    curK = ev.transform.k;
    syncZoomUI();
  });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", function () { drillOut(); });

  // Animate, EXCEPT in a hidden tab. d3's transition scheduler runs on requestAnimationFrame,
  // which browsers suspend while a tab is backgrounded, so an animated zoom started there
  // never advances past CREATED — the map freezes mid-flight and stays frozen after you
  // switch back. Applying the transform directly when document.hidden keeps it correct.
  function applyTransform(t, dur) {
    if (dur === 0 || document.hidden) svg.call(zoom.transform, t);
    else svg.transition().duration(dur).call(zoom.transform, t);
  }
  function zoomToFeature(f, dur) {
    var b = path.bounds(f);
    var dx = b[1][0] - b[0][0], dy = b[1][1] - b[0][1];
    var cx = (b[0][0] + b[1][0]) / 2, cy = (b[0][1] + b[1][1]) / 2;
    var k = Math.max(K_MIN, Math.min(K_MAX, 0.85 / Math.max(dx / 975, dy / 610)));
    applyTransform(d3.zoomIdentity.translate(975 / 2 - k * cx, 610 / 2 - k * cy).scale(k),
                   dur === undefined ? 650 : dur);
  }
  function resetZoom(dur) {
    applyTransform(d3.zoomIdentity, dur === undefined ? 650 : dur);
  }

  // A county click means "closer": from the nation it selects that county's STATE (clicking a
  // 3-pixel county to select the state is what a user actually intends at that zoom); from
  // the state it drills to the county and opens its breakdown.
  function countyClicked(d) {
    var st = String(d.id).slice(0, 2);
    if (level === 0) {
      focusState = st; focusCounty = null; level = 1;
      if (stateById[st]) zoomToFeature(stateById[st]);
    } else {
      focusState = st; focusCounty = String(d.id); level = 2;
      zoomToFeature(d);
    }
    applyLevel();
  }
  function drillOut() {
    if (level === 2) { focusCounty = null; level = 1;
                       if (stateById[focusState]) zoomToFeature(stateById[focusState]); }
    else if (level === 1) { focusState = null; level = 0; resetZoom(); }
    else return;
    applyLevel();
  }
  function drillTo(lv) {
    if (lv === 0) { level = 0; focusState = null; focusCounty = null; resetZoom(); }
    else if (lv === 1 && focusState) { level = 1; focusCounty = null;
                                       if (stateById[focusState]) zoomToFeature(stateById[focusState]); }
    applyLevel();
  }

  function applyLevel() {
    countySel
      .classed("dimmed", function (d) {
        if (level === 0) return false;
        return String(d.id).slice(0, 2) !== focusState;
      })
      .classed("focused", function (d) { return level === 2 && String(d.id) === focusCounty; });
    var focusFeat = focusCounty ? countyById[focusCounty] : null;
    gFocus.attr("d", (level === 2 && focusFeat) ? path(focusFeat) : null);
    renderDetail();
    updateCrumb();
  }

  // The county panel: every crop x band cell this county has, at the CURRENT evidence bar,
  // with the per-crop unclaimed dollars. This is the drill-down's payload — the level below a
  // county is not geography, it is the crop mix.
  var detail = document.getElementById("detail");
  function renderDetail() {
    if (level !== 2 || !focusCounty) { detail.style.display = "none"; return; }
    var byCrop = COUNTIES[focusCounty];
    var name = DATA.county_names[focusCounty] ||
               (countyById[focusCounty] && countyById[focusCounty].properties &&
                countyById[focusCounty].properties.name) || "County";
    var rows = [], totSub = 0, totPrem = 0, totUnsold = 0, anySub = false;
    var pct = commPct(focusCounty);
    if (byCrop) {
      CROPS.forEach(function (cropName, ci) {
        var byBand = byCrop[String(ci)];
        if (!byBand) return;
        BANDS.forEach(function (bandName, bi) {
          var c = byBand[String(bi)];
          if (!c) return;
          if (band !== ALL_BANDS && bandName !== band) return;
          if (c[C_EV] < minEvidence) return;
          var base = c[C_BASE], bandAc = Math.min(c[C_BAND], base), unsold = base - bandAc;
          var sub = (c[C_SUB] === null || c[C_SUB] === undefined) ? null : unsold * c[C_SUB];
          var prem = (c[C_PREM] === null || c[C_PREM] === undefined) ? null : unsold * c[C_PREM];
          var isAll = cropName === DATA.all_crops;
          if (isAll) { totSub = sub === null ? totSub : (anySub = true, totSub + sub);
                       totPrem += prem || 0; totUnsold += unsold; }
          var brc = (BR[focusCounty] && BR[focusCounty][String(ci)] &&
                     BR[focusCounty][String(ci)][String(bi)]) || null;
          rows.push({ crop: cropName, band: bandName, all: isAll, base: base,
                      pen: base > 0 ? bandAc / base : null, unsold: unsold, sub: sub,
                      prem: prem, ev: c[C_EV], br: brc,
                      adj: (brc && sub !== null) ? sub * (1 - brc[B_MISS]) : null });
        });
      });
    }
    rows.sort(function (a, b) {
      if (a.all !== b.all) return a.all ? -1 : 1;
      return (b.sub || 0) - (a.sub || 0);
    });
    var h = '<span class="d-close" id="dClose">close &times;</span>' +
            '<h2>' + esc(name) + ' County &mdash; RY' + (DATA.year || "") + '</h2>';
    if (!rows.length) {
      h += '<div class="d-note">No eligible acres here for the current crop, band and ' +
           'evidence selection.</div>';
    } else {
      h += '<table><thead><tr><th>crop &middot; band</th><th>pen</th>' +
           '<th>unclaimed</th><th>basis-adj</th><th>miss</th></tr></thead><tbody>';
      rows.slice(0, 22).forEach(function (r) {
        h += '<tr class="' + (r.all ? 'tot' : 'sub') + '"><td>' + esc(r.crop) +
             (band === ALL_BANDS ? ' &middot; ' + esc(r.band) : '') + '</td><td>' +
             fmtPct(r.pen) + '</td><td>' + fmtBig(r.sub) + '</td><td>' +
             (r.br ? fmtBig(r.adj) : '<span style="color:#9c2a1c">unknown</span>') +
             '</td><td>' + (r.br ? (100 * r.br[B_MISS]).toFixed(0) + '%' +
                            (r.br[B_SHARE] < 0.999 ? '*' : '') : '&mdash;') + '</td></tr>';
      });
      h += '</tbody></table>';
      h += '<div class="d-note">Unclaimed subsidy on unsold acres, then the same dollars ' +
           'weighted by P(the band pays | the farm has a loss). <b>unknown</b> means no ' +
           'basis-risk estimate for that crop and band &mdash; not a low one. * = the rollup\'s ' +
           'estimate covers only part of its eligible acres. ' +
           (pct === null || pct === undefined
             ? 'No commission rate set, so no agency figure is shown.'
             : 'At ' + fmtRate(pct) + ', the unsold premium here is worth ' +
               fmtBig(totPrem * pct / 100) + ' of commission (SAMPLE rate).') +
           ' Rows are the (all crops) rollup first, then the biggest crops. There is no ' +
           'geography below a county here: SCO, ECO and STAX all trigger on the COUNTY ' +
           'index, so the county is the finest grain these bands are priced at.</div>';
    }
    detail.innerHTML = h;
    // "block", NOT "": the stylesheet hides #detail by default, so clearing the inline style
    // falls straight back through to display:none and the panel renders into a 0x0 box with
    // all the right content in it. Same trap prfpage documents for #formulaNote.
    detail.style.display = "block";
    var close = document.getElementById("dClose");
    if (close) close.addEventListener("click", function (ev) { ev.stopPropagation(); drillTo(1); });
  }

  // ---------------- the RANKING view
  // Three columns, always, whatever metric is driving the sort: RAW opportunity, BASIS-ADJUSTED
  // opportunity, and the basis-risk term between them. One table rather than two lists, because
  // two lists let a reader pick the flattering one and never see that they disagree. Counties
  // with no basis-risk estimate are still LISTED — dropping them would quietly turn a ranking
  // of everything into a ranking of the measured half — but their adjusted cell says UNKNOWN.
  var rankPanel = document.getElementById("rank"), rankBtn = document.getElementById("rankBtn");
  var rankOpen = false, RANK_N = 30;
  // Rounded, and "-0" never printed: a county that moved a third of a percentile did not move.
  function fmtGap(v) {
    var r = Math.round(v) || 0;
    return '<span class="' + (r > 0 ? "r-dn" : (r < 0 ? "r-up" : "")) + '">' +
           (r > 0 ? "+" : "") + r + '</span>';
  }
  function renderRank() {
    if (!rankOpen) { rankPanel.style.display = "none"; return; }
    var perAcre = (metric === "acre" || metric === "adjacre" || metric === "prodac" ||
                   metric === "commac" || metric === "miss" || metric === "pen" ||
                   metric === "gap" || metric === "bgap" || metric === "ret");
    // Two lists, and the split is the point. `ranked` is every county the current metric can
    // actually value. `unranked` is every county with eligible acres whose basis risk is
    // UNKNOWN: they are shown, counted and named, immediately under the ranking and never
    // inside it. Mixing them in on their raw value would let an unmeasured county outrank a
    // measured one on the strength of the very term that is missing; dropping them would turn
    // a ranking of the country into a ranking of the measured half without saying so.
    var ranked = [], unranked = [];
    for (var f in COUNTIES) {
      var s = stats(f); if (!s) continue;
      var raw = perAcre ? s.acre : s.sub;
      var adj = perAcre ? s.adjSubPA : s.adjSub;
      var v = valFor(f);
      var row = { f: f, raw: raw, adj: adj, s: s, sort: v };
      if (v !== null && v !== undefined && isFinite(v)) ranked.push(row);
      else if (basisUnknown(f) && raw !== null) unranked.push(row);
    }
    ranked.sort(function (a, b) { return b.sort - a.sort; });
    unranked.sort(function (a, b) { return (b.raw || 0) - (a.raw || 0); });
    var money = function (v) { return v === null || v === undefined ? "&mdash;"
                                     : (perAcre ? "$" + v.toFixed(2) : fmtBig(v)); };
    var h = '<span class="r-close" id="rClose">close &times;</span>' +
      '<h2>Top counties &mdash; ' + esc(CROPS[+fCrop.value] || "") + ' &middot; ' +
      esc(band === ALL_BANDS ? "all bands" : band) + ', RY' + (DATA.year || "") + '</h2>' +
      '<div class="r-note">Sorted by <b>' + esc(METRICS[metric].legend) + '</b>. ' +
      (perAcre ? 'Dollars are per ELIGIBLE ACRE.' : 'Dollars are county totals.') + '</div>';
    if (!ranked.length && !unranked.length) {
      h += '<div class="r-note">Nothing to rank for this selection.</div>';
    } else {
      var line = function (r, i, cls) {
        var bg = bgapFor(r.f);
        var missCell = r.s.br ? (100 * r.s.br.miss).toFixed(0) + "%" +
                                (r.s.br.partial ? "*" : "") : "unknown";
        return '<tr class="' + cls + '" data-f="' + esc(r.f) + '"><td>' +
             (i === null ? "" : i + ". ") + esc(DATA.county_names[r.f] || r.f) + ' ' +
             esc(DATA.county_states[r.f] || "") + '</td><td>' + money(r.raw) + '</td><td>' +
             (r.s.br ? money(r.adj) : '<b>unknown</b>') + '</td><td>' + missCell + '</td><td>' +
             (bg === null ? "&mdash;" : fmtGap(bg)) + '</td></tr>';
      };
      h += '<table><thead><tr><th>county</th><th>raw</th><th>basis-adj</th><th>miss</th>' +
           '<th>&Delta;rank</th></tr></thead><tbody>';
      ranked.slice(0, RANK_N).forEach(function (r, i) { h += line(r, i + 1, ""); });
      if (unranked.length) {
        h += '<tr><td colspan="5" style="padding-top:8px;color:#9c2a1c;font-weight:650">' +
             'NOT RANKED &mdash; basis risk unknown (' + unranked.length +
             ' counties, biggest raw first)</td></tr>';
        unranked.slice(0, 8).forEach(function (r) { h += line(r, null, "unk"); });
      }
      h += '</tbody></table>';
      h += '<div class="r-note"><b>raw</b> = unclaimed federal subsidy. <b>basis-adj</b> = the ' +
           'same dollars &times; P(the band pays | the farm has a loss). <b>&Delta;rank</b> is ' +
           'the raw percentile minus the adjusted one: <span class="r-dn">amber</span> means ' +
           'the raw ranking oversells this county, <span class="r-up">green</span> means it ' +
           'undersells it. ' +
           (unranked.length
             ? 'The counties below the break have <b>no basis-risk estimate at all</b> and are ' +
               'deliberately kept out of the ranking rather than scored on the raw column ' +
               '&mdash; <b>unknown is not low</b>. ' : '') +
           '* = partial coverage; the crops with an estimate carry only part of the eligible ' +
           'acres. Click a row to zoom to that county.</div>';
    }
    rankPanel.innerHTML = h;
    rankPanel.style.display = "block";        // "block", not "" — see #detail below
    var rc = document.getElementById("rClose");
    if (rc) rc.addEventListener("click", function (ev) { ev.stopPropagation(); toggleRank(false); });
    rankPanel.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var f = tr.getAttribute("data-f"), feat = countyById[f];
        if (!feat) return;
        focusState = f.slice(0, 2); focusCounty = f; level = 2;
        zoomToFeature(feat); applyLevel();
      });
    });
  }
  function toggleRank(on) {
    rankOpen = on === undefined ? !rankOpen : !!on;
    rankBtn.classList.toggle("on", rankOpen);
    renderRank();
  }
  rankBtn.addEventListener("click", function (ev) { ev.stopPropagation(); toggleRank(); });

  var crumb = document.getElementById("crumb");
  function stateNameOf(fips) {
    var s = stateById[fips];
    return (s && s.properties && s.properties.name) || "State";
  }
  function updateCrumb() {
    var h = '<span class="' + (level === 0 ? "c-here" : "c-step") + '" data-lv="0">United States</span>';
    if (focusState) {
      h += '<span class="c-sep">&rsaquo;</span><span class="' +
           (level === 1 ? "c-here" : "c-step") + '" data-lv="1">' +
           esc(stateNameOf(focusState)) + '</span>';
    }
    if (focusCounty) {
      h += '<span class="c-sep">&rsaquo;</span><span class="c-here">' +
           esc(DATA.county_names[focusCounty] || "County") + ' County</span>';
    }
    var hint = level === 0 ? "click a state to zoom"
             : level === 1 ? "click a county for its crop mix"
             : "county is the finest grain these bands are priced at &middot; click away to go back";
    h += '<span class="c-hint">' + hint + '</span>';
    crumb.innerHTML = h;
    crumb.querySelectorAll(".c-step").forEach(function (el) {
      el.addEventListener("click", function (ev) {
        ev.stopPropagation(); drillTo(parseInt(el.getAttribute("data-lv"), 10));
      });
    });
  }

  // ---------------- zoom slider (logarithmic: each step is the same PROPORTIONAL change)
  var zSlider = document.getElementById("zSlider"), zLabel = document.getElementById("zLabel");
  function kToSlider(k) { return 100 * Math.log(k / K_MIN) / Math.log(K_MAX / K_MIN); }
  function sliderToK(v) { return K_MIN * Math.pow(K_MAX / K_MIN, v / 100); }
  function syncZoomUI() {
    zSlider.value = String(kToSlider(curK));
    zLabel.innerHTML = (curK < 10 ? curK.toFixed(1) : Math.round(curK)) + "&times;";
  }
  function zoomToK(k) {
    var kk = Math.max(K_MIN, Math.min(K_MAX, k));
    if (document.hidden) svg.call(zoom.scaleTo, kk);
    else svg.transition().duration(120).call(zoom.scaleTo, kk);
  }
  zSlider.addEventListener("input", function () { zoomToK(sliderToK(+zSlider.value)); });
  document.getElementById("zIn").addEventListener("click", function (ev) {
    ev.stopPropagation(); zoomToK(curK * 1.6);
  });
  document.getElementById("zOut").addEventListener("click", function (ev) {
    ev.stopPropagation(); zoomToK(curK / 1.6);
  });

  // ---------------- render / recolor
  function refresh() {
    var shaded = 0, unknown = 0;
    countySel.attr("fill", function (d) {
      var fips = String(d.id);
      // Hatched, NOT grey and NOT pale: "no basis-risk answer here" is a third state, and it
      // has to be visibly different from both "no eligible acres" and "low basis risk".
      if (basisUnknown(fips)) { unknown++; return UNKNOWN_FILL; }
      var c = colorOf(valFor(fips));
      if (c !== NONE) shaded++;
      return c;
    });

    var total = 0, any = false;
    if (metric === "total" || metric === "commtot" || metric === "adjtotal") {
      for (var f in COUNTIES) {
        var v = valFor(f);
        if (v !== null && v !== undefined && isFinite(v)) { total += v; any = true; }
      }
    }
    var line = document.getElementById("countLine");
    line.innerHTML = (!hasData && !unknown) ? "" : (shaded + " counties" +
      (any ? " &middot; " + fmtBig(total) + " nationally" : "") +
      (unknown ? ' &middot; <span style="color:#9c2a1c">' + unknown +
                 " basis risk unknown</span>" : "") +
      (isFullRange() ? "" : " at " + fmtShort(rangeLo()) + "&ndash;" + fmtShort(rangeHi()) +
                            readoutSuffix()));

    var note = document.getElementById("note"), msg = "";
    if (!DATA.row_count) {
      msg = "The row-crop opportunity table is empty or missing. Run "
          + "`.venv/bin/python -m src.rowcropopt` against the WORKING catalog "
          + "(data/catalog.db) — the county-grain sob_sales it reads is dropped from the "
          + "shipped app DB, so this map can only ever read the precomputed result.";
    } else if (METRICS[metric].needsComm && !COMM.aips.length) {
      msg = "No AIPs listed in " + COMM.path + " — add one row per AIP you write and reload.";
    } else if (METRICS[metric].needsComm && !anyRateSet()) {
      msg = "No commission rates set — fill in " + COMM.path + " (a percent of TOTAL premium, "
          + "e.g. 12.5) or " + CZONE.path + ", then reload. Commission is negotiated between "
          + "you and each AIP and is published nowhere, so it cannot be derived; nothing is "
          + "shaded until you enter it.";
    } else if (METRICS[metric].basis && !BMETA.loaded) {
      msg = "basis_risk_county is empty or absent in this database, so every county on this "
          + "map is 'basis risk unknown'. Run `.venv/bin/python "
          + "scripts/analysis/build_basis_risk.py` against the WORKING catalog (it reads "
          + "nass_county_yield, which is dropped from the shipped app DB). Unknown is NOT low.";
    } else if (METRICS[metric].basis && shaded === 0) {
      msg = "No county in this selection has a basis-risk estimate. " + unknownWhy();
    } else if (shaded === 0) {
      msg = "No counties have a value for this selection"
          + (isFullRange() ? "" : " and range") + ".";
    } else if (METRICS[metric].basis && unknown > shaded) {
      msg = unknown + " of the " + (unknown + shaded) + " counties with eligible acres here "
          + "have NO basis-risk estimate and are hatched, not ranked. " + unknownWhy();
    } else {
      // A band in its FIRST book year reads as almost entirely unclaimed because nobody has
      // had the chance to buy it yet — that is a calendar fact, not an opportunity, and it
      // would otherwise put the newest endorsement at the top of every ranking on this page.
      var newBands = (band === ALL_BANDS ? PRESENT : [band]).filter(function (b) {
        return BSUM[b] && BSUM[b]["new"];
      });
      if (newBands.length) {
        msg = newBands.join(" and ") + " is in its FIRST book year (RY" + (DATA.year || "") +
              "), at " + (BSUM[newBands[0]].pen === null ? "very low"
                          : (100 * BSUM[newBands[0]].pen).toFixed(1) + "%") +
              " national penetration. Nearly every eligible acre reads as unclaimed because " +
              "the endorsement has only just been offered, not because anyone is overlooking " +
              "it. Compare it against SCO or ECO before treating the dollars as a backlog.";
      }
    }
    note.style.display = msg ? "block" : "none";
    note.textContent = msg;
    drawLegend();
    renderRank();
  }

  // ---------------- wiring
  mSel.addEventListener("change", function () {
    if (metric === mSel.value) return;
    metric = mSel.value;
    syncControls();
    applyMetric();
  });
  fCrop.addEventListener("change", function () { statCache = {}; applyMetric(); renderDetail(); });
  fEvidence.addEventListener("change", function () {
    minEvidence = parseInt(fEvidence.value, 10) || 0;
    applyMetric(); renderDetail();
  });
  fAip.addEventListener("change", function () { applyMetric(); renderDetail(); });
  [rMin, rMax].forEach(function (r) {
    r.addEventListener("input", function () { updateRange(); refresh(); });
  });
  document.getElementById("rReset").addEventListener("click", function () {
    rMin.value = 0; rMax.value = UNITS; updateRange(); refresh();
  });

  syncControls();
  applyMetric();     // builds the colour scale everything else reads
  applyLevel();
  syncZoomUI();
})();
</script>
</body>
</html>
"""
