"""LGM (Livestock Gross Margin, plan code 82) — the MARGIN leg of the livestock trio.

We already have LRP (plan 81, PRICE only) and DRP (plan 83, REVENUE = price x yield).
LGM insures the MARGIN — revenue minus a declared feed cost — which completes the set and
creates the two comparisons a producer actually faces:

    LGM-Dairy vs DRP    same milk, two subsidised products; the question is whether FEED
                        COST risk is worth insuring.  For RY2027 this stopped being an
                        either/or: see "CONCURRENT COVERAGE" below.
    LGM-Cattle vs LRP   price-only vs margin on the same herd.

Written to mirror src/drpopt.py: pure scoring functions first, ADM parsing second, DB
upserts third, CLI last, and every reported quantity normalized so a caller can scale it.

=============================================================================
1. THE SUBSIDY KEYS OFF THE DEDUCTIBLE, NOT A COVERAGE LEVEL
=============================================================================
This is the structural fact that makes LGM different from every other plan in this repo,
and it is verified from RMA's own actuarial data rather than from a fact sheet.

ADM ``A00070 Subsidy Percent`` carries plan 82 under **record category 05**, and its key
column is ``Deductible Amount`` — not ``Coverage Level Percent``, which is blank on every
plan-82 row.  Compare the same file's other livestock plans:

    plan 81 LRP  record category 08  keyed by Range Low/High Value (coverage level)
    plan 82 LGM  record category 05  keyed by DEDUCTIBLE AMOUNT           <-- LGM
    plan 83 DRP  record category 04  keyed by Coverage Level Percent

The plan-82 schedule below is byte-identical in RY2026 and RY2027, both pulled from
``{RY}_ADM_YTD.zip``.  It is reproduced here as a constant so the pure functions work with
no database, but ``subsidy_table()`` reads the live ADM rows when they are loaded and
should be preferred — see "WHAT CHANGED FOR RY2027".

    Cattle (0803)   $0 .18  $10 .20  $20 .23  $30 .27  $40 .31  $50 .36  $60 .43
                    $70..$150 .50
    Swine  (0815)   $0 .18  $2 .21   $4 .25   $6 .30   $8 .37   $10 .47  $12..$20 .50
    Dairy  (0847)   $0 .18  $0.10 .19  $0.20 .21  $0.30 .23  $0.40 .25  $0.50 .28
                    $0.60 .31  $0.70 .34  $0.80 .38  $0.90 .43  $1.00 .48  $1.10..$2.00 .50

A $0 DEDUCTIBLE IS NOT UNSUBSIDISED.  It receives 18%, the bottom rung of the ladder.
The zero-subsidy case in LGM is a different dial entirely:

    "The producer is only eligible for premium subsidy if they target market in two (2)
     or more months of an insurance period.  This is calculated for each SCE."
        -- LGM for Dairy Cattle Handbook 2026 (FCIC-20080, April 2025), Part 2 s21 D(8);
           identical wording at s21 D(8) of the LGM for Cattle Handbook 2027 (FCIC-20060,
           April 2026) and the LGM for Swine Handbook s21 D(8).

    "You are only eligible for premium subsidy if you target market in 2 or more months
     of an insurance period."
        -- 26-LGM Dairy Cattle policy (released April 2025), section 5(b) Premium.

RMA's own worked example spells the consequence out as a second column of the same table:

    "Premium subsidy is given in the table below under step six, based on the deductible
     chosen and the numbers of months with insured marketings.  Pooled coverage is when
     two or more months of an insurance period have insured marketings.  Unpooled coverage
     is when only one month of an insurance period has insured marketings."
        -- LGM-Cattle Premium Calculation, Step by Step Instructions, p.2 (July 2020)

and prints 0.00 subsidy for UNPOOLED at every deductible from $0 through $150.  So
``pooled=False`` zeroes the subsidy at a $150 deductible exactly as hard as at $0.  That
is the LGM cliff, and it is a marketing-plan property, not a deductible property.

WHAT CHANGED FOR RY2027 (and what did not)
------------------------------------------
PM-26-024 (April 30, 2026) says the 2027 revisions "Revise the definition of beginning
farmer or rancher and update the subsidy percentages to conform with the One Big Beautiful
Bill Act."  Read against the ADM, that sentence does NOT touch the base ladder: RY2026 and
RY2027 A00070 plan-82 rows are identical, value for value, across all three commodities.
What changed is the BFR add-on.  The policy's flat rule is

    "If you qualify as a beginning farmer or rancher, your premium subsidy will be 10
     percentage points greater than the premium subsidy that you would otherwise receive,
     unless otherwise specified in the Special Provisions."
        -- 26-LGM Dairy Cattle policy, section 5(f)

and RMA's 2027 announcement layers the OBBBA ladder on top of it: an extra 5 points in
years one and two, 3 in year three, 1 in year four.  ``subsidy_rate(bfr_year=...)``
implements both.  Do not assume the base ladder is frozen — read it from the ADM per year.

CONCURRENT COVERAGE (why the head-to-heads changed shape)
---------------------------------------------------------
The 26-LGM Dairy policy still says, at section 3(i), that you "may not have any other FCIC
reinsured livestock policy covering the same class of livestock for any month for which you
have target marketings".  RMA's 2027 announcement lists "Permitting concurrent coverage
between similar livestock programs" among the changes effective for the 2027 crop year.
So "LGM-Dairy vs DRP" is an either/or question in RY2026 and a portfolio question in
RY2027.  This module does not model a stacked LGM+DRP position; it reports both legs
separately and flags the pairing.  See docs/lgm.md s6.

=============================================================================
2. PREMIUM IS A MONTE CARLO, AND RMA PUBLISHES THE DRAWS
=============================================================================
Same situation as DRP: there is no rate table to look up, but every input is public, so
premium is exactly reproducible.  RMA's published algorithm, verbatim:

    EGM  = sum_m p(m) * h(m)                     (round to dollars and cents)
    GMG  = EGM - DL * sum_m h(m)                 (round to dollars and cents)
    SGM(i) = sum_m gm(i,m) * h(m)                (round to dollars and cents)
    loss(i) = max(GMG - SGM(i), 0)               (round to dollars and cents)
    premium = (1/N) sum_i loss(i)                (round to dollars and cents)
    total premium = 1.03 * premium               (round to whole dollar amount)
    producer premium = total premium * (1 - premium subsidy)
        -- LGM-Cattle Premium Calculation, Steps 1-7 (July 2020)

tests/test_lgm.py pins the whole chain against RMA's own worked example, including the
intermediate SGMs and the $24,117.46 total premium.

THE DRAW COUNT DOES NOT MATCH THE INSTRUCTIONS.  The July 2020 instructions say "i = 1, 2,
...., 5,000" and divide by 5,000.  The ADM file RMA actually publishes,
``{RY}_ADMLivestockLgm_Daily_{date}.zip`` member ``A00610 LgmDraw``, carries **500** draws
per state x type (Margin Draw Number 1..500), for every commodity, in both RY2026 and
RY2027.  This module divides by the number of draws it was handed rather than by a
hardcoded constant, and ``load_draws()`` records the count it saw.  Treat any premium
computed from the public file as a 500-draw estimate of the number an AIP's system
produces; the Monte Carlo standard error at 500 draws is real and ``premium_stderr()``
reports it.

CATTLE MARGINS MUST BE ASSEMBLED; SWINE AND DAIRY ARE PUBLISHED WHOLE
---------------------------------------------------------------------
``A00600 LgmGrossMargin`` and ``A00610 LgmDraw`` are shaped differently per commodity:

  * Swine (0815) and Dairy (0847) publish record category 01/02 rows whose
    ``MonthN Expected Gross Margin Amount`` / ``MonthN Margin Draw Amount`` are the
    composite margin already netted of feed.  Read them straight.
  * Cattle (0803) publishes record category 02 with THREE rows per state x type, one per
    ``Market Symbol Code`` — ``LE`` live cattle ($/cwt), ``GF`` feeder cattle ($/cwt),
    ``C`` corn ($/bu) — and the draw file mirrors that with three blocks of monthly
    columns.  The composite is assembled with the declared ration:

        margin(m) = LE(m)*live_cwt - GF(m)*feeder_cwt - C(m)*corn_bu

    ``composite_cattle_margin()`` does this.  Verified numerically: for RY2027 Iowa, type
    807, the mean of the 500 assembled draws reproduces the published expected margin to
    within 0.5% in every month (350.75 vs 351.03, 386.28 vs 386.01, ... 411.64 vs 410.46).

=============================================================================
3. THE RATION IS LGM's BASIS RISK — BUT ONLY SWINE IS ACTUALLY LOCKED
=============================================================================
LGM settles on a ration RMA declares, not on the operation's feed bill, which is the same
county-index-vs-my-farm problem src/basisrisk.py handles for SCO/ECO.  The important
correction is that the three commodities are NOT equally exposed, because two of them let
the producer declare their own ration inside a band:

  CATTLE  -- ELECTABLE within bands.  "The target corn weight, measured in bushels of corn
     per head, is restricted to be within the range of 50 and 85 bushels per head for
     yearling finishing operations and within the range of 50 to 75 bushels per head for
     calf finishing operations.  The target feeder cattle weight must fall within the range
     of 6 to 12 cwt for yearling finishing operations and 4 to 6 cwt for calf finishing
     operations.  The target live cattle weight must fall within the range of 12 to 18 cwt
     for yearling finishing operations and 11 to 16 cwt for calf finishing operations."
       -- LGM for Cattle Handbook 2027 (FCIC-20060), s21 D(4)
     Defaults if nothing is elected: yearling 7.5 cwt in / 12.5 cwt out / 50 bu corn;
     calf 5.5 cwt in / 11.5 cwt out / 52 bu corn (s21 D(10)).  Those defaults are also
     published as the ``Live/Feeder Cattle Equivalent Default Value`` and ``Corn Equivalent
     Default Value`` columns of A00600, and the two sources agree exactly.

  DAIRY   -- ELECTABLE within bands.  "The number of tons of corn per month is restricted
     to be between 0.00364 and 0.0381 tons per cwt of milk.  The number of tons of soybean
     meal per month is restricted to be between 0.000805 and 0.013 tons per cwt of milk.
     Default values of 0.014 tons (0.5 bushels) of corn and 0.002 tons (4 pounds) of
     soybean meal per cwt of milk can be used if producers do not wish to choose feed
     amounts."
       -- LGM for Dairy Cattle Handbook 2026 (FCIC-20080), s21 D(4)
     In bushels (the units this module works in, converted with the handbook's own
     2,000/56) the corn band is 0.13 to 1.36 bu/cwt and the 0.014 t default is 0.50 bu —
     comfortably interior, so a dairy can move its declared corn a factor of ~2.7 up or
     ~3.8 down from RMA's default.  RATION_BANDS records the converted band.

  SWINE   -- FIXED.  No election exists.  "All swine are assumed to be marketed at 260
     pounds.  This number will be expressed in cwt as 2.6 cwt.  Swine insured in a Farrow
     to Finish operation are assumed to consume 12 bushels of corn and 138.55 pounds of
     soybean meal.  Swine insured in an operation that Finishes Feeder Pigs are assumed to
     consume 9 bushels of corn and 82 pounds of soybean meal.  Swine insured in an
     operation that finishes Segregated Early Weaned Pigs are assumed to consume 9.05
     bushels of corn and 91 pounds of soybean meal."
       -- LGM for Swine Handbook, s21 D(10)

So ration basis risk is ELIMINABLE for cattle and dairy inside the band and IRREDUCIBLE
outside it and for swine at all times.  ``ration_divergence()`` reports which case an
operation is in, and measures the gap three ways: in physical units, in dollars of expected
margin, and — the one that matters — as the residual standard deviation and tracking
correlation between the operation's true margin and the insured margin ACROSS RMA'S OWN
DRAWS.  That last number is the direct analogue of basisrisk.miss_rate: it is what fraction
of the operation's real margin risk the policy does not follow.

=============================================================================
4. DATA THIS REPO CANNOT SEE
=============================================================================
LGM experience IS in RMA's Summary of Business, in ``sobtpu`` (not ``sobcov``), exactly as
src/connectors/rma_sob.py's docstring predicted.  It is dropped one filter later, by
``sob_crop()``: ``ADM_ROW_CROP_CODES`` has no entry for 0803 / 0815 / 0847, so
``sob_crop()`` returns None and ``canonical_records()`` skips the row.  See
``SOB_GATE_NOTE`` below for the exact change that file needs.

What is NOT recoverable even after that change: sobtpu publishes ``Coverage Level`` as
``.0000`` for every plan-82 row from crop year 2008 forward, so realized loss ratio BY
DEDUCTIBLE does not exist in any public file.  Deductible-level economics in this module
are therefore forward-looking (computed off RMA's rate draws), never backtested.

CLI:
    .venv/bin/python -m src.lgm --subsidy --year 2027
    .venv/bin/python -m src.lgm --margins --year 2027
    .venv/bin/python -m src.lgm --curve --commodity 0803 --type 807 --state 19
    .venv/bin/python -m src.lgm --ration --commodity 0847 --corn 0.020 --soybean-meal 0.0035
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from . import config

PLAN_CODE = "82"

LIVESTOCK_BASE = "https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{year}/"
LGM_CACHE_DIR = config.CACHE_DIR / "lgm"

# ---------------------------------------------------------------------------
# Commodity / type vocabulary
# ---------------------------------------------------------------------------
# Commodity codes as they appear in BOTH the livestock ADM and sobtpu. sobtpu additionally
# reports a share of plan-82 business under commodity 9999 "All Other Commodities" (68% of
# 2024 premium, 80% of 2026) — that is an aggregation, not a fourth commodity, and
# commodity_from_sob() recovers the real one from type code + quantity type.
COMMODITY_NAMES = {
    "0803": "Cattle",
    "0815": "Swine",
    "0847": "Dairy Cattle",
}

# (commodity, type) -> name. Type names are taken from sobtpu's own Type Name column, which
# is the authority: 807 is CALF finishing and 808 is YEARLING finishing, the opposite of
# what the ascending code order suggests.
TYPE_NAMES = {
    ("0803", "807"): "Calf Finishing",
    ("0803", "808"): "Yearling Finishing",
    ("0815", "804"): "Farrow to Finish",
    ("0815", "805"): "Feeder Pig Finishing",
    ("0815", "806"): "SEW Pig Finishing",
    ("0847", "997"): "No Type Specified",
}

# Unit of exposure the deductible and the margin are quoted in.
COMMODITY_UNIT = {
    "0803": "head",
    "0815": "head",
    "0847": "cwt of milk",
}

# Months of an insurance period that can carry target marketings. Month 1 is always
# excluded ("with the exception of the first month of any insurance period" — s21 D(4)).
# Cattle and dairy run 11 months (months 2..11); swine runs 6 (months 2..6), which is what
# the ADM actually populates.
INSURED_MONTHS = {
    "0803": tuple(range(2, 12)),
    "0847": tuple(range(2, 12)),
    "0815": tuple(range(2, 7)),
}

# "total premium = 1.03 * premium" — LGM-Cattle Premium Calculation, Step 5.
LOADING_FACTOR = 1.03

# ---------------------------------------------------------------------------
# Subsidy: keyed by DEDUCTIBLE (ADM A00070, record category 05, plan 82)
# ---------------------------------------------------------------------------
# Verified identical in RY2026 and RY2027. Kept as a constant so the pure functions run
# without a database; subsidy_table(conn, ry) supersedes it when ADM rows are loaded.
SUBSIDY_BY_DEDUCTIBLE: dict[str, dict[float, float]] = {
    "0803": {0.0: 0.18, 10.0: 0.20, 20.0: 0.23, 30.0: 0.27, 40.0: 0.31, 50.0: 0.36,
             60.0: 0.43, 70.0: 0.50, 80.0: 0.50, 90.0: 0.50, 100.0: 0.50, 110.0: 0.50,
             120.0: 0.50, 130.0: 0.50, 140.0: 0.50, 150.0: 0.50},
    "0815": {0.0: 0.18, 2.0: 0.21, 4.0: 0.25, 6.0: 0.30, 8.0: 0.37, 10.0: 0.47,
             12.0: 0.50, 14.0: 0.50, 16.0: 0.50, 18.0: 0.50, 20.0: 0.50},
    "0847": {0.0: 0.18, 0.1: 0.19, 0.2: 0.21, 0.3: 0.23, 0.4: 0.25, 0.5: 0.28,
             0.6: 0.31, 0.7: 0.34, 0.8: 0.38, 0.9: 0.43, 1.0: 0.48, 1.1: 0.50,
             1.2: 0.50, 1.3: 0.50, 1.4: 0.50, 1.5: 0.50, 1.6: 0.50, 1.7: 0.50,
             1.8: 0.50, 1.9: 0.50, 2.0: 0.50},
}
SUBSIDY_SOURCE_YEARS = (2026, 2027)

# Section 5(f) flat bump, plus the OBBBA ladder RMA layered on for the 2027 crop year.
# Year is the producer's year of BFR status, 1-based; years 5..10 keep the flat 10 points.
BFR_FLAT_POINTS = 0.10
BFR_OBBBA_EXTRA_POINTS = {1: 0.05, 2: 0.05, 3: 0.03, 4: 0.01}
BFR_MAX_YEARS = 10

# The two comparison plans, same ADM file, different key column. Used by the head-to-heads.
LRP_SUBSIDY_BY_COVERAGE = {0.750: 0.55, 0.800: 0.50, 0.850: 0.45, 0.875: 0.45,
                           0.900: 0.40, 0.925: 0.40, 0.950: 0.35, 0.960: 0.35,
                           0.970: 0.35, 0.980: 0.35, 0.990: 0.35, 1.000: 0.35}
DRP_SUBSIDY_BY_COVERAGE = {0.80: 0.55, 0.85: 0.49, 0.90: 0.44, 0.95: 0.44}


# ---------------------------------------------------------------------------
# The declared ration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ration:
    """RMA's assumed inputs and output for one (commodity, type), per unit of exposure.

    Quantities are per head for cattle and swine and per cwt of milk for dairy. A field is
    None when the commodity has no such leg (dairy buys no feeder animal; swine and dairy
    have no live-cattle leg; cattle is fed no soybean meal).
    """
    commodity_code: str
    type_code: str
    corn_bu: float | None = None            # bushels of corn per unit
    soybean_meal_ton: float | None = None   # tons of soybean meal per unit
    feeder_cwt: float | None = None         # cwt of feeder animal bought in
    output_cwt: float | None = None         # cwt of live animal / milk sold out
    electable: bool = False                 # can the producer declare their own?

    @property
    def name(self) -> str:
        return TYPE_NAMES.get((self.commodity_code, self.type_code), self.type_code)


# Verbatim from the handbooks (see the module docstring for the quoted wording).
# Swine soybean meal is quoted in pounds and converted at 2,000 lb/ton, which is the
# conversion the handbook itself applies ("82 pounds divided by 2,000 pounds per ton").
# Dairy corn is quoted in TONS and converted to bushels at 2,000/56, again the handbook's
# own conversion ("multiplied by 2,000 / 56 (to convert tons to bushels)").
DAIRY_DEFAULT_CORN_TON = 0.014
DAIRY_DEFAULT_SBM_TON = 0.002
TONS_TO_BUSHELS_CORN = 2000.0 / 56.0

DECLARED_RATION: dict[tuple[str, str], Ration] = {
    ("0803", "807"): Ration("0803", "807", corn_bu=52.0, feeder_cwt=5.5,
                            output_cwt=11.5, electable=True),
    ("0803", "808"): Ration("0803", "808", corn_bu=50.0, feeder_cwt=7.5,
                            output_cwt=12.5, electable=True),
    ("0815", "804"): Ration("0815", "804", corn_bu=12.0, soybean_meal_ton=138.55 / 2000.0,
                            output_cwt=2.6, electable=False),
    ("0815", "805"): Ration("0815", "805", corn_bu=9.0, soybean_meal_ton=82.0 / 2000.0,
                            output_cwt=2.6, electable=False),
    ("0815", "806"): Ration("0815", "806", corn_bu=9.05, soybean_meal_ton=91.0 / 2000.0,
                            output_cwt=2.6, electable=False),
    ("0847", "997"): Ration("0847", "997",
                            corn_bu=DAIRY_DEFAULT_CORN_TON * TONS_TO_BUSHELS_CORN,
                            soybean_meal_ton=DAIRY_DEFAULT_SBM_TON,
                            output_cwt=1.0, electable=True),
}

# Election bands, as (low, high) in the same units as Ration. None = not electable.
RATION_BANDS: dict[tuple[str, str], dict[str, tuple[float, float]]] = {
    ("0803", "807"): {"corn_bu": (50.0, 75.0), "feeder_cwt": (4.0, 6.0),
                      "output_cwt": (11.0, 16.0)},
    ("0803", "808"): {"corn_bu": (50.0, 85.0), "feeder_cwt": (6.0, 12.0),
                      "output_cwt": (12.0, 18.0)},
    ("0847", "997"): {"corn_bu": (0.00364 * TONS_TO_BUSHELS_CORN,
                                  0.0381 * TONS_TO_BUSHELS_CORN),
                      "soybean_meal_ton": (0.000805, 0.013)},
}

# "The difference between target live cattle weight and target feeder cattle weight must
# not exceed 6 cwt for yearling finishing operations, and 10 cwt for calf finishing
# operations." -- LGM for Cattle Handbook 2027, s21 D(4)
CATTLE_MAX_GAIN_CWT = {"808": 6.0, "807": 10.0}


# ---------------------------------------------------------------------------
# The one-line change rma_sob.py needs (documented here; that file is not ours)
# ---------------------------------------------------------------------------
SOB_GATE_NOTE = """\
src/connectors/rma_sob.py :: sob_crop() drops every livestock row because
ADM_ROW_CROP_CODES (imported from rma_adm) has no 0803/0815/0847 entry. The minimal change
is one line at the top of the function body, before the ADM_ROW_CROP_CODES lookup:

    if plan_code in LIVESTOCK_PLAN_CODES:
        return LIVESTOCK_COMMODITY_CODES.get(commodity_code)

