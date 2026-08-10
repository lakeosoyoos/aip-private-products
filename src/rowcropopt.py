"""Row-crop OPPORTUNITY precompute — UNCLAIMED SUBSIDY per county x crop x band.

WHAT THIS ANSWERS
    "Which counties are most lucrative to work?" — for an agency deciding where to prospect,
    and for a producer deciding what they are leaving on the table.

THE METRIC

    unclaimed subsidy ($) = eligible acres x (1 - penetration) x subsidy captured per acre

Read left to right: how many acres could carry a supplemental band, how few of them do, and
how many federal dollars each of those acres would pull down. It is the rare number that is
simultaneously the best producer advice and the best agency prospect list:

  * A producer who buys only base MPCI and skips the supplemental bands leaves roughly
    $12-26 per acre of FEDERAL subsidy unclaimed. Those three figures are not assumptions —
    they are the RY2026 book, computed by this module from sob_sales:
    ECO-RP $23.26/ac, MCO-RP $26.25/ac, SCO-RP $12.10/ac of subsidy per band acre sold.
  * The bands return ~5.1x per producer dollar. That is 1/(1 - subsidy share) at FCIC's
    STATUTORY target loss ratio of 1.0 (7 U.S.C. 1506(n)(2)): the producer pays (1-s) of the
    premium and the expected indemnity is the whole premium. The RY2026 band subsidy share
    is ~0.804, so 1/(1-0.804) = 5.1. Recommending a band is therefore not a push, it is
    closing a gap.
  * Agent commission follows TOTAL premium (the subsidised portion included), so the premium
    on those same unsold acres IS the agency's opportunity, measured in its own currency.

WHY THE THREE RANKINGS ARE NOT THE SAME LIST
    Producer value per acre is subsidy per acre.  Agency value per acre is commission =
    premium per acre x a negotiated rate that varies BY REGION. Both are proportional to
    premium per acre, so they correlate — but the regional rate re-ranks them, and the
    producer's LEVERAGE (return per producer dollar) is nearly flat everywhere because the
    subsidy share is set in statute, not by geography. What varies county to county is how
    many dollars are at stake, not how good the deal is. src/rowcroppage.py shows all three
    and names where they diverge.

THE DENOMINATOR — WHAT "ELIGIBLE" MEANS HERE
    base_acres = net acres on an INDIVIDUAL, ADDITIONAL-COVERAGE plan:
        plan 01 YP, 02 RP, 03 RPHPE, 90 APH, with coverage_type 'A'.
    Deliberately excluded:
      * CAT (coverage_type 'C'). A CAT policy cannot carry SCO or ECO — the bands require
        additional coverage — so counting CAT acres would invent opportunity that RMA's own
        rules forbid. 1.37M acres in RY2026.
      * Area plans (04 AYP, 05 ARP, 06 ARP-HPE) and the standalone margin plans (16 MP,
        17 MP-HPO): a band does not layer on them either.
    That denominator validates: across 1,892 corn counties in RY2026 not one has ECO acres
    exceeding base acres. Five county x crop x band cells nationally do exceed it (max 3.76x,
    all tiny); penetration is CAPPED at 1.0 and each capped cell is counted and reported
    rather than silently clipped.

SUBSIDY PER ACRE — COMPUTED WHERE POSSIBLE, IMPUTED AND LABELLED WHERE NOT
    A county that already sells the band tells us directly what an acre of it captures:
    band subsidy / band acres, from that county's own rows. `value_basis` = 'county'.

    A county with no (or negligible) band sales has no such figure, and the whole point of
    the map is those counties — so it is IMPUTED, from the one thing that does travel:
    a band's subsidy per acre is very nearly proportional to revenue per acre.

        k(scope) = SUM(band subsidy) / SUM(band acres x base liability per acre)
        imputed subsidy per acre = k x this county's base liability per acre

    k is fitted per (crop, band) over the STATE first, the nation as fallback; `value_basis`
    records which. On RY2026 corn/ECO the county-level correlation between base liability per
    acre and observed ECO subsidy per acre is 0.85 and k's 10th-90th percentile spread is
    0.0397-0.0553 — a 1.4x band around a quantity that itself ranges more than 10x across
    counties, which is why the ratio travels and the raw dollar figure does not.

    Every imputed cell is flagged. Nothing in this module ever substitutes a national average
    dollar figure for a local one without saying so.

PENETRATION BELOW 100% IS NOT AUTOMATICALLY OPPORTUNITY
    Three reasons a rational, well-advised producer declines, none of which the raw metric can
    see, and all of which src/rowcroppage.py states on the page itself:
      1. ELIGIBILITY. Not every eligible-looking acre can actually carry the band. The famous
         case USED to be ARC: through CY2025 an FSA farm serial number with ARC elected on a
         crop was barred from SCO on that crop. OBBBA sec. 10303(b) REPEALED that bar for
         CY2026 (7 U.S.C. 1508(c)(4)(C)(iv) now excludes only STAX acres; RMA MGR-25-006 and
         25-OBBA; see docs/rowcrop_endorsement_stacking.md sec. (b), which verifies this
         against the statute, the bulletin and the 2027 handbook). So on the RY2026 book ARC
         and PLC are NEUTRAL to SCO — but the RY2025 rows in this table still carry the bar,
         and FSA's election is not in Summary of Business at any grain, so it cannot be netted
         out of the RY2025 denominator. The exclusion that survives into 2026 is STAX-
         designated acreage, and that one IS modelled (see EXCLUSIVE_PAIRS). Everything else
         that disqualifies a unit — uninsurable ground, a practice or type the ADM does not
         offer — is invisible here: this table counts acres, not eligibility.
      2. BASIS RISK. SCO/ECO/STAX trigger on a COUNTY index. A farm poorly correlated with
         its county gets a band that pays when it does not need it and does not pay when it
         does. That is a real reason to decline, it is quantified in basis_risk_county
         (src/basisrisk.py), and the JOIN section below is where the two meet.
      3. AVAILABILITY. A band is only offered where the actuarial documents offer it. This
         module does not read ADM, so it infers offer from OBSERVED SALES and records the
         inference in `evidence`: 2 = the band is sold for this crop in THIS county,
         1 = somewhere in this STATE, 0 = only elsewhere in the nation. A (crop, band) pair
         with no national sales at all in the year gets NO ROW — that is why there is no
         "MCO on wheat" opportunity in the RY2026 output. An evidence-0 cell is the weakest
         claim on the map and the page filters it out by default.

THE BASIS-RISK JOIN — WHY THE RAW METRIC ALONE IS THE WRONG RANKING
    Reason 2 above is not a footnote, it is a competing explanation for the whole map. Every
    band here settles on a COUNTY index, so a county can be unsold precisely because an
    area-triggered product does not work well there. Ranking such a county as a top prospect
    is wrong in the one direction that matters: it would have an agency sell a product that
    cannot respond to its client's loss.

    `basis_risk_county` (src/basisrisk.py, built by scripts/analysis/build_basis_risk.py) is
    the missing term. Its headline is

        miss_rate = P(the band pays NOTHING | the farm has a loss beyond its own deductible)

    so its complement is the thing the opportunity metric is silently assuming is 1:

        responsiveness R = 1 - miss_rate

    and the adjusted measure is the raw one weighted by it:

        basis-adjusted unclaimed subsidy = unclaimed subsidy x R

    R is a WEIGHT, not a forecast. The federal subsidy on an unsold acre is the same number
    whatever the county index does; what R says is how much of that money buys protection that
    shows up in the years the client actually needs it. Both measures are carried, never one
    instead of the other — see `join_basis_risk` and the CLI's --report.

    THE JOIN KEY, and the two places the grains do not line up:
      * BAND. rowcrop_unclaimed says SCO / ECO / MCO / STAX; basis_risk_county says SCO86 /
        ECO90 / ECO95, because a band's basis risk depends on its TRIGGER. SCO -> SCO86.
        ECO -> ECO95: [V] in RY2026 sob_sales, 100.1M of the 101.2M ECO acres in the book
        elect the 95% trigger and 1.06M elect 90%, so ECO95 is the book, not a coin flip.
        ECO90's row is carried alongside as the alternative election. MCO and STAX have NO
        row at any trigger: basisrisk.py does not model MCO's margin (input-cost) trigger and
        has no STAX estimator, so those cells are UNKNOWN, never zero and never borrowed.
      * COVERAGE LEVEL. basis_risk_county is published at coverage_level 0.85 — the FARM's own
        deductible, which sets what counts as "a farm loss". rowcrop_unclaimed pools every
        coverage level. 0.85 is the highest common election and produces the HIGHEST miss rate
        of any of them, so the adjustment is CONSERVATIVE for most of the book: [V] RY2026
        base acres elect 0.75 (76.5M), 0.80 (49.7M), 0.70 (29.0M) and 0.85 (23.4M), and [C]
        re-running basisrisk.basis_risk on the same county series at 0.75 roughly halves the
        ECO95 miss rate. It discounts opportunity by more than the modal buyer's own basis
        risk warrants, not less.

    HALF THE MAP HAS NO ANSWER, AND SAYS SO. Only 4,511 of the 9,271 (county, crop) keys in
    rowcrop_unclaimed have a basis_risk_county row: the estimator covers Corn, Soybeans and
    Wheat and refuses any county with fewer than 12 usable NASS years. The gap is carried as
    an explicit third state — `unknown` — and never inner-joined away or filled with a
    default. A county whose basis risk is unknown is NOT a county whose basis risk is low, and
    conflating those two is the same mistake as conflating low penetration with opportunity.

    The (all crops) rollup gets an ACRE-WEIGHTED miss rate over the crops beneath it that do
    have one, together with the share of its eligible acres those crops carry. Below
    MIN_BASIS_COVER of the acres the rollup reverts to `unknown`: a weighted mean over a
    minority of the acres is a statement about the minority, not about the county.

WHERE THE DATA COMES FROM, AND WHY THIS IS A PRECOMPUTE
    Everything above is county-grain, and the only county-grain source is `sob_sales`
    (3.23M rows, 1989-2026, 34 plan codes). That table is DROPPED from the shipped app DB by
    scripts/build_app_db.py — it is ~400 MB — so the map cannot read it at runtime. This
    module is the prf_opt_best pattern applied to row crops: run it against the WORKING
    catalog, land a compact per-county result table, and let the page read only that.

    The schema underneath is in flux. check_sob_schema() FAILS LOUDLY with the missing table
    or column named, rather than letting a silent OperationalError turn into a map of zeros.

    .venv/bin/python -m src.rowcropopt              # newest year in sob_sales
    .venv/bin/python -m src.rowcropopt --year 2026 --year 2025
    .venv/bin/python -m src.rowcropopt --report     # top counties by each measure
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------- vocabulary

# The eligible denominator: INDIVIDUAL plans at ADDITIONAL coverage. See the module docstring
# for why CAT, the area plans and the standalone margin plans are all excluded.
BASE_PLAN_CODES: tuple[str, ...] = ("01", "02", "03", "90")   # YP, RP, RPHPE, APH
BASE_COVERAGE_TYPE = "A"

# The supplemental bands, by plan-code family. Each family is the YP / RP / RPHPE variants of
# one endorsement; they are pooled because penetration is asked of the ENDORSEMENT ("do they
# have ECO?"), not of the variant, and the variant simply follows whatever base plan the
# producer already bought.
BAND_PLANS: dict[str, tuple[str, ...]] = {
    "SCO":  ("31", "32", "33"),     # Supplemental Coverage Option
    "ECO":  ("87", "88", "89"),     # Enhanced Coverage Option
    "MCO":  ("67", "68", "69"),     # Margin Coverage Option (new for RY2026)
    "STAX": ("35", "36"),           # Stacked Income Protection Plan (upland cotton only)
}
BAND_ORDER: tuple[str, ...] = ("SCO", "ECO", "MCO", "STAX")

# Bands that CANNOT sit on the same acre, so each one's eligible denominator excludes the
# other's acres. SCO and STAX are mutually exclusive by rule: acreage insured under STAX
# cannot also carry SCO. Without this, a cotton county that has fully converted to SCO reads
# as a large untouched STAX opportunity, and "all bands" double-counts the same acre twice.
# The data agrees: across the 157 RY2026 counties selling both, SCO + STAX acres never exceed
# eligible acres (the highest is 0.951 of them).
#
# ECO's and MCO's stacking rules against the others are NOT encoded, deliberately. ECO layers
# above SCO by design; MCO is in its first book year (RY2026) and this project has no primary
# source in hand for its interaction rules, so inventing one would be worse than saying so.
# 800 counties sell MCO alongside SCO and 802 alongside ECO, which is at least consistent with
# them not being exclusive.
EXCLUSIVE_PAIRS: tuple[tuple[str, str], ...] = (("SCO", "STAX"),)
BAND_LABELS: dict[str, str] = {
    "SCO": "SCO — Supplemental Coverage Option",
    "ECO": "ECO — Enhanced Coverage Option",
    "MCO": "MCO — Margin Coverage Option",
    "STAX": "STAX — Stacked Income Protection",
}

# The rollup row's crop label. Stored EXPLICITLY rather than summed on the client, because the
# per-crop rows only cover the top crops and a client-side sum of those would silently
# under-count. Its denominator is the base acres of every crop for which THAT BAND is offered
# — including wheat acres in an MCO rollup would invent opportunity for a product wheat
# cannot buy.
ALL_CROPS = "(all crops)"

# Band acres below this in a county make its own per-acre figures one small policy's worth of
# noise, so the imputed (state/national) ratio is used instead. The penetration numerator
# still counts every acre — this threshold governs the DOLLAR figure only.
MIN_OBS_ACRES = 100.0

# How many crops get their own rows. The rollup above always covers all of them.
DEFAULT_TOP_CROPS = 8

SOURCE = "sob_sales:rowcropopt"

# Columns this module reads. Named explicitly so a schema change is a clear error message
# rather than a map of zeros.
REQUIRED_SOB_COLUMNS: tuple[str, ...] = (
    "year", "state", "county_fips", "crop", "plan_code", "coverage_type",
    "net_acres", "liability", "total_premium", "subsidy", "producer_premium",
    "policies_sold",
)


class SobSchemaError(RuntimeError):
    """sob_sales is missing, or is missing a column this module needs.

    Raised instead of returning empty results: another agent is mid-load on this table, and a
    silent zero here would look exactly like "no opportunity anywhere", which is the one
    wrong answer this tool must never give.
    """


def check_sob_schema(conn: sqlite3.Connection) -> list[str]:
    """Verify sob_sales exists with every column needed; return its columns. Fails loudly."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if "sob_sales" not in tables:
        raise SobSchemaError(
            "sob_sales is not in this database. It is the ONLY county-grain Summary of "
            "Business table and scripts/build_app_db.py DROPS it from the shipped app DB, so "
            "this precompute must be run against the WORKING catalog (data/catalog.db) — "
            "never against data/catalog_app.db. Run `.venv/bin/python -m src.refresh "
            "--source rma_sob` if the working catalog has never loaded it."
        )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sob_sales)")]
    missing = [c for c in REQUIRED_SOB_COLUMNS if c not in cols]
    if missing:
        raise SobSchemaError(
            f"sob_sales is missing the column(s) {missing}. src/rowcropopt.py reads "
            f"{list(REQUIRED_SOB_COLUMNS)}; the table currently has {cols}. The SoB loader "
            "(src/connectors/rma_sob.py) owns this schema — re-run db.init_db() / "
            "db.migrate_sob_sales() against the working catalog before this precompute."
        )
    return cols


