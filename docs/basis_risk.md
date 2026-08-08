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
farm coverage level 0.85, ρ = 0.70, OLS detrend, 1975–2025.)*

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
4. **MCO's margin trigger.** MCO settles on a county *margin* — revenue minus an input-cost index.
   We model it as an area revenue band, which **understates** its basis risk, because input-cost
   basis is an additional layer we do not model at all.
5. **Prevented planting, replant, and quality adjustment**, all of which can make a farm's insurable
   loss differ from its yield loss.
6. **STAX** specifically. It is cotton-dominated and `docs/rowcrop_endorsement_stacking.md` already
   flags its Summary-of-Business rows as untrustworthy. The estimator will run on cotton counties,
   but cotton is not in the loaded crop set.
7. **Whether RMA's expected county yield equals our fitted trend.** RMA publishes the *expected*
   county yield used for area plans in the ADM; we fit our own trend to NASS. They will not agree
   exactly, and a county whose RMA expected yield sits above our fitted trend will trigger less
   often than we estimate. Reconciling the two is the highest-value next step.
8. **The correlation between national yield and harvest price (−0.6)** is assumed, not measured.
   Measuring it requires projected/harvest price history from the ADM rather than cash prices.

---

## 9. Operations

### Load and build

```bash
# 1. Load the NASS history (heavy, opt-in, local only) — ~1.1 GB download, ~4 min
.venv/bin/python -m src.connectors.nass_yield --force
#    ...or through the orchestrator:  python -m src.refresh --source nass_yield --force

# 2. Precompute the shipped table
.venv/bin/python scripts/analysis/build_basis_risk.py

# 3. Inspect
.venv/bin/python scripts/analysis/build_basis_risk.py --report
.venv/bin/python scripts/analysis/build_basis_risk.py --calibrate-rho
```

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
`basis_risk_county` ≈ **4 MB** (ships).

### Files

| File | Role |
|---|---|
| `src/connectors/nass_yield.py` | NASS bulk loader (new) |
| `src/basisrisk.py` | the estimator + the farm calculator (new) |
| `src/db.py` | `nass_county_yield`, `basis_risk_county` DDL (appended) |
| `scripts/analysis/build_basis_risk.py` | precompute, report, ρ calibration (new) |
| `scripts/analysis/farm_basis_risk.py` | the producer-facing CLI (new) |
| `scripts/analysis/basis_risk.py` | the pre-existing Monte Carlo + ADM/SoB evidence (unchanged) |
| `tests/test_basisrisk.py` | 48 tests, including the two limits (new) |

`scripts/analysis/basis_risk.py` is complementary, not superseded: its Part A (the
irrigated/non-irrigated Reference Rate gap in the same county) and Part B (the price-vs-yield
decomposition of the band payment) are measured from ADM/SoB and are evidence this document leans
on. What it lacked, and what this adds, is a **county yield history** — so its Part C had to sweep ρ
in the abstract, where this can compute σ_county per county from data.
