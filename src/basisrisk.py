"""Basis risk for the AREA-triggered endorsements (SCO, ECO, MCO, STAX).

THE PROBLEM
===========
SCO, ECO, MCO and STAX settle on a COUNTY yield/revenue index. Individual MPCI settles on the
producer's own unit. So an area-triggered band can fail to pay a producer who had a genuine,
severe loss, because the county as a whole was fine. That failure is BASIS RISK.

It matters because it is the ONLY farm-specific thing about these products. They carry ~80%
premium subsidy, so at FCIC's statutory target loss ratio of 1.0 (7 U.S.C. 1506(n)(2)) the
expected return per producer dollar is 1/(1-0.80) = 5x — and that multiple is an arithmetic
identity, IDENTICAL for every farm in the country. What is not identical is whether the trigger
fires when a given farm actually loses money. Strip basis risk out and the honest advice
degenerates to "everyone should buy ECO", which is wrong.

WHAT WE CAN AND CANNOT KNOW  (read this before using any number here)
=====================================================================
We have NO farm-level yield data and cannot get it — RMA's APH database is private. So:

  * The COUNTY side of every calculation is MEASURED, from NASS Quick Stats county yield
    history (src/connectors/nass_yield.py). Its variability, trend, skew and how often the
    index would historically have fired are facts.
  * The FARM side is MODELLED. Every county-level number this module produces describes a
    TYPICAL farm in that county — not any actual farm, and not the reader's farm.
  * The path to a real answer is `farm_basis_risk()`, which takes the producer's own APH yield
    history (a short series they read off their own schedule), measures THEIR correlation to
    the county, and reports THEIR shortfall frequency. That needs no private data we do not
    have, because the producer supplies it.

THE ESTIMATOR
=============
Step 1 — DETREND. A county yield series has a strong technology trend; treating it as risk
would inflate every number here. We fit a trend and work in RATIOS to it:

    ratio_t = y_t / fitted_t          (mean ~1, unitless)

The default is ordinary least squares on year. That is not an arbitrary choice: it is the same
form RMA itself uses for its Trend-Adjusted APH endorsement and for the expected county yield
that SCO/ECO settle against, so `ratio_t` is the empirical analogue of the county index RMA
computes. `theilsen` (median of pairwise slopes) is available and is more robust when a couple
of drought years would otherwise drag the fitted trend down; `mean` (no trend) exists for
testing and for series too short to fit. The chosen method is recorded on every output row.

Step 2 — THE COUNTY DISTRIBUTION IS THE DATA. We do not fit a parametric yield distribution.
County draws come from a variance-corrected smoothed bootstrap of the detrended ratios
(Silverman & Young 1987; Efron & Tibshirani, *An Introduction to the Bootstrap*, 1993, §16.5),
which preserves the county's own left skew and its actual drought tail instead of imposing a
Beta or Normal shape on it.

Step 3 — THE FARM IS THE COUNTY PLUS IDIOSYNCRATIC RISK. One equation:

    y_farm = y_county + e,        e independent of y_county,  E[e] = 0

This is the aggregation identity, not a free-form assumption. If a county index is (near
enough) the acreage-weighted mean of the farms in it, and farm deviations from it are
exchangeable, then the county is the systemic factor and each farm is that factor plus its own
noise. Two consequences follow immediately and both are used:

    corr(y_farm, y_county) = sigma_county / sigma_farm  ==  rho
    sigma_e = sigma_county * sqrt(1/rho^2 - 1)

So rho and the farm/county standard-deviation ratio are THE SAME PARAMETER. This is what makes
the whole exercise tractable: the county data pins down sigma_county exactly, and exactly ONE
number has to be imported from outside — rho. Everything else follows. Because it is one
parameter and it is the only soft spot, every output carries its sensitivity (rho_lo/rho_hi)
rather than a single point estimate, and `aggregation_scaling()` below derives an independent,
data-driven estimate of it from public data as a cross-check.

Note the sign of the model's error: `e` is Normal by default, i.e. SYMMETRIC. Real farm-
specific shocks (hail, a localized storm, one flooded bottom field) are left-skewed, so the
Normal default UNDERSTATES basis risk. `idio="skewed"` draws a reflected-Gamma e with the same
variance and a negative skew; use it to see which way and how far that matters.

Step 4 — PRICE. For the RP variants both the farm and the county are multiplied by the SAME
harvest/projected price ratio, because price is national: every insured acre in the country
sees the same harvest price. That is why a revenue-triggered band carries LESS basis risk than
a yield-triggered one — the price leg cannot miss anybody. The price ratio is lognormal at the
volatility factor RMA publishes in the ADM, correlated with the county yield only through the
county's measured correlation to the NATIONAL yield (a small county's weather does not move
the board; the Corn Belt's does).

Step 5 — THE METRICS. At the producer's own coverage level CL and the band's trigger:

    farm loss    :=  farm revenue/yield ratio < CL          (a loss beyond their deductible)
    band pays    :=  county index < trigger

    miss_rate               = P(band pays nothing | farm loss)      <- THE HEADLINE
    p_hard_miss             = P(farm loss AND band pays nothing)    <- annual frequency
    p_farm_loss_given_no_pay= P(farm loss | county index above trigger)
    deep_miss_rate          = P(band pays nothing | farm loss 10+ points beyond CL)
    windfall_rate           = P(band pays | farm had NO loss)
    uncovered_share         = share of the farm's in-band loss DOLLARS left uncovered

`windfall_rate` is not a criticism of the product — those dollars are real income. But they are
a transfer, not insurance, and they are exactly the dollars that were not there in the years the
loss came and the cheque did not.

Step 5b — THERE ARE TWO COVERAGE LEVELS IN THIS MODEL AND THEY LIVE ON OPPOSITE SIDES
=====================================================================================
This is the single easiest thing to get wrong here, so it gets its own step. Two different
percentages both get called "coverage level" in the trade, and they enter the joint
distribution in different places:

  1. THE BAND'S TRIGGER — 0.95 / 0.90 / 0.86 (ECO95 / ECO90 / SCO86). RMA's number, fixed by
     the endorsement the producer elects, applied to the COUNTY index. It is the `band`
     argument, it lives in BAND_SPECS, and it is the COUNTY side of the joint distribution:
     `pays := county_ratio < trigger`. The producer's own election does not move it.

  2. THE PRODUCER'S OWN MPCI COVERAGE LEVEL — 0.50 to 0.85 in 5-point steps, their DEDUCTIBLE
     on their individual policy. It is the `coverage_level` argument and it is the FARM side:
     `farm loss := farm_ratio < coverage_level`. It defines what counts as a loss worth
     insuring against, i.e. what the miss_rate is conditioned ON. It never touches the county
     index.

    +-- county side (MEASURED) ------+       +-- farm side (MODELLED) -----------+
    |  county_ratio < band trigger   |       |  farm_ratio < coverage_level      |
    |  trigger = 0.95 / 0.90 / 0.86  |       |  coverage_level = 0.50 ... 0.85   |
    +--------------------------------+       +-----------------------------------+
                miss_rate  =  P( NOT county side | farm side )

  THE ONE EXCEPTION, and it is real: SCO EXITS AT THE PRODUCER'S OWN COVERAGE LEVEL. ECO's band
  is 0.86 -> trigger no matter who buys it, but SCO runs from 0.86 DOWN to the underlying
  election, so for SCO — and only SCO — the producer's level ALSO sets the county-side band's
  lower bound and therefore the band's width and its payment schedule. At CL 0.85 SCO is one
  coverage point wide; at CL 0.65 it is twenty-one. See `band_bounds`.

DIRECTION, because it is counter-intuitive at first reading. A LOWER producer coverage level
means a BIGGER deductible, so the farm losses that qualify are RARER and DEEPER — and a deep
farm loss is much more likely to have come from weather the whole county shared, which is
exactly when the county index fires. So:

    lower producer coverage level  ->  fewer qualifying farm losses  ->  LOWER miss_rate

Measured on a typical Corn Belt county (county CV 0.12, rho 0.70, RP), ECO95 miss_rate runs
13.1% at CL 0.85, 9.0% at 0.80, 5.5% at 0.75, 3.2% at 0.70, 1.7% at 0.65. SCO86 runs 42.9% /
34.6% / 25.9% / 18.2% / 12.2% over the same grid. The 0.85 end is the WORST case in the whole
grid, and it is what the shipped table used to be built at alone — see PUBLISHED_COVERAGE_LEVELS
and ELECTION_MIX below for what producers actually buy.

Step 6 — UNCERTAINTY. A county with 12 usable years supports a far weaker claim than one with
40. `bootstrap_miss_rate()` resamples YEARS (not draws), refits the trend on each resample and
re-runs the estimator, so the reported interval carries the shortness of the series. Counties
are graded A (>=30 years) / B (20-29) / C (12-19) and refused below 12.

WHO CONSUMES THIS, AND THE TWO SEAMS THE CONSUMER HAS TO KNOW ABOUT
===================================================================
`basis_risk_county` (scripts/analysis/build_basis_risk.py) is JOINED into the row-crop
opportunity ranking by src/rowcropopt.join_basis_risk() and drawn by src/rowcroppage.py, on
county x crop x band, as `unclaimed subsidy x (1 - miss_rate)` shown ALONGSIDE the raw figure.
Two seams matter to anyone reading that map, and both are documented in
docs/rowcrop_opportunity.md:

  * BAND vs TRIGGER. The opportunity table says SCO / ECO / MCO / STAX; this module says
    SCO86 / ECO90 / ECO95, because basis risk depends on the trigger. ECO maps to ECO95 (99.0%
    of the RY2026 ECO book elects the 95% trigger). MCO and STAX map to NOTHING — see below —
    and are carried as an explicit `unknown`, never as a borrowed neighbour's number.
  * COVERAGE LEVEL. `coverage_level` here is the FARM's own deductible (Step 5b), which is what
    defines "a farm loss". The table is now built across PUBLISHED_COVERAGE_LEVELS — 0.65, 0.70,
    0.75, 0.80, 0.85 — and `coverage_level` is part of its primary key, so a caller SELECTs the
    level it wants. It used to be built at 0.85 alone, which is the highest common election and
    therefore the HIGHEST miss rate in the grid; on the measured RY2025 election mix that
    over-stated the discount by a wide margin (see ELECTION_MIX). A consumer that still reads
    0.85 is being CONSERVATIVE, not wrong — it under-states opportunity. A consumer that wants
    the typical producer should read MODAL_COVERAGE_LEVEL, and one that wants the book should
    blend with `election_weights()`.

WHAT THIS MODULE DOES NOT DO
============================
* MCO. NOT MODELLED, and not because nobody got to it. MCO settles on a county MARGIN —
  expected crop value less an input-cost index of diesel, natural gas, urea, DAP and potash
  (26-MCO §1; docs/rowcrop_endorsement_stacking.md §3.3). That is a THIRD leg in the joint
  distribution, not a re-parameterization of the two here, and the leg has no history: RMA
  publishes the Expected Margin Amount per county in the ADM (record A00810), but MCO's first
  reinsurance year is 2026, so there is exactly ONE observation of it. Treating MCO as an area
  revenue band would look like an answer and be a guess in the wrong direction — the input-cost
  leg is national, like price, so it cannot miss anybody, while a farm's OWN input costs can
  and do differ from the index. No MCO rows are written; consumers see `unknown`.
  docs/basis_risk.md §8 sets out exactly what an MCO estimator would need.
* It does not model prevented planting, replant, or the quality adjustments that can make a
  farm's insurable loss differ from its yield loss.
* It has no farm-level data anywhere in it. See the honesty block above.

STAX IS MODELLED, AND IT IS A THIRD SHAPE — NOT ECO's AND NOT SCO's
===================================================================
Step 5b says the band's trigger is the COUNTY side and the producer's election is the FARM
side, with SCO the one exception because its EXIT slides down to the producer's own level.
STAX is neither case cleanly, so it gets its own paragraph. From the RMA Cotton Crop
Provisions, 16-STAX-0021 (quoted verbatim in docs/rowcrop_endorsement_stacking.md §3.4):

  §1 "Area loss trigger - The percentage of expected area revenue you choose, ranging from 90
      percent to 75 percent, below which an indemnity is paid..."
  §1 "Coverage range - A percentage of not less than 0 percent and not more than 20 percent,
      which represents the amount of the expected area revenue covered by STAX..."
  §10(b)(1) "The coverage range you elect for the type and practice added to the coverage
      level you have elected for the companion policy must not exceed the area loss trigger..."
  §10(b)(3) reduces the coverage range "in 5 percent increments" until that holds, and "If
      this reduction would result in a coverage range of less than 5 percent, no STAX coverage
      will be provided for that type or practice for the crop year."

So both halves are true at once:

  * THE TRIGGER IS COUNTY-SIDE, like ECO's. The producer picks it (0.90 / 0.85 / 0.80 / 0.75),
    but it is a percentage of expected AREA revenue and it is compared against the COUNTY. It
    is emphatically NOT their deductible, and it does not move when their deductible moves.
    That is why each trigger is its own BAND_SPECS entry (STAX90, ...), exactly like ECO95 and
    ECO90, rather than being derived from `coverage_level`.
  * THE EXIT IS FARM-SIDE-BOUNDED, like SCO's — but floored. §10(b)(1) is the same "you cannot
    insure below your own deductible" rule that gives SCO its sliding exit, so the exit rises
    to the companion policy's coverage level when that level is high. Unlike SCO it cannot
    slide indefinitely: the 20-point cap on the coverage range floors the exit at
    trigger - 0.20. At the 0.90 trigger, a 0.65 or 0.70 election both exit at 0.70 (the full
    20 points), 0.75 exits at 0.75 (15 points), 0.85 exits at 0.85 (5 points), and 0.90 is
    refused outright because §10(b)(3)(ii) voids a range under 5 points.

  Mechanically that is `exit = max(coverage_level, trigger - 0.20)`, and `band_bounds` applies
  it through the `max_width` / `min_width` keys rather than special-casing the band name.

  THE ELECTION IS MEASURED, NOT ASSUMED: 99.5% of RY2026 STAX acres elect the 0.90 trigger
  (STAX_TRIGGER_MIX below), which is why STAX90 is the entry the build ships. The Summary of
  Business also confirms the provisions from the sales side — plans 35/36 report coverage_level
  at 0.75/0.80/0.85/0.90 and nowhere else, which is §1's range exactly.

  THE PROTECTION FACTOR IS NOT IN ANY NUMBER HERE, AND THAT IS CORRECT. §5(a)(1) lets the
  producer scale liability "From a range of 80 percent to 120 percent" — the only product in
  this layer that can exceed 100%. But §5(e) applies it as the last multiplier on POLICY
  PROTECTION, i.e. it scales the dollars on both sides of every ratio this module computes.
  Every output here is a probability or a share, so the protection factor cancels out of all of
  them exactly. It changes how much a miss COSTS, never how often one happens. See
  PROTECTION_FACTOR_RANGE.

  STAX AND SCO CANNOT COVER THE SAME ACRE (§10(c)(1): "the same acreage cannot be covered by
  both STAX and SCO"), which is why src/rowcropopt.py treats them as an exclusive pair. Both
  bands are still estimated for every cotton county, because that is the choice a producer is
  actually making between.

UNITS: THE ONE LOADING ERROR THAT WOULD NOT SHOW UP IN ANY NUMBER HERE
======================================================================
Cotton and rice report in LB / ACRE; corn, soybeans and wheat report in BU / ACRE. Getting
that wrong is not a cosmetic error, and — this is the dangerous part — it is INVISIBLE to
every metric in this module. Step 1 divides the series by its own fitted trend, so `ratio` is
unitless and `cv`, `skew`, `miss_rate` and all the rest are EXACTLY scale-invariant: multiply
a whole yield series by 50 and not one probability here changes by a single digit. A unit
mix-up therefore produces a perfectly plausible-looking answer rather than an error.

It is not a hypothetical. NASS carries cotton at BOTH 'LB / ACRE' and 'LB / NET PLANTED ACRE',
and the second series' county values run 10-50x SMALLER than the first (Merced CA 1987: 119.3
vs ~1,150). Whatever NASS means by it, a county that picked it up would be detrended into a
completely reasonable CV.

The only place a unit error is visible is the LEVEL — `mean_yield`, the one column here that
is NOT scale-invariant. So that is where the guard lives: CROP_YIELD_UNIT pins the unit each
crop is loaded and selected at, and `check_yield_unit()` range-checks the fitted mean against
what that crop can physically yield. The builder refuses the county rather than writing it.
Never replace that check with one on `cv` — a rescaled series has an identical CV, which is
the whole reason this paragraph exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Bands. Verified against docs/rowcrop_endorsement_stacking.md and RMA MGR-25-006.
# ---------------------------------------------------------------------------
# ECO attaches at 86% and runs UP to its elected trigger (90% or 95%) of expected county
# revenue/yield. SCO runs from 86% DOWN to the producer's own underlying coverage level, so
# its width depends on the producer: at 85% RP, SCO is one coverage point wide.
#
# Keys:
#   trigger   - the COUNTY-side threshold. RMA's, never the producer's deductible.
#   exit      - fixed lower bound, or None when it slides down to the producer's own level.
#   max_width - statutory cap on trigger - exit, or None when uncapped. STAX only: 16-STAX-0021
#               §1 caps the coverage range at 20 points, which FLOORS the sliding exit at
#               trigger - 0.20 (see the STAX section of the module docstring).
#   min_width - the width below which the band is void rather than merely small. STAX only:
#               §10(b)(3)(ii) refuses a coverage range under 5 points. SCO has no such floor —
#               it is legitimately sold one point wide at an 0.85 election — so it stays None
#               and `band_bounds` refuses it only at zero width.
#   crops     - None for every crop, or the tuple of crops the band is offered on. STAX is
#               upland cotton ONLY (§2(a): "the insured crop will be all upland cotton"), so
#               writing a STAX row for corn would be a fabrication, not an approximation.
BAND_SPECS: dict[str, dict] = {
    "ECO95": {"trigger": 0.95, "exit": 0.86, "max_width": None, "min_width": None,
              "crops": None, "label": "ECO, 95% trigger"},
    "ECO90": {"trigger": 0.90, "exit": 0.86, "max_width": None, "min_width": None,
              "crops": None, "label": "ECO, 90% trigger"},
    "SCO86": {"trigger": 0.86, "exit": None, "max_width": None, "min_width": None,
              "crops": None, "label": "SCO (exits at the underlying level)"},
    # STAX at the 0.90 area loss trigger — 99.5% of the book (STAX_TRIGGER_MIX). The other
    # three triggers are real and selectable; they are simply not worth the rows until someone
    # asks. Adding one is a line here, because the shape is already parameterized.
    "STAX90": {"trigger": 0.90, "exit": None, "max_width": 0.20, "min_width": 0.05,
               "crops": ("Cotton",),
               "label": "STAX, 90% area loss trigger (upland cotton)"},
}

# 16-STAX-0021 §5(a)(1): "You must choose a protection factor: (1) From a range of 80 percent
# to 120 percent". §5(e) applies it as the final multiplier on policy protection — it scales
# LIABILITY DOLLARS, on both sides of every ratio computed here, so it cancels exactly out of
# every probability and every share this module reports. It is recorded because it is the
# single biggest lever on what a STAX miss COSTS, and omitting it from the docs would invite
# someone to "correct" for it in a number that already has no dependence on it.
PROTECTION_FACTOR_RANGE: tuple[float, float] = (0.80, 1.20)

# MEASURED. STAX's area loss trigger election, acre-weighted, from sob_national plans 35/36
# (RY2026; RY2025 and RY2024 both give 99.5-99.6% at 0.90 too). For plans 35/36 the Summary of
# Business `coverage_level` column carries STAX's own TRIGGER, not the producer's deductible —
# the same convention as ECO, and the opposite of SCO. That the only values it ever takes are
# 0.75/0.80/0.85/0.90 is an independent confirmation of the §1 range from the sales side.
STAX_TRIGGER_MIX: dict[float, float] = {0.75: 0.0040, 0.80: 0.0000,
                                        0.85: 0.0005, 0.90: 0.9954}

# ---------------------------------------------------------------------------
# The PRODUCER's coverage level — their own deductible, the FARM side. Not the band's
# trigger, which is RMA's and lives in BAND_SPECS above. See Step 5b of the module docstring.
# ---------------------------------------------------------------------------
# Every buy-up election RMA offers on the underlying MPCI policy (7 CFR 457.8 §3(c); the
# actuarials publish 0.50-0.85 in 5-point steps). CAT is 0.50 of a 55% price election and is a
# different animal — a CAT producer cannot buy SCO or ECO at all, so CAT is excluded from the
# election mixes below.
COVERAGE_LEVELS: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)

# The grid the shipped table is BUILT at. Five levels covering 95.0% of RY2025 corn/soybean/
# wheat buy-up acres and 95.2% of the acres of producers who actually bought SCO. The three
# levels below 0.65 are omitted on purpose: together they are 5.0% of the book, and snapping
# them up to 0.65 (`nearest_published_level`) over-states their basis risk, which is the safe
# direction. Each extra level costs ~5.3 MB in the shipped app DB (measured), so this is a
# budget decision as well as a modelling one — see docs/basis_risk.md, "Size discipline".
PUBLISHED_COVERAGE_LEVELS: tuple[float, ...] = (0.65, 0.70, 0.75, 0.80, 0.85)

# The single level to quote when only one number fits: the MODE of the election distribution,
# not the maximum. 35.6% of RY2025 corn/soy/wheat buy-up acres and 50.7% of SCO buyers' acres.
MODAL_COVERAGE_LEVEL = 0.75

# MEASURED election mixes. Source: sob_national (RMA Summary of Business, national rollup),
# reinsurance year 2025 — the last year with a complete sales season; 2026 is still filling.
# Acre-weighted (`net_acres`). Reproduce with:
#     .venv/bin/python scripts/analysis/build_basis_risk.py --election-mix
#
# ELECTION_MIX is the WHOLE underlying book: plan codes 01/02/03 (YP / RP / RP-HPE),
# coverage_type 'A' (buy-up). This is who COULD buy an endorsement.
ELECTION_MIX: dict[str, dict[float, float]] = {
    "Corn":     {0.50: 0.0222, 0.55: 0.0022, 0.60: 0.0215, 0.65: 0.0251,
                 0.70: 0.1249, 0.75: 0.3423, 0.80: 0.2964, 0.85: 0.1654},
    "Soybeans": {0.50: 0.0287, 0.55: 0.0027, 0.60: 0.0230, 0.65: 0.0222,
                 0.70: 0.1129, 0.75: 0.3456, 0.80: 0.3050, 0.85: 0.1600},
    "Wheat":    {0.50: 0.0113, 0.55: 0.0012, 0.60: 0.0371, 0.65: 0.0578,
                 0.70: 0.3159, 0.75: 0.4120, 0.80: 0.1165, 0.85: 0.0482},
    "ALL":      {0.50: 0.0227, 0.55: 0.0022, 0.60: 0.0249, 0.65: 0.0299,
                 0.70: 0.1549, 0.75: 0.3561, 0.80: 0.2671, 0.85: 0.1422},
}

# SCO_ELECTION_MIX is the sharper number and the one to prefer for an endorsement question.
# For plan codes 31/32/33 the Summary of Business reports coverage_level as the UNDERLYING
# policy's level, not SCO's 0.86 attachment — so this is a DIRECT measurement of the deductible
# carried by people who actually bought an area band, no inference required. It is available
# only for SCO: for ECO (87/88/89) and MCO (67/68/69) the same field carries the endorsement's
# own TRIGGER (0.90/0.95), so an ECO buyer's underlying level is not observable in the national
# rollup at all. SCO buyers are the best available proxy for ECO buyers.
SCO_ELECTION_MIX: dict[str, dict[float, float]] = {
    "Corn":     {0.50: 0.0302, 0.55: 0.0042, 0.60: 0.0383, 0.65: 0.0107,
                 0.70: 0.1303, 0.75: 0.4763, 0.80: 0.2836, 0.85: 0.0262},
    "Soybeans": {0.50: 0.0117, 0.55: 0.0030, 0.60: 0.0302, 0.65: 0.0107,
                 0.70: 0.1096, 0.75: 0.5143, 0.80: 0.2840, 0.85: 0.0365},
    "Wheat":    {0.50: 0.0073, 0.55: 0.0002, 0.60: 0.0118, 0.65: 0.0273,
                 0.70: 0.2642, 0.75: 0.5397, 0.80: 0.1397, 0.85: 0.0099},
    "ALL":      {0.50: 0.0183, 0.55: 0.0025, 0.60: 0.0273, 0.65: 0.0166,
                 0.70: 0.1737, 0.75: 0.5065, 0.80: 0.2326, 0.85: 0.0225},
}

# THE HEADLINE FROM THOSE TWO TABLES: 0.85 — the level the shipped table used to be built at
# ALONE — is 14.2% of the underlying book and 2.3% of SCO buyers. It is the tail of the
# election distribution, not its centre, and it is the worst-case end of the miss-rate grid.
SHARE_AT_MAX_LEVEL = 0.1422           # ELECTION_MIX["ALL"][0.85]
SHARE_AT_MAX_LEVEL_SCO = 0.0225       # SCO_ELECTION_MIX["ALL"][0.85]

# ECO's TRIGGER election, for the band mapping rather than the deductible: 98.95% of RY2026 ECO
# acres (99.52% of liability) elect the 95% trigger, which is why src/rowcropopt.py maps ECO to
# ECO95 first. Same source, RY2026 all crops.
ECO_TRIGGER_MIX: dict[float, float] = {0.90: 0.0105, 0.95: 0.9895}

# Farm-county yield correlation. THE one parameter this module imports from outside the data.
# See docs/basis_risk.md for the sources and for the sensitivity of every output to it.
#
# THE LOW END IS 0.35, NOT 0.55, AND THAT CHANGE IS EMPIRICAL. src/basisrisk_empirical.py
# counts what actually happened instead of simulating it: across 2015-2024, 1,460,637
# individual policies collected an indemnity and 815,129 of them sat in a county-year where
# the area band paid NOTHING — a 55.8% miss rate, against the ~36% this module simulates at
# rho 0.70. Inverting the simulator on that target implies rho 0.34 for corn and 0.28 for
# soybeans at one unit, 0.47 and 0.39 at two. Your book is ~1.5 effective units. Wheat lands
# at 0.58-0.72 and is the only crop the old band contained.
#
# The old band's floor was therefore too high for the two crops that carry most of the
# acreage, and every output at RHO_LO was correspondingly optimistic.
#
# RHO_REF STAYS AT 0.70 on purpose. The measured window contains none of the six systemic
# years in the 36-year record (1989, 1991, 1992, 1993, 2002, 2012) against a 16.7% base rate,
# and a systemic year is by definition one the index FIRES — so the observation is drawn from
# precisely the decade that flatters local, scattered losses and penalises an area trigger.
# Correcting for that puts the true miss at 46.5-55.8% rather than 55.8%. That is enough to
# say the floor was wrong; it is not enough to move the centre.
#
# Read RHO_LO as "what the record actually did in a drought-free decade", not as a tail.
RHO_REF = 0.70
RHO_LO = 0.35
RHO_HI = 0.85

# Depth below the deductible that counts as a "deep" loss for deep_miss_rate, in coverage points.
DEEP_LOSS_MARGIN = 0.10

MIN_YEARS = 12          # below this we refuse to publish a county metric at all
GRADE_A_YEARS = 30
GRADE_B_YEARS = 20


def grade_for(n_years: int) -> str | None:
    """A/B/C data grade from series length, or None when too short to publish.

    `grade` is DATA QUALITY — how many years of county history stand behind the row — and
    never a risk level. A grade-A county can have terrible basis risk and a grade-C county
    almost none; the grade says only how much evidence there is.
    """
    if n_years >= GRADE_A_YEARS:
        return "A"
    if n_years >= GRADE_B_YEARS:
        return "B"
    if n_years >= MIN_YEARS:
        return "C"
    return None


# ===========================================================================
# Coverage levels — selecting, snapping and blending on the FARM side
# ===========================================================================

def cl_key(coverage_level: float) -> float:
    """Canonical key for a coverage level: 0.7000000001 and 0.7 must be the same row.

    coverage_level is part of basis_risk_county's PRIMARY KEY and it is a REAL, so a caller
    that arrives at 0.75 by arithmetic rather than by literal must still hit the row. Two
    decimal places is exactly RMA's granularity (5-point steps).
    """
    return round(float(coverage_level), 2)


def nearest_published_level(coverage_level: float,
                            levels: Sequence[float] = PUBLISHED_COVERAGE_LEVELS) -> float:
    """Snap a producer's own election onto the grid the table was built at.

    Snaps UP, not to the nearest. Miss rate rises with the coverage level (Step 5b), so
    rounding a 0.60 producer up to the published 0.65 OVER-states their basis risk and
    UNDER-states the opportunity — the same conservative direction the rest of this module
    errs in. Above the top of the grid it clamps to the top, which is the worst case anyway.
    """
    grid = sorted(cl_key(x) for x in levels)
    if not grid:
        raise ValueError("no published coverage levels")
    cl = cl_key(coverage_level)
    for g in grid:
        if g >= cl - 1e-9:
            return g
    return grid[-1]


def election_weights(crop: str = "ALL", *, book: str = "sco",
                     levels: Sequence[float] = PUBLISHED_COVERAGE_LEVELS) -> dict[float, float]:
    """Measured election weights, folded onto `levels` and renormalized to sum to 1.

    book="sco"  — SCO_ELECTION_MIX, the deductibles carried by producers who actually bought an
                  area band. The right weighting for an endorsement question, and the only one
                  measured directly rather than inferred (see the constant's comment).
    book="all"  — ELECTION_MIX, the whole underlying buy-up book: who COULD buy one.

    Levels off the grid are folded into `nearest_published_level` of themselves, so no acre is
    dropped and the sub-0.65 tail lands on 0.65 rather than vanishing.
    """
    src = {"sco": SCO_ELECTION_MIX, "all": ELECTION_MIX}.get(book)
    if src is None:
        raise ValueError(f"unknown book {book!r}; use 'sco' or 'all'")
    mix = src.get(crop) or src["ALL"]
    grid = [cl_key(x) for x in levels]
    out = {g: 0.0 for g in grid}
    for cl, w in mix.items():
        out[nearest_published_level(cl, grid)] += float(w)
    total = sum(out.values())
    if total <= 0:
        raise ValueError("election mix sums to zero")
    return {k: v / total for k, v in out.items()}


def blend_over_coverage_levels(by_level: dict[float, float], crop: str = "ALL", *,
                               book: str = "sco") -> float:
    """Election-weighted mean of a per-coverage-level quantity (usually miss_rate).

    `by_level` is {coverage_level: value} — e.g. the five miss_rates for one county x crop x
    band. Missing or NaN levels are dropped and the remaining weights renormalized, so a
    partial build still returns something honest rather than a hole.

    This is the number to quote for "the book", not for a person: a real producer has ONE
    deductible and should be shown the row at THEIR level. The blend exists so that a national
    or county rollup is not silently quoted at the worst level in the grid.
    """
    vals = {cl_key(k): float(v) for k, v in by_level.items()
            if v is not None and not math.isnan(float(v))}
    if not vals:
        return float("nan")
    w = election_weights(crop, book=book, levels=tuple(sorted(vals)))
    tot = sum(w.get(k, 0.0) for k in vals)
    if tot <= 0:
        return float(sum(vals.values()) / len(vals))
    return float(sum(vals[k] * w.get(k, 0.0) for k in vals) / tot)


# ===========================================================================
# Detrending
# ===========================================================================

@dataclass
class TrendFit:
    """A detrended yield series. `ratio` is what everything downstream works in."""
    method: str
    n: int
    year_min: int
    year_max: int
    years: np.ndarray
    values: np.ndarray
    fitted: np.ndarray
    ratio: np.ndarray            # values / fitted, mean ~1
    slope: float                 # yield units per year
    intercept: float
    r2: float
    mean_yield: float
    pct_per_year: float          # slope as a share of mean fitted yield
    cv: float                    # SD of `ratio` — the detrended county yield risk
    skew: float

    def ratio_by_year(self) -> dict[int, float]:
        return {int(y): float(r) for y, r in zip(self.years, self.ratio)}


def _theilsen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Median of pairwise slopes, then median intercept. Robust to a few disaster years."""
    n = len(x)
    slopes = []
    for i in range(n - 1):
        dx = x[i + 1:] - x[i]
        ok = dx != 0
        if ok.any():
            slopes.append((y[i + 1:][ok] - y[i]) / dx[ok])
    if not slopes:
        return 0.0, float(np.median(y))
    slope = float(np.median(np.concatenate(slopes)))
    return slope, float(np.median(y - slope * x))


def detrend(years: Sequence[int], values: Sequence[float], method: str = "ols") -> TrendFit:
    """Fit a technology trend and return the series as a ratio to it.

    Raises ValueError for a series too short, non-positive yields, or an unknown method. A
    fitted trend that goes non-positive anywhere is refused rather than silently producing an
    enormous ratio — that only happens on a pathological series and should be seen, not hidden.
    """
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError("years and values must be 1-D and the same length")
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(x) < 3:
        raise ValueError(f"need at least 3 years to detrend, got {len(x)}")
    if (y <= 0).any():
        raise ValueError("yields must be positive")

    if method == "ols":
        slope, intercept = np.polyfit(x, y, 1)
    elif method == "theilsen":
        slope, intercept = _theilsen(x, y)
    elif method == "mean":
        slope, intercept = 0.0, float(y.mean())
    else:
        raise ValueError(f"unknown detrend method: {method!r}")

    fitted = intercept + slope * x
    if (fitted <= 0).any():
        raise ValueError("fitted trend is non-positive somewhere in the series")

    ratio = y / fitted
    resid = y - fitted
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    mean_fitted = float(fitted.mean())
    sd = float(ratio.std(ddof=1)) if len(ratio) > 1 else 0.0
    return TrendFit(
        method=method, n=len(x), year_min=int(x[0]), year_max=int(x[-1]),
        years=x.astype(int), values=y, fitted=fitted, ratio=ratio,
        slope=float(slope), intercept=float(intercept), r2=r2,
        mean_yield=float(y.mean()),
        pct_per_year=float(slope) / mean_fitted if mean_fitted else 0.0,
        cv=sd, skew=_skew(ratio),
    )


def _skew(a: np.ndarray) -> float:
    a = np.asarray(a, float)
    n = len(a)
    if n < 3:
        return 0.0
    s = a.std(ddof=0)
    if s <= 0:
        return 0.0
    return float(((a - a.mean()) ** 3).mean() / s ** 3)


# ===========================================================================
# Simulation
# ===========================================================================

def smoothed_bootstrap(rng: np.random.Generator, ratios: Sequence[float], n: int) -> np.ndarray:
    """Variance-corrected smoothed bootstrap of an observed ratio series.

    A plain bootstrap of 40 observations can only ever return those 40 values, which makes
    every threshold probability a step function of the trigger. Adding a Gaussian kernel fixes
    that; dividing by sqrt(1 + h^2/s^2) puts the variance back to the sample variance, so the
    smoothing does not quietly inflate the county's risk (Silverman & Young 1987).
    """
    x = np.asarray(ratios, dtype=float)
    if len(x) == 0:
        raise ValueError("no ratios to resample")
    m = float(x.mean())
    s = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    draws = x[rng.integers(0, len(x), n)]
    if s <= 0:
        return draws
    h = 1.06 * s * len(x) ** (-0.2)                      # Silverman's rule of thumb
    eps = rng.standard_normal(n) * h
    return m + (draws - m + eps) / math.sqrt(1.0 + (h * h) / (s * s))


def _idio(rng: np.random.Generator, n: int, sigma: float, kind: str, skew: float) -> np.ndarray:
    """Mean-zero idiosyncratic farm shock with the requested SD and shape."""
    if sigma <= 0:
        return np.zeros(n)
    if kind == "normal":
        return rng.standard_normal(n) * sigma
    if kind == "skewed":
        # Reflected Gamma: mean 0, SD `sigma`, skewness -2/sqrt(k). Solve k from `skew`.
        k = max(0.5, 4.0 / (skew * skew)) if skew else 4.0
        theta = sigma / math.sqrt(k)
        return -(rng.gamma(k, theta, n) - k * theta)
    raise ValueError(f"unknown idiosyncratic shape: {kind!r}")


@dataclass
class BasisRisk:
    """Every probability is an ANNUAL frequency for a TYPICAL farm in the county."""
    band: str
    plan_type: str
    coverage_level: float        # the PRODUCER's own MPCI deductible — the FARM side (Step 5b)
    trigger: float               # the BAND's county trigger — RMA's, the COUNTY side
    exit: float                  # 0.86 for ECO; the producer's coverage level for SCO
    rho: float
    county_cv: float
    farm_cv: float
    n_draws: int
    # -- the numbers ---------------------------------------------------------
    p_farm_loss: float
    p_band_pays: float
    p_hard_miss: float
    miss_rate: float
    p_farm_loss_given_no_pay: float
    deep_miss_rate: float
    p_deep_loss: float
    windfall_rate: float
    uncovered_share: float
    windfall_share: float
    payout_corr: float
    expected_payment_per_dollar: float
    clipped_share: float          # draws where farm yield hit the 0 floor (should be ~0)

    def as_dict(self) -> dict:
        return asdict(self)


def band_bounds(band: str, coverage_level: float) -> tuple[float, float]:
    """(exit, trigger) for a band at a producer's coverage level. Raises if degenerate.

    The TRIGGER is RMA's and never moves: 0.95 / 0.90 / 0.86. The EXIT is 0.86 for both ECO
    variants and the PRODUCER'S OWN coverage level for SCO — the one place where the farm-side
    election reaches across into the county side (Step 5b). So SCO86 is 1 point wide at a 0.85
    election, 11 at 0.75 and 21 at 0.65, and is refused outright at 0.86 and above, where there
    is literally nothing left to buy.

    STAX slides like SCO but cannot slide past 20 points (`max_width`), and is void rather than
    narrow below 5 points (`min_width`) — 16-STAX-0021 §1 and §10(b)(3). At the 0.90 trigger
    that makes 0.65 and 0.70 elections identical (both exit at 0.70, the full 20-point range),
    0.75 a 15-point band, 0.85 a 5-point band, and 0.90 void. See the module docstring.

    The 5-point stepping in §10(b)(3)(i) is applied, not glossed: the coverage range is reduced
    in whole 5-point increments, so a producer at an off-grid 0.78 gets a 10-point range
    exiting at 0.80 — ABOVE their own deductible, leaving a 2-point gap they carry themselves.
    Every level in COVERAGE_LEVELS is on the 5-point grid, so this only bites off-grid callers,
    and it errs toward a narrower band, which is the conservative direction.
    """
    spec = BAND_SPECS.get(band)
    if spec is None:
        raise ValueError(f"unknown band {band!r}; known: {sorted(BAND_SPECS)}")
    trigger = spec["trigger"]
    exit_ = spec["exit"] if spec["exit"] is not None else coverage_level
    max_width = spec.get("max_width")
    if max_width is not None:
        # The elected range is capped AND quantized to 5-point steps, then the exit follows.
        width = min(max_width, math.floor((trigger - exit_) / 0.05 + 1e-9) * 0.05)
        exit_ = round(trigger - max(0.0, width), 10)
    min_width = spec.get("min_width") or 0.0
    width = trigger - exit_
    if width <= 0 or width < min_width - 1e-9:
        raise ValueError(
            f"{band} has zero width at coverage level {coverage_level:.2f} "
            f"(exit {exit_:.2f} >= trigger {trigger:.2f}) — there is nothing to buy"
            + (f"; its minimum coverage range is {min_width:.0%}" if min_width else ""))
    return exit_, trigger


def band_covers_crop(band: str, crop: str) -> bool:
    """Is `band` actually sold on `crop`? STAX is upland cotton only (16-STAX-0021 §2(a)).

    The builder asks this before writing a row. A STAX row for corn would not be a rough
    estimate of anything — the product does not exist for corn — and `unknown` is the honest
    output for a cell with no product in it.
    """
    spec = BAND_SPECS.get(band)
    if spec is None:
        raise ValueError(f"unknown band {band!r}; known: {sorted(BAND_SPECS)}")
    crops = spec.get("crops")
    return crops is None or crop in crops


def basis_risk(
    county_ratios: Sequence[float],
    *,
    band: str = "ECO95",
    coverage_level: float = 0.85,
    rho: float = RHO_REF,
    plan_type: str = "RP",
    price_vol: float = 0.15,
    corr_county_national: float = 0.5,
    corr_national_price: float = -0.6,
    idio: str = "normal",
    idio_skew: float = 1.0,
    n_draws: int = 200_000,
    seed: int = 7,
    rng: np.random.Generator | None = None,
) -> BasisRisk:
    """Estimate basis risk for one county x band x coverage level.

    `county_ratios` are DETRENDED county yield ratios (TrendFit.ratio) — pass raw yields here
    and every number will be wrong, inflated by the technology trend.

    `coverage_level` is the PRODUCER's own MPCI deductible (Step 5b), not the band's trigger.
    The default stays 0.85 because it is the conservative end of the grid — the most basis risk
    any buy-up producer can have — but it describes only 14.2% of the underlying book and 2.3%
    of the people who actually bought SCO. Pass the producer's own level when you know it,
    MODAL_COVERAGE_LEVEL (0.75) for a typical one, or sweep PUBLISHED_COVERAGE_LEVELS and
    combine with `blend_over_coverage_levels` for a book-level figure.

    The correlation between the county yield and the harvest price is not assumed directly. It
    is built as `corr_county_national * corr_national_price`: price responds to the NATIONAL
    crop, and a county participates in that only to the extent its own yield moves with the
    nation's. `corr_county_national` is MEASURED per county from the NASS data;
    `corr_national_price` is the single assumed national natural-hedge parameter.
    """
    d = draw_joint(county_ratios, rho=rho, plan_type=plan_type, price_vol=price_vol,
                   corr_county_national=corr_county_national,
                   corr_national_price=corr_national_price, idio=idio, idio_skew=idio_skew,
                   n_draws=n_draws, seed=seed, rng=rng)
    return metrics_from_draws(
        d.farm_ratio, d.county_ratio, band=band, coverage_level=coverage_level,
        plan_type=plan_type, rho=rho, county_cv=d.county_cv, farm_cv=d.farm_cv,
        clipped_share=d.clipped_share,
    )


@dataclass
class JointDraws:
    """One simulated joint sample of (farm, county) outcome ratios, reusable across bands."""
    farm_ratio: np.ndarray
    county_ratio: np.ndarray
    county_cv: float
    farm_cv: float
    clipped_share: float
    rho: float
    plan_type: str


def draw_joint(
    county_ratios: Sequence[float],
    *,
    rho: float = RHO_REF,
    plan_type: str = "RP",
    price_vol: float = 0.15,
    corr_county_national: float = 0.5,
    corr_national_price: float = -0.6,
    idio: str = "normal",
    idio_skew: float = 1.0,
    n_draws: int = 200_000,
    seed: int = 7,
    rng: np.random.Generator | None = None,
) -> JointDraws:
    """Simulate the joint (farm, county) outcome. Split out so one sample serves every band.

    The county draw, the farm's idiosyncratic shock and the price shock do not depend on the
    band or on the producer's coverage level — only the thresholds do. Building the sample once
    and reading every band off it is what makes a national build tractable, and it has the side
    benefit that the bands are compared on IDENTICAL weather, not on independent simulations.
    """
    if rng is None:
        rng = np.random.default_rng(seed)
    if not 0.0 < rho <= 1.0:
        raise ValueError(f"rho must be in (0, 1], got {rho}")
    if plan_type not in ("RP", "YP"):
        raise ValueError(f"plan_type must be RP or YP, got {plan_type!r}")

    ratios = np.asarray(county_ratios, dtype=float)
    sigma_c = float(ratios.std(ddof=1)) if len(ratios) > 1 else 0.0
    y_c = smoothed_bootstrap(rng, ratios, n_draws)

    # Farm = county + idiosyncratic. sigma_farm = sigma_county / rho, so the idiosyncratic
    # variance is the difference. rho == 1 collapses this to zero: the farm IS the county.
    sigma_e = sigma_c * math.sqrt(max(0.0, 1.0 / (rho * rho) - 1.0))
    y_f_raw = y_c + _idio(rng, n_draws, sigma_e, idio, idio_skew)
    y_f = np.clip(y_f_raw, 0.0, None)
    clipped_share = float((y_f_raw < 0).mean())

    if plan_type == "RP" and price_vol > 0:
        rho_yp = float(np.clip(corr_county_national * corr_national_price, -0.99, 0.99))
        # Gaussian copula between the county draw's rank and the price shock. The rank comes
        # from the county's OWN 40-odd observations (searchsorted), not from an argsort of the
        # whole draw: same linkage, and it keeps a national build to minutes rather than hours.
        srt = np.sort(ratios)
        u = (np.searchsorted(srt, y_c, side="left") + 0.5) / len(srt)
        z_c = _norm_ppf(np.clip(u, 1e-6, 1 - 1e-6))
        z_p = rho_yp * z_c + math.sqrt(max(0.0, 1.0 - rho_yp * rho_yp)) * rng.standard_normal(n_draws)
        sig = math.sqrt(math.log(1.0 + price_vol * price_vol))
        p = np.exp(sig * z_p - 0.5 * sig * sig)
        # RP recomputes the guarantee at the HIGHER of projected/harvest price, so price
        # upside is neutralized in the index and only price downside bites.
        adj = np.maximum(1.0, p)
        r_c = y_c * p / adj
        r_f = y_f * p / adj
    else:
        r_c, r_f = y_c, y_f

    return JointDraws(farm_ratio=r_f, county_ratio=r_c, county_cv=sigma_c,
                      farm_cv=sigma_c / rho, clipped_share=clipped_share,
                      rho=rho, plan_type=plan_type)


def metrics_from_draws(
    farm_ratio: Sequence[float],
    county_ratio: Sequence[float],
    *,
    band: str = "ECO95",
    coverage_level: float = 0.85,
    plan_type: str = "RP",
    rho: float = float("nan"),
    county_cv: float = float("nan"),
    farm_cv: float = float("nan"),
    clipped_share: float = 0.0,
) -> BasisRisk:
    """Turn a joint sample of (farm, county) outcome ratios into the basis-risk metrics.

    Separated from the simulation on purpose: this is the part that defines what each number
    MEANS, and it is testable against hand-constructed joint samples with no model in the way.
    Two limits pin it down, and both are asserted in tests/test_basisrisk.py:
      * farm == county exactly  ->  miss_rate == 0. The index cannot miss a farm it IS.
      * farm independent of county -> miss_rate == P(county index >= trigger), because
        knowing the farm lost tells you nothing about whether the county did.

    THIS is also where the two coverage levels meet, and where the split is easiest to see in
    code: `coverage_level` is compared against `farm_ratio` and NOTHING ELSE, while `trigger`
    (from `band`) is compared against `county_ratio`. Sweeping coverage levels over ONE
    JointDraws sample is therefore exact, not an approximation — the draws do not depend on the
    producer's deductible at all. For ECO that also means the purely county-side outputs
    (p_band_pays, uncovered_share, payout_corr, expected_payment_per_dollar) are identical at
    every coverage level; for SCO they are not, because the exit moves with the election.
    """
    r_f = np.asarray(farm_ratio, dtype=float)
    r_c = np.asarray(county_ratio, dtype=float)
    if r_f.shape != r_c.shape:
        raise ValueError("farm and county samples must be the same length")
    exit_, trigger = band_bounds(band, coverage_level)
    width = trigger - exit_

    farm_loss = r_f < coverage_level
    deep_loss = r_f < (coverage_level - DEEP_LOSS_MARGIN)
    pays = r_c < trigger
    payment = np.clip(trigger - r_c, 0.0, width)
    farm_band_loss = np.clip(trigger - r_f, 0.0, width)
    shortfall = farm_band_loss - payment

    n_loss = int(farm_loss.sum())
    n_deep = int(deep_loss.sum())
    n_nopay = int((~pays).sum())
    n_ok = int((~farm_loss).sum())
    fbl_mean = float(farm_band_loss.mean())
    pay_mean = float(payment.mean())

    return BasisRisk(
        band=band, plan_type=plan_type, coverage_level=coverage_level,
        trigger=trigger, exit=exit_, rho=rho,
        county_cv=county_cv, farm_cv=farm_cv, n_draws=len(r_f),
        p_farm_loss=float(farm_loss.mean()),
        p_band_pays=float(pays.mean()),
        p_hard_miss=float((farm_loss & ~pays).mean()),
        miss_rate=float((farm_loss & ~pays).sum() / n_loss) if n_loss else float("nan"),
        p_farm_loss_given_no_pay=float((farm_loss & ~pays).sum() / n_nopay) if n_nopay else 0.0,
        deep_miss_rate=float((deep_loss & ~pays).sum() / n_deep) if n_deep else float("nan"),
        p_deep_loss=float(deep_loss.mean()),
        windfall_rate=float((~farm_loss & pays).sum() / n_ok) if n_ok else 0.0,
        uncovered_share=float(np.clip(shortfall, 0, None).mean() / fbl_mean) if fbl_mean > 0 else 0.0,
        windfall_share=float(np.clip(-shortfall, 0, None).mean() / pay_mean) if pay_mean > 0 else 0.0,
        payout_corr=_safe_corr(farm_band_loss, payment),
        expected_payment_per_dollar=pay_mean / width if width > 0 else 0.0,
        clipped_share=clipped_share,
    )


def _norm_ppf(u: np.ndarray) -> np.ndarray:
    """Inverse standard normal CDF. scipy if present, Acklam's rational approximation if not."""
    try:
        from scipy.stats import norm
        return norm.ppf(u)
    except Exception:                                        # pragma: no cover - fallback
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        u = np.clip(np.asarray(u, float), 1e-12, 1 - 1e-12)
        out = np.empty_like(u)
        lo, hi = u < 0.02425, u > 1 - 0.02425
        mid = ~(lo | hi)
        q = np.sqrt(-2 * np.log(u[lo]))
        out[lo] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = np.sqrt(-2 * np.log(1 - u[hi]))
        out[hi] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = u[mid] - 0.5
        r = q * q
        out[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
        return out


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    sa, sb = float(np.std(a)), float(np.std(b))
    if sa <= 0 or sb <= 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


# ===========================================================================
# Uncertainty from the length of the county series
# ===========================================================================

def bootstrap_miss_rate(
    years: Sequence[int],
    values: Sequence[float],
    *,
    n_boot: int = 200,
    detrend_method: str = "ols",
    n_draws: int = 20_000,
    seed: int = 11,
    ci: float = 0.90,
    **kw,
) -> tuple[float, float, float]:
    """(point, lo, hi) for miss_rate, resampling YEARS to carry the series' shortness.

    Resampling years and REFITTING the trend on each resample is the point: it propagates both
    the sampling error in the county's yield distribution and the estimation error in the
    trend. A 12-year county and a 45-year county get visibly different intervals, which is the
    whole reason this exists.
    """
    rng = np.random.default_rng(seed)
    x = np.asarray(years, int)
    y = np.asarray(values, float)
    n = len(x)
    point = basis_risk(detrend(x, y, detrend_method).ratio, n_draws=n_draws, seed=seed, **kw).miss_rate

    got: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        xi, yi = x[idx], y[idx]
        # A resample can repeat years; jitter identical x so the trend fit stays determined.
        if len(np.unique(xi)) < 3:
            continue
        try:
            fit = detrend(xi, yi, detrend_method)
        except ValueError:
            continue
        try:
            got.append(basis_risk(fit.ratio, n_draws=n_draws,
                                  rng=np.random.default_rng(rng.integers(1 << 31)), **kw).miss_rate)
        except ValueError:
            continue
    if len(got) < 10:
        return point, float("nan"), float("nan")
    a = (1 - ci) / 2
    arr = np.array([g for g in got if not math.isnan(g)])
    if len(arr) < 10:
        return point, float("nan"), float("nan")
    return point, float(np.quantile(arr, a)), float(np.quantile(arr, 1 - a))


# ===========================================================================
# Independent, data-driven check on rho: how variance decays with aggregation
# ===========================================================================

@dataclass
class ScalingFit:
    """log(variance of detrended yield) regressed on log(area). See `aggregation_scaling`."""
    exponent: float          # d log(var) / d log(area); negative
    intercept: float
    r2: float
    n_levels: int
    points: list[tuple[str, float, float]]   # (level, mean area, mean variance)
    implied_rho: float | None
    farm_acres: float
    county_acres: float

    def rho_for(self, farm_acres: float, county_acres: float) -> float:
        """rho = sigma_county / sigma_farm implied by the fitted scaling law."""
        var_ratio = (county_acres / farm_acres) ** self.exponent      # var_c / var_f
        return float(min(1.0, math.sqrt(max(1e-9, var_ratio))))


def aggregation_scaling(
    level_variances: dict[str, Sequence[float]],
    level_areas: dict[str, float],
    *,
    farm_acres: float = 500.0,
    county_acres: float = 100_000.0,
) -> ScalingFit:
    """Fit var(detrended yield) ~ area^exponent across aggregation levels, and imply rho.

    WHY THIS EXISTS. rho is the one parameter the county data cannot supply, and taking it
    purely on the literature's word leaves the whole result resting on a citation. But NASS
    publishes the SAME yield at four nested aggregation levels — county, agricultural district,
    state, nation — and yield variance falls in a regular way as the reporting unit grows,
    because independent local shocks average out. Fitting that decay over the three orders of
    magnitude we CAN observe, then extrapolating one order further down to farm scale, gives an
    estimate of sigma_farm/sigma_county — and therefore of rho — from public data alone.

    WHAT IT IS NOT. This is an extrapolation BEYOND the observed range, and it assumes the
    power law that holds between county and nation keeps holding between farm and county. It
    does not: within-county spatial correlation is much higher than between-state correlation,
    so the extrapolation OVERSTATES how much variance a farm-to-county step removes and
    therefore UNDERSTATES sigma_farm — i.e. it is biased toward too HIGH a rho and too LITTLE
    basis risk. Treat the number it returns as a lower bound on basis risk and a sanity check
    on the literature value, never as a replacement for it. The lineage is Marra & Schurle's
    reference-unit-size work on Kansas wheat; see docs/basis_risk.md.
    """
    pts: list[tuple[str, float, float]] = []
    for level, variances in level_variances.items():
        area = level_areas.get(level)
        v = [float(x) for x in variances if x is not None and x > 0]
        if area and area > 0 and v:
            pts.append((level, float(area), float(np.median(v))))
    if len(pts) < 2:
        raise ValueError("need at least two aggregation levels with data")
    pts.sort(key=lambda p: p[1])
    la = np.log(np.array([p[1] for p in pts]))
    lv = np.log(np.array([p[2] for p in pts]))
    slope, intercept = np.polyfit(la, lv, 1)
    pred = intercept + slope * la
    ss_tot = float(((lv - lv.mean()) ** 2).sum())
    r2 = 1.0 - float(((lv - pred) ** 2).sum()) / ss_tot if ss_tot > 0 else 1.0
    fit = ScalingFit(exponent=float(slope), intercept=float(intercept), r2=r2,
                     n_levels=len(pts), points=pts, implied_rho=None,
                     farm_acres=farm_acres, county_acres=county_acres)
    fit.implied_rho = fit.rho_for(farm_acres, county_acres)
    return fit


# ===========================================================================
# THE FARM CALCULATOR — the path from a generic map to a real answer
# ===========================================================================

@dataclass
class FarmBasisRisk:
    """A producer's OWN basis risk, from their OWN APH yields. No private data required."""
    crop: str
    county_fips: str
    n_common_years: int
    years: list[int]
    farm_yields: list[float]
    county_yields: list[float]
    farm_detrend: str
    farm_trend_pct_per_year: float
    farm_cv: float
    county_cv: float
    county_n_years: int
    # -- the producer's own correlation, MEASURED -----------------------------
    rho_measured: float
    rho_ci_lo: float
    rho_ci_hi: float
    rho_implied_by_cv: float          # sigma_county/sigma_farm — the aggregation-identity check
    rho_used: float
    # -- what actually happened on this farm ---------------------------------
    farm_shortfall_years: list[int]        # farm ratio below its coverage level
    farm_shortfall_freq: float
    historical_miss_years: list[int]       # farm lost AND county index would not have paid
    historical_pay_years: list[int]        # county index would have paid
    historical_windfall_years: list[int]   # county paid, farm had no loss
    # -- modelled at the producer's own rho ----------------------------------
    modelled: BasisRisk
    modelled_rho_lo: BasisRisk
    modelled_rho_hi: BasisRisk
    warnings: list[str] = field(default_factory=list)


def _fisher_ci(r: float, n: int, ci: float = 0.90) -> tuple[float, float]:
    """Fisher z confidence interval for a correlation. Wide at APH sample sizes — that is the point."""
    if n < 4 or abs(r) >= 1.0:
        return float("nan"), float("nan")
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    # 90% -> 1.6449, 95% -> 1.9600
    crit = 1.6449 if abs(ci - 0.90) < 1e-9 else 1.9600
    lo, hi = z - crit * se, z + crit * se
    return math.tanh(lo), math.tanh(hi)


def farm_basis_risk(
    farm_years: Sequence[int],
    farm_yields: Sequence[float],
    county_years: Sequence[int],
    county_yields: Sequence[float],
    *,
    crop: str = "",
    county_fips: str = "",
    band: str = "ECO95",
    coverage_level: float = 0.85,
    detrend_method: str = "ols",
    farm_detrend: str = "county",       # county | own | none
    plan_type: str = "RP",
    price_vol: float = 0.15,
    corr_county_national: float = 0.5,
    corr_national_price: float = -0.6,
    n_draws: int = 200_000,
    seed: int = 7,
    rho_override: float | None = None,
) -> FarmBasisRisk:
    """Compute a producer's OWN basis risk from their APH yield history.

    THIS is the deliverable that turns a generic county map into farm-specific advice. The
    producer reads a short series off their own APH/production schedule; everything else comes
    from data we already hold.

    farm_detrend:
      "county" (default) — remove the COUNTY's estimated %/year technology trend from the farm
        series. An APH series is typically 4-10 years, which is far too short to fit a trend to
        without the fit eating the very variability we are trying to measure; the county trend
        is estimated from 40+ years and a farm in that county shares its technology.
      "own" — fit the farm's own OLS trend. Honest only with a long series; the result carries
        a warning below 15 years.
      "none" — ratio to the farm's own mean. Use when the series is already trend-adjusted
        (e.g. TA-APH yields), otherwise the trend enters as risk and inflates everything.

    The correlation is measured on the OVERLAPPING years only, and its confidence interval is
    reported because at n=10 it is very wide. Two producers with the same point estimate but
    different series lengths do not have the same evidence, and the output says so.
    """
    warnings: list[str] = []
    county_fit = detrend(county_years, county_yields, detrend_method)
    county_ratio = county_fit.ratio_by_year()

    fy = {int(y): float(v) for y, v in zip(farm_years, farm_yields) if v and float(v) > 0}
    common = sorted(set(fy) & set(county_ratio))
    if len(common) < 3:
        raise ValueError(
            f"need at least 3 years where the farm and county series overlap; got {len(common)}"
        )
    f_vals = np.array([fy[y] for y in common], float)
    c_ratio = np.array([county_ratio[y] for y in common], float)
    c_vals = np.array([float(v) for y, v in zip(county_fit.years, county_fit.values)
                       if int(y) in set(common)], float)

    # -- detrend the farm ----------------------------------------------------
    yrs = np.array(common, float)
    if farm_detrend == "county":
        # Farm trend line anchored on the farm's own mean, sloped at the county's %/year.
        g = county_fit.pct_per_year
        centre = yrs.mean()
        shape = 1.0 + g * (yrs - centre)
        if (shape <= 0).any():
            raise ValueError("county trend rate implies a non-positive farm trend on these years")
        base = float((f_vals / shape).mean())
        f_fit = base * shape
        farm_trend_pct = g
    elif farm_detrend == "own":
        if len(common) < 15:
            warnings.append(
                f"farm_detrend='own' with only {len(common)} years: fitting a trend to a short "
                "series absorbs real variability and will UNDERSTATE farm risk. "
                "farm_detrend='county' is the safer default.")
        slope, intercept = np.polyfit(yrs, f_vals, 1)
        f_fit = intercept + slope * yrs
        if (f_fit <= 0).any():
            raise ValueError("fitted farm trend is non-positive")
        farm_trend_pct = float(slope) / float(f_fit.mean())
    elif farm_detrend == "none":
        f_fit = np.full_like(f_vals, f_vals.mean())
        farm_trend_pct = 0.0
    else:
        raise ValueError(f"unknown farm_detrend: {farm_detrend!r}")

    f_ratio = f_vals / f_fit
    farm_cv = float(f_ratio.std(ddof=1)) if len(f_ratio) > 1 else 0.0

    # -- the producer's own correlation --------------------------------------
    rho_measured = _safe_corr(f_ratio, c_ratio)
    rho_lo_ci, rho_hi_ci = _fisher_ci(rho_measured, len(common))
    rho_implied = (county_fit.cv / farm_cv) if farm_cv > 0 else float("nan")

    if len(common) < 8:
        warnings.append(
            f"only {len(common)} overlapping years: the correlation estimate is very imprecise "
            "and the historical counts below are anecdote, not frequency.")
    if not math.isnan(rho_measured) and rho_measured < 0:
        warnings.append(
            "measured farm-county correlation is NEGATIVE. That is not physically plausible "
            "over a long run and almost always means a data problem (wrong county, wrong crop, "
            "irrigated farm vs a dryland county series, or a yield entered in the wrong unit). "
            "Check the inputs before using this result.")
    if not math.isnan(rho_implied) and rho_implied > 1.0:
        warnings.append(
            f"your yields are LESS variable than the county's (county CV {county_fit.cv:.3f} vs "
            f"yours {farm_cv:.3f}). A single farm cannot be steadier than the average of every "
            "farm around it, so this is a data artefact, not a fact about the farm. The usual "
            "causes: the yields supplied are already TREND-ADJUSTED or APH-capped (an APH "
            "database applies yield floors and T-yields that truncate exactly the bad years "
            "this calculation needs), the series is too short to have caught a bad year, or a "
            "different practice/irrigation regime than the county series. Supply RAW harvested "
            "yields for as many years as you have, and treat the result as optimistic.")
    if (not math.isnan(rho_measured) and not math.isnan(rho_implied)
            and rho_measured > 0 and rho_implied <= 1.0
            and abs(rho_measured - rho_implied) > 0.25):
        warnings.append(
            f"the measured correlation ({rho_measured:.2f}) and the correlation implied by the "
            f"variance ratio ({rho_implied:.2f}) disagree by more than 0.25. Under the "
            "farm = county + idiosyncratic model these should agree; a gap this size means the "
            "farm's yields move with something other than the county, or the sample is too "
            "short to say. Treat both as soft.")

    rho_used = rho_override if rho_override is not None else rho_measured
    if math.isnan(rho_used) or rho_used <= 0:
        rho_used = RHO_REF
        warnings.append(
            f"could not use the measured correlation; fell back to the reference rho={RHO_REF}. "
            "This result is NOT farm-specific.")
    rho_used = float(min(0.999, max(0.05, rho_used)))

    # -- what actually happened, on this farm, in these years ------------------
    exit_, trigger = band_bounds(band, coverage_level)
    shortfall_years = [y for y, r in zip(common, f_ratio) if r < coverage_level]
    pay_years = [y for y, r in zip(common, c_ratio) if r < trigger]
    miss_years = [y for y in shortfall_years if y not in set(pay_years)]
    windfall_years = [y for y in pay_years if y not in set(shortfall_years)]

    # -- modelled, at the producer's own rho and at its CI --------------------
    kw = dict(band=band, coverage_level=coverage_level, plan_type=plan_type,
              price_vol=price_vol, corr_county_national=corr_county_national,
              corr_national_price=corr_national_price, n_draws=n_draws, seed=seed)
    lo = rho_lo_ci if not math.isnan(rho_lo_ci) else RHO_LO
    hi = rho_hi_ci if not math.isnan(rho_hi_ci) else RHO_HI
    lo = float(min(0.999, max(0.05, lo)))
    hi = float(min(0.999, max(0.05, hi)))

    return FarmBasisRisk(
        crop=crop, county_fips=county_fips,
        n_common_years=len(common), years=list(common),
        farm_yields=[float(v) for v in f_vals], county_yields=[float(v) for v in c_vals],
        farm_detrend=farm_detrend, farm_trend_pct_per_year=farm_trend_pct,
        farm_cv=farm_cv, county_cv=county_fit.cv, county_n_years=county_fit.n,
        rho_measured=rho_measured, rho_ci_lo=rho_lo_ci, rho_ci_hi=rho_hi_ci,
        rho_implied_by_cv=rho_implied, rho_used=rho_used,
        farm_shortfall_years=shortfall_years,
        farm_shortfall_freq=len(shortfall_years) / len(common),
        historical_miss_years=miss_years,
        historical_pay_years=pay_years,
        historical_windfall_years=windfall_years,
        modelled=basis_risk(county_fit.ratio, rho=rho_used, **kw),
        modelled_rho_lo=basis_risk(county_fit.ratio, rho=lo, **kw),
        modelled_rho_hi=basis_risk(county_fit.ratio, rho=hi, **kw),
        warnings=warnings,
    )


# ===========================================================================
# Database helpers (thin — the heavy lifting is in scripts/analysis/)
# ===========================================================================

# Which NASS series represents a county, in preference order. Wheat has no single county
# series that is both long AND current: NASS stopped publishing county wheat at
# CLASS_DESC='ALL CLASSES' after 2007, so a wheat county has to be scored on WINTER or
# SPRING. That is exactly why `load_series` below refuses a series that has gone dead —
# a 1975-2007 series is longer, and useless for a 2026 recommendation.
CLASS_PREFERENCE = {
    "Corn": ["ALL CLASSES"],
    "Soybeans": ["ALL CLASSES"],
    "Wheat": ["WINTER", "SPRING, (EXCL DURUM)", "SPRING, DURUM", "ALL CLASSES"],
    # Cotton has NO 'ALL CLASSES' county series at all — NASS splits it UPLAND / PIMA and
    # nothing else, so the generic default would silently match zero rows. UPLAND is also the
    # only class STAX insures (16-STAX-0021 §2(a)); Pima is a different insured commodity (ADM
    # 0022, Cotton Ex Long Staple) with 10 usable counties, and the loader drops it.
    "Cotton": ["UPLAND"],
}
# ALL PRODUCTION PRACTICES is the default because it is the only practice with broad county
# coverage. It is also a real limitation: RMA rates and settles SCO/ECO by TYPE AND PRACTICE,
# so an irrigated farm's endorsement triggers on the IRRIGATED county index, not the blended
# one used here. See docs/basis_risk.md, "What we could not determine".
PRACTICE_PREFERENCE = ["ALL PRODUCTION PRACTICES", "NON-IRRIGATED", "IRRIGATED"]
DEFAULT_UNIT = "BU / ACRE"

# ---------------------------------------------------------------------------
# UNITS — per crop, because they are NOT all bushels, and a mistake here is silent
# ---------------------------------------------------------------------------
# Read the "UNITS" section of the module docstring before touching any of this. The short
# version: everything this module computes is a ratio to a fitted trend, so it is exactly
# scale-invariant, so a wrong unit changes NO probability and cannot be caught downstream.
#
# `DEFAULT_UNIT` above stays 'BU / ACRE' for backwards compatibility with callers that pass a
# unit explicitly or only ever ask about grain. Anything that resolves a unit FROM A CROP must
# go through `yield_unit()` instead — a cotton query at the bushel default matches zero rows.
CROP_YIELD_UNIT: dict[str, str] = {
    "Corn": "BU / ACRE",
    "Soybeans": "BU / ACRE",
    "Wheat": "BU / ACRE",
    "Cotton": "LB / ACRE",       # lint pounds. NOT bushels, and not bales either.
}

# The abandonment-inclusive variant of each, loaded as the robustness check (see the
# nass_county_yield schema comment). For cotton this is the series that makes the whole guard
# necessary: NASS's cotton 'LB / NET PLANTED ACRE' county values run 10-50x below its
# 'LB / ACRE' ones, and a detrended CV cannot tell the two apart.
CROP_PLANTED_YIELD_UNIT: dict[str, str] = {
    "Corn": "BU / NET PLANTED ACRE",
    "Soybeans": "BU / NET PLANTED ACRE",
    "Wheat": "BU / NET PLANTED ACRE",
    "Cotton": "LB / NET PLANTED ACRE",
}

# Physically possible MEAN yields, per crop, in that crop's unit. Deliberately WIDE — this is a
# unit tripwire, not a plausibility model, and it must never reject a real county. The job is
# only to separate a series from the one an order of magnitude away from it, so each band is
# roughly a factor of 3 clear of the extremes actually observed in the NASS county data:
#   corn      county means run ~25-250 bu/ac      soybeans ~10-80 bu/ac
#   wheat     ~10-120 bu/ac                       cotton   ~150-1,800 lb/ac
# A cotton series mistakenly read as bushels lands near 900 and is caught by the wheat-scale
# ceiling only if the crop is known — which is exactly why this is keyed by crop.
YIELD_SANITY: dict[str, tuple[float, float]] = {
    "Corn": (5.0, 500.0),
    "Soybeans": (3.0, 200.0),
    "Wheat": (3.0, 300.0),
    "Cotton": (50.0, 5_000.0),
}


def yield_unit(crop: str, *, planted: bool = False) -> str:
    """The NASS unit `crop`'s yield is reported in. Raises for a crop with no declared unit.

    Raising is the point. A crop that reaches the estimator without an entry here has never had
    its unit checked by anybody, and defaulting it to bushels would load a plausible-looking
    series at the wrong scale rather than stopping.
    """
    table = CROP_PLANTED_YIELD_UNIT if planted else CROP_YIELD_UNIT
    try:
        return table[crop]
    except KeyError:
        raise ValueError(
            f"no yield unit declared for crop {crop!r}. Add it to basisrisk.CROP_YIELD_UNIT "
            f"(and CROP_PLANTED_YIELD_UNIT) — do NOT let it default to {DEFAULT_UNIT!r}: "
            "every metric in this module is scale-invariant, so the wrong unit would produce "
            "a plausible answer instead of an error. Known: "
            f"{sorted(CROP_YIELD_UNIT)}") from None


def check_yield_unit(crop: str, mean_yield: float, unit: str | None = None) -> str | None:
    """None if `mean_yield` is a physically possible mean for `crop`, else why not.

    THE ONLY UNIT CHECK THAT CAN WORK. `mean_yield` is the single non-scale-invariant number
    the estimator produces; cv, skew, miss_rate and every other output are identical under a
    50x rescale of the input series. So a level check is not one option among several — it is
    the only signal a unit error leaves behind. Never "improve" this into a CV check.

    Returns a message rather than raising so the builder can count and report the rejects
    alongside its other skip reasons instead of dying on one bad county.
    """
    want = CROP_YIELD_UNIT.get(crop)
    if unit is not None and want is not None and unit != want:
        return (f"{crop} series loaded in {unit!r}, but {crop} yields are reported in {want!r}. "
                f"Refusing it: the detrended CV would look completely normal either way.")
    band = YIELD_SANITY.get(crop)
    if band is None:
        return (f"no yield sanity band declared for {crop!r} — add one to "
                "basisrisk.YIELD_SANITY before publishing it")
    lo, hi = band
    if not (lo <= mean_yield <= hi):
        return (f"{crop} mean yield {mean_yield:,.1f} is outside the physically possible range "
                f"{lo:,.0f}-{hi:,.0f} {want or ''}. This is almost always a UNIT mix-up "
                f"(cotton and rice report LB/ACRE, grain reports BU/ACRE; NASS also carries a "
                f"'NET PLANTED ACRE' series at a different scale). Note that the detrended CV "
                f"and every probability derived from it are scale-invariant, so nothing "
                f"downstream would have flagged this.")
    return None

# A county series must reach at least this recently to be scored. NASS county coverage has
# been shrinking (corn counties reporting fell from ~1,670 in 2020 to ~1,210 in 2025), so a
# series can simply stop; scoring a dead one would quietly answer a 2026 question with a
# 2007 county.
DEFAULT_MIN_LAST_YEAR = 2018


def load_series(conn, crop: str, loc_key: str, *, agg_level: str = "COUNTY",
                unit: str | None = None, class_desc: str | None = None,
                practice: str | None = None, min_year: int | None = None,
                max_year: int | None = None,
                min_last_year: int | None = DEFAULT_MIN_LAST_YEAR):
    """Pull one yield series out of nass_county_yield, honoring the preference chains.

    Returns (years, values, class_used, practice_used) or None when nothing usable is there.

    Selection rule, in order: the series must still be LIVE (reach `min_last_year`), then the
    LONGEST such series wins, then the class-preference order breaks ties. Length alone is the
    wrong rule — see CLASS_PREFERENCE above for the wheat case that proves it.

    `unit` defaults to THE CROP'S OWN unit (`yield_unit`), not to bushels. It used to default to
    'BU / ACRE' for every crop, which was harmless while the only crops were grain and becomes
    a trap the moment one of them is cotton. Note what the wrong default does here: `unit` is
    in the WHERE clause, so a bushel query against cotton returns NOTHING and the county is
    silently skipped — the crop just quietly fails to appear on the map. The far worse case is
    a unit that MATCHES the wrong series; that one is caught by `check_yield_unit` downstream,
    because nothing about a returned series' shape reveals its scale.
    """
    if unit is None:
        unit = yield_unit(crop)
    classes = [class_desc] if class_desc else CLASS_PREFERENCE.get(crop, ["ALL CLASSES"])
    practices = [practice] if practice else PRACTICE_PREFERENCE
    best = None
    best_rank = None
    for ci, cls in enumerate(classes):
        for pi, prac in enumerate(practices):
            sql = ("SELECT year, value FROM nass_county_yield "
                   "WHERE crop=? AND stat='YIELD' AND agg_level=? AND loc_key=? AND unit=? "
                   "AND class_desc=? AND practice=?")
            args = [crop, agg_level, loc_key, unit, cls, prac]
            if min_year:
                sql += " AND year >= ?"
                args.append(min_year)
            if max_year:
                sql += " AND year <= ?"
                args.append(max_year)
            rows = conn.execute(sql + " ORDER BY year", args).fetchall()
            if len(rows) < 3:
                continue
            if min_last_year and int(rows[-1][0]) < min_last_year:
                continue
            rank = (len(rows), -ci, -pi)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best = ([int(r[0]) for r in rows], [float(r[1]) for r in rows], cls, prac)
    return best


def load_area(conn, crop: str, loc_key: str, *, agg_level: str = "COUNTY",
              class_desc: str = "ALL CLASSES", min_year: int | None = None) -> float | None:
    """Median harvested ACRES for a reporting unit — the 'area' in the aggregation scaling law."""
    sql = ("SELECT value FROM nass_county_yield WHERE crop=? AND stat='AREA HARVESTED' "
           "AND agg_level=? AND loc_key=? AND class_desc=? AND practice='ALL PRODUCTION PRACTICES'")
    args = [crop, agg_level, loc_key, class_desc]
    if min_year:
        sql += " AND year >= ?"
        args.append(min_year)
    vals = [float(r[0]) for r in conn.execute(sql, args) if r[0]]
    return float(np.median(vals)) if vals else None
