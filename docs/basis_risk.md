# Basis risk in the area-triggered endorsements (SCO, ECO, MCO, STAX)

**The one thing to take away:** the ~5x expected return per producer dollar on an 80%-subsidised
endorsement is an arithmetic identity, identical for every farm in the country. Basis risk is not.
It is the *entire* farm-specific content of a row-crop recommendation, and without it the honest
advice collapses to "everyone should buy ECO", which is wrong.

---

## 1. The question

SCO, ECO, MCO and STAX settle on a **county** yield/revenue index. Individual MPCI settles on the
producer's **own unit**. So an area-triggered band can fail to pay a producer who had a genuine,
severe loss, because the county as a whole was fine. That failure is basis risk.

Why it decides the recommendation:

| | |
|---|---|
| Premium subsidy on SCO/ECO/MCO/STAX (2026 CY) | ~80% |
| Expected return per producer dollar at FCIC's statutory target loss ratio of 1.0 (7 U.S.C. §1506(n)(2)) | 1/(1−0.80) = **5.0x** |
| How much that varies by farm | **none — it is an identity** |
| Whether the trigger fires when *your* farm loses money | **everything** |

`docs/rowcrop_endorsement_stacking.md` establishes the first three rows from the Summary of
Business. This document supplies the fourth.

### The band mechanics being modelled

| Band | Trigger (pays below) | Exits at | Width |
|---|---|---|---|
| `ECO95` | 95% of expected county revenue/yield | 86% | 9 points, fixed |
| `ECO90` | 90% | 86% | 4 points, fixed |
| `SCO86` | 86% | the producer's own coverage level | **depends on the producer** — 1 point at 85% RP |

### Two things are called "coverage level". Read this before reading any number below

| | What it is | Which side of the joint distribution | Column |
|---|---|---|---|
| **Band trigger** — 0.95 / 0.90 / 0.86 | RMA's, fixed by the endorsement elected | the **county** index | `band` |
| **Producer coverage level** — 0.50 … 0.85 | the producer's own MPCI **deductible** | the **farm** | `coverage_level` |

`miss_rate` = P( county index ≥ **trigger** │ farm ratio < **producer coverage level** ). The two
percentages never touch except in `SCO86`, where the band *exits* at the producer's own level, so
the election also sets the band's width. §4 Step 5b works this through. It is the easiest thing in
this document to get backwards, and getting it backwards inverts the sign of every conclusion.

---

## 2. What we can and cannot know — read this before using any number

We have **no farm-level yield data and cannot get it**. RMA's APH database is private. Therefore:

* The **county side** of every calculation is **MEASURED** from NASS county yield history. Its
  variability, trend, skew, and how often the index would historically have fired are facts.
* The **farm side** is **MODELLED**. Every county-level number in `basis_risk_county` describes a
  *typical* farm in that county — **not any actual farm, and not the reader's farm**.
* The path to a real answer is the **farm calculator**, which takes the producer's own APH yield
  history — a short series they read off their own schedule — and measures *their* correlation to
  the county. It needs no private data we do not have, because the producer supplies it.

A county map of this is a screening tool. It tells you where the area products are structurally a
poor fit. It cannot tell any individual whether to buy one.

---

## 3. The data we loaded

**Source:** USDA NASS Quick Stats, bulk file `https://www.nass.usda.gov/datasets/qs.crops_YYYYMMDD.txt.gz`.
Free, public, **no API key**. (The Quick Stats *API* requires a personal key — it returns
`401 unauthorized` unauthenticated — so the keyless bulk file is the only honestly automatable
path. The filename carries a build date, so the connector reads the directory index and takes the
newest file rather than hard-coding a URL.)

**Connector:** `src/connectors/nass_yield.py`, following the existing idioms — `http.Client`
download with the `url_cache` freshness gate and polite delay, `fetch_log` provenance, gated behind
`--force` like `rma_adm`/`prf_adm`. 1.13 GB gzipped is streamed and filtered in one pass.

**Loaded** (`nass_county_yield`, **local only**): 2,572,860 observations — 2,964 counties,
1866–2026, corn / soybeans / wheat, at four aggregation levels.

| | |
|---|---|
| COUNTY | 2,171,689 rows |
| DISTRICT (NASS ag statistics district) | 302,516 |
| STATE | 69,202 |
| NATIONAL | 1,516 |

Four levels, not one, because the model needs one parameter a county series cannot supply — see §5.

### Coverage after the quality gates

Gates: analysis window **1975–2025**; series must still be **live** (reach 2018 or later); at least
**12 usable years**.

| Crop | Counties scored | Median years | Grade A (≥30 yrs) |
|---|---|---|---|
| Corn | ~1,900 | 48 | ~1,790 |
| Soybeans | ~1,630 | 48 | ~1,475 |
| Wheat | ~1,580 (Winter + Spring + Durum) | 46 | ~1,490 |

