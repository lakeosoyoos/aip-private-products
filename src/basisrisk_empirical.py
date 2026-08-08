"""Basis risk measured from REALIZED indemnities, not simulated from an assumed correlation.

WHY THIS MODULE EXISTS
======================
`src/basisrisk.py` answers "how often does an area-triggered band (SCO/ECO) fail to pay a
producer who had a real loss?" by SIMULATION. Its county side is measured from NASS; its farm
side rests on ONE imported number — rho, the farm-to-county yield correlation, assumed at 0.70
nationwide. The sensitivity is brutal: the shipped corn SCO86 miss rate is 0.469 at rho=0.55
and 0.246 at rho=0.85. The absolute level is therefore more assumption than measurement.

The Summary of Business records REALIZED indemnities per county x crop x year x plan. For the
same county-year we hold both an INDIVIDUAL plan (RP 02 / YP 01, which settles on the
producer's own unit) and an AREA plan (SCO 32/31, ECO 88/87, STAX 35, which settles on the
county index). When individual policies were indemnified and the area plan paid nothing, that
is an OBSERVED miss. Real, not simulated. This module builds an estimator on that.

THE ESTIMATOR, PRECISELY
========================
Universe. One CELL = (crop, county, year) where BOTH books were sold, restricted to:

  * `coverage_type = 'A'` (buy-up). CAT ('C') is 100% subsidised and the admin fee is absent
    from these files, so every producer-economics denominator collapses. 'L' (limited) and
    'E' (existing) are excluded for the same comparability reason.
  * `sob_year.settled = 1`. 2025 and 2026 are still developing — the 2026 file loads at a
    0.082 national loss ratio against a mature 0.91-0.93 — so an unsettled year would enter as
    a fabricated miss.
  * area liability > 0 and individual policies-earning-premium > 0. Without an area book in the
    cell we cannot observe whether the index fired, and a cell with no individual book has no
    losses to miss.

Per cell:

    area_fired      := area indemnity > fire_eps * area liability        (default: > 0)
    farm losses     := individual `policies_indemnified`
    farm exposures  := individual `policies_earning_premium`

THE HEADLINE — the policy-weighted miss rate:

    miss_policy = SUM over cells where NOT area_fired of ind_policies_indemnified
                / SUM over all cells             of ind_policies_indemnified

Read it as: of every individual policy that collected an indemnity in a county-year where the
area band was on sale, what share sat in a county-year where the band paid nothing.

WHY THE POLICY COUNT AND NOT THE LOSS RATIO. This is the one design decision that matters, and
it is what makes the estimator worth building at all. A county's individual-plan LOSS RATIO is
a county AGGREGATE — an average over farms — so it understates how bad individual farms got and
conditions on an event that is more systemic than a farm loss. `policies_indemnified` is not an
aggregate: it is a COUNT OF FARMS that collected. An individual policy pays exactly when the
insured's own realized yield/revenue falls below their own coverage level, which is precisely
the simulator's `farm loss := farm ratio < coverage_level`. So the numerator and denominator
are farm-level counts and the aggregation objection largely dissolves for THIS statistic. It
does NOT dissolve for the loss-ratio statistics, which are reported alongside and labelled.

Also computed, all on the same cells:

    miss_dollar   share of individual indemnity DOLLARS arriving in a no-fire cell
    miss_cell     share of cells with ind loss ratio >= `lr_threshold` that did not fire
                  (the literal loss-ratio-vs-loss-ratio form; kept because it is the obvious
                  construction and because its gap to miss_policy IS the aggregation effect)
    windfall_rate share of NON-indemnified individual policies sitting in a cell that fired
    p_ind_loss    SUM policies_indemnified / SUM policies_earning_premium
    p_area_fires  cell-weighted and policy-weighted frequency of the index firing
    corr_lr       corr(ind loss ratio, area loss ratio) across cells, pooled and within-county

THE FIVE THINGS THAT CAN INVALIDATE THIS — each is addressed by a named function
================================================================================
1. SHORT HISTORY (`systemic_year_exposure`, `systemic_bounds`). SCO starts 2015, ECO 2021.
   Both MISS 2012 (national loss ratio 1.65) and every other systemic year in the record. Of
   the 36 settled years 1989-2024, six ran a national loss ratio >= 1.2 (1989, 1991, 1992,
   1993, 2002, 2012) — a 16.7% base rate. The SCO window 2015-2024 contains ZERO of them; its
   worst year is 2019 at 1.07. Direction: a systemic year is a year the index FIRES, i.e. a
   HIT, not a miss. Dropping systemic years therefore biases `miss_policy` UPWARD, and any rho
   backed out of it DOWNWARD. `systemic_bounds` puts a numeric floor under the correction by
   imputing the missing systemic years as pure hits.

2. SELECTION (`by_participation_decile`, `participation_summary`). Narrower than it first
   looks, but not gone.

   WHY IT IS NARROWER. The area book is not used as a sample of losses. It is used as a
   REVEALED INDICATOR OF THE COUNTY INDEX. Whether the index fell below its trigger in a
   county-year is a county-level fact, identical for every acre of that crop/type/practice
   whether or not its owner bought the endorsement; the area indemnity is simply how we read
   that fact off the file. The denominator — individual policies indemnified — can therefore be
   the WHOLE individual book, buyers and non-buyers alike, which is also the right population:
   the question is what a PROSPECTIVE buyer should expect, not what current buyers got.

   It is narrower for a second reason. SCO is not elected acre by acre. 20-SCO §5(a), as
   replaced by 25-OBBA: "All planted acreage of the crop in the county that is insured by the
   underlying policy must be insured under this Endorsement, except ... acreage that is
   designated as covered by STAX." So for an electing policy the SCO acres ARE the underlying
   acres. The selection is between POLICIES, not within them.

   WHY IT IS NOT GONE. Three channels survive:
     (a) The sample is confined to county-years where SOMEONE bought the endorsement. Counties
         with no SCO book contribute nothing, and they are unlikely to be a random draw.
     (b) The index we observe firing is the index the BOOK settles on. RMA publishes a separate
         county index by type and practice; if the county's SCO book is mostly irrigated, the
         cell reads "fired" off the irrigated index while a dryland farm settles elsewhere.
     (c) Through RY2025 the ARC bar (20-SCO §5(a)(2), repealed by OBBBA §10303(b)) excluded
         acreage on any FSA farm serial number with an ARC election, "regardless of ARC
         enrollment status". ARC-CO is itself a county-index program, chosen by producers who
         expect county-visible revenue shortfalls, so the pre-2026 SCO book is systematically
         short of exactly the acres most likely to see the index fire. Direction: biases the
         observed miss rate UPWARD.

   What CAN be done is a stability probe — stratify by the county's area/individual acreage
   ratio, which under §5(a) is close to the share of the county's insured acres whose policies
   elected the endorsement. A flat profile means a selection story must operate equally at 3%
   and 60% participation. A sloped profile means selection is live, the LEVEL is not
   interpretable, and only the within-stratum ordering survives.

3. AGGREGATION (`simulate_cells`, `estimator_bias`). Even the policy-count form is not the
   farm-level estimand, for one reason the loss-ratio critique misses: OPTIONAL UNITS. A policy
   is counted indemnified when ANY unit paid, not when the whole farm was short. A one-unit
   loss is more frequent and more idiosyncratic than a whole-farm loss, so the estimator's
   conditioning event is broader and more local than the simulator's — biasing `miss_policy`
   UPWARD. `simulate_cells` reproduces the estimator on synthetic data where the true
   farm-level answer is known, so the size of that bias is computed rather than asserted.
   How much of the book it can touch is itself measurable: the RY2015-2024 individual RP book
   (coverage_type 'A', settled years) is 59.1% ENTERPRISE units by liability, 12.6% basic and
   25.1% optional (sob_unit_national). An enterprise unit pools every acre of that crop the
   insured has in the county into ONE unit, so for three fifths of the book `indemnified`
   already means a whole-farm shortfall and the bias is zero. Liability-weighted effective
   units per policy is roughly 1.5.
   Cutting the other way, a county index is published BY TYPE AND PRACTICE, so a cell can show
   `area_fired` because the irrigated index tripped while the dryland index a dryland farmer
   actually settles on did not — biasing DOWNWARD. Both are documented; only the first is
   quantified here.

4. OPEN YEARS. Handled by the `settled` join described above. `load_cells` refuses to run
   without `sob_year`, rather than silently including 2026.

5. CAT. Handled by the `coverage_type='A'` filter.

WHAT THIS CAN AND CANNOT ESTABLISH
==================================
CAN: that a miss of this general magnitude happens, at a measured rate, on real money, in the
years we can see; the RANK of counties/crops by observed miss frequency; a range for rho that
is CONSISTENT WITH observed outcomes under the simulator's own model (`implied_rho`).

CANNOT: a farm-level miss rate, because the SoB has no farms in it; an unbiased estimate of the
long-run rate, because the observation window excludes every systemic year in the record; a
per-county rate, because a county contributes at most 10 SCO years and 4 ECO years and the
year-block bootstrap interval on that is wider than the entire rho sensitivity band; anything
at all about the producers who did NOT buy the endorsement.

Verdict on rho, argued in docs/basis_risk_empirical.md: CALIBRATE and CROSS-CHECK, do not
REPLACE.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

import numpy as np

from src import basisrisk as B


# ===========================================================================
# Plan pairing
# ===========================================================================
# RMA insurance plan codes, verified against the plan_abbrev column of sob_national in
# data/catalog_app.db (2011-2026): 01 YP, 02 RP, 03 RPHPE, 31 SCO-YP, 32 SCO-RP, 33 SCO-RPHPE,
# 35 STAX-RP, 36 STAX-RPHPE, 87 ECO-YP, 88 ECO-RP, 89 ECO-RPHPE, 90 APH.

@dataclass(frozen=True)
class PairSpec:
    """One area plan and the individual plan it is compared against.

    `band` is the `basis_risk_county.band` this pair maps onto, or None where the simulator
    writes nothing (STAX). The mapping is not cosmetic: basis risk depends on the TRIGGER, so
    an ECO row is only comparable to ECO95 if the ECO book being measured elected the 95%
    trigger — hence `area_coverage_levels`.

    `area_coverage_meaning` records what `sob_sales.coverage_level` holds on the AREA side, and
    the two plans differ:
      * SCO — the UNDERLYING policy's coverage level (0.50-0.85). SCO always triggers at 86%
        and exits at the underlying level, so this column is the band's WIDTH, and it is also
        the farm's own deductible, i.e. the simulator's `coverage_level`.
      * ECO / STAX — the band's TRIGGER (0.90 / 0.95). The underlying level is not recoverable
        from these rows.
    """
    name: str
    area_plans: tuple[str, ...]
    ind_plans: tuple[str, ...]
    plan_type: str                       # RP | YP
    band: str | None                     # basis_risk_county.band, or None
    first_year: int                      # first crop year the plan exists at all
    area_coverage_meaning: str           # "underlying" | "trigger"
    area_coverage_levels: tuple[float, ...] | None = None   # restrict the area book


PAIR_SPECS: dict[str, PairSpec] = {
    # SCO against individual RP. The default pair: it is the biggest area book with an
    # individual twin (RY2015-2026 SCO-RP liability $8.97B) and both legs carry the same
    # harvest-price mechanics, so a difference between them is yield basis, not price.
    "SCO-RP": PairSpec("SCO-RP", ("32",), ("02",), "RP", "SCO86", 2015, "underlying"),
    "SCO-YP": PairSpec("SCO-YP", ("31",), ("01",), "YP", "SCO86", 2015, "underlying"),
    # ECO at the 95% trigger is 98.4% of the ECO-RP book by liability ($11.93B of $12.13B),
    # computed from sob_national; the simulator's ECO95 row is the right comparator.
    "ECO-RP": PairSpec("ECO-RP", ("88",), ("02",), "RP", "ECO95", 2021, "trigger", (0.95,)),
    "ECO-RP90": PairSpec("ECO-RP90", ("88",), ("02",), "RP", "ECO90", 2021, "trigger", (0.90,)),
    "ECO-YP": PairSpec("ECO-YP", ("87",), ("01",), "YP", "ECO95", 2021, "trigger", (0.95,)),
    # STAX maps to NO simulated band — basisrisk.py deliberately writes none, and STAX does not
    # require an underlying policy, so its selection problem is different in kind.
    "STAX-RP": PairSpec("STAX-RP", ("35",), ("02",), "RP", None, 2015, "trigger"),
}

DEFAULT_PAIR = "SCO-RP"
CROPS = ("Corn", "Soybeans", "Wheat")

# A cell counts as "the index fired" when area indemnity exceeds this share of area liability.
# Default 0 (any dollar). A county index is one number per type/practice, so in a clean county
# the outcome really is all-or-nothing; a small positive value means one practice fired and
# another did not. `fire_eps` exists to let that case be moved to the other side and the answer
# re-read, not because 0 is wrong.
DEFAULT_FIRE_EPS = 0.0

# Below this many indemnified individual policies a pooled estimate is refused. Chosen to be
# obviously too small rather than defensibly right: at any n a county reaches in 10 years the
# per-county number is dominated by sampling error, and `bootstrap_ci` is the honest guard.
MIN_LOSS_POLICIES = 30

# National loss ratio at or above which a crop year is called SYSTEMIC. 1.2 is a judgment call;
# `systemic_year_exposure` reports the whole distribution so the reader can move it.
SYSTEMIC_LR = 1.2


class EmptySourceError(RuntimeError):
    """sob_sales (or sob_year) is missing or empty. Raised loudly, never worked around."""


# ===========================================================================
# The observation unit
# ===========================================================================

@dataclass
class CellObs:
    """One (crop, county, year) with both books present. Everything downstream is these."""
    crop: str
    state: str
    county_fips: str
    year: int
    # -- individual plan ------------------------------------------------------
    ind_policies_earning: float = 0.0
    ind_policies_indemnified: float = 0.0
    ind_indemnity: float = 0.0
    ind_premium: float = 0.0
    ind_liability: float = 0.0
    ind_acres: float = 0.0
    # -- area plan ------------------------------------------------------------
    area_policies_earning: float = 0.0
    area_policies_indemnified: float = 0.0
    area_indemnity: float = 0.0
    area_premium: float = 0.0
    area_liability: float = 0.0
    area_acres: float = 0.0
    # -- optional: set when the pull was restricted to one coverage level -------
    coverage_level: float | None = None

    # -- derived ---------------------------------------------------------------
    @property
    def ind_loss_ratio(self) -> float:
        return self.ind_indemnity / self.ind_premium if self.ind_premium > 0 else float("nan")

    @property
    def area_loss_ratio(self) -> float:
        return self.area_indemnity / self.area_premium if self.area_premium > 0 else float("nan")

    @property
    def ind_loss_freq(self) -> float:
        """Share of individual policies that collected. The farm-level loss frequency."""
        if self.ind_policies_earning > 0:
            return self.ind_policies_indemnified / self.ind_policies_earning
        return float("nan")

    @property
    def area_loss_cost(self) -> float:
        return self.area_indemnity / self.area_liability if self.area_liability > 0 else float("nan")

    @property
    def participation_share(self) -> float:
        """Area net acres / individual net acres. The selection probe's stratifier."""
        return self.area_acres / self.ind_acres if self.ind_acres > 0 else float("nan")

    def fired(self, fire_eps: float = DEFAULT_FIRE_EPS) -> bool:
        if self.area_liability <= 0:
            return False
        return self.area_indemnity > fire_eps * self.area_liability

    def usable(self) -> bool:
        return (self.area_liability > 0 and self.ind_policies_earning > 0
                and self.ind_premium > 0)


