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
  * COVERAGE LEVEL. `coverage_level` here is the FARM's own deductible, which is what defines
    "a farm loss". The shipped build is 0.85 only, which is the highest common election and so
    the HIGHEST miss rate: re-running basis_risk() on the same series at 0.75 roughly halves
    the ECO95 miss rate, and 88% of the RY2026 book insures below 0.85. Any adjustment built on
    the shipped rows is therefore CONSERVATIVE. Building --coverage-levels 0.70 0.75 0.80 0.85
    and joining on the county's own modal election is the fix.

WHAT THIS MODULE DOES NOT DO
============================
* It does not model MCO's margin trigger (input costs) — MCO is treated as an area revenue
  band, which understates its basis risk, since input-cost basis is an extra layer. No MCO
  rows are written at all, so a consumer sees `unknown` rather than an understatement.
* It does not model prevented planting, replant, or the quality adjustments that can make a
  farm's insurable loss differ from its yield loss.
* It has no farm-level data anywhere in it. See the honesty block above.
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
BAND_SPECS: dict[str, dict] = {
    "ECO95": {"trigger": 0.95, "exit": 0.86, "label": "ECO, 95% trigger"},
    "ECO90": {"trigger": 0.90, "exit": 0.86, "label": "ECO, 90% trigger"},
    "SCO86": {"trigger": 0.86, "exit": None, "label": "SCO (exits at the underlying level)"},
}

# Farm-county yield correlation. THE one parameter this module imports from outside the data.
# See docs/basis_risk.md for the sources and for the sensitivity of every output to it.
# Deliberately a wide band, because the literature's own range is wide and varies by crop,
# region and farm size.
RHO_REF = 0.70
RHO_LO = 0.55
RHO_HI = 0.85

# Depth below the deductible that counts as a "deep" loss for deep_miss_rate, in coverage points.
DEEP_LOSS_MARGIN = 0.10

MIN_YEARS = 12          # below this we refuse to publish a county metric at all
GRADE_A_YEARS = 30
GRADE_B_YEARS = 20


def grade_for(n_years: int) -> str | None:
    """A/B/C data grade from series length, or None when too short to publish."""
    if n_years >= GRADE_A_YEARS:
        return "A"
    if n_years >= GRADE_B_YEARS:
        return "B"
    if n_years >= MIN_YEARS:
        return "C"
    return None


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
    coverage_level: float
    trigger: float
    exit: float
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
    """(exit, trigger) for a band at a producer's coverage level. Raises if degenerate."""
    spec = BAND_SPECS.get(band)
    if spec is None:
        raise ValueError(f"unknown band {band!r}; known: {sorted(BAND_SPECS)}")
    trigger = spec["trigger"]
    exit_ = spec["exit"] if spec["exit"] is not None else coverage_level
    if trigger - exit_ <= 0:
        raise ValueError(
            f"{band} has zero width at coverage level {coverage_level:.2f} "
            f"(exit {exit_:.2f} >= trigger {trigger:.2f}) — there is nothing to buy")
    return exit_, trigger


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
}
# ALL PRODUCTION PRACTICES is the default because it is the only practice with broad county
# coverage. It is also a real limitation: RMA rates and settles SCO/ECO by TYPE AND PRACTICE,
# so an irrigated farm's endorsement triggers on the IRRIGATED county index, not the blended
# one used here. See docs/basis_risk.md, "What we could not determine".
PRACTICE_PREFERENCE = ["ALL PRODUCTION PRACTICES", "NON-IRRIGATED", "IRRIGATED"]
DEFAULT_UNIT = "BU / ACRE"

# A county series must reach at least this recently to be scored. NASS county coverage has
# been shrinking (corn counties reporting fell from ~1,670 in 2020 to ~1,210 in 2025), so a
# series can simply stop; scoring a dead one would quietly answer a 2026 question with a
# 2007 county.
DEFAULT_MIN_LAST_YEAR = 2018


def load_series(conn, crop: str, loc_key: str, *, agg_level: str = "COUNTY",
                unit: str = DEFAULT_UNIT, class_desc: str | None = None,
                practice: str | None = None, min_year: int | None = None,
                max_year: int | None = None,
                min_last_year: int | None = DEFAULT_MIN_LAST_YEAR):
    """Pull one yield series out of nass_county_yield, honoring the preference chains.

    Returns (years, values, class_used, practice_used) or None when nothing usable is there.

    Selection rule, in order: the series must still be LIVE (reach `min_last_year`), then the
    LONGEST such series wins, then the class-preference order breaks ties. Length alone is the
    wrong rule — see CLASS_PREFERENCE above for the wheat case that proves it.
    """
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
