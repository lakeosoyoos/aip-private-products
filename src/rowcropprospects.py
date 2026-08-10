"""rowcropprospects.py -- one ranked list answering "where should we sell this?".

WHY A TABLE AND NOT ANOTHER MAP
-------------------------------
The row-crop side already has two maps. Neither answers the prospecting question, because the
question is a JOIN and a map is a single layer:

    rowcrop_unclaimed   how much federal subsidy is going unclaimed in a county x crop x band
    basis_risk_county   whether that band would actually pay this county's producers

Ranked on unclaimed dollars alone the list is misleading. The largest cell in the country is
ND 38017 corn at $4.26M -- and at the pessimistic correlation that band pays nothing in 34.9%
of the years a farm there has a loss. That is not opportunity; it is a product that will
disappoint the client and come back as a cancellation. Sorted the same way but filtered to
cells that survive the pessimistic case, the top of the list becomes WA Whitman wheat (5.4%
miss, $4.20M) and a run of Nebraska corn counties whose county index tracks their farms almost
perfectly (0.3-4.3% miss).

Same data, opposite advice. That join is the product.

THE TWO VOCABULARIES
--------------------
rowcrop_unclaimed says ECO; basis_risk_county says ECO90 and ECO95, because RMA prices two ECO
trigger levels and the Summary of Business does not distinguish them. BASIS_BANDS is the
bridge and it is not optional -- joining the raw strings returns zero rows, silently. MCO maps
to nothing: it has no published basis-risk estimate, so those cells are reported as unknown
rather than dropped, because "we did not measure it" and "it is fine" must not look alike.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .rowcropopt import (
    BASIS_BANDS,
    BASIS_COVERAGE_LEVEL,
    BASIS_PLAN_TYPE,
)

# The pessimistic correlation is the one to filter on. The reference rho of 0.70 is an
# imported assumption; the only empirical check we have (basis_risk_empirical) says the real
# miss rate sits at or below the pessimistic end. Screening on the optimistic number would
# pass exactly the cells most likely to disappoint.
DEFAULT_MAX_MISS = 0.30
DEFAULT_MIN_ACRES = 5_000

SORTS = {
    "unclaimed": ("unclaimed_subsidy", "Unclaimed subsidy ($)"),
    "acres": ("unsold_acres", "Unsold acres"),
    "per_acre": ("sub_per_acre", "Subsidy per acre ($)"),
    "penetration": ("penetration", "Penetration (lowest first)"),
    "miss": ("miss_rate_rho_lo", "Basis risk (lowest first)"),
}
ASCENDING = {"penetration", "miss"}


@dataclass
class Prospect:
    state: str
    county_fips: str
    county_name: str
    crop: str
    band: str
    unsold_acres: float
    penetration: float | None
    sub_per_acre: float | None
    unclaimed_subsidy: float
    miss_rate: float | None = None
    miss_rate_rho_lo: float | None = None
    grade: str | None = None
    basis_band: str | None = None

    @property
    def basis_known(self) -> bool:
        return self.miss_rate_rho_lo is not None


@dataclass
class ProspectResult:
    rows: list[Prospect] = field(default_factory=list)
    total_cells: int = 0          # cells before filtering
    unknown_basis: int = 0        # cells kept/dropped for having no basis estimate
    total_unclaimed: float = 0.0  # sum over the returned rows


def basis_variants(band: str) -> tuple[str, ...]:
    """The basis_risk_county band names for an unclaimed-table band. () when unmeasured."""
    return tuple(BASIS_BANDS.get(band, ()))


def _county_names(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(f): n for f, n in conn.execute(
            "SELECT DISTINCT county_fips, county_name FROM prf_grid_county")}
    except sqlite3.OperationalError:
        return {}


def _basis_index(conn: sqlite3.Connection, coverage_level: float, plan_type: str) -> dict:
    """(county_fips, crop, basis_band) -> (miss, miss_lo, grade), loaded once.

    One query rather than a correlated lookup per cell: 25,721 cells against 82,185 basis rows
    is a join, and doing it row-by-row in Python is how a page becomes slow enough that nobody
    opens it.
    """
    out: dict[tuple[str, str, str], tuple] = {}
    try:
        rows = conn.execute(
            "SELECT county_fips, crop, band, miss_rate, miss_rate_rho_lo, grade "
            "FROM basis_risk_county WHERE coverage_level = ? AND plan_type = ?",
            (coverage_level, plan_type))
    except sqlite3.OperationalError:
        return out
    for fips, crop, band, miss, miss_lo, grade in rows:
        out[(str(fips), crop, band)] = (miss, miss_lo, grade)
    return out


def find_prospects(conn: sqlite3.Connection, *,
                   states: list[str] | None = None,
                   crops: list[str] | None = None,
                   bands: list[str] | None = None,
                   min_acres: float = DEFAULT_MIN_ACRES,
                   max_miss: float | None = DEFAULT_MAX_MISS,
                   max_penetration: float | None = None,
                   include_unknown_basis: bool = False,
                   conservative: bool = False,
                   sort: str = "unclaimed",
                   limit: int = 250,
                   coverage_level: float = BASIS_COVERAGE_LEVEL,
                   plan_type: str = BASIS_PLAN_TYPE) -> ProspectResult:
    """Rank county x crop x band cells by opportunity, screened on basis risk.

    max_miss screens on miss_rate_rho_lo -- the PESSIMISTIC correlation -- deliberately; see
    the module note. include_unknown_basis keeps cells with no published estimate (MCO, and
    any crop outside the four measured), which are never silently treated as low-risk.
    conservative=True reads the worst trigger variant of a band rather than the primary one.
    """
    result = ProspectResult()
    try:
        rows = conn.execute(
            "SELECT state, county_fips, crop, band, unsold_acres, penetration, "
            "sub_per_acre, unclaimed_subsidy FROM rowcrop_unclaimed "
            "WHERE crop <> '(all crops)' AND unclaimed_subsidy IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return result

    names = _county_names(conn)
    basis = _basis_index(conn, coverage_level, plan_type)
    want_states = {s.upper() for s in states} if states else None
    want_crops = set(crops) if crops else None
    want_bands = set(bands) if bands else None

    out: list[Prospect] = []
    for state, fips, crop, band, acres, pen, spa, unclaimed in rows:
        result.total_cells += 1
        if want_states and (state or "").upper() not in want_states:
            continue
        if want_crops and crop not in want_crops:
            continue
        if want_bands and band not in want_bands:
            continue
        if acres is None or acres < min_acres:
            continue
        if max_penetration is not None and pen is not None and pen > max_penetration:
            continue

        # WHICH TRIGGER LEVEL. ECO is sold at 95% and 90%; they carry materially different
        # basis risk and the Summary of Business does not record which a county bought.
        #
        # The default is the PRIMARY variant -- BASIS_BANDS[band][0], ECO95 -- because that is
        # the representative the rest of the app already uses, and because at the pessimistic
        # correlation it is the only variant a screen can distinguish at all: 20% of ECO95
        # cells come in under a 30% miss, against 0% of ECO90, SCO86 and STAX90. Taking the
        # worst variant is defensible in principle and useless in practice -- it returned one
        # row out of 19,102.
        #
        # conservative=True takes the worst instead, for anyone who wants the floor rather
        # than the representative case.
        miss = miss_lo = grade = None
        used_band = None
        for bv in basis_variants(band):
            hit = basis.get((str(fips), crop, bv))
            if not hit or hit[1] is None:
                continue
            if used_band is None or (conservative and hit[1] > miss_lo):
                miss, miss_lo, grade, used_band = hit[0], hit[1], hit[2], bv
            if not conservative:
                break                      # primary variant only

        if miss_lo is None:
            result.unknown_basis += 1
            if not include_unknown_basis:
                continue
        elif max_miss is not None and miss_lo > max_miss:
            continue

        out.append(Prospect(
            state=state or "", county_fips=str(fips),
            county_name=names.get(str(fips), ""), crop=crop, band=band,
            unsold_acres=float(acres), penetration=pen, sub_per_acre=spa,
            unclaimed_subsidy=float(unclaimed), miss_rate=miss,
            miss_rate_rho_lo=miss_lo, grade=grade, basis_band=used_band))

    key, _ = SORTS.get(sort, SORTS["unclaimed"])
    asc = sort in ASCENDING
    # None sorts last in BOTH directions: a missing figure is not a good score.
    out.sort(key=lambda p: (getattr(p, key) is None,
                            (getattr(p, key) or 0) * (1 if asc else -1)))
    result.rows = out[:limit]
    result.total_unclaimed = sum(p.unclaimed_subsidy for p in result.rows)
    return result


def axes(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """The distinct states / crops / bands present, for the filter controls."""
    try:
        return {
            "states": sorted({r[0] for r in conn.execute(
                "SELECT DISTINCT state FROM rowcrop_unclaimed WHERE state IS NOT NULL")}),
            "crops": sorted({r[0] for r in conn.execute(
                "SELECT DISTINCT crop FROM rowcrop_unclaimed "
                "WHERE crop <> '(all crops)'")}),
            "bands": sorted({r[0] for r in conn.execute(
                "SELECT DISTINCT band FROM rowcrop_unclaimed WHERE band IS NOT NULL")}),
        }
    except sqlite3.OperationalError:
        return {"states": [], "crops": [], "bands": []}