with, alongside the existing WFRP constants:

    LIVESTOCK_PLAN_CODES = {"81", "82", "83"}
    LIVESTOCK_COMMODITY_CODES = {"0803": "Cattle", "0815": "Swine",
                                 "0847": "Dairy Cattle", "9999": "Livestock (aggregated)"}

Two things to know before wiring it:
  * sobcov genuinely omits plans 81/82/83, so the gate must not be relaxed on the sobcov
    path or `sob_sales` / `sob_national` will gain crops with no rows. Livestock experience
    exists only on the sobtpu path (`sob_unit`, `sob_unit_national`).
  * `coverage_level` is '.0000' on every plan-82 row from 2008 forward, so the livestock
    rows will land on the coverage_level=0 slot of a primary key that assumes a real level.
    That is correct — LGM has no coverage level — but any per-level rollup must exclude
    them rather than treat 0 as a level.
"""
LIVESTOCK_PLAN_CODES = {"81", "82", "83"}


def commodity_from_sob(type_code: str, quantity_type: str) -> str | None:
    """Recover the real commodity for a sobtpu plan-82 row filed under 9999.

    sobtpu reports a large and growing share of LGM premium under commodity 9999 "All Other
    Commodities" (68% of plan-82 total premium in 2024, 80% in 2026), but it keeps the type
    code and the quantity type, and between them those identify the commodity uniquely.
    """
    t = (type_code or "").strip()
    if t in ("804", "805", "806"):
        return "0815"
    if t in ("807", "808"):
        return "0803"
    if "Milk" in (quantity_type or ""):
        return "0847"
    return None


# ---------------------------------------------------------------------------
# Pure premium engine — RMA's published Steps 1-7
# ---------------------------------------------------------------------------

def _r2(x: float) -> float:
    """Round to dollars and cents, which RMA's steps do at every stage."""
    return float(np.round(x + 0.0, 2))


