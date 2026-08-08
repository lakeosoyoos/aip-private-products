# LGM — Livestock Gross Margin (plan code 82)

**The margin leg. What its subsidy actually keys off, where the deductible optimum sits, how
it compares to DRP and LRP on realized experience, and why its "fixed ration" is only fixed
for one of the three commodities.**

Author: research pass, 2026-08-08. Companion to `docs/producer_decision_research.md` (LRP and
DRP) and `docs/rowcrop_private_products.md`, whose tagging convention this document follows.

---

## 0. How to read this document

- **[V]** — verified against a primary source: an RMA policy, handbook, premium-calculation
  instruction, product-management bulletin, or RMA's own Actuarial Data Master. Document and
  section given.
- **[C]** — computed by me in this session, from RMA's published Actuarial Data Master and
  from the cached Summary of Business files in `data/cache/`. Every `[C]` number is
  reproduced by:

  ```
  .venv/bin/python scripts/analysis/lgm_deductible.py
  .venv/bin/python scripts/analysis/lgm_deductible.py --only curve
  ```

- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis.

### The one-sentence version

> LGM's subsidy is the only one in this catalog keyed on the **deductible** rather than a
> coverage level; a $0 deductible is **not** unsubsidised (it draws 18%), the genuinely
> unsubsidised case is a **single-month marketing plan**, and because the ladder caps at 50%
> while premium keeps shrinking, the deductible that maximises expected dollars sits strictly
> inside the grid — at **$70/head for cattle, $10/head for swine, $1.00/cwt for dairy**, in
> all 50 states.

---

## 1. The subsidy structure

### 1.1 It keys off the deductible — confirmed [V]

`ADM A00070 Subsidy Percent` carries plan 82 under **record category 05**, whose key column
is `Deductible Amount`. `Coverage Level Percent` is blank on every plan-82 row. The same
file, same reinsurance year, keys the other two livestock plans differently: **[V]**

| plan | record category | key column | source |
|---|---|---|---|
| 81 LRP | 08 | `Range Low/High Value` (coverage level) | `2027_ADM_YTD.zip` → `A00070_SubsidyPercent` |
| **82 LGM** | **05** | **`Deductible Amount`** | same file |
| 83 DRP | 04 | `Coverage Level Percent` | same file |

The full filed ladder, pulled from `{RY}_ADM_YTD.zip` for both years: **[V]**

| deductible | Cattle (0803) | | deductible | Swine (0815) | | deductible | Dairy (0847) |
|---|---|---|---|---|---|---|---|
| $0 | 0.18 | | $0 | 0.18 | | $0.00 | 0.18 |
| $10 | 0.20 | | $2 | 0.21 | | $0.10 | 0.19 |
| $20 | 0.23 | | $4 | 0.25 | | $0.20 | 0.21 |
| $30 | 0.27 | | $6 | 0.30 | | $0.30 | 0.23 |
| $40 | 0.31 | | $8 | 0.37 | | $0.40 | 0.25 |
| $50 | 0.36 | | $10 | 0.47 | | $0.50 | 0.28 |
| $60 | 0.43 | | **$12–$20** | **0.50** | | $0.60 | 0.31 |
| **$70–$150** | **0.50** | | | | | $0.70 | 0.34 |
| | | | | | | $0.80 | 0.38 |
| | | | | | | $0.90 | 0.43 |
| | | | | | | $1.00 | 0.48 |
| | | | | | | **$1.10–$2.00** | **0.50** |

Deductible grids and increments are confirmed independently in the handbooks: cattle "$0 per
head to $150 per head in $10 increments" (LGM for Cattle Handbook 2027, FCIC-20060, §21
D(7)); swine "$0 per head to $20 per head in $2" (LGM for Swine Handbook, §21 D(7)); dairy
"$0 per cwt to $2.00 per cwt in $0.10 increments" (LGM for Dairy Cattle Handbook 2026,
FCIC-20080, §21 D(7)). **[V]**

### 1.2 A $0 deductible is subsidised at 18% — the framing is refuted [V]

The working assumption going in was that a $0 deductible receives **no** subsidy. It does not
survive the documents. Every commodity's bottom rung is **0.18**, and RMA's own worked
example computes a producer premium at exactly that rate:

> "In this example, since the producer chose a $0.00 deductible and had pooled coverage, the
> premium subsidy is 0.18 or 18%."
> — *LGM-Cattle Premium Calculation, Step by Step Instructions*, Step 6 (July 2020) **[V]**

### 1.3 Where the zero actually is: unpooled coverage [V]

There **is** a zero-subsidy case in LGM, and the framing had located it on the wrong dial. It
is the marketing plan, not the deductible:

> "The producer is only eligible for premium subsidy if they target market in two (2) or more
> months of an insurance period. This is calculated for each SCE."
> — *LGM for Dairy Cattle Handbook 2026* (FCIC-20080, April 2025), Part 2 §21 D(8); the same
> sentence appears at §21 D(8) of the Cattle and Swine handbooks. **[V]**

> "You are only eligible for premium subsidy if you target market in 2 or more months of an
> insurance period."
> — *26-LGM Dairy Cattle* policy (released April 2025), §5(b) Premium **[V]**

RMA's premium instructions print this as a second column of the subsidy table:

> "Premium subsidy is given in the table below under step six, based on the deductible chosen
> and the numbers of months with insured marketings. Pooled coverage is when two or more
> months of an insurance period have insured marketings. Unpooled coverage is when only one
> month of an insurance period has insured marketings."
> — *LGM-Cattle Premium Calculation*, p.2 **[V]**

and the "Subsidy for Unpooled Coverage" column is **0.00 at every deductible from $0 through
$150**. **[V]**

So the cliff is real but orthogonal: a single-month marketing plan is unsubsidised at a $150
deductible exactly as hard as at $0.

### 1.4 What changed for RY2027 — the base ladder did not [V][C]

PM-26-024 (April 30, 2026) says the 2027 revisions

> "Revise the definition of beginning farmer or rancher and update the subsidy percentages to
> conform with the One Big Beautiful Bill Act." **[V]**

which reads like a change to the table above. It is not. The RY2026 and RY2027 plan-82 rows
of `A00070` are **identical, value for value, across all three commodities and all 48
rungs**. **[C]**

What the OBBBA changed is the beginning-farmer add-on layered on top of the policy's flat
rule:

> "If you qualify as a beginning farmer or rancher, your premium subsidy will be 10 percentage
> points greater than the premium subsidy that you would otherwise receive, unless otherwise
> specified in the Special Provisions."
> — *26-LGM Dairy Cattle*, §5(f) **[V]**

RMA's 2027 announcement adds an extra 5 points in BFR years one and two, 3 in year three, 1
in year four, on top of that 10. **[V]** `lgm.subsidy_rate(bfr_year=...)` implements both, and
gates them behind the pooling rule — an unpooled beginning farmer is still unsubsidised.
**[C]**

**Do not treat the ladder as frozen.** It is loaded from the ADM per year into `lgm_subsidy`
and read from there; the module constant is a documented fallback, not the source of truth.
**[R]**

### 1.5 The 3% load, which the usual shorthand drops [V][C]

This repo's shorthand is *net expected gain = total premium × subsidy rate*, which holds only
when a plan is rated to a loss ratio of exactly 1.0. LGM is not:

> "Total premium = 1.03 * premium"
> — *LGM-Cattle Premium Calculation*, Step 5 **[V]**

So at RMA's own rating E[indemnity] = total premium / 1.03, and

```
net expected gain = total premium × (1/1.03 − 1 + subsidy)
```

The break-even subsidy is therefore **2.9126%**, not 0%. **[C]** Two consequences:

- An **unpooled** LGM purchase loses 2.91% of total premium in expectation. Small, but
  strictly negative — it is the only configuration in this repo's federal catalog that is
  value-destroying by construction. **[C]**
- A **$0 deductible, pooled** purchase nets 15.1% of total premium, not zero. **[C]**

---

## 2. The deductible optimum

### 2.1 Why it must be interior [R]

Raising the deductible raises the subsidy **rate** and shrinks the premium **base**. Their
product is what a producer nets. The rate stops rising at the 0.50 cap while the base keeps
falling, so the product peaks strictly inside the grid — it cannot be at the top, and it is
at the bottom only if premium decays faster than the rate climbs over the first rungs.

### 2.2 Where it actually sits [C]