def available_years(conn: sqlite3.Connection) -> list[int]:
    """Crop years present in sob_sales, ascending. Empty when the table has no rows."""
    check_sob_schema(conn)
    return [int(r[0]) for r in conn.execute(
        "SELECT DISTINCT year FROM sob_sales WHERE year IS NOT NULL ORDER BY year")]


# ------------------------------------------------------------------ helpers

def fips5(value) -> str:
    """Normalize a county FIPS to the 5-digit string the us-atlas topology keys on."""
    s = str(value or "").strip()
    return s.zfill(5) if s else ""


def _num(value) -> float:
    """float(value) or 0.0 — SoB leaves blanks for 'no dollars', which sum as zero."""
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v          # NaN never becomes a dollar figure


def _div(num: float, den: float):
    """num/den, or None when the denominator is not a positive number.

    None, never 0: "we cannot compute a per-acre figure" and "the per-acre figure is zero"
    are different claims and only the second may be multiplied into a total.
    """
    if not den or den <= 0:
        return None
    return num / den


def _r(value, nd: int):
    """round(), preserving None. Payload size is round-off, not precision."""
    return None if value is None else round(value, nd)


# ------------------------------------------------------------- aggregation

def _blank() -> dict:
    return {"acres": 0.0, "liability": 0.0, "premium": 0.0, "subsidy": 0.0,
            "pprem": 0.0, "policies": 0}