# ===========================================================================
# Loading
# ===========================================================================

def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


_has_table = has_table          # historical alias, kept so callers need not care


def settled_years(conn: sqlite3.Connection) -> set[int]:
    """Crop years whose indemnities are mature, from sob_year.settled.

    Raises rather than guessing. An unsettled year in this estimator is not a small error: an
    unsettled year has almost no indemnities recorded yet on EITHER side, and the area side
    develops later than the individual side, so it enters as an almost-pure fabricated miss.
    """
    if not _has_table(conn, "sob_year"):
        raise EmptySourceError(
            "sob_year is missing, so settled/unsettled cannot be told apart. Load it with "
            "`.venv/bin/python -m src.refresh --source rma_sob` before running this estimator.")
    rows = conn.execute("SELECT year FROM sob_year WHERE settled = 1").fetchall()
    if not rows:
        raise EmptySourceError("sob_year has no settled years — the SoB load is incomplete.")
    return {int(r[0]) for r in rows}


def _cl_clause(col_alias: str, levels: tuple[float, ...] | None) -> str:
    if not levels:
        return ""
    inner = " OR ".join(f"ABS({col_alias}.coverage_level - {lv:g}) < 1e-6" for lv in levels)
    return f" AND ({inner})"


def load_cells(
    conn: sqlite3.Connection,
    *,
    pair: str | PairSpec = DEFAULT_PAIR,
    crops: Sequence[str] = CROPS,
    min_year: int | None = None,
    max_year: int | None = None,
    coverage_levels: Sequence[float] | None = None,
    states: Sequence[str] | None = None,
    settled: set[int] | None = None,
) -> list[CellObs]:
    """Pull the county x crop x year cells for one area/individual pair out of `sob_sales`.

    `coverage_levels` restricts BOTH books to the same coverage level(s) — the matched
    comparison. It is only meaningful for the SCO pairs, where the area row's coverage_level is
    the underlying election and therefore the same quantity as the individual row's. For ECO
    the area coverage_level is the TRIGGER; the pair spec already restricts it, and
    `coverage_levels` then applies to the individual side only, which is what you want when
    comparing against a `basis_risk_county` row built at one farm coverage level.

    `settled` overrides the `sob_year` lookup. It exists because `sob_year` and `sob_sales` do
    not always live in the same file — catalog_app.db ships `sob_year` while the county-grain
    `sob_sales` stays in the working DB — and because an analyst restricting the window by hand
    should not have to fake a table. Passing an unsettled year in it is on the caller.

    Raises EmptySourceError with an actionable message when `sob_sales` is absent or empty —
    the table is rebuilt by scripts/rebuild_rest.sh and is legitimately empty mid-rebuild.
    """
    spec = pair if isinstance(pair, PairSpec) else PAIR_SPECS[pair]
    if not has_table(conn, "sob_sales"):
        raise EmptySourceError(
            "sob_sales is missing. It is the county x crop x plan x coverage-level Summary of "
            "Business and the only source of realized county indemnities. Rebuild it with "
            "scripts/rebuild_rest.sh (or `python -m src.refresh --source rma_sob`).")
    n_rows = conn.execute("SELECT COUNT(*) FROM sob_sales").fetchone()[0]
    if n_rows == 0:
        raise EmptySourceError(
            "sob_sales is EMPTY (0 rows). It is mid-rebuild; scripts/rebuild_rest.sh repopulates "
            "it with ~3.23M rows (county x crop x plan x coverage level, 1989-2026). "
            "This estimator has nothing to measure until it lands.")

    settled = settled if settled is not None else settled_years(conn)
    lo = max(min_year or spec.first_year, spec.first_year)
    hi = max_year if max_year is not None else max(settled)
    years = sorted(y for y in settled if lo <= y <= hi)
    if not years:
        raise EmptySourceError(
            f"no SETTLED crop years between {lo} and {hi}; {spec.name} starts in "
            f"{spec.first_year} and the newest settled year is {max(settled)}.")

    ind_in = ",".join("?" * len(spec.ind_plans))
    area_in = ",".join("?" * len(spec.area_plans))
    yr_in = ",".join("?" * len(years))
    crop_in = ",".join("?" * len(crops))

    # Coverage-level restrictions differ by side; see the docstring.
    ind_cl = _cl_clause("s", tuple(coverage_levels) if coverage_levels else None)
    area_cl = _cl_clause("s", spec.area_coverage_levels)
    if spec.area_coverage_meaning == "underlying" and coverage_levels:
        area_cl += _cl_clause("s", tuple(coverage_levels))

    ind_when = f"s.plan_code IN ({ind_in}){ind_cl}"
    area_when = f"s.plan_code IN ({area_in}){area_cl}"

    def agg(side_when: str, col: str) -> str:
        return f"SUM(CASE WHEN {side_when} THEN COALESCE(s.{col}, 0) ELSE 0 END)"

    sql = f"""
        SELECT s.crop, s.state, s.county_fips, s.year,
               {agg(ind_when, 'policies_earning_premium')},
               {agg(ind_when, 'policies_indemnified')},
               {agg(ind_when, 'indemnity')},
               {agg(ind_when, 'total_premium')},
               {agg(ind_when, 'liability')},
               {agg(ind_when, 'net_acres')},
               {agg(area_when, 'policies_earning_premium')},
               {agg(area_when, 'policies_indemnified')},
               {agg(area_when, 'indemnity')},
               {agg(area_when, 'total_premium')},
               {agg(area_when, 'liability')},
               {agg(area_when, 'net_acres')}
        FROM sob_sales s
        WHERE s.coverage_type = 'A'
          AND s.year IN ({yr_in})
          AND s.crop IN ({crop_in})
          AND (s.plan_code IN ({ind_in}) OR s.plan_code IN ({area_in}))
    """
    args: list = []
    # Order matters: the CASE expressions are evaluated in SELECT order, then the WHERE.
    for _ in range(6):
        args += list(spec.ind_plans)
    for _ in range(6):
        args += list(spec.area_plans)
    args += years + list(crops) + list(spec.ind_plans) + list(spec.area_plans)
    if states:
        sql += f" AND s.state IN ({','.join('?' * len(states))})"
        args += list(states)
    sql += " GROUP BY s.crop, s.state, s.county_fips, s.year"

    cells: list[CellObs] = []
    only_cl = float(coverage_levels[0]) if coverage_levels and len(coverage_levels) == 1 else None
    for r in conn.execute(sql, args):
        cell = CellObs(
            crop=r[0], state=r[1], county_fips=r[2], year=int(r[3]),
            ind_policies_earning=float(r[4] or 0), ind_policies_indemnified=float(r[5] or 0),
            ind_indemnity=float(r[6] or 0), ind_premium=float(r[7] or 0),
            ind_liability=float(r[8] or 0), ind_acres=float(r[9] or 0),
            area_policies_earning=float(r[10] or 0), area_policies_indemnified=float(r[11] or 0),
            area_indemnity=float(r[12] or 0), area_premium=float(r[13] or 0),
            area_liability=float(r[14] or 0), area_acres=float(r[15] or 0),
            coverage_level=only_cl,
        )
        if cell.usable():
            cells.append(cell)
    return cells


