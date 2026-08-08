# Row-Crop Opportunity, and What It Looks Like With Basis Risk Priced In

**Where the unclaimed federal subsidy on SCO / ECO / MCO / STAX actually is — and where a
county is unsold because an area-triggered product does not work there.**

Author: research pass, 2026-08-07. Companion to `docs/basis_risk.md` (the estimator),
`docs/rowcrop_endorsement_stacking.md` (what the bands are) and
`docs/rowcrop_private_products.md` (the non-federal side). Code: `src/rowcropopt.py`
(the metric and the join), `src/basisrisk.py` (the basis-risk estimator),
`src/rowcroppage.py` (the map).

---

## 0. How to read this document

Every factual claim is tagged, on the convention `docs/rowcrop_private_products.md` sets:

- **[V]** — verified against a primary source (statute, RMA bulletin, or RMA's own published
  Summary of Business / Actuarial Data Master records as loaded in this repo). Source named.
- **[C]** — computed by me from the databases in this session. Most are reproduced by

  ```
  .venv/bin/python -m src.rowcropopt --db data/catalog_app.db --report-only --band ECO
  .venv/bin/python -m src.rowcropopt --db data/catalog_app.db --report-only --band SCO
  ```

  which reads only the two tables that ship (`rowcrop_unclaimed`, `basis_risk_county`) and is
  read-only. Where a number comes from somewhere else the query or module call is given inline.
- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis.

### The one-paragraph version

> The raw opportunity metric — unclaimed federal subsidy on eligible acres that do not carry a
> supplemental band — is a good number and it is **incomplete in one specific, dangerous way**:
> it assumes the band, if bought, would pay when the buyer had a loss. Every one of these bands
> settles on a **county index**, and how often that assumption holds is measurable. Weighting
> the raw metric by `1 − miss rate` cuts the national ECO figure to **83%** and the national SCO
> figure to **62%** **[C]**, re-orders the two products against each other, and moves individual
> counties by up to **18 percentile points** **[C]**. It also cannot be done at all for **52%**
> of the county × crop × band cells on the map **[C]** — and those cells are carried as
> *unknown*, which is a different thing from *low*.

---

## 1. The raw metric

```
unclaimed subsidy ($) = eligible acres × (1 − penetration) × subsidy captured per acre
```

`src/rowcropopt.py` computes it per **county × crop × band × crop year** into
`rowcrop_unclaimed` (44,979 rows across RY2025–RY2026; 25,721 rows and 2,066 counties in
RY2026) **[C]**. The full derivation, the eligibility rules behind the denominator and the
observed-vs-fitted labelling of the per-acre dollar figures are in that module's docstring and
are not repeated here. Three things matter for what follows:

| term | what it is |
|---|---|
| eligible acres | net acres on an **individual, additional-coverage** MPCI plan (YP, RP, RP-HPE, APH). CAT acres excluded — a CAT policy cannot carry a band **[V]** (RMA plan/coverage-type rules; `src/rowcropopt.py`) |
| penetration | band acres ÷ eligible acres, capped at 1.0 |
| subsidy captured per acre | the county's own figure where it sells the band, otherwise fitted from its liability per acre and labelled `state` / `national` |

The metric is deliberately the same number for two audiences: it is the federal money a
producer is leaving unclaimed, and — because agent commission is a percent of **total** premium
— its premium twin is the agency's prospecting size.

### 1.1 What the raw metric silently assumes

Read the formula again and ask what makes an unsold acre an *opportunity* rather than a
*decision*. The metric answers "how many federal dollars would attach to this acre". It does
not answer "would the coverage those dollars buy respond to this farm's loss". It assumes the
answer is yes, everywhere, with probability 1.

That assumption is the subject of the rest of this document.

---

## 2. Why low penetration is not automatically opportunity

Three reasons a rational, well-advised producer declines. Only the second is measurable here,
and it is the one that matters most.