Three crops, not because the estimator cares which crop it is, but because the connector's
`COMMODITIES` map stops there. **§8a measures what every other field crop would yield if loaded** —
cotton is the one worth doing, canola and dry peas genuinely cannot be done.

### Data decisions that materially affect the answer

* **NASS county coverage is shrinking.** Counties with a corn estimate fell from ~1,670 (2020) to
  ~1,210 (2025). A county's series can simply stop.
* **A dead series is refused, however long it is.** NASS stopped publishing county wheat at
  `CLASS_DESC='ALL CLASSES'` after **2007**. That series is *longer* than the WINTER series in many
  counties and completely useless for a 2026 recommendation, so selection is: live first, then
  longest, then class preference. `basis_risk_county.class_used` records what was chosen.
* **Suppressed values are missing, never zero.** NASS writes `(D)` (withheld to avoid disclosing an
  individual operation), `(NA)`, `(X)`, `(Z)` in the value column. Coercing any of those to 0 would
  enter a total crop failure into the history.
* **`OTHER (COMBINED) COUNTIES` (code 998) is dropped.** It is NASS's residual bucket for
  suppressed counties, has no FIPS, and its composition changes year to year.
* **Harvested-acre yield is the default** (`BU / ACRE`). Planted-acre yield
  (`BU / NET PLANTED ACRE`, which includes abandonment and so carries a deeper downside tail) is
  loaded as a robustness check but has far fewer county-years.

---

## 4. The estimator

### Step 1 — Detrend, and say how

A county yield series carries a strong technology trend. Treating it as risk inflates everything
downstream: a Corn Belt county whose yields nearly tripled since 1975 has a **raw** CV around 0.30
and an actual year-to-year risk near 0.13. We fit a trend and work in ratios to it:

```
ratio_t = y_t / fitted_t          (mean ≈ 1, unitless)
```

**Default: ordinary least squares on year.** Not arbitrary — it is the same form RMA itself uses
for the Trend-Adjusted APH endorsement and for the expected county yield that SCO/ECO settle
against, so `ratio_t` is the empirical analogue of the index RMA actually computes. `theilsen`
(median of pairwise slopes, more robust when two drought years drag the fitted line down) and
`mean` (no trend) are available; the method used is recorded on every output row
(`detrend_method`), along with the fitted slope in bu/yr, as %/yr, and its R².

The window starts at **1975** because a *linear* trend is only a fair description of the modern
era. NASS has county corn back to 1910; fitting one straight line through 1910–2025 would be a
worse model, not a better-informed one.

`tests/test_basisrisk.py::test_trend_is_not_risk` is the guard on this.

### Step 2 — The county distribution *is* the data

No parametric yield distribution is fitted. County draws come from a **variance-corrected smoothed
bootstrap** of the detrended ratios (Silverman & Young 1987; Efron & Tibshirani, *An Introduction to
the Bootstrap*, 1993, §16.5), which preserves the county's own left skew and its actual drought tail
rather than imposing a Beta or Normal shape. The variance correction (dividing by
`sqrt(1 + h²/s²)`) keeps the kernel from quietly inflating county risk.

### Step 3 — The farm is the county plus idiosyncratic risk

One equation:

```
y_farm = y_county + e,     e ⟂ y_county,     E[e] = 0
```

This is the **aggregation identity**, not a free-form assumption. If a county index is (near enough)
the acreage-weighted mean of the farms in it and farm deviations are exchangeable, then the county
*is* the systemic factor and each farm is that factor plus its own noise. Two consequences follow
immediately, and both are used:

```
corr(y_farm, y_county) = σ_county / σ_farm  ≡  ρ
σ_e = σ_county · sqrt(1/ρ² − 1)
```

**ρ and the farm/county standard-deviation ratio are the same parameter.** That is what makes the
whole exercise tractable: the county data pins down σ_county exactly, and exactly **one** number has
to be imported from outside. Everything else follows.

The default idiosyncratic shock `e` is **Normal — i.e. symmetric**. Real farm-specific shocks (hail,
one localized storm, one flooded bottom field) are left-skewed, so **the default understates basis
risk**. `--idio skewed` draws a reflected-Gamma `e` with the same variance and negative skew;
`test_skewed_idiosyncratic_raises_basis_risk_above_normal` pins the direction.

### Step 4 — Price, and why revenue triggers are safer than yield triggers

For the RP variants both the farm and the county are multiplied by the **same** harvest/projected
price ratio, because **price is national**: every insured acre in the country sees the same harvest
price. The price leg of an RP band therefore **cannot miss anybody**, and RP carries measurably less
basis risk than YP (`test_revenue_trigger_carries_less_basis_risk_than_yield_trigger`).