def expected_total_gross_margin(expected: Sequence[float],
                                marketings: Sequence[float]) -> float:
    """Step 1a. EGM = sum_m p(m) * h(m), rounded to cents."""
    if len(expected) != len(marketings):
        raise ValueError("expected margins and marketings must be the same length")
    return _r2(float(np.dot(np.asarray(expected, float), np.asarray(marketings, float))))


def gross_margin_guarantee(egm: float, deductible: float,
                           marketings: Sequence[float]) -> float:
    """Step 1b. GMG = EGM - DL * sum_m h(m), rounded to cents.

    The deductible is per unit of exposure and bites on the TOTAL marketed quantity, not
    per month — which is why raising it shrinks the guarantee proportionally to size.
    """
    return _r2(egm - float(deductible) * float(np.sum(np.asarray(marketings, float))))


def simulated_total_gross_margins(draws: np.ndarray,
                                  marketings: Sequence[float]) -> np.ndarray:
    """Step 2. SGM(i) = sum_m gm(i,m) * h(m) for every draw, rounded to cents.

    `draws` is (n_draws, n_months) in the same month order as `marketings`.
    """
    draws = np.asarray(draws, float)
    h = np.asarray(marketings, float)
    if draws.ndim != 2 or draws.shape[1] != h.size:
        raise ValueError(f"draws {draws.shape} do not line up with {h.size} months")
    return np.round(draws @ h, 2)