Computed from RMA's published expected margins (`A00600 LgmGrossMargin`) and its 500 published
margin draws (`A00610 LgmDraw`), running RMA's Steps 1–7 at every filed deductible with the
marketing plan held fixed at equal exposure in every insurable month. RY2027 for cattle and
swine, RY2026 for dairy (see §5.2).

| commodity / type | grid | **argmax net gain** | subsidy there | ladder caps at | argmax return per $1 | net gain vs $0 | states agreeing |
|---|---|---|---|---|---|---|---|
| Cattle · Calf Finishing | $0–150 / $10 | **$70** | 0.50 | $70 | $70 | **1.93×** | 50 / 50 |
| Cattle · Yearling Finishing | $0–150 / $10 | **$70** | 0.50 | $70 | $70 | **1.86×** | 50 / 50 |
| Swine · Farrow to Finish | $0–20 / $2 | **$10** | 0.47 | $12 | $12 | 1.08× | 50 / 50 |
| Swine · Feeder Pig Finishing | $0–20 / $2 | **$10** | 0.47 | $12 | $12 | 1.07× | 50 / 50 |
| Swine · SEW Pig Finishing | $0–20 / $2 | **$10** | 0.47 | $12 | $12 | 1.07× | 50 / 50 |
| Dairy | $0–2.00 / $0.10 | **$1.00** | 0.48 | $1.10 | $1.10 | 1.39× | 50 / 50 |

**The optimum is always at, or one rung below, the point where the ladder caps.** Never at
$0; never at the top of the grid. Every state agrees, for every commodity and type. **[C]**

The size of the prize varies a lot. Moving a cattle SCE from a $0 to a $70 deductible nearly
doubles the expected net benefit (1.9×); the same move in swine is worth 7–8%. That is a
premium-decay-rate difference: cattle total premium falls 72% across its grid, dairy only 43%.
**[C]**

Worked curve, RY2026 LGM-Dairy, Wisconsin, 10,000 cwt/month for 10 months: **[C]**

| deductible $/cwt | subsidy | total premium | producer premium | net expected gain | return per $1 | guarantee retained |
|---|---|---|---|---|---|---|
| 0.00 | 0.18 | 85,942 | 70,472 | 12,966 | 1.18 | 100.0% |
| 0.50 | 0.28 | 60,325 | 43,434 | 15,134 | 1.35 | 96.7% |
| 0.90 | 0.43 | 43,613 | 24,859 | 17,483 | 1.70 | 94.1% |
| **1.00** | **0.48** | **39,902** | **20,749** | **17,991** | 1.87 | 93.4% |
| 1.10 | 0.50 | 36,450 | 18,225 | 17,163 | **1.94** | 92.8% |
| 1.50 | 0.50 | 24,749 | 12,374 | 11,654 | **1.94** | 90.2% |
| 2.00 | 0.50 | 14,182 | 7,091 | 6,678 | **1.94** | 86.9% |

### 2.3 The two objectives are not the same question — and one of them goes blind [C]

- **Maximise return per producer dollar.** At rated experience this is `1/(1−subsidy)`. It is
  monotone in the subsidy, so it picks the *cheapest* deductible that reaches the 0.50 cap —
  and then it is **flat at 1.94 across every rung above it**. In the dairy table above it
  cannot tell $1.10 from $2.00, while net expected gain falls 61% between them. A producer
  optimising the repo's familiar metric gets no signal at all in the region where most of the
  benefit is thrown away. **[C]**
- **Maximise net expected dollars.** Interior, as tabulated. **[C]**
- **Maximise protection.** Always $0 — the guarantee retained is monotonically decreasing.
  **[C]**

A producer who cannot absorb the deductible in a bad year is rationally buying variance
reduction and paying for it in expected value. That is not an error; it is a different
objective, and §2.2 is not advice to them. **[R]**

### 2.4 $70 is a fact about this year's price spread, not about LGM-Cattle [C][R]

The argmax depends on how volatile the *total* simulated margin is relative to the deductible
grid. Widen the margin distribution and the optimum rises; tighten it and it falls, all the
way to $0. `tests/test_lgm.py::test_optimum_depends_on_the_margin_spread_not_on_a_constant`
pins that directionally. This is why `src/lgm.py` recomputes the curve per (commodity, type,
state, sales date) rather than shipping the table above as a constant. **[C][R]**