The corollary matters commercially: **a producer buying ECO-YP or SCO-YP is buying almost pure basis
risk** — the cheap part of the product is exactly the part that can fail them.

Price volatility is **measured**, from the 2026 ADM Price record (`A00810`, "Price Volatility
Factor"): corn 0.15 (range 0.00–0.16, n=227,796), soybeans 0.13 (0.12–0.13, n=351,498), wheat 0.19
(0.16–0.21, n=116,166).

The yield–price correlation is **not assumed directly**. It is built as

```
corr(county yield, price) = corr(county yield, NATIONAL yield) × corr(national yield, price)
```

where the first factor is **measured per county** from the NASS data and stored as `corr_national`,
and only the second is a single assumed national parameter (**−0.6**). A small county in an off-Belt
state gets very little of the natural hedge, and now the model knows that county by county instead
of assuming one number for the whole country.

### Step 5 — The metrics

At the producer's coverage level `CL` and the band's trigger:

* **farm loss** := farm ratio < `CL` (a loss beyond their own deductible)
* **band pays** := county index < trigger

| Column | Meaning |
|---|---|
| **`miss_rate`** | **P(band pays nothing \| farm loss)** — the headline |
| `p_hard_miss` | P(farm loss AND band pays nothing), an annual frequency |
| `p_farm_loss_given_no_pay` | P(farm loss \| county index above trigger) |
| `deep_miss_rate` | P(band pays nothing \| farm loss 10+ points beyond `CL`) |
| `windfall_rate` | P(band pays \| farm had **no** loss) |
| `uncovered_share` | share of the farm's in-band loss **dollars** left uncovered |
| `payout_corr` | corr(farm in-band loss, band payment) |

`windfall_rate` is not a criticism of the product. Those dollars are real income. But they are a
**transfer, not insurance**, and they are exactly the dollars that were not there in the years the
loss came and the cheque did not.

**The two limits that define all of this**, both asserted in the test suite:

* farm ≡ county → `miss_rate` **= 0**. An index that *is* the farm cannot miss it.
* farm ⟂ county → `miss_rate` **= P(county index ≥ trigger)**. Knowing the farm lost tells you
  nothing about the county, so the conditional collapses to the unconditional.

Everything else is an interpolation between those two, governed by ρ.

### Step 5b — The producer's coverage level, and why 0.85 was the wrong place to stand

The first build of `basis_risk_county` was produced at **coverage level 0.85 only**. That is a
defensible default in exactly one sense — it is the worst case — and wrong in every other, because
`miss_rate` is *monotone increasing* in the producer's election and 0.85 is the top of the grid.

**Why the direction is what it is.** A lower election is a *bigger* deductible. The farm losses
that qualify are therefore rarer and deeper, and a deep farm loss is far more likely to have come
from weather the whole county shared — which is precisely when the county index fires. So fewer of
the qualifying losses get missed:

```
lower producer coverage level → fewer, deeper qualifying farm losses → LOWER miss_rate
```

Measured on the national distribution of county CVs (RP, ρ = 0.70, medians across 4,935
county × crop cells):

| Band | CL 0.65 | 0.70 | 0.75 | 0.80 | **0.85** | election-blended |
|---|---|---|---|---|---|---|
| `ECO95` | 5.2% | 7.1% | 9.4% | 12.2% | **15.4%** | **9.5%** |
| `ECO90` | 10.1% | 13.3% | 16.8% | 20.7% | **25.1%** | **16.8%** |
| `SCO86` | 16.0% | 20.4% | 24.7% | 29.5% | **34.7%** | **24.8%** |

### What producers actually elect — measured, not assumed

Source: `sob_national` (RMA Summary of Business national rollup), **RY2025**, acre-weighted. Rerun
with `build_basis_risk.py --election-mix`, which also re-checks the constants in `src/basisrisk.py`
against the database.

| Population | 0.50 | 0.55 | 0.60 | 0.65 | 0.70 | **0.75** | 0.80 | 0.85 |
|---|---|---|---|---|---|---|---|---|
| Underlying buy-up, corn+soy+wheat (198.7M ac) | 2.3% | 0.2% | 2.5% | 3.0% | 15.5% | **35.6%** | 26.7% | 14.2% |
| **Producers who actually bought SCO** (6.6M ac) | 1.8% | 0.3% | 2.7% | 1.7% | 17.4% | **50.7%** | 23.3% | **2.3%** |

Two things follow, and the second is the sharper one:

* **0.85 is the tail, not the centre.** 14.2% of the book by acres (19.8% by liability), and the
  mode is 0.75.
* **Among people who buy an area band it is 2.3%.** SCO is the one endorsement whose Summary-of-
  Business `coverage_level` field reports the *underlying* policy's level rather than its own
  attachment, so this is a **direct measurement** of the deductible carried by area-band buyers —
  no inference. The old build described one SCO buyer in forty-four.
  (For ECO and MCO the same field carries the endorsement's own **trigger**, so an ECO buyer's
  underlying level is not observable in the national rollup at all. SCO buyers are the proxy, and
  the report prints both mixes so the substitution is visible.)

**What the 0.85-only build was costing the opportunity map.** The map multiplies unclaimed subsidy
by *responsiveness* = 1 − `miss_rate`. Applying the top of the grid everywhere over-discounts:

| | ECO | SCO | SCO + ECO |
|---|---|---|---|
| Raw unclaimed subsidy, covered cells (RY2026, corn/soy/wheat) | $1.651B | $1.353B | $3.00B |
| Basis-adjusted at CL 0.85 (as shipped) | $1.375B | $0.837B | $2.21B |
| Basis-adjusted at the measured election mix | $1.480B | $0.984B | $2.46B |
| **Over-discount** | +$106M (+7.7%) | +$147M (+17.6%) | **+$253M (+11.4%)** |

Nearly a third of the discount the map applied — $253M of $792M — was an artefact of the coverage
level chosen at build time, not a statement about basis risk. SCO takes the larger correction
because at CL 0.85 SCO is a *one-point-wide* band, the most degenerate configuration it has.

**The fix, now in place.** `--coverage-levels` defaults to
`basisrisk.PUBLISHED_COVERAGE_LEVELS = (0.65, 0.70, 0.75, 0.80, 0.85)` and `coverage_level` is part
of `basis_risk_county`'s primary key, so a caller selects the level it wants:

* a producer with a known election → their own level (`nearest_published_level` snaps off-grid
  elections **up**, which over-states their basis risk — the safe direction);
* one number for a typical producer → `MODAL_COVERAGE_LEVEL` = 0.75;
* a book-level rollup → `blend_over_coverage_levels(...)`, weighted by `SCO_ELECTION_MIX`.

The five published levels carry 95.0% of buy-up acres and 95.2% of SCO buyers' acres; the 5.0%
below 0.65 fold up into 0.65 rather than being dropped.

### Step 6 — Uncertainty from the length of the series

`bootstrap_miss_rate` resamples **years** (not draws) and **refits the trend on each resample**, so
the reported interval carries both the sampling error in the yield distribution and the estimation
error in the trend. Counties are graded and the grade ships on every row:

| Grade | Usable years |
|---|---|
| A | ≥ 30 |
| B | 20–29 |
| C | 12–19 |
| *(refused)* | < 12 |

---

## 5. ρ — the one imported parameter, and how far it moves the answer

Everything above is measured except ρ. ρ is handled three ways at once.

### (a) A data-driven estimate from public data alone

NASS publishes the same yield at four nested aggregation levels. Yield variance falls in a regular
way as the reporting unit grows, because independent local shocks average out. Fitting that decay
over the three orders of magnitude we *can* observe and extrapolating one order further down to farm
scale gives an estimate of σ_farm/σ_county — and therefore ρ — with no citation involved.

Run: `scripts/analysis/build_basis_risk.py --calibrate-rho`

| Crop | Fitted `var ~ area^b` | R² | County CV | National CV | **Implied ρ, 500-acre farm** |
|---|---|---|---|---|---|
| Corn | b = −0.198 | 0.970 | 0.175 | 0.078 | **0.72** |
| Soybeans | b = −0.225 | 0.811 | 0.132 | 0.066 | **0.58** |
| Wheat | b = −0.249 | 0.970 | 0.167 | 0.065 | **0.68** |

Farm size matters, and the model says so: corn at 200 acres → ρ 0.66; at 2,500 acres → ρ 0.85.
**A bigger farm is a better match for its county, and is better served by an area product.**

**This is an extrapolation beyond the observed range, and it is biased.** Within-county spatial
correlation is much higher than between-state correlation, so the fitted power law is too steep at
farm scale: it **overstates ρ and understates basis risk**. Treat it as a *floor* on basis risk and
a sanity check on the literature, never as a replacement. That it nonetheless lands at 0.58–0.72 —
at or below the reference value — is the useful result.

### (b) The literature

Farm–county yield correlation is well studied and the range is genuinely wide, varying by crop,
region and farm size. The lineage this model sits in:

* **Miranda, M. J. (1991),** "Area-Yield Crop Insurance Reconsidered," *American Journal of
  Agricultural Economics* 73(2):233–242 — the origin of the `y_farm = α + β·y_county + ε`
  decomposition used here, and of the observation that area-yield insurance effectiveness is
  governed by β and the residual variance.
* **Marra, M. C. & Schurle, B. W. (1994),** "Reference Unit Size and Yield Variability," (Kansas
  wheat) — the reference-unit-size work that the aggregation-scaling calibration in (a) descends
  from: yield CV falls systematically as the reference unit grows.
* **Skees, J., Black, J. R. & Barnett, B. J. (1997),** "Designing and Rating an Area Yield Crop
  Insurance Contract," *AJAE* 79:430–438.
* **Barnett, B. J., Black, J. R., Hu, Y. & Skees, J. R. (2005),** "Is Area Yield Insurance
  Competitive with Farm Yield Insurance?" *Journal of Agricultural and Resource Economics* 30(2).
* **Deng, X., Barnett, B. J. & Vedenov, D. V. (2007),** "Is There a Viable Market for Area-Based
  Crop Insurance?" *AJAE* 89(2):508–519.
* **Gerlt, S., Thompson, W. & Miller, D. J. (2014),** "Exploiting the Relationship between
  Farm-Level Yields and County-Level Yields for Applied Analysis," *JARE* 39(2) — the most directly
  applicable: farm-level yield variance is substantially larger than county-level, estimated from
  RMA APH data.

> **Standard of proof note.** The reference values below are set from the *data-driven* estimate in
> (a), which we ran ourselves and can reproduce, with the literature above cited for the framework
> and for the fact that the true range is wide. Where a specific published ρ point estimate would be
> needed to justify a narrower band, we have not verified one to the page and have therefore **not**
> narrowed the band. The sensitivity in (c) is the substantive defence, not the citation.

### (c) Sensitivity — reported on every row, because it is the weak point

`basis_risk_county` stores `miss_rate` at three correlations, not one:

| | ρ | Interpretation |
|---|---|---|
| `rho_lo` / `miss_rate_rho_lo` | **0.55** | small farm, heterogeneous county, or dryland in an irrigated county |
| `rho_ref` / `miss_rate` | **0.70** | the reference |
| `rho_hi` / `miss_rate_rho_hi` | **0.85** | large farm, homogeneous county |

**The ρ swing is larger than the spread across most states.** That is the honest limit on how hard
the county map can be pushed, and it is the reason the farm calculator exists rather than being a
nice-to-have: for an individual, ρ is *measurable*, and measuring it beats assuming it.

---

## 6. Results

*(Generated by `scripts/analysis/build_basis_risk.py --report`. Reference settings: RP plan type,
ρ = 0.70, OLS detrend, 1975–2025, and the **modal** farm coverage level 0.75 — not 0.85; see §4
Step 5b for why the drill-downs moved off the top of the grid.)*

See `RESULTS` section appended below by the build.

---

## 7. The farm calculator — the path to a real answer

```bash
# oldest year first
scripts/analysis/farm_basis_risk.py --county 19153 --crop Corn --start-year 2013 \
    --yields 152,188,196,214,201,205,178,209,198,145,216,203 --coverage-level 0.85

# or year:yield pairs, or --csv myaph.csv, or --all-bands to compare
```

What the producer gets that the county map cannot give them:

1. **Their measured correlation to the county — with its confidence interval.** Ten APH years buy a
   wide one (typically ±0.3 or more), and a point estimate would be a lie of precision. The
   calculator reports the modelled miss rate at the interval's endpoints, not just at the point.
2. **Their own history, year by year**: which years they were below their coverage level, which of
   those the county index would have paid, and which it would have missed — by year, named. Small
   sample, but it is *their* sample, and it is stated as a record rather than a frequency.
3. **The consistency check.** Under the model, the measured correlation and σ_county/σ_farm must
   agree. When they don't, the calculator says so instead of averaging them.

### Two warnings the calculator raises, and why they matter

* **"Your yields are LESS variable than the county's."** A single farm cannot be steadier than the
  average of every farm around it, so this is always an artefact. The usual cause is real and
  common: **the yields supplied are already trend-adjusted or APH-capped.** An APH database applies
  yield floors and T-yields that truncate exactly the bad years this calculation needs. Supply raw
  harvested yields.
* **"Measured correlation is NEGATIVE."** Not physically plausible over a long run; it means wrong
  county, wrong crop, an irrigated farm against a dryland county series, or a unit error.

In both cases the calculator falls back to the reference ρ *and says the result is no longer
farm-specific*, rather than silently producing a farm-specific-looking number.

**`farm_detrend` defaults to `county`**: the farm series is detrended at the *county's* estimated
%/year trend rather than its own. An APH series is 4–10 years, far too short to fit a trend to
without the fit absorbing the very variability being measured; the county trend is estimated from
40+ years and a farm in that county shares its technology. `--farm-detrend own` is available and
warns below 15 years.

---

## 8. What we could not determine

Stated plainly, because each one bounds a claim above.

1. **Anything about an actual farm, from the county data alone.** No farm-level yield data exists
   publicly. Every county number is a typical-farm estimate. This is the binding limitation.
2. **ρ, from data at farm scale.** Our estimate (§5a) extrapolates a power law one order of
   magnitude below its observed range, and is biased toward too little basis risk. The literature
   range is wide and we did not narrow it beyond what we could verify.
3. **Practice-specific county indices.** RMA rates and settles SCO/ECO by **type and practice**, so
   an irrigated farm's endorsement triggers on the *irrigated* county index. We score
   `ALL PRODUCTION PRACTICES` because that is the only practice with broad NASS county coverage.
   For a county where RMA prices irrigated and non-irrigated separately, the blended index used here
   is the wrong series — and the direction of the error differs by farm. (The
   irrigated/non-irrigated rate gap that proves RMA treats these as different risks is measured in
   `scripts/analysis/basis_risk.py`, Part A.)
4. **MCO's margin trigger** — see §8a, which sets out what an estimator would need.
5. **Prevented planting, replant, and quality adjustment**, all of which can make a farm's insurable
   loss differ from its yield loss.
6. **STAX** — see §8a. Unlike MCO this one is a loading problem, not a modelling problem.
7. **Whether RMA's expected county yield equals our fitted trend.** RMA publishes the *expected*
   county yield used for area plans in the ADM; we fit our own trend to NASS. They will not agree
   exactly, and a county whose RMA expected yield sits above our fitted trend will trigger less
   often than we estimate. Reconciling the two is the highest-value next step.
8. **The correlation between national yield and harvest price (−0.6)** is assumed, not measured.
   Measuring it requires projected/harvest price history from the ADM rather than cash prices.

---

## 8a. The two uncovered bands, and the uncovered crops

### MCO — the largest hole on the map, and the one that should stay a hole for now

MCO carries **$7.89B of unclaimed subsidy at 1.2% penetration** — the biggest raw figure in
`rowcrop_unclaimed` and 100% unmeasured for basis risk. It is also the one band that must not be
approximated with the estimator in this repo, for a reason of mechanism rather than effort.

**MCO settles on a county MARGIN, not a county revenue.** PM-25-029: *"a band of insurance from 86
percent up to 95 percent of expected crop value to cover producers' operating margins."* The
input basket, per the MCO FAQ, is **diesel, natural gas, urea, DAP and potash** — note it uses
natural gas where Margin Protection uses interest, so the two margin products do not even price the
same basket (`docs/rowcrop_endorsement_stacking.md` §3.3). That is a **third leg** in the joint
distribution, not a re-parameterisation of the two that are there.

What an MCO estimator would need, and what exists:

| Input | Status |
|---|---|
| County expected yield index | **Have** (NASS, corn/soy/wheat; cotton/sorghum/rice would need loading) |
| Projected & harvest price | **Have** (ADM `A00810`) |
| RMA's *expected margin* per county × type × practice | **Have, for RY2026 only** — ADM `A00810` carries `Expected Margin Amount`, `Expected Revenue Amount` and `Expected Index Value`, so the implied input-cost amount is just their difference (e.g. soybeans: $519.33 − $450.86 = **$68.47/acre**) |
| A **history** of that input-cost index | **Do not have, and it does not exist.** MCO's first reinsurance year is 2026. There is exactly one observation of the index |
| The joint distribution of (county yield, harvest price, input cost) | **Do not have.** This is the whole ballgame — input costs are strongly positively correlated with crop prices (2008, 2021–22), which *hedges* the margin |
| The basket weights / per-acre application rates by crop | Live in the MCO actuarial method and the 508(h) filing, not in anything loaded here |

**Verdict: report `unknown`, do not model.** Bolting MCO onto the yield model would not merely be
imprecise, it would be biased in a direction that is hard to sign, because the two errors run
opposite ways: the input-cost leg is *national*, like price, so it cannot miss anybody and pushes
MCO's basis risk **down** relative to a yield band — while the producer's *own* input costs (a
farm that pre-bought fertiliser, or runs a different rate) differ from the index and add a layer
that pushes it **up**. Neither is estimable from what we hold.

Reconstructing a 25-year history of RMA's basket from public component series (EIA diesel and
natural gas, fertiliser price indices) is a genuine research project, and the result would be *our*
index, not RMA's. The honest interim path is the one already taken: `src/rowcropopt.py` maps MCO to
no band variant, and `BASIS_BAND_NOTE` says so on the page.