def simulated_losses(gmg: float, sgm: np.ndarray) -> np.ndarray:
    """Step 3. loss(i) = max(GMG - SGM(i), 0)."""
    return np.round(np.maximum(gmg - np.asarray(sgm, float), 0.0), 2)


def premium_from_losses(losses: np.ndarray) -> float:
    """Step 4. premium = mean(loss).

    Divides by the number of draws actually supplied. The July 2020 instructions hardcode
    5,000; the published ADM draw file carries 500. See the module docstring.
    """
    losses = np.asarray(losses, float)
    if losses.size == 0:
        raise ValueError("no draws")
    return _r2(float(losses.mean()))


def total_premium_from_losses(losses: np.ndarray) -> float:
    """Step 5. total premium = 1.03 * premium, rounded to whole dollars."""
    return float(round(LOADING_FACTOR * premium_from_losses(losses)))


def premium_stderr(losses: np.ndarray) -> float:
    """Monte Carlo standard error of the Step-4 mean, in the same dollars.

    Not part of RMA's algorithm. It exists because the public file carries 500 draws rather
    than the 5,000 the instructions describe, so any premium quoted from it has a sampling
    error worth reporting next to it.
    """
    losses = np.asarray(losses, float)
    if losses.size < 2:
        return 0.0
    return float(losses.std(ddof=1) / np.sqrt(losses.size))


def is_pooled(marketings: Sequence[float]) -> bool:
    """True when two or more months carry target marketings — the subsidy eligibility gate."""
    return int(np.count_nonzero(np.asarray(marketings, float) > 0)) >= 2


def deductible_grid(commodity_code: str,
                    table: dict[str, dict[float, float]] | None = None) -> list[float]:
    """Every deductible RMA publishes a subsidy for, ascending."""
    tbl = (table or SUBSIDY_BY_DEDUCTIBLE)[commodity_code]
    return sorted(tbl)


def subsidy_rate(commodity_code: str, deductible: float, *, pooled: bool = True,
                 bfr_year: int | None = None, obbba: bool = True,
                 table: dict[str, dict[float, float]] | None = None) -> float:
    """Premium subsidy as a fraction of total premium.

    `pooled=False` (target marketings in exactly one month) returns 0.0 at EVERY
    deductible — the handbook eligibility rule, and RMA's own worked-example table prints
    it as a full column of zeros. A beginning farmer or rancher gets 10 points on top
    (policy s5(f)); `obbba=True` adds the 2027 ladder of 5/5/3/1 extra points in BFR years
    1-4. The result is capped at 1.0.
    """
    tbl = (table or SUBSIDY_BY_DEDUCTIBLE).get(commodity_code)
    if tbl is None:
        raise KeyError(f"no LGM subsidy table for commodity {commodity_code!r}")
    key = _nearest_deductible(deductible, tbl)
    if not pooled:
        return 0.0
    rate = tbl[key]
    if bfr_year is not None:
        if not 1 <= bfr_year <= BFR_MAX_YEARS:
            raise ValueError(f"bfr_year must be 1..{BFR_MAX_YEARS}, got {bfr_year}")
        rate += BFR_FLAT_POINTS
        if obbba:
            rate += BFR_OBBBA_EXTRA_POINTS.get(bfr_year, 0.0)
    return min(rate, 1.0)


def _nearest_deductible(deductible: float, tbl: dict[float, float]) -> float:
    """Snap to the filed deductible grid, refusing anything off it by more than a cent."""
    d = float(deductible)
    key = min(tbl, key=lambda k: abs(k - d))
    if abs(key - d) > 0.005:
        raise ValueError(
            f"deductible {d} is not on the filed grid {sorted(tbl)}")
    return key


def producer_premium(total_premium: float, subsidy: float) -> float:
    """Step 7. producer premium = total premium * (1 - subsidy), whole dollars."""
    return float(round(float(total_premium) * (1.0 - float(subsidy))))


def return_per_producer_dollar(loss_ratio: float, subsidy: float) -> float:
    """indemnity / (total premium - subsidy) — this repo's cross-plan comparison metric.

    Identical in form to sob_national.indemnity_per_producer_dollar and to the identity
    basisrisk.py uses for the area bands. At FCIC's statutory target loss ratio of 1.0
    (7 U.S.C. 1506(n)(2)) it collapses to 1 / (1 - subsidy).
    """
    if subsidy >= 1.0:
        return float("inf")
    return float(loss_ratio) / (1.0 - float(subsidy))


def net_expected_gain(total_premium: float, subsidy: float, *,
                      loss_ratio: float | None = None,
                      loading: float = LOADING_FACTOR) -> float:
    """Expected dollars the producer nets: E[indemnity] - producer premium.

    The repo's shorthand is `total premium x subsidy rate`, which holds when the policy is
    rated to a loss ratio of exactly 1.0. LGM is not: Step 5 multiplies the simulated
    expected loss by 1.03, so at RMA's own rating E[indemnity] = total premium / 1.03 and

        gain = total_premium * (1/loading - 1 + subsidy)

    The loading is why the honest break-even subsidy is 2.91%, not 0%. Pass `loss_ratio`
    to override the rated assumption with realized experience.
    """
    tp = float(total_premium)
    expected_indemnity = tp * (float(loss_ratio) if loss_ratio is not None
                               else 1.0 / float(loading))
    return expected_indemnity - tp * (1.0 - float(subsidy))


def break_even_subsidy(loading: float = LOADING_FACTOR,
                       loss_ratio: float | None = None) -> float:
    """The subsidy rate at which net expected gain crosses zero."""
    lr = float(loss_ratio) if loss_ratio is not None else 1.0 / float(loading)
    return 1.0 - lr


# ---------------------------------------------------------------------------
# The deductible curve — where the interior optimum sits
# ---------------------------------------------------------------------------

@dataclass
class DeductibleCell:
    """One deductible on one (commodity, type, state), everything else held fixed."""
    commodity_code: str
    type_code: str
    state_code: str
    deductible: float
    subsidy: float
    total_premium: float
    producer_premium: float
    expected_indemnity: float
    net_expected_gain: float
    return_per_producer_dollar: float
    premium_stderr: float
    gmg: float
    egm: float
    pooled: bool

    @property
    def guarantee_retained(self) -> float:
        """GMG / EGM — how much of the expected margin is still insured."""
        return self.gmg / self.egm if self.egm else 0.0


def deductible_curve(commodity_code: str, type_code: str, state_code: str,
                     expected: Sequence[float], draws: np.ndarray,
                     marketings: Sequence[float], *,
                     bfr_year: int | None = None,
                     loss_ratio: float | None = None,
                     table: dict[str, dict[float, float]] | None = None,
                     ) -> list[DeductibleCell]:
    """Score every filed deductible against one marketing plan.

    Everything except the deductible is held fixed, so the curve isolates exactly the trade
    the producer is making: a higher deductible buys a higher subsidy RATE on a SMALLER
    premium base. Premium falls faster than the subsidy rate rises once the ladder tops out
    at 0.50, so the product of the two peaks strictly inside the grid.
    """
    egm = expected_total_gross_margin(expected, marketings)
    sgm = simulated_total_gross_margins(draws, marketings)
    pooled = is_pooled(marketings)
    out: list[DeductibleCell] = []
    for d in deductible_grid(commodity_code, table):
        gmg = gross_margin_guarantee(egm, d, marketings)
        losses = simulated_losses(gmg, sgm)
        tp = total_premium_from_losses(losses)
        s = subsidy_rate(commodity_code, d, pooled=pooled, bfr_year=bfr_year, table=table)
        pp = producer_premium(tp, s)
        gain = net_expected_gain(tp, s, loss_ratio=loss_ratio)
        lr = loss_ratio if loss_ratio is not None else 1.0 / LOADING_FACTOR
        out.append(DeductibleCell(
            commodity_code=commodity_code, type_code=type_code, state_code=state_code,
            deductible=d, subsidy=s, total_premium=tp, producer_premium=pp,
            expected_indemnity=tp * lr, net_expected_gain=gain,
            return_per_producer_dollar=return_per_producer_dollar(lr, s),
            premium_stderr=premium_stderr(losses), gmg=gmg, egm=egm, pooled=pooled))
    return out