---

## 3. The two head-to-heads, on realized experience

From the cached `sobtpu` files, settled crop years only (through 2024), national. This is the
same `loss_ratio / (1 − subsidy)` metric `sob_national.indemnity_per_producer_dollar` uses.
**[C]**

### 3.1 Subsidised era (2021–2024)

| plan | total premium | subsidy | loss ratio | **indemnity per producer $** |
|---|---|---|---|---|
| **LGM Dairy Cattle** | 78,503,078 | 47.9% | 1.01 | **1.93** |
| LGM Swine | 147,309,662 | 44.0% | 0.98 | 1.76 |
| **DRP (all)** | 1,595,724,412 | 44.1% | 0.75 | **1.34** |
| LRP (all) | 2,053,098,233 | 35.2% | 0.64 | **0.99** |
| **LGM Cattle** | 48,942,234 | 47.8% | 0.21 | **0.40** |

### 3.2 All settled years (through 2024)

| plan | total premium | subsidy | loss ratio | indemnity per producer $ |
|---|---|---|---|---|
| LGM Swine | 161,984,349 | 40.0% | 0.99 | 1.65 |
| DRP (all) | 1,690,705,878 | 44.1% | 0.75 | 1.33 |
| LGM Dairy Cattle | 173,377,876 | 45.7% | 0.63 | 1.16 |
| LRP (all) | 2,126,228,487 | 34.5% | 0.67 | 1.02 |
| LGM Cattle | 51,127,128 | 45.8% | 0.21 | 0.39 |

**LGM-Cattle and LGM-Swine were effectively unsubsidised before crop year 2021** — the
Summary of Business reports 0% subsidy on their rows through 2019, while LGM-Dairy shows
subsidy from 2011. **[C]** The 2021+ window is therefore the regime a producer faces today,
and the long window blends two different products. Both are shown because they disagree.

### 3.3 LGM-Dairy vs DRP

Same milk, two subsidised products; the question is whether feed-cost risk is worth insuring.

- In the subsidised era **LGM-Dairy beats DRP** on realized return per producer dollar, 1.93
  vs 1.34 — and it does so despite a *lower* subsidy ceiling (0.50 vs DRP's 0.55 at the 80%
  coverage level). The whole difference is rating: LGM-Dairy came in at a loss ratio of 1.01
  against DRP's 0.75. **[C]**
- Over the longer window the ranking reverses (1.16 vs 1.33), because LGM-Dairy's 2011–2019
  experience was poor (loss ratios of 0.00, 0.07, 0.16, 0.32 in 2011–2014). **[C]** Four years
  of a favourable regime is not a durable edge. **[R]**
- **This stopped being an either/or for 2027.** The 26-LGM Dairy policy still bars it at
  §3(i) — you "may not have any other FCIC reinsured livestock policy covering the same class
  of livestock for any month for which you have target marketings" **[V]** — but RMA's 2027
  announcement lists "Permitting concurrent coverage between similar livestock programs" among
  the changes effective for the 2027 crop year. **[V]** So from RY2027 the comparison becomes
  a portfolio question rather than a choice. This module does not model a stacked LGM+DRP
  position. **[R]**

### 3.4 LGM-Cattle vs LRP

Price-only vs margin, same herd. **LRP wins decisively: 0.99 vs 0.40.** **[C]**

LGM-Cattle is the standout finding, and it is the **mirror image** of the row-crop result
already on record in this repo (85% coverage returns the worst 1.72 per producer dollar
because its subsidy collapses to 47% despite a middling loss ratio). Here the subsidy is at
the *top* of the ladder — 47.8%, better than LRP's blended 35.2% — and the product still
returns 40 cents on the producer dollar, because `0.21 / (1 − 0.478) = 0.40`. **A generous
subsidy rate cannot rescue a loss ratio of 0.21.** **[C]**

Caveats, in order of importance: **[R]**

- 2021–2024 is a historically extraordinary cattle-margin regime (record fed-cattle prices
  against a feeder market that has not kept up). Low LGM-Cattle loss ratios are partly *why*
  nobody needed the coverage, not evidence the product is mispriced forever.