**One caveat that belongs next to the $7.89B.** RY2026 is MCO's **first sales year**. A 1.2%
penetration rate in year one is what a new product looks like, not necessarily an untapped market;
the map's largest number is also its youngest, and it will move a lot on its own.

### STAX — a loading problem, not a modelling problem

STAX is upland-cotton-only and settles on **expected area revenue** with a trigger the producer
picks between 90% and 75% and a coverage range up to 20 points (23-STAX-0021 §1). That is
structurally the *same shape* the estimator already handles — a county revenue index with a trigger
and an exit. Nothing conceptual is missing. What is missing is cotton:

1. `src/connectors/nass_yield.py`'s `COMMODITIES` map stops at `CORN / SOYBEANS / WHEAT`. Adding
   `COTTON → Cotton` loads **408 usable upland-cotton counties**, 351 of them grade A (measured
   below).
2. `basisrisk.DEFAULT_UNIT` is hard-coded to `BU / ACRE`; cotton and rice are `LB / ACRE`, so the
   unit needs to become per-crop.
3. `BAND_SPECS` needs STAX entries keyed by trigger — `STAX90` (0.90 → 0.70), `STAX85`, … — and the
   protection factor (80–120%, §5(a)) scales liability, not the trigger, so it does not enter
   `miss_rate` at all.