def optimal_deductible(curve: Sequence[DeductibleCell],
                       objective: str = "gain") -> DeductibleCell:
    """The best cell on a curve under ONE of two objectives that disagree.

    objective='gain'      maximise net expected DOLLARS (subsidy rate x premium base).
                          Interior: the ladder tops out at 0.50 while premium keeps
                          shrinking, so past that point every extra dollar of deductible is
                          pure give-back.
    objective='per_dollar' maximise return per producer dollar, 1/(1-subsidy) at rated
                          experience. Monotone in the subsidy rate, so it always picks the
                          LOWEST deductible that reaches the 0.50 cap — and it is blind to
                          how little protection is left there.
    objective='protection' maximise the guarantee actually retained. Always $0.

    These are different questions. A producer who cannot absorb the deductible in a bad
    year is rationally buying 'protection' and paying for it in expected value.
    """
    if not curve:
        raise ValueError("empty curve")
    if objective == "gain":
        return max(curve, key=lambda c: (c.net_expected_gain, -c.deductible))
    if objective == "per_dollar":
        return max(curve, key=lambda c: (round(c.return_per_producer_dollar, 9),
                                         -c.deductible))
    if objective == "protection":
        return max(curve, key=lambda c: (c.guarantee_retained, -c.deductible))
    raise ValueError(f"unknown objective {objective!r}")


# ---------------------------------------------------------------------------
# Ration basis risk
# ---------------------------------------------------------------------------

@dataclass
class RationDivergence:
    """How far an operation's real ration sits from the one LGM settles on.

    `residual_sd` and `tracking_corr` are the numbers that matter. They are measured
    across RMA's OWN published margin draws, so they describe divergence under exactly the
    price scenarios RMA priced the policy with — not under a distribution we invented.
    """
    commodity_code: str
    type_code: str
    insured: Ration
    actual: Ration
    deltas: dict[str, float]                 # actual - insured, physical units
    within_band: dict[str, bool]             # per leg; empty when nothing is electable
    electable: bool
    eliminable: bool                         # can declaring your own ration close the gap?
    expected_margin_insured: float | None = None
    expected_margin_actual: float | None = None
    expected_margin_gap: float | None = None
    residual_sd: float | None = None         # sd(actual margin - insured margin) per unit
    insured_sd: float | None = None
    tracking_corr: float | None = None
    unexplained_variance_share: float | None = None

    @property
    def verdict(self) -> str:
        if not self.deltas or all(abs(v) < 1e-12 for v in self.deltas.values()):
            return "on the declared ration"
        if self.eliminable:
            return "divergent but ELIMINABLE — declare your own ration"
        return "divergent and IRREDUCIBLE — no election available"


def ration_for(commodity_code: str, type_code: str) -> Ration:
    try:
        return DECLARED_RATION[(commodity_code, type_code)]
    except KeyError:
        raise KeyError(
            f"no declared LGM ration for commodity {commodity_code!r} type {type_code!r}"
        ) from None


def _leg_values(r: Ration) -> dict[str, float]:
    return {k: v for k, v in (("corn_bu", r.corn_bu),
                              ("soybean_meal_ton", r.soybean_meal_ton),
                              ("feeder_cwt", r.feeder_cwt),
                              ("output_cwt", r.output_cwt)) if v is not None}


def margin_per_unit(ration: Ration, *, output_price: float, corn_price: float = 0.0,
                    soybean_meal_price: float = 0.0, feeder_price: float = 0.0) -> float:
    """Gross margin per unit of exposure under one ration and one set of prices.

        cattle  live_cwt*live$ - feeder_cwt*feeder$ - corn_bu*corn$
        swine   2.6*hog$       - corn_bu*corn$      - sbm_ton*sbm$
        dairy   1*milk$        - corn_bu*corn$      - sbm_ton*sbm$

    Corn is always priced per BUSHEL here; the dairy handbook quotes the ration in tons and
    converts with 2,000/56, which DECLARED_RATION has already applied.
    """
    m = (ration.output_cwt or 0.0) * float(output_price)
    m -= (ration.corn_bu or 0.0) * float(corn_price)
    m -= (ration.soybean_meal_ton or 0.0) * float(soybean_meal_price)
    m -= (ration.feeder_cwt or 0.0) * float(feeder_price)
    return m


def ration_divergence(commodity_code: str, type_code: str, actual: Ration, *,
                      prices: dict[str, float] | None = None,
                      price_draws: dict[str, np.ndarray] | None = None,
                      ) -> RationDivergence:
    """Measure an operation's divergence from the ration LGM settles on.

    Three layers, cheapest first:

    1. PHYSICAL     per-leg deltas, and whether each leg is inside RMA's election band.
    2. LEVEL        with `prices`, the gap in expected margin per unit — a one-number
                    answer to "does the policy think my margin is bigger or smaller than it
                    is". A level gap alone is not basis risk: it shifts the guarantee, and
                    the deductible can be moved to compensate.
    3. RISK         with `price_draws` (arrays of equal length for whatever legs apply,
                    ideally RMA's own A00610 draws), the residual standard deviation and
                    correlation between the true and insured margins. THIS is basis risk:
                    `unexplained_variance_share` is the fraction of the operation's margin
                    variance that the policy does not track, the LGM analogue of
                    basisrisk.py's miss rate.
    """
    insured = ration_for(commodity_code, type_code)
    ins_legs, act_legs = _leg_values(insured), _leg_values(actual)
    deltas = {k: float(act_legs.get(k, 0.0) - v) for k, v in ins_legs.items()}

    bands = RATION_BANDS.get((commodity_code, type_code), {})
    within = {k: (lo <= act_legs.get(k, ins_legs[k]) <= hi)
              for k, (lo, hi) in bands.items() if k in ins_legs}
    # A cattle election also has to satisfy the max-gain constraint between the two weights.
    if commodity_code == "0803" and actual.output_cwt and actual.feeder_cwt:
        cap = CATTLE_MAX_GAIN_CWT.get(type_code)
        if cap is not None:
            within["gain_cwt"] = (actual.output_cwt - actual.feeder_cwt) <= cap + 1e-9
    eliminable = bool(insured.electable and within and all(within.values()))

    out = RationDivergence(commodity_code=commodity_code, type_code=type_code,
                           insured=insured, actual=actual, deltas=deltas,
                           within_band=within, electable=insured.electable,
                           eliminable=eliminable)

    if prices:
        out.expected_margin_insured = margin_per_unit(insured, **prices)
        out.expected_margin_actual = margin_per_unit(actual, **prices)
        out.expected_margin_gap = out.expected_margin_actual - out.expected_margin_insured

    if price_draws:
        keys = {"output_price", "corn_price", "soybean_meal_price", "feeder_price"}
        arrs = {k: np.asarray(v, float) for k, v in price_draws.items() if k in keys}
        if not arrs:
            raise ValueError(f"price_draws needs at least one of {sorted(keys)}")
        n = {a.size for a in arrs.values()}
        if len(n) != 1:
            raise ValueError("every price_draws array must be the same length")
        zeros = np.zeros(n.pop())
        get = lambda k: arrs.get(k, zeros)  # noqa: E731
        m_ins = ((insured.output_cwt or 0.0) * get("output_price")
                 - (insured.corn_bu or 0.0) * get("corn_price")
                 - (insured.soybean_meal_ton or 0.0) * get("soybean_meal_price")
                 - (insured.feeder_cwt or 0.0) * get("feeder_price"))
        m_act = ((actual.output_cwt or 0.0) * get("output_price")
                 - (actual.corn_bu or 0.0) * get("corn_price")
                 - (actual.soybean_meal_ton or 0.0) * get("soybean_meal_price")
                 - (actual.feeder_cwt or 0.0) * get("feeder_price"))
        resid = m_act - m_ins
        out.residual_sd = float(resid.std(ddof=1)) if resid.size > 1 else 0.0
        out.insured_sd = float(m_ins.std(ddof=1)) if m_ins.size > 1 else 0.0
        act_sd = float(m_act.std(ddof=1)) if m_act.size > 1 else 0.0
        if out.insured_sd > 0 and act_sd > 0:
            out.tracking_corr = float(np.corrcoef(m_act, m_ins)[0, 1])
            out.unexplained_variance_share = max(0.0, 1.0 - out.tracking_corr ** 2)
        else:
            out.tracking_corr = None
            out.unexplained_variance_share = None
    return out


