"""DRP (Dairy Revenue Protection, plan 83) risk-shape optimizer.

The DRP analogue of src/prfopt.py + src/prfsweep.py, folded into one module because
DRP's search space is four orders of magnitude smaller than PRF's and needs no
enumeration machinery of its own.

WHAT IS BEING OPTIMIZED
-----------------------
A DRP quarterly coverage endorsement is a declaration of six things:

    pricing option   Class | Component          -- a market, not a dial: chosen once
    coverage level   0.80 0.85 0.90 0.95        -- (RY2019 also filed 0.70 and 0.75)
    weighting factor 0.00 .. 1.00 in 5pp steps  -- 21 values
    protection factor 1.00 .. 1.50 in 5pp steps -- 11 values
    declared production (lb) and declared share -- pure size
    butterfat / protein tests (Component only)  -- the herd's own tests

Naively that is 4 x 21 x 11 = 924 declarations per pricing option, and RMA's own
count (see drpdata.declaration_space) is 1,848 across both.  It is not: **the
protection factor collapses out.**  M13 exhibit P18-1 puts ProtectionFactor in
both TotalPremiumAmount and Liability, and P28-1 puts it in the indemnity, so it
multiplies cost and payout by the same number.  It can change how many dollars are
at stake and it cannot change the win rate or the return per dollar.  Declared
production and declared share collapse for exactly the same reason.

So the real search space is 84 RISK SHAPES per pricing option:

    4 coverage levels  x  21 weighting factors  =  84

and everything this module stores is normalized PER $1 OF LIABILITY, which is the
DRP analogue of prfsweep's per-$1-of-protection normalization.  A caller turns a
stored number into dollars by multiplying by liability; liability is
ExpectedMilkPrice x DeclaredProduction/100 x CoverageLevel x Share x ProtectionFactor,
and the page does that multiplication at display time.  tests/test_drpopt.py pins the
collapse property directly.

The butterfat and protein tests do NOT collapse: they re-weight butterfat against
protein inside the expected milk price, so they change the shape of the risk, not just
its size.  They are also a declaration of fact (the herd's actual component tests), not
a dial to optimize, so they are module-level inputs defaulting to roughly the recent US
average (4.20% / 3.25%, both on RMA's declarable grid) and settable from the CLI.

THE GRAIN
---------
DRP IS SOLD STATEWIDE.  Every plan-83 offer carries county code 998 (see the schema
note in src/db.py), so results are keyed by state -- there is no county or grid grain
to roll up from, and drp_opt_best has no analogue of prf_grid_county.

Results are stored per (state, pricing option, quarter, coverage level), where
quarter 1..4 is the calendar quarter of the insured period and quarter 0 is the pooled
"any quarter" rollup the map shades by default.  Within each such row the module
searches the 21 weighting factors.

WHAT AN OBSERVATION IS
----------------------
One SETTLED quarter, priced on ONE sales date.  drp_daily_price carries every quarter
on every sales date it was quoted (~200 dates per quarter), which would make a "win
rate" a count of heavily autocorrelated re-quotes of the same outcome.  Instead each
(state, pricing option, calendar quarter) contributes exactly one observation, taken at
the LAST sales date on which that quarter was quoted against a settled actual price
(--lead last, the default: the best-informed purchase, typically ~2 weeks before the
quarter opens) or the FIRST (--lead first: the earliest forward quote, up to 15 months
out).  That yields 30 continuous observations per state per pricing option,
2019Q1..2026Q2.

Three RMA rules the assembly obeys, each of which silently corrupts the answer if
ignored:

  1. MILK YIELD AS OF THE SALES DATE.  NASS restates, and every drp_daily_price row
     points at the milk-yield generation current on ITS day.  The join is therefore
     drp_daily_price.milk_yield_id -> drp_milk_yield, never "the latest row for this
     state".  RMA's own known gap (1,100 RY2025 rows pointing at never-published ids
     10031-10080) drops those observations rather than substituting a neighbour.

  2. ACTUAL PRICES ARE KEYED BY (RY, actual_price_id), NOT BY QUARTER.  RY2025 carries
     two parallel settlement series (ids 49-56 and 57-62) for the same quarters under
     the pre- and post-June-2025 FMMO make allowances.  Joining on quarter would
     double-count every RY2025 quarter and mix two incompatible component-price
     regimes.  The join is drp_daily_price.actual_price_id -> drp_actual_price.

  3. RESTRICTED WEIGHTING FACTORS.  When only one side of the market is published for a
     quarter, RMA PINS the declared weighting factor (drp_daily_price.class_weight_
     restricted / component_weight_restricted; 26,300 Class rows and 124,300 Component
     rows pinned to 1.0, 13,600 to 0.0).  A shape's weight is REPLACED by the pin on
     those observations -- that is the declaration a producer could actually file that
     quarter -- and the substitution is counted in n_pinned so a collapsed search is
     visible rather than disguised.  See `admissible_weight`.

PREMIUM: A SIMULATION, NOT A LOOKUP
-----------------------------------
There is no DRP rate table and there cannot be one.  P18-1 specifies a 5,000-iteration
Monte Carlo over lognormal price draws using RMA's OWN published uniform draws
(drp_draw), which AIPs must use verbatim:

    SimulatedPrice[m]    = ExpectedPrice[m] x EXP(sigma[m] x NORMSINV(u[m]) - sigma[m]^2 / 2)
    SimulatedQuarter     = mean over the quarter's three months
    SimulatedYield       = ExpectedYield + YieldSD x NORMSINV(u_yield)
    SimulatedRevenue     = SimulatedMilkPrice x DCMP/100 x SimulatedYield / ExpectedYield
    SimulatedLoss[seq]   = MAX(0, RevenueGuarantee - SimulatedRevenue[seq])
    SimulatedLossAverage = MAX(SUM(SimulatedLoss)/5000, 0.02 x DCMP/100)
    TotalPremiumAmount   = SimulatedLossAverage x DeclaredShare x ProtectionFactor
                           x LoadingFactor

TWO DEVIATIONS FROM P18-1, both deliberate and both documented in the same spirit as
prfsweep's dropped cent-rounding:

  * THE TWO ROUNDINGS ARE DROPPED.  P18-1 rounds SimulatedLossAverage to cents and the
    share/PF product to whole dollars.  Neither is linear in size, and this module's
    whole contract is that its numbers ARE linear in size.  The residual is rounding
    dust on a per-cwt figure.

  * THE DRAWS ARE NOT REINSURANCE-YEAR-MATCHED.  RMA publishes ~226 MB of draws per
    year and only RY2026's are loaded (250 milk-yield ids x 5,000 sequences = the
    1.25M-row drp_draw table; loading is opt-in behind `drpdata --draws` precisely
    because of the size).  A 2019 observation is therefore simulated with the RY2026
    draw set for the SAME state and the SAME quarter number.  The draws are a fixed
    uniform(0,1) sample, so this is a valid 5,000-path Monte Carlo and an unbiased
    premium estimate -- it is simply not the byte-exact premium RMA's AIP software
    produced that day.  `premium_draw_ry` records which year's draws were used, and
    nothing here is presented as a filed rate.

  * BEGINNING/VETERAN FARMER TERMS ARE NOT MODELLED.  P18-1 sec.9 gives a qualifying
    beginning or veteran farmer or rancher an ADDITIONAL 10 percentage points of premium
    subsidy, and floors the producer premium at $1.  Both are facts about a POLICY and
    its holder, not about a risk shape, so neither can live in a table keyed by
    (state, pricing option, quarter, coverage) -- two producers buying the identical
    declaration in the same state pay different premiums.  Consequence: for a BFR/VFR
    producer every producer-premium figure here is TOO HIGH and every net figure is too
    low, so the map understates their advantage.  It is never wrong in the other
    direction, which is the safe way for it to be wrong.  Applying the 10 points is a
    per-quote adjustment a caller must make; it cannot be baked into these rows.

COMPONENT PRICING: THE FMMO CHAIN
---------------------------------
The Class option quotes CME Class III/IV futures directly.  The Component option quotes
butter / cheese / dry whey / NFDM futures, and the component prices come from the FMMO
manufacturing formulas in drp_fmmo_factor:

    ButterfatPrice     = (Butter   - butter_make_allowance)   x butter_mfg_yield
    NonfatSolidsPrice  = (NFDM     - nfdm_make_allowance)     x nfdm_mfg_yield
    OtherSolidsPrice   = (DryWhey  - dry_whey_make_allowance) x dry_whey_mfg_yield
    ProteinPrice       = (Cheese - cheese_make_allowance) x cheese_mfg_yield_casein
                       + (((Cheese - cheese_make_allowance) x cheese_mfg_yield_butterfat
                           - ButterfatPrice x butterfat_retention_rate)
                          x butterfat_to_protein_ratio)

VERIFIED, not assumed: applying these to the published monthly futures reproduces
drp_daily_price's own expected_butterfat / expected_protein / expected_other_solids /
expected_nonfat_solids to within one unit in the 4th decimal (a rounding tie) on every
one of 4,000 sampled component rows.  The butterfat_retention_rate term inside the
protein formula is what that check nailed down -- omit it and protein is off by ~0.31.
tests/test_drpopt.py re-runs the check against the live DB.

The expected milk price itself is NOT inferred -- it is quoted from the Basic Provisions.
26-DRP section 1, "Expected component pricing milk revenue", defines it verbatim as:

    "[(E(P_B) x Q_B + E(P_P) x Q_P + E(P_OS) x Q_OS) x W
      + (E(P_B) x Q_B + E(P_N) x (Q_P + 5.8)) x (1 - W)] x Q / 100."

Q_B is the declared butterfat test, Q_P the declared protein test, Q_OS the other solids
test, W the declared component price weighting factor and Q the declared covered milk
production.  Dividing out Q/100 leaves the $/cwt milk price this module computes:

    ExpectedMilkPrice(Component)
        = w x (ButterfatPrice x butterfat_test
               + ProteinPrice x protein_test + OtherSolidsPrice x os_test)
        + (1 - w) x (ButterfatPrice x butterfat_test
                     + NonfatSolidsPrice x (protein_test + os_test))
    ExpectedMilkPrice(Class)     = w x ExpectedClassIII + (1 - w) x ExpectedClassIV

Four things that wording settles, each of which the code previously only guessed at:

  * BUTTERFAT IS INSIDE BOTH BRACKETS, with the same test Q_B.  It is therefore
    algebraically unweighted -- w x BF + (1-w) x BF = BF -- but it is unweighted as a
    CONSEQUENCE of appearing on both sides, not because it sits outside the weighting.
    The two forms are identical, so the arithmetic here is unaffected.

  * THE OTHER SOLIDS TEST IS FIXED, NOT DECLARED.  26-DRP sec.1: "Other solids test -
    The pounds of other milk solids contained in 100 pounds of your milk, fixed at 5.8
    pounds."  Only butterfat and protein are declarable.

  * THE NONFAT SOLIDS TEST IS protein_test + os_test, exactly as the (Q_P + 5.8) term
    reads.  FCIC-20400U (04-2025) sec.23 puts it in words: "The nonfat solids test is
    determined by adding the declared protein test to the 5.8 other solids test.
    Example: Protein 4.00 + Other Solids 5.8 = 9.80 Nonfat Solids."

  * THE WEIGHTING IS APPLIED TO REVENUE BRACKETS, NOT TO BARE PRICES.  Because butterfat
    carries the same test in both brackets the two collapse to the same number, so this
    is a statement about provenance rather than about arithmetic.

RMA CHANGED THE OTHER SOLIDS TEST FOR RY2026.  19-DRP, 25-DRP and the 2025 handbook all
read "fixed at 5.7 pounds"; 26-DRP and FCIC-20400U (04-2025), "2026 and Succeeding Crop
Years", read "fixed at 5.8 pounds".  This module spans RY2019..RY2026, so the test is
read PER OBSERVATION YEAR via `other_solids_test()` and never hardcoded -- see that
function.  Using one value for the whole span misprices one end of the backtest or the
other.

w = 1 is the Class III / protein+other-solids side, w = 0 the Class IV / nonfat-solids
side, which is exactly how RMA's *_restricted columns are encoded (1 published when
only Class III or only protein+other solids exists).  26-DRP sec.1 confirms the
orientation: "The declared component price weighting factor is your percentage of
protein and other solids price used to determine your liability."

UNITS.  The component prices are $/lb; a test is pounds of that component per 100 lb of
milk.  Price x test is therefore already $/cwt, with no factor of 100 anywhere.  The
lone /100 in RMA's formula converts declared production from POUNDS to hundredweight.

WHICH TESTS APPLY WHERE.  The DECLARED tests set the expected revenue (hence liability
and premium).  Both the final revenue guarantee and the actual milk revenue use the
FINAL tests, which 26-DRP sec.7(e) sets equal to the declared tests unless the actual
test falls below 90% of declared, in which case the actual test is substituted.  The
final test therefore enters BOTH sides of the indemnity and largely cancels; this module
carries the declared tests through all three, which is exact whenever the herd's actual
tests hold at or above 90% of declaration and is the only assumption available anyway,
since RMA publishes no herd-level test data.

METRICS STORED (mirroring prf_opt_best's vocabulary)
----------------------------------------------------
    best_win_rate   share of settled quarters whose net was strictly positive
    best_net        mean net return PER $1 OF LIABILITY
    net             = indemnity - producer premium, per $1 of liability
    indemnity       = MAX(0, RevenueGuarantee - ActualRevenue)      [P28-1]
    producer prem   = TotalPremiumAmount x (1 - subsidy for that coverage IN THAT RY)

RY2019 filed six coverage levels and RY2020+ filed four, so the subsidy is read per
observation year from drp_subsidy; a coverage a year never filed simply drops that
observation, and n_obs records what actually got scored.

CLI (mirrors src/prfsweep.py):
    .venv/bin/python -m src.drpopt --all [--jobs 4]
    .venv/bin/python -m src.drpopt --state WI [--option Class] [--lead last] [--force]
    .venv/bin/python -m src.drpopt --state WI --explain 2024 3   # one quarter, verbose
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone

import numpy as np
from scipy.special import ndtri

from . import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The 21 declarable weighting factors, 0.00..1.00 in 5-percentage-point steps.
# Mirrors drpdata.WEIGHTING_FACTORS; restated here so the engine has no import-order
# dependency on the loader and so the search space is visible in this file.
WEIGHTING_FACTORS: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(21))

PRICING_OPTIONS = ("Class", "Component")

# Declared component tests (Component option only). RMA's declarable grids are
# butterfat 4.00-6.00 and protein 3.20-4.50 in 0.05 steps; these defaults sit at
# roughly the recent US average. They are a declaration of the herd's actual tests,
# not a dial to optimize -- see the module docstring.
DEFAULT_BUTTERFAT_TEST = 4.20
DEFAULT_PROTEIN_TEST = 3.25
# The other solids test is fixed by the DRP Basic Provisions, not declarable -- and RMA
# CHANGED it between RY2025 and RY2026, so it is a function of the observation's
# reinsurance year, never a module constant.
#
#   19-DRP sec.1 / 25-DRP sec.1 / FCIC-20400U (2025) sec.23:
#       "Other solids test - The pounds of other milk solids contained in 100 pounds of
#        your milk, fixed at 5.7 pounds."
#   26-DRP sec.1 / FCIC-20400U (04-2025, "2026 and Succeeding Crop Years") sec.23:
#       "Other solids test - The pounds of other milk solids contained in 100 pounds of
#        your milk, fixed at 5.8 pounds."
#
# RMA's own worked examples pin the boundary: the 2025 handbook's component example uses
# 5.7 throughout, the 2026 handbook's and 26-DRP's use 5.8. tests/test_drpopt.py
# reproduces all three examples to the published dollar.
OTHER_SOLIDS_TEST_BY_RY = {
    "legacy": 5.7,   # RY2019 .. RY2025
    "current": 5.8,  # RY2026 and succeeding crop years
}
OTHER_SOLIDS_TEST_CHANGE_RY = 2026


def other_solids_test(reinsurance_year: int) -> float:
    """The fixed other solids test in force for `reinsurance_year`, in lb per cwt.

    Also the addend that turns the declared protein test into the nonfat solids test
    (26-DRP's `Q_P + 5.8` term), so the two move together by construction -- they are the
    same policy constant used twice, and splitting them would let them drift apart.
    """
    return (OTHER_SOLIDS_TEST_BY_RY["current"]
            if int(reinsurance_year) >= OTHER_SOLIDS_TEST_CHANGE_RY
            else OTHER_SOLIDS_TEST_BY_RY["legacy"])

N_DRAWS = 5000

# P18-1's minimum: SimulatedLossAverage is floored at 0.02 x DCMP/100, i.e. 2 cents
# per hundredweight of declared production.
MIN_LOSS_PER_CWT = 0.02

# A (state, option, quarter, coverage) cell needs at least this many settled quarters
# before a win rate means anything. RY2019-only coverage levels (0.70 / 0.75) fall
# below it and are skipped rather than published off two observations.
MIN_OBS = 4

TOP_N = 10

# Quarter 0 is the pooled "any quarter" rollup, not a real quarter.
ALL_QUARTERS = 0


class DrpSkip(RuntimeError):
    """A cell that cannot be scored honestly (too few settled quarters, missing inputs)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pure pricing math (no DB, no I/O -- all unit-tested)
# ---------------------------------------------------------------------------

def fmmo_components(butter, cheese, dry_whey, nfdm, f) -> tuple:
    """(butterfat, protein, other_solids, nonfat_solids) $/lb from the four futures.

    `f` is a drp_fmmo_factor row (any mapping with the column names). Inputs may be
    scalars or numpy arrays; the arithmetic is elementwise either way, which is what
    lets the same function serve both the expected prices and all 5,000 simulated
    paths. See the module docstring for the verification of these formulas -- in
    particular `butterfat_retention_rate`, which multiplies the butterfat price
    INSIDE the protein formula and nowhere else.
    """
    butterfat = (butter - f["butter_make_allowance"]) * f["butter_mfg_yield"]
    nonfat_solids = (nfdm - f["nfdm_make_allowance"]) * f["nfdm_mfg_yield"]
    other_solids = (dry_whey - f["dry_whey_make_allowance"]) * f["dry_whey_mfg_yield"]
    net_cheese = cheese - f["cheese_make_allowance"]
    protein = (net_cheese * f["cheese_mfg_yield_casein"]
               + ((net_cheese * f["cheese_mfg_yield_butterfat"]
                   - butterfat * f["butterfat_retention_rate"])
                  * f["butterfat_to_protein_ratio"]))
    return butterfat, protein, other_solids, nonfat_solids


def class_milk_price(weight, class3, class4):
    """$/cwt expected (or actual, or simulated) milk price under the Class option.

    weight = 1.0 is all Class III, 0.0 is all Class IV -- the same orientation as
    drp_daily_price.class_weight_restricted.
    """
    return weight * class3 + (1.0 - weight) * class4


def component_milk_price(weight, butterfat, protein, other_solids, nonfat_solids,
                         butterfat_test=DEFAULT_BUTTERFAT_TEST,
                         protein_test=DEFAULT_PROTEIN_TEST,
                         *, os_test):
    """$/cwt milk price under the Component option -- 26-DRP sec.1, verbatim.

        "[(E(P_B) x Q_B + E(P_P) x Q_P + E(P_OS) x Q_OS) x W
          + (E(P_B) x Q_B + E(P_N) x (Q_P + 5.8)) x (1 - W)] x Q / 100"

    with the Q/100 (declared production, pounds -> cwt) left to the caller. The same
    expression serves the expected, actual and simulated price; only the four component
    prices change. Prices are $/lb and tests are lb per 100 lb of milk, so a price x test
    product is already $/cwt -- there is no further scaling.

    Butterfat appears in BOTH brackets with the same test, so it is algebraically
    unweighted; that is a consequence of the policy wording, not an independent rule.

    `os_test` is keyword-only and has NO default on purpose: it is 5.7 for RY2019..RY2025
    and 5.8 for RY2026+, and a default here is exactly how the wrong value got used for
    the whole backtest once already. Pass `other_solids_test(reinsurance_year)`.
    """
    nonfat_test = protein_test + os_test
    return (weight * (butterfat * butterfat_test
                      + protein * protein_test + other_solids * os_test)
            + (1.0 - weight) * (butterfat * butterfat_test
                                + nonfat_solids * nonfat_test))


def admissible_weight(row, pricing_option: str) -> tuple[float | None, str]:
    """The PIN on this offer's declared weighting factor, or (None, "") if free.

    Returns (pinned_weight, reason). A non-None pin means every legal declaration for
    this offer carries exactly that weighting factor, so a risk shape's own weight is
    overridden -- ignoring this produces declarations that cannot be filed.

    Two sources of a pin, in order:

    * RMA'S OWN COLUMN. drp_daily_price.class_weight_restricted /
      component_weight_restricted is non-NULL exactly when only one side of the market
      is published for a far-out quarter. This is the authoritative pin.

    * AN UNPUBLISHED EXPECTED PRICE. RY2019 and RY2020 Component rows carry no
      expected_nonfat_solids at all (RMA's ADM did not yet publish the column) and no
      restriction flag either. The nonfat-solids leg of the price is then not merely
      unattractive, it is not computable, so the only weight that can be priced is 1.0.
      Flagged with a distinct reason so an inferred pin is never mistaken for a filed
      one.
    """
    def _get(name):
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    if pricing_option == "Class":
        pin = _get("class_weight_restricted")
        if pin is not None:
            return float(pin), "class_weight_restricted"
        if _get("expected_class4") is None and _get("expected_class3") is not None:
            return 1.0, "no Class IV expected price published"
        if _get("expected_class3") is None and _get("expected_class4") is not None:
            return 0.0, "no Class III expected price published"
        return None, ""

    pin = _get("component_weight_restricted")
    if pin is not None:
        return float(pin), "component_weight_restricted"
    if _get("expected_nonfat_solids") is None:
        return 1.0, "no nonfat-solids expected price published"
    if _get("expected_protein") is None or _get("expected_other_solids") is None:
        return 0.0, "no protein / other-solids expected price published"
    return None, ""


def effective_weight(shape_weight: float, pin: float | None) -> float:
    """The weighting factor actually declared: the pin when there is one."""
    return shape_weight if pin is None else pin


def simulate_quarter_price(monthly, sigmas, z):
    """5,000 simulated QUARTERLY prices from three monthly futures + their sigmas.

    P18-1's lognormal, mean-preserving: P[m] = E[m] x exp(sigma[m] z - sigma[m]^2 / 2).
    The quarterly price is the plain mean of the three months -- verified against
    drp_daily_price, where expected_class4 19.49 is exactly round((19.50 + 19.50 +
    19.46)/3, 2).

    `monthly` and `sigmas` are 3-sequences; `z` is (n, 3) standard normals.
    """
    m = np.asarray(monthly, dtype=float)
    s = np.asarray(sigmas, dtype=float)
    z = np.asarray(z, dtype=float)
    return (m * np.exp(s * z - s * s / 2.0)).mean(axis=1)


def normal_from_uniform(u):
    """NORMSINV over RMA's published uniform draws.

    The draws are quoted to 4 decimals and observed to span [0.0001, 0.9999], so the
    clip never binds on real data; it is there so a malformed draw file cannot turn a
    premium into an infinity.
    """
    return ndtri(np.clip(np.asarray(u, dtype=float), 1e-9, 1.0 - 1e-9))


# ---------------------------------------------------------------------------
# Observation assembly (the DRP analogue of PRF's grid x interval x year matrix)
# ---------------------------------------------------------------------------

_OBS_SQL = """
SELECT o.state_code, o.state_abbrev, o.pricing_option,
       o.quarter_year, o.quarter, o.quarter_start,
       d.reinsurance_year, d.sales_date, d.loading_factor,
       d.m1_class3, d.m2_class3, d.m3_class3,
       d.m1_class4, d.m2_class4, d.m3_class4,
       d.m1_class3_sigma, d.m2_class3_sigma, d.m3_class3_sigma,
       d.m1_class4_sigma, d.m2_class4_sigma, d.m3_class4_sigma,
       d.m1_butter, d.m2_butter, d.m3_butter,
       d.m1_cheese, d.m2_cheese, d.m3_cheese,
       d.m1_dry_whey, d.m2_dry_whey, d.m3_dry_whey,
       d.m1_nfdm, d.m2_nfdm, d.m3_nfdm,
       d.m1_butter_sigma, d.m2_butter_sigma, d.m3_butter_sigma,
       d.m1_cheese_sigma, d.m2_cheese_sigma, d.m3_cheese_sigma,
       d.m1_dry_whey_sigma, d.m2_dry_whey_sigma, d.m3_dry_whey_sigma,
       d.m1_nfdm_sigma, d.m2_nfdm_sigma, d.m3_nfdm_sigma,
       d.expected_class3, d.expected_class4,
       d.expected_butterfat, d.expected_protein,
       d.expected_other_solids, d.expected_nonfat_solids,
       d.class_weight_restricted, d.component_weight_restricted,
       d.fmmo_factor_id,
       y.expected_yield, y.actual_yield, y.expected_yield_sd,
       a.actual_class3, a.actual_class4,
       a.actual_butterfat, a.actual_protein,
       a.actual_other_solids, a.actual_nonfat_solids
  FROM drp_daily_price d
  JOIN drp_offer o
    ON o.reinsurance_year = d.reinsurance_year AND o.offer_id = d.offer_id
  LEFT JOIN drp_milk_yield y
    ON y.reinsurance_year = d.reinsurance_year AND y.milk_yield_id = d.milk_yield_id
  LEFT JOIN drp_actual_price a
    ON a.reinsurance_year = d.reinsurance_year AND a.actual_price_id = d.actual_price_id
 WHERE o.state_code = ?
   AND o.deleted_date IS NULL
   AND a.settled = 1
   AND y.expected_yield IS NOT NULL
   AND y.actual_yield IS NOT NULL
"""


def observations(conn, state_code: str, pricing_option: str | None = None,
                 lead: str = "last") -> list:
    """One settled-quarter observation per (pricing option, calendar quarter).

    Pure read. `lead` picks which of the ~200 sales dates a quarter was quoted on
    represents it: "last" (default) is the best-informed purchase, "first" the earliest
    forward quote. Both joins that RMA's data punishes -- milk yield through the daily
    row's own milk_yield_id, actual prices through its own actual_price_id -- are in
    the SQL above; see the module docstring.
    """
    if lead not in ("last", "first"):
        raise ValueError(f"lead must be 'last' or 'first', got {lead!r}")
    sql = _OBS_SQL
    args: list = [str(state_code).zfill(2)]
    if pricing_option:
        sql += " AND o.pricing_option = ?"
        args.append(pricing_option)
    picked: dict[tuple, sqlite3.Row] = {}
    for r in conn.execute(sql, args):
        key = (r["pricing_option"], r["quarter_year"], r["quarter"])
        cur = picked.get(key)
        if cur is None:
            picked[key] = r
        elif lead == "last":
            if r["sales_date"] > cur["sales_date"]:
                picked[key] = r
        elif r["sales_date"] < cur["sales_date"]:
            picked[key] = r
    return [picked[k] for k in sorted(picked)]


def draw_sets(conn, state_code: str) -> dict[int, tuple[int, np.ndarray]]:
    """{quarter 1..4: (reinsurance_year, (5000, 13) float array)} for one state.

    Column order is fixed by DRAW_COLS below. Only RY2026's draws are loaded (see the
    module docstring on why), and its 250 milk-yield ids cover five consecutive
    quarters, so every quarter NUMBER is present; where a number appears twice the
    earliest quarter wins, deterministically.
    """
    ry = conn.execute("SELECT MAX(reinsurance_year) FROM drp_draw").fetchone()[0]
    if ry is None:
        raise DrpSkip("drp_draw is empty -- run `python -m src.drpdata --draws`")
    st = str(state_code).zfill(2)
    # milk-yield id -> quarter, restricted to the ids drp_draw actually carries. The
    # milk-yield table holds ~28 ids per state per year while only 5 of them have a
    # published draw set, so the restriction is what makes this pick a usable id.
    id_quarter: dict[int, tuple[int, int]] = {}
    for r in conn.execute(
            """SELECT DISTINCT d.milk_yield_id, o.quarter_year, o.quarter
                 FROM drp_daily_price d
                 JOIN drp_offer o ON o.reinsurance_year = d.reinsurance_year
                                 AND o.offer_id = d.offer_id
                WHERE d.reinsurance_year = ? AND o.state_code = ?
                  AND d.milk_yield_id IN (SELECT DISTINCT milk_yield_id FROM drp_draw
                                           WHERE reinsurance_year = ?)""",
            (ry, st, ry)):
        cur = id_quarter.get(r[0])
        if cur is None or (r[1], r[2]) < cur:
            id_quarter[r[0]] = (r[1], r[2])

    # One draw set per quarter NUMBER. The five loaded quarters span one number twice,
    # so pick the earliest calendar quarter, then the lowest id: deterministic either way.
    by_quarter: dict[int, int] = {}
    for mid, (qy, q) in sorted(id_quarter.items()):
        prev = by_quarter.get(q)
        if prev is None or (qy, mid) < (id_quarter[prev][0], prev):
            by_quarter[q] = mid

    out: dict[int, tuple[int, np.ndarray]] = {}
    cols = ", ".join(DRAW_COLS)
    for q, mid in by_quarter.items():
        rows = conn.execute(
            f"SELECT {cols} FROM drp_draw WHERE reinsurance_year = ? "
            "AND milk_yield_id = ? ORDER BY draw_number", (ry, mid)).fetchall()
        if len(rows) != N_DRAWS:
            continue  # a partial draw set is not a 5,000-iteration simulation
        out[q] = (ry, np.array(rows, dtype=float))
    if not out:
        raise DrpSkip(f"no complete {N_DRAWS}-draw set for state {st} in RY{ry}")
    return out


DRAW_COLS = (
    "m1_class3", "m2_class3", "m3_class3",
    "m1_class4", "m2_class4", "m3_class4",
    "m1_butter", "m2_butter", "m3_butter",
    "m1_cheese", "m2_cheese", "m3_cheese",
    "m1_dry_whey", "m2_dry_whey", "m3_dry_whey",
    "m1_nfdm", "m2_nfdm", "m3_nfdm",
    "yield_draw",
)
_DRAW_IX = {name: i for i, name in enumerate(DRAW_COLS)}


def _draw_z(draws: np.ndarray, prefix: str) -> np.ndarray:
    """(n, 3) standard normals for one commodity's three months."""
    ix = [_DRAW_IX[f"m{m}_{prefix}"] for m in (1, 2, 3)]
    return normal_from_uniform(draws[:, ix])


# ---------------------------------------------------------------------------
# Scoring one observation
# ---------------------------------------------------------------------------

def score_observation(obs, draws: np.ndarray, fmmo, subsidy_by_cov: dict[float, float],
                      weights=WEIGHTING_FACTORS,
                      butterfat_test: float = DEFAULT_BUTTERFAT_TEST,
                      protein_test: float = DEFAULT_PROTEIN_TEST) -> dict:
    """Score every (coverage, weighting factor) shape against one settled quarter.

    Returns {"pin", "pin_reason", "cells": {(coverage, shape_weight): {...}}} where each
    cell carries, all per 100 lb (one hundredweight) of declared production at declared
    share 1.0 and PROTECTION FACTOR 1.0:

        eff        the weighting factor actually declared (the pin, when pinned)
        emp        expected milk price ($/cwt)
        liability  = emp x coverage         (P18-1's Liability at PF 1)
        premium    total premium            (P18-1's TotalPremiumAmount at PF 1)
        producer   premium x (1 - subsidy)
        indemnity  MAX(0, liability - actual revenue)   (P28-1 at PF 1)
        net        indemnity - producer
        net_per_1  net / liability          -- the scale-invariant metric that is stored

    Everything a protection factor, a declared share or a declared production would
    multiply appears in liability, premium AND indemnity, so net_per_1 is invariant to
    all three. That is the property tests/test_drpopt.py pins.

    CELLS ARE KEYED BY THE SHAPE'S OWN WEIGHT, NOT THE EFFECTIVE ONE. When RMA pins the
    weighting factor for this quarter every shape collapses onto the same declaration,
    and keying by the effective weight would leave 20 of the 21 shapes unscored on this
    quarter -- which would then drop them from the whole state as "not comparable".
    Keying by the shape weight keeps every shape scored on every settled quarter; `eff`
    records what was really declared.
    """
    option = obs["pricing_option"]
    pin, reason = admissible_weight(obs, option)
    eff_of = {round(w, 4): effective_weight(w, pin) for w in weights}
    distinct_eff = sorted(set(eff_of.values()))

    ey = obs["expected_yield"]
    ay = obs["actual_yield"]
    if not ey:
        raise DrpSkip("no expected milk yield for the sales date")
    yield_ratio_actual = ay / ey
    sim_yield = np.maximum(
        ey + (obs["expected_yield_sd"] or 0.0)
        * normal_from_uniform(draws[:, _DRAW_IX["yield_draw"]]), 0.0)
    sim_yield_ratio = sim_yield / ey

    if option == "Class":
        sim3 = simulate_quarter_price(
            [obs["m1_class3"], obs["m2_class3"], obs["m3_class3"]],
            [obs["m1_class3_sigma"], obs["m2_class3_sigma"], obs["m3_class3_sigma"]],
            _draw_z(draws, "class3")) if obs["expected_class3"] is not None else None
        sim4 = simulate_quarter_price(
            [obs["m1_class4"], obs["m2_class4"], obs["m3_class4"]],
            [obs["m1_class4_sigma"], obs["m2_class4_sigma"], obs["m3_class4_sigma"]],
            _draw_z(draws, "class4")) if obs["expected_class4"] is not None else None

        def expected_for(w):
            return _mix(w, obs["expected_class3"], obs["expected_class4"])

        def simulated_for(w):
            return _mix(w, sim3, sim4)

        def actual_for(w):
            return _mix(w, obs["actual_class3"], obs["actual_class4"])
    else:
        # Component: simulate the four product futures, then push every path through
        # the FMMO formulas. The transform is affine in the futures price, so it has to
        # be applied PER PATH -- averaging first and transforming after would lose the
        # convexity of MAX(0, ...) against the make allowances.
        #
        # Each leg is simulated INDEPENDENTLY and stays None when RMA published no
        # futures for it, because 0 * NaN is NaN, not 0: RY2019 and RY2020 component
        # rows carry no NFDM strip at all (verified: 81,800 rows), so folding a NaN
        # nonfat-solids leg into a weight-1.0 price would silently poison the whole
        # state. None here means the same as None in `_component_mix` -- that weight is
        # not priceable and the observation drops out of it.
        sim_butter = _sim_leg(obs, draws, "butter")
        sim_cheese = _sim_leg(obs, draws, "cheese")
        sim_whey = _sim_leg(obs, draws, "dry_whey")
        sim_nfdm = _sim_leg(obs, draws, "nfdm")
        sim_bf = sim_prot = sim_os = sim_nfs = None
        if sim_butter is not None:
            sim_bf, _p, _o, _n = fmmo_components(sim_butter, 0.0, 0.0, 0.0, fmmo)
            if sim_cheese is not None:
                _b, sim_prot, _o, _n = fmmo_components(sim_butter, sim_cheese, 0.0,
                                                       0.0, fmmo)
        if sim_whey is not None:
            _b, _p, sim_os, _n = fmmo_components(0.0, 0.0, sim_whey, 0.0, fmmo)
        if sim_nfdm is not None:
            _b, _p, _o, sim_nfs = fmmo_components(0.0, 0.0, 0.0, sim_nfdm, fmmo)

        # The other solids test is a policy constant that RMA changed for RY2026, so it
        # is read off THIS observation's reinsurance year -- the same per-observation
        # discipline the subsidy table and the milk yield already follow.
        os_test = other_solids_test(obs["reinsurance_year"])

        def expected_for(w):
            return _component_mix(
                w, obs["expected_butterfat"], obs["expected_protein"],
                obs["expected_other_solids"], obs["expected_nonfat_solids"],
                butterfat_test, protein_test, os_test)

        def simulated_for(w):
            return _component_mix(w, sim_bf, sim_prot, sim_os, sim_nfs,
                                  butterfat_test, protein_test, os_test)

        def actual_for(w):
            return _component_mix(
                w, obs["actual_butterfat"], obs["actual_protein"],
                obs["actual_other_solids"], obs["actual_nonfat_solids"],
                butterfat_test, protein_test, os_test)

    loading = obs["loading_factor"] or 1.0
    covs = sorted(subsidy_by_cov)
    cov_arr = np.array(covs, dtype=float)
    by_eff: dict[float, dict[float, dict]] = {}
    for w in distinct_eff:
        emp = expected_for(w)
        actual_price = actual_for(w)
        if emp is None or actual_price is None:
            continue  # a leg RMA never published: drop, never impute
        sim_price = simulated_for(w)
        if sim_price is None:
            continue  # the futures strip for a needed leg was never published
        sim_rev = sim_price * sim_yield_ratio
        actual_rev = actual_price * yield_ratio_actual
        liab = emp * cov_arr                                    # (n_cov,)
        # (n_cov, n_draws): P18-1's SimulatedLoss for every coverage at once.
        pure = np.maximum(liab[:, None] - sim_rev[None, :], 0.0).mean(axis=1)
        pure = np.maximum(pure, MIN_LOSS_PER_CWT)
        premium = pure * loading
        row_by_cov: dict[float, dict] = {}
        for i, cov in enumerate(covs):
            if liab[i] <= 0:
                continue
            producer = float(premium[i]) * (1.0 - subsidy_by_cov[cov])
            indemnity = max(0.0, float(liab[i]) - actual_rev)
            net = indemnity - producer
            row_by_cov[cov] = {
                "eff": float(w), "emp": float(emp), "liability": float(liab[i]),
                "premium": float(premium[i]), "producer": producer,
                "indemnity": indemnity, "net": net,
                "net_per_1": net / float(liab[i]),
                "prem_per_1": producer / float(liab[i]),
            }
        by_eff[w] = row_by_cov

    cells: dict[tuple, dict] = {}
    for w, e in eff_of.items():
        for cov, cell in by_eff.get(e, {}).items():
            cells[(round(cov, 4), w)] = cell
    return {"pin": pin, "pin_reason": reason, "cells": cells,
            "weights": tuple(sorted(eff_of)), "effective": eff_of}


def dollars(cell, declared_production_lb: float, declared_share: float = 1.0,
            protection_factor: float = 1.0) -> dict:
    """Turn a per-hundredweight cell from `score_observation` into policy dollars.

    THIS FUNCTION IS THE PROTECTION-FACTOR COLLAPSE, made explicit. P18-1 puts
    DeclaredShare and ProtectionFactor into BOTH TotalPremiumAmount and Liability, P28-1
    puts them into the indemnity, and every revenue formula divides
    DeclaredCoveredMilkProduction by 100 against a $/cwt price. So all three are one
    common multiplier:

        size = declared_production_lb / 100 x declared_share x protection_factor

    Liability, premium, producer premium, indemnity and net all scale by `size`;
    net_per_1 and prem_per_1 come through untouched. That is why the optimizer searches
    84 risk shapes and not 924 declarations, and why the map can shade one number for a
    state and let the page apply the producer's own size at display time -- exactly as
    prfpage multiplies a per-$1-of-protection number by CBV x coverage x productivity.
    """
    size = declared_production_lb / 100.0 * declared_share * protection_factor
    return {
        "size": size,
        "liability": cell["liability"] * size,
        "premium": cell["premium"] * size,
        "producer": cell["producer"] * size,
        "indemnity": cell["indemnity"] * size,
        "net": cell["net"] * size,
        "net_per_1": cell["net_per_1"],
        "prem_per_1": cell["prem_per_1"],
    }


def _mix(w, a, b):
    """w*a + (1-w)*b, propagating None when a needed leg is unpublished."""
    if w >= 1.0:
        return a
    if w <= 0.0:
        return b
    if a is None or b is None:
        return None
    return class_milk_price(w, a, b)


def _component_mix(w, butterfat, protein, other_solids, nonfat_solids,
                   butterfat_test, protein_test, os_test):
    """component_milk_price, propagating None when a needed leg is unpublished.

    Works on scalars and on (n_draws,) arrays alike, which is why the guards are
    explicit `is None` and not truthiness -- a numpy array has no truth value. A leg the
    weight zeroes out is substituted with 0.0 rather than passed through, because
    0 * NaN is NaN: RY2019/RY2020 component rows have no NFDM strip, and folding that
    into a weight-1.0 price would poison the entire state.
    """
    if butterfat is None:
        return None
    if w > 0.0 and (protein is None or other_solids is None):
        return None
    if w < 1.0 and nonfat_solids is None:
        return None
    return component_milk_price(
        w, butterfat,
        0.0 if protein is None else protein,
        0.0 if other_solids is None else other_solids,
        0.0 if nonfat_solids is None else nonfat_solids,
        butterfat_test, protein_test, os_test=os_test)


def _sim_leg(obs, draws, prefix: str):
    """5,000 simulated quarterly prices for one product future, or None if unpublished."""
    monthly = [obs[f"m{m}_{prefix}"] for m in (1, 2, 3)]
    sigmas = [obs[f"m{m}_{prefix}_sigma"] for m in (1, 2, 3)]
    if any(v is None for v in monthly) or any(v is None for v in sigmas):
        return None
    return simulate_quarter_price(monthly, sigmas, _draw_z(draws, prefix))


# ---------------------------------------------------------------------------
# Scoring a whole state
# ---------------------------------------------------------------------------

def subsidy_table(conn) -> dict[int, dict[float, float]]:
    """{reinsurance_year: {coverage: subsidy}} -- read per year, never hardcoded.

    RY2019 filed six coverage levels (0.70 .. 0.95) and RY2020 onward filed four, so a
    backtest that spans 2019 MUST look the level set up per year.
    """
    out: dict[int, dict[float, float]] = {}
    for ry, cov, pct in conn.execute(
            "SELECT reinsurance_year, coverage_level, subsidy_pct FROM drp_subsidy"):
        out.setdefault(int(ry), {})[round(float(cov), 4)] = float(pct)
    return out


def fmmo_table(conn) -> dict[tuple[int, int], dict]:
    """{(reinsurance_year, fmmo_factor_id): row-as-dict}."""
    return {(r["reinsurance_year"], r["fmmo_factor_id"]): dict(r)
            for r in conn.execute("SELECT * FROM drp_fmmo_factor")}


def state_roster(conn, state: str | None = None) -> list[tuple[str, str, str]]:
    """[(state_code, state_abbrev, state_name)] from drp_state."""
    sql = ("SELECT state_code, MAX(state_abbrev), MAX(state_name) FROM drp_state "
           "GROUP BY state_code ORDER BY state_code")
    rows = [(r[0], r[1], r[2]) for r in conn.execute(sql)]
    if state:
        s = state.upper()
        rows = [r for r in rows if r[0] == s.zfill(2) or (r[1] or "").upper() == s]
        if not rows:
            raise DrpSkip(f"no DRP offers for state {state!r}")
    return rows


def compute_state_rows(conn, state_code: str, *, lead: str = "last",
                       weights=WEIGHTING_FACTORS,
                       butterfat_test: float = DEFAULT_BUTTERFAT_TEST,
                       protein_test: float = DEFAULT_PROTEIN_TEST,
                       min_obs: int = MIN_OBS, top_n: int = TOP_N) -> list[dict]:
    """Every drp_opt_best row for one state: 2 options x 5 quarter keys x coverages.

    Quarter keys are 1..4 plus 0, the pooled rollup over all four. Coverage levels are
    whatever drp_subsidy filed for the years the observations land in; a (quarter,
    coverage) cell with fewer than `min_obs` scored quarters is dropped rather than
    published off a handful of outcomes.
    """
    obs_rows = observations(conn, state_code, lead=lead)
    if not obs_rows:
        raise DrpSkip("no settled DRP quarters for this state")
    draws = draw_sets(conn, state_code)
    subs = subsidy_table(conn)
    fmmos = fmmo_table(conn)

    st = obs_rows[0]
    state_abbrev = st["state_abbrev"]

    # scored[(option, quarter, coverage, weight)] -> list of per-observation cells
    scored: dict[tuple, list] = {}
    # meta[(option, quarter)] -> bookkeeping shared by every coverage/weight in the cell
    meta: dict[tuple, dict] = {}

    for obs in obs_rows:
        q = int(obs["quarter"])
        if q not in draws:
            continue
        draw_ry, draw_arr = draws[q]
        fmmo = fmmos.get((obs["reinsurance_year"], obs["fmmo_factor_id"]))
        if obs["pricing_option"] == "Component" and fmmo is None:
            continue  # no FMMO formula set for this row: cannot price components
        sub_by_cov = subs.get(int(obs["reinsurance_year"]), {})
        if not sub_by_cov:
            continue
        try:
            res = score_observation(obs, draw_arr, fmmo, sub_by_cov, weights=weights,
                                    butterfat_test=butterfat_test,
                                    protein_test=protein_test)
        except DrpSkip:
            continue
        if not res["cells"]:
            continue
        label = f"{obs['quarter_year']}Q{q}"
        for key_q in (q, ALL_QUARTERS):
            m = meta.setdefault((obs["pricing_option"], key_q), {
                "labels": [], "n_pinned": 0, "pins": {}, "draw_ry": draw_ry})
            m["labels"].append(label)
            if res["pin"] is not None:
                m["n_pinned"] += 1
                m["pins"].setdefault(str(res["pin"]), []).append(label)
            for (cov, w), cell in res["cells"].items():
                scored.setdefault(
                    (obs["pricing_option"], key_q, cov, w), []).append(cell)

    rows: list[dict] = []
    # Group the flat (option, quarter, coverage, weight) map into one row per
    # (option, quarter, coverage), searching the weights inside it.
    by_cell: dict[tuple, dict[float, list]] = {}
    for (option, q, cov, w), cells in scored.items():
        by_cell.setdefault((option, q, cov), {})[w] = cells

    for (option, q, cov), by_weight in sorted(by_cell.items()):
        n_obs = max(len(v) for v in by_weight.values())
        if n_obs < min_obs:
            continue
        m = meta[(option, q)]
        shapes = []
        for w, cells in sorted(by_weight.items()):
            if len(cells) != n_obs:
                # A weight priced on fewer quarters than its siblings is not comparable
                # with them; dropping it keeps every shape in the row scored on the
                # same settled outcomes. (Pins do NOT cause this -- see
                # score_observation on why cells are keyed by the shape's own weight.)
                continue
            nets = [c["net_per_1"] for c in cells]
            shapes.append({
                "w": round(w, 4),
                "win": sum(1 for x in nets if x > 0) / len(nets),
                "net": sum(nets) / len(nets),
                "prem": sum(c["prem_per_1"] for c in cells) / len(cells),
                "liab": sum(c["liability"] for c in cells) / len(cells),
                # Share of the scored quarters on which this shape's declared weighting
                # factor was the shape's OWN weight rather than an RMA pin.
                "eff_share": sum(1 for c in cells
                                 if abs(c["eff"] - w) < 1e-9) / len(cells),
            })
        if not shapes:
            continue
        # Tie-break, in order: toward the shape whose weight was actually declarable
        # most often, then toward the lower weight. Without the first key a fully
        # pinned cell (all 21 shapes identical) would report w = 0.00 while the only
        # filable declaration was w = 1.00.
        by_win = sorted(shapes, key=lambda s: (-s["win"], -s["net"],
                                               -s["eff_share"], s["w"]))
        by_net = sorted(shapes, key=lambda s: (-s["net"], -s["win"],
                                               -s["eff_share"], s["w"]))
        w0, n0 = by_win[0], by_net[0]
        nets = sorted(s["net"] for s in shapes)
        mid = len(nets) // 2
        median = nets[mid] if len(nets) % 2 else (nets[mid - 1] + nets[mid]) / 2
        labels = sorted(set(m["labels"]))
        rows.append({
            "state_code": str(state_code).zfill(2),
            "state_abbrev": state_abbrev,
            "pricing_option": option,
            "quarter": int(q),
            "coverage_level": float(cov),
            "quarter_min": labels[0],
            "quarter_max": labels[-1],
            "n_obs": int(n_obs),
            "n_shapes": len(shapes),
            "n_pinned": int(m["n_pinned"]),
            "best_win_rate": float(w0["win"]),
            "best_win_weight": float(w0["w"]),
            "best_win_net": float(w0["net"]),
            "best_win_prem": float(w0["prem"]),
            "best_net": float(n0["net"]),
            "best_net_weight": float(n0["w"]),
            "best_net_win_rate": float(n0["win"]),
            "best_net_prem": float(n0["prem"]),
            "best_net_liability_cwt": float(n0["liab"]),
            "median_net": float(median),
            "pct_positive": sum(1 for s in shapes if s["net"] > 0) / len(shapes),
            "premium_draw_ry": int(m["draw_ry"]),
            "top_json": json.dumps({
                "by_win": by_win[:top_n],
                "by_net": by_net[:top_n],
                "pins": m["pins"],
            }, separators=(",", ":")),
        })
    if not rows:
        raise DrpSkip(f"no cell reached {min_obs} settled quarters")
    return rows


# ---------------------------------------------------------------------------
# DB writes (idempotent upsert; this module owns drp_opt_best)
# ---------------------------------------------------------------------------

_UPSERT = """
INSERT INTO drp_opt_best
  (state_code, state_abbrev, pricing_option, quarter, coverage_level,
   quarter_min, quarter_max, n_obs, n_shapes, n_pinned,
   best_win_rate, best_win_weight, best_win_net, best_win_prem,
   best_net, best_net_weight, best_net_win_rate, best_net_prem,
   best_net_liability_cwt, median_net, pct_positive, premium_draw_ry,
   top_json, source, fetched_at)
VALUES
  (:state_code, :state_abbrev, :pricing_option, :quarter, :coverage_level,
   :quarter_min, :quarter_max, :n_obs, :n_shapes, :n_pinned,
   :best_win_rate, :best_win_weight, :best_win_net, :best_win_prem,
   :best_net, :best_net_weight, :best_net_win_rate, :best_net_prem,
   :best_net_liability_cwt, :median_net, :pct_positive, :premium_draw_ry,
   :top_json, :source, :fetched_at)
ON CONFLICT(state_code, pricing_option, quarter, coverage_level) DO UPDATE SET
   state_abbrev=excluded.state_abbrev,
   quarter_min=excluded.quarter_min, quarter_max=excluded.quarter_max,
   n_obs=excluded.n_obs, n_shapes=excluded.n_shapes, n_pinned=excluded.n_pinned,
   best_win_rate=excluded.best_win_rate, best_win_weight=excluded.best_win_weight,
   best_win_net=excluded.best_win_net, best_win_prem=excluded.best_win_prem,
   best_net=excluded.best_net, best_net_weight=excluded.best_net_weight,
   best_net_win_rate=excluded.best_net_win_rate, best_net_prem=excluded.best_net_prem,
   best_net_liability_cwt=excluded.best_net_liability_cwt,
   median_net=excluded.median_net, pct_positive=excluded.pct_positive,
   premium_draw_ry=excluded.premium_draw_ry, top_json=excluded.top_json,
   source=excluded.source, fetched_at=excluded.fetched_at
"""


def upsert_best(conn, rows, source: str = "drpopt") -> int:
    """Write drp_opt_best rows. Idempotent; commits once."""
    stamp = _now_iso()
    payload = [{**r, "source": source, "fetched_at": stamp} for r in rows]
    conn.executemany(_UPSERT, payload)
    conn.commit()
    return len(payload)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def sweep(conn, state: str | None = None, *, lead: str = "last",
          butterfat_test: float = DEFAULT_BUTTERFAT_TEST,
          protein_test: float = DEFAULT_PROTEIN_TEST,
          min_obs: int = MIN_OBS, force: bool = False, limit: int | None = None,
          source: str | None = None, log=print) -> dict:
    """Score every state (or one) and upsert drp_opt_best.

    Resumable in prfsweep's sense: a state already present in drp_opt_best is skipped
    unless `force`. Each state commits alone, so an interrupted run loses at most the
    state in flight.
    """
    roster = state_roster(conn, state)
    if limit:
        roster = roster[:limit]
    done: set[str] = set()
    if not force:
        try:
            done = {r[0] for r in conn.execute(
                "SELECT DISTINCT state_code FROM drp_opt_best")}
        except sqlite3.OperationalError:
            done = set()

    src = source or f"drpopt_{lead}"
    written, resumed = 0, 0
    skipped: dict[str, str] = {}
    t0 = time.monotonic()
    for i, (code, abbrev, name) in enumerate(roster, 1):
        if code in done:
            resumed += 1
            continue
        try:
            rows = compute_state_rows(
                conn, code, lead=lead, butterfat_test=butterfat_test,
                protein_test=protein_test, min_obs=min_obs)
        except DrpSkip as e:
            skipped[code] = str(e)
            log(f"  {abbrev or code}: SKIPPED - {e}")
            continue
        except Exception as e:  # one bad state must not abort a 50-state run
            skipped[code] = f"{type(e).__name__}: {e}"
            log(f"  {abbrev or code}: ERROR - {skipped[code]}")
            continue
        written += upsert_best(conn, rows, source=src)
        if i % 10 == 0 or i == len(roster):
            log(f"[{i}/{len(roster)}] {abbrev or code}: {written} rows written, "
                f"{resumed} resumed, {len(skipped)} skipped, "
                f"{time.monotonic() - t0:.0f}s")
    return {"states": len(roster), "rows": written, "resumed": resumed,
            "skipped": skipped, "elapsed_s": time.monotonic() - t0}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _explain(conn, state: str, quarter_year: int, quarter: int, lead: str,
             butterfat_test: float, protein_test: float) -> None:
    """Print one quarter's full arithmetic -- the hand-check path for P18-1."""
    roster = state_roster(conn, state)
    code = roster[0][0]
    draws = draw_sets(conn, code)
    subs = subsidy_table(conn)
    fmmos = fmmo_table(conn)
    for obs in observations(conn, code, lead=lead):
        if obs["quarter_year"] != quarter_year or obs["quarter"] != quarter:
            continue
        res = score_observation(obs, draws[quarter][1],
                                fmmos.get((obs["reinsurance_year"], obs["fmmo_factor_id"])),
                                subs[obs["reinsurance_year"]],
                                butterfat_test=butterfat_test, protein_test=protein_test)
        print(f"\n{obs['state_abbrev']} {quarter_year}Q{quarter} "
              f"{obs['pricing_option']}  sales {obs['sales_date']} "
              f"(RY{obs['reinsurance_year']}, draws RY{draws[quarter][0]})")
        print(f"  loading {obs['loading_factor']}  yield {obs['expected_yield']} -> "
              f"{obs['actual_yield']} (sd {obs['expected_yield_sd']})")
        print(f"  weighting pin: {res['pin']} {res['pin_reason'] or '(free)'}")
        print(f"  {'cov':>5} {'w':>5} {'EMP':>8} {'liab':>8} {'prem':>8} "
              f"{'prod':>8} {'indem':>8} {'net':>9} {'net/$1':>9}")
        for (cov, w), c in sorted(res["cells"].items()):
            if abs(w * 4 - round(w * 4)) > 1e-9:
                continue  # print quarter-steps only, so the table stays readable
            print(f"  {cov:5.2f} {w:5.2f} {c['emp']:8.3f} {c['liability']:8.3f} "
                  f"{c['premium']:8.4f} {c['producer']:8.4f} {c['indemnity']:8.4f} "
                  f"{c['net']:9.4f} {c['net_per_1']:9.5f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sweep the DRP risk-shape optimizer over states (no network).")
    ap.add_argument("--state", default=None, help="2-letter abbrev or 2-digit FIPS")
    ap.add_argument("--all", action="store_true", help="every state in drp_state")
    ap.add_argument("--lead", default="last", choices=("last", "first"),
                    help="which sales date represents a quarter (default: last, the "
                         "best-informed purchase)")
    ap.add_argument("--butterfat-test", type=float, default=DEFAULT_BUTTERFAT_TEST,
                    help="declared butterfat test %% (Component option; RMA allows "
                         "4.00-6.00)")
    ap.add_argument("--protein-test", type=float, default=DEFAULT_PROTEIN_TEST,
                    help="declared protein test %% (Component option; RMA allows "
                         "3.20-4.50)")
    ap.add_argument("--min-obs", type=int, default=MIN_OBS,
                    help="minimum settled quarters before a cell is published")
    ap.add_argument("--limit", type=int, default=None, help="only the first N states")
    ap.add_argument("--force", action="store_true",
                    help="rescore states already in drp_opt_best")
    ap.add_argument("--explain", nargs=2, metavar=("YEAR", "QUARTER"), default=None,
                    help="print one quarter's full arithmetic and exit (needs --state)")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    if not args.all and not args.state:
        ap.error("--state is required unless --all is given")

    def say(msg):
        print(msg, flush=True)

    conn = db.connect(args.db)
    db.init_db(conn)
    try:
        if args.explain:
            _explain(conn, args.state, int(args.explain[0]), int(args.explain[1]),
                     args.lead, args.butterfat_test, args.protein_test)
            return 0
        res = sweep(conn, state=None if args.all else args.state, lead=args.lead,
                    butterfat_test=args.butterfat_test, protein_test=args.protein_test,
                    min_obs=args.min_obs, force=args.force, limit=args.limit, log=say)
    finally:
        conn.close()

    print(f"\ndone in {res['elapsed_s']:.0f}s: {res['states']} states, "
          f"{res['rows']} drp_opt_best rows written, {res['resumed']} resumed, "
          f"{len(res['skipped'])} skipped")
    if res["skipped"]:
        for code, why in sorted(res["skipped"].items()):
            print(f"  {code}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