# ===========================================================================
# The estimator
# ===========================================================================

@dataclass
class EmpiricalMiss:
    """The observed analogue of basisrisk.BasisRisk. Every field is a realized frequency."""
    pair: str
    n_cells: int
    n_counties: int
    n_years: int
    year_min: int
    year_max: int
    fire_eps: float
    lr_threshold: float
    # -- exposure --------------------------------------------------------------
    ind_policies_earning: float
    ind_policies_indemnified: float
    ind_indemnity: float
    ind_premium: float
    area_indemnity: float
    area_premium: float
    ind_acres: float
    area_acres: float
    # -- THE HEADLINE ----------------------------------------------------------
    miss_policy: float          # P(index did not fire | an individual policy was indemnified)
    n_missed_policies: float
    # -- the same question, other weightings -----------------------------------
    miss_dollar: float          # share of individual indemnity dollars in a no-fire cell
    miss_cell: float            # share of cells with ind LR >= threshold that did not fire
    n_cells_over_threshold: int
    miss_cell_unweighted: float  # share of ALL cells that had any loss and did not fire
    # -- the other side of the ledger -------------------------------------------
    windfall_rate: float        # P(index fired | an individual policy was NOT indemnified)
    p_ind_loss: float           # policies indemnified / policies earning premium
    p_area_fires_cell: float
    p_area_fires_policy: float
    # -- levels, for calibration and for the reader's sanity ---------------------
    ind_loss_ratio: float
    area_loss_ratio: float
    corr_lr_pooled: float
    corr_lr_within_county: float
    participation_share_median: float

    def as_dict(self) -> dict:
        return asdict(self)