# ---------------------------------------------------------------------------
# ADM parsing
# ---------------------------------------------------------------------------

# ONLY SWINE PUBLISHES A COMPOSITE MARGIN. Cattle and dairy both publish one row per
# COMPONENT, tagged by Market Symbol Code, and the margin has to be assembled with the
# ration. This is easy to get wrong in a way that produces plausible numbers: the rows for
# one (commodity, type, state) are otherwise identical, so taking "the first row" silently
# reads a corn price as a gross margin — which is what dairy premium exceeding dairy
# expected margin looked like before this was split out.
#
# Per commodity: leg -> (Market Symbol Code in A00600, monthly column prefix in A00610).
COMPONENT_LEGS: dict[str, dict[str, tuple[str, str]]] = {
    "0803": {"output": ("LE", "Live Cattle "),      # fed cattle, $/cwt
             "feeder": ("GF", "Feeder Cattle "),    # feeder cattle, $/cwt
             "corn": ("C", "Corn ")},               # corn, $/bu
    "0847": {"output": ("DA", "Dairy "),            # Class III milk, $/cwt
             "corn": ("C", "Corn "),                # corn, $/bu
             "soybean_meal": ("SM", "SoyM ")},      # soybean meal, $/ton
}
# Swine (0815) is absent on purpose: one row, no Market Symbol Code, margin already netted
# of feed in the generic MonthN columns.


def parse_pipe(text: str) -> list[dict[str, str]]:
    """Header-bearing pipe-delimited ADM member -> list of dicts."""
    return list(csv.DictReader(io.StringIO(text), delimiter="|"))


def _f(row: dict[str, str], key: str) -> float | None:
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def monthly(row: dict[str, str], template: str,
            months: Iterable[int]) -> list[float | None]:
    """Pull MonthN columns for one row in month order, e.g. '{m} Expected Gross Margin Amount'."""
    return [_f(row, template.format(m=m)) for m in months]


@dataclass
class MarginPanel:
    """Expected margins and draws for one (commodity, type, state, sales date), per unit."""
    commodity_code: str
    type_code: str
    state_code: str
    sales_effective_date: str
    months: tuple[int, ...]
    expected: np.ndarray                 # (n_months,)
    draws: np.ndarray                    # (n_draws, n_months)
    ration: Ration | None = None
    liability_price: float | None = None

    @property
    def n_draws(self) -> int:
        return int(self.draws.shape[0])


# Ration field that scales each component leg.
LEG_RATION_FIELD = {"output": "output_cwt", "feeder": "feeder_cwt",
                    "corn": "corn_bu", "soybean_meal": "soybean_meal_ton"}


def composite_margin(legs: dict[str, Sequence[float | None]],
                     ration: Ration) -> list[float | None]:
    """Assemble a monthly gross margin from component price paths and a ration.

        cattle  margin(m) = LE(m)*live_cwt - GF(m)*feeder_cwt - C(m)*corn_bu
        dairy   margin(m) = DA(m)*1.0      - C(m)*corn_bu     - SM(m)*sbm_ton

    Every leg but 'output' is a cost and enters negative. A month is None unless every leg
    has a value for it. Verified numerically against RMA's own published expected margins:
    for RY2027 Iowa cattle type 807 the mean of the 500 assembled draws reproduces the
    published expected margin in all ten months to within Monte Carlo noise (350.75 vs
    351.03 ... 411.64 vs 410.46), and dairy reproduces likewise.
    """
    n = len(next(iter(legs.values())))
    out: list[float | None] = []
    for i in range(n):
        total = 0.0
        ok = True
        for leg, series in legs.items():
            v = series[i]
            if v is None:
                ok = False
                break
            q = getattr(ration, LEG_RATION_FIELD[leg], None) or 0.0
            total += v * q if leg == "output" else -v * q
        out.append(total if ok else None)
    return out


def composite_cattle_margin(live: Sequence[float | None], feeder: Sequence[float | None],
                            corn: Sequence[float | None],
                            ration: Ration) -> list[float | None]:
    """Cattle-shaped convenience wrapper over composite_margin()."""
    return composite_margin({"output": live, "feeder": feeder, "corn": corn}, ration)


def _trim(expected: list[float | None], draws: list[list[float | None]],
          months: tuple[int, ...]) -> tuple[tuple[int, ...], np.ndarray, np.ndarray]:
    """Keep only months populated in BOTH the expected row and every draw."""
    keep = [i for i, v in enumerate(expected)
            if v is not None and all(d[i] is not None for d in draws)]
    if not keep:
        raise ValueError("no month is populated in both the expected row and the draws")
    m = tuple(months[i] for i in keep)
    e = np.array([expected[i] for i in keep], float)
    d = np.array([[row[i] for i in keep] for row in draws], float)
    return m, e, d


def build_panels(gross_margin_text: str, draw_text: str, *,
                 commodity_code: str | None = None,
                 state_code: str | None = None,
                 type_code: str | None = None) -> list[MarginPanel]:
    """Turn the two ADM members into per-(commodity, type, state) margin panels.

    Handles both shapes: composite (swine 0815, dairy 0847 — one row, margin published
    whole) and per-component (cattle 0803 — three Market Symbol rows assembled with the
    ration). Rows with no usable month are skipped rather than raising, because RMA
    publishes placeholder rows for commodities whose sales period has not opened.
    """
    gm_rows = parse_pipe(gross_margin_text)
    dr_rows = parse_pipe(draw_text)

    def want(r: dict[str, str]) -> bool:
        return (str(r.get("Insurance Plan Code", "")).strip() == PLAN_CODE
                and (commodity_code is None
                     or str(r.get("Commodity Code", "")).strip() == commodity_code)
                and (state_code is None
                     or str(r.get("State Code", "")).strip() == state_code)
                and (type_code is None
                     or str(r.get("Type Code", "")).strip() == type_code))

    gm_rows = [r for r in gm_rows if want(r)]
    dr_rows = [r for r in dr_rows if want(r)]

    # Keyed on the SALES EFFECTIVE DATE too, because RMA's file accumulates: a mid-year
    # RY2026 pull carries every sales date the year has seen so far, and collapsing them
    # would silently price one date's margins against another date's draws. The draw file
    # carries only the date it was published for, so a gross-margin row with no matching
    # draw date is a historical row and is skipped.
    def key(r: dict[str, str]) -> tuple[str, str, str, str]:
        return (r["Commodity Code"].strip(), r["Type Code"].strip(),
                r["State Code"].strip(), (r.get("Sales Effective Date") or "").strip())

    gm_by: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for r in gm_rows:
        gm_by.setdefault(key(r), []).append(r)
    dr_by: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for r in dr_rows:
        dr_by.setdefault(key(r), []).append(r)

    panels: list[MarginPanel] = []
    for k, rows in sorted(gm_by.items()):
        cc, tc, sc, sed = k
        months = INSURED_MONTHS.get(cc, tuple(range(2, 12)))
        drows = dr_by.get(k, [])
        if not drows:
            continue
        ration = DECLARED_RATION.get((cc, tc))
        if cc in COMPONENT_LEGS:
            panel = _component_panel(rows, drows, months, cc, tc, sc, sed)
        else:
            panel = _composite_panel(rows, drows, months, cc, tc, sc, sed, ration)
        if panel is not None:
            panels.append(panel)
    return panels


def _composite_panel(rows, drows, months, cc, tc, sc, sed, ration) -> MarginPanel | None:
    row = rows[0]
    expected = monthly(row, "Month{m} Expected Gross Margin Amount", months)
    draws = [monthly(d, "Month{m} Margin Draw Amount", months) for d in drows]
    try:
        m, e, dd = _trim(expected, draws, months)
    except ValueError:
        return None
    return MarginPanel(cc, tc, sc, sed, m, e, dd, ration,
                       _f(row, "Liability Price"))