def county_totals(conn: sqlite3.Connection, year: int) -> dict:
    """One pass over sob_sales for `year` -> {(fips, crop): {...}}. Pure read; testable.

    Each value is
        {"state": ss, "base": {acres, liability, premium, subsidy, pprem, policies},
         "bands": {band: {same}}}

    Only the base plans and the band plan families are read; every other plan code in the
    3.23M-row table (WFRP, MP, PACE, CLIP, HIP-WI, and the 1989-2010 legacy plans) is dropped
    here, because neither a band nor a band's denominator can be built out of it.
    """
    check_sob_schema(conn)
    plan_of_band = {code: band for band, codes in BAND_PLANS.items() for code in codes}
    wanted = set(BASE_PLAN_CODES) | set(plan_of_band)

    out: dict[tuple[str, str], dict] = {}
    rows = conn.execute(
        "SELECT state, county_fips, crop, plan_code, coverage_type, "
        "       SUM(net_acres), SUM(liability), SUM(total_premium), SUM(subsidy), "
        "       SUM(producer_premium), SUM(policies_sold) "
        "FROM sob_sales WHERE year = ? GROUP BY state, county_fips, crop, plan_code, "
        "coverage_type", (int(year),))
    for (state, fips_raw, crop, plan, cov_type, acres, liab, prem, sub, pprem, pol) in rows:
        plan = str(plan or "").strip().zfill(2)
        if plan not in wanted:
            continue
        fips = fips5(fips_raw)
        crop = str(crop or "").strip()
        if not fips or not crop:
            continue
        is_base = plan in BASE_PLAN_CODES
        # CAT acres are not band-eligible; see the module docstring. Band rows are all
        # additional coverage by construction, so the filter only bites on the denominator.
        if is_base and str(cov_type or "").strip().upper() != BASE_COVERAGE_TYPE:
            continue
        cell = out.setdefault((fips, crop), {
            "state": str(state or "").strip(), "base": _blank(), "bands": {}})
        bucket = cell["base"] if is_base else cell["bands"].setdefault(
            plan_of_band[plan], _blank())
        bucket["acres"] += _num(acres)
        bucket["liability"] += _num(liab)
        bucket["premium"] += _num(prem)
        bucket["subsidy"] += _num(sub)
        bucket["pprem"] += _num(pprem)
        try:
            bucket["policies"] += int(pol or 0)
        except (TypeError, ValueError):
            pass
    return out


def bands_offered(totals: dict) -> dict[str, set[str]]:
    """{crop: {bands with ANY observed acres nationally}} — the offer inference.

    A (crop, band) pair absent here gets no row at all. Without this rule the map would
    report a large, entirely fictional MCO opportunity on every wheat county in the country,
    because MCO simply is not offered on wheat and 0% penetration would read as 100% unsold.
    """
    out: dict[str, set[str]] = {}
    for (_fips, crop), cell in totals.items():
        for band, agg in cell["bands"].items():
            if agg["acres"] > 0:
                out.setdefault(crop, set()).add(band)
    return out


def rank_crops(totals: dict, offered: dict[str, set[str]], top_n: int) -> list[str]:
    """The crops that get their own rows: biggest base acreage first, bands-offered only."""
    acres: dict[str, float] = {}
    for (_fips, crop), cell in totals.items():
        if crop in offered:
            acres[crop] = acres.get(crop, 0.0) + cell["base"]["acres"]
    ordered = sorted(acres, key=lambda c: (-acres[c], c))
    return ordered if top_n is None or top_n <= 0 else ordered[:top_n]


def value_ratios(totals: dict, min_obs: float = MIN_OBS_ACRES) -> dict:
    """Fit k = SUM(band subsidy) / SUM(band acres x base liability per acre), by scope.

    Returns {"sub": {scope_key: k}, "prem": {...}, "ret": {...}} where scope_key is
    ("N", crop, band) nationally or ("S", state, crop, band) per state. `ret` is the plain
    total-premium-to-producer-premium ratio (= 1/(1 - subsidy share)), which needs no
    liability scaling because it is already dimensionless.

    Only counties that ACTUALLY SELL the band, and sell enough of it to measure, contribute to
    the fit. An unsold county has no per-acre figure to fit against — that is the entire reason
    the fit exists — and a county with one 5-acre policy has one that is noise. Both are
    excluded by the SAME `min_obs` threshold that decides whether a county trusts its own
    figures, because a number too unreliable to use locally is too unreliable to export.
    """
    acc: dict[tuple, dict] = {}
    for (_fips, crop), cell in totals.items():
        base = cell["base"]
        blpa = _div(base["liability"], base["acres"])
        state = cell["state"]
        for band, agg in cell["bands"].items():
            if agg["acres"] < min_obs or agg["acres"] <= 0:
                continue
            for key in (("N", crop, band), ("S", state, crop, band)):
                a = acc.setdefault(key, {"sub": 0.0, "prem": 0.0, "pprem": 0.0, "denom": 0.0})
                a["sub"] += agg["subsidy"]
                a["prem"] += agg["premium"]
                a["pprem"] += agg["pprem"]
                if blpa is not None:
                    a["denom"] += agg["acres"] * blpa

    sub: dict[tuple, float] = {}
    prem: dict[tuple, float] = {}
    ret: dict[tuple, float] = {}
    for key, a in acc.items():
        ks = _div(a["sub"], a["denom"])
        kp = _div(a["prem"], a["denom"])
        kr = _div(a["prem"], a["pprem"])
        if ks is not None:
            sub[key] = ks
        if kp is not None:
            prem[key] = kp
        if kr is not None:
            ret[key] = kr
    return {"sub": sub, "prem": prem, "ret": ret}


def band_states(totals: dict) -> set[tuple[str, str, str]]:
    """{(state, crop, band)} with observed acres — the `evidence == 1` test."""
    out: set[tuple[str, str, str]] = set()
    for (_fips, crop), cell in totals.items():
        for band, agg in cell["bands"].items():
            if agg["acres"] > 0:
                out.add((cell["state"], crop, band))
    return out


# ---------------------------------------------------------------- the metric

def eligible_base(base: dict, bands: dict, band: str) -> dict:
    """`base`, less the acres a mutually-exclusive band has already taken.

    Acres carrying STAX cannot also carry SCO and vice versa, so those acres are not part of
    the other band's eligible denominator — they are spoken for, not unsold. Liability is
    scaled by the SAME factor as acres so liability per acre (the imputation's input) is
    unchanged: what shrinks is how many acres are on offer, not what an acre is worth.

    Returns `base` itself when nothing is excluded, so the common path allocates nothing.
    """
    taken = 0.0
    for a, b in EXCLUSIVE_PAIRS:
        other = b if band == a else (a if band == b else None)
        if other:
            taken += (bands.get(other) or {}).get("acres", 0.0)
    if taken <= 0 or base["acres"] <= 0:
        return base
    acres = max(0.0, base["acres"] - taken)
    scale = acres / base["acres"]
    out = dict(base)
    out["acres"] = acres
    out["liability"] = base["liability"] * scale
    return out