- The premium base is small ($49M over four years, vs $2.05B for LRP), so the ratio is noisy.
  But it is consistently low: 0.06, 0.26, 0.02, 0.29 in 2021–2024. **[C]**
- The RY2027 ADM shows Iowa yearling-finishing expected margins that are **negative** in most
  months (feeder cattle at $363/cwt against fed cattle at $225/cwt). **[C]** A margin product
  written on an expected margin near or below zero has degenerate protection metrics —
  `guarantee_retained` goes negative — and is a different instrument from the one the historic
  loss ratios describe. Treat cattle numbers this year with care.

---

## 4. The ration — LGM's basis risk

LGM settles on a ration RMA declares, not on the operation's feed bill. That is structurally
the SCO/ECO county-index-vs-my-farm problem `src/basisrisk.py` handles. The important
correction to the premise is that **the three commodities are not equally exposed.**

### 4.1 What RMA declares, and who can change it [V]

| commodity / type | corn | soybean meal | animal in | out | election |
|---|---|---|---|---|---|
| Cattle · Calf Finishing | 52 bu/hd | — | 5.5 cwt | 11.5 cwt | **electable**: corn 50–75 bu, in 4–6 cwt, out 11–16 cwt |
| Cattle · Yearling Finishing | 50 bu/hd | — | 7.5 cwt | 12.5 cwt | **electable**: corn 50–85 bu, in 6–12 cwt, out 12–18 cwt |
| Swine · Farrow to Finish | 12 bu/hd | 138.55 lb | — | 2.6 cwt | **FIXED** |
| Swine · Feeder Pig Finishing | 9 bu/hd | 82 lb | — | 2.6 cwt | **FIXED** |
| Swine · SEW Pig Finishing | 9.05 bu/hd | 91 lb | — | 2.6 cwt | **FIXED** |
| Dairy | 0.014 t (0.5 bu) /cwt | 0.002 t (4 lb) /cwt | — | 1 cwt | **electable**: corn 0.00364–0.0381 t, SBM 0.000805–0.013 t per cwt |

Governing wording:

> "Unless the insured chooses target corn, feeder cattle and live cattle weight, cattle insured
> in a yearling finishing operation will be assumed to weigh 750 pounds (7.5 cwt) when they
> enter the feedlot, to weigh 1,250 pounds at slaughter (12.5 cwt), and to consume 50 bushels
> of corn. Cattle insured in a calf finishing operation will be assumed to weigh 550 pounds
> (5.5 cwt) when they enter the feedlot, to weigh 1,150 pounds at slaughter (11.5 cwt), and to
> consume 52 bushels of corn."
> — *LGM for Cattle Handbook 2027* (FCIC-20060), §21 D(10) **[V]**

> "All swine are assumed to be marketed at 260 pounds. This number will be expressed in cwt as
> 2.6 cwt. Swine insured in a Farrow to Finish operation are assumed to consume 12 bushels of
> corn and 138.55 pounds of soybean meal. Swine insured in an operation that Finishes Feeder
> Pigs are assumed to consume 9 bushels of corn and 82 pounds of soybean meal. Swine insured
> in an operation that finishes Segregated Early Weaned Pigs are assumed to consume 9.05
> bushels of corn and 91 pounds of soybean meal."
> — *LGM for Swine Handbook*, §21 D(10) **[V]**

> "The number of tons of corn per month is restricted to be between 0.00364 and 0.0381 tons
> per cwt of milk. The number of tons of soybean meal per month is restricted to be between
> 0.000805 and 0.013 tons per cwt of milk. Default values of 0.014 tons (0.5 bushels) of corn
> and 0.002 tons (4 pounds) of soybean meal per cwt of milk can be used if producers do not
> wish to choose feed amounts."
> — *LGM for Dairy Cattle Handbook 2026* (FCIC-20080), §21 D(4) **[V]**

Cattle carries an extra constraint: live minus feeder weight "must not exceed 6 cwt for
yearling finishing operations, and 10 cwt for calf finishing operations" (§21 D(4)). **[V]**
`ration_divergence()` enforces it.

The cattle defaults are published twice and agree exactly — the handbook constants above, and
the `Corn / Live Cattle / Feeder Cattle Equivalent Default Value` columns of ADM `A00600`. The
module prefers the ADM copy so a future change is picked up without a code edit. **[C]**