4. `PRICE_VOL` needs cotton's factor; the 2026 ADM publishes it (0.13 on the rows checked).

STAX's whole book is **$0.22B unclaimed** against MCO's $7.89B, so this is a small prize — but it
is a small prize for a day's work, whereas MCO is a large prize for a research programme.

### Which further crops are feasible from NASS county yields

Counties whose SURVEY county yield series has **≥12 distinct years since 1975 and still reports in
2018 or later** — the same gates the estimator applies. Measured directly from the cached Quick
Stats bulk file (`qs.crops_20260807`), so these are what a load would actually yield, not an
estimate. "Grade A" is ≥30 years.

| NASS commodity / class | Unit | Usable counties | Grade A | Unclaimed on the map | Verdict |
|---|---|---|---|---|---|
| CORN, all classes | BU/ACRE | 1,917 | 1,810 | $3.92B | **loaded** |
| SOYBEANS, all classes | BU/ACRE | 1,628 | 1,475 | $2.30B | **loaded** |
| WHEAT — winter / spring / durum | BU/ACRE | 1,291 / 237 / 57 | 1,220 / 220 / 50 | $0.47B | **loaded** |
| **COTTON, upland** | LB/ACRE | **408** | 351 | $0.46B | **feasible — do this one.** Unlocks STAX *and* cotton SCO/ECO/MCO; covers 75% of the 542 cotton counties on the map |
| **SORGHUM** (catalog "Grain Sorghum") | BU/ACRE | **267** | 257 | $0.11B | **feasible**, but only 41% of the 647 sorghum counties on the map — the rest never had a county estimate |
| **RICE** | LB/ACRE | **81** | 75 | $0.11B | **feasible**; 77% of the 105 rice counties on the map |
| OATS | BU/ACRE | 576 | 525 | — | feasible, no material area-band book |
| BARLEY | BU/ACRE | 174 | 164 | — | feasible, thin |
| PEANUTS | LB/ACRE | 148 | 117 | — | feasible, thin |
| SUNFLOWER, oil type | LB/ACRE | 49 | 44 | — | marginal |
| BEANS, dry edible | LB/ACRE | 39 | 35 | — | marginal |
| **CANOLA** | LB/ACRE | 41 | **0** | $0.034B | **not feasible.** No county reaches 30 years; median ~20. Covers 23% of the 180 canola counties on the map |
| **PEAS, dry edible** | LB/ACRE | 29 | **0** | $0.019B | **not feasible.** Same problem, worse — 21% of map counties |
| FLAXSEED | BU/ACRE | 25 | 24 | — | not worth it |
| COTTON, Pima | LB/ACRE | 10 | 7 | — | **not feasible** |
| LENTILS / CHICKPEAS / MUSTARD / RYE | — | ≤10 | 0 | — | **not feasible** |

