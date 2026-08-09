# LRP and DRP — Producer Decision Research

**A first-principles build spec, in the style of `src/prfopt.py`'s calibration docstring.**

Author: research pass, 2026-08-07. Scope: legitimate election optimization only.
No tactic here requires misstating production, inventory, ownership, or claims.

---

## 0. How to read this document

Every factual claim is tagged:

- **[V]** — verified against a primary source (RMA handbook, Basic Provisions, or RMA's own
  published data files), URL given.
- **[C]** — computed by me in this session from RMA's published data. The script is described
  well enough to re-run.
- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis to test.

The PRF work succeeded because it reduced the product to an exact payout equation, enumerated
the complete legal election set, and scored every element against a published history. This
document does the same for LRP and DRP. The headline is that **both are more tractable than
PRF, not less** — for LRP because RMA archives every daily rate file back to 2015, and for DRP
because RMA publishes the actual Monte Carlo draws that generate its premiums.

---

## 1. LRP — the equations

### 1.1 Payout and premium

From the **LRP Insurance Standards Handbook FCIC-20010** (May 2024 and the 2026 revision),
¶23.D/E worked examples. **[V]**
<https://www.rma.usda.gov/sites/default/files/handbooks/2025-20010-Livestock-Risk-Protection.pdf>

```
CoveragePrice   = ExpectedEndingValue × CoverageLevel          [rounded to cents]
InsuredValue    = Head × TargetWeight_cwt × CoveragePrice × PAF × Share
GrossPremium    = InsuredValue × LivestockRate
Subsidy         = GrossPremium × SubsidyRate(CoverageLevel)
ProducerPremium = GrossPremium − Subsidy
Indemnity       = Head × TargetWeight_cwt × max(0, CoveragePrice − ActualEndingValue) × PAF × Share
```

The handbook's own numbers: 100 head × 7.5 cwt = 750 cwt; 750 × $75 = $56,250; × PAF 1.00 =
$56,250; × rate 0.013990 = **$787 total premium**; × 0.35 subsidy = $275; **producer pays $512**. **[V]**

I verified two of these identities directly against RMA's daily rate file for 2026-08-05
(99,800 rows, all commodities): **[C]**

- `LivestockRate × CoveragePrice == CostPerCwtAmount` — exact on **100.00%** of fed-cattle and
  swine rows, 99.88% of feeder rows (max residual $0.001, pure rounding dust).
- `ExpectedEndingValue × CoverageLevel == CoveragePrice` — holds to **$0.005**, i.e. the
  coverage price is the product rounded to the nearest cent.

**This matters enormously and is the source of the most serious bug in the current tool
(§7.1): `Cost Per Cwt Amount` is the GROSS premium, not the producer premium.** The handbook
example makes this unambiguous — $787/750 cwt = $1.049/cwt is the *total* premium line, and the
producer's $512/750 = $0.683/cwt is a separate, later step.

### 1.2 The subsidy schedule — a step function

| Coverage level | Subsidy |
|---|---|
| 75% | 55% |
| 80% | 50% |
| 85% **or 87.5%** | 45% |
| 90% **or 92.5%** | 40% |
| 95%, 96%, 97%, 98%, 99%, **100%** | 35% |