def _cell_row(year: int, state: str, fips: str, crop: str, band: str,
              base: dict, agg: dict, ratios: dict, seen_states: set,
              min_obs: float = MIN_OBS_ACRES) -> dict | None:
    """The metric, for one (county, crop, band). Returns None when there is no denominator.

    unclaimed subsidy = base_acres x (1 - penetration) x subsidy per acre
    unclaimed premium = base_acres x (1 - penetration) x TOTAL premium per acre
                        (the agency's side: commission is a percent of total premium, so the
                         page multiplies this by the negotiated rate at display time)
    """
    base_acres = base["acres"]
    if base_acres <= 0:
        return None
    band_acres = agg["acres"]

    raw_pen = band_acres / base_acres
    penetration = min(1.0, raw_pen)
    capped = 1 if raw_pen > 1.0 + 1e-9 else 0
    unsold = base_acres * (1.0 - penetration)

    # --- per-acre dollar figures: this county's own, or the fitted ratio, always labelled.
    if band_acres >= min_obs:
        sub_pa = _div(agg["subsidy"], band_acres)
        prem_pa = _div(agg["premium"], band_acres)
        ret = _div(agg["premium"], agg["pprem"])
        # return_per_dollar is gross / producer premium, i.e. 1/(1 - subsidy share), so it is
        # BOUNDED BY THE FILED SUBSIDY SCHEDULE. The bands are filed at 80%, and a qualifying
        # beginning or veteran farmer adds 10 points, so ~90% is the highest share the rules
        # produce and ~10x the highest honest multiple. Measured, 5,680 county rows exceeded
        # 5.2x and one reached 20.4x — an implied 95% share that no filed schedule allows.
        # The source is not wrong: RMA's own SoB carries 508 SCO county rows above a 90%
        # share, all buy-up, no CAT. They are counties whose premium is small enough that
        # rounding dominates the split. Guarding on the SHARE rather than on the premium
        # SIZE is what works: a county can carry thousands of dollars of premium spread thinly
        # and still produce a 20x ratio, which is why an absolute-dollar floor did not bite.
        ret = _credible_ret(ret, sub_pa, prem_pa)
        basis = "county"
    else:
        sub_pa = prem_pa = ret = None
        basis = None

    if sub_pa is None or prem_pa is None:
        blpa = _div(base["liability"], base_acres)
        for scope, key in (("state", ("S", state, crop, band)), ("national", ("N", crop, band))):
            ks, kp = ratios["sub"].get(key), ratios["prem"].get(key)
            if blpa is None or ks is None or kp is None:
                continue
            sub_pa, prem_pa = ks * blpa, kp * blpa
            ret = ratios["ret"].get(key)
            basis = scope
            break

    if ret is None:
        ret = (ratios["ret"].get(("S", state, crop, band))
               or ratios["ret"].get(("N", crop, band)))

    evidence = 2 if band_acres > 0 else (1 if (state, crop, band) in seen_states else 0)

    unclaimed_sub = None if sub_pa is None else unsold * sub_pa
    unclaimed_prem = None if prem_pa is None else unsold * prem_pa
    pprem_pa = None if (sub_pa is None or prem_pa is None) else max(0.0, prem_pa - sub_pa)

    return {
        "year": int(year), "state": state, "county_fips": fips, "crop": crop, "band": band,
        "base_acres": _r(base_acres, 1),
        "base_liability": _r(base["liability"], 0),
        "base_policies": int(base["policies"]),
        "band_acres": _r(band_acres, 1),
        "penetration": _r(penetration, 5),
        "pen_capped": capped,
        "unsold_acres": _r(unsold, 1),
        "sub_per_acre": _r(sub_pa, 4),
        "prem_per_acre": _r(prem_pa, 4),
        "pprem_per_acre": _r(pprem_pa, 4),
        "return_per_dollar": _r(ret, 4),
        "value_basis": basis,
        "evidence": evidence,
        "unclaimed_subsidy": _r(unclaimed_sub, 0),
        "unclaimed_premium": _r(unclaimed_prem, 0),
    }


# Basis strength, strongest first. A rollup made of cells with different bases reports the
# honest compound answer rather than borrowing the strongest label in the mix.
_BASIS_RANK = {"county": 0, "mixed": 1, "state": 2, "national": 3, None: 4}


def _rollup(cells: list[dict], year: int, state: str, fips: str, band: str) -> dict | None:
    """Sum per-crop cells for one county x band into the (all crops) row.

    Built by SUMMING the per-crop rows rather than by re-running the metric on pooled
    aggregates, for one reason worth stating: the rollup's denominator is a DIFFERENT set of
    crops for every band (MCO is offered on far fewer crops than ECO), so there is no single
    pooled "base acres" to run the metric against. Summing makes the rollup exactly equal to
    the sum of its parts by construction — which is the property a total has to have.

    The per-acre figures come back out of the sums (unclaimed $ / unsold acres), so they are
    the acre-weighted blend of the crops underneath, not an average of averages.
    """
    if not cells:
        return None
    base_acres = sum(c["base_acres"] or 0 for c in cells)
    if base_acres <= 0:
        return None
    band_acres = sum(c["band_acres"] or 0 for c in cells)
    unsold = sum(c["unsold_acres"] or 0 for c in cells)
    have_sub = [c for c in cells if c["unclaimed_subsidy"] is not None]
    have_prem = [c for c in cells if c["unclaimed_premium"] is not None]
    unclaimed_sub = sum(c["unclaimed_subsidy"] for c in have_sub) if have_sub else None
    unclaimed_prem = sum(c["unclaimed_premium"] for c in have_prem) if have_prem else None

    # Only the crops that actually contribute unsold acres get a say in the basis label —
    # a fully-penetrated crop contributes no dollars and so cannot make the total "imputed".
    contributing = {c["value_basis"] for c in cells
                    if (c["unsold_acres"] or 0) > 0 and c["value_basis"]}
    if not contributing:
        basis = next((c["value_basis"] for c in cells if c["value_basis"]), None)
    elif len(contributing) == 1:
        basis = contributing.pop()
    elif "county" in contributing:
        basis = "mixed"
    else:
        basis = sorted(contributing, key=lambda b: _BASIS_RANK.get(b, 9))[-1]

    sub_pa = _div(unclaimed_sub or 0.0, unsold) if unclaimed_sub is not None else None
    prem_pa = _div(unclaimed_prem or 0.0, unsold) if unclaimed_prem is not None else None
    if unsold <= 0:                      # fully penetrated: fall back to the sold-acre blend
        sub_pa = _div(sum((c["sub_per_acre"] or 0) * (c["band_acres"] or 0) for c in cells),
                      band_acres)
        prem_pa = _div(sum((c["prem_per_acre"] or 0) * (c["band_acres"] or 0) for c in cells),
                       band_acres)
    pprem_pa = None if (sub_pa is None or prem_pa is None) else max(0.0, prem_pa - sub_pa)
    ret = None if (prem_pa is None or not pprem_pa) else prem_pa / pprem_pa
    ret = _credible_ret(ret, sub_pa, prem_pa)   # the rollup needs the same rule as a cell

    return {
        "year": int(year), "state": state, "county_fips": fips, "crop": ALL_CROPS,
        "band": band,
        "base_acres": _r(base_acres, 1),
        "base_liability": _r(sum(c["base_liability"] or 0 for c in cells), 0),
        "base_policies": sum(c["base_policies"] or 0 for c in cells),
        "band_acres": _r(band_acres, 1),
        "penetration": _r(min(1.0, band_acres / base_acres), 5),
        "pen_capped": 1 if any(c["pen_capped"] for c in cells) else 0,
        "unsold_acres": _r(unsold, 1),
        "sub_per_acre": _r(sub_pa, 4),
        "prem_per_acre": _r(prem_pa, 4),
        "pprem_per_acre": _r(pprem_pa, 4),
        "return_per_dollar": _r(ret, 4),
        "value_basis": basis,
        "evidence": max(c["evidence"] for c in cells),
        "unclaimed_subsidy": _r(unclaimed_sub, 0),
        "unclaimed_premium": _r(unclaimed_prem, 0),
    }