Two things this table settles. **Cotton is the one crop that materially moves the map** — it is the
fourth-largest unclaimed figure and it is the only band-and-crop pair where a single connector
change unlocks a whole band. And **canola and dry peas cannot be done at all**, not because nobody
loaded them but because NASS has never published a long enough county series; any number for them
would be a 20-year CV dressed up as a 45-year one. They stay `unknown`, which is the true answer.

---

## 9. Operations

### Load and build

```bash
# 1. Load the NASS history (heavy, opt-in, local only) — ~1.1 GB download, ~4 min
.venv/bin/python -m src.connectors.nass_yield --force
#    ...or through the orchestrator:  python -m src.refresh --source nass_yield --force

# 2. Precompute the shipped table
.venv/bin/python scripts/analysis/build_basis_risk.py

# 3. Inspect  (--report and --election-mix open the DB READ-ONLY and skip db.init_db, so they
#    are safe to point at the committed data/catalog_app.db; the build and --calibrate-rho
#    are not, because they need nass_county_yield and they write.)
.venv/bin/python scripts/analysis/build_basis_risk.py --report
.venv/bin/python scripts/analysis/build_basis_risk.py --report --at-coverage-level 0.85
.venv/bin/python scripts/analysis/build_basis_risk.py --election-mix
.venv/bin/python scripts/analysis/build_basis_risk.py --calibrate-rho
```