def _nan_corr(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    x, y = a[ok], b[ok]
    if x.std() <= 0 or y.std() <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def empirical_miss(
    cells: Sequence[CellObs],
    *,
    pair: str = DEFAULT_PAIR,
    fire_eps: float = DEFAULT_FIRE_EPS,
    lr_threshold: float = 1.0,
) -> EmpiricalMiss:
    """Compute the observed miss statistics over a set of cells. Pure, deterministic, no DB.

    The three limits this has to respect, all asserted in tests/test_basisrisk_empirical.py:
      * the index fires in every cell that had any indemnified policy -> miss_policy = 0
      * the index never fires                                          -> miss_policy = 1
      * the index fires independently of the individual book           -> miss_policy =
        1 - (policy-weighted firing frequency), because knowing a policy was indemnified says
        nothing about the county.
    They mirror basisrisk.metrics_from_draws' two limits on purpose: if a simulated and an
    observed estimator do not agree at the limits, comparing them in the middle is meaningless.
    """
    cells = [c for c in cells if c.usable()]
    if not cells:
        raise ValueError("no usable cells: every cell needs area liability > 0, individual "
                         "policies-earning-premium > 0 and individual premium > 0")

    fired = np.array([c.fired(fire_eps) for c in cells], dtype=bool)
    pol_ind = np.array([c.ind_policies_indemnified for c in cells], float)
    pol_earn = np.array([c.ind_policies_earning for c in cells], float)
    ind_ind = np.array([c.ind_indemnity for c in cells], float)
    ind_prem = np.array([c.ind_premium for c in cells], float)
    ind_liab = np.array([c.ind_liability for c in cells], float)
    ar_ind = np.array([c.area_indemnity for c in cells], float)
    ar_prem = np.array([c.area_premium for c in cells], float)
    ind_ac = np.array([c.ind_acres for c in cells], float)
    ar_ac = np.array([c.area_acres for c in cells], float)
    years = np.array([c.year for c in cells], int)

    pol_ok = pol_earn - pol_ind                      # policies that were NOT indemnified
    tot_ind = float(pol_ind.sum())
    tot_ok = float(pol_ok.sum())
    tot_dollars = float(ind_ind.sum())

    ind_lr = np.where(ind_prem > 0, ind_ind / np.where(ind_prem > 0, ind_prem, 1.0), np.nan)
    area_lr = np.where(ar_prem > 0, ar_ind / np.where(ar_prem > 0, ar_prem, 1.0), np.nan)

    over = np.isfinite(ind_lr) & (ind_lr >= lr_threshold)
    any_loss = pol_ind > 0

    # Within-county correlation: remove each county's own mean from both series first, so the
    # number is "when THIS county has a bad year does its index fire", not "do bad counties
    # have bad indexes". Cross-county variation is mostly rating adequacy, not basis risk.
    by_county: dict[str, list[int]] = {}
    for i, c in enumerate(cells):
        by_county.setdefault(f"{c.crop}|{c.county_fips}", []).append(i)
    dm_i, dm_a = [], []
    for idx in by_county.values():
        if len(idx) < 3:
            continue
        a = ind_lr[idx]
        b = area_lr[idx]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 3:
            continue
        dm_i.append(a[ok] - a[ok].mean())
        dm_a.append(b[ok] - b[ok].mean())

    part = np.array([c.participation_share for c in cells], float)
    part = part[np.isfinite(part)]

    return EmpiricalMiss(
        pair=pair,
        n_cells=len(cells),
        n_counties=len(by_county),
        n_years=int(len(set(years.tolist()))),
        year_min=int(years.min()), year_max=int(years.max()),
        fire_eps=fire_eps, lr_threshold=lr_threshold,
        ind_policies_earning=float(pol_earn.sum()),
        ind_policies_indemnified=tot_ind,
        ind_indemnity=tot_dollars, ind_premium=float(ind_prem.sum()),
        area_indemnity=float(ar_ind.sum()), area_premium=float(ar_prem.sum()),
        ind_acres=float(ind_ac.sum()), area_acres=float(ar_ac.sum()),
        miss_policy=float(pol_ind[~fired].sum() / tot_ind) if tot_ind > 0 else float("nan"),
        n_missed_policies=float(pol_ind[~fired].sum()),
        miss_dollar=float(ind_ind[~fired].sum() / tot_dollars) if tot_dollars > 0 else float("nan"),
        miss_cell=(float((over & ~fired).sum() / over.sum()) if over.sum() else float("nan")),
        n_cells_over_threshold=int(over.sum()),
        miss_cell_unweighted=(float((any_loss & ~fired).sum() / any_loss.sum())
                              if any_loss.sum() else float("nan")),
        windfall_rate=float(pol_ok[fired].sum() / tot_ok) if tot_ok > 0 else float("nan"),
        p_ind_loss=float(tot_ind / pol_earn.sum()) if pol_earn.sum() > 0 else float("nan"),
        p_area_fires_cell=float(fired.mean()),
        p_area_fires_policy=(float(pol_earn[fired].sum() / pol_earn.sum())
                             if pol_earn.sum() > 0 else float("nan")),
        ind_loss_ratio=float(ind_ind.sum() / ind_prem.sum()) if ind_prem.sum() > 0 else float("nan"),
        area_loss_ratio=float(ar_ind.sum() / ar_prem.sum()) if ar_prem.sum() > 0 else float("nan"),
        corr_lr_pooled=_nan_corr(ind_lr, area_lr),
        corr_lr_within_county=(_nan_corr(np.concatenate(dm_i), np.concatenate(dm_a))
                               if dm_i else float("nan")),
        participation_share_median=float(np.median(part)) if len(part) else float("nan"),
    )


# ===========================================================================
# Uncertainty. This is where the short history stops being an abstraction.
# ===========================================================================

def bootstrap_ci(
    cells: Sequence[CellObs],
    *,
    by: str = "year",
    n_boot: int = 400,
    ci: float = 0.90,
    seed: int = 13,
    stat: str = "miss_policy",
    **kw,
) -> tuple[float, float, float]:
    """(point, lo, hi) for one statistic, resampling whole BLOCKS rather than cells.

    `by` must be "year", "county" or "cell":

      * "year" is the one that matters and the one to quote. Crop years are the level at which
        the shocks are shared: every county in the Corn Belt sees the same drought, so cells
        within a year are massively correlated and treating them as independent would produce
        an interval an order of magnitude too tight. With ten SCO years the year-block interval
        is wide, and that width IS the finding — it is why this estimator cannot be used county
        by county, and why it calibrates rather than replaces.
      * "county" clusters the other way (a county's own years are correlated through its soils
        and its book).
      * "cell" is the naive i.i.d. interval. Provided only so the gap to "year" can be shown.
    """
    rng = np.random.default_rng(seed)
    cells = [c for c in cells if c.usable()]
    point = getattr(empirical_miss(cells, **kw), stat)

    if by == "cell":
        blocks = [[c] for c in cells]
    elif by == "year":
        d: dict[int, list[CellObs]] = {}
        for c in cells:
            d.setdefault(c.year, []).append(c)
        blocks = list(d.values())
    elif by == "county":
        d2: dict[str, list[CellObs]] = {}
        for c in cells:
            d2.setdefault(f"{c.crop}|{c.county_fips}", []).append(c)
        blocks = list(d2.values())
    else:
        raise ValueError(f"by must be year|county|cell, got {by!r}")

    if len(blocks) < 3:
        return point, float("nan"), float("nan")

    got: list[float] = []
    nb = len(blocks)
    for _ in range(n_boot):
        pick = rng.integers(0, nb, nb)
        sample: list[CellObs] = []
        for i in pick:
            sample.extend(blocks[i])
        try:
            v = getattr(empirical_miss(sample, **kw), stat)
        except ValueError:
            continue
        if not math.isnan(v):
            got.append(v)
    if len(got) < 20:
        return point, float("nan"), float("nan")
    a = (1 - ci) / 2
    arr = np.array(got)
    return point, float(np.quantile(arr, a)), float(np.quantile(arr, 1 - a))


def leave_one_year_out(cells: Sequence[CellObs], **kw) -> list[tuple[int, float, int]]:
    """(dropped year, miss_policy without it, n cells dropped), worst influence first.

    With ten years, one year can move the headline several points. Printing the table is more
    informative than any interval, because it names WHICH year the answer depends on.
    """
    cells = [c for c in cells if c.usable()]
    years = sorted({c.year for c in cells})
    out = []
    for y in years:
        rest = [c for c in cells if c.year != y]
        if not rest:
            continue
        try:
            out.append((y, empirical_miss(rest, **kw).miss_policy,
                        sum(1 for c in cells if c.year == y)))
        except ValueError:
            continue
    base = empirical_miss(cells, **kw).miss_policy
    out.sort(key=lambda t: -abs(t[1] - base))
    return out


# ===========================================================================
# HARD PART 1 — the short history, and the systemic years it never saw
# ===========================================================================

@dataclass
class SystemicExposure:
    """How much of the historical loss record the observation window actually contains."""
    window_min: int
    window_max: int
    systemic_lr: float
    full_years: list[int]
    full_lr: dict[int, float]
    full_systemic_years: list[int]
    window_years: list[int]
    window_systemic_years: list[int]
    missed_systemic_years: list[int]
    base_rate_systemic: float          # share of ALL settled years that were systemic
    window_rate_systemic: float        # share of window years that were systemic
    full_mean_lr: float
    window_mean_lr: float
    window_max_lr: float
    full_indemnity: float
    window_indemnity: float
    indemnity_share_in_window: float

    @property
    def direction(self) -> str:
        if self.window_rate_systemic < self.base_rate_systemic:
            return ("window is DEFICIENT in systemic years: miss_policy is biased UPWARD "
                    "(too much basis risk), and any rho backed out of it is biased DOWNWARD")
        if self.window_rate_systemic > self.base_rate_systemic:
            return ("window is RICH in systemic years: miss_policy is biased DOWNWARD "
                    "(too little basis risk), and any rho backed out of it is biased UPWARD")
        return "window matches the historical rate of systemic years"


def systemic_year_exposure(
    conn: sqlite3.Connection,
    *,
    window_min: int,
    window_max: int | None = None,
    systemic_lr: float = SYSTEMIC_LR,
) -> SystemicExposure:
    """Quantify hard part 1 from `sob_year`: which loss years the estimator can never see.

    The logic behind the sign. A systemic year is by construction a year the COUNTY INDEX
    falls — that is what "systemic" means — so it is a year the area band FIRES and the
    individual losses it coincides with are HITS, not misses. A window that contains no
    systemic years is a window whose losses are disproportionately local, and local losses are
    exactly the ones an area index misses. Hence: too few systemic years -> miss rate too high.
    """
    if not _has_table(conn, "sob_year"):
        raise EmptySourceError("sob_year is missing; cannot measure systemic-year exposure.")
    rows = conn.execute(
        "SELECT year, loss_ratio, indemnity FROM sob_year WHERE settled = 1 "
        "AND loss_ratio IS NOT NULL ORDER BY year").fetchall()
    if not rows:
        raise EmptySourceError("sob_year has no settled years with a loss ratio.")
    full_lr = {int(r[0]): float(r[1]) for r in rows}
    indem = {int(r[0]): float(r[2] or 0.0) for r in rows}
    hi = window_max if window_max is not None else max(full_lr)
    full_years = sorted(full_lr)
    win = [y for y in full_years if window_min <= y <= hi]
    if not win:
        raise EmptySourceError(f"no settled years in [{window_min}, {hi}]")
    full_sys = [y for y in full_years if full_lr[y] >= systemic_lr]
    win_sys = [y for y in win if full_lr[y] >= systemic_lr]
    tot_ind = sum(indem.values())
    win_ind = sum(indem[y] for y in win)
    return SystemicExposure(
        window_min=window_min, window_max=hi, systemic_lr=systemic_lr,
        full_years=full_years, full_lr=full_lr,
        full_systemic_years=full_sys, window_years=win, window_systemic_years=win_sys,
        missed_systemic_years=[y for y in full_sys if y not in set(win)],
        base_rate_systemic=len(full_sys) / len(full_years),
        window_rate_systemic=len(win_sys) / len(win),
        full_mean_lr=float(np.mean([full_lr[y] for y in full_years])),
        window_mean_lr=float(np.mean([full_lr[y] for y in win])),
        window_max_lr=float(max(full_lr[y] for y in win)),
        full_indemnity=tot_ind, window_indemnity=win_ind,
        indemnity_share_in_window=(win_ind / tot_ind) if tot_ind > 0 else float("nan"),
    )


@dataclass
class SystemicBounds:
    """A bound, not a correction. See `systemic_bounds`."""
    observed_miss: float
    n_window_years: int
    n_imputed_years: float
    hit_weight_per_year: float
    miss_lower: float
    miss_upper: float
    note: str


def systemic_bounds(
    emp: EmpiricalMiss,
    exposure: SystemicExposure,
    *,
    systemic_hit_rate: float = 1.0,
    loss_intensity: float = 1.0,
) -> SystemicBounds:
    """Bound `miss_policy` for the systemic years the window never saw.

    The correction is NOT identified — you cannot reweight into a stratum with zero
    observations, and the window has zero systemic years. What IS available is a bound, by
    imputing the missing years at their historical frequency and asking what they would have
    done to the ratio.

    Construction. Let the window contain `n` years carrying `L` indemnified policies of which
    `M` were missed, so observed miss = M/L. At the historical base rate the window SHOULD have
    contained `k = n * base_rate / (1 - base_rate)` additional systemic years (the count that
    restores the base rate). Each such year carries `loss_intensity x (L/n)` indemnified
    policies — 1.0 means "a systemic year has the same number of indemnified policies as an
    average year", which is conservative to the point of being wrong in the safe direction: a
    systemic year has more. 2012 is the largest indemnity year in the settled record ($16.46B)
    at a 1.647 loss ratio against a 0.916 mean, and more hits in the denominator pushes the
    corrected miss rate lower still. Of those, a share `1 - systemic_hit_rate` are missed.

      miss_upper = the observed value (the imputation can only add hits)
      miss_lower = M / (L + k * loss_intensity * L/n)   when systemic_hit_rate = 1

    Both are bounds on the LONG-RUN rate under the stated imputation, not a point estimate.
    """
    n = max(1, len(exposure.window_years))
    br = exposure.base_rate_systemic
    wr = exposure.window_rate_systemic
    if br <= wr or br >= 1.0:
        return SystemicBounds(emp.miss_policy, n, 0.0, 0.0, emp.miss_policy, emp.miss_policy,
                              "window is not deficient in systemic years; no bound needed")
    k = n * (br - wr) / (1.0 - br)
    per_year = emp.ind_policies_indemnified / n
    added = k * loss_intensity * per_year
    added_missed = added * (1.0 - systemic_hit_rate)
    denom = emp.ind_policies_indemnified + added
    lower = (emp.n_missed_policies + added_missed) / denom if denom > 0 else float("nan")
    return SystemicBounds(
        observed_miss=emp.miss_policy, n_window_years=n, n_imputed_years=k,
        hit_weight_per_year=per_year,
        miss_lower=lower, miss_upper=emp.miss_policy,
        note=(f"imputing {k:.1f} systemic year(s) at {systemic_hit_rate:.0%} hit rate and "
              f"{loss_intensity:.1f}x average loss volume restores the {br:.1%} historical "
              f"base rate of national loss ratio >= {exposure.systemic_lr}"),
    )


# ===========================================================================
# HARD PART 2 — selection
# ===========================================================================

@dataclass
class ParticipationStratum:
    label: str
    lo: float
    hi: float
    n_cells: int
    n_counties: int
    policies_indemnified: float
    area_acres: float
    ind_acres: float
    miss_policy: float


def by_participation_decile(
    cells: Sequence[CellObs], *, n_strata: int = 5, **kw
) -> list[ParticipationStratum]:
    """Stratify the estimate by area-acres / individual-acres. The selection stability probe.

    What this can and cannot do. It cannot identify selection: SoB never records which
    individual policies also bought the endorsement, so the acres under the two plans are
    simply different acres and no reweighting fixes that. What it can do is test whether the
    answer MOVES with participation. A flat profile does not prove the absence of selection —
    it means a selection story must work equally at 3% and 60% participation. A sloped profile
    is affirmative evidence that it is present, and in that case the LEVEL is not interpretable
    and only the within-stratum ordering survives.
    """
    cells = [c for c in cells if c.usable() and math.isfinite(c.participation_share)]
    if not cells:
        return []
    shares = np.array([c.participation_share for c in cells])
    edges = np.quantile(shares, np.linspace(0, 1, n_strata + 1))
    out: list[ParticipationStratum] = []
    for i in range(n_strata):
        lo, hi = float(edges[i]), float(edges[i + 1])
        cut_lo = -np.inf if i == 0 else lo
        cut_hi = np.inf if i == n_strata - 1 else hi
        grp = [c for c in cells if cut_lo <= c.participation_share < cut_hi
               or (i == n_strata - 1 and c.participation_share >= cut_lo)]
        if not grp:
            continue
        try:
            e = empirical_miss(grp, **kw)
        except ValueError:
            continue
        out.append(ParticipationStratum(
            label=f"Q{i+1}", lo=lo, hi=hi,
            n_cells=e.n_cells, n_counties=e.n_counties,
            policies_indemnified=e.ind_policies_indemnified,
            area_acres=e.area_acres, ind_acres=e.ind_acres,
            miss_policy=e.miss_policy))
    return out


def participation_summary(cells: Sequence[CellObs]) -> dict:
    """How much of the individual book the area book actually overlaps. Scale of the problem."""
    cells = [c for c in cells if c.usable()]
    if not cells:
        return {}
    ia = sum(c.ind_acres for c in cells)
    aa = sum(c.area_acres for c in cells)
    per = np.array([c.participation_share for c in cells], float)
    per = per[np.isfinite(per)]
    return {
        "n_cells": len(cells),
        "ind_acres": ia, "area_acres": aa,
        "overall_participation": (aa / ia) if ia > 0 else float("nan"),
        "median_county_participation": float(np.median(per)) if len(per) else float("nan"),
        "p90_county_participation": float(np.quantile(per, 0.90)) if len(per) else float("nan"),
        "share_of_cells_under_5pct": float((per < 0.05).mean()) if len(per) else float("nan"),
    }


# ===========================================================================
# HARD PART 3 — aggregation. Quantified, not asserted.
# ===========================================================================

@dataclass
class SimCells:
    """Synthetic county-years with the truth attached, for measuring the estimator's bias."""
    rho: float
    n_farms: int
    n_cells: int
    units_per_farm: int
    within_farm_rho: float
    coverage_level: float
    band: str
    trigger: float
    exit: float
    # -- the estimand: what basisrisk.py's miss_rate means ----------------------
    true_farm_miss: float          # P(no fire | WHOLE-FARM ratio < coverage level)
    p_farm_loss: float
    # -- what the SoB estimator would report on the same world ------------------
    est_miss_policy: float         # P(no fire | ANY unit of the policy short)
    est_miss_dollar: float
    est_miss_cell: float
    p_policy_loss: float
    p_fire: float
    # -- the gap ----------------------------------------------------------------
    bias_policy: float             # est_miss_policy - true_farm_miss
    cells: list[CellObs] = field(default_factory=list)


def simulate_cells(
    county_ratios: Sequence[float],
    *,
    rho: float = B.RHO_REF,
    n_farms: int = 150,
    n_cells: int = 4000,
    coverage_level: float = 0.85,
    band: str = "SCO86",
    plan_type: str = "RP",
    price_vol: float = 0.15,
    corr_county_national: float = 0.5,
    corr_national_price: float = -0.6,
    units_per_farm: int = 1,
    within_farm_rho: float = 0.6,
    seed: int = 21,
    keep_cells: bool = False,
) -> SimCells:
    """Run the SoB estimator against a simulated world where the true answer is known.

    Same generative model as `basisrisk.draw_joint` — county draw from the variance-corrected
    smoothed bootstrap, farm = county + independent shock with sigma_e = sigma_c*sqrt(1/rho^2-1),
    one national harvest-price factor with the same max(1,p) guarantee reset — extended in one
    way: each county-year now carries `n_farms` farms rather than one, and optionally
    `units_per_farm` optional units per farm, so the SoB's actual observables
    (`policies_indemnified`, county indemnity totals) can be constructed and the estimator run
    on them.

    `test_single_farm_matches_the_simulator` pins this reimplementation to
    `basisrisk.basis_risk` at n_farms=1, units_per_farm=1. That test is the guard against the
    two models silently drifting apart; without it, any bias measured here would be
    indistinguishable from a coding difference.

    OPTIONAL UNITS are the reason the estimator is not exactly the estimand. RMA counts a policy
    indemnified when ANY unit paid. `within_farm_rho` is the correlation between two units of
    the same farm net of the county; the farm's WHOLE-FARM idiosyncratic variance is held at
    sigma_e^2 regardless, so turning units on redistributes variance rather than adding it, and
    the resulting bias is attributable to the unit structure alone.
    """
    if not 0.0 < rho <= 1.0:
        raise ValueError(f"rho must be in (0, 1], got {rho}")
    if n_farms < 1 or units_per_farm < 1:
        raise ValueError("n_farms and units_per_farm must be >= 1")
    if not 0.0 < within_farm_rho <= 1.0:
        raise ValueError("within_farm_rho must be in (0, 1]")
    exit_, trigger = B.band_bounds(band, coverage_level)
    width = trigger - exit_

    rng = np.random.default_rng(seed)
    ratios = np.asarray(county_ratios, float)
    sigma_c = float(ratios.std(ddof=1)) if len(ratios) > 1 else 0.0
    y_c = B.smoothed_bootstrap(rng, ratios, n_cells)
    sigma_e = sigma_c * math.sqrt(max(0.0, 1.0 / (rho * rho) - 1.0))

    # Split sigma_e into a farm-common part and a unit-specific part so that the WHOLE-FARM
    # idiosyncratic SD is sigma_e for any units_per_farm:
    #     var_f + var_u/k = sigma_e^2 ,  var_u = var_f (1-w)/w
    k, w = units_per_farm, within_farm_rho
    var_f = sigma_e ** 2 / (1.0 + (1.0 - w) / (w * k)) if sigma_e > 0 else 0.0
    var_u = var_f * (1.0 - w) / w if w < 1.0 else 0.0
    f_shock = rng.standard_normal((n_cells, n_farms)) * math.sqrt(var_f)
    u_shock = (rng.standard_normal((n_cells, n_farms, k)) * math.sqrt(var_u)
               if var_u > 0 else np.zeros((n_cells, n_farms, k)))

    unit_ratio = y_c[:, None, None] + f_shock[:, :, None] + u_shock
    farm_ratio = unit_ratio.mean(axis=2)

    if plan_type == "RP" and price_vol > 0:
        rho_yp = float(np.clip(corr_county_national * corr_national_price, -0.99, 0.99))
        srt = np.sort(ratios)
        u = (np.searchsorted(srt, y_c, side="left") + 0.5) / len(srt)
        z_c = B._norm_ppf(np.clip(u, 1e-6, 1 - 1e-6))
        z_p = rho_yp * z_c + math.sqrt(max(0.0, 1 - rho_yp ** 2)) * rng.standard_normal(n_cells)
        sig = math.sqrt(math.log(1.0 + price_vol * price_vol))
        p = np.exp(sig * z_p - 0.5 * sig * sig)
        fac = (p / np.maximum(1.0, p))[:, None]
        y_c = y_c * fac[:, 0]
        farm_ratio = farm_ratio * fac
        unit_ratio = unit_ratio * fac[:, :, None]

    farm_ratio = np.clip(farm_ratio, 0.0, None)
    unit_ratio = np.clip(unit_ratio, 0.0, None)

    fired = y_c < trigger
    area_pay = np.clip(trigger - y_c, 0.0, width)

    farm_loss = farm_ratio < coverage_level                     # THE ESTIMAND's event
    unit_short = unit_ratio < coverage_level
    policy_ind = unit_short.any(axis=2)                         # what SoB actually counts
    unit_indem = np.clip(coverage_level - unit_ratio, 0.0, None).sum(axis=(1, 2))
    n_pol_ind = policy_ind.sum(axis=1).astype(float)

    true_miss = (float((farm_loss & ~fired[:, None]).sum() / farm_loss.sum())
                 if farm_loss.sum() else float("nan"))

    # Premiums at the statutory target loss ratio of 1.0, so a loss ratio means what it means.
    ind_prem_cell = float(unit_indem.mean()) or 1.0
    area_prem_cell = float(area_pay.mean()) or 1.0
    cells = [
        CellObs(crop="SIM", state="SM", county_fips="00000", year=1000 + i,
                ind_policies_earning=float(n_farms),
                ind_policies_indemnified=float(n_pol_ind[i]),
                ind_indemnity=float(unit_indem[i]), ind_premium=ind_prem_cell,
                ind_liability=float(n_farms * k), ind_acres=float(n_farms),
                area_policies_earning=float(n_farms),
                area_policies_indemnified=float(n_farms if fired[i] else 0),
                area_indemnity=float(area_pay[i]), area_premium=area_prem_cell,
                area_liability=1.0, area_acres=float(n_farms),
                coverage_level=coverage_level)
        for i in range(n_cells)
    ]
    est = empirical_miss(cells, pair="SIM")
    return SimCells(
        rho=rho, n_farms=n_farms, n_cells=n_cells, units_per_farm=units_per_farm,
        within_farm_rho=within_farm_rho, coverage_level=coverage_level,
        band=band, trigger=trigger, exit=exit_,
        true_farm_miss=true_miss, p_farm_loss=float(farm_loss.mean()),
        est_miss_policy=est.miss_policy, est_miss_dollar=est.miss_dollar,
        est_miss_cell=est.miss_cell, p_policy_loss=float(policy_ind.mean()),
        p_fire=float(fired.mean()),
        bias_policy=(est.miss_policy - true_miss
                     if not math.isnan(true_miss) else float("nan")),
        cells=cells if keep_cells else [],
    )


def estimator_bias(
    county_ratios: Sequence[float],
    *,
    rhos: Sequence[float] = (0.55, 0.70, 0.85),
    units: Sequence[int] = (1, 3),
    **kw,
) -> list[SimCells]:
    """The aggregation/unit-structure bias table: run the estimator against known truth."""
    out = []
    for rho in rhos:
        for k in units:
            out.append(simulate_cells(county_ratios, rho=rho, units_per_farm=k, **kw))
    return out


# ===========================================================================
# CALIBRATION — back the rho out of the observed outcome
# ===========================================================================

@dataclass
class ImpliedRho:
    target: float
    metric: str
    rho: float | None
    rho_lo: float | None          # from the target's own confidence interval
    rho_hi: float | None
    bracket_lo: float
    bracket_hi: float
    value_at_lo: float
    value_at_hi: float
    n_iter: int
    note: str


def implied_rho(
    target_miss: float,
    county_ratios: Sequence[float],
    *,
    metric: str = "estimator",
    target_lo: float | None = None,
    target_hi: float | None = None,
    bracket: tuple[float, float] = (0.10, 0.995),
    tol: float = 2e-3,
    max_iter: int = 30,
    n_cells: int = 4000,
    n_farms: int = 60,
    **kw,
) -> ImpliedRho:
    """Invert the simulator: which rho reproduces the OBSERVED miss rate?

    `metric`:
      * "estimator" (default) — match `simulate_cells(...).est_miss_policy`, i.e. reproduce
        what the SoB estimator itself would report in a world with that rho. This is the
        like-for-like inversion: the optional-unit and county-index effects sit on BOTH sides,
        so they cancel instead of being charged to rho.
      * "farm" — match the clean farm-level `basisrisk.basis_risk(...).miss_rate`. Use only if
        you believe the estimator is unbiased for the farm concept, which `estimator_bias`
        exists to test and generally refutes.

    THIS IS A CALIBRATION, NOT A MEASUREMENT. The inversion runs entirely inside the
    farm = county + independent-shock model. It converts an observed frequency into the value
    of rho that would have produced it *under that model*; it does not test the model, and
    every bias in the target (§ hard parts 1-3) passes straight through into rho. Pass
    `target_lo`/`target_hi` — the year-block bootstrap endpoints — and read the rho interval,
    never the point.

    Monotonicity: miss rate is decreasing in rho (a farm more like its county is missed less
    often), so bisection is valid. The bracket is checked and a target outside it returns
    rho=None with a note rather than a clipped answer that looks like a result.
    """
    ratios = np.asarray(county_ratios, float)

    def f(rho: float) -> float:
        if metric == "estimator":
            return simulate_cells(ratios, rho=rho, n_cells=n_cells, n_farms=n_farms, **kw).est_miss_policy
        if metric == "farm":
            allowed = {k: v for k, v in kw.items()
                       if k not in ("units_per_farm", "within_farm_rho", "keep_cells")}
            return B.basis_risk(ratios, rho=rho, n_draws=max(n_cells * n_farms, 50_000),
                                **allowed).miss_rate
        raise ValueError(f"metric must be 'estimator' or 'farm', got {metric!r}")

    lo, hi = bracket
    v_lo, v_hi = f(lo), f(hi)          # v_lo is the HIGH miss rate (low rho)

    def solve(t: float) -> tuple[float | None, int]:
        if math.isnan(t):
            return None, 0
        if t > v_lo or t < v_hi:
            return None, 0
        a, b = lo, hi
        for i in range(max_iter):
            m = 0.5 * (a + b)
            v = f(m)
            if abs(v - t) < tol:
                return m, i + 1
            if v > t:
                a = m
            else:
                b = m
        return 0.5 * (a + b), max_iter

    rho, n_iter = solve(target_miss)
    # A HIGHER observed miss rate implies a LOWER rho, so the interval endpoints swap.
    r_hi, _ = solve(target_lo) if target_lo is not None else (None, 0)
    r_lo, _ = solve(target_hi) if target_hi is not None else (None, 0)

    if rho is None:
        note = (f"target {target_miss:.3f} is outside the reachable range "
                f"[{v_hi:.3f} at rho={hi:.3f}, {v_lo:.3f} at rho={lo:.3f}]. "
                "No rho in the model reproduces it — which is itself informative: the observed "
                "outcome is not consistent with the model at ANY correlation, so the gap is "
                "something other than farm-county correlation.")
    else:
        note = "bisection on a monotone decreasing function; model-internal, not a measurement"
    return ImpliedRho(target=target_miss, metric=metric, rho=rho, rho_lo=r_lo, rho_hi=r_hi,
                      bracket_lo=lo, bracket_hi=hi, value_at_lo=v_lo, value_at_hi=v_hi,
                      n_iter=n_iter, note=note)


# ===========================================================================
# Comparison against the simulated table
# ===========================================================================

def by_county(
    cells: Sequence[CellObs], *, min_loss_policies: int = MIN_LOSS_POLICIES, **kw
) -> dict[tuple[str, str], EmpiricalMiss]:
    """(crop, county_fips) -> EmpiricalMiss, for counties with enough observed losses.

    The gate is necessary and nowhere near sufficient. A county contributes at most ten SCO
    years; `bootstrap_ci(by='year')` on a single county is normally wider than [0, 1] is
    useful. Treat these rows as an input to a POOLED or RANK comparison, never as a county's
    basis risk.
    """
    groups: dict[tuple[str, str], list[CellObs]] = {}
    for c in cells:
        if c.usable():
            groups.setdefault((c.crop, c.county_fips), []).append(c)
    out = {}
    for key, grp in groups.items():
        tot = sum(g.ind_policies_indemnified for g in grp)
        if tot < min_loss_policies:
            continue
        try:
            out[key] = empirical_miss(grp, **kw)
        except ValueError:
            continue
    return out


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    x, y = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 5:
        return float("nan")
    def rank(v):
        order = v.argsort()
        r = np.empty(len(v), float)
        r[order] = np.arange(len(v), dtype=float)
        return r
    return _nan_corr(rank(x[ok]), rank(y[ok]))


@dataclass
class Comparison:
    band: str
    crop: str | None
    coverage_level: float
    n_matched: int
    empirical_median: float
    simulated_median: float
    simulated_median_rho_lo: float
    simulated_median_rho_hi: float
    spearman: float
    share_empirical_above_simulated: float
    share_empirical_inside_rho_band: float
    rows: list[tuple] = field(default_factory=list)   # (crop, fips, n_loss_pol, emp, sim, lo, hi)


def compare_to_simulated(
    conn: sqlite3.Connection,
    county_miss: dict[tuple[str, str], EmpiricalMiss],
    *,
    band: str,
    coverage_level: float = 0.85,
    plan_type: str = "RP",
    crop: str | None = None,
) -> Comparison:
    """Join the observed county rates onto `basis_risk_county` and characterise the agreement.

    Two things are worth reading and one is not:
      * WORTH: the level gap between the pooled medians, and whether the observed rates fall
        inside the simulated rho_lo/rho_hi band.
      * WORTH: the Spearman rank correlation — does the simulator order counties the way the
        realized record does? Rank survives a lot of level bias.
      * NOT WORTH: any individual county row. See `by_county`.

    A coverage-level caveat travels with every comparison: `basis_risk_county` as shipped is
    built at farm coverage level 0.85 only, while the SCO book is dominated by underlying 0.75
    and 0.80 (RY2015-2026 SCO-RP liability $3.77B at 0.75 and $1.86B at 0.80, against $0.08B at
    0.85). SCO86 at 0.85 is a ONE-POINT band; at 0.75 it is eleven. Comparing an observed 0.75
    book against a simulated 0.85 row compares two different products. Restrict the pull with
    `load_cells(coverage_levels=[0.85])` for a matched comparison, or rebuild the simulated
    side at the observed modal level.
    """
    if not _has_table(conn, "basis_risk_county"):
        raise EmptySourceError("basis_risk_county is missing; build it with "
                               "scripts/analysis/build_basis_risk.py")
    rows = []
    for (cr, fips), e in sorted(county_miss.items()):
        if crop and cr != crop:
            continue
        r = conn.execute(
            "SELECT miss_rate, miss_rate_rho_lo, miss_rate_rho_hi FROM basis_risk_county "
            "WHERE crop=? AND county_fips=? AND band=? AND plan_type=? "
            "AND ABS(coverage_level - ?) < 1e-6",
            (cr, fips, band, plan_type, coverage_level)).fetchone()
        if not r or r[0] is None:
            continue
        rows.append((cr, fips, e.ind_policies_indemnified, e.miss_policy,
                     float(r[0]), float(r[1]) if r[1] is not None else float("nan"),
                     float(r[2]) if r[2] is not None else float("nan")))
    if not rows:
        return Comparison(band, crop, coverage_level, 0, float("nan"), float("nan"),
                          float("nan"), float("nan"), float("nan"), float("nan"), float("nan"))
    emp = np.array([r[3] for r in rows], float)
    sim = np.array([r[4] for r in rows], float)
    s_lo = np.array([r[5] for r in rows], float)
    s_hi = np.array([r[6] for r in rows], float)
    inside = np.isfinite(s_lo) & np.isfinite(s_hi) & (emp >= s_hi) & (emp <= s_lo)
    return Comparison(
        band=band, crop=crop, coverage_level=coverage_level, n_matched=len(rows),
        empirical_median=float(np.median(emp)), simulated_median=float(np.median(sim)),
        simulated_median_rho_lo=float(np.nanmedian(s_lo)),
        simulated_median_rho_hi=float(np.nanmedian(s_hi)),
        spearman=_spearman(emp, sim),
        share_empirical_above_simulated=float((emp > sim).mean()),
        share_empirical_inside_rho_band=float(inside.mean()),
        rows=rows,
    )


# ===========================================================================
# Persistence. DDL lives here rather than in src/db.py so this module can be added,
# reviewed and dropped without touching a shared file.
# ===========================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS basis_risk_empirical (
    pair            TEXT NOT NULL,     -- SCO-RP | ECO-RP | ... (PAIR_SPECS key)
    grain           TEXT NOT NULL,     -- national | crop | state | county
    crop            TEXT NOT NULL,     -- '' at national grain
    state           TEXT NOT NULL,     -- '' above state grain
    county_fips     TEXT NOT NULL,     -- '' above county grain
    coverage_level  REAL NOT NULL,     -- 0 = every coverage level pooled
    band            TEXT,              -- basis_risk_county band this maps onto, if any
    year_min        INTEGER,
    year_max        INTEGER,
    n_years         INTEGER,
    n_cells         INTEGER,
    n_counties      INTEGER,
    -- ---- exposure ----------------------------------------------------------
    ind_policies_earning      REAL,
    ind_policies_indemnified  REAL,    -- the observed farm losses: the denominator
    ind_indemnity   REAL,
    ind_premium     REAL,
    area_indemnity  REAL,
    area_premium    REAL,
    ind_acres       REAL,
    area_acres      REAL,
    participation   REAL,              -- area_acres / ind_acres
    -- ---- THE OBSERVED MISS -------------------------------------------------
    miss_policy     REAL,              -- HEADLINE: share of indemnified policies in a no-fire cell
    miss_policy_ci_lo REAL,            -- year-block bootstrap; the honest interval
    miss_policy_ci_hi REAL,
    miss_dollar     REAL,
    miss_cell       REAL,
    windfall_rate   REAL,
    p_ind_loss      REAL,
    p_area_fires_cell REAL,
    ind_loss_ratio  REAL,
    area_loss_ratio REAL,
    corr_lr_within_county REAL,
    -- ---- calibration -------------------------------------------------------
    implied_rho     REAL,              -- rho that reproduces miss_policy IN THE MODEL
    implied_rho_lo  REAL,
    implied_rho_hi  REAL,
    -- ---- the simulated comparator, where one exists -------------------------
    sim_miss_rate   REAL,
    sim_miss_rate_rho_lo REAL,
    sim_miss_rate_rho_hi REAL,
    source          TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (pair, grain, crop, state, county_fips, coverage_level)
);
CREATE INDEX IF NOT EXISTS idx_basis_risk_empirical_grain
    ON basis_risk_empirical (grain, pair, crop);
