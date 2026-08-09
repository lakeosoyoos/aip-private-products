"""LGM (plan 82) deductible ladder, MEASURED against realized margins instead of computed.

src/lgm.py ends its data section with a claim this module exists to retract:

    "Realized loss ratio by deductible ... does not exist in any public RMA file: sobtpu
     reports Coverage Level as .0000 for every plan-82 row from crop year 2008 forward.
     Everything in s2 is therefore forward-looking, computed off RMA's own rate draws, and
     cannot be backtested."

The first sentence is true and the conclusion does not follow.  sobtpu is the wrong file.
LGM's OWN actuarial record, ``A00600 LgmGrossMargin``, publishes both sides of the
settlement:

    Month2..Month11 Expected Gross Margin Amount    what the guarantee was struck on
    Month2..Month11 Actual   Gross Margin Amount    what the margin turned out to be

so the indemnity is RECONSTRUCTIBLE with no modelling at all, at any deductible, whether or
not a producer ever bought that rung:

    GMG(d)       = EGM - d * sum_m h(m)                     (RMA Step 1b, src/lgm.py)
    AGM          = sum_m actual(m) * h(m)
    indemnity(d) = MAX(0, GMG(d) - AGM)

This is structurally the same problem src/drpopt.py solves against ``drp_actual_price``, and
this module mirrors its idioms deliberately: pure scoring first, one observation per settled
period rather than per re-quote, everything normalized per unit of exposure, and every
independence compromise named in the docstring rather than buried.

=============================================================================
1. WHAT THE ARCHIVE ACTUALLY HOLDS  (establish this before believing any number)
=============================================================================
RMA publishes the LGM files under the same tree src/drpdata.py harvests for DRP,
``pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{RY}/``, as
``{RY}_ADMLivestockLgm_Daily_{YYYYMMDD}.zip``.  The tree carries **RY2014 through RY2027**
— 648 files, of which 641 are readable (the seven that are not are each the first file of
a reinsurance year, RY2015-RY2020, and are zero-padded with no end-of-central-directory
record; they are skipped, not worked around).

THE ACTUAL COLUMNS ARE POPULATED, BUT ONLY IN LATER FILES.  This is the single assumption
the whole exercise rests on, so it is worth being exact about how the file behaves:

  * A file published DURING the sales window is forward-looking.  Its Actual columns are
    blank except where an input leg's purchase month already lies in the past — for cattle
    the feeder-cattle and corn legs settle before the live-cattle leg, so a fresh file shows
    six actual feeder months and zero actual live-cattle months, and every value it does
    show equals the expected value.  A forward file therefore proves nothing either way.
  * RMA then BACK-FILLS.  After a marketing month settles it re-publishes the affected rows,
    with the same Sales Effective Date and the realized margin in the Actual columns, in a
    small delta file.  The back-fill continues for roughly a year past the end of the
    reinsurance year: RY2025's last delta landed 2026-06-12.

Merging every published file for a reinsurance year therefore yields fully settled
expected/actual pairs.  ``load_history()`` does that merge, taking the EARLIEST publication
of each expected vector (the at-sale guarantee) and the LATEST of each actual vector.

WHERE THE USABLE WINDOW STARTS, AND WHY IT IS NOT RY2014
--------------------------------------------------------
The A00600 layout changed twice.

    RY2014-RY2021   LONG   one row per Calendar Month Number, single Expected/Actual
                           column, and **no Sales Effective Date column at all**
    RY2022          LONG   Sales Effective Date added
    RY2023-RY2027   WIDE   Month2..Month11 Expected/Actual columns

The missing Sales Effective Date is fatal for RY2014-RY2021, not inconvenient.  A settled
back-fill row carries an expected vector and an actual vector but nothing that says which
sales date struck that guarantee, and a reinsurance year holds a dozen of them.  The
guarantee is the whole quantity under test, so this module refuses those years rather than
guessing which snapshot a row belongs to.  ``FIRST_BACKTESTABLE_RY`` is 2022.

That boundary is luckier than it looks.  LGM-Cattle and LGM-Swine carried 0% subsidy in the
Summary of Business through 2019 (docs/lgm.md s3.2); RY2022 sales begin July 2021.  So the
window that is mechanically recoverable is also, to within one year, exactly the subsidised
era — a longer window would have blended two economically different products.  The cost is
that the unsubsidised era cannot be measured here at all, only excluded.

=============================================================================
2. THE MARKETING-MONTH STRUCTURE IS RECOVERABLE, AND IT IS NOT ONE MONTH
=============================================================================
An LGM insurance period is a BUNDLE.  The ADM publishes the bundle explicitly: months 2..11
for cattle and dairy, months 2..6 for swine (src/lgm.INSURED_MONTHS), month 1 never insured.
Verified from the data rather than assumed — swine rows populate five months and stop, and
cattle/dairy rows populate ten.

What the ADM does NOT publish is the producer's declared weights h(m); those are a purchase
decision, not an actuarial fact.  This module therefore scores the NEUTRAL plan, equal
target marketings in every insurable month, exactly as src/lgm.deductible_curve does.  That
is an assumption and it is load-bearing in one direction: an equal-weight plan is POOLED, so
the subsidy applies at every rung.  A single-month plan is unpooled and unsubsidised at
every rung (src/lgm.subsidy_rate(pooled=False)), which no deductible can repair.  Any
producer running a genuinely lumpy plan should re-run ``realised_curve`` with their own
h(m); the function takes it as an argument for that reason.

=============================================================================
3. WHAT AN OBSERVATION IS  (the number that governs how much to believe)
=============================================================================
Three collapses have to happen, and each one shrinks the sample:

  1. STATE IS NOT A DIMENSION.  Every LGM margin is a CME futures construction, and the
     published margins are IDENTICAL in all 50 states — verified cell for cell on every
     sales date sampled, for all three commodities.  So the "50 / 50 states agreeing" in
     docs/lgm.md s2.2 is one observation printed fifty times, and this module carries a
     single national series.  ``collapse_states()`` asserts the identity rather than
     assuming it, and raises if a future file ever breaks it.

  2. SALES DATES WITHIN A MONTH ARE RE-QUOTES OF ONE OUTCOME.  From RY2022 the ADM carries
     weekly (Thursday) sales dates, ~51 a year.  Every sales date in a calendar month
     insures the SAME marketing months and therefore settles against an identical actual
     vector — verified: all four or five Thursdays of a month share one actual vector, and
     consecutive months' vectors are the same series shifted by one.  Counting them
     separately would inflate n by ~4x with no new information.  So, exactly as
     drpopt.observations does for DRP quarters, each (reinsurance year, sales month)
     contributes ONE observation, taken by default at the LAST sales date of the month
     (``lead="last"`` — the best-informed purchase, and the traditional LGM sales close).

  3. CONSECUTIVE MONTHLY PERIODS OVERLAP.  This is worse than DRP, where quarters abut.  A
     ten-month LGM period sold in January shares nine of its ten marketing months with the
     period sold in February.  Monthly observations are therefore heavily autocorrelated,
     and a t-test over them would be nonsense.  ``independent_blocks()`` takes every
     len(months)-th period so no two share a marketing month, and every summary this module
     prints reports BOTH counts.  For the RY2022-RY2026 window that is roughly 58 overlapping
     monthly periods and **six** non-overlapping ones per commodity/type.  Six.  Read every
     conclusion here against that number.

=============================================================================
4. PREMIUM, AND WHY IT STILL COMES FROM THE DRAWS
=============================================================================
The indemnity is measured; the premium cannot be, because RMA publishes no plan-82 rate
table and sobtpu's plan-82 rows carry no deductible.  Premium is therefore recomputed with
RMA's own Steps 1-7 from the ``A00610 LgmDraw`` member OF THE SAME SALES DATE — not a
proxy year, unlike drpopt's deliberate reuse of one draw year.  That keeps the loss ratio
honest: numerator realized, denominator RMA's own published rating for that day.

Consequence to keep in view: a loss ratio here is realized-indemnity over RMA-rated-premium
for the neutral marketing plan, which is what "was this rung correctly priced" means.  It is
NOT the book loss ratio in the Summary of Business, which blends whatever deductibles and
marketing plans producers actually chose.

The draw file has three dialects and ``draw_matrix()`` handles all three:

    RY<=2022        generic MonthN columns; component commodities split across rows by
                    Market Symbol Code
    RY2023-RY2024   generic MonthN for composite commodities, prefixed leg columns
                    ("Corn ", "Dairy ", "SoyM ") for dairy on one row
    RY2025+         prefixed leg columns for cattle ("Live Cattle ", "Feeder Cattle ",
                    "Corn ") and dairy, generic Month2..Month6 for swine

Which shape applies is decided from the A00600 side — whether that commodity publishes a
Market Symbol Code — never from the reinsurance year, so a fourth dialect will not silently
mis-read.  ``validate_draws()`` checks the assembled draw mean against RMA's own published
expected margin, the same check src/lgm.py's docstring records.

=============================================================================
5. THE SUBSIDY LADDER DID NOT MOVE ACROSS THE WINDOW  [V]
=============================================================================
docs/lgm.md records the plan-82 A00070 ladder as identical in RY2026 and RY2027.  It is
identical in RY2022, RY2023, RY2024 and RY2025 too — pulled from each year's
``{RY}_ADM_YTD.zip`` and compared value for value across all 48 rungs and all three
commodities.  So no part of a measured optimum moving over this window can be attributed to
a subsidy change; the ladder is a constant of the experiment.

CLI:
    .venv/bin/python -m src.lgmbacktest --harvest --years 2022-2026
    .venv/bin/python -m src.lgmbacktest --ladder --commodity 0803
    .venv/bin/python -m src.lgmbacktest --ladder --by-year
    .venv/bin/python -m src.lgmbacktest --validate
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import re
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from . import config
from .lgm import (COMMODITY_NAMES, COMMODITY_UNIT, DECLARED_RATION, INSURED_MONTHS,
                  LIVESTOCK_BASE, PLAN_CODE, TYPE_NAMES, Ration, composite_margin,
                  deductible_grid, expected_total_gross_margin, gross_margin_guarantee,
                  is_pooled, premium_stderr, return_per_producer_dollar, simulated_losses,
                  simulated_total_gross_margins, subsidy_rate, total_premium_from_losses,
                  uniform_marketings)

# Where the harvested members live. Both directories are pure cache: everything in them is
# re-derivable from pubfs with --harvest, and nothing else in the repo reads them.
HISTORY_DIR = config.CACHE_DIR / "lgm" / "history"
DRAWS_DIR = config.CACHE_DIR / "lgm" / "history_draws"

# RY2022 is the first year whose A00600 carries Sales Effective Date. See the docstring.
FIRST_BACKTESTABLE_RY = 2022
ARCHIVE_FIRST_RY = 2014

_FILE_RE = re.compile(r"(\d{4})_ADMLivestockLgm_Daily_(\d{8})\.zip")
_MEMBER_RE = re.compile(r"(\d{4})_ADMLivestockLgm_Daily_(\d{8})_(A00600|A00610)\.txt\.gz")

# Market Symbol Code -> the column prefix the draw file uses for that leg. Mirrors
# src.lgm.COMPONENT_LEGS, which maps the same pairing the other way round.
DRAW_PREFIX = {"LE": "Live Cattle ", "GF": "Feeder Cattle ", "C": "Corn ",
               "DA": "Dairy ", "SM": "SoyM "}
# Market Symbol Code -> the ration field that scales it. 'output' legs enter positive.
SYMBOL_LEG = {"LE": "output", "GF": "feeder", "C": "corn", "DA": "output", "SM": "soybean_meal"}


# ---------------------------------------------------------------------------
# The wording the LGM tab and src/lgm.py should now carry (neither file is ours)
# ---------------------------------------------------------------------------
# Same device src.lgm.SOB_GATE_NOTE uses: the change belongs in a file this module does not
# own, so the exact replacement text lives here with a test asserting it stays accurate.
LGM_TAB_NOTE = """\
src/lgm.py's module docstring (section 4, "DATA THIS REPO CANNOT SEE") and docs/lgm.md
s5.4 both say the deductible ladder cannot be backtested. The premise is right and the
conclusion is wrong, and the correction is a replacement rather than an addition.