`--report` drills into the **modal** election (0.75) rather than the top of the grid, and ends with
a COVERAGE-LEVEL BIAS block that measures the over-discount of §4 Step 5b from the built rows.
`--election-mix` re-derives the election distribution from `sob_national` and flags any constant in
`src/basisrisk.py` that has drifted more than half a point from it.

### Size discipline — what has to be wired into `scripts/build_app_db.py`

The shipped app DB must stay under 95 MB. This work adds one heavy local table and one small
shipped one, exactly the `prf_opt_best` pattern.

**`scripts/build_app_db.py` needs two additions** (not made here — that file is owned elsewhere):

```python
DROP_TABLES = [
    ...,
    # NASS county yield + area history, 1866-2026 at four aggregation levels: ~2.6M rows and
    # the raw INPUT to the basis-risk estimator, exactly like prf_grid_index is to prf_opt_best.
    # The app reads the precomputed basis_risk_county instead; this never ships.
    "nass_county_yield",
]

REQUIRED = [
    ...,
    # The basis-risk result table. Small, and it is the ONLY thing that survives dropping
    # nass_county_yield above — without it the row-crop recommendation has no farm-specific
    # content at all and degenerates to "everyone should buy ECO".
    "basis_risk_county",
]
```

Measured footprint: `nass_county_yield` ≈ **420 MB** with its index (must not ship);
`basis_risk_county` ≈ **6.4 MB** at one coverage level, data plus indexes (ships).