### 4.2 So the honest statement is [R]

> LGM's ration basis risk is **eliminable** for cattle and dairy inside RMA's declaration
> band, and **irreducible** outside it and for swine at all times.

An operation that simply accepts the defaults is taking avoidable basis risk in two of three
commodities. That is a different piece of advice from "LGM has basis risk."

### 4.3 How to measure a given operation's divergence [C]

`lgm.ration_divergence()` reports three layers, and they are not the same thing:

1. **Physical** — per-leg deltas, and whether each leg is inside the band.
2. **Level** — the gap in expected margin per unit at a given price set. **This is not basis
   risk.** It shifts the guarantee up or down, and the deductible dial can be moved to offset
   it.
3. **Risk** — measured across RMA's *own* published draws: the residual standard deviation
   between the operation's true margin and the insured margin, the tracking correlation, and
   `unexplained_variance_share = 1 − corr²`. That last number is the LGM analogue of
   `basisrisk.py`'s miss rate: the fraction of the operation's real margin risk the policy
   does not follow.

Worked example — a dairy feeding 0.9 bu corn and 0.0035 t soybean meal per cwt against RMA's
0.5 bu / 0.002 t default, both legs still inside the band: **[C]**

```
verdict                    divergent but ELIMINABLE — declare your own ration
expected margin, insured   $15.054/cwt
expected margin, actual    $12.730/cwt
LEVEL gap                  -$2.324/cwt      <- offsettable with the deductible
residual sd                 $0.347/cwt      <- BASIS RISK
insured margin sd           $2.576/cwt
tracking correlation        0.9917
variance NOT tracked        1.64%
```

Note how different those two numbers are. The level gap is large and alarming-looking; the
actual untracked risk is 1.64%. Feed prices and milk prices move together enough that a
*ration* error mostly produces a level bias, not a tracking failure. **[R]** The tracking
number degrades as the ration error grows, and `tests/test_lgm.py` pins that monotonicity.
**[C]**

---

## 5. Data, and what could not be determined

### 5.1 The one-line change `src/connectors/rma_sob.py` needs [C]

That file's own docstring is right: `sobcov` omits plans 81/82/83 and `sobtpu` includes them.
Confirmed — 156,439 livestock rows are sitting in the already-cached `sobtpu` zips, crop years
2003–2026. **[C]**

They are dropped one filter later than the docstring implies: not by the plan map, but by
**`sob_crop()`**, because `ADM_ROW_CROP_CODES` (imported from `rma_adm`) has no entry for
0803 / 0815 / 0847, so it returns `None` and `canonical_records()` skips the row. The minimal
change is one line at the top of `sob_crop()`'s body, before the `ADM_ROW_CROP_CODES` lookup:

```python
if plan_code in LIVESTOCK_PLAN_CODES:
    return LIVESTOCK_COMMODITY_CODES.get(commodity_code)
```

with, alongside the existing WFRP constants:

```python
LIVESTOCK_PLAN_CODES = {"81", "82", "83"}
LIVESTOCK_COMMODITY_CODES = {"0803": "Cattle", "0815": "Swine",
                             "0847": "Dairy Cattle", "9999": "Livestock (aggregated)"}
```

Two things to know before wiring it: **[C]**

- **Do not relax the gate on the `sobcov` path.** sobcov genuinely omits the livestock plans,
  so `sob_sales` / `sob_national` would gain crops with no rows. Livestock experience exists
  only on the `sobtpu` path — `sob_unit`, `sob_unit_national`.
- **`coverage_level` is `.0000` on every plan-82 row from 2008 forward.** Those rows will land
  on the `coverage_level = 0` slot of a primary key that assumes a real level. That is correct
  — LGM has no coverage level — but any per-level rollup must exclude them rather than treat 0
  as a level.
- A large and growing share of plan-82 premium is filed under commodity **9999 "All Other
  Commodities"** — 68% in 2024, 80% in 2026 — but the type code and quantity type still
  identify the real commodity uniquely. `lgm.commodity_from_sob()` recovers it, and the §3
  tables use it. Without that recovery, four fifths of recent LGM business is uncategorised.
  **[C]**