def compute_rows(totals: dict, year: int, top_crops: int = DEFAULT_TOP_CROPS,
                 min_obs: float = MIN_OBS_ACRES) -> list[dict]:
    """Every result row for one crop year: per-crop cells plus the (all crops) rollup.

    The rollup is accumulated over EVERY crop, not only the ones that get their own rows, so
    a county's total is complete even though its per-crop detail is capped at `top_crops`.
    """
    offered = bands_offered(totals)
    ratios = value_ratios(totals, min_obs)
    seen_states = band_states(totals)
    keep = set(rank_crops(totals, offered, top_crops))

    rows: list[dict] = []
    roll: dict[tuple[str, str], list[dict]] = {}
    roll_state: dict[str, str] = {}

    for (fips, crop), cell in totals.items():
        base, state = cell["base"], cell["state"]
        for band in BAND_ORDER:
            if band not in offered.get(crop, ()):        # not offered on this crop at all
                continue
            agg = cell["bands"].get(band) or _blank()
            r = _cell_row(year, state, fips, crop, band,
                          eligible_base(base, cell["bands"], band), agg, ratios,
                          seen_states, min_obs)
            if r is None:
                continue
            if crop in keep:
                rows.append(r)
            roll.setdefault((fips, band), []).append(r)
            roll_state.setdefault(fips, state)

    for (fips, band), cells in roll.items():
        r = _rollup(cells, year, roll_state.get(fips, ""), fips, band)
        if r is not None:
            rows.append(r)

    rows.sort(key=lambda r: (r["county_fips"], r["crop"], r["band"]))
    return rows


# ------------------------------------------------------------ the basis-risk join
#
# See the module docstring. This half of the file joins the OPPORTUNITY metric above to
# `basis_risk_county` and produces the adjusted measure ALONGSIDE the raw one. Nothing here
# writes to the database: both inputs already ship in the slim app DB (rowcrop_unclaimed
# 44,979 rows, basis_risk_county 14,805 rows), so the join is cheap enough to do at read time
# and a third precomputed table would only be a copy that can go stale against its two parents.

# The slice of basis_risk_county that is published. plan_type 'RP' because the bands are sold
# overwhelmingly as revenue variants and the RP estimate carries the price leg.
#
# COVERAGE LEVEL 0.75, not 0.85. This was 0.85 only because that is the single level the
# builder used to be run at, and it turned out to describe a product almost nobody buys:
# measured from Summary of Business, 2.3% of the acres that bought SCO carry an 0.85 election
# against 50.7% at 0.75 — roughly one buyer in forty-four.
#
# It is not a magnitude error either. SCO exits at the producer's OWN level, so at 0.85 the
# band is ONE point wide and at 0.65 it is twenty-one; those are different products, not the
# same product measured differently. Publishing 0.85 over-discounted unclaimed subsidy by
# $253M of $792M (+11.4%).
#
# The builder now produces all five published levels, so this is a free choice rather than
# the only row available. Do NOT move it to a level the build did not produce: load_basis_risk
# filters on it exactly, and every county would silently render "unknown".
# Highest subsidy share the filed schedules can produce: bands are filed at 80%, and P18-1's
# beginning/veteran-farmer provision adds 10 points. A county reporting more than this is a
# rounding artefact, not a richer subsidy, so it reports no return multiple — while still
# reporting its subsidy and unclaimed dollars, which do not depend on the ratio.
MAX_CREDIBLE_SUBSIDY_SHARE = 0.92


def _credible_ret(ret, sub_pa, prem_pa):
    """Suppress a return multiple whose implied subsidy share no filed schedule can produce.

    return_per_dollar is gross / producer premium == 1 / (1 - subsidy share), so it is bounded
    by the schedule: bands are filed at 80%, and P18-1's beginning/veteran-farmer provision
    adds 10 points, making ~90% the ceiling and ~10x the highest honest multiple. Measured,
    5,680 rows exceeded 5.2x and one reached 20.4x on an implied 95% share.

    The source is not wrong -- RMA's own SoB carries 508 SCO county rows above a 90% share,
    all buy-up, no CAT. They are counties whose premium is small enough that rounding
    dominates the split. The row keeps its subsidy and unclaimed dollars, which do not depend
    on this ratio; it just declines to quote a multiple.

    ONE helper rather than a check per branch: the first attempt guarded only the per-crop
    path and the "(all crops)" rollup sailed straight past it, still reporting 17.8x.
    """
    if ret is None or not prem_pa:
        return ret
    share = (sub_pa or 0.0) / prem_pa
    return None if share > MAX_CREDIBLE_SUBSIDY_SHARE else ret

BASIS_PLAN_TYPE = "RP"
BASIS_COVERAGE_LEVEL = 0.75

# band (this module's vocabulary) -> basis_risk_county band variants, PREFERRED FIRST.
# ECO95 leads ECO90 because 99.0% of RY2026 ECO acres elect the 95% trigger (see the docstring).
# MCO maps to nothing at all: that is the honest answer, not an oversight to be patched.
# STAX now HAS an estimator (a plain county revenue trigger, RMA 16-STAX-0021). Its rows only
# appear once cotton is loaded into nass_county_yield and build_basis_risk.py is re-run; until
# then a STAX county simply has no row and falls through to "unknown", which is correct.
BASIS_BANDS: dict[str, tuple[str, ...]] = {
    "SCO": ("SCO86",),
    "ECO": ("ECO95", "ECO90"),
    "MCO": (),
    "STAX": ("STAX90",),
}

# Why a band has no basis-risk estimate — shown on the page so "unknown" is never mistaken for
# "low". Keyed by band; crops and short series are handled by BASIS_CROP_NOTE / grade.
BASIS_BAND_NOTE: dict[str, str] = {
    "MCO": "MCO settles on a MARGIN (revenue less input costs) index. src/basisrisk.py models "
           "yield and revenue triggers only, so MCO's basis risk is not estimated anywhere in "
           "this project — not estimated to be low.",
    # NOT "no estimator" any more — that was true until cotton was loaded. The live caveat is
    # different and easy to trip over: STAX90 and ECO90 share a 0.90 county trigger, and a
    # miss rate depends ONLY on the trigger, so the two are identical by arithmetic. They
    # differ in uncovered_share, because STAX's exit slides up to the producer's own coverage
    # level (16-STAX-0021 s10(b)) rather than sitting at a fixed floor.
    "STAX": "STAX90 and ECO90 share a 0.90 county trigger, so their miss rates are identical "
            "by construction — do not read one as better than the other on that number. They "
            "differ in how much of the band is left uncovered, because STAX's exit rises with "
            "the producer's own coverage level.",
}
BASIS_CROP_NOTE = (
    "basis_risk_county covers Corn, Soybeans and Wheat — the crops with a long enough NASS "
    "county yield series to detrend. Every other crop on this map is unknown, not low.")

# Coverage states. Three, deliberately: the two-state version is the bug this join exists to
# avoid, because it forces every unmeasured county into whichever bucket is convenient.
BASIS_COVERED = "covered"     # a basis_risk_county row matched this exact county x crop x band
BASIS_PARTIAL = "partial"     # a rollup: some of its crops matched, and they carry most of the acres
BASIS_UNKNOWN = "unknown"     # nothing matched. NOT low risk. NOT zero. Not ranked.
BASIS_STATES: tuple[str, ...] = (BASIS_COVERED, BASIS_PARTIAL, BASIS_UNKNOWN)

# Share of a rollup's eligible acres that must carry a basis-risk estimate before the rollup
# publishes one. Below this the acre-weighted mean describes the minority of the county's acres
# and is reported as UNKNOWN instead. Half is the natural line: at or above it the estimate
# speaks for most of the ground, below it it does not. [C] 377 of the 3,798 RY2026 (all crops)
# cells that have any coverage at all fall below it; 191 fall below 0.25.
MIN_BASIS_COVER = 0.50

# Grades, worst last — a rollup inherits the WORST grade among its contributing crops, because
# a mean is only as trustworthy as its shakiest term. A/B/C is series length: A >= 30 usable
# years, B 20-29, C 12-19; below 12 basisrisk.py writes no row at all.
BASIS_GRADES: tuple[str, ...] = ("A", "B", "C")