def _panel_ration(cc: str, tc: str, by_leg: dict[str, dict[str, str]]) -> Ration | None:
    """Prefer the ration RMA published on the rows themselves; fall back to the handbook.

    Cattle carries its defaults as explicit A00600 columns, so a future change to them is
    picked up without a code edit; the two sources currently agree exactly. Dairy publishes
    no equivalent columns, so it always uses the handbook defaults.
    """
    fallback = DECLARED_RATION.get((cc, tc))
    if cc != "0803":
        return fallback
    ration = Ration(cc, tc,
                    corn_bu=_f(by_leg["corn"], "Corn Equivalent Default Value"),
                    feeder_cwt=_f(by_leg["feeder"],
                                  "Feeder Cattle Equivalent Default Value"),
                    output_cwt=_f(by_leg["output"],
                                  "Live Cattle Equivalent Default Value"),
                    electable=True)
    if None in (ration.corn_bu, ration.feeder_cwt, ration.output_cwt):
        return fallback
    return ration


def _component_panel(rows, drows, months, cc, tc, sc, sed) -> MarginPanel | None:
    """Assemble cattle / dairy, whose ADM rows are one price path per component."""
    spec = COMPONENT_LEGS[cc]
    symbol_to_leg = {sym: leg for leg, (sym, _) in spec.items()}
    by_leg: dict[str, dict[str, str]] = {}
    for r in rows:
        leg = symbol_to_leg.get((r.get("Market Symbol Code") or "").strip())
        if leg is not None:
            by_leg[leg] = r
    if set(by_leg) != set(spec):
        return None
    ration = _panel_ration(cc, tc, by_leg)
    if ration is None:
        return None
    expected = composite_margin(
        {leg: monthly(by_leg[leg], "Month{m} Expected Gross Margin Amount", months)
         for leg in spec}, ration)
    draws = [composite_margin(
        {leg: monthly(d, prefix + "Month{m} Margin Draw Amount", months)
         for leg, (_, prefix) in spec.items()}, ration) for d in drows]
    try:
        m, e, dd = _trim(expected, draws, months)
    except ValueError:
        return None
    return MarginPanel(cc, tc, sc, sed, m, e, dd, ration,
                       _f(by_leg["output"], "Liability Price"))


def uniform_marketings(n_months: int, per_month: float = 1.0) -> list[float]:
    """The neutral marketing plan: equal exposure in every insurable month.

    Used to isolate the deductible. It is also the plan that maximises the pooling benefit,
    so a curve built on it is the best case for the subsidy.
    """
    return [float(per_month)] * int(n_months)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _cache_path(name: str) -> Path:
    LGM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return LGM_CACHE_DIR / name


def parse_listing(html: str, ry: int) -> list[str]:
    """LGM zip names in a pubfs directory listing, oldest first."""
    pat = re.compile(rf"{ry}_ADMLivestockLgm_Daily_(\d{{8}})\.zip")
    return [n for _, n in sorted({(m.group(1), m.group(0)) for m in pat.finditer(html)})]


def fetch_lgm_zip(session, ry: int, filename: str, *, force: bool = False,
                  timeout: int = 180) -> dict[str, str]:
    """Download one LGM ADM zip (cached) and return {member_substring: text}."""
    dest = _cache_path(filename)
    if force or not dest.exists():
        resp = session.get(LIVESTOCK_BASE.format(year=ry) + filename, timeout=timeout)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    out: dict[str, str] = {}
    with zipfile.ZipFile(dest) as zf:
        for n in zf.namelist():
            if not n.lower().endswith(".txt"):
                continue
            tag = "A00600" if "A00600" in n else ("A00610" if "A00610" in n else n)
            out[tag] = zf.read(n).decode("utf-8", "replace")
    return out


def parse_subsidy_rows(lines: Iterable[str]) -> list[tuple[int, str, float, float]]:
    """A00070 record-category-05 rows -> (reinsurance_year, commodity, deductible, pct).

    Parsed by column NAME, not position: A00070's layout has drifted between reinsurance
    years before (drpdata's note on the RY2019 18-field vs RY2020 19-field shape).
    """
    rows = parse_pipe("\n".join(lines))
    out: list[tuple[int, str, float, float]] = []
    for r in rows:
        if str(r.get("Insurance Plan Code", "")).strip() != PLAN_CODE:
            continue
        d = _f(r, "Deductible Amount")
        s = _f(r, "Subsidy Percent")
        cc = str(r.get("Commodity Code", "")).strip().zfill(4)
        ry = r.get("Reinsurance Year", "").strip()
        if d is None or s is None or not ry:
            continue
        out.append((int(ry), cc, d, s))
    return out


def stream_adm_subsidy(session, ry: int, base_url: str, timeout: int = 180) -> list[str]:
    """Stream-filter plan 82 out of the crop ADM YTD zip's A00070 member.

    Same HTTP-range + mid-inflate trick src/drpdata.py uses for plan 83: the YTD zip is
    gigabytes and we want a few dozen rows, so nothing large touches disk.
    """
    from .connectors.rma_adm import http_range_zip

    rz = http_range_zip(session, base_url.format(year=ry) + f"{ry}_ADM_YTD.zip", timeout)
    m = rz.find("A00070_SubsidyPercent")
    lh = rz._read(m.header_offset, m.header_offset + 29)
    nlen, elen = struct.unpack("<HH", lh[26:30])
    start = m.header_offset + 30 + nlen + elen

    dec = zlib.decompressobj(-15)
    buf = b""
    out: list[str] = []
    header_done = False

    def handle(raw: bytes) -> None:
        nonlocal header_done
        line = raw.rstrip(b"\r").decode("utf-8", "replace")
        if not line:
            return
        if not header_done:
            out.append(line)
            header_done = True
        elif line.split("|")[5:6] == [PLAN_CODE]:
            out.append(line)

    for chunk in rz._stream(start, start + m.csize - 1):
        buf += dec.decompress(chunk)
        *lines, buf = buf.split(b"\n")
        for raw in lines:
            handle(raw)
    buf += dec.flush()
    for raw in buf.split(b"\n"):
        handle(raw)
    return out


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_subsidy(conn: sqlite3.Connection,
                   rows: Iterable[tuple[int, str, float, float]],
                   source: str = "adm_a00070") -> int:
    ts = _now_iso()
    payload = [(ry, cc, COMMODITY_NAMES.get(cc, cc), d, s, source, ts)
               for ry, cc, d, s in rows]
    conn.executemany(
        """INSERT INTO lgm_subsidy (reinsurance_year, commodity_code, commodity_name,
               deductible, subsidy_pct, source, fetched_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, commodity_code, deductible) DO UPDATE SET
             commodity_name=excluded.commodity_name, subsidy_pct=excluded.subsidy_pct,
             source=excluded.source, fetched_at=excluded.fetched_at""", payload)
    conn.commit()
    return len(payload)


def subsidy_table(conn: sqlite3.Connection,
                  reinsurance_year: int) -> dict[str, dict[float, float]]:
    """Live ADM subsidy ladder for one year, in the shape subsidy_rate() wants.

    Falls back to SUBSIDY_BY_DEDUCTIBLE only when the table is empty for that year, and the
    caller can tell the difference because the fallback is returned unchanged.
    """
    out: dict[str, dict[float, float]] = {}
    for r in conn.execute(
            "SELECT commodity_code, deductible, subsidy_pct FROM lgm_subsidy "
            "WHERE reinsurance_year = ?", (reinsurance_year,)):
        out.setdefault(r[0], {})[float(r[1])] = float(r[2])
    return out or SUBSIDY_BY_DEDUCTIBLE