**[V]** University of Missouri Extension G459, Table 1
(<https://extension.missouri.edu/publications/g459>), consistent with the RMA handbook's
worked examples (which use 35% at a 95%-region coverage price). Beginning/veteran farmers
receive an additional 10 percentage points. **[V]**

### 1.3 The complete election space

**[V]** Handbook ¶22.B(3), quoted verbatim:

> "Coverage Levels: Authorized coverage levels are 75%, 80%, 85%, 87.5%, 90%, 92.5%, 95%, 96%,
> 97%, 98%, 99% and 100%."

Confirmed against the rate file: exactly **12 distinct coverage levels**, and exactly **10
endorsement lengths** — 13, 17, 21, 26, 30, 34, 39, 43, 47, 52 weeks. **[C]**

Per commodity, per sales date:

```
Feeder cattle : 15 type/weight classes × 10 tenors × 12 coverage levels = 1,800  (1,632 populated)
Fed cattle    :  2 type classes      × 10 tenors × 12 coverage levels =   240
Swine         :  2 type classes      × 10 tenors × 12 coverage levels =   240  (124 populated)
```

**[C]** These are the counts actually present in the 2026-08-05 file — **~2,004 elections per
day** across all three commodities. So the LRP analogue of PRF's 59,536 is trivially small; the
whole daily offer enumerates in milliseconds. The combinatorial difficulty in LRP is not the
election space, it is the *time series* of 2,000-row daily offers, ~250 per year.

**Do not hard-code any axis. [C]** Availability is date-dependent and ragged:

- Only **136 of 150** feeder (type, tenor) pairs are offered on a given day.
- **Tenor availability varies:** 2021-07-01 offered only 8 tenors (no 47, no 52); 2023-06-01 had
  no 13-week. The 12 coverage levels, by contrast, are always all present within an offered
  (type, tenor) pair — the ragged axis is (type, tenor), not coverage.
- **PAF is not a static per-type constant.** Steers Wt1 1.10, Steers Wt2 1.00, Heifers Wt1 1.00,
  Heifers Wt2 0.90, Brahman Wt1 1.00, Brahman Wt2 0.90, Unborn B&H Wt1 1.05, Wt2 0.95 — but
  **Dairy and Unborn Calf PAFs vary by end month** (Dairy Wt1 ranged 1.17–1.37; Unborn Calves
  3.47–4.67 across end months within a single file).
- **PAF multiplies the EEV itself**, so it flows into coverage price, premium *and* indemnity —
  it is not a separate premium adjustment. **[V]**
- **Target weight is a pure elected multiplier**, not a rating input: it scales liability,
  premium and indemnity identically. The rate depends only on (commodity, type, tenor, coverage
  level). **[V]**

**Type classes [C]:** Feeder cattle has **15** — Steers Wt1/Wt2, Heifers Wt1/Wt2, Brahman
Wt1/Wt2, Dairy Wt1/Wt2, Unborn Bulls & Heifers Wt1/Wt2, Unborn Brahman Wt1/Wt2, Unborn Dairy
Wt1/Wt2, Unborn Calves. Fed Cattle: Steers & Heifers, Cull Cows. Swine: Unborn Swine, No Type
Specified.

**Target weight ranges [V]:** Feeder Wt1 1.0–5.99 cwt, Wt2 6.0–10.0 cwt (Wt2 is steers-only for
the steer class); Unborn Calves 0.6–0.99 cwt; Fed steers/heifers 10–16 cwt; cull cows 8–15 cwt.

Other binding constraints, all **[V]** from the handbook:

- **Head limits:** 12,000 head per endorsement, **25,000 head per crop year**, for feeder cattle
  and fed cattle each (¶23.B(1), ¶24.B(1)). Aggregated across all policies in which the insured
  holds a substantial beneficial interest.
- **No double-covering the same animals** (¶22.B): "The insured may not cover the same covered
  livestock under more than one SCE simultaneously." The handbook's own example forbids
  re-covering the same 1,000 head as a different weight class or as fed cattle with a later end
  month while the original endorsement is live. **This is the hard constraint on "laddering" —
  you may ladder across *different* animals or *sequential* periods, not by stacking
  endorsements on one set of animals.**
- **End date must fall within 60 days** of when the livestock are expected to be marketed or
  reach target weight (¶22.B(2)). This is the honest limit on tenor shopping: you cannot simply
  pick the tenor with the best historical net return; it has to match your real marketing date.
- **Ownership/marketing proof:** for swine and fed cattle, sales records dated no later than 60
  days after the end date (2026 revision).

### 1.4 The structural edge — derived, not asserted

Write expected net return per cwt as a function of coverage level `C`:

```
E[net](C) = A(C) − Load·A(C)·(1 − s(C))
          = A(C) · [ 1 − Load·(1 − s(C)) ]
```

where `A(C)` is the actuarially fair expected indemnity per cwt (strictly increasing in `C`),
`Load` is RMA's rate loading, and `s(C)` is the subsidy step function. Dividing by the producer
premium `Load·A(C)·(1−s(C))`:

```
E[net] per producer-premium-dollar = 1 / [ Load·(1 − s(C)) ] − 1
```

**This ratio depends only on `s(C)` and the load — not on `A(C)`, not on tenor, not on the
market.** Since `s` is a step function, the ratio is *constant within each subsidy band* and
jumps at band boundaries — **provided `Load` is constant across coverage levels.** It is not
(§1.5), and that turns out to be the whole story.

Two consequences follow immediately:

**(a) Seven of the twelve coverage levels are weakly dominated.** Within a band, every level
delivers the same expected net per premium dollar, but the higher level delivers strictly more
expected net dollars (because `A(C)` is strictly increasing). So: **[R]**, derived from **[V]**
inputs

| Band | Levels | Dominated by |
|---|---|---|
| 45% subsidy | 85% | **87.5%** |
| 40% subsidy | 90% | **92.5%** |
| 35% subsidy | 95%, 96%, 97%, 98%, 99% | **100%** |

The efficient frontier of LRP coverage levels is only **five points: 75%, 80%, 87.5%, 92.5%,
100%.** A producer at 95% coverage is paying the same subsidy rate as at 100% while insuring
less. Unless they specifically want that strike (a legitimate reason — see the caveat below),
they should move up to the top of their band.

*Caveat, stated honestly:* this is dominance in expected value, not in risk shape. A
budget-constrained producer can buy 95% on more head for the same premium dollars as 100% on
fewer head, and expected net is identical. The real content of the result is narrower but still
useful: **there is no subsidy-efficiency reason to sit below the top of your band, so the choice
among levels within a band should be made on strike placement alone, never on "cheaper premium."**

**(b) Subsidy efficiency at today's rates.** Computed from the real 2026-08-05 file, feeder
cattle type 809, 26-week tenor: **[C]**

| Coverage | Coverage price | Gross prem $/cwt | Subsidy | Producer prem $/cwt | Net per producer-$ (if fairly rated) |
|---|---|---|---|---|---|
| 0.750 | 265.70 | 1.103 | 55% | 0.496 | **1.222** |
| 0.800 | 283.42 | 2.151 | 50% | 1.076 | 1.000 |
| 0.850 | 301.13 | 4.165 | 45% | 2.291 | 0.818 |
| 0.875 | 309.99 | 5.697 | 45% | 3.133 | 0.818 |
| 0.900 | 318.84 | 7.740 | 40% | 4.644 | 0.667 |
| 0.925 | 327.70 | 10.351 | 40% | 6.211 | 0.667 |
| 0.950 | 336.56 | 13.616 | 35% | 8.850 | 0.538 |
| 1.000 | 354.27 | 22.270 | 35% | 14.476 | 0.538 |

### 1.5 The counterweight nobody is modelling: RMA's volatility smile

I backed RMA's own implied volatility out of its published rates by inverting Black-76 at each
strike, using RMA's own Expected Ending Value as the forward. Feeder cattle type 809,
2026-08-05: **[C]**

| Coverage | 13w | 26w | 39w | 52w |
|---|---|---|---|---|
| 0.750 | 27.7 | 24.7 | 24.3 | 24.9 |
| 0.800 | 25.6 | 23.4 | 23.3 | 23.8 |
| 0.875 | 23.1 | 22.2 | 22.3 | 22.5 |
| 0.925 | 22.3 | 21.9 | 22.0 | 22.3 |
| 0.950 | 22.2 | 21.9 | 22.0 | 22.2 |
| 1.000 | 22.7 | 22.3 | 22.3 | 22.5 |

**RMA does not rate LRP at a flat volatility.** There is a pronounced put skew — 24.7% at 75%
coverage versus 21.9% at 92.5%, a 2.8-point spread at 26 weeks, and 5.5 points at 13 weeks.
Deep-out-of-the-money LRP is rated *more expensively per unit of risk* than at-the-money LRP.

This directly opposes the subsidy gradient from §1.4(b): the subsidy is richest exactly where
RMA's rating is most expensive. **The 75%-coverage "most subsidy-efficient" corner is an illusion
created by reading the subsidy schedule in isolation.** The higher implied vol at low strikes is
a higher effective load, and it more than eats the extra 20 points of subsidy.

**The published literature confirms this decisively, and it is the most important corrective in
this document.** Three independent datasets find that net return rises *with* coverage level: **[V]**

- **K-State (Ifft, Johnson & Rowley 2022)**, 2007–2020 at current subsidies: April 26-week loss
  ratio **2.11** at 97.5–100% coverage versus **1.93** at 90–92.49%; net **+$5.05** vs
  **+$1.68/cwt**. Producer-paid loss ratios *rise* with coverage.
  <https://www.agmanager.info/crop-insurance/livestock-insurance-papers-and-information/historic-performance-livestock-risk>
- **Boyer & Griffith**, *Agricultural Finance Review* 83(2) — address the hypothesis directly: a
  35% subsidy on a high coverage level is a larger *absolute* premium reduction than 55% on a low
  one.
- **Haviland & Feuz (2022)**, *Western Economics Forum* 20(2):62–72 — at 34 weeks, low coverage
  goes outright negative (−$1.64/cwt) while high coverage stays positive.

So the naive "buy 75% because the subsidy is 55%" conclusion is **wrong**, and any tool that
ranks cells on subsidy rate alone will mislead. **[C]** My smile measurement is, as far as I can
tell, the mechanism nobody has published: RMA prices the low strikes at 2.8–5.5 more vol points,
which is exactly why the extra subsidy there does not convert into return.

**The genuine LRP edge is therefore relative, not absolute:** buy the coverage level where RMA's
implied vol is cheapest *relative to CME's implied vol at the same strike*, then apply the
subsidy step. Neither term alone answers the question, and the current tool computes neither
correctly (§7.2).

**Quantification of the overall wedge [V]** — Zhang, Keller, Arita & Steinbach (NBER c15388),
strike- and expiry-matched Black-76, Jul 2020–Jun 2025, 8,641 feeder endorsements:

| | Feeder | Live Cattle | Lean Hogs |
|---|---|---|---|
| LRP **gross** premium $/cwt | 8.04 | 6.01 | 6.19 |
| Matched CME put settlement $/cwt | 6.96 | 4.92 | 5.21 |
| Gross gap | **+1.08 (+15.5%)** | +1.09 (+22.2%) | +0.98 (+18.8%) |
| **Producer-paid** gap | **−1.78 (−25.6%)** | −1.05 | −1.24 |

**Before subsidy, LRP is over-priced by ~15–22% versus the matched CME put; after subsidy it is
under-priced by ~26%.** This validates the savings-gap concept the tool is built on — and note
that the over-pricing before subsidy is the same phenomenon as the smile. Critically, that paper
covers only ~6.2% of feeder endorsements, all near 97.5% coverage and ~181 days, and **nobody has
decomposed the gap by tenor or by moneyness.** That decomposition is exactly what T2 proposes and
is genuinely novel work.
<https://www.nber.org/system/files/chapters/c15388/revisions/c15388.rev1.pdf>

### 1.5b Seasonality dominates coverage choice

**[V]** Boyer & Griffith (2023), *JARE* 48(1):31–45, 2.7M offered contracts 2014–2018. Mean net
LRP return by marketing month: **Dec +$1.95/cwt**, Nov +$0.94, Oct +$0.81, Jan +$0.14 …
Jun −$2.53, Jul −$2.84, **Aug −$3.16**.

Haviland & Feuz's 5×5×12 grid agrees: best cell **April, 26-week, level 5 = +$6.16/cwt**; worst
August −$0.84; **over half of the 25 length×level cells have negative average net return.**

**The month of the end date matters more than the coverage level.** No current tool surfaces
this, and it is cheap to add (§5, T8). The honest framing for a producer is not "buy in
December" — the marketing date is set by the cattle — but "your August marketing window is a
structurally expensive one to insure; size accordingly."

### 1.6 Timing

**[V]** from the Basic Provisions `26-LRP-BASIC`, the handbook, and the 2026 product bulletin:

- **The sales period "begins when the coverage price and rates are posted and ends at 8:25 AM
  Central Time the following calendar day."** Basic Provisions §1. **The widely-repeated 9:00 AM
  figure — including in `lrp_signal.py`'s own docstring — is wrong by 35 minutes.**
- Prices must be published **by 4:30 PM CT** or there is no sale that day (§2(e)(4)). The
  familiar "~3:30 PM" is the typical posting time, not the rule.
- The effective date is the date rates were *published*, even when the producer buys the next
  morning.
- The insured may **revise or withdraw an SCE up to 1:30 PM Central** on the effective date
  (¶22.B(5)(b)) — a detail the current tool's docstring does not mention and which materially
  extends the decision window.
- An SCE may be **signed up to 14 calendar days before** the sales period, with substantive
  fields completed, then submitted when rates post (¶22.B(5)(d)). This lets a producer
  pre-stage paperwork and act instantly on a favorable posting.
- **Suspensions [V]** (¶23.B):
  - Any **limit move** in a relevant CME Feeder Cattle future. As of June 2023 the daily limit
    is **$8.25/cwt**, expanded **$12.25/cwt**.
  - **All feeder cattle and fed cattle sales are suspended on Cattle on Feed release days.**
  - **All swine sales are suspended on Hogs and Pigs release days.**
- **2026 change [V]:** premium billing date moves to "the first day of the second month after
  the end date." Premium is due *after* the coverage ends — a large, free cash-flow benefit that
  should be shown explicitly in any premium display.
  <https://www.rma.usda.gov/policy-procedure/bulletins-memos/product-management-bulletin/pm-25-028-livestock-risk-protection>
- **2026 additions [V]:** new coverage types (Feeder Cattle with Unborn Calves; Fed Cattle with
  Cull Cows, 13-week limit), coverage permitted through forward contracts with documentation,
  and a drought exemption keyed to the Drought Monitor Severity and Coverage Index.

### 1.7 Basis — what LRP does not cover

The Actual Ending Value is a national index, not the producer's cash price. LRP therefore leaves
three uncovered exposures, none of which the current tool displays: **[R]**

1. **Regional cash basis** vs the CME Feeder Cattle Index (a 700–899 lb steer index).
2. **Weight/class basis** — the PAF corrects the *expected* value for weight class, but the
   *realized* spread between, say, 5-weight calves and the index is not fixed and moves with
   feed costs.
3. **Timing basis** — the endorsement settles on one date; the producer sells over a window.

A producer can be fully indemnified and still lose money, or sell well and collect nothing.

### 1.8 Stacking

- **[V]** Basic Provisions §4(g): no other FCIC-reinsured livestock policy on the **same class
  with the same end month**, and none insuring the same animals at the same time. Intentional
  duplication → sanctions; unintentional → the first coverage stands and the duplicate is voided.
  **Concurrent coverage between similar programs becomes permitted for 2027** under PM-26-024.
- **LRP + CME hedge is now heavily constrained** — see §3.
- **LRP + PRF/LFP** are orthogonal (price vs forage) and stack cleanly. **[R]**
- LRP pays on the index regardless of what the producer actually receives; there is no
  requirement to have sold at a loss to collect. Ownership and marketing documentation *is*
  required. **[V]**

---

## 2. DRP — the equations

### 2.1 Payout and premium

From the **26-DRP Basic Provisions** §1, §5, §7. **[V]**
<https://www.rma.usda.gov/sites/default/files/2025-04/DRP%20Basic%20Provisions%2026-DRP%20BP.pdf>

**Class pricing (Type 831):**

```
ExpectedRevenue  = (E(PIII)·W + E(PIV)·(1−W)) × Q_declared / 100
ExpectedGuarantee= ExpectedRevenue × CoverageLevel
Liability        = ExpectedGuarantee × Share × ProtectionFactor
FinalGuarantee   = (E(PIII)·W + E(PIV)·(1−W)) × Q_covered / 100 × CoverageLevel
ActualRevenue    = (PIII·W + PIV·(1−W)) × Q_covered × Y / 100
Indemnity        = max(0, FinalGuarantee − ActualRevenue) × Share × ProtectionFactor
```

**Component pricing (Type 832):**

```
ExpectedRevenue = [ (E(PB)·QB + E(PP)·QP + E(POS)·5.8)·W
                  + (E(PB)·QB + E(PN)·(QP + 5.8))·(1−W) ] × Q_declared / 100
```
with the actual-revenue analogue using realized prices, `Q_covered`, and `Y`.

**Premium:** `GrossPremium = Liability × Rate`; `Subsidy = GrossPremium × SubsidyRate(CoverageLevel)`.
RMA's own worked example: `$182,875 × 0.024 = $4,389`; `× 0.44 = $1,931` subsidy; producer pays
**$2,458**. **[V]**

**Yield adjustment:** `Y = actual milk per cow ÷ expected milk per cow` for the pooled production
region; set to 1 if NASS does not publish (§7(g)). **[V]** This is a *state-level* factor the
producer does not control and cannot hedge — an under-appreciated basis term (§2.6).

**Linearity.** Both `FinalGuarantee` and `ActualRevenue` are linear in `Q`, and the indemnity is
multiplied by `Share × ProtectionFactor`. Therefore **the rate per dollar of liability is
invariant to protection factor, declared production, and share**, and premium is exactly linear
in all three. **[V]** structurally from the definitions plus the worked example. This is the
single most important computational fact about DRP: three of the knobs factor out and never need
enumeration.

### 2.2 Subsidy schedule

| Coverage level | 80% | 85% | 90% | 95% |
|---|---|---|---|---|
| Subsidy | **55%** | **49%** | **44%** | **44%** |

**[V]** RMA DRP Fact Sheet.
<https://www.rma.usda.gov/sites/default/files/2024-02/Dairy-Revenue-Protection-Fact-Sheet.pdf>
There are no 70% or 75% levels — §3(c)(4) fixes the range at 80–95 in 5-point steps. Protection
factor does **not** affect the subsidy *rate*. Beginning/veteran farmers get +10 percentage
points. **[V]**

### 2.3 The complete election space

**[V]** 26-DRP §3(c), quoted:

| Knob | Legal values | Count |
|---|---|---|
| Pricing option | Class (831) / Component (832) | 2 |
| Coverage level | 80–95%, 5-point steps | **4** |
| Protection factor | 1.00–1.50, 0.05 steps | **11** |
| Class weighting `W` | 0–100%, 5-point steps | **21** |
| Component weighting `W` | 0–100%, 5-point steps | **21** |
| Butterfat test `QB` | **4.00–6.00 lb**, 0.05 steps | **41** |
| Protein test `QP` | **3.20–4.50 lb**, 0.05 steps | **27** |
| Other solids | fixed **5.8** | 1 |

The weighting is a **single dial** — the complement is forced. There is no independent
Class III / Class IV pair to constrain to 100%.

```
Class pricing     :  4 × 11 × 21              =        924
Component pricing :  4 × 11 × 21 × 41 × 27    =  1,022,868
                                       TOTAL  =  1,023,792  per quarter
× 5 open quarters                             =  5,118,960
```

**But protection factor factors out linearly (§2.1), so it never needs enumeration** — under a
linear objective its optimum is always a corner (1.00 or 1.50). Dividing out the 11:

```
Distinct RATE cells per quarter:
  Class     :  4 × 21              =      84
  Component :  4 × 21 × 41 × 27    =  92,988
                            TOTAL  =  93,072   per quarter
× 5 quarters                       = 465,360
```

**93,072 rate cells per quarter is the DRP analogue of PRF's 59,536.** Same order of magnitude,
so the same exhaustive-enumeration architecture applies directly.

**Two corrections to widely-repeated claims:**

- **Only five quarters are open at once**, not eight (four during June 16–30). **[V]** 2026 DRP
  Handbook ¶23.D. Independently confirmed by the draw file: 250 state-quarter keys = 50 states ×
  5 quarters. **[C]**
- **The 2026 crop year changed the component test limits**: butterfat min 3.25→**4.00**, max
  5.50→**6.00**; protein min 2.75→**3.20**; other solids 5.7→**5.8**. **[V]** Building against
  the 2025 numbers gives wrong guarantees. For CY2025 the component block is
  `4 × 21 × 46 × 36 = 139,104`.

**A constraint the optimizer must respect:** on illiquid distant quarters RMA *restricts* the
weighting to a single legal value, published daily in the `Class Price Weighting Factor
Restricted Value` / `Component Price Weighting Factor Restricted Value` columns. When present,
the 21-way dimension collapses to 1. **[V]** §3(c)(1)(i)(B), (ii)(D); fields confirmed populated
in the live file. **[C]**

### 2.4 The structural edge — derived and computed

Same algebra as §1.4. Using RMA's **actual published** expected prices, per-month sigmas, and
loading factor from `2027_A00833_ADMDrpDailyPrice_Daily_20260805` (Class III $17.31/17.47/17.51
with sigma 0.1115/0.1258/0.1387; Class IV $17.91/17.90/17.85 with sigma 0.1067/0.1254/0.1415;
**Loading Factor 1.0638**), I simulated the quarter-average revenue index and computed `A(C)`: **[C]**

Per $1 of expected revenue, PF = 1.00, 100% Class III weighting:

| Coverage | `A(C)` (fair rate) | Gross rate | Subsidy | Producer prem | **E[net]** | **Net per producer-$** |
|---|---|---|---|---|---|---|
| 0.80 | 0.00002 | 0.00002 | 55% | 0.00001 | 0.00001 | **1.089** |
| 0.85 | 0.00029 | 0.00031 | 49% | 0.00016 | 0.00013 | 0.843 |
| 0.90 | 0.00227 | 0.00241 | 44% | 0.00135 | 0.00092 | 0.679 |
| 0.95 | 0.01003 | 0.01067 | 44% | 0.00597 | **0.00405** | 0.679 |

**The single biggest structural edge in DRP: 90% coverage is dominated by 95% coverage.** They
share the identical 44% subsidy rate, so net-per-premium-dollar is identical (0.679), but 95%
delivers **4.4× the expected net dollars**. Moving 90→95 buys more coverage at *zero
subsidy-rate penalty* — the only free step on the DRP ladder. **[C]**, derived from **[V]** inputs.

Note also what the table shows about the "most efficient corner" framing: 80% coverage has the
best ratio (1.089) but an expected indemnity of essentially **zero** at current volatilities.
Optimizing the efficiency ratio alone would recommend an election that almost never pays. The
correct objective is **maximize expected net dollars subject to a premium budget**, which points
to high coverage and high protection factor, not to the 80% corner. **[R]**

**Class weighting is not a free diversification lunch.** Blending 50/50 Class III/IV *lowers*
`A(C)` from 0.01003 to 0.00775 — averaging two imperfectly correlated prices cuts variance,
which cuts the option value. **[C]** So a producer whose milk check is genuinely Class III
should not dilute toward Class IV: it reduces both premium and protection *and* introduces
basis risk against their actual check. The weighting dial should track the producer's true
class exposure, not be used as a risk-reduction device.

### 2.5 Two legal over-declaration allowances

Both are explicit in the Basic Provisions and both are legitimate — they are tolerance bands
RMA wrote in, not misreporting. **[V]**

- **Production, ~17.6%.** §7(d)(1): if marketings are at or above **85%** of declared covered
  production, covered production **equals declared**. So declaring up to `expected ÷ 0.85 =
  1.176×` expected marketings retains full coverage.
- **Component tests, ~11.1%.** §7(e)(2): if the actual test is at least **90%** of declared, the
  final test **equals declared**. So declaring up to `actual ÷ 0.90 = 1.111×` retains full value.

**Both are cliffs, not slopes, and the premium is never refunded.** §7(d)(v): "your premium will
not be reduced as a result of any recalculations"; §7(e)(3) says the same for tests. Overshoot
and the *guarantee* is rescaled down while you keep paying the full premium. **[V]**

The correct tool behaviour is therefore **not** "declare the maximum." It is: size the
declaration against the *downside* of the production/test forecast so that the realized value
lands just inside the cliff with high probability. A tool that shows the cliff and the
probability of breaching it is worth more than one that shows the optimum. **[R]**

### 2.6 Basis — what DRP does not cover

DRP settles on announced FMMO class/component prices and a **state-level** yield factor. The
residual an individual producer carries: **[R]**

1. **Class mix basis** — the declared weighting `W` versus the producer's actual utilization.
2. **Component basis** — declared tests versus the actual herd tests (bounded by the ±10%
   allowance above, but only bounded on one side).
3. **PPD / location basis** — the producer's mailbox price versus the announced class price,
   including the producer price differential, hauling, and quality premiums. This is the largest
   and least modelled term.
4. **Yield factor `Y`** — a state aggregate applied to an individual's revenue. A producer whose
   own production diverges from the state trend is exposed to a factor they do not control and
   cannot hedge.

### 2.7 Timing and stacking

- **Sales period [V]:** prices/rates post by **4:30 PM CT**; the window ends **9:00 AM Central on
  the earlier of Sunday or the following business day** (2026 Handbook ¶23.B). The Sunday clause
  creates a long Friday-evening-through-weekend window. Late QCEs signed during the window are
  accepted to **10:30 AM CT**, or **noon CT** with a documented reason.
- **Suspensions [V]** (§3(g)–(k)): days USDA releases **Milk Production, Cold Storage, or Dairy
  Products**; any **limit move** in a milk future expiring in the insured period; any day prices
  are not published by 4:30. "Business day" follows the CME dairy calendar, not the federal one.
- **DRP + LGM-Dairy is PROHIBITED. [V]** §17(a): "you must not obtain insurance under any other
  livestock plan of insurance … on milk to be marketed during any month of any quarterly
  insurance period for which you have coverage under this policy." If both exist, the **earliest
  endorsement controls** and the other is void (§17(b)). One DRP policy per state per crop year;
  unlimited QCEs within it. *The common claim that this was relaxed is wrong for CY2025/2026.*
- **DRP + DMC** is not addressed in the DRP provisions — DMC is an FSA program, not an FCIC
  livestock plan, so §17(a) does not reach it. Widely treated as complementary. **[R]** —
  inferred from the absence of a prohibition; I did not find affirmative confirmation.
- **2026 change [V]:** DRP premium billing moves to "the first day of the **third** month after
  the end date."

---

## 3. Hard compliance boundary: the 2026 subsidy-capture rules

26-DRP added **§3(l)** and a new **§24 Subsidy Capture**; LRP added a parallel **§25**. **[V]**
Both *presume* a violation — **no intent required**.

**LRP §25** presumes capture when a producer buys an SCE and opens a short put such that all
three hold:

1. the put expires within **4 calendar days** of the SCE end date;
2. it was sold between **2 trading days before and 5 trading days after** the SCE effective date;
3. the put premium per cwt exceeded **80% of the SCE premium**.

A parallel test covers short call + long futures (a synthetic short put). **§12(g) authorizes
USDA access to brokerage records.**

**DRP §24** uses the same 2-before/5-after window and 80% threshold on the relevant dairy
contract; §24(b) extends to private off-exchange contracts exchanging indemnities for a fixed
sum, and §18(e) authorizes brokerage-record access. Consequences are administrative, civil, *or
criminal*.

Worth noting for calibration: the NBER study (§1.5) simulated exactly this LRP + short-put trade
and found it nets only **−$0.18 to +$0.09/cwt with −$29.82/cwt worst-5% tails**. The wedge is
real but does not reliably convert to profit — so the rule forecloses a strategy that was, in
practice, a bad one anyway. **[V]**

**This must be a hard constraint in any optimizer, not a scoring penalty.** Any recommendation
that pairs an endorsement with an offsetting short-volatility position is out of bounds. Note
that this does *not* prohibit ordinary directional hedging (buying puts, selling futures against
physical inventory) — it targets selling back the volatility you just bought subsidized.

---

## 4. Where the history lives

### 4.1 LRP — daily rate files, 2015 to present **[C][V]**

```
https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{RY}/
    {RY}_ADMLivestockLrp_Daily_{YYYYMMDD}.zip
      -> {RY}_A00630_LrpRate_Daily_{YYYYMMDD}.txt   (pipe-delimited, header row)
```

`{RY}` is the **reinsurance year, which rolls 1 July** — the existing code already handles this.
Directory index pages are served at `.../adm_livestock/{RY}/index.html`, so the archive is
enumerable rather than guessable.

**Depth: ~530–585 files per year, RY2016 (2015-07-01) through today — roughly 5,800 daily rate
files.** **[C]** I downloaded 238 of them spanning 2015-07-01 to 2025-05-29 and parsed 132,345
feeder-cattle rows without incident.

35 columns; the ones that matter: `Commodity Code`, `Type Code`, `Endorsement Length Count`,
`Coverage Price`, `Expected Ending Value Amount`, `Livestock Coverage Level Percent`,
`Livestock Rate`, `Cost Per Cwt Amount`, `Price Adjustment Factor`, `End Date`,
`Sales Effective Date`.

**Two vintage discontinuities you must handle: [C]**

1. **`Price Adjustment Factor` is empty in older files.** In 2015 the type-specific adjustment
   was baked into `Expected Ending Value Amount` (type 809 EEV = 238.239 while type 816 =
   173.265 on the same day). It is now broken out as a separate multiplier (0.73–4.64 for
   feeder cattle). Treat blank as 1.0 and use the EEV as published.
2. **The clean 12-level coverage grid only appears in 2024–25.** Before that RMA published a
   menu of coverage *prices* and the `Livestock Coverage Level Percent` column was the
   *realized ratio* — continuous, with 215–1,145 distinct values per year. Distinct values by
   year: 2015: 215, 2019: 989, 2021: 1,145, 2024: 642, **2025: exactly 12**. Critically, the
   **minimum coverage level actually offered** was 0.866 in 2015, 0.881 in 2022, 0.893 in 2023 —
   the 75–80% high-subsidy corner **did not exist for most of the historical record** and first
   appears in 2024. Any backtest that reports returns for "80% coverage" over 2015–2023 is
   scoring an election that could not be purchased.

### 4.2 LRP — actual ending values (this problem is solved)

**<https://public.rma.usda.gov/livestockreports/LRPReport>** — "LRP Coverage Prices, Rates, and
Actual Ending Values." An ASP.NET Core wizard, POST-driven, requiring a cookie plus a
`__RequestVerificationToken`. Four steps: `EffectiveDate` → `StateSelection` →
`CommoditySelection` → `TypeSelection`, then `buttonType=Create Report`; leaving `TypeSelection`
unselected returns all types. `ReportType=HTML|PDF`. **Driven end-to-end successfully; scraping
is straightforward.** **[C]**

**The decisive fact: historical rows carry the realized `Actual End Value` already populated**
(confirmed 880/880 rows on 2021-07-01, 1188/1188 on 2025-06-02). **RMA hands you both sides of
the payoff — no external index series is needed at all.** **[C]**

16 columns: State, County, Endorsement Length, Commodity, Type, Practice, Price Adj. Fctr.,
Crop Year, Exp. End Value, Coverage Price, Coverage Level, Rate, Cost Per CWT, **Producer
Premium Per CWT**, End Date, **Actual End Value**.

Note that this report publishes `Cost Per CWT` and `Producer Premium Per CWT` as *separate
columns* — independent confirmation of the §7.1 bug.

**Depth: 1,273 effective dates, 2021-07-01 → present** (CY2022–CY2027). **[C]** Shorter than the
ADM rate archive (2015+, §4.1) but self-contained. Recommended split: use **LRPReport for
2021→present** where AEVs come free; fall back to the ADM archive plus a scraped index only if
2015–2021 is genuinely needed.

**Two schema traps [C]:** CY2022–CY2026 files have **15** columns (no PAF), CY2027 has **16** —
parse by header name, never by position. And the 2024-07-01 coverage-grid regime change (§4.1)
applies here too.

**Do not substitute front-month futures.** I tested `GF=F` as a proxy and measured the bias,
which is why the above matters: **[C]**

```
mean Expected Ending Value at sale  : $203.29
mean proxy AEV at end date          : $192.07
mean (AEV − EEV)                    : −$11.22        <- should be ~0 if unbiased
median (AEV − EEV)                  : −$14.74
share of endorsements with AEV<EEV  : 78.4%
```

A −$11/cwt systematic bias produces an implied gross loss ratio of **2.66** on a program RMA
rates to ~1.0. I ran the full backtest with this proxy and am **deliberately not reporting the
resulting net-return tables**, because they are dominated by the proxy error rather than by the
program's economics. **Use the `Actual End Value` column from LRPReport. Never a futures series.**

For reference, the exact settlement definitions **[V]**, which differ by commodity and are easy
to get wrong:

- **Feeder cattle:** the CME Feeder Cattle Reported Index (itself a 7-day weighted average) on
  the end date, **× PAF**. A single day, not a window — the averaging is inside the index. If
  the end date is not a report day, use the prior report day.
- **Fed cattle, steers & heifers: not CME at all** — it is the AMS *5 Area Weekly Weighted
  Average Direct Slaughter Cattle*, Live Basis, Steers, Over 80% Choice, for the week containing
  the end date. <https://mymarketnews.ams.usda.gov/viewReport/2477>
- **Fed cattle, cull cows:** CME Feeder Cattle Index × PAF.

**A gap I could not close [V-negative]:** there is **no published LRP Commodity Exchange Price
Provisions document giving the EEV derivation.** Both Specific Coverage Endorsements define
Expected Ending Value only as "the market price expected at the end period, **and found in the
actuarial documents**." RMA does not publish the futures→EEV mapping. **Treat EEV as an observed
daily input, not a reproducible computation** — any tool that tries to predict tomorrow's EEV
from today's futures is extrapolating an unpublished formula.

### 4.3 DRP — the complete rating engine **[C][V]**

Same tree, five datasets. This is the find that makes DRP tractable:

| Record | Filename pattern | Cadence | Contents |
|---|---|---|---|
| **A00833** | `{RY}_A00833_ADMDrpDailyPrice_Daily_{date}.zip` | every sales day | **Loading Factor**; monthly + quarterly expected Class III/IV; monthly expected butter/cheese/dry whey/NFDM; **monthly sigmas (implied vols) for all six**; expected butterfat/protein/other-solids/nonfat-solids; **weighting restrictions** |
| **A00831** | `..._ADMDrpDraw_Quarterly_...` | ~5/yr | **5,000 Monte Carlo draws per state-quarter** as uniform [0,1] quantiles, jointly indexed across all six commodities *and* the yield draw. 1,250,000 rows (50 states × 5 quarters × 5,000), ~65 MB zipped / 226 MB raw |
| **A00832** | `..._ADMDrpMilkYield_Quarterly_...` | ~8/yr | Expected Yield, Actual Yield, **Expected Yield SD**, by state |
| **A00834** | `..._ADMDrpActualPrice_Quarterly_...` | 4–9/yr | **Settlement values** — actual Class III/IV, butterfat, protein, other solids, nonfat solids |
| **A00835** | `..._ADMDrpFmmoPricingFactor_Yearly_...` | 1/yr | Make allowances, manufacturing yields |

**Depth: 2018-10-09 (DRP's first sales day) to present, ~135–220 daily files per crop year,
~1,650 total.** Settlement files cover every quarter since inception — about **31 completed
quarters**. That is the scoring history, and it is *much* shorter than PRF's 19 years of annual
observations. Treat DRP backtest win rates with corresponding humility.

**There is no public DRP premium calculator and no published rate table** — with ~93,000 rate
cells per quarter per state per day, tabulation is infeasible. The Livestock Reports portal
serves **only LRP and LGM**. **[C]** RMA publishes the draws *instead of* a rate table, and the
intended architecture is:

1. Read expected prices and monthly sigmas from **A00833** for the sales date.
2. Read the 5,000 uniform draws for the state-quarter from **A00831**.
3. Transform `u → P = E(P)·exp(σ·Φ⁻¹(u) − σ²/2)`. **[R]** — this is the standard construction
   and is consistent with sigmas being the only dispersion parameter published, but the exact
   transform is **not stated** in the CEE. **Validate against a real agent quote before trusting
   the engine.**
4. Transform the yield draw using **A00832** expected yield and SD.
5. Compute the indemnity per draw; average → expected loss.
6. `Rate = (expected loss / liability) × LoadingFactor`.

Because the draw index ties all six commodities *and* the yield together row by row, **the entire
correlation structure comes for free** — no correlation matrix to estimate. This is a
substantially better position than the PRF work started from.

**Loading factor is not constant** — I observed 1.0638, 1.0855, and 1.1081 on different offers
in the same file. Read it per row. **[C]**

**FMMO make allowances changed materially in June 2025** (butter 0.1715→0.2272, cheese
0.2003→0.2519, NFDM 0.1678→0.2393, dry whey 0.1991→0.2668). Always read A00835 keyed to the
sales date's `Adm Drp Fmmo Pricing Factor ID`; never hardcode from a CEE PDF. **[C]**

---

## 5. Tool recommendations

Ordered by decision value. "Cheap" means days, "expensive" means weeks.

### T1. Fix the LRP premium and subsidy layer — **CHEAP, blocking everything else**

Correct the three defects in §7. Until `Cost Per Cwt Amount` is treated as gross, the subsidy
schedule is aligned to RMA's real bands, and the coverage-level list matches the 12 authorized
values, **every number the LRP tab displays is wrong**, and the immutable gap history is
accumulating wrong values daily.

Display, per cell: coverage price, **gross** premium/cwt, subsidy $/cwt, **producer**
premium/cwt, and the premium *due date* (first of the second month after end date — it is now
deferred, and that is worth showing).

### T2. LRP relative-value surface: RMA vol vs CME vol, **per strike** — CHEAP-to-MEDIUM

The current tool prices the CME comparison put at a single flat `base_vol` (default 14%) across
all 12 strikes while RMA's own rating carries a 2.8–5.5 point skew (§1.5). Replace with a
strike-matched comparison:

```
rma_iv(C, tenor)  = implied vol backing out RMA's published rate at strike = coverage price
cme_iv(C, tenor)  = CME implied vol at the SAME strike, from real option settlements
vol_edge(C,tenor) = cme_iv − rma_iv        [vol points; >0 means RMA is cheap]
```

Display as a **12 × 10 heatmap** (coverage level × tenor) of `vol_edge`, with a second panel
showing the subsidy step. The buy decision is where `vol_edge` and the subsidy step both favour
the same cell. **This is the highest-value analytical addition available**, because it is the
only thing that resolves the §1.5 tension between the subsidy gradient and the rating skew.

Requires fetching real CME feeder cattle option settlements — the one genuine new data
dependency. Everything else in this document uses data the repo can already reach.

### T3. LRP dominance filter — **VERY CHEAP, high explanatory value**

Grey out or annotate the seven weakly-dominated coverage levels (85, 90, 95, 96, 97, 98, 99) with
the reason: "same 35% subsidy as 100% — no efficiency gain from insuring less." One derived
column, no new data. This single change reframes how a producer reads the grid.

### T4. DRP exhaustive optimizer — **EXPENSIVE, but this is the PRF analogue the user asked for**

Enumerate the 93,072 rate cells per quarter (§2.3), price each exactly via the A00831 draws
(§4.3), and rank by expected net and by net-per-premium-dollar. Because premium is linear in
protection factor, share, and declared production, **compute the rate surface once and scale**
— the 5.1 million-candidate figure never needs to be materialised.

Score against the ~31 completed quarters from A00834. Output the PRF-style ranked table plus a
`coverage level × protection factor` grid. Reuse `prfsweep.py`'s structure directly.

Start with the **class-pricing block only — 84 cells per quarter.** It is 0.1% of the work,
covers most producers, and validates the whole engine before committing to the 92,988-cell
component block.

### T5. DRP declaration-cliff calculator — **CHEAP, and the highest per-producer dollar value**

Given a production forecast and its uncertainty, show:

- the 85% production cliff and the 90% test cliff in the producer's own units,
- the declaration that maximises coverage subject to `P(breach) ≤ x%`,
- the dollar cost of breaching (guarantee rescaled, premium **not** refunded).

Small model, large money, and it is the part of DRP most producers get wrong in the
conservative direction — under-declaring gives away coverage they have already been approved for.

### T6. LRP historical backtest — **CHEAP-to-MEDIUM (upgraded: the AEV problem is solved)**

Scrape LRPReport (§4.2) for its 1,273 effective dates. **Every historical row already carries
both the producer premium and the realized Actual End Value**, so the net return is a subtraction
— no pricing model, no external index, no proxy error. Score every (type, tenor, coverage level,
end month) cell for win rate, mean net $/cwt, and producer loss ratio. This is the direct PRF
analogue and it is now much cheaper than I first assessed.

**Present with three caveats** or it will mislead: (a) the 75–80% coverage corner did not exist
before 2024 — those cells have no meaningful history; (b) the sample is a large cattle bull
market, so any "short tenors win" result is a directional artefact; (c) bin coverage levels
across the 2024-07-01 regime change (§4.1) or key off coverage price.

### T8. Seasonality panel — **CHEAP, and it outranks most of the grid**

Mean net return by **end month** is a larger effect than coverage level (§1.5b): Dec +$1.95/cwt
to Aug −$3.16/cwt in Boyer & Griffith; over half of Haviland & Feuz's 25 length×level cells are
negative on average. Fall this straight out of T6 and display it as a 12-month bar with the
producer's own marketing window highlighted.

Frame it honestly: the marketing date is set by the cattle, not by the insurance. The decision
this informs is *how much* to insure in a structurally expensive window, not *when* to market.

### T7. Basis panel for both products — MEDIUM

Show the residual the product does not cover (§1.7, §2.6). For LRP, the producer's regional cash
basis to the index. For DRP, the mailbox-minus-announced-class gap and the state yield factor.
A tool that shows "you are 87% hedged, here is the other 13%" is more honest and more useful than
one that implies the index is the price.

---

## 6. Top 5 features, ranked

| # | Feature | Rationale | Build cost |
|---|---|---|---|
| 1 | **Fix LRP premium/subsidy/coverage-level/cutoff layer (T1)** | Every displayed number is currently wrong, and the immutable gap history is accruing wrong values daily. Nothing else can be trusted until this lands. | **Cheap** — hours |
| 2 | **LRP historical backtest + seasonality panel (T6 + T8)** | Upgraded to near-top: RMA publishes premium *and* realized ending value in the same row, so this is a subtraction, not a model. End-month effect is larger than coverage level and nothing surfaces it today. | **Cheap–medium** — scraper is the only work |
| 3 | **Strike-matched RMA-vs-CME vol surface (T2)** | The only analysis that turns the savings gap into a per-cell decision. Also genuinely novel — the published work covers one strike and one tenor. | Medium; needs CME option settlements |
| 4 | **DRP declaration-cliff calculator (T5)** | Largest per-producer dollar impact here; the 17.6% and 11.1% allowances are legal, explicit, and routinely left unused. | Cheap |
| 5 | **DRP class-pricing optimizer, 84 cells/quarter (T4 phase 1)** | Delivers the PRF-style exhaustive ranking for DRP at 0.1% of the full build, and validates the draw-based pricing engine before the 92,988-cell component block. | Medium |

*(T3, the dominance filter, is nearly free and should ride along with T1.)*

**Biggest structural edge, LRP:** the subsidy is a **step function** while expected indemnity is
continuous in coverage, so within each band the lower levels are weakly dominated — the efficient
frontier is five points, 75%/80%/87.5%/92.5%/100%, not twelve.

But the more valuable finding is a **negative** one that overturns the brief's premise: the
"subsidy is richest at low coverage, so low coverage is most efficient" reasoning is **wrong**,
and three independent published backtests show net return rising *with* coverage. **[C]** My
measurement of RMA's volatility smile (24.7% implied at 75% coverage vs 21.9% at 92.5%) appears
to be the unpublished mechanism: RMA charges a higher effective load exactly where the subsidy is
richest, and it more than offsets the extra 20 subsidy points. **The real edge is relative —
RMA's implied vol versus CME's implied vol at the same strike, per day — and no published work
has decomposed it by tenor or moneyness.**

**Biggest structural edge, DRP:** **90% coverage is dominated by 95%.** They carry the identical
44% subsidy rate, so expected net per premium dollar is identical (0.679), but 95% delivers
**4.4× the expected net dollars**. It is the only free step on the ladder, and it is derivable
from the subsidy schedule alone.

---

## 7. What the current LRP tool gets wrong

These are ordered by severity. Items 7.1–7.3 change displayed dollar values; 7.4–7.6 change
which cell looks best.

### 7.1 `Cost Per Cwt Amount` is the GROSS premium, but the tool treats it as the producer premium

`lrp_signal.py::_parse_rate_file` assigns:

```python
"producer_prem": cost_cwt,                # cost_per_cwt_amount
"actuarial_prem": rate * cov_price,
```

I verified that `Livestock Rate × Coverage Price == Cost Per Cwt Amount` **exactly** (100% of fed
cattle and swine rows). **So these two fields are the same number, and both are the gross
premium.** The handbook's worked example is unambiguous: $787 total premium / 750 cwt = $1.049 is
the *total* line; the producer's cost is $512/750 = $0.683.

Then `build_grid` compounds it:

```python
act_prem = prod_prem / (1 - subsidy_rate)
```

taking an already-gross number and dividing by `(1 − s)` again, inflating it by a further
1.54–2.22×. Net effect at 26 weeks / 100% coverage on 2026-08-05: the tool shows the producer
paying **$22.27/cwt** when the true producer premium is **$14.48/cwt**. **[C]**

Because the headline metric is `gap = cme_px − prod_prem`, overstating `prod_prem` by the entire
subsidy **systematically understates the savings gap** — the tool under-triggers its own BUY
signal. And the `subsidy_gap = act_prem − prod_prem` decomposition is a fabricated quantity
rather than the real subsidy.

### 7.2 `base_vol` defaults to 14% against a market and a rating that are both ~22%

`--vol` defaults to 14 (`lrp_signal.py:1237`), and `base_vol` is used directly as the CME
comparison vol. RMA's own implied vol, backed out of its published rates, is **21.8–27.7%**
(§1.5). Pricing the comparison put 8 volatility points too low makes it far too cheap and
shrinks the measured gap. There is no fetch of real CME option settlements anywhere in the
module — the "CME equivalent put" is priced off a hardcoded constant.

### 7.3 The subsidy schedule is misaligned by one tier, and catastrophically wrong at 75%

```python
SUBSIDY_SCHEDULE = {1.00: 0.35, 0.95: 0.40, 0.90: 0.45, 0.85: 0.50, 0.80: 0.55}
# get_subsidy_rate: for t in sorted(desc): if cov >= t: return SUBSIDY_SCHEDULE[t]
```

versus RMA's actual bands (§1.2):

| Coverage | RMA | Repo | Error |
|---|---|---|---|
| 0.75 | **55%** | 35% (falls through to the default) | **−20 pts** |
| 0.80 | 50% | 55% | +5 pts |
| 0.85 / 0.875 | 45% | 50% | +5 pts |
| 0.90 / 0.925 | 40% | 45% | +5 pts |
| 0.95–0.99 | 35% | 40% | +5 pts |
| 1.00 | 35% | 35% | ✓ |

Every level except 100% is wrong. The 0.75 case is worst: `get_subsidy_rate` finds no matching
tier and returns the `0.35` default, so **the single most subsidy-efficient election in the
program is shown with the *lowest* subsidy in the program.**

The correct schedule is **double-verified**: MU Extension G459 Table 1 **[V]**, and independently
recovered empirically as `ProducerPremiumPerCwt / CostPerCwt` across all 2,004 rows of a live
LRPReport pull — measured means 0.3500, 0.4000, 0.4499, 0.4999, 0.5497, identical across all
three commodities. **[C]**

### 7.4 `COVERAGE_LEVELS` includes a level that does not exist and omits six that do

```python
COVERAGE_LEVELS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
```

RMA's authorized set (**[V]**, handbook ¶22.B(3), confirmed in the rate file) is
`[0.75, 0.80, 0.85, 0.875, 0.90, 0.925, 0.95, 0.96, 0.97, 0.98, 0.99, 1.00]`.

- **0.70 is not purchasable.** It matches nothing in the rate file, so the code falls into the
  `else` branch and displays a *fabricated* premium built from an invented
  `load = 1.09 + 0.03*(1-cov)`. A producer could act on a row for a product that does not exist.
- **0.875, 0.925, 0.96, 0.97, 0.98, 0.99 are missing** — and 0.875 and 0.925 are exactly the
  band-top levels that dominate 0.85 and 0.90 (§1.4). The tool cannot see the efficient frontier
  because half of it is not in the list.

`TENORS_WEEKS = [13,17,21,26,30,34,39,43,47,52]` is **correct**. **[C]**

### 7.5 Coverage matching is a ±0.025 window over a grid with 0.01 spacing

```python
lrp_df["coverage_level"].between(cov - 0.025, cov + 0.025)
```

then `.iloc[0]`. At the top of the grid the real levels are 1 point apart (0.95, 0.96, 0.97,
0.98, 0.99), so a ±2.5-point window matches up to five rows and silently takes whichever sorts
first. The displayed premium may belong to a different coverage level than the row label.

### 7.6 Price and delta use different sigmas, contrary to the code's own docstring

`_cell_sigma`'s docstring says it exists "so price and delta always use the SAME sigma for the
same cell." But `build_grid` calls `cme_put_price(F, cov_price, T, r, base_vol)` — passing the
flat `base_vol` — while the delta uses `_cell_sigma(...)`. The hedge ratio is therefore
inconsistent with the price it is derived from. Separately, `_cell_sigma`'s skew term
(`-moneyness * 0.15`) implies +4.3 vol points at 75% coverage where RMA's actual smile is
+2.4 — roughly 1.8× too steep.

### 7.7 The sales-window cutoff in the docstring is wrong

The module docstring states "9:00 AM CT — Window closes, prices expire" and
`fetch_lrp_current()` branches on `now_ct.hour < 9`. The Basic Provisions say the sales period
"ends at **8:25 AM Central Time** the following calendar day." **[V]** The tool therefore treats
a 35-minute dead window as live and will hand a producer rates they can no longer act on. The
`< 9` hour comparison should become an explicit 8:25 CT boundary.

### 7.8 Hard-coded axes that RMA varies

`TENORS_WEEKS` is correct for today but tenor availability is date-dependent (8 tenors in 2021,
no 13-week in mid-2023), and only 136 of 150 feeder (type, tenor) pairs are offered on a given
day (§1.3). PAF for Dairy and Unborn Calf classes varies **by end month**, not just by type. All
of these should be read from the file.

### 7.9 Missing analysis that would change a decision

- **No seasonality view** — the end-month effect (Dec +$1.95 to Aug −$3.16/cwt) is larger than
  the coverage-level effect the grid is organised around (§1.5b).
- **No basis panel.** The tool implies the index is the producer's price (§1.7).
- **No head-limit tracking** — 25,000 head/crop year aggregated across SBI (§1.3).
- **No no-double-coverage check** — the handbook forbids re-covering the same animals under a
  second endorsement, which is the binding constraint on laddering (§1.3).
- **No premium-due-date display** — premium is now due the first of the second month after the
  end date, a material and free cash-flow benefit (§1.6).
- **No suspension calendar** — Cattle on Feed and Hogs and Pigs release days, and CME limit
  moves, are knowable in advance and determine whether tomorrow's window will even exist.
- **The 60-day marketing-window rule is not enforced**, so the grid invites tenor-shopping on
  historical returns when the legal choice is constrained by the actual marketing date (§1.3).
- **The gap history is immutable and is accumulating values computed with 7.1–7.3 in force.**
  It will need to be recomputed from the archived daily rate files rather than corrected in
  place — which is feasible, since §4.1 and §4.2 show the entire input history is retrievable.
- **No subsidy-capture guard.** If the delta-hedge tab ever recommends a paired exchange
  position, LRP §25 (§3) makes that presumptively a violation with criminal exposure. This
  belongs in the code as a hard block, not a footnote.

---

## 8. Reproduction notes

Everything marked **[C]** came from:

- `https://pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{RY}/index.html` — directory
  listings, RY2014–RY2027.
- `2027_ADMLivestockLrp_Daily_20260805.zip` — 99,800 rows; election-space enumeration, identity
  verification, and the implied-vol smile (Black-76 inverted at each strike with RMA's EEV as
  the forward).
- 238 archived daily LRP rate files, 2015-07-01 → 2025-05-29, 132,345 feeder-cattle rows —
  vintage discontinuities and the AEV proxy-bias diagnostic.
- `2027_A00833_ADMDrpDailyPrice_Daily_20260805.zip` — expected prices, sigmas, loading factor;
  the DRP `A(C)` table via 400,000-path lognormal simulation with ρ = 0.6 between Class III and
  Class IV.
- `2027_A00831_ADMDrpDraw_Quarterly_20260723.zip`, `A00832`, `A00834`, `A00835` — schema
  confirmation.

- `https://public.rma.usda.gov/livestockreports/LRPReport` — wizard driven end-to-end; column
  schema, 1,273-date range, populated Actual End Values, and the empirically recovered subsidy
  schedule.

The DRP `A(C)` figures use a lognormal approximation to RMA's copula draws; the **ordering and
the dominance conclusion** are what matter, not the third decimal. A production implementation
should use the A00831 draws directly, which removes the approximation entirely.

### Open items worth chasing

1. **The lognormal draw transform for DRP is inferred, not published.** Validate the engine
   against a real agent quote before trusting it (§4.3 step 3).
2. **No published study quantifies whether RMA's rating vol lags CME implied vol.** The word
   "volatility" does not appear anywhere in FCIC-20010. This is the empirical question behind
   the whole savings-gap thesis and it is genuinely open.
3. **A 2027 subsidy revision is coming** to conform to the One Big Beautiful Bill Act
   (PM-26-024), which will also permit concurrent coverage between similar programs. Any
   hard-coded schedule will need revisiting.
4. **Anderson (2025)**, Univ. of Arkansas MS thesis <https://scholarworks.uark.edu/etd/5712/> —
   the only LRP-specific basis study found; full text is 403-blocked and worth requesting
   directly for the §1.7 basis panel.