# The columns carried through the join. miss_rate is the adjustment; everything else is there
# so the reader can see how soft it is before acting on it — the rho sensitivity (rho is the
# ONE parameter src/basisrisk.py imports from outside the data), the bootstrap interval over
# the length of the county series, the dollar-weighted view, the deep-loss view, and the
# windfall rate that is the same product's other tail.
BASIS_TERMS: tuple[str, ...] = (
    "miss_rate", "miss_rate_rho_lo", "miss_rate_rho_hi", "miss_rate_ci_lo", "miss_rate_ci_hi",
    "deep_miss_rate", "uncovered_share", "windfall_rate",
)


def load_basis_risk(conn: sqlite3.Connection, plan_type: str = BASIS_PLAN_TYPE,
                    coverage_level: float = BASIS_COVERAGE_LEVEL) -> dict:
    """{(county_fips, crop, variant): {term: value, 'grade': str}} from basis_risk_county.

    Returns {} — not an exception — when the table is absent or empty. A missing basis-risk
    table must degrade the map to "basis risk unknown everywhere", which is a true statement,
    rather than taking the tab down. src/rowcroppage.py renders that state explicitly.
    """
    cols = ", ".join(BASIS_TERMS)
    try:
        rows = conn.execute(
            f"SELECT county_fips, crop, band, grade, n_years, {cols} FROM basis_risk_county "
            "WHERE plan_type = ? AND coverage_level = ?",
            (str(plan_type), float(coverage_level))).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        fips = fips5(r[0])
        crop = str(r[1] or "").strip()
        variant = str(r[2] or "").strip()
        if not (fips and crop and variant):
            continue
        cell = {"grade": str(r[3] or "") or None, "n_years": r[4]}
        for i, term in enumerate(BASIS_TERMS):
            v = r[5 + i]
            cell[term] = None if v is None else float(v)
        out[(fips, crop, variant)] = cell
    return out


def basis_variants(band: str) -> tuple[str, ...]:
    """The basis_risk_county band variants describing `band`, preferred election first."""
    return BASIS_BANDS.get(str(band or "").strip(), ())


def responsiveness(miss_rate) -> float | None:
    """1 - miss_rate, clamped to [0, 1]. None in, None out — never a silent 1.0.

    This is P(the band pays | the farm has a loss beyond its deductible): the share of the
    farm's loss YEARS in which an area-triggered product actually shows up. It is the weight
    the raw opportunity metric implicitly sets to 1 everywhere.
    """
    if miss_rate is None:
        return None
    try:
        m = float(miss_rate)
    except (TypeError, ValueError):
        return None
    if m != m:
        return None
    return max(0.0, min(1.0, 1.0 - m))


def adjust(value, miss_rate):
    """`value` weighted by responsiveness. None if either side is missing — never 0, never `value`.

    "We cannot say what this county's basis risk is" and "this county's basis risk is nil" are
    different claims, and only the second may be multiplied into a ranking.
    """
    r = responsiveness(miss_rate)
    if value is None or r is None:
        return None
    try:
        return float(value) * r
    except (TypeError, ValueError):
        return None


def _basis_hit(index: dict, fips: str, crop: str, band: str):
    """The preferred basis_risk_county row for one county x crop x band, or (None, None)."""
    for variant in basis_variants(band):
        cell = index.get((fips5(fips), str(crop or "").strip(), variant))
        if cell is not None and cell.get("miss_rate") is not None:
            return cell, variant
    return None, None


def _worst_grade(grades) -> str | None:
    seen = [g for g in grades if g in BASIS_GRADES]
    return max(seen, key=BASIS_GRADES.index) if seen else None


def basis_for_cell(index: dict, fips: str, crop: str, band: str) -> dict | None:
    """Basis risk for ONE per-crop cell. None means unknown — the caller must not invent one."""
    cell, variant = _basis_hit(index, fips, crop, band)
    if cell is None:
        return None
    out = {t: cell.get(t) for t in BASIS_TERMS}
    out.update(variant=variant, grade=cell.get("grade"), n_years=cell.get("n_years"),
               cover=BASIS_COVERED, cover_share=1.0, crops=[str(crop).strip()])
    return out


def basis_for_rollup(index: dict, fips: str, band: str, crop_acres, rollup_acres,
                     min_cover: float = MIN_BASIS_COVER) -> dict | None:
    """Acre-weighted basis risk for an (all crops) rollup, or None when too little is covered.

    `crop_acres` is {crop: eligible acres} for the PER-CROP rows of the same county and band —
    which is all rowcrop_unclaimed holds, since per-crop rows stop at the biggest crops. Using
    only those understates coverage where a small crop is missing, and understating coverage is
    the safe direction: it moves a cell towards `unknown`, never away from it.

    Every term is weighted by the same acres, so the rollup's rho band and its bootstrap
    interval stay consistent with its miss rate instead of being borrowed from one crop.
    """
    num: dict[str, float] = {t: 0.0 for t in BASIS_TERMS}
    have: dict[str, float] = {t: 0.0 for t in BASIS_TERMS}
    den = 0.0
    grades: list[str] = []
    crops: list[str] = []
    variants: list[str] = []
    for crop, acres in (crop_acres or {}).items():
        a = _num(acres)
        if a <= 0:
            continue
        cell, variant = _basis_hit(index, fips, crop, band)
        if cell is None:
            continue
        den += a
        crops.append(str(crop))
        if variant:
            variants.append(variant)
        if cell.get("grade"):
            grades.append(cell["grade"])
        for t in BASIS_TERMS:
            v = cell.get(t)
            if v is not None:
                num[t] += float(v) * a
                have[t] += a
    if den <= 0:
        return None
    total = _num(rollup_acres) or den
    share = min(1.0, den / total) if total > 0 else 0.0
    if share < min_cover:
        return None                     # a minority of the acres cannot speak for the county
    out = {t: (num[t] / have[t] if have[t] > 0 else None) for t in BASIS_TERMS}
    if out["miss_rate"] is None:
        return None
    out.update(variant=(sorted(set(variants))[0] if variants else None),
               grade=_worst_grade(grades), n_years=None,
               cover=BASIS_COVERED if share >= 0.999 else BASIS_PARTIAL,
               cover_share=round(share, 4), crops=sorted(crops))
    return out


def join_basis_risk(rows, index: dict, min_cover: float = MIN_BASIS_COVER) -> dict:
    """{(county_fips, crop, band): basis dict} for every rowcrop_unclaimed row that HAS one.

    `rows` are rowcrop_unclaimed rows for ONE crop year — sqlite3.Row, dicts, or anything with
    ['county_fips'], ['crop'], ['band'] and ['base_acres']. Cells ABSENT from the result are
    `unknown`; absence is the wire format for it, so nothing downstream can read a missing
    entry as a zero.

    Pure: takes the already-loaded index, touches no database, and is the single place the
    band mapping, the rollup weighting and the coverage floor are decided.
    """
    per_crop: dict[tuple[str, str], dict[str, float]] = {}
    rollups: list[tuple[str, str, float]] = []
    out: dict[tuple[str, str, str], dict] = {}

    for r in rows:
        fips = fips5(r["county_fips"])
        crop = str(r["crop"] or "").strip()
        band = str(r["band"] or "").strip()
        acres = _num(r["base_acres"])
        if not (fips and crop and band):
            continue
        if crop == ALL_CROPS:
            rollups.append((fips, band, acres))
            continue
        slot = per_crop.setdefault((fips, band), {})
        slot[crop] = slot.get(crop, 0.0) + acres
        hit = basis_for_cell(index, fips, crop, band)
        if hit is not None:
            out[(fips, crop, band)] = hit

    for fips, band, acres in rollups:
        hit = basis_for_rollup(index, fips, band, per_crop.get((fips, band), {}), acres,
                               min_cover=min_cover)
        if hit is not None:
            out[(fips, ALL_CROPS, band)] = hit
    return out