REPLACE, in src/lgm.py section 4 and in the LGM tab's caption:

    "sobtpu publishes Coverage Level as .0000 for every plan-82 row from crop year 2008
     forward, so realized loss ratio BY DEDUCTIBLE does not exist in any public file.
     Deductible-level economics in this module are therefore forward-looking (computed off
     RMA's rate draws), never backtested."

WITH:

    "sobtpu publishes Coverage Level as .0000 for every plan-82 row, so realized loss ratio
     by deductible cannot come from the Summary of Business. It does not have to: ADM
     A00600 LgmGrossMargin publishes Month2..Month11 ACTUAL Gross Margin Amount alongside
     the expected columns, back-filled after each marketing month settles, so the indemnity
     at every filed deductible is reconstructible with no modelling. src/lgmbacktest.py
     does that for RY2022-RY2026, the span whose A00600 carries a Sales Effective Date.

     Measured on 312 settled monthly insurance periods (equal target marketings in every
     insurable month), the forward-looking optimum holds for SWINE ($10/head, in every
     sub-window tested) and does NOT hold elsewhere. LGM-Dairy's measured optimum sits
     BELOW $1.00/cwt in every window tested ($0.10-$0.80), because the realized loss ratio
     falls from 1.17 at a $0 deductible to 0.53 at $2.00 while the rated model assumes it
     is flat at 1/1.03. LGM-Cattle paid NOTHING at any deductible of $60/head or more in
     five reinsurance years, so the recommended $70 rung returned zero cents on the
     producer dollar; every rung lost money and the loss shrinks monotonically with the
     deductible, which is a way of saying the product should not have been bought.

     Read all of that against the sample it rests on: the margins are national, so the 50
     states are one observation, and consecutive monthly periods share nine of their ten
     marketing months. There are 51-57 monthly periods and only 6-11 NON-OVERLAPPING ones
     per commodity and type. The swine result is stable across sub-windows; the dairy level
     is not (only its direction is); the cattle result is a statement about an extraordinary
     2021-2026 cattle-margin regime, not about how LGM-Cattle is rated forever."

Do not simply append this. Leaving "cannot be backtested" in place next to a backtest is
worse than either sentence alone.
"""


# ---------------------------------------------------------------------------
# Parsing: one normalized shape out of two A00600 layouts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GrossMarginRow:
    """One A00600 row, normalized across the LONG and WIDE layouts.

    `expected` and `actual` are month-indexed lists positioned by INSURED_MONTHS' 2..11
    convention, so index 0 is month 2. None means the file left the cell blank, which is
    RMA's encoding for 'not published', never zero.
    """
    reinsurance_year: int
    commodity_code: str
    type_code: str
    state_code: str
    market_symbol: str
    sales_effective_date: str
    expected: tuple[float | None, ...]
    actual: tuple[float | None, ...]

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (self.commodity_code, self.type_code, self.state_code,
                self.market_symbol, self.sales_effective_date)


ALL_MONTHS = tuple(range(2, 12))


def _num(v: str | None) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_gross_margin(text: str, *, file_stamp: str | None = None) -> list[GrossMarginRow]:
    """Parse an A00600 member in EITHER layout into GrossMarginRow.

    The WIDE layout (RY2023+) carries Month2..Month11 columns on one row.  The LONG layout
    (RY2022 and earlier) carries one row per Calendar Month Number, so its rows are folded
    together on everything except the month.

    `file_stamp` is used as the sales effective date only when the file has no such column,
    which happens for RY2021 and earlier.  Those years are not backtestable (see the module
    docstring) — the fallback exists so the archive can still be INSPECTED, and
    `settled_periods` refuses them explicitly rather than letting a file stamp masquerade as
    a sales date.
    """
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    if not rows:
        return []
    wide = "Month2 Expected Gross Margin Amount" in rows[0]
    acc: dict[tuple, tuple[list, list, int]] = {}
    for r in rows:
        if str(r.get("Insurance Plan Code", "")).strip() != PLAN_CODE:
            continue
        ry = int(str(r.get("Reinsurance Year") or 0).strip() or 0)
        sed = (r.get("Sales Effective Date") or file_stamp or "").strip()
        k = (ry, r["Commodity Code"].strip(), r["Type Code"].strip(),
             r["State Code"].strip(), (r.get("Market Symbol Code") or "").strip(), sed)
        e, a, _ = acc.setdefault(k, ([None] * 10, [None] * 10, 0))
        if wide:
            for i, m in enumerate(ALL_MONTHS):
                e[i] = _num(r.get(f"Month{m} Expected Gross Margin Amount"))
                a[i] = _num(r.get(f"Month{m} Actual Gross Margin Amount"))
        else:
            m = int(_num(r.get("Calendar Month Number")) or 0)
            if m not in ALL_MONTHS:
                continue
            e[m - 2] = _num(r.get("Expected Gross Margin Amount"))
            a[m - 2] = _num(r.get("Actual Gross Margin Amount"))
    return [GrossMarginRow(k[0], k[1], k[2], k[3], k[4], k[5], tuple(e), tuple(a))
            for k, (e, a, _) in acc.items()]


# ---------------------------------------------------------------------------
# Merging the whole archive for a reinsurance year
# ---------------------------------------------------------------------------

@dataclass
class MergedRow:
    """One (commodity, type, state, leg, sales date) across every file that published it."""
    expected: list[float | None] = field(default_factory=lambda: [None] * 10)
    actual: list[float | None] = field(default_factory=lambda: [None] * 10)
    first_seen: str = ""
    last_seen: str = ""

    @property
    def settled(self) -> bool:
        """Every month with a published guarantee also has a published settlement."""
        pub = [i for i, v in enumerate(self.expected) if v is not None]
        return bool(pub) and all(self.actual[i] is not None for i in pub)

    @property
    def months(self) -> tuple[int, ...]:
        return tuple(ALL_MONTHS[i] for i, v in enumerate(self.expected) if v is not None)


def merge_rows(batches: Iterable[tuple[str, Sequence[GrossMarginRow]]],
               ) -> dict[tuple[str, str, str, str, str], MergedRow]:
    """Fold every published snapshot into one settled record per key.

    `batches` is (file stamp, rows) in ANY order; the fold is order-independent because it
    keeps the earliest expected value and the latest actual value explicitly rather than
    relying on iteration order.  That matters: RMA's delta files are not strictly monotone
    in what they re-publish, and a later file re-states the ORIGINAL expected vector
    alongside the new actuals.

    EXPECTED takes the EARLIEST publication because that is the guarantee the producer
    bought.  ACTUAL takes the LATEST because settlement is revised into place.
    """
    out: dict[tuple[str, str, str, str, str], MergedRow] = {}
    for stamp, rows in batches:
        for r in rows:
            m = out.setdefault(r.key, MergedRow())
            if not m.first_seen or stamp < m.first_seen:
                m.first_seen = stamp
            if stamp > m.last_seen:
                m.last_seen = stamp
            for i in range(10):
                if r.expected[i] is not None and (m.expected[i] is None
                                                  or stamp <= m.first_seen):
                    m.expected[i] = r.expected[i]
                if r.actual[i] is not None and stamp >= m.last_seen:
                    m.actual[i] = r.actual[i]
    return out


def history_files(reinsurance_year: int, root: Path | None = None) -> list[Path]:
    root = root or HISTORY_DIR
    if not root.exists():
        return []
    return sorted(p for p in root.glob(f"{reinsurance_year}_*_A00600.txt.gz"))


@lru_cache(maxsize=8)
def _cached_text(path_str: str, mtime: float) -> str:
    """Gunzip one harvested member, memoized on (path, mtime).

    The draw members are ~30 MB each and a whole-window sweep re-reads the same handful of
    them hundreds of times; the mtime in the key means an edited cache file is still picked
    up.  Small maxsize on purpose — these are large strings.
    """
    return gzip.decompress(Path(path_str).read_bytes()).decode("utf-8", "replace")


def _read_member(p: Path) -> str:
    return _cached_text(str(p), p.stat().st_mtime)


@lru_cache(maxsize=32)
def _load_history_cached(reinsurance_year: int, root_str: str | None):
    root = Path(root_str) if root_str else None
    batches = []
    for p in history_files(reinsurance_year, root):
        m = _MEMBER_RE.match(p.name)
        stamp = m.group(2) if m else ""
        text = gzip.decompress(p.read_bytes()).decode("utf-8", "replace")
        batches.append((stamp, parse_gross_margin(text, file_stamp=stamp)))
    return merge_rows(batches)


def load_history(reinsurance_year: int, root: Path | None = None,
                 ) -> dict[tuple[str, str, str, str, str], MergedRow]:
    """Merge every harvested A00600 snapshot for one reinsurance year.

    Memoized: a window sweep loads the same year four or five times, and the merge walks
    every one of the ~100 files a year publishes.  The result is treated as READ-ONLY by
    everything downstream (`collapse_states` and `settled_periods` both copy or re-key
    rather than mutate), so sharing it is safe.
    """
    return _load_history_cached(reinsurance_year, str(root) if root else None)


# ---------------------------------------------------------------------------
# State collapse — the first thing that shrinks n
# ---------------------------------------------------------------------------

class StateDivergence(RuntimeError):
    """Raised when LGM margins stop being national. Never seen; the check is the point."""


def collapse_states(merged: dict[tuple[str, str, str, str, str], MergedRow],
                    ) -> tuple[dict[tuple[str, str, str, str], MergedRow], int]:
    """Drop the state dimension, asserting first that it carries no information.

    Returns (keyed without state, number of states collapsed).  LGM margins are CME futures
    constructions with no state basis, so all 50 state rows of a (commodity, type, leg,
    sales date) are byte-identical — but that is an empirical fact about RMA's files, not a
    theorem, so it is checked on every key and raises rather than silently averaging.
    """
    grouped: dict[tuple[str, str, str, str], dict[str, MergedRow]] = defaultdict(dict)
    for (cc, tc, sc, sym, sed), row in merged.items():
        grouped[(cc, tc, sym, sed)][sc] = row
    out: dict[tuple[str, str, str, str], MergedRow] = {}
    states: set[str] = set()
    for k, by_state in grouped.items():
        states.update(by_state)
        vals = {(tuple(r.expected), tuple(r.actual)) for r in by_state.values()}
        if len(vals) > 1:
            raise StateDivergence(
                f"{k} differs across states ({len(vals)} distinct margin vectors); "
                "LGM margins were national when this module was written")
        out[k] = next(iter(by_state.values()))
    return out, len(states)


# ---------------------------------------------------------------------------
# Settled periods: the observation unit
# ---------------------------------------------------------------------------

@dataclass
class SettledPeriod:
    """One (reinsurance year, commodity, type, sales date) whose margins have all settled.

    `expected` and `actual` are composite gross margins PER UNIT OF EXPOSURE (per head for
    cattle and swine, per cwt of milk for dairy), in `months` order.
    """
    reinsurance_year: int
    commodity_code: str
    type_code: str
    sales_effective_date: str
    months: tuple[int, ...]
    expected: np.ndarray
    actual: np.ndarray
    ration: Ration | None
    legs: tuple[str, ...] = ()          # market symbols assembled, () when composite

    @property
    def sales_month(self) -> str:
        return self.sales_effective_date[:6]

    @property
    def commodity_type(self) -> tuple[str, str]:
        return (self.commodity_code, self.type_code)


def _assemble(rows_by_symbol: dict[str, MergedRow], ration: Ration | None,
              ) -> tuple[tuple[int, ...], np.ndarray, np.ndarray, tuple[str, ...]] | None:
    """Composite expected/actual margin from either a whole row or a set of component legs.

    A composite commodity publishes one row with a blank Market Symbol Code and the margin
    already netted of feed.  A component commodity publishes one row per leg carrying that
    leg's PRICE, and the margin is assembled with the declared ration — the same arithmetic
    src.lgm.composite_margin does, reused rather than re-derived so the two cannot drift.
    """
    if "" in rows_by_symbol:
        row = rows_by_symbol[""]
        idx = [i for i in range(10)
               if row.expected[i] is not None and row.actual[i] is not None]
        if not idx:
            return None
        months = tuple(ALL_MONTHS[i] for i in idx)
        return (months,
                np.array([row.expected[i] for i in idx], float),
                np.array([row.actual[i] for i in idx], float), ())
    if ration is None:
        return None
    legs = {SYMBOL_LEG[s]: r for s, r in rows_by_symbol.items() if s in SYMBOL_LEG}
    if len(legs) != len(rows_by_symbol):
        return None
    exp = composite_margin({leg: list(r.expected) for leg, r in legs.items()}, ration)
    act = composite_margin({leg: list(r.actual) for leg, r in legs.items()}, ration)
    idx = [i for i in range(10) if exp[i] is not None and act[i] is not None]
    if not idx:
        return None
    return (tuple(ALL_MONTHS[i] for i in idx),
            np.array([exp[i] for i in idx], float),
            np.array([act[i] for i in idx], float),
            tuple(sorted(rows_by_symbol)))


def settled_periods(reinsurance_year: int, root: Path | None = None,
                    ) -> list[SettledPeriod]:
    """Every fully settled insurance period of one reinsurance year, states collapsed.

    Refuses reinsurance years whose A00600 carries no Sales Effective Date: without it the
    guarantee cannot be attached to the purchase that struck it, and the guarantee is the
    quantity under test.
    """
    if reinsurance_year < FIRST_BACKTESTABLE_RY:
        raise ValueError(
            f"RY{reinsurance_year} A00600 has no Sales Effective Date column; the earliest "
            f"backtestable reinsurance year is RY{FIRST_BACKTESTABLE_RY}. "
            "See src/lgmbacktest.py s1.")
    national, _ = collapse_states(load_history(reinsurance_year, root))
    grouped: dict[tuple[str, str, str], dict[str, MergedRow]] = defaultdict(dict)
    for (cc, tc, sym, sed), row in national.items():
        if row.settled:
            grouped[(cc, tc, sed)][sym] = row

    out: list[SettledPeriod] = []
    for (cc, tc, sed), by_sym in sorted(grouped.items()):
        want = INSURED_MONTHS.get(cc, ALL_MONTHS)
        built = _assemble(by_sym, DECLARED_RATION.get((cc, tc)))
        if built is None:
            continue
        months, exp, act, legs = built
        keep = [i for i, m in enumerate(months) if m in want]
        if len(keep) != len(want):
            continue           # a partly published period is not a settled period
        out.append(SettledPeriod(reinsurance_year, cc, tc, sed,
                                 tuple(months[i] for i in keep), exp[keep], act[keep],
                                 DECLARED_RATION.get((cc, tc)), legs))
    return out


def one_per_sales_month(periods: Sequence[SettledPeriod], *, lead: str = "last",
                        ) -> list[SettledPeriod]:
    """Collapse weekly re-quotes to one observation per (commodity, type, sales month).

    The DRP analogue is drpopt.observations' one-row-per-settled-quarter rule, and the
    reason is identical: every sales date in a month insures the same marketing months and
    settles against the same actual margins, so counting them separately multiplies n
    without adding a single new outcome.  `lead="last"` takes the best-informed purchase —
    the last Thursday of the month, which is also LGM's traditional sales close;
    `lead="first"` takes the earliest quote of the month.
    """
    if lead not in ("last", "first"):
        raise ValueError(f"lead must be 'last' or 'first', got {lead!r}")
    picked: dict[tuple[str, str, str], SettledPeriod] = {}
    for p in periods:
        k = (p.commodity_code, p.type_code, p.sales_month)
        cur = picked.get(k)
        if cur is None:
            picked[k] = p
        elif lead == "last":
            if p.sales_effective_date > cur.sales_effective_date:
                picked[k] = p
        elif p.sales_effective_date < cur.sales_effective_date:
            picked[k] = p
    return [picked[k] for k in sorted(picked)]


def independent_blocks(periods: Sequence[SettledPeriod]) -> list[SettledPeriod]:
    """The subset in which no two periods share a marketing month.

    Monthly LGM periods overlap in all but one of their marketing months, so a run of
    monthly observations is one long autocorrelated series, not a sample.  Stepping by
    len(months) leaves periods that are genuinely disjoint in the underlying futures
    outcomes.  This is the count any claim about the ladder should be read against; it is
    small, and saying so is the point.
    """
    out: list[SettledPeriod] = []
    for (cc, tc), group in sorted(_by_commodity_type(periods).items()):
        group = sorted(group, key=lambda p: p.sales_effective_date)
        step = max(1, len(group[0].months)) if group else 1
        out.extend(group[::step])
    return out


def _by_commodity_type(periods: Sequence[SettledPeriod],
                       ) -> dict[tuple[str, str], list[SettledPeriod]]:
    d: dict[tuple[str, str], list[SettledPeriod]] = defaultdict(list)
    for p in periods:
        d[p.commodity_type].append(p)
    return d


# ---------------------------------------------------------------------------
# Draws (premium denominator)
# ---------------------------------------------------------------------------

def draw_path(reinsurance_year: int, sales_effective_date: str,
              root: Path | None = None) -> Path:
    root = root or DRAWS_DIR
    return (root / f"{reinsurance_year}_ADMLivestockLgm_Daily_"
                   f"{sales_effective_date}_A00610.txt.gz")


def index_draw_rows(text: str, state_code: str,
                    ) -> dict[tuple[str, str], list[dict[str, str]]]:
    """One A00610 member -> {(commodity, type): rows} for a single state.

    Split out of `draw_matrix` purely so a whole-window sweep parses each 30 MB member
    once instead of once per commodity: the file is national (verified — every state's
    draws are byte-identical), so a single state's slice is all anyone needs.
    """
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in csv.DictReader(io.StringIO(text), delimiter="|"):
        if str(r.get("Insurance Plan Code", "")).strip() != PLAN_CODE:
            continue
        if r["State Code"].strip() != state_code:
            continue
        out[(r["Commodity Code"].strip(), r["Type Code"].strip())].append(r)
    return dict(out)


def draw_matrix(text: str, commodity_code: str, type_code: str, state_code: str,
                months: Sequence[int], ration: Ration | None,
                legs: Sequence[str] = ()) -> np.ndarray | None:
    """(n_draws, n_months) composite margin draws out of an A00610 member."""
    rows = index_draw_rows(text, state_code).get((commodity_code, type_code), [])
    return draw_matrix_from_rows(rows, months, ration, legs)


def draw_matrix_from_rows(rows: Sequence[dict[str, str]], months: Sequence[int],
                          ration: Ration | None,
                          legs: Sequence[str] = ()) -> np.ndarray | None:
    """(n_draws, n_months) composite margin draws for one (commodity, type, state).

    Three dialects, resolved by what the A00600 side said rather than by year (see s4 of
    the module docstring).  `legs` empty means the commodity publishes a composite margin,
    so the generic MonthN columns are read straight; otherwise each leg is read from its
    prefixed columns when the file has them and from the generic columns on that leg's own
    Market Symbol row when it does not, then combined with the ration.
    """
    if not rows:
        return None

    def series(row: dict[str, str], prefix: str) -> list[float | None]:
        return [_num(row.get(f"{prefix}Month{m} Margin Draw Amount")) for m in months]

    def draw_no(row: dict[str, str]) -> int:
        return int(_num(row.get("Margin Draw Number")) or 0)

    if not legs:
        plain = sorted((r for r in rows if not (r.get("Market Symbol Code") or "").strip()),
                       key=draw_no)
        if not plain:
            return None
        mat = np.array([series(r, "") for r in plain], dtype=float)
        return None if np.isnan(mat).any() else mat

    if ration is None:
        return None
    has_prefix = any(f"{DRAW_PREFIX[s]}Month{months[0]} Margin Draw Amount" in rows[0]
                     for s in legs if s in DRAW_PREFIX)
    per_leg: dict[str, np.ndarray] = {}
    for sym in legs:
        leg = SYMBOL_LEG.get(sym)
        if leg is None:
            return None
        if has_prefix:
            src = sorted(rows, key=draw_no)
            arr = np.array([series(r, DRAW_PREFIX[sym]) for r in src], dtype=float)
        else:
            src = sorted((r for r in rows
                          if (r.get("Market Symbol Code") or "").strip() == sym),
                         key=draw_no)
            if not src:
                return None
            arr = np.array([series(r, "") for r in src], dtype=float)
        if arr.size == 0 or np.isnan(arr).any():
            return None
        per_leg[leg] = arr
    n = {a.shape[0] for a in per_leg.values()}
    if len(n) != 1:
        return None
    out = np.zeros_like(next(iter(per_leg.values())))
    for leg, arr in per_leg.items():
        q = getattr(ration, {"output": "output_cwt", "feeder": "feeder_cwt",
                             "corn": "corn_bu", "soybean_meal": "soybean_meal_ton"}[leg],
                    None) or 0.0
        out += arr * q if leg == "output" else -arr * q
    return out


@lru_cache(maxsize=8)
def _draw_index(path_str: str, mtime: float, state_code: str):
    return index_draw_rows(_cached_text(path_str, mtime), state_code)


def load_draws(period: SettledPeriod, state_code: str = "19",
               root: Path | None = None) -> np.ndarray | None:
    """Composite draws for one settled period, or None when the member was not harvested."""
    p = draw_path(period.reinsurance_year, period.sales_effective_date, root)
    if not p.exists():
        return None
    rows = _draw_index(str(p), p.stat().st_mtime, state_code).get(
        (period.commodity_code, period.type_code), [])
    return draw_matrix_from_rows(rows, period.months, period.ration, period.legs)


def validate_draws(period: SettledPeriod, draws: np.ndarray) -> float:
    """Max relative gap between the assembled draw mean and RMA's published expected margin.

    The construction check src/lgm.py's docstring records, expressed as a number so it can
    be asserted.  A 500-draw mean will not equal the expected margin exactly; it should be
    within a couple of percent, and a mis-assembled ration or a mis-read column is off by
    orders of magnitude rather than by noise.
    """
    mean = np.asarray(draws, float).mean(axis=0)
    denom = np.where(np.abs(period.expected) < 1e-9, np.nan, np.abs(period.expected))
    return float(np.nanmax(np.abs(mean - period.expected) / denom))


# ---------------------------------------------------------------------------
# The measured ladder
# ---------------------------------------------------------------------------

@dataclass
class RealisedCell:
    """One deductible on one settled period. Realized numerator, RMA-rated denominator."""
    reinsurance_year: int
    commodity_code: str
    type_code: str
    sales_effective_date: str
    deductible: float
    subsidy: float
    egm: float
    gmg: float
    agm: float
    indemnity: float
    total_premium: float
    producer_premium: float
    net_realised: float
    premium_stderr: float
    pooled: bool
    n_draws: int

    @property
    def loss_ratio(self) -> float:
        return self.indemnity / self.total_premium if self.total_premium else 0.0

    @property
    def paid(self) -> bool:
        return self.indemnity > 0.0

    @property
    def guarantee_retained(self) -> float:
        return self.gmg / self.egm if self.egm else 0.0


def realised_indemnity(egm: float, agm: float, deductible: float,
                       marketings: Sequence[float]) -> float:
    """MAX(0, GMG - AGM) — the whole reconstruction, in one line and with no modelling.

    RMA Step 1b sets the guarantee; the actual gross margin replaces the simulated one that
    Step 3 uses for rating.  Nothing here is estimated: both sides come from published
    A00600 columns.
    """
    gmg = gross_margin_guarantee(egm, deductible, marketings)
    return max(0.0, round(gmg - float(agm), 2))


def realised_curve(period: SettledPeriod, draws: np.ndarray,
                   marketings: Sequence[float] | None = None, *,
                   table: dict[str, dict[float, float]] | None = None,
                   bfr_year: int | None = None) -> list[RealisedCell]:
    """Score EVERY filed deductible on one settled period.

    The counterfactual is the point: each rung is evaluated on the same history, so this is
    what each deductible WOULD have paid, not what the deductibles producers happened to buy
    did pay.  That also disposes of the selection problem the Summary of Business cannot —
    there is no election to condition on.
    """
    h = list(marketings) if marketings is not None else uniform_marketings(len(period.months))
    if len(h) != len(period.months):
        raise ValueError(f"marketings has {len(h)} months, period has {len(period.months)}")
    egm = expected_total_gross_margin(period.expected, h)
    agm = expected_total_gross_margin(period.actual, h)
    sgm = simulated_total_gross_margins(draws, h)
    pooled = is_pooled(h)
    out: list[RealisedCell] = []
    for d in deductible_grid(period.commodity_code, table):
        gmg = gross_margin_guarantee(egm, d, h)
        losses = simulated_losses(gmg, sgm)
        tp = total_premium_from_losses(losses)
        s = subsidy_rate(period.commodity_code, d, pooled=pooled, bfr_year=bfr_year,
                         table=table)
        pp = round(tp * (1.0 - s))
        ind = max(0.0, round(gmg - agm, 2))
        out.append(RealisedCell(
            reinsurance_year=period.reinsurance_year,
            commodity_code=period.commodity_code, type_code=period.type_code,
            sales_effective_date=period.sales_effective_date, deductible=d, subsidy=s,
            egm=egm, gmg=gmg, agm=agm, indemnity=ind, total_premium=float(tp),
            producer_premium=float(pp), net_realised=ind - pp,
            premium_stderr=premium_stderr(losses), pooled=pooled,
            n_draws=int(np.asarray(draws).shape[0])))
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class LadderRung:
    """One deductible pooled over a set of settled periods."""
    commodity_code: str
    type_code: str
    deductible: float
    subsidy: float
    n_periods: int
    n_paid: int
    total_premium: float
    producer_premium: float
    indemnity: float

    @property
    def loss_ratio(self) -> float:
        return self.indemnity / self.total_premium if self.total_premium else 0.0

    @property
    def net_realised(self) -> float:
        return self.indemnity - self.producer_premium

    @property
    def net_per_premium_dollar(self) -> float:
        """Net realized dollars per dollar of TOTAL premium.

        A SECONDARY display, not the ranking metric, and the distinction matters.  Total
        premium shrinks as the deductible rises, so dividing by it rewards high deductibles
        for being small rather than for being good.  Ranking is done on `net_realised`,
        which is the direct measured analogue of src.lgm.net_expected_gain — the same fixed
        marketing plan across every rung, so raw dollars ARE comparable rung to rung.  This
        ratio is here because it is the honest way to compare ACROSS commodities, where a
        $700/head cattle bundle and a $60/head swine bundle are not.
        """
        return self.net_realised / self.total_premium if self.total_premium else 0.0

    @property
    def return_per_producer_dollar(self) -> float:
        """loss ratio / (1 - subsidy) — this repo's cross-plan metric, on MEASURED experience.

        Note the trap docs/lgm.md s2.3 records: this is constant across a subsidy plateau,
        so it cannot rank rungs above the 0.50 cap.  Use net_per_premium_dollar there.
        """
        return return_per_producer_dollar(self.loss_ratio, self.subsidy)

    @property
    def pay_rate(self) -> float:
        return self.n_paid / self.n_periods if self.n_periods else 0.0


def pool(cells: Iterable[RealisedCell]) -> list[LadderRung]:
    """Sum realized indemnity and rated premium across periods, per deductible."""
    acc: dict[tuple[str, str, float], LadderRung] = {}
    for c in cells:
        k = (c.commodity_code, c.type_code, c.deductible)
        r = acc.get(k)
        if r is None:
            r = acc[k] = LadderRung(c.commodity_code, c.type_code, c.deductible,
                                    c.subsidy, 0, 0, 0.0, 0.0, 0.0)
        r.n_periods += 1
        r.n_paid += int(c.paid)
        r.total_premium += c.total_premium
        r.producer_premium += c.producer_premium
        r.indemnity += c.indemnity
    return [acc[k] for k in sorted(acc)]


def best_rung(rungs: Sequence[LadderRung],
              objective: str = "net") -> LadderRung:
    """The measured optimum under one objective. Ties break toward the LOWER deductible.

    objective='net'        maximise realized net DOLLARS on the same fixed marketing plan.
                           The measured analogue of src.lgm.optimal_deductible('gain'), and
                           the one the forward-looking table should be compared against.
    objective='per_dollar' maximise realized return per producer dollar. On RATED
                           experience this is blind across a subsidy plateau (docs/lgm.md
                           s2.3); on MEASURED experience it is not, because the realized
                           loss ratio varies rung to rung.
    objective='loss_ratio' maximise the realized loss ratio — 'which rung was RMA most
                           wrong about', ignoring who paid for it.

    Ties break toward the lower deductible because that rung retains more of the guarantee
    for the same score, which is the direction a producer should be nudged when the
    economics cannot tell two rungs apart.
    """
    if not rungs:
        raise ValueError("empty ladder")
    keys = {"net": lambda r: round(r.net_realised, 2),
            "per_dollar": lambda r: round(r.return_per_producer_dollar, 9),
            "loss_ratio": lambda r: round(r.loss_ratio, 9)}
    if objective not in keys:
        raise ValueError(f"unknown objective {objective!r}")
    return max(rungs, key=lambda r: (keys[objective](r), -r.deductible))


def is_degenerate(rungs: Sequence[LadderRung]) -> bool:
    """True when no rung paid anything, so 'the optimum' is not a meaningful statement.

    When realized indemnity is zero at every deductible the ladder is a pure cost schedule:
    net is -producer premium, which is monotone in the deductible, and the argmax is just
    'buy the least'.  Printing a rung there would dress up 'this product did not pay' as a
    recommendation, so callers check this first.
    """
    return all(r.indemnity <= 0.0 for r in rungs)


# ---------------------------------------------------------------------------
# Whole-window assembly
# ---------------------------------------------------------------------------

def forward_optimum(period: SettledPeriod, draws: np.ndarray,
                    marketings: Sequence[float] | None = None, *,
                    table: dict[str, dict[float, float]] | None = None) -> float:
    """The deductible src/lgm.py would have recommended on THIS period's own draws.

    The apples-to-apples counterpart to the measured optimum: same sales date, same
    marketing plan, same 500 draws — the only difference is that this one assumes the
    policy is rated to a loss ratio of 1/1.03 at every rung, and the measured one uses what
    the margin actually did.  Comparing the two isolates exactly the assumption under test.
    """
    from .lgm import deductible_curve, optimal_deductible
    h = list(marketings) if marketings is not None else uniform_marketings(len(period.months))
    curve = deductible_curve(period.commodity_code, period.type_code, "00",
                             period.expected, draws, h, table=table)
    return optimal_deductible(curve, "gain").deductible


@dataclass
class Backtest:
    years: tuple[int, ...]
    periods: list[SettledPeriod]
    cells: list[RealisedCell]
    skipped_no_draws: list[SettledPeriod] = field(default_factory=list)
    forward: dict[tuple[str, str, str], float] = field(default_factory=dict)

    @property
    def n_periods(self) -> int:
        return len(self.periods)

    def n_independent(self, commodity_code: str, type_code: str) -> int:
        got = [p for p in self.periods if p.commodity_type == (commodity_code, type_code)]
        return len(independent_blocks(got))

    def ladder(self, commodity_code: str | None = None, type_code: str | None = None,
               reinsurance_year: int | None = None) -> list[LadderRung]:
        sel = [c for c in self.cells
               if (commodity_code is None or c.commodity_code == commodity_code)
               and (type_code is None or c.type_code == type_code)
               and (reinsurance_year is None or c.reinsurance_year == reinsurance_year)]
        return pool(sel)


def run(years: Sequence[int], *, lead: str = "last", state_code: str = "19",
        marketings: Sequence[float] | None = None,
        table: dict[str, dict[float, float]] | None = None,
        root: Path | None = None, draws_root: Path | None = None,
        independent_only: bool = False) -> Backtest:
    """Backtest the whole ladder over a span of reinsurance years.

    Periods with no harvested draw member are SKIPPED and listed, never priced off another
    date's draws: LGM premium is a property of the day's futures strip, and substituting a
    neighbouring sales date would put a realized indemnity over a premium that was never
    quoted against it.
    """
    periods: list[SettledPeriod] = []
    for ry in years:
        periods.extend(settled_periods(ry, root))
    periods = one_per_sales_month(periods, lead=lead)
    if independent_only:
        periods = independent_blocks(periods)
    cells: list[RealisedCell] = []
    used: list[SettledPeriod] = []
    skipped: list[SettledPeriod] = []
    fwd: dict[tuple[str, str, str], float] = {}
    # Sorted by SALES DATE first so every commodity sharing a draw member is scored while
    # that member is still in the parse cache; one A00610 is ~30 MB inflated.
    for p in sorted(periods, key=lambda x: (x.reinsurance_year, x.sales_effective_date,
                                            x.commodity_code, x.type_code)):
        draws = load_draws(p, state_code, draws_root)
        if draws is None or draws.shape[1] != len(p.months):
            skipped.append(p)
            continue
        cells.extend(realised_curve(p, draws, marketings, table=table))
        fwd[(p.commodity_code, p.type_code, p.sales_effective_date)] = forward_optimum(
            p, draws, marketings, table=table)
        used.append(p)
    return Backtest(tuple(years), used, cells, skipped, fwd)


# ---------------------------------------------------------------------------
# Harvest (network) — everything above runs off the cache
# ---------------------------------------------------------------------------

def parse_listing(html: str, ry: int) -> list[str]:
    """LGM zip names for one reinsurance year out of a pubfs directory listing."""
    return sorted({m.group(0) for m in _FILE_RE.finditer(html)
                   if m.group(1) == str(ry)})


def _central_entry(read, total: int, want: str) -> tuple[int, int, int]:
    """(local header offset, compressed size, method) for a member, via HTTP range reads.

    The A00600 member is a few kilobytes inside a zip that is often forty megabytes, and the
    whole archive is 648 of them, so the member is located through the central directory and
    fetched on its own — the same range-read discipline src/drpdata.py uses on the ADM YTD
    zip.  Some first-of-year zips are zero-padded past the end-of-central-directory record,
    hence the widening search.
    """
    i, tail = -1, b""
    for shift in (16, 20, 24, 26):
        span = min(total, 1 << shift)
        tail = read(total - span, total - 1)
        i = tail.rfind(b"PK\x05\x06")
        if i >= 0:
            break
    if i < 0:
        raise RuntimeError("no end-of-central-directory record")
    cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
    cd = read(cd_off, cd_off + cd_size - 1)
    p = 0
    while p + 46 <= len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        meth = struct.unpack("<H", cd[p + 10:p + 12])[0]
        csize = struct.unpack("<I", cd[p + 20:p + 24])[0]
        nlen, elen, clen = struct.unpack("<HHH", cd[p + 28:p + 34])
        lho = struct.unpack("<I", cd[p + 42:p + 46])[0]
        if want in cd[p + 46:p + 46 + nlen].decode("utf-8", "replace"):
            return lho, csize, meth
        p += 46 + nlen + elen + clen
    raise RuntimeError(f"{want} not in the central directory")


def fetch_member(session, ry: int, filename: str, record: str, dest: Path, *,
                 timeout: int = 600) -> int:
    """Range-read one member out of one published zip and cache it gzipped."""
    url = LIVESTOCK_BASE.format(year=ry) + filename

    def read(a: int, b: int) -> bytes:
        r = session.get(url, headers={"Range": f"bytes={a}-{b}"}, timeout=timeout)
        r.raise_for_status()
        return r.content

    head = session.head(url, timeout=timeout)
    head.raise_for_status()
    total = int(head.headers["Content-Length"])
    lho, csize, meth = _central_entry(read, total, record)
    nlen, elen = struct.unpack("<HH", read(lho, lho + 29)[26:30])
    start = lho + 30 + nlen + elen
    raw = read(start, start + csize - 1)
    data = zlib.decompressobj(-15).decompress(raw) if meth == 8 else raw
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(gzip.compress(data, 6))
    return len(data)


def harvest(session, years: Sequence[int], *, draws: bool = True,
            root: Path | None = None, draws_root: Path | None = None,
            force: bool = False) -> dict[str, int]:
    """Cache every A00600 for the given years, plus the A00610 of each month's last sale.

    Split deliberately: the gross-margin members are tiny and ALL of them are needed (the
    settled actuals arrive in scattered delta files), while the draw members are ~30 MB each
    and only one per sales month is ever scored.
    """
    root = root or HISTORY_DIR
    draws_root = draws_root or DRAWS_DIR
    stats = {"listed": 0, "gm_fetched": 0, "gm_failed": 0,
             "draws_fetched": 0, "draws_failed": 0}
    for ry in years:
        html = session.get(LIVESTOCK_BASE.format(year=ry), timeout=300).text
        names = parse_listing(html, ry)
        stats["listed"] += len(names)
        for name in names:
            dest = root / f"{name[:-4]}_A00600.txt.gz"
            if dest.exists() and not force:
                continue
            try:
                fetch_member(session, ry, name, "A00600", dest)
                stats["gm_fetched"] += 1
            except Exception:
                stats["gm_failed"] += 1
        if not draws:
            continue
        for sed in month_end_sales_dates(ry, root):
            dest = draws_root / f"{ry}_ADMLivestockLgm_Daily_{sed}_A00610.txt.gz"
            if dest.exists() and not force:
                continue
            try:
                fetch_member(session, ry, f"{ry}_ADMLivestockLgm_Daily_{sed}.zip",
                             "A00610", dest)
                stats["draws_fetched"] += 1
            except Exception:
                stats["draws_failed"] += 1
    return stats


def month_end_sales_dates(ry: int, root: Path | None = None) -> list[str]:
    """The last sales date of each sales month present in the harvested A00600 files."""
    seds: set[str] = set()
    for p in history_files(ry, root):
        text = _read_member(p)
        m = _MEMBER_RE.match(p.name)
        for r in parse_gross_margin(text, file_stamp=m.group(2) if m else None):
            if r.sales_effective_date:
                seds.add(r.sales_effective_date)
    by_month: dict[str, str] = {}
    for s in sorted(seds):
        by_month[s[:6]] = s
    return [by_month[k] for k in sorted(by_month)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _label(cc: str, tc: str) -> str:
    return f"{COMMODITY_NAMES.get(cc, cc)} / {TYPE_NAMES.get((cc, tc), tc)}"


def format_ladder(rungs: Sequence[LadderRung], unit: str = "unit") -> str:
    degenerate = is_degenerate(rungs)
    best_net = None if degenerate else best_rung(rungs, "net")
    best_pd = None if degenerate else best_rung(rungs, "per_dollar")
    lines = [f"{'deduct':>8} {'subs':>6} {'periods':>8} {'paid':>6} {'total prem':>12} "
             f"{'producer':>11} {'indemnity':>12} {'loss ratio':>11} {'net $':>10} "
             f"{'net/prem$':>10} {'per prod$':>10}"]
    for r in rungs:
        mark = ""
        if r is best_net:
            mark += "  <- max measured net"
        if r is best_pd:
            mark += "  <- max return per producer $"
        lines.append(
            f"{r.deductible:>8.2f} {r.subsidy:>6.2f} {r.n_periods:>8d} {r.n_paid:>6d} "
            f"{r.total_premium:>12,.0f} {r.producer_premium:>11,.0f} "
            f"{r.indemnity:>12,.0f} {r.loss_ratio:>11.3f} {r.net_realised:>10,.0f} "
            f"{r.net_per_premium_dollar:>10.3f} "
            f"{r.return_per_producer_dollar:>10.2f}{mark}")
    if degenerate:
        lines.append("NO RUNG PAID over this window: net is -producer premium everywhere, "
                     "so there is no optimum to report.")
    lines.append(f"(per {unit}, equal target marketings in every insurable month; "
                 "net $ ranks the ladder, net/prem$ compares across commodities)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="LGM (plan 82) deductible ladder measured against realized margins.")
    ap.add_argument("--years", default="2022-2026",
                    help=f"reinsurance years, e.g. 2022-2026 "
                         f"(RY{FIRST_BACKTESTABLE_RY} is the earliest backtestable)")
    ap.add_argument("--harvest", action="store_true", help="cache ADM members (network)")
    ap.add_argument("--no-draws", action="store_true", help="harvest A00600 only")
    ap.add_argument("--ladder", action="store_true", help="print the measured ladder")
    ap.add_argument("--by-year", action="store_true", help="also print each year alone")
    ap.add_argument("--validate", action="store_true",
                    help="check assembled draws against published expected margins")
    ap.add_argument("--commodity", default=None)
    ap.add_argument("--type", dest="type_code", default=None)
    ap.add_argument("--lead", default="last", choices=("last", "first"))
    ap.add_argument("--independent-only", action="store_true",
                    help="keep only non-overlapping insurance periods")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))

    if args.harvest:
        import requests
        stats = harvest(requests.Session(), years, draws=not args.no_draws,
                        force=args.force)
        print(" ".join(f"{k}={v}" for k, v in stats.items()))
        if not (args.ladder or args.validate):
            return 0

    bt = run(years, lead=args.lead, independent_only=args.independent_only)
    if not bt.cells:
        print("no settled periods with harvested draws; run --harvest first")
        return 1

    if args.validate:
        worst: list[tuple[float, SettledPeriod]] = []
        for p in bt.periods:
            d = load_draws(p)
            if d is not None:
                worst.append((validate_draws(p, d), p))
        worst.sort(reverse=True)
        print(f"draw-vs-expected check over {len(worst)} periods:")
        for gap, p in worst[:5]:
            print(f"  {gap * 100:6.2f}%  {_label(*p.commodity_type)} "
                  f"{p.sales_effective_date}")
        print(f"  median {np.median([g for g, _ in worst]) * 100:.2f}%")

    if args.ladder or not args.validate:
        pairs = sorted({p.commodity_type for p in bt.periods})
        for cc, tc in pairs:
            if args.commodity and cc != args.commodity:
                continue
            if args.type_code and tc != args.type_code:
                continue
            rungs = bt.ladder(cc, tc)
            n = len([p for p in bt.periods if p.commodity_type == (cc, tc)])
            grain = (f"{n} NON-OVERLAPPING periods" if args.independent_only
                     else f"{n} monthly periods, {bt.n_independent(cc, tc)} non-overlapping")
            print(f"\n{_label(cc, tc)} — RY{years[0]}-RY{years[-1]}, {grain}")
            fwd = [d for (a, b, _), d in bt.forward.items() if (a, b) == (cc, tc)]
            if fwd:
                counts = sorted(((fwd.count(d), d) for d in set(fwd)), reverse=True)
                print("  forward-looking optimum on the same periods: "
                      + ", ".join(f"${d:g} on {k}/{len(fwd)}" for k, d in counts))
            print(format_ladder(rungs, COMMODITY_UNIT.get(cc, "unit")))
            if args.by_year:
                for ry in years:
                    yr = bt.ladder(cc, tc, ry)
                    if not yr:
                        continue
                    if is_degenerate(yr):
                        print(f"    RY{ry}: {yr[0].n_periods} periods, NO RUNG PAID")
                        continue
                    b = best_rung(yr, "net")
                    print(f"    RY{ry}: {yr[0].n_periods} periods, "
                          f"measured optimum {b.deductible:g} "
                          f"(loss ratio {b.loss_ratio:.2f}, net ${b.net_realised:,.0f}, "
                          f"net/prem$ {b.net_per_premium_dollar:+.3f})")
        if bt.skipped_no_draws:
            print(f"\nskipped for want of a harvested draw member: "
                  f"{len(bt.skipped_no_draws)} periods")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