The same note lives in code at `src.lgm.SOB_GATE_NOTE`, with a test asserting it stays
accurate.

### 5.2 LGM-Dairy is missing from the RY2027 livestock ADM [C]

As of the `20260806` file, `2027_ADMLivestockLgm_Daily_*.zip` contains cattle (0803) and swine
(0815) only — no dairy rows in either `A00600` or `A00610`, and the same is true of the
earliest RY2027 file (`20260702`). **[C]** LGM-Dairy is nonetheless clearly *offered* for
RY2027: its full 21-rung subsidy ladder is filed in the RY2027 `A00070`. **[C]** The most
likely reading is that dairy margin/draw rows publish on their own weekly cadence and had not
landed at the time of this pass **[R]**; §2.2's dairy row therefore comes from RY2026. Worth
re-checking rather than assuming.

### 5.3 The draw count contradicts RMA's own instructions [V][C]

The premium instructions specify `i = 1, 2, ...., 5,000` and divide by 5,000. **[V]** The
published `A00610 LgmDraw` member carries **Margin Draw Number 1..500** — 500 draws per state
× type, for every commodity, in both RY2026 and RY2027. **[C]** `src/lgm.py` divides by the
count it is handed and records it, and `premium_stderr()` reports the sampling error, because
a 500-draw premium is an estimate of the number an AIP's system produces, not that number.

The construction was validated the only way available: for RY2027 Iowa cattle type 807, the
mean of the 500 assembled draws reproduces RMA's own published expected gross margin in all
ten months to within Monte Carlo noise (350.75 vs 351.03 … 411.64 vs 410.46); dairy reproduces
to 0.11% and swine to 0.18%. **[C]**

### 5.4 What I could not determine

- **Realized loss ratio by deductible.** It does not exist in any public RMA file: `sobtpu`
  reports `Coverage Level` as `.0000` for every plan-82 row from crop year 2008 forward. **[C]**
  Everything in §2 is therefore forward-looking, computed off RMA's own rate draws, and cannot
  be backtested. The §3 tables are realized but blended across whatever deductibles producers
  actually elected — the ~46–48% observed blended subsidy implies most business already sits
  at or near the 0.50 cap. **[R]**
- **The exact statutory text behind the OBBBA subsidy change.** I verified the ADM ladder is
  unchanged between RY2026 and RY2027 **[C]** and quoted PM-26-024 and RMA's announcement
  **[V]**, but I did not read the enacted OBBBA section itself. If the BFR ladder matters to a
  decision, read the statute.
- **The 27-LGM policy documents.** PM-26-024 says they would be posted by April 30, 2026; I
  could not locate 27-LGM Dairy / Cattle / Swine PDFs on RMA's crop-policies index, so §1.3
  and §1.4's policy quotes are from **26-LGM Dairy Cattle**. The RY2027 *handbook*
  (FCIC-20060, April 2026) was available and carries the same §21 D(8) subsidy-eligibility
  wording, so the rule is confirmed for 2027 — but the policy-section numbering is 2026's.
- **Whether concurrent LGM+DRP coverage changes the optimal deductible.** §3.3 flags the
  RY2027 change; modelling the stacked position is not done here. **[R]**
- **LGM-Cattle's forward loss ratio.** The 0.21 is four years of an extreme cattle-margin
  regime on a small book. I would not extrapolate it. **[R]**

---

## 6. Where the code is

| file | what it holds |
|---|---|
| `src/lgm.py` | the engine: RMA Steps 1–7, the subsidy ladder, the deductible curve, the ration and its divergence measure, ADM parsing, DB upserts, CLI |
| `src/db.py` | `lgm_subsidy`, `lgm_margin`, `lgm_deductible_curve` (DDL appended only) |
| `tests/test_lgm.py` | 51 tests; the premium chain is pinned against RMA's published worked example end to end |
| `scripts/analysis/lgm_deductible.py` | reproduces every `[C]` number above |

```
.venv/bin/python -m src.lgm --subsidy --year 2027
.venv/bin/python -m src.lgm --curve --commodity 0803 --type 807 --state 19
.venv/bin/python -m src.lgm --ration --commodity 0847 --corn 0.020 --soybean-meal 0.0035
```