def upsert_panels(conn: sqlite3.Connection, ry: int, panels: Iterable[MarginPanel],
                  source: str = "adm_lgm") -> int:
    ts = _now_iso()
    rows = []
    for p in panels:
        r = p.ration
        rows.append((ry, p.commodity_code, COMMODITY_NAMES.get(p.commodity_code),
                     p.type_code, TYPE_NAMES.get((p.commodity_code, p.type_code)),
                     p.state_code, p.sales_effective_date,
                     ",".join(str(m) for m in p.months),
                     float(p.expected.sum()), float(p.expected.mean()), p.n_draws,
                     float(p.draws.sum(axis=1).std(ddof=1)) if p.n_draws > 1 else None,
                     p.liability_price,
                     r.corn_bu if r else None, r.soybean_meal_ton if r else None,
                     r.feeder_cwt if r else None, r.output_cwt if r else None,
                     source, ts))
    conn.executemany(
        """INSERT INTO lgm_margin (reinsurance_year, commodity_code, commodity_name,
               type_code, type_name, state_code, sales_effective_date, months,
               expected_margin_total, expected_margin_mean, n_draws, draw_total_sd,
               liability_price, ration_corn_bu, ration_soybean_meal_ton,
               ration_feeder_cwt, ration_output_cwt, source, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, commodity_code, type_code, state_code,
                       sales_effective_date) DO UPDATE SET
             expected_margin_total=excluded.expected_margin_total,
             expected_margin_mean=excluded.expected_margin_mean,
             n_draws=excluded.n_draws, draw_total_sd=excluded.draw_total_sd,
             liability_price=excluded.liability_price,
             ration_corn_bu=excluded.ration_corn_bu,
             ration_soybean_meal_ton=excluded.ration_soybean_meal_ton,
             ration_feeder_cwt=excluded.ration_feeder_cwt,
             ration_output_cwt=excluded.ration_output_cwt,
             source=excluded.source, fetched_at=excluded.fetched_at""", rows)
    conn.commit()
    return len(rows)


def upsert_curve(conn: sqlite3.Connection, ry: int, cells: Iterable[DeductibleCell],
                 source: str = "lgm") -> int:
    ts = _now_iso()
    rows = [(ry, c.commodity_code, c.type_code, c.state_code, c.deductible, c.subsidy,
             c.total_premium, c.producer_premium, c.expected_indemnity,
             c.net_expected_gain, c.return_per_producer_dollar, c.premium_stderr,
             c.egm, c.gmg, c.guarantee_retained, int(c.pooled), source, ts)
            for c in cells]
    conn.executemany(
        """INSERT INTO lgm_deductible_curve (reinsurance_year, commodity_code, type_code,
               state_code, deductible, subsidy_pct, total_premium, producer_premium,
               expected_indemnity, net_expected_gain, return_per_producer_dollar,
               premium_stderr, expected_total_gross_margin, gross_margin_guarantee,
               guarantee_retained, pooled, source, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(reinsurance_year, commodity_code, type_code, state_code,
                       deductible) DO UPDATE SET
             subsidy_pct=excluded.subsidy_pct, total_premium=excluded.total_premium,
             producer_premium=excluded.producer_premium,
             expected_indemnity=excluded.expected_indemnity,
             net_expected_gain=excluded.net_expected_gain,
             return_per_producer_dollar=excluded.return_per_producer_dollar,
             premium_stderr=excluded.premium_stderr,
             expected_total_gross_margin=excluded.expected_total_gross_margin,
             gross_margin_guarantee=excluded.gross_margin_guarantee,
             guarantee_retained=excluded.guarantee_retained, pooled=excluded.pooled,
             source=excluded.source, fetched_at=excluded.fetched_at""", rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_curve(curve: Sequence[DeductibleCell], unit: str) -> str:
    lines = [f"{'deduct':>8} {'subsidy':>8} {'total$':>12} {'producer$':>12} "
             f"{'net gain$':>12} {'per $1':>7} {'guar%':>7}"]
    best_gain = optimal_deductible(curve, "gain")
    best_pd = optimal_deductible(curve, "per_dollar")
    for c in curve:
        mark = ""
        if c is best_gain:
            mark += "  <- max net gain"
        if c is best_pd:
            mark += "  <- max return per producer $"
        lines.append(f"{c.deductible:>8.2f} {c.subsidy:>8.3f} {c.total_premium:>12,.0f} "
                     f"{c.producer_premium:>12,.0f} {c.net_expected_gain:>12,.0f} "
                     f"{c.return_per_producer_dollar:>7.2f} "
                     f"{c.guarantee_retained * 100:>6.1f}%{mark}")
    lines.append(f"(per {unit}; premium scales linearly with marketed quantity)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LGM (plan 82) — margin insurance.")
    ap.add_argument("--year", type=int, default=2027, help="reinsurance year")
    ap.add_argument("--subsidy", action="store_true", help="load ADM subsidy ladder")
    ap.add_argument("--margins", action="store_true", help="load ADM margin panels")
    ap.add_argument("--curve", action="store_true", help="print a deductible curve")
    ap.add_argument("--ration", action="store_true", help="measure ration divergence")
    ap.add_argument("--commodity", default="0803")
    ap.add_argument("--type", dest="type_code", default=None)
    ap.add_argument("--state", default="19")
    ap.add_argument("--corn", type=float, default=None, help="corn: bu/head, or tons/cwt (dairy)")
    ap.add_argument("--soybean-meal", type=float, default=None, help="tons per unit")
    ap.add_argument("--feeder-cwt", type=float, default=None)
    ap.add_argument("--output-cwt", type=float, default=None)
    ap.add_argument("--unpooled", action="store_true",
                    help="one month of target marketings — zeroes the subsidy")
    ap.add_argument("--bfr-year", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    from . import db

    if args.ration:
        cc = args.commodity
        tc = args.type_code or next(t for (c, t) in DECLARED_RATION if c == cc)
        ins = ration_for(cc, tc)
        corn = args.corn
        if cc == "0847" and corn is not None:
            corn *= TONS_TO_BUSHELS_CORN
        actual = Ration(cc, tc,
                        corn_bu=corn if corn is not None else ins.corn_bu,
                        soybean_meal_ton=(args.soybean_meal if args.soybean_meal is not None
                                          else ins.soybean_meal_ton),
                        feeder_cwt=(args.feeder_cwt if args.feeder_cwt is not None
                                    else ins.feeder_cwt),
                        output_cwt=(args.output_cwt if args.output_cwt is not None
                                    else ins.output_cwt),
                        electable=ins.electable)
        d = ration_divergence(cc, tc, actual)
        print(f"{COMMODITY_NAMES.get(cc, cc)} / {ins.name}: {d.verdict}")
        for k, v in d.deltas.items():
            band = d.within_band.get(k)
            flag = "" if band is None else ("  (in band)" if band else "  (OUTSIDE BAND)")
            print(f"  {k:>18}: {v:+.5f}{flag}")
        if "gain_cwt" in d.within_band and not d.within_band["gain_cwt"]:
            print("  gain (out - in) exceeds the filed maximum")
        return 0

    conn = db.connect()
    db.init_db(conn)

    if args.subsidy:
        import requests
        cfg = config.load()
        lines = stream_adm_subsidy(requests.Session(), args.year, cfg.rma_adm_base_url)
        n = upsert_subsidy(conn, parse_subsidy_rows(lines))
        print(f"lgm_subsidy: {n} rows for RY{args.year}")

    if args.margins or args.curve:
        import requests
        s = requests.Session()
        listing = s.get(LIVESTOCK_BASE.format(year=args.year), timeout=120).text
        names = parse_listing(listing, args.year)
        if not names:
            print(f"no LGM ADM files published for RY{args.year}")
            return 1
        members = fetch_lgm_zip(s, args.year, names[-1], force=args.force)
        panels = build_panels(members.get("A00600", ""), members.get("A00610", ""))
        if args.margins:
            print(f"lgm_margin: {upsert_panels(conn, args.year, panels)} panels "
                  f"from {names[-1]}")
        if args.curve:
            tbl = subsidy_table(conn, args.year)
            want = [p for p in panels
                    if p.commodity_code == args.commodity and p.state_code == args.state
                    and (args.type_code is None or p.type_code == args.type_code)]
            if not want:
                print(f"no panel for commodity {args.commodity} state {args.state}")
                return 1
            for p in want:
                h = uniform_marketings(len(p.months))
                if args.unpooled:
                    h = [0.0] * len(h)
                    h[0] = 1.0
                curve = deductible_curve(p.commodity_code, p.type_code, p.state_code,
                                         p.expected, p.draws, h,
                                         bfr_year=args.bfr_year, table=tbl)
                name = TYPE_NAMES.get((p.commodity_code, p.type_code), p.type_code)
                print(f"\n{COMMODITY_NAMES.get(p.commodity_code)} / {name} / "
                      f"state {p.state_code} / sales {p.sales_effective_date} / "
                      f"{p.n_draws} draws")
                print(_fmt_curve(curve, COMMODITY_UNIT.get(p.commodity_code, "unit")))
                upsert_curve(conn, args.year, curve)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