1. **Eligibility.** Acreage designated as covered by **STAX cannot carry SCO** **[V]**
   (7 U.S.C. 1508(c)(4)(C)(iv) as amended) — this one *is* modelled: `EXCLUSIVE_PAIRS` in
   `src/rowcropopt.py` removes each band's acres from the other's denominator.
   The famous case, ARC, needs care and is **year-dependent**: through CY2025 an FSA farm
   serial number with ARC elected on a crop was barred from SCO on that crop **[V]**
   (20-SCO §5(a)(2); 2026 CIH FCIC-18010 ¶916J), and **OBBBA §10303(b) repealed that bar for
   CY2026** **[V]** (amended 7 U.S.C. 1508(c)(4)(C)(iv); RMA 25-OBBA; MGR-25-006: *"Insureds
   can now purchase the SCO regardless of their Area Risk Coverage (ARC) elections"*). All of
   this is verified line by line in `docs/rowcrop_endorsement_stacking.md` §(b), against the
   statute, the bulletin and the 2027 handbook. **Consequence for this map:** the RY2026 view —
   the default — is *not* distorted by ARC at all; the RY2025 rows still are, by an amount
   Summary of Business cannot reveal. Other disqualifiers (uninsurable ground, a practice or
   type the ADM does not offer) remain invisible: the metric counts acres, not eligibility.
2. **Basis risk.** SCO, ECO, MCO and STAX all settle on a **county** index **[V]** (RMA
   MGR-25-006 and the band provisions; summarized in
   `docs/rowcrop_endorsement_stacking.md`). Individual MPCI settles on the producer's own unit.
   A farm poorly matched to its county index gets a product that pays when it did not need it
   and fails to pay when it did.
3. **Availability.** A band is only offered where the actuarial documents offer it.
   `rowcrop_unclaimed` does not read ADM; it infers the offer from observed sales and grades
   the inference in its `evidence` column (2 = sold in this county, 1 = somewhere in this
   state, 0 = only elsewhere nationally).

**[R]** Reason 2 is not a footnote on the metric, it is a **competing explanation for the whole
map**. If a county is unsold *because* the county index does not describe its farms, then
ranking it as a top prospect is not merely imprecise — it is wrong in the direction that would
have an agency sell a product that cannot respond to its client's loss. A map that cannot
distinguish "nobody has offered this yet" from "the people here looked at it and were right to
say no" is not a prospecting tool, it is a lead list with a chart on it.

---

## 3. The adjustment

### 3.1 Definition

`basis_risk_county` (built by `scripts/analysis/build_basis_risk.py` from `src/basisrisk.py`)
publishes, per county × crop × band-trigger:

```
miss_rate = P(the band pays NOTHING | the farm has a loss beyond its own deductible)
```

Its complement is exactly the weight §1.1 says the raw metric sets to 1:

```
responsiveness  R = 1 − miss_rate     = P(the band pays | the farm has a loss)

basis-adjusted unclaimed subsidy = unclaimed subsidy × R
basis-adjusted unclaimed premium = unclaimed premium × R
```

`src/rowcropopt.responsiveness()` and `.adjust()`. Both return `None` — never `0`, never the
unadjusted value — when the miss rate is unknown.

### 3.2 Why `1 − miss_rate`, and why multiplicative

**[R]** Four reasons, in the order they were decided:

1. **It is the term the raw metric is missing, not a new opinion bolted on.** The raw metric is
   `acres × shortfall × dollars`, with an implicit fourth factor of 1 for "and the coverage
   works". Making that factor explicit and filling it with a measured number changes nothing
   else about the metric. Any *additive* penalty, or any re-scoring scheme, would be a
   different metric rather than the same one with its assumption exposed.
2. **`miss_rate` is `basisrisk.py`'s own declared headline**, is the column the module's grade
   and both of its uncertainty measures attach to, and is the only one with a rho-sensitivity
   pair. Choosing a different column would mean carrying an adjustment whose uncertainty is not
   published beside it.
3. **It is bounded, monotone and legible.** `R ∈ [0, 1]`; the adjusted figure is never larger
   than the raw one and never negative; and "$4.5M of the $5.3M attaches to coverage that shows
   up" is a sentence a reader can check against the two columns.
4. **It never destroys the raw number.** Both are shipped, both are on the map, and §7 is about
   where they disagree. The adjustment is offered as a *second reading*, not a correction.

### 3.3 What the adjusted figure is NOT

**It is not a dollar forecast.** The federal subsidy on an unsold acre is the same number
whatever the county index does; a producer who buys ECO captures the subsidy in a year the band
pays nothing. The adjusted figure is a **ranking weight** with dollar units — it says how much
of the money on the table buys protection that arrives in the years the client needs it. Any
sentence of the form "this county has $4.5M of unclaimed subsidy" must use the **raw** column.

**It is not risk-neutral-equivalent.** A band with a 40% miss rate is not worth 60% of a band
with a 0% miss rate to a producer. Utility over a shortfall is not linear in the probability of
being paid, and the windfall payments the same product makes in no-loss years are real income
that this weight throws away entirely. **[R]** The weight is a ranking device, and the honest
claim for it is ordinal.

**It does not price MCO's margin trigger, prevented planting, replant, or quality adjustment**
— none of which `src/basisrisk.py` models. See §9.

### 3.4 Alternatives considered and rejected

| candidate | why not |
|---|---|
| `uncovered_share` (share of in-band loss **dollars** left uncovered) | Arguably the better economic weight, and it is carried in the tooltip and the table. Rejected as the *headline* because it moves in the **opposite** direction to `miss_rate` as the farm's coverage level falls (**[C]** for Champaign-belt Illinois county 17075 Corn, SCO86: `miss_rate` 0.409 → 0.275 from CL 0.85 → 0.75, while `uncovered_share` 0.427 → 0.468), so the two cannot both be the single number without saying which question is being asked. `miss_rate` answers "does it respond at all", which is the question that decides whether to recommend the product. |
| `deep_miss_rate` (miss on losses 10+ points past the deductible) | The right weight if the only losses that matter are severe ones. Carried in the tooltip. Not the headline because it discards the shallow losses the bands are specifically designed to cover. |
| `1 − payout_corr` | Correlation is not a probability and cannot be multiplied into a dollar figure without a story about the distribution. |
| Rank-within-tiers (sort raw, break by basis grade) | Hides the magnitude of the adjustment and makes the "where do they disagree" question unanswerable. |
| Replacing the raw metric | Refused outright. The two disagree in useful ways and the disagreement is §7. |

---

## 4. The join

`rowcrop_unclaimed` × `basis_risk_county` on **(county_fips, crop, band)**.
`src/rowcropopt.join_basis_risk()`. Both tables ship in the slim app DB, so the join happens at
page-build time and there is no third precomputed table to go stale against its parents.

### 4.1 Band → trigger

The two tables do not share a band vocabulary, because a band's basis risk depends on its
**trigger**.

| `rowcrop_unclaimed` | `basis_risk_county` | note |
|---|---|---|
| `SCO` | `SCO86` | SCO attaches at 86% and runs down to the producer's own coverage level **[V]** |
| `ECO` | **`ECO95`**, falling back to `ECO90` | see below |
| `MCO` | *(nothing)* | no estimator |
| `STAX` | *(nothing)* | no estimator |

**ECO → ECO95 is not a coin flip.** **[V]** In RY2026 `sob_sales` (plan codes 87/88/89),
**100,126,453** net acres elect the 95% trigger and **1,057,738** elect 90% — **99.0%** of the
book is ECO95. `ECO90`'s row is carried as the alternative election and is used only where a
county has no `ECO95` row.

```sql
SELECT coverage_level, SUM(net_acres) FROM sob_sales
WHERE year = 2026 AND plan_code IN ('87','88','89') GROUP BY 1;
-- 0.95 -> 100,126,453   |   0.90 -> 1,057,738
```

**MCO and STAX get nothing, deliberately.** MCO settles on a **margin** index — county revenue
less input costs — and `src/basisrisk.py` models yield and revenue triggers only. STAX has no
estimator at all. Borrowing SCO's number for either would look reasonable on the map and be
invented. They are `unknown`, and §5 is about what that costs.

### 4.2 Coverage level — and why the adjustment is conservative

`basis_risk_county` is published at **plan RP, coverage_level 0.85** — the *farm's own*
deductible, which is what defines "a farm loss". `rowcrop_unclaimed` pools every coverage level.

0.85 is the **highest common election**, and a higher deductible means shallower events count
as losses, which means **more** of them are idiosyncratic, which means the **highest** miss rate
of any coverage level. **[V]** RY2026 individual additional-coverage base acres by election:

| coverage level | net acres | share |
|---|---|---|
| 0.75 | 76,467,699 | 39.2% |
| 0.80 | 49,666,439 | 25.4% |
| 0.70 | 29,042,319 | 14.9% |
| **0.85** | **23,388,277** | **12.0%** |
| 0.60 / 0.65 / 0.50 / 0.55 | 16,688,298 | 8.5% |

So **88.0% of the eligible book insures below 85%** and gets a *lower* real miss rate than the
one used here. **[C]** Re-running `basisrisk.basis_risk()` on the same detrended county series
at other coverage levels (Corn, 60k draws, seed 7):

| county | band | CL 0.85 | 0.80 | 0.75 | 0.70 |
|---|---|---|---|---|---|
| 17075 IL Iroquois | ECO95 | 0.198 | 0.156 | 0.116 | 0.086 |
| 17075 IL Iroquois | SCO86 | 0.409 | 0.342 | 0.275 | 0.217 |
| 19039 IA Clarke | ECO95 | 0.242 | 0.213 | 0.183 | 0.157 |
| 20003 KS Allen | ECO95 | 0.218 | 0.192 | 0.167 | 0.143 |
| 31041 NE Dawson | ECO95 | 0.051 | 0.017 | 0.003 | 0.000 |

**The adjustment therefore discounts opportunity by more than the modal buyer's own basis risk
warrants, not less.** That is the safe direction for this particular error **[R]**, but it is an
error: a county's adjusted figure understates the responsiveness a 75%-coverage producer would
actually get. Fixing it properly means rebuilding `basis_risk_county` across coverage levels
(`build_basis_risk.py --coverage-levels`) and joining on the county's own modal election. See
§10.

### 4.3 The `(all crops)` rollup

`rowcrop_unclaimed`'s `(all crops)` row is the sum over every crop the band is offered on. Its
basis risk is the **acre-weighted mean** over the per-crop rows beneath it that have an
estimate, weighted by eligible acres, with every term (miss rate, both rho bounds, deep-miss,
uncovered share) weighted identically so they stay mutually consistent. The rollup inherits the
**worst** grade among its contributors.

Two guards:

- The rollup carries `cover_share` — the fraction of its eligible acres whose crops have an
  estimate — and is labelled `partial` whenever that is below 1.
- Below **`MIN_BASIS_COVER = 0.50`** the rollup publishes **nothing** and reverts to `unknown`.
  A weighted mean over a minority of the acres is a statement about the minority. **[C]** 377 of
  the 3,798 RY2026 `(all crops)` cells with any coverage at all fall below the floor; 191 fall
  below 0.25.

**[R]** Applying the covered crops' miss rate to the whole cell's dollars *is* an extrapolation
— from Corn/Soybeans/Wheat onto the county's Cotton or Sorghum acres. It is made because the
alternative (dropping every rollup, i.e. the map's default view) throws away more than it
protects; it is bounded below by the 50% floor; it is labelled `partial` with its share
everywhere it appears; and it is *within one county across crops*, not across geography. It is
the single softest step in the join.

---

## 5. The coverage gap

**Half the map has no answer, and the map says so.**

**[C]** `rowcrop_unclaimed` holds **9,271** distinct (county, crop) keys. `basis_risk_county`
holds **4,935**, of which **4,511 overlap** — **48.7%**. At the cell grain the RY2026 picture is:

| band | covered | partial | **unknown** | why unknown |
|---|---|---|---|---|
| ECO | 5,044 | 1,147 | **2,751** | crop outside Corn/Soybeans/Wheat, or a county series under 12 usable years |
| SCO | 5,044 | 1,148 | **2,747** | same |
| MCO | 0 | 0 | **6,806** | **no estimator** — margin trigger not modelled |
| STAX | 0 | 0 | **1,034** | **no estimator** |
| **total** | **10,088** | **2,295** | **13,338** | 51.9% of all cells |

`basis_risk_county` covers 2,169 counties across three crops — Corn 1,902 counties, Soybeans
1,628, Wheat 1,405 **[C]**.

### 5.1 How unknown is represented

It is a **third state**, carried end to end, and it is never allowed to become either of the
other two:

- **In the join** (`src/rowcropopt.py`): a cell with no estimate is simply **absent** from the
  result dict. Absence is the wire format for unknown on purpose — there is no sentinel value
  for a downstream reader to coerce into a low miss rate, and `adjust()` returns `None` rather
  than the unadjusted value.
- **In the payload** (`src/rowcroppage.py`): `basis_risk[fips][crop][band]` is absent. Not
  `null` in a fixed slot, which is the thing that gets read as `0`.
- **On the map**: the county is drawn **hatched**, not tinted. Any tint places it somewhere on
  the colour ramp, and every position on the ramp is a claim we do not have. The legend carries
  its own hatched swatch reading *"basis risk unknown — N counties, not ranked here. **Unknown
  is not low.**"*
- **In the tooltip**: `Basis risk UNKNOWN for <band> — not low, not zero, not ranked`, followed
  by the *named* reason (MCO's margin trigger, STAX having no estimator, or the crop being
  outside Corn/Soybeans/Wheat).
- **In the ranking panel**: unknown counties are listed **below a break**, headed *"NOT RANKED
  — basis risk unknown"*, with their raw figure shown and their adjusted cell reading
  `unknown`. They are neither dropped (which would silently turn a ranking of the country into
  a ranking of the measured half) nor mixed into the order on their raw value (which would let
  an unmeasured county outrank a measured one on the strength of the very term that is missing).
- **Across bands**: under "All bands", if **any** selected band is unknown, the whole selection
  is unknown. **[R]** The bands are different products with different triggers; extrapolating
  across crops within one band is defensible, extrapolating ECO's miss rate onto MCO's
  margin-triggered dollars is not.
- **When `basis_risk_county` is missing entirely**: `load_basis_risk()` returns `{}` and the
  map renders every county as unknown with a note naming the build command. It does not raise.

### 5.2 The most expensive unknown

**[C]** **MCO carries the largest raw unclaimed figure of any band on the map — $3.557B across
1,243 counties, at 1.2% national penetration — and 100% of it is basis-risk unknown.** It is
also in its **first book year** (no MCO acres in RY2025 at all), so nearly every eligible acre
reads as unclaimed because the endorsement has only just been offered.

**[R]** This is the single most important thing on the page for anyone deciding where to work:
the biggest pool of "opportunity" the raw metric finds is the one product whose basis risk this
project cannot evaluate and which nobody has had a chance to buy yet. The map states both
facts, in the note bar and in the tooltip. Neither is a reason not to look at MCO. Both are
reasons not to put it at the top of a call list on the strength of the dollar figure.

---

## 6. Top counties by each measure

RY2026, `(all crops)`, `evidence >= 1`, counties **with** a basis-risk estimate
(n = 1,710 for ECO, 1,711 for SCO). Full lists from `--report-only`. **[C]**

### 6.1 ECO — totals

| # | county | raw unclaimed | basis-adjusted | miss | coverage |
|---|---|---|---|---|---|
| 1 | Cass ND | $7,779,429 | $6,369,108 | 18.1% | partial |
| 2 | Polk MN | $6,883,855 | $5,645,988 | 18.0% | partial |
| 3 | Iroquois IL | $6,765,074 | $5,461,202 | 19.3% | covered |
| 4 | Richland ND | $6,269,900 | $5,214,930 | 16.8% | partial |
| 5 | Spink SD | $6,118,555 | $5,019,265 | 18.0% | partial |
| 6 | Saline MO | $6,092,250 | $5,113,735 | 16.1% | covered |
| 7 | Marshall MN | $5,868,107 | $4,714,102 | 19.7% | partial |
| 8 | Livingston IL | $5,841,480 | $4,594,846 | 21.3% | covered |
| 9 | Yuma CO | $5,336,564 | $4,763,680 | 10.7% | partial |
| 10 | Kit Carson CO | $5,256,489 | $4,463,967 | 15.1% | partial |

Ranked by the **adjusted** column instead, the same ten counties reshuffle mildly and two
change places at the bottom: Yuma CO climbs from 9th to 7th (10.7% miss — the lowest in the
group), Kit Carson CO drops out, and **Whitman WA** ($5.11M raw, 10.8% miss) enters 10th.

### 6.2 SCO — totals

| # | county | raw unclaimed | basis-adjusted | miss |
|---|---|---|---|---|
| 1 | Polk MN | $7,513,358 | $4,664,141 | 37.9% |
| 2 | Cass ND | $6,579,783 | $3,896,762 | 40.8% |
| 3 | Kit Carson CO | $6,393,942 | $4,391,690 | 31.3% |
| 4 | McLean ND | $6,259,717 | $4,097,885 | 34.5% |
| 5 | Wells ND | $5,983,898 | $3,874,115 | 35.3% |

Adjusted: Kit Carson CO climbs 3rd → 2nd and Cass ND falls 2nd → 4th, on a 9.5-point miss-rate
difference between them.

### 6.3 The band-level re-ranking, which is bigger than any county's

**[C]** Nationally, over the counties that have an estimate:

| band | raw unclaimed | × R | basis-adjusted | effective miss |
|---|---|---|---|---|
| ECO | $1.768B | 0.833 | **$1.472B** | 16.7% |
| SCO | $1.461B | 0.620 | **$0.907B** | 38.0% |
| MCO | $3.557B | — | **unknown** | — |
| STAX | $0.103B | — | **unknown** | — |

Raw, ECO's pool is **1.21×** SCO's. Adjusted, it is **1.62×**. **[R]** This is the largest
single effect of the whole exercise and it is a *product* re-ranking, not a geographic one: at a
producer's 85% coverage level SCO is a **one-coverage-point-wide** band whose county index has
to fall to 86% before it pays anything, and it misses more than twice as often as ECO95 does.
Anyone reading the map to decide which band to lead a conversation with should read this row
before reading any county.

Underlying distribution of `miss_rate` across the 4,935 county × crop keys **[C]**:

| variant | min | p10 | median | p90 | max | mean |
|---|---|---|---|---|---|---|
| ECO95 | 0.003 | 0.111 | 0.164 | 0.210 | 0.259 | 0.162 |
| ECO90 | 0.029 | 0.209 | 0.267 | 0.311 | 0.370 | 0.262 |
| SCO86 | 0.142 | 0.296 | 0.359 | 0.432 | 0.515 | 0.361 |

---

## 7. Where the two rankings diverge

**This is the section worth reading.** It is where an agency's incentive and a producer's
interest come apart, and it is invisible in the totals.

### 7.1 The totals barely disagree; the per-acre measure does

**[C]** Spearman rank correlation between the raw and basis-adjusted orderings:

| band | on county **totals** | on **$ per eligible acre** |
|---|---|---|
| ECO | 0.9995 | 0.9960 |
| SCO | 0.9978 | 0.9862 |

**[R]** The totals agree because county **size** swamps everything: a 500,000-acre county
outranks a 50,000-acre county under any weight between 0.6 and 1.0. That agreement is not
reassurance, it is a measurement artifact of what the total is mostly made of. Strip size out
and the disagreement appears, because that is the measure on which basis risk is competing with
something its own size.

Rank movement on the per-acre measure **[C]**:

| band | counties moving ≥5 pctl | ≥10 pctl | largest move | top-decile churn |
|---|---|---|---|---|
| ECO | 94 (5%) | 2 (0%) | +7.6 / −11.5 | 12 of 171 drop out |
| SCO | **511 (30%)** | **74 (4%)** | **+14.5 / −18.1** | **19 of 171 drop out** |

Sign convention throughout: **positive = the raw ranking oversells the county** (it ranks higher
on dollars than on dollars-that-respond). Negative = the raw ranking undersells it.

### 7.2 SCO — the eastern Corn Belt is systematically oversold

**[C]** State means of the per-acre rank gap, states with ≥15 counties:

| oversold by raw | | undersold by raw | |
|---|---|---|---|
| IA | **+4.7** | ID | **−6.4** |
| IL | +4.2 | OK | −6.2 |
| IN | +4.1 | OR | −6.1 |
| AR | +3.9 | TX | −6.1 |
| KY | +3.1 | MT | −5.8 |
| WI | +3.0 | CO | −5.4 |
| OH | +3.0 | WA | −4.6 |
| MO | +2.7 | KS | −4.2 |

An **11-percentile-point** systematic swing between Iowa and Idaho. Individual counties, worst
first **[C]**:

| oversold | raw $/ac (pctl) | adjusted $/ac (pctl) | Δ | miss |
|---|---|---|---|---|
| Knox IN | $10.77 (p72) | $5.90 (p58) | **+14.5** | 45.2% |
| Wapello IA | $11.73 (p80) | $6.47 (p67) | +13.9 | 44.8% |
| Effingham IL | $11.68 (p80) | $6.45 (p66) | +13.7 | 44.7% |
| Washington IA | $9.02 (p54) | $4.83 (p40) | +13.5 | 46.4% |
| Dane WI | $10.64 (p71) | $5.97 (p59) | +12.1 | 43.9% |

| undersold | raw $/ac (pctl) | adjusted $/ac (pctl) | Δ | miss |
|---|---|---|---|---|
| Yuma AZ | $6.59 (p28) | $5.18 (p46) | **−18.1** | 21.4% |
| Bingham ID | $9.48 (p59) | $7.01 (p75) | −15.8 | 26.1% |
| Madison ID | $9.25 (p56) | $6.73 (p71) | −14.8 | 27.2% |
| Oldham TX | $7.39 (p37) | $5.47 (p51) | −13.9 | 25.9% |
| Gilliam OR | $8.82 (p52) | $6.37 (p65) | −13.5 | 27.8% |

### 7.3 ECO — a different, smaller, and differently-shaped map

**[C]** Oversold: AL +2.1, KY +2.0, SD +1.9, MO +1.9, ND +1.9, SC +1.8, VA +1.6, TN +1.4.
Undersold: NY −4.0, ID −3.6, NE −3.2, WA −2.9, OR −2.8, MI −1.6, CO −1.4, OH −1.4.

Worst individual movers **[C]**: Lac Qui Parle MN +7.6 (22.5% miss), Decatur IA +7.3,
Calloway KY +6.8; and the other way, Kearney NE −11.5 (6.1% miss), Canyon ID −11.4,
Dawson NE −9.9, Franklin NE −9.7.

Note that **the two bands do not oversell the same places**. Iowa and Illinois lead the SCO
overstatement list and are near-neutral on ECO; Nebraska is the most understated state for ECO
and only mid-pack for SCO. A single "basis risk" intuition applied to both bands would be wrong
about at least one of them.

### 7.4 Why the geography looks like this

**[C]** Correlations between `miss_rate` and the measured county statistics on the same row,
across all 4,935 keys:

| | vs `county_cv` | vs `p_county_below_trigger` | vs `corr_national` | vs `uncovered_share` | vs `payout_corr` |
|---|---|---|---|---|---|
| ECO95 | **+0.686** | +0.159 | +0.275 | +0.500 | −0.880 |
| SCO86 | **−0.374** | **−0.507** | +0.554 | +0.995 | −0.495 |

**The sign on county variability flips between the two bands**, and that is the whole
explanation for §7.2 vs §7.3. **[R]** The mechanism:

- **ECO95** triggers at 95% of expected county revenue — barely below trend, so the county index
  crosses it routinely everywhere. What decides whether the band pays *in a farm's own loss
  year* is how much of that farm's loss was idiosyncratic. With `rho` held at 0.70 the modelled
  farm-specific shock scales with the county's own standard deviation, so **high-variability
  counties miss more**: Alabama, Kentucky, North Dakota and Missouri (state mean Corn `county_cv`
  0.29, 0.20, 0.27, 0.23) against Nebraska and New York (0.13, 0.12) **[C]**.
- **SCO86** triggers at 86% — deep — and at an 85% farm coverage level is **one point wide**.
  Now the binding constraint is whether the county index ever gets down to 86% at all. A very
  stable county almost never does: Dawson NE Corn has `p_county_below_trigger` of **0.021** for
  SCO86 against 0.25 for ECO95 **[C]**. So the eastern Corn Belt — moderate `county_cv` (IA
  0.157, IN 0.153, IL 0.171) but *high* correlation to the national crop (Wapello IA 0.76,
  Effingham IL 0.73, Knox IN 0.65) — gets both a county index that seldom reaches the trigger
  and a harvest-price leg that props that index up in exactly the systemic years. Dryland Texas
  Panhandle and irrigated Idaho, with `corr_national` of 0.06 and 0.10 **[C]**, get neither:
  their shortfalls are local, unhedged by price, and drive the county index straight through
  86%.

**[R]** Stated plainly for an agency: **in the eastern Corn Belt, SCO's raw dollar figure is the
least trustworthy number on this map.** Those are the counties where the product's own economics
are weakest relative to how good the dollars look, and they are also the counties an agency's
raw prospecting list would send you to first.

### 7.5 The honest caveat on all of §7

**[R]** The cross-county variation in `miss_rate` is driven **entirely by the shape of the
county yield distribution**, because `rho` — the farm-to-county correlation, the one parameter
imported from outside the data — is held at **0.70 for every county in the country**. So §7 is a
ranking of *county index behaviour*, not of measured farm-to-county heterogeneity. If real `rho`
varies systematically by region (large uniform Corn Belt fields versus fragmented irrigated
ground would be the obvious hypothesis), some of the geography above is that variation showing
up in the wrong column. **This is not testable with any data in this repo.** The map ships the
whole `rho` 0.55–0.85 sensitivity band on every tooltip for that reason, and the honest use of
§7 is to generate questions for a producer's own APH schedule
(`src/basisrisk.farm_basis_risk()`), not to close them.

---

## 8. What the page does with all this

`src/rowcroppage.py`. Four metrics were added; **none replaced**:

| metric | family | what it draws |
|---|---|---|
| `adjtotal` | basis risk | basis-adjusted unclaimed subsidy, total $ |
| `adjacre` | basis risk | the same per eligible acre — the measure that actually re-ranks |
| `miss` | basis risk | the term itself, on its own red ramp so it cannot be confused with the money maps |
| `bgap` | divergence | raw percentile − adjusted percentile, diverging ramp, amber = raw oversells |

Plus: a **Top counties** ranking panel showing raw, basis-adjusted and miss side by side with
the unknown counties below a break; a basis-risk block in **every** tooltip whatever metric is
selected, including its rho band, its dollar-weighted and deep-loss views, its grade and its
partial-coverage share; a hatched fill and its own legend swatch for unknown; and the
basis-adjusted column added to the county drill-down panel.

The always-visible `<summary>` of the caveat block — the part that does not collapse — now
reads, before anything else on the page:

> Low penetration is not automatically opportunity, and this map is **not a list of people to
> sell to**. An unsold acre can be unsold because the producer is **ineligible**, or because
> they **rationally declined on basis risk** — these bands pay on a COUNTY index, and on a farm
> that does not track its county that is a product which cannot respond to the client's loss.
> Measured for 48% of the county × crop × band cells here (10,088 fully, 2,295 partly); 13,338
> are UNKNOWN, which is not low.

### 8.1 Storage

**Nothing needs adding to `scripts/build_app_db.py`.** Both inputs already ship: it keeps
`rowcrop_unclaimed` (44,979 rows) and `basis_risk_county` (14,805 rows, ~5.5 MB) and drops their
raw inputs (`sob_sales`, `nass_county_yield`). The join is done at page-build time from those
two tables, which is cheaper than a third table and cannot go stale against either parent. The
shipped DB is unchanged at 60 MB against the 95 MB guard. The rendered page grows from 2.19 MB
to **2.80 MB**; five of `basis_risk_county`'s eight modelled terms ship on the wire, rounded to
three decimals, and the two dropped (the bootstrap interval, and `windfall_rate`) remain in the
table, the CLI report and this document.

**[R]** One recommendation, not made because that file is out of scope: add
`("basis_risk_county", "miss_rate")` to `REQUIRED_COLUMNS` in `scripts/build_app_db.py`. Today a
shipped DB built from a working catalog that never ran `build_basis_risk.py` would pass every
guard and render every county "unknown" — which is *honest*, but silently so.

---

## 9. Caveats

Everything below applies to every number in §6 and §7.

**On the basis-risk estimator** (all of these are `src/basisrisk.py`'s own, restated because
they travel with the join):

1. **No farm-level data exists in this project and none can.** RMA's APH database is private.
   The **county** side of every estimate is measured from NASS county yield history; the
   **farm** side is *modelled*. Every figure describes a **typical farm** in the county and
   **none of them describes any actual farm**.
2. **`rho = 0.70` is imported from outside the data** and is the only such parameter. It is held
   constant nationally. See §7.5. The `rho` 0.55–0.85 sensitivity is published on every row and
   on every tooltip; at the low end ECO95's mean miss rate rises from 0.162 to **0.250** and at the
   high end falls to **0.064**, and SCO86's moves 0.361 -> 0.455 / 0.235 **[C]** — a range wider than most of the cross-county variation in §7.3.
3. **The idiosyncratic shock is Normal by default, i.e. symmetric.** Real farm-specific shocks
   (hail, one flooded bottom) are left-skewed, so the default **understates** basis risk.
4. **Series length varies.** Grades: A (≥30 usable years) 13,770 rows, B (20–29) 744, C (12–19)
   291; below 12 years no row is written at all **[C]**. Range 12–51 years, mean 44.5. A grade-C
   county's miss rate is a much weaker claim than a grade-A county's and the rollup inherits the
   worst grade among its crops.
5. **MCO's margin trigger is not modelled**, prevented planting / replant / quality adjustment
   are not modelled, and STAX has no estimator. See §5.2.

**On the join specifically:**

6. **Coverage level mismatch — the adjustment is conservative.** §4.2. Published at CL 0.85;
   88.0% of the eligible book insures below that and would see a lower miss rate.
7. **The `(all crops)` rollup extrapolates across crops within a county** above a 50% acre
   floor, and is labelled `partial` with its share wherever it does. §4.3.
8. **48% coverage.** §5. Unknown is carried explicitly and is not low.
9. **ECO is scored at the 95% trigger.** Correct for 99.0% of the book **[V]**, wrong for the
   1.06M acres that elected 90%, whose real miss rate is about 10 percentage points higher.

**On the opportunity metric underneath:**

10. **The RY2025 SCO denominator is overstated by the ARC bar**, which applied through CY2025
    and which Summary of Business cannot reveal. RY2026 — the map's default year — is clean on
    this point: the bar was repealed **[V]**. §2, item 1. Do not carry the old "ARC blocks SCO"
    intuition into a 2026 conversation; per `docs/rowcrop_endorsement_stacking.md`, a producer
    who declines SCO in 2026 to protect an ARC election is giving up coverage for nothing.
11. **Availability is inferred from observed sales**, not read from ADM.
12. **ECO's and MCO's stacking interactions are not modelled.** Only SCO↔STAX exclusivity is.
13. **MCO is in its first book year**, so its penetration is a calendar fact rather than a
    backlog.
14. **Commission rates are SAMPLE data** in `data/seed/aip_commission.csv`. Every agency figure
    on the page is labelled ASSUMED for that reason. No basis-risk figure depends on them.

---

## 10. What is not done

1. **`basis_risk_county` at more than one coverage level.** The single biggest improvement
   available, and mechanical: `build_basis_risk.py --coverage-levels 0.70 0.75 0.80 0.85`, then
   join on each county's own acre-weighted modal election from `sob_sales`. It would remove the
   conservative bias in §4.2 and make the adjustment describe the book instead of its
   most-protected 12%.
2. **No estimator for MCO or STAX** — §5.2 — which leaves the largest raw pool on the map
   unevaluated.
3. **Crops beyond Corn, Soybeans and Wheat.** Cotton, Grain Sorghum, Rice, Canola and Dry Peas
   have no county-yield basis-risk estimate here, which is most of what makes the Southern
   Plains and the Delta unknown.
4. **`rho` is not regionalized.** §7.5. `basisrisk.aggregation_scaling()` derives an independent
   data-driven estimate of it and is not yet used to vary it by region or farm size.
5. **No year axis on the adjustment.** `basis_risk_county` is a single long-run estimate per
   county; the map's crop-year selector changes the opportunity side only.
6. **The producer-facing farm calculator is not on this page.** `farm_basis_risk()` takes a
   producer's own APH history and answers the question this map can only pose. Wiring it into
   the county drill-down is the natural next step, and is what would turn §7 from a research
   finding into something usable in front of a client.