**The coverage-level dimension is this table's one real budget line.** 373 bytes per row, measured,
and every extra level is a full set of ~2,960 rows:

| Coverage levels built | Rows | `basis_risk_county` | App DB |
|---|---|---|---|
| 1 (the old `0.85`) | 14,805 | 6.4 MB | 60 MB |
| **5 (the default now)** | **74,025** | **32.6 MB** | **~86 MB** |

That is inside the 95 MB ceiling and inside `build_app_db.py`'s 90 MB warning, but it spends most of
the remaining headroom. Two levers, in order of preference, if it ever needs to come back down:

1. **Drop levels, not columns.** `--coverage-levels 0.70,0.75,0.80,0.85` still covers 92.0% of
   buy-up acres and 93.7% of SCO buyers' acres for 26 MB.
2. **Normalise behind a view.** About half of each row (state, county name, `n_years`, the trend
   fit, `county_cv`, `county_skew`, `corr_national`, `grade`, provenance) does not vary with the
   coverage level and is duplicated five times. Splitting the per-county facts into one table and
   the per-level metrics into another, with `basis_risk_county` recreated as a **view** over the
   join, measures at **17.2 MB** for the same five levels — a 15.4 MB saving with no change to any
   reader, since every consumer selects named columns. `prf_opt_best` is already exactly this
   pattern (`scripts/build_app_db.py: dedupe_prf_opt_best`), and `REQUIRED` / `REQUIRED_COLUMNS`
   already accept a view. **Not done here**: it needs a DDL change in `src/db.py` plus a migration
   that drops the existing table (a `CREATE VIEW IF NOT EXISTS` is silently a no-op when a table of
   that name exists), and the working DB was mid-rebuild.

### Files

| File | Role |
|---|---|
| `src/connectors/nass_yield.py` | NASS bulk loader (new) |
| `src/basisrisk.py` | the estimator + the farm calculator (new) |
| `src/db.py` | `nass_county_yield`, `basis_risk_county` DDL (appended) |
| `scripts/analysis/build_basis_risk.py` | precompute, report, ρ calibration (new) |
| `scripts/analysis/farm_basis_risk.py` | the producer-facing CLI (new) |
| `scripts/analysis/basis_risk.py` | the pre-existing Monte Carlo + ADM/SoB evidence (unchanged) |
| `tests/test_basisrisk.py` | 67 tests: the two limits, the coverage-level direction, and the builder end-to-end on a synthetic county history |

`scripts/analysis/basis_risk.py` is complementary, not superseded: its Part A (the
irrigated/non-irrigated Reference Rate gap in the same county) and Part B (the price-vs-yield
decomposition of the band payment) are measured from ADM/SoB and are evidence this document leans
on. What it lacked, and what this adds, is a **county yield history** — so its Part C had to sweep ρ
in the abstract, where this can compute σ_county per county from data.