def basis_note_for(band: str, crop: str = "") -> str:
    """Why this band x crop has no basis-risk estimate. Shown wherever `unknown` is."""
    note = BASIS_BAND_NOTE.get(str(band or "").strip())
    if note:
        return note
    return BASIS_CROP_NOTE


def basis_coverage(rows, joined: dict) -> dict:
    """Counts by coverage state, overall and per band — the honest header for any ranking."""
    per_band: dict[str, dict[str, int]] = {}
    totals = {s: 0 for s in BASIS_STATES}
    for r in rows:
        band = str(r["band"] or "").strip()
        key = (fips5(r["county_fips"]), str(r["crop"] or "").strip(), band)
        state = (joined.get(key) or {}).get("cover", BASIS_UNKNOWN)
        totals[state] += 1
        per_band.setdefault(band, {s: 0 for s in BASIS_STATES})[state] += 1
    return {"total": totals, "by_band": per_band}


# ------------------------------------------------------------------- storage

_INSERT_COLS = ("year", "state", "county_fips", "crop", "band", "base_acres",
                "base_liability", "base_policies", "band_acres", "penetration",
                "pen_capped", "unsold_acres", "sub_per_acre", "prem_per_acre",
                "pprem_per_acre", "return_per_dollar", "value_basis", "evidence",
                "unclaimed_subsidy", "unclaimed_premium", "source", "fetched_at")