"""


def init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


UPSERT_COLUMNS = (
    "pair", "grain", "crop", "state", "county_fips", "coverage_level", "band",
    "year_min", "year_max", "n_years", "n_cells", "n_counties",
    "ind_policies_earning", "ind_policies_indemnified", "ind_indemnity", "ind_premium",
    "area_indemnity", "area_premium", "ind_acres", "area_acres", "participation",
    "miss_policy", "miss_policy_ci_lo", "miss_policy_ci_hi", "miss_dollar", "miss_cell",
    "windfall_rate", "p_ind_loss", "p_area_fires_cell", "ind_loss_ratio", "area_loss_ratio",
    "corr_lr_within_county", "implied_rho", "implied_rho_lo", "implied_rho_hi",
    "sim_miss_rate", "sim_miss_rate_rho_lo", "sim_miss_rate_rho_hi", "source", "fetched_at",
)


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[Sequence]) -> int:
    cols = ", ".join(UPSERT_COLUMNS)
    marks = ", ".join("?" * len(UPSERT_COLUMNS))
    rows = list(rows)
    conn.executemany(f"INSERT OR REPLACE INTO basis_risk_empirical ({cols}) VALUES ({marks})",
                     rows)
    conn.commit()
    return len(rows)


def row_for(
    emp: EmpiricalMiss,
    *,
    pair: str,
    grain: str,
    crop: str = "",
    state: str = "",
    county_fips: str = "",
    coverage_level: float = 0.0,
    band: str | None = None,
    ci: tuple[float, float] = (float("nan"), float("nan")),
    rho: tuple[float | None, float | None, float | None] = (None, None, None),
    sim: tuple[float | None, float | None, float | None] = (None, None, None),
    source: str = "sob_sales + basisrisk_empirical",
    fetched_at: str = "",
) -> tuple:
    """Flatten one EmpiricalMiss into the `basis_risk_empirical` column order."""
    part = (emp.area_acres / emp.ind_acres) if emp.ind_acres > 0 else None
    return (
        pair, grain, crop, state, county_fips, float(coverage_level), band,
        emp.year_min, emp.year_max, emp.n_years, emp.n_cells, emp.n_counties,
        emp.ind_policies_earning, emp.ind_policies_indemnified, emp.ind_indemnity,
        emp.ind_premium, emp.area_indemnity, emp.area_premium, emp.ind_acres, emp.area_acres,
        part,
        emp.miss_policy, ci[0], ci[1], emp.miss_dollar, emp.miss_cell,
        emp.windfall_rate, emp.p_ind_loss, emp.p_area_fires_cell,
        emp.ind_loss_ratio, emp.area_loss_ratio, emp.corr_lr_within_county,
        rho[0], rho[1], rho[2], sim[0], sim[1], sim[2], source, fetched_at,
    )