def write_rows(conn: sqlite3.Connection, rows: list[dict], year: int) -> int:
    """Replace this year's rowcrop_unclaimed rows. Returns how many were written."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute("DELETE FROM rowcrop_unclaimed WHERE year = ?", (int(year),))
    conn.executemany(
        f"INSERT OR REPLACE INTO rowcrop_unclaimed ({', '.join(_INSERT_COLS)}) "
        f"VALUES ({', '.join('?' * len(_INSERT_COLS))})",
        [tuple(r.get(c) for c in _INSERT_COLS[:-2]) + (SOURCE, now) for r in rows])
    conn.commit()
    return len(rows)


def build(conn: sqlite3.Connection, years=None, top_crops: int = DEFAULT_TOP_CROPS,
          min_obs: float = MIN_OBS_ACRES) -> dict:
    """Compute and store every requested crop year. Returns a summary dict."""
    check_sob_schema(conn)
    have = available_years(conn)
    if not have:
        raise SobSchemaError(
            "sob_sales has no rows. The county-grain Summary of Business load has not run "
            "against this database (or is still in progress) — nothing can be computed.")
    if years:
        want = [int(y) for y in years]
        unknown = [y for y in want if y not in have]
        if unknown:
            raise SobSchemaError(
                f"sob_sales has no rows for crop year(s) {unknown}; it carries {have[0]}-"
                f"{have[-1]}.")
    else:
        want = [have[-1]]

    per_year = {}
    for y in want:
        totals = county_totals(conn, y)
        rows = compute_rows(totals, y, top_crops=top_crops, min_obs=min_obs)
        write_rows(conn, rows, y)
        per_year[y] = summarize(rows)
    return {"years": want, "per_year": per_year}


def summarize(rows: list[dict]) -> dict:
    """Counts a human should look at before trusting the table."""
    basis: dict[str, int] = {}
    evidence: dict[int, int] = {}
    for r in rows:
        basis[str(r["value_basis"])] = basis.get(str(r["value_basis"]), 0) + 1
        evidence[r["evidence"]] = evidence.get(r["evidence"], 0) + 1
    unclaimed = sum(r["unclaimed_subsidy"] or 0 for r in rows if r["crop"] == ALL_CROPS)
    return {
        "rows": len(rows),
        "counties": len({r["county_fips"] for r in rows}),
        "crops": len({r["crop"] for r in rows}) - (1 if any(
            r["crop"] == ALL_CROPS for r in rows) else 0),
        "bands": sorted({r["band"] for r in rows}),
        "capped": sum(r["pen_capped"] for r in rows),
        "basis": basis,
        "evidence": evidence,
        "unclaimed_subsidy_all_crops": unclaimed,
    }


# ----------------------------------------------------------------------- CLI

def _report(conn: sqlite3.Connection, year: int, band: str = "ECO", limit: int = 15) -> str:
    """Top counties by each measure — the sanity check, and the answer to 'where do I work'."""
    out: list[str] = []

    def block(title: str, sql: str, params, fmt) -> None:
        out.append(f"\n{title}")
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            out.append("  (no rows)")
        for r in rows:
            out.append("  " + fmt(r))

    base = ("FROM rowcrop_unclaimed WHERE year = ? AND crop = ? AND band = ? "
            "AND evidence >= 1 ")
    p = (year, ALL_CROPS, band)
    block(f"Top {limit} counties — UNCLAIMED SUBSIDY, total $ ({band}, all crops, {year})",
          "SELECT county_fips, state, unclaimed_subsidy, unsold_acres, penetration, "
          "value_basis " + base + "ORDER BY unclaimed_subsidy DESC LIMIT ?", p + (limit,),
          lambda r: f"{r[0]} {r[1]:2}  ${r[2]:>12,.0f}  {r[3]:>10,.0f} unsold ac  "
                        f"pen {100*(r[4] or 0):5.1f}%  [{r[5]}]")
    block(f"Top {limit} counties — UNCLAIMED SUBSIDY per ELIGIBLE acre ($/ac)",
          "SELECT county_fips, state, unclaimed_subsidy/base_acres, base_acres, penetration, "
          "value_basis " + base + "AND base_acres >= 5000 AND unclaimed_subsidy IS NOT NULL "
          "ORDER BY 3 DESC LIMIT ?", p + (limit,),
          lambda r: f"{r[0]} {r[1]:2}  ${r[2]:>7.2f}/ac  {r[3]:>10,.0f} base ac  "
                        f"pen {100*(r[4] or 0):5.1f}%  [{r[5]}]")
    block(f"Lowest {limit} penetration (base acres >= 25,000)",
          "SELECT county_fips, state, penetration, base_acres, unclaimed_subsidy " + base +
          "AND base_acres >= 25000 ORDER BY penetration ASC LIMIT ?", p + (limit,),
          lambda r: f"{r[0]} {r[1]:2}  pen {100*(r[2] or 0):5.1f}%  "
                        f"{r[3]:>10,.0f} base ac  ${r[4] or 0:>12,.0f} unclaimed")
    block(f"Top {limit} counties — PRODUCER value per acre (subsidy captured $/ac)",
          "SELECT county_fips, state, sub_per_acre, return_per_dollar, value_basis " + base +
          "AND sub_per_acre IS NOT NULL ORDER BY sub_per_acre DESC LIMIT ?", p + (limit,),
          lambda r: f"{r[0]} {r[1]:2}  ${r[2]:>7.2f}/ac captured  "
                        f"{r[3] or 0:>5.2f}x per producer $  [{r[4]}]")
    block(f"Top {limit} counties — AGENCY value per acre (TOTAL band premium $/ac)",
          "SELECT county_fips, state, prem_per_acre, unclaimed_premium, value_basis " + base +
          "AND prem_per_acre IS NOT NULL ORDER BY prem_per_acre DESC LIMIT ?", p + (limit,),
          lambda r: f"{r[0]} {r[1]:2}  ${r[2]:>7.2f}/ac premium  "
                        f"${r[3] or 0:>12,.0f} unsold premium  [{r[4]}]")
    out.append("\nCommission = unsold premium x YOUR negotiated rate (data/seed/"
               "aip_commission.csv). The rates shipped there are SAMPLE data.")
    out.append(_basis_report(conn, year, band=band, limit=limit))
    return "\n".join(out)


def _basis_report(conn: sqlite3.Connection, year: int, band: str = "ECO",
                  limit: int = 15) -> str:
    """RAW vs BASIS-ADJUSTED, side by side, plus where the two rankings disagree.

    Deliberately printed as one table with BOTH columns rather than as two lists. Two lists
    invite the reader to pick the flattering one; one table makes the disagreement the subject.
    """
    out: list[str] = []
    try:
        rows = conn.execute(
            "SELECT county_fips, state, crop, band, base_acres, unclaimed_subsidy, evidence "
            "FROM rowcrop_unclaimed WHERE year = ?", (int(year),)).fetchall()
    except sqlite3.OperationalError:
        return "\n(no rowcrop_unclaimed table)"
    rows = [{"county_fips": r[0], "state": r[1], "crop": r[2], "band": r[3],
             "base_acres": r[4], "unclaimed_subsidy": r[5], "evidence": r[6]} for r in rows]
    index = load_basis_risk(conn)
    if not index:
        return ("\nBASIS RISK: basis_risk_county is empty or absent in this database, so every "
                "county is 'basis risk unknown'. Run scripts/analysis/build_basis_risk.py "
                "against the working catalog. Unknown is NOT low.")
    joined = join_basis_risk(rows, index)
    cov = basis_coverage(rows, joined)
    out.append(f"\nBASIS RISK COVERAGE ({year}, all bands, all crops): "
               f"{cov['total'][BASIS_COVERED]:,} covered · {cov['total'][BASIS_PARTIAL]:,} "
               f"partial · {cov['total'][BASIS_UNKNOWN]:,} UNKNOWN cells")
    for b in BAND_ORDER:
        c = cov["by_band"].get(b)
        if c:
            out.append(f"    {b:5} {c[BASIS_COVERED]:>6,} covered  {c[BASIS_PARTIAL]:>6,} "
                       f"partial  {c[BASIS_UNKNOWN]:>6,} unknown"
                       + ("   <- no estimator" if not basis_variants(b) else ""))

    sel = [r for r in rows if r["crop"] == ALL_CROPS and r["band"] == band
           and (r["evidence"] or 0) >= 1 and r["unclaimed_subsidy"] is not None
           and (r["base_acres"] or 0) > 0]
    known = []
    for r in sel:
        br = joined.get((fips5(r["county_fips"]), ALL_CROPS, band))
        if br is None:
            continue
        adj = adjust(r["unclaimed_subsidy"], br["miss_rate"])
        if adj is None:
            continue
        known.append({**r, "miss": br["miss_rate"], "adj": adj, "cover": br["cover"],
                      "share": br["cover_share"],
                      "raw_pa": r["unclaimed_subsidy"] / r["base_acres"],
                      "adj_pa": adj / r["base_acres"]})
    if not known:
        out.append(f"\n(no {band} county has a basis-risk estimate in this database)")
        return "\n".join(out)

    n = len(known)
    raw_tot = sum(k["unclaimed_subsidy"] for k in known)
    adj_tot = sum(k["adj"] for k in known)
    out.append(f"\n{band}, (all crops), {n:,} counties WITH a basis-risk estimate: raw "
               f"${raw_tot/1e9:,.3f}B unclaimed -> ${adj_tot/1e9:,.3f}B basis-adjusted "
               f"({100*adj_tot/raw_tot:.0f}% — the rest is subsidy on coverage that would not "
               f"have paid in the years the farm lost money)")

    def show(title, rows_, fmt):
        out.append(f"\n{title}")
        for k in rows_:
            out.append("  " + fmt(k))

    def money(k) -> str:
        tag = k["cover"]
        if tag != BASIS_COVERED:
            tag += " %.0f%%" % (100 * (k["share"] or 0))
        return (f"{k['county_fips']} {k['state']:2}  raw ${k['unclaimed_subsidy']:>11,.0f}"
                f"  adj ${k['adj']:>11,.0f}  miss {100*k['miss']:5.1f}%  [{tag}]")

    show(f"Top {limit} — RAW unclaimed subsidy (basis-known counties only)",
         sorted(known, key=lambda k: -k["unclaimed_subsidy"])[:limit], money)
    show(f"Top {limit} — BASIS-ADJUSTED unclaimed subsidy",
         sorted(known, key=lambda k: -k["adj"])[:limit], money)

    # The divergence. Percentiles on the PER-ELIGIBLE-ACRE measure, because county size swamps
    # everything in the totals: [C] Spearman between raw and adjusted totals is 0.9995, while
    # on the per-acre measure it is 0.9965 for ECO and 0.9872 for SCO. The disagreement is
    # real, it is a tail, and it is invisible in the totals.
    raw_rank = {k["county_fips"]: i for i, k in enumerate(sorted(known, key=lambda k: k["raw_pa"]))}
    adj_rank = {k["county_fips"]: i for i, k in enumerate(sorted(known, key=lambda k: k["adj_pa"]))}
    for k in known:
        k["gap"] = 100 * (raw_rank[k["county_fips"]] - adj_rank[k["county_fips"]]) / max(1, n - 1)
    div = sorted(known, key=lambda k: -k["gap"])
    pen = (lambda k: f"{k['county_fips']} {k['state']:2}  raw ${k['raw_pa']:>6.2f}/ac "
                     f"(p{100*raw_rank[k['county_fips']]/max(1, n-1):>4.0f})  adj "
                     f"${k['adj_pa']:>6.2f}/ac (p{100*adj_rank[k['county_fips']]/max(1, n-1):>4.0f})"
                     f"  {k['gap']:+5.1f} pts  miss {100*k['miss']:5.1f}%")
    show(f"Top {limit} — RAW MOST OVERSTATES the county (adjusting demotes it)",
         div[:limit], pen)
    show(f"Top {limit} — RAW MOST UNDERSTATES the county (adjusting promotes it)",
         div[-limit:][::-1], pen)
    out.append("\nBoth columns are shown on purpose. The raw one is the federal money on the "
               "table; the adjusted one weights it by P(the band pays | the farm has a loss), "
               "which is the raw metric's silent assumption of 1. Counties with NO estimate are "
               "excluded from these lists entirely and are not low-risk counties.")
    return "\n".join(out)


def main(argv=None) -> int:
    from . import config, db as dbmod

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None, help="working catalog (default: data/catalog.db)")
    ap.add_argument("--year", action="append", type=int,
                    help="crop year (repeatable); default = newest in sob_sales")
    ap.add_argument("--top-crops", type=int, default=DEFAULT_TOP_CROPS,
                    help=f"crops given their own rows (default {DEFAULT_TOP_CROPS}); "
                         "the (all crops) rollup always covers every crop")
    ap.add_argument("--min-obs-acres", type=float, default=MIN_OBS_ACRES,
                    help="band acres below which a county's own $/acre is treated as noise")
    ap.add_argument("--report", action="store_true", help="print top counties after building")
    ap.add_argument("--report-only", action="store_true",
                    help="print the report against an ALREADY-BUILT rowcrop_unclaimed and skip "
                         "the precompute. The only way to run it against the shipped app DB, "
                         "which has no sob_sales — and the reproducer for "
                         "docs/rowcrop_opportunity.md")
    ap.add_argument("--band", default="ECO", choices=list(BAND_ORDER), help="band to report on")
    args = ap.parse_args(argv)

    path = Path(args.db or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if args.report_only:
            years = [int(r[0]) for r in conn.execute(
                "SELECT DISTINCT year FROM rowcrop_unclaimed ORDER BY year")]
            if not years:
                print("rowcrop_unclaimed is empty in this database — nothing to report. Run "
                      "`.venv/bin/python -m src.rowcropopt` against the WORKING catalog first.")
                return 2
            print(_report(conn, (args.year or years)[-1], band=args.band))
            return 0
        dbmod.init_db(conn)
        try:
            res = build(conn, years=args.year, top_crops=args.top_crops,
                        min_obs=args.min_obs_acres)
        except SobSchemaError as exc:
            print(f"REFUSING TO BUILD: {exc}")
            return 2
        for y, s in res["per_year"].items():
            print(f"{y}: {s['rows']:,} rows · {s['counties']:,} counties · {s['crops']} crops "
                  f"+ rollup · bands {','.join(s['bands'])}")
            print(f"      value basis {s['basis']} · evidence {s['evidence']} · "
                  f"{s['capped']} penetration cells capped at 100%")
            print(f"      total unclaimed subsidy (all crops, all bands): "
                  f"${s['unclaimed_subsidy_all_crops']:,.0f}")
        if args.report:
            print(_report(conn, res["years"][-1], band=args.band))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
