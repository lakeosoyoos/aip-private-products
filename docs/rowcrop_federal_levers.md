# Row-Crop Federal Crop Insurance — The Producer's Levers

**A first-principles enumeration and quantification, in the style of `docs/producer_decision_research.md`
and the calibration docstring of `src/prfopt.py`.**

Author: research pass, 2026-08-07. Reinsurance year 2026.

---

## 0. How to read this document

Every factual claim is tagged:

- **[V]** — verified against a primary source (RMA handbook, Basic Provisions, statute), quoted.
- **[C]** — computed by me in this session from RMA's own published data files. The script is in
  `scripts/analysis/` and is named at the point of use.
- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis to test.

The PRF work reduced a product to an exact payout equation, enumerated the complete legal election
set, and scored every element against a published history. LRP/DRP did the same. This document does
it for the individual-plan row-crop policy (YP / RP / RP-HPE).

**Two things make this tractable in the same way DRP was.** First, RMA publishes every rating
primitive in the Actuarial Data Master, so the entire election space can be priced from files the
repo already reaches. Second — and this is the structural collapse that makes the search space small
— **expected net return per producer premium dollar depends only on the subsidy rate and the rate
load. Every other multiplicative factor divides out.** §2.3 derives this. It is the exact analogue of
DRP's protection factor collapsing (`drpopt.py`) and of the PRF normalization per $1 of protection
(`prfopt.py`).

---

## 1. SCOPE BOUNDARY — read this first

**This document is about choosing legally among the products, plans, coverage levels, unit
structures and options a producer is entitled to elect.** Every lever below is an election the
producer makes on an application or acreage report, priced by RMA in the actuarial documents,
and available to anyone who qualifies.

**It is NOT about misreporting acres, yields, practices, shares, or production.** That is fraud. It is
what RMA's schemes-or-devices rules target, and it does not appear here as a "lever" at any point.

Basic Provisions 26-BR §27, quoted verbatim: **[V]**

> "27. Concealment, Misrepresentation or Fraud
> (a) If you have falsely or fraudulently concealed the fact that you are ineligible to receive
> benefits under the Act or if you or anyone assisting you has intentionally concealed or
> misrepresented any material fact relating to this policy:
> (1) This policy will be voided; and
> (2) You may be subject to remedial sanctions in accordance with 7 CFR part 400, subpart R.
> (b) Even though the policy is void, you will still be required to pay 20 percent of the premium
> that you would [otherwise owe]…"

The line between a lever and a scheme is bright and it is this: **a lever changes what you buy; a
scheme changes what you report.** Electing enterprise units is a lever. Reporting two units as one to
get the enterprise subsidy while keeping optional-unit loss adjustment is a scheme. Electing Yield
Exclusion for a county-declared eligible year is a lever. Dropping a bad year that RMA did not
declare eligible is a scheme.

**Agent compensation.** Standard Reinsurance Agreement §III(a)(4) caps what an AIP may pay for
sale and service of eligible crop insurance contracts at **80 percent of the A&O expense subsidy by
State**, with an exception in §III(a)(4)(C) permitting up to 100 percent where the AIP earned an
underwriting gain for the reinsurance year. **[V]**
<https://www.rma.usda.gov/sites/default/files/2024-09/SRA%202024.pdf>
This matters here for one reason: **the producer's premium is identical at every agent and every
AIP** — federal rates and subsidies are set by RMA, not negotiated. Anything offered as a
producer-side price concession is a rebate, which is prohibited, and any "extra service" funded
outside the A&O cap is a schemes-or-devices exposure for the agent, not a lever for the producer.
See RMA's Agent Compensation — Schemes or Devices FAQ. **[V]**
<https://www.rma.usda.gov/about-crop-insurance/frequently-asked-questions/agent-compensation-schemes-devices>

---

## 2. The equations

### 2.1 Guarantee and indemnity

From the Common Crop Insurance Policy Basic Provisions 26-BR and the crop-specific Crop
Provisions. **[V]**
<https://www.rma.usda.gov/sites/default/files/2025-11/Basic-Provisions-26-BR.pdf>

```
ApprovedYield  = APH average, after TA / YE / substitution / cup / floor       (§4, and CIH Part 16)
Guarantee_YP   = ApprovedYield × CoverageLevel
Liability_YP   = Guarantee_YP × ProjectedPrice × Acres × Share

RP  : RevenueGuarantee = ApprovedYield × CoverageLevel × max(ProjectedPrice, HarvestPrice)
RPHPE: RevenueGuarantee = ApprovedYield × CoverageLevel × ProjectedPrice

Indemnity_YP  = max(0, Guarantee_YP − ProductionToCount) × ProjectedPrice × Acres × Share
Indemnity_RP  = max(0, RevenueGuarantee − ProductionToCount × HarvestPrice) × Acres × Share
```

### 2.2 Premium

The ADM primitives, all confirmed present in the RY2026 files: **[C]**

```
PreliminaryRate = ReferenceRate × (RateYield / ReferenceAmount)^Exponent + FixedRate    [A01010]
BaseRate        = PreliminaryRate × RateDifferentialFactor(CoverageLevel)               [A01040]
                                  × UnitResidualFactor(CoverageLevel, unit)             [A01040]
                                  × UnitDiscountFactor(CoverageLevel, unit, unit acres)  [A01090]
                                  × Π OptionRate(option)                                [A01060]
GrossPremium    = Liability × BaseRate
Subsidy         = GrossPremium × SubsidyPercent(CoverageLevel, UnitStructure, Plan)     [A00070]
ProducerPremium = GrossPremium − Subsidy
```

`Exponent` is negative (−1.39 to −1.59 in the corn belt), so a higher rate yield lowers the rate.
**[C]** For Champaign County IL corn, type 016, RY2026: `ReferenceAmount = 212`,
`ReferenceRate = 0.0078`, `Exponent = −1.593`, `FixedRate = 0.0051`.

**The verbatim assembly order above is my reading of the ADM layout, not a quoted RMA formula.**
RMA does not publish the premium-calculation pseudocode in the ADM documentation. I have
reproduced plausible dollar magnitudes (§4.4) but I have **not** validated against RMA's Cost
Estimator — see §12, open item 1. Treat the *ratios* in this document as solid and the *absolute
dollars* as illustrative.

### 2.3 The structural collapse

Write expected net return as a function of coverage level `C` and unit structure `u`. Let `A(C,u)` be
the actuarially fair expected indemnity per acre and `L` the rate load, so
`GrossPremium = L · A(C,u)`:

```
E[net]          = A(C,u) − L·A(C,u)·(1 − s(C,u))
E[net] / ProducerPremium = A(C,u) / (L·A(C,u)·(1 − s(C,u))) − 1
                         = 1 / [ L · (1 − s(C,u)) ] − 1
```

**`A(C,u)` cancels.** So does the preliminary yield rate, the rate differential factor, the unit
residual factor, the unit discount factor, acres, share, the projected price, and the approved yield.
**Expected net return per producer premium dollar is a function of the subsidy rate and the load,
and nothing else.**

Three consequences, all of which drive the rest of this document:

1. **The subsidy schedule alone determines capital efficiency.** Anywhere `s` is flat across two
   coverage levels, the lower level is weakly dominated — same return per dollar, strictly fewer
   dollars of coverage.
2. **The rate differential factor is irrelevant to efficiency but decisive for budget.** It sets how
   many dollars of coverage a given premium buys, not the return on them.
3. **The only thing that can overturn (1) is a load `L` that varies with `C` or `u`.** In LRP that is
   exactly what happened — RMA's volatility smile made the high-subsidy corner an illusion
   (`producer_decision_research.md` §1.5). **So the load-by-coverage-level question is the single
   most important empirical check in this document, and §5.3 answers it with 15 years of RMA's own
   experience data.**

The producer's edge over a market-priced hedge **is the subsidy**, exactly as in LRP. There is no
private market that will sell an at-the-money revenue put on a farm's own yield at 41–80 percent
off. Every ranking below is fundamentally a ranking of subsidy capture per unit of retained risk.

---

## 3. The subsidy schedule — computed from ADM, and it changed for 2026

### 3.1 RY2026, computed

From `2026_A00070_SubsidyPercent_YTD.txt`, plans 01/02/03 (YP/RP/RPHPE), Coverage Type A
(buy-up), commodity-independent rows. **[C]** — `scripts/analysis/` inline pivot; 315 rows for
these three plans, of which the 89 commodity-independent rows form the schedule.

| Coverage level | Basic (BU) | Optional (OU) | Enterprise (EU) | Whole-farm (WU) |
|---|---|---|---|---|
| 0.50 | 67% | 67% | **80%** | **80%** |
| 0.55 | 69% | 69% | **80%** | **80%** |
| 0.60 | 69% | 69% | **80%** | **80%** |
| 0.65 | 64% | 64% | **80%** | **80%** |
| 0.70 | 64% | 64% | **80%** | **80%** |
| 0.75 | 60% | 60% | **80%** | **80%** |
| 0.80 | 51% | 51% | 71% | 71% |
| 0.85 | 41% | 41% | 56% | 56% |

CAT (Coverage Type C) is a single row: 0.50 coverage, BU, **100%** subsidy. **[C]**

**One trap in this table worth naming, because I nearly reported it wrong.** A00070 also carries 48
rows for commodity 0018 (Rice) at a flat **41 percent** subsidy across every coverage level for BU
and OU. Those are **not** the rice base policy — every one of them carries
`Insurance Option Code = DC`, which A00570 resolves as **"Downed Commodity Endsmnt"**, a separately
rated rice endorsement (A01060 option rate 0.3561, rate method F/fixed). **[C]** Rice's base policy
follows the generic schedule above. The 89 commodity-independent rows are the schedule; the 226
commodity-coded rows for 0051 and 0081 are exact duplicates of it, and the 48 rice rows are the
endorsement. Any loader that reads A00070 without filtering on `Insurance Option Code` will
mis-subsidize rice.

**Basic and optional units carry the identical subsidy percentage at every coverage level.** **[C]**
This is worth stating plainly because it is widely misremembered; the BU/OU difference is entirely
in the *rate* (§4.2), not the subsidy.

### 3.2 The statute

7 U.S.C. 1508(e)(2) sets the basic/optional schedule; 1508(e)(5) governs enterprise and whole-farm
units and caps their subsidy at **80 percent of total premium**, requiring the subsidy "to the
maximum extent practicable, provide the same dollar amount of premium subsidy per acre" as under
basic units. **[V]** <https://www.law.cornell.edu/uscode/text/7/1508>

The ADM table is at the statutory cap for every level up to 0.75 for EU and WU. That cap is why the
enterprise advantage *shrinks* at 80 and 85 percent: at those levels 80 percent of the (much larger)
premium would exceed what the statute allows relative to the basic-unit dollar-parity rule.

### 3.3 The 2026 change, and the pre-2026 schedule recovered empirically

I recovered the *previous* schedule directly, as `subsidy ÷ total premium`, from RMA's Summary of
Business Type/Practice/Unit-Structure files for 2010–2024 (15 years, all crops, buy-up only).
**[C]** — `scripts/analysis/scan_sobtpu.py`, `sob_report.py`.

| Coverage | OU/BU **pre-2026** (measured) | OU/BU **RY2026** (ADM) | Δ | EU **pre-2026** (measured) | EU **RY2026** | Δ |
|---|---|---|---|---|---|---|
| 0.50 | 0.6691 → **67%** | 67% | 0 | 0.8000 → **80%** | 80% | 0 |
| 0.55 | 0.6398 → **64%** | 69% | **+5** | 0.8000 → **80%** | 80% | 0 |
| 0.60 | 0.6399 → **64%** | 69% | **+5** | 0.8000 → **80%** | 80% | 0 |
| 0.65 | 0.5900 → **59%** | 64% | **+5** | 0.8000 → **80%** | 80% | 0 |
| 0.70 | 0.5900 → **59%** | 64% | **+5** | 0.8000 → **80%** | 80% | 0 |
| 0.75 | 0.5500 → **55%** | 60% | **+5** | 0.7700 → **77%** | 80% | **+3** |
| 0.80 | 0.4800 → **48%** | 51% | **+3** | 0.6800 → **68%** | 71% | **+3** |
| 0.85 | 0.3800 → **38%** | 41% | **+3** | 0.5300 → **53%** | 56% | **+3** |

The measured 2010–2014 values reproduce the statutory table to four decimals across billions of
dollars of premium. This is the same empirical-recovery trick that validated the LRP subsidy
schedule (`producer_decision_research.md` §7.3), and it works just as cleanly here.

**RY2026 is the first crop year of the premium-support increase enacted in the 2025 reconciliation
act (H.R. 1, "One Big Beautiful Bill Act").** **[V]** for the statutory change
(<https://www.congress.gov/crs-product/R48574>); **[C]** for the exact per-level deltas above,
which I measured rather than quoted.

Three things the deltas imply that no summary I found states:

- **The increase is largest (+5 points) exactly in the 55–75 percent band, and smallest (+3) at
  80–85 percent.** The subsidy ladder got *steeper*, not flatter. Moving from 75 to 80 percent now
  costs a 9-point subsidy drop instead of 7.
- **Enterprise units at 75 percent and above were raised to exactly the whole-farm-unit schedule
  (80/71/56).** For RY2026 the EU and WU subsidy percentages are identical at every level for the
  first time. **[C]** The whole-farm unit's remaining advantage over the enterprise unit is
  therefore zero on the subsidy side — it is now purely a rate-and-pooling question.
- **The schedule became non-monotone at the bottom.** 50 percent coverage now carries a *lower*
  subsidy (67%) than 55 or 60 percent (69%). Under the old schedule 50 percent was the
  high-subsidy corner. Now it is strictly dominated: 60 percent coverage gives you more insurance
  *and* a better subsidy rate. See §5.2.

**Beginning, veteran and (from 2026) first-time farmers receive additional premium assistance:
5 percentage points in each of the first two reinsurance years, 3 points in the third, 1 point in
the fourth.** **[V]** per the 2025 act summary; I did not find these tiers in the ADM subsidy table,
which suggests they are applied downstream of the actuarial documents. Flagged as an ADM gap.

---

## 4. LEVER 1 — UNIT STRUCTURE (the largest lever, in both directions)

### 4.1 Mechanism and rule

Basic Provisions 26-BR definitions, verbatim: **[V]**

> "Enterprise unit — All insurable acreage in the county in which you have a share on the date
> coverage begins for the crop year, provided you meet the requirements in section 34 of:
> (1) The same insured crop; (2) Irrigated or non-irrigated acreage of the same insured crop; or
> (3) Acreage grown under an organic farming practice or acreage not grown under an organic
> farming practice of the same insured crop."

> "Whole-farm unit — All insurable acreage of all the insured crops planted in the county in which
> you have a share on the date coverage begins for each crop for the crop year and for which the
> whole-farm unit structure is available in accordance with section 34."

§34(a)(2)(i)–(ii), the qualifying test, verbatim: **[V]**

> "(i) The acreage in an enterprise unit must be located in: (A) Two or more sections, if optional
> units are available by sections where the insured acreage is located; … (E) One section, section
> equivalent, or FSA farm number that contains at least 660 planted acres of the insured crop…
> (ii) At least two of the sections, section equivalents, FSA farm numbers, units established by
> written agreement, or non-contiguous parcels of land … must each have planted acreage that
> constitutes at least the lesser of 20 acres or 20 percent of the insured crop acreage in the
> enterprise unit."

§34(a)(3)(i)(B)–(C) for whole-farm units: **[V]**

> "(B) A whole-farm unit must contain all of the insurable acreage of at least two crops; and
> (C) At least two of the insured crops must each have planted acreage that constitutes 10 percent
> or more of the total planted acreage liability of all insured crops in the whole-farm unit…"

§34(c), optional units, verbatim: **[V]**

> "(c) Each optional unit must meet at least one of the following, unless otherwise specified in the
> Crop Provisions or allowed by written agreement: (1) Land location— (i) Section—Optional units may
> be established if each optional unit is located in a separate section where the boundaries are
> readily discernible. … (2) Irrigation practice—Separate optional units may be based on irrigated
> and non-irrigated acreage."

And the recordkeeping price of optional units, §34(b): **[V]**

> "(3) You have records, that are acceptable to us, for at least the previous crop year for all
> optional units that you will report in the current crop year …; and (4) You have records of
> marketed or stored production from each optional unit maintained in such a manner that permits us
> to verify the production from each optional unit…"

### 4.2 The rate side — computed, and it is not what the folklore says

Two ADM tables carry the unit-structure rate effect.

**A01090 UnitDiscount** publishes `Optional Unit Discount Factor`, `Basic Unit Discount Factor`
and `Enterprise Unit Discount Factor` by (unit-discount ID, coverage level, unit acreage band).
**[C]** 6,252 live rows; 6,196 in record category 04, which is the category every corn, soybean,
wheat, cotton, peanut, dry-bean and dry-pea offer points to.

Findings, all **[C]**:

- **Optional unit is the reference: its factor is 1.000 in 6,240 of 6,252 rows.**
- **In record category 04 the Basic and Enterprise discount factors are numerically identical in
  100.0% of rows.** For corn, soybeans, wheat, cotton and peanuts, *a basic unit and an enterprise
  unit of the same acreage receive the same rate discount.* The discount is a function of **unit
  size**, not of the label. Only the smaller crops (rice, canola, grain sorghum, barley — record
  category 03) show a flat BU factor of 0.900 against an acreage-varying EU factor.
- **The discount is steeply size-dependent and floors at 0.600.** Corn, mean across the eight corn
  unit-discount IDs:

| Unit acres | 0.50 | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 |
|---|---|---|---|---|---|---|---|
| 0.01–49.99 | 0.648 | 0.673 | 0.686 | 0.699 | 0.712 | 0.725 | 0.738 |
| 50–99.99 | 0.626 | 0.651 | 0.664 | 0.677 | 0.689 | 0.702 | 0.715 |
| 100–199.99 | 0.611 | 0.629 | 0.641 | 0.654 | 0.667 | 0.679 | 0.693 |
| 200–399.99 | 0.603 | 0.613 | 0.621 | 0.632 | 0.644 | 0.657 | 0.670 |
| 400–799.99 | 0.600 | 0.603 | 0.608 | 0.615 | 0.624 | 0.634 | 0.647 |
| 800+ | 0.600 | 0.600 | 0.601 | 0.604 | 0.610 | 0.617 | 0.627 |

  **This table is RMA's own price of risk pooling**, and it is the cleanest quantification in this
  document of the thing the enterprise unit actually buys. A 900-acre unit is rated at 0.627 of an
  optional unit's rate at 85 percent coverage; a 40-acre unit at 0.738. The whole benefit of
  aggregating is that you slide down this curve.

**A01040 CoverageLevelDifferential** carries a second, smaller unit effect through
`Unit Residual Factor` (applies to OU and BU), `Enterprise Unit Residual Factor`, and
`Whole Farm Unit Residual Factor`. **[C]** — `scripts/analysis/scan_cld.py`, 3.90 million qualifying
row-crop rows streamed out of the 2.7 GB file. National means:

| Crop | factor | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 |
|---|---|---|---|---|---|---|
| Corn | U (OU/BU) | 1.0000 | 1.0000 | 1.0129 | 1.0467 | 1.0959 |
| Corn | EU | 0.9998 | 0.9999 | 1.0062 | 1.0230 | 1.0477 |
| Soybeans | U | 1.0000 | 1.0048 | 1.0286 | 1.0535 | 1.0785 |
| Soybeans | EU | 0.9998 | 1.0024 | 1.0142 | 1.0267 | 1.0392 |
| Wheat | U | 1.0000 | 1.0288 | 1.0781 | 1.1309 | 1.1830 |
| Wheat | EU | 1.0000 | 1.0144 | 1.0390 | 1.0655 | 1.0915 |

So above 70 percent coverage there is an additional surcharge on non-enterprise units, roughly
double the enterprise surcharge — 9.6 vs 4.8 points for corn at 85 percent.

**Whole-farm units are the gap in this reconstruction.** `Whole Farm Unit Residual Factor` is exactly
1.0000 in all 64 crop × coverage-level cells I measured, and A01090 has **no whole-farm column at
all**. **[C]** So the ADM tables I pulled do not determine the whole-farm rate path. The natural
inference is that WFU uses the enterprise discount factor evaluated on total whole-farm acreage,
but I did not confirm this. **[R]** — flagged as open item 2.

### 4.3 The trigger-probability side — measured, not asserted

The brief is right that the subsidy gain must not be presented without the pooling loss. Here it is,
measured. I aggregated 15 years (2010–2024) of RMA's SOBTPU experience file — every state, county,
crop, coverage level, unit structure — and then built **matched cells**: same year, same state, same
crop, same coverage level, with at least $20 million of liability in *both* the EU and OU column, so
that geography, crop and coverage level are controlled. 1,642 matched cells. **[C]** —
`scripts/analysis/scan_sobtpu_state.py`.

| Year | OU gross LR | EU gross LR | **EU/OU** | OU gross rate | EU gross rate | OU net $/ac | EU net $/ac |
|---|---|---|---|---|---|---|---|
| 2011 | 0.778 | 0.565 | **0.726** | 0.1189 | 0.0889 | 17.72 | 13.47 |
| **2012** | 1.531 | **2.161** | **1.411** | 0.1140 | 0.0776 | 55.65 | **82.59** |
| 2013 | 1.005 | 1.082 | 1.077 | 0.1135 | 0.0810 | 28.62 | 35.22 |
| 2014 | 0.988 | 0.925 | 0.936 | 0.1051 | 0.0788 | 21.53 | 22.87 |
| 2015 | 0.562 | 0.415 | 0.738 | 0.1076 | 0.0884 | 3.22 | 3.99 |
| 2016 | 0.268 | 0.163 | **0.608** | 0.1047 | 0.0875 | −7.51 | −4.74 |
| 2017 | 0.462 | 0.297 | **0.643** | 0.1063 | 0.0868 | −0.62 | −0.17 |
| 2018 | 0.537 | 0.407 | 0.758 | 0.0995 | 0.0778 | 2.27 | 3.72 |
| 2019 | 0.962 | 0.930 | 0.967 | 0.1034 | 0.0801 | 18.69 | 21.91 |
| 2020 | 0.588 | 0.576 | 0.980 | 0.0955 | 0.0762 | 3.87 | 9.15 |
| 2021 | 0.635 | 0.466 | 0.734 | 0.1063 | 0.0902 | 7.28 | 7.85 |
| 2022 | 0.906 | 0.630 | 0.695 | 0.1073 | 0.0912 | 26.64 | 20.25 |
| 2023 | 1.037 | 0.709 | **0.684** | 0.1014 | 0.0807 | 33.46 | 22.59 |
| 2024 | 0.817 | 0.582 | 0.712 | 0.1002 | 0.0814 | 16.35 | 12.70 |

Pooled over all matched cells:

| | gross LR | gross rate | producer rate | net $/acre | **net per producer $** |
|---|---|---|---|---|---|
| Optional | 0.837 | 0.1066 | 0.0504 | 16.89 | 0.769 |
| Basic | 0.972 | 0.0831 | 0.0402 | **18.59** | 1.009 |
| Enterprise | **0.702** | 0.0835 | **0.0249** | 17.36 | **1.353** |

**This is the honest two-sided answer, and it has four parts:**

1. **The pooling loss is real and it is about 16 percent of gross loss ratio.** EU 0.702 vs OU 0.837
   in matched cells. In 12 of 14 years the enterprise unit collected less per gross premium dollar
   than the optional unit on the same crop, in the same state, at the same coverage level.
2. **The loss is concentrated in scattered-loss years and reverses in systemic ones.** The two years
   where EU beat OU are 2012 (LR ratio 1.411) and 2013 (1.077) — the widespread drought. The worst
   years for EU are 2016 (0.608), 2017 (0.643) and 2023 (0.684), all years of good national yields
   with localized damage. **The enterprise unit is a bet that your bad years will be your county's
   bad years.** That is the correct way to frame the decision to a producer, and it is a statement
   about their farm's spatial correlation, not about the insurance.
3. **The rate discount plus the subsidy more than pays for it.** EU gross rate is 22 percent below
   OU; the producer rate is **half** (0.0249 vs 0.0504). Net per producer dollar is 1.353 for EU
   against 0.769 for OU — a 76 percent improvement in return on premium capital.
4. **In raw dollars per acre it is nearly a wash, and basic units won.** EU $17.36, OU $16.89,
   BU $18.59. **The enterprise unit's advantage is capital efficiency, not expected dollars.** A tool
   that ranks on net dollars per acre will not pick EU; a tool that ranks on net per premium dollar
   will pick it decisively. Both are legitimate objectives and the producer's budget constraint
   decides which applies.

### 4.4 The basic-unit result, which I did not expect

Basic units carry **the same subsidy percentage as optional units** (§3.1, [C]) and **the same rate
discount factor as enterprise units** in ADM record category 04 (§4.2, [C]). Empirically, over
2010–2024, they returned **$18.59/acre net and 1.009 per producer dollar — better than optional
units on both measures, at 80 percent of the producer premium rate.** **[C]**

The mechanism is visible in the loss ratios: BU realized a gross loss ratio of 0.972 against OU's
0.837. **RMA's basic-unit discount is more generous than the realized experience justifies**, whereas
the optional-unit surcharge is not earned back by the extra trigger opportunities.

**Caveats, stated honestly. [R]** This is an unmatched population comparison at the aggregate level;
producers who choose basic over optional units are self-selected, and BU is the *default* structure
assigned when an optional-unit election fails its recordkeeping test (§34(b)(3)–(4)), so the BU pool
contains involuntary entrants. I did not control for farm size, and unit size drives the discount
factor directly. The result is strong enough to be worth testing properly and not strong enough to
recommend on.

### 4.5 Availability

Every one of the 543,342 RY2026 row-crop YP/RP/RPHPE insurance offers carries
`Optional Unit Allowed Flag = Y`, `Basic Unit Allowed Flag = Y`, and
`Enterprise Unit Allowed Flag = Y`. **[C]** — `scripts/analysis/scan_offers.py`. Whole-farm units are
allowed on two thirds of offers and are **entirely unavailable for peanuts, dry beans and dry peas**
(0 of 17,901 / 17,307 / 13,959 offers). Enterprise units are available in 100 percent of counties for
all 15 row crops.

Two free structural options found in A01060, both with an **Option Rate of exactly 1.0000
(multiplicative)** — i.e. no rate charge at all: **[C]**

- **`MC` Multi-County EU** — offered on 11 row crops, 108,582 corn offers. Combining counties into
  one enterprise unit costs nothing in rate *and* moves the unit down the size-discount curve.
  A producer at 300 acres in each of two counties pays the 200–399 band (0.657 at 85%); combined at
  600 acres they pay the 400–799 band (0.647). Small but free.
- **`EI` EU by Irrigation Practice**, **`ET` EU by Type**, **`EC` EU by Cropping Practice** — all
  1.0000. Splitting an enterprise unit by practice is free in rate but **shrinks each unit**, moving
  you back *up* the discount curve, and the experience data says it goes badly: `EP` (EU separated
  by irrigation practice) returned **0.653 per producer dollar** and `EC` (by cropping practice)
  **−0.286**, against plain EU's 1.419, over 2010–2024. **[C]** For corn at 85 percent coverage the
  `EP` net was **+$0.29/acre** against plain EU's **+$23.60/acre**. This is the sharpest negative
  finding in the document: **splitting an enterprise unit by practice destroys most of its value.**

---

## 5. LEVER 2 — COVERAGE LEVEL

### 5.1 The rate cost of each step

`Rate Differential Factor` from A01040, normalized to 1.0000 at the 65 percent reference level,
national mean over all qualifying county/type/practice rows. Identical across YP, RP and RPHPE to
four decimals for every crop — **the coverage-level rate curve does not depend on the plan.** **[C]**

| Crop | 0.50 | 0.55 | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 |
|---|---|---|---|---|---|---|---|---|
| Corn | 0.7335 | 0.8060 | 0.8949 | 1.0000 | 1.1227 | 1.2637 | 1.4208 | 1.5937 |
| Soybeans | 0.7018 | 0.7760 | 0.8754 | 1.0000 | 1.1503 | 1.3257 | 1.5272 | 1.7549 |
| Wheat | 0.7427 | 0.8184 | 0.9042 | 1.0000 | 1.1068 | 1.2244 | 1.3528 | 1.4921 |
| Cotton | 0.7776 | 0.8471 | 0.9218 | 1.0000 | 1.0828 | 1.1724 | 1.2712 | 1.3775 |
| Grain Sorghum | 0.7962 | 0.8611 | 0.9290 | 1.0000 | 1.0736 | 1.1500 | 1.2291 | 1.3113 |
| Rice | 0.8900 | 0.9222 | 0.9591 | 1.0000 | 1.0470 | 1.0991 | 1.1565 | 1.2179 |
| Barley | 0.7564 | 0.8306 | 0.9118 | 1.0000 | 1.0964 | 1.2001 | 1.3109 | 1.4291 |
| Oats | 0.8210 | 0.8780 | 0.9377 | 1.0000 | 1.0650 | 1.1327 | 1.2038 | 1.2781 |

**The curve is steepest where the crop is least volatile relative to its county mean, and it varies
enormously within a crop.** Corn's 85-percent factor has a national mean of 1.5937 but ranges
**1.0393 to 2.5193** across counties. **[C]** In Champaign County IL — prime, low-risk ground — it is
**2.2669**. High coverage is far more expensive, in relative terms, on good ground than on marginal
ground, because on good ground the 65-percent reference level almost never triggers.

### 5.2 Marginal producer cost per dollar of added liability

The brief asks for this in producer dollars per $1 of added liability. Worked from ADM primitives
for Champaign County IL corn, RP, type 016, non-irrigated, 212-bu APH sitting exactly at the county
reference yield, $4.62 projected price, a 400–799-acre unit. **[C]** —
`scripts/analysis/worked_example.py`. Preliminary yield rate 0.01290.

| Unit | Cov | Liability $/ac | Base rate | Gross $/ac | Subsidy | **Producer $/ac** | Producer $/ac at pre-2026 subsidy | **Marginal producer $ per $1 added liability** |
|---|---|---|---|---|---|---|---|---|
| OU | 0.50 | 489.72 | 0.00763 | 3.74 | 67% | 1.23 | 1.23 | — |
| OU | 0.55 | 538.69 | 0.00868 | 4.68 | 69% | 1.45 | 1.68 | 0.0044 |
| OU | 0.60 | 587.66 | 0.01044 | 6.13 | 69% | 1.90 | 2.21 | 0.0092 |
| OU | 0.65 | 636.64 | 0.01290 | 8.21 | 64% | 2.96 | 3.37 | 0.0215 |
| OU | 0.70 | 685.61 | 0.01607 | 11.02 | 64% | 3.97 | 4.52 | 0.0206 |
| OU | 0.75 | 734.58 | 0.02000 | 14.69 | 60% | 5.88 | 6.61 | 0.0390 |
| OU | 0.80 | 783.55 | 0.02555 | 20.02 | 51% | 9.81 | 10.41 | **0.0803** |
| OU | 0.85 | 832.52 | 0.03233 | 26.92 | 41% | 15.88 | 16.69 | **0.1240** |
| BU | 0.75 | 734.58 | 0.01247 | 9.16 | 60% | 3.66 | 4.12 | 0.0250 |
| BU | 0.80 | 783.55 | 0.01620 | 12.70 | 51% | 6.22 | 6.60 | 0.0522 |
| BU | 0.85 | 832.52 | 0.02092 | 17.42 | 41% | 10.28 | 10.80 | 0.0828 |
| EU | 0.50 | 489.72 | 0.00458 | 2.24 | 80% | **0.45** | 0.45 | — |
| EU | 0.65 | 636.64 | 0.00784 | 4.99 | 80% | 1.00 | 1.00 | 0.0053 |
| EU | 0.70 | 685.61 | 0.00988 | 6.77 | 80% | 1.35 | 1.35 | 0.0073 |
| EU | 0.75 | 734.58 | 0.01245 | 9.15 | 80% | 1.83 | 2.10 | **0.0097** |
| EU | 0.80 | 783.55 | 0.01560 | 12.22 | 71% | 3.54 | 3.91 | **0.0350** |
| EU | 0.85 | 832.52 | 0.01964 | 16.35 | 56% | 7.20 | 7.69 | **0.0746** |

Read the last column as: *this is what the next dollar of coverage costs you.*

- **Under an enterprise unit, every dollar of coverage up to 75 percent costs under one cent.** The
  step from 70 to 75 percent costs **0.97 cents per added dollar of liability.**
- **The step from 75 to 80 percent costs 3.6× that (3.50 cents), and 80 to 85 costs 7.7× (7.46
  cents).** Those two cliffs are the subsidy dropping 80 → 71 → 56.
- **Under optional units the same two steps cost 8.03 and 12.40 cents.** An optional-unit producer's
  last five points of coverage cost 12.4 cents per dollar; an enterprise-unit producer's cost 7.5.
- **The 2026 subsidy increase is worth 5–10 percent of producer premium here** (column 8 minus
  column 7), and it is worth *nothing at all* to an enterprise-unit producer below 75 percent
  coverage, because that band was already at the 80 percent statutory cap.

### 5.3 Dominance, and the load check that could have overturned it

From §2.3, `E[net] per producer dollar = 1/[L·(1−s)] − 1`. With `L` constant, any coverage level
that shares a subsidy rate with a higher level is weakly dominated. From the RY2026 schedule: **[C]**

| Unit | Subsidy bands | **Dominated levels** | Efficient frontier |
|---|---|---|---|
| BU / OU | {0.55, 0.60}→69%; {0.65, 0.70}→64%; 0.50→67% is *below* 0.60's 69% | **0.50, 0.55, 0.65** | **0.60, 0.70, 0.75, 0.80, 0.85** |
| EU / WU | {0.50 … 0.75} all →80% | **0.50, 0.55, 0.60, 0.65, 0.70** | **0.75, 0.80, 0.85** |

**For an enterprise unit, five of the eight coverage levels are strictly dominated.** Anything below
75 percent buys less insurance at exactly the same 80 percent subsidy rate. This is the direct
analogue of DRP's "90 percent is dominated by 95 percent" (`producer_decision_research.md` §2.4) and
it is five times larger. **An enterprise-unit producer sitting at 70 percent coverage is leaving
free liability on the table**, and the dollar size is in §5.2: going 70 → 75 costs 0.97 cents per
added dollar and buys $49/acre more coverage for $0.48/acre more premium.

**But `L` is not constant, and the LRP experience says to check.** Measured gross loss ratio by
coverage level, 2010–2024, corn+soy+wheat buy-up: **[C]**

| Coverage | OU gross LR | BU gross LR | EU gross LR | OU net $/ac | BU net $/ac | EU net $/ac | EU net per producer $ |
|---|---|---|---|---|---|---|---|
| 0.50 | 0.818 | 1.020 | 0.517 | 9.46 | 10.29 | 3.84 | 1.583 |
| 0.55 | 0.804 | 0.963 | 0.545 | 11.23 | 11.45 | 5.75 | 1.710 |
| 0.60 | 0.837 | 1.053 | 0.555 | 15.56 | 17.41 | 8.43 | 1.782 |
| 0.65 | 0.848 | 1.082 | 0.642 | 14.53 | 17.48 | 12.81 | 2.210 |
| 0.70 | 0.835 | 1.050 | 0.674 | 17.62 | 21.40 | 17.84 | **2.379** |
| **0.75** | 0.839 | 1.043 | 0.707 | **19.20** | **23.57** | **21.39** | 2.089 |
| 0.80 | 0.853 | 0.951 | 0.692 | 17.04 | 17.77 | 16.57 | 1.170 |
| 0.85 | **0.899** | 0.972 | **0.802** | 13.88 | 15.24 | 14.54 | 0.709 |

**The load is not constant: it falls as coverage rises.** For enterprise units the gross loss ratio
climbs monotonically from 0.517 at 50 percent to 0.802 at 85 percent — RMA rates low coverage with
substantially more cushion than high coverage. This is the *same direction* as the LRP volatility
smile (RMA over-prices out-of-the-money protection), and it **reinforces rather than overturns the
dominance result**: high coverage is both better subsidized *within a band* and more fairly rated.

**The empirical peak, in dollars, is 75 percent for every unit structure.** Net dollars per acre rise
to 0.75 and then fall — because above 0.75 the subsidy collapses faster than the rating improves.
The efficiency ratio peaks earlier (0.70 for EU, at 2.379 per producer dollar).

**So the correct summary is a two-part rule, and neither part alone is right: [C]/[R]**

> **Never sit below the top of your subsidy band** — that is free liability, guaranteed by the
> arithmetic of §2.3, with no offsetting rate penalty in the direction that would matter.
> **Above 75 percent you are buying real risk transfer at a real price** — the marginal cost per
> dollar of liability triples at 80 and roughly doubles again at 85 — and 15 years of experience says
> those top two steps did not pay for themselves in expected dollars. Buy them because you need the
> downside protection, not because the ladder looks like a bargain.

The gap between "the top of your band is free" and "80 and 85 percent are expensive" is not a
contradiction: for enterprise units the top of the band *is* 75 percent.

---

## 6. LEVER 3 — PLAN: YP vs RP vs RP-HPE

### 6.1 What the harvest price option actually buys

`RevenueGuarantee_RP = ApprovedYield × CoverageLevel × max(ProjectedPrice, HarvestPrice)`. The RP
guarantee ratchets up if the harvest price exceeds the projected price. Since the indemnity is
`Guarantee − Production × HarvestPrice`, the harvest price appears on both sides — so **the harvest
price option is economically a call on the price of the bushels you failed to grow.** It pays only in
the joint state {short production} ∧ {price rally}, which is precisely the state in which a producer
who forward-contracted has to buy back bushels at the higher price.

**This is the one lever whose value is genuinely producer-specific rather than actuarial.** A
producer with no forward sales has no bushels to buy back and gains only the guarantee ratchet; a
producer who has forward-contracted 60 percent of an expected crop faces exactly the exposure RP
covers. **[R]**

### 6.2 Cost — computed two ways

**(a) The coverage-level rate curve is identical across the three plans.** `Rate Differential Factor`
matches to four decimals for YP, RP and RPHPE in every crop (§5.1). **[C]** So the plan choice does
not interact with the coverage-level choice at all; they are separable decisions.

**(b) The subsidy percentage is identical across the three plans.** A00070 gives plans 01, 02 and 03
the same schedule at every coverage level and unit structure. **[C]** **This is the key economic
fact: the harvest price option is subsidized at the same 41–80 percent as the base policy.** A
producer buying RP over RPHPE is buying a price call at a 41–80 percent discount. No commercial
counterparty offers that.

**(c) The premium difference.** RMA does not tabulate RP and RPHPE rates — they are simulated at
quote time from the A01020 Beta draws (500 standardized, mean-0, sd-1 yield/price draw pairs per
state × commodity; 404 beta IDs, 202,000 rows) together with the A01030 ComboRevenueFactor
parameters and the A00810 `Price Volatility Factor`. **[C]** I confirmed the components exist and
their shapes but did not reconstruct RMA's revenue simulation — see §12, open item 3.

Measured instead from matched Summary-of-Business cells (same year, state, crop, coverage level and
unit structure, at least $5 million of liability in each plan; 637 cells, 2010–2024): **[C]**

| Crop | cells | median RP gross rate ÷ RPHPE gross rate |
|---|---|---|
| Corn | 382 | **1.72** |
| Soybeans | 216 | **1.55** |
| Cotton | 6 | 1.45 |
| Wheat | 33 | **1.30** |

**The harvest price option roughly doubles the premium on corn and soybeans.** **Caveat [R]:** RPHPE
is a small, self-selected pool — producers who choose it differ systematically from RP buyers in
ways that matched state/coverage/unit cells do not fully control (APH quality, forward-marketing
behavior, and the fact that SOB liability for RP reflects the *final* guarantee after any harvest
price ratchet). Treat 1.3–1.7 as an order of magnitude, not a rate quote.

### 6.3 When it pays

RY2026 realized ratios, where the harvest price is already set in ADM (winter-sown crops): **[C]**
Champaign County IL wheat, projected $5.76, harvest $6.52 — **a 13.2 percent guarantee ratchet
that RPHPE buyers did not receive**. `Price Volatility Factor` for RY2026: corn 0.15, soybeans
0.13, wheat 0.19–0.21, oats 0.18, sunflowers 0.22, cotton 0.06. **[C]**

The volatility factor is the one input that tells you what RMA thinks the option is worth in a given
year. **A tool should surface it: at 0.06 (cotton) the harvest price option is nearly worthless; at
0.21 (rye, wheat) it is the most valuable single election on the page.** **[R]**

### 6.4 Realized experience

2010–2024, all units, buy-up, corn+soy+wheat: **[C]**

| Plan | liability | gross LR | subsidy % | net per producer $ | net $/acre |
|---|---|---|---|---|---|
| YP (01) | $58.3B | 0.934 | 62.6% | 1.498 | 13.58 |
| RP (02) | $1,113.4B | 0.782 | 62.9% | 1.111 | 17.69 |
| RPHPE (03) | $15.0B | 0.990 | 59.6% | 1.452 | 17.08 |

**RP carries the lowest gross loss ratio of the three — RMA rated the harvest price option with more
cushion than it rated the yield component.** That is the same phenomenon as the LRP smile, applied
to the price dimension. But YP and RPHPE together are barely 6 percent of the book and are grown in
systematically different places, so these are not comparable populations. **[R]**

**Direction and magnitude for the doc's purposes:** RP costs 30–70 percent more premium than RPHPE,
is subsidized identically, and delivers a payoff that is worth a great deal to a forward-seller and
comparatively little to a producer who markets only after harvest. YP is a legacy choice that makes
sense only where no projected price exists or where the crop is fed rather than sold.

---

## 7. LEVER 4 — APH / YIELD-HISTORY TOOLS (the highest return per dollar of effort)

### 7.1 The rule that makes them work

This is the most important citation in the document. Crop Insurance Handbook FCIC-18010-1 (August
2025) ¶1606, **verbatim**: **[V]**

> "**Determining Premium Rates**
> If the approved yield calculation chosen by the insured includes at least one substituted actual
> yield, an optional coverage rate may apply as provided in the actuarial document.
> **The rate yield is equal to the average yield when yield substitutions are used in an APH database**
> with the following exceptions: (1) the approved yield is reduced for Inconsistent approved yields…;
> and (2) the approved yield is reduced for Different Production Methods…"

And "average yield" is defined in the parallel passage at ¶923.R(1)(a), **verbatim**: **[V]**

> "Calculate the average yield by: (a) summing the annual yields in the APH database, **prior to EHA
> yield adjustments, yield exclusions, yield substitutions, trend adjustments, cup, or floor**; and
> (b) dividing that sum by the number of annual yields in the APH database."

Together: **the rate yield is the unadjusted average. Trend adjustment, yield exclusion, yield
substitution, cup and floor raise the approved yield — and therefore the guarantee and the
liability — while leaving the rate yield, and hence the premium rate, untouched.**

The handbook says the same thing in words at ¶923.P: **[V]**

> "The adjusted yield is not the same as the rate yield. The increase in coverage resulting from the
> EHA relative to the APH yield without EHA is used to determine the appropriate premium rate for
> the effective coverage. … Note: The adjusted yield for EHA uses similar methodology as the
> adjusted yield for TA, YE, and YC purposes."

### 7.2 And the option rates are all exactly 1.0000

Streamed from `2026_A01060_OptionRate_YTD.txt` — 5.6 million option-rate rows for row crops.
**[C]** — `scripts/analysis/scan_optrate.py`. All are Rate Method **M** (multiplicative):

| Option | Name | Crops | Rows (corn / soy / wheat) | **Option Rate** |
|---|---|---|---|---|
| `TA` | Trend Adjustment | 11 | 11,037 / 12,750 / 10,161 | **1.0000 (min = max)** |
| `YE` | Yield Exclusion | 15 | 53,052 / 62,373 / 30,240 | **1.0000 (min = max)** |
| `YA` | Yield Adjustment 60% (substitution) | 15 | all offers | **1.0000** |
| `YC` | Yield Cup | 15 | all offers | **1.0000** |
| `MC` | Multi-County EU | 11 | all offers | 1.0000 |
| `HB` | High-Risk Land Exclusion | 5 | 62,073 / 145,116 / 16,020 | 1.0000 |
| `EI`/`ET`/`EC` | EU by practice / type / cropping | 14/4/2 | — | 1.0000 |
| `PY` | Personal T-Yield | 12 | 3,240 / 6,426 / 2,259 | **1.018 – 1.071** (surcharge) |
| `HF` | Hail & Fire Exclusion | 15 | all offers | **0.8923** (credit) |
| `PF` | Prevented Planting +5% | **6 only** | 0 / 0 / 42,462 | **1.0258** (surcharge) |
| `FN` / `FO` | Floor Option 90% / 100% | 2 (wheat, barley) | — | **1.10 / 1.20** |
| `CR` | 2-Yr Crop Rotation | 1 (canola) | — | 1.0879 |
| `SR` | Short Rate Adjustment | 3 | — | 0.3785 (method T) |
| `DC` | Downed Commodity Endorsement | 1 (rice) | — | 0.3561 (method F, fixed) |

**Trend-Adjusted APH, Yield Exclusion, yield substitution and yield cup carry no rate charge
whatsoever, in every offer, for every row crop.** Combined with the ¶1606 rule, this means:

```
liability   ↑ by (1 + g)      where g = the approved-yield lift
rate        unchanged
gross prem  ↑ by (1 + g)      exactly proportional
subsidy $   ↑ by (1 + g)      exactly proportional
producer $  ↑ by (1 + g)      exactly proportional
```

### 7.3 Where the value actually comes from — be precise about this

Because premium scales exactly with liability, **the naive claim "these tools raise the guarantee
without raising the rate proportionally" is only half right, and the half that is right is the
important half.** The rate per dollar of liability is unchanged, so the *proportional* premium
increase is exactly the proportional coverage increase. The value is not a rate discount. It is
this: **[R]**, derived from **[V]** inputs

- **Yield Exclusion**: you remove a county-declared catastrophic year from the average. Your *true*
  forward yield distribution is unchanged by that removal — the bad year already happened. So the
  guarantee moves up relative to an unchanged distribution: expected indemnity rises **more than**
  proportionally while premium rises exactly proportionally. This is a genuine, legal actuarial gain
  and it is the largest of the four.
- **Yield substitution (`YA`, 60 percent of T-yield)**: same logic, applied to individually bad years
  rather than county-declared ones. Same conclusion.
- **Trend adjustment (`TA`)**: the gain is real **only if the trend is real on your farm.** TA raises
  the guarantee on the premise that your older APH years understate your current capability. If
  they do, the guarantee-to-true-mean ratio is unchanged and TA is a pure scale-up — more coverage,
  more subsidy dollars, same efficiency. If they do not (your ground is not trending), TA is a free
  actuarial gain at RMA's expense. Either way it is never negative for the producer, which is why it
  should be the default election.
- **Yield cup / floor**: limits the year-over-year fall in approved yield. Same structure, smaller
  magnitude.

**The one thing RMA closed off:** because the rate yield is the *unadjusted* average, you do **not**
get a rate discount from a higher adjusted yield. Given the negative exponent in §2.2, a producer
whose adjusted yield flowed into the rate yield would get *both* more liability and a lower rate.
¶1606 prevents that. Anyone who models TA as lowering the rate is wrong.

**Availability.** YE is offered on 53,052 corn, 62,373 soybean and 30,240 wheat RY2026 offers; TA on
11,037 / 12,750 / 10,161. **[C]** TA is roughly a fifth as widely offered as YE. The eligible YE
years and the per-county TA yield-adjustment factor are published in the county actuarial documents;
`Historical Yield Trend ID` is blank on **all** row-crop offers in A00030 **[C]**, so the TA factor
is not recoverable from the ADM tables I pulled — see FCIC-20220 Trend-Adjusted APH Standards
Handbook. <https://www.rma.usda.gov/sites/default/files/handbooks/2022-20220-Trend-Adjusted-APH-Standards.pdf>

**Interaction, from RMA's own guidance: [V]** an actual yield excluded under YE is not considered for
TA purposes when determining the trend-adjusted yield. The two stack but do not double-count.

### 7.4 The free rate credit nobody elects

**`HF` — Hail & Fire Exclusion — carries an option rate of 0.8923**, offered on all 15 row crops.
**[C]** A producer who excludes hail and fire from the federal policy cuts the gross premium by
**10.8 percent**. Because the option is multiplicative, producer premium falls by the same
10.8 percent — the subsidy scales down with it, so the *percentage* saving is the same at every
coverage level, but the *dollar* saving is `0.108 × gross × (1 − s)` and is therefore largest where
the subsidy is smallest. On the Champaign corn example at 85 percent optional units it is
0.108 × $26.92 × 0.59 = **$1.72/acre**; on an enterprise unit at 75 percent it is $0.20/acre. The
producer then buys private crop-hail to fill the gap.

Whether that is a good trade depends entirely on the private crop-hail rate in the county, which is
exactly what this repo's private-product catalog covers. **This is the clearest place where the
federal and private sides of the catalog interact, and it is the single most actionable
cross-product finding here.** **[R]** for the recommendation; **[C]** for the 0.8923.

---

## 8. LEVER 5 — PREVENTED PLANTING

### 8.1 The rule

Basic Provisions 26-BR §17(b), **verbatim**: **[V]**

> "(b) The actuarial documents may contain additional levels of prevented planting coverage that you
> may purchase for the insured crop:
> (1) Such purchase must be made on or before the sales closing date.
> (2) If you do not purchase one of those additional levels by the sales closing date, you will
> receive the prevented planting coverage specified in the Crop Provisions.
> (3) If you have a Catastrophic Risk Protection Endorsement for any crop, the additional levels of
> prevented planting coverage will not be available for that crop.
> (4) **You cannot increase your elected or assigned prevented planting coverage level for any crop
> year if a cause of loss that could prevent planting (even though it is not known whether such
> cause will actually prevent planting) has occurred during the prevented planting insurance
> period** … and prior to your request to change your prevented planting coverage level."

§17(c): **[V]**

> "The premium amount for acreage that is prevented from being planted will be the same as that for
> timely planted acreage…"

And the payment calculation, §17: "Multiplying the prevented planting coverage level [percentage] by
the production guarantee…". The base coverage factor lives in each crop's Crop Provisions (55 percent
for corn, 60 percent for soybeans and wheat, by long-standing practice — **not verified here**).

### 8.2 The computed finding

**The prevented-planting buy-up (`PF`, "+5%") exists in RY2026 for only six row crops — Barley,
Canola, Dry Peas, Oats, Rye and Wheat — and does NOT exist for corn, soybeans, cotton, grain
sorghum, rice, peanuts, sunflowers, dry beans or flax.** **[C]** Zero `PF` rows in A01060 for
corn or soybeans against 42,462 for wheat. Note also that the RY2026 option list contains only
`PF` "Prevented Planting +5%" — there is no +10 percent option code at all. **[C]**

Where it exists, the option rate is **1.02 to 1.06, mean 1.0258, multiplicative** — a 2.6 percent
premium surcharge on the whole policy for a 5-percentage-point lift in the prevented-planting
coverage factor. **[C]** For a wheat crop with a 60 percent base PP factor, that is a **+8.3 percent
increase in the prevented-planting guarantee for a +2.6 percent increase in total premium**, of
which the producer pays `(1 − s)`.

**Direction and magnitude: strongly positive, small, and only available on small-grain acres.** **[R]**
On ground with any real prevented-planting history it is close to a free option; §17(b)(4) is the
binding constraint — you must elect it at sales closing, before the wet spring you are worried
about. Any tool that surfaces this must surface it in the fall.

**Who it does not help:** corn and soybean producers, at all, because the election no longer exists
for them; and anyone with CAT coverage, per §17(b)(3).

---

## 9. LEVER 6 — PRACTICE AND TYPE SPLITS, AND WRITTEN AGREEMENTS

### 9.1 Irrigated vs non-irrigated

Two separable effects, both computed from A01010 at the 65 percent reference level, RY2026, RP,
comparing irrigation practice 002 (irrigated) against 003 (non-irrigated) within the same county
and type. **[C]** — `scripts/analysis/practice_split.py`. 17,579 county-type pairs where both exist.

**RMA does not differentiate them everywhere.** The reference amount and reference rate are byte-
identical for 53 percent of corn county-types and 51 percent of wheat county-types — in Champaign
County IL, for instance, irrigated and non-irrigated corn share `212 bu / 0.0078 / −1.593 / 0.0051`
exactly. Restricting to the county-types where the ADM actually differentiates:

| Crop | county-types | median county reference-yield lift (irr ÷ non-irr) | median rate ratio | **median gross premium per acre ratio** |
|---|---|---|---|---|
| Corn | 2,779 | **1.483** | **0.429** | **0.705** |
| Soybeans | 4,728 | 1.258 | 0.584 | 0.756 |
| Cotton | 591 | 1.549 | 0.490 | 0.840 |
| Grain Sorghum | 768 | 1.263 | 0.636 | 0.877 |
| Wheat | 1,342 | 1.421 | 0.721 | 1.039 |

**Where RMA distinguishes them, irrigated corn carries 48 percent more liability per acre at 57
percent less rate — a 30 percent LOWER gross premium per acre than non-irrigated corn in the same
county.** That is a very large effect and it is not a lever the producer can pull by election; it is
a fact about which ground gets reported under which practice, and reporting practice truthfully is
non-negotiable (§1).

**What *is* a lever** is the unit consequence, and it cuts both ways: §34(c)(2) allows separate
optional units by irrigation practice, and §34(a)(2)(v) allows separate enterprise units by
irrigation practice. The first is usually worth taking; **the second is usually not** — the `EP`
experience in §4.5 (0.653 per producer dollar vs plain EU's 1.419) is the measurement.

### 9.2 Type splits

Within Champaign County IL corn alone, RY2026 carries six commodity types with **materially different
reference amounts and rates**: type 016/341/382 at 212 bu and 0.0078, type 381 at 201 bu and 0.0080,
type 739 at 148 bu and 0.0101, type 383 at 123 bu and 0.0121. **[C]** And different projected prices:
$4.62 for grain types, $6.47 for type 739, $7.30 for several types under practice 702/713. **[C]**
The `Rate Differential Factor` by coverage level is identical across all six practices in that
county, so the type choice is a pure liability-and-base-rate question, orthogonal to coverage level.
**[C]**

`ET` (EU by Type) is offered for wheat, dry beans, dry peas and sunflowers at an option rate of
1.0000. **[C]**

### 9.3 Written agreements

Basic Provisions §18 governs written agreements; A01040 and A01010 both carry `WA Number` and
`WA Land ID` columns, and §34(a)(2)(i)(F) explicitly counts "two or more units established by
written agreement" toward enterprise-unit qualification. **[V]** So a written agreement is a genuine
route to an enterprise unit for a producer whose ground does not otherwise meet the two-parcel test.

I excluded all `WA Number`-bearing rows from the computations in this document because they are
producer-specific rather than county-general. **I did not quantify the written-agreement lever.**
It is the biggest un-analyzed item here: written agreements can establish insurability, yields,
practices and units on ground the actuarial documents do not cover, and the ADM carries the rows.
Flagged as open item 4.

---

## 10. THE LAYER ABOVE — county endorsements, where 2026 changed the ranking

These are elections a row-crop producer makes on the same application and they now carry the highest
subsidy rate in the program. RY2026 ADM subsidy percentages: **[C]**

| Plan | Coverage levels offered | **Subsidy** |
|---|---|---|
| SCO-YP / SCO-RP / SCO-RPHPE | 0.50 – 0.85 (attaches at the underlying level) | **80%** |
| ECO-YP / ECO-RP / ECO-RPHPE | 0.90, 0.95 | **80%** |
| STAX-RP / STAX-RPHPE (cotton) | 0.75 – 0.90 | **80%** |
| MCO-YP / MCO-RP / MCO-RPHPE | 0.90, 0.95 | **80%** |
| PACE-YP / RP / RPHPE | 0.75 / 0.80 / 0.85 / 0.90 | 60 / 51 / 41 / 41% |
| MP / MP-HPO | 0.70 – 0.95 | 59 / 55 / 55 / 49 / 44 / 44% |

**SCO, ECO, STAX and MCO are all at 80 percent for RY2026** — up from 65 percent (SCO) and
44–51 percent (ECO) previously, per the 2025 act. **[C]** for the ADM values, **[V]** for the
statutory change.

**This changes the whole ranking of the marginal coverage dollar.** From §5.2, an optional-unit
producer's 80 → 85 percent step costs 12.4 cents of producer money per dollar of liability, at a
41 percent subsidy. The county band immediately above — 86 percent to 90 or 95 percent, via SCO then
ECO — is subsidized at **80 percent**. **The cheapest marginal coverage in the 2026 program is not at
the top of the individual policy; it is in the county layer above it.** **[C]**/**[R]**

The price is basis: SCO and ECO trigger on the *county* revenue or yield, not the farm's. A producer
whose farm moves with the county gets cheap coverage; a producer whose farm does not gets a lottery
ticket. **That is the same spatial-correlation question as the enterprise unit (§4.3), one level
coarser — and a producer who answered "yes, my losses are my county's losses" for the enterprise unit
has already answered it for SCO/ECO.** These two decisions should be made together and no tool I know
of presents them together. **[R]**

*(A full treatment of SCO/ECO/STAX belongs in its own pass; `src/drpopt.py`'s architecture — enumerate
the rate cells, price from RMA's own draws — applies directly, and A01130/A01135 AreaCoverageLevel
and AreaRate are already in `data/cache/adm/`.)*

---

## 11. RANKING

By expected value to the producer, holding risk appetite fixed. "Size" is the magnitude of the effect
on expected return per producer dollar; "confidence" is how well I established it.

| # | Lever | Direction | Size | Who it helps | Who it does not | Confidence |
|---|---|---|---|---|---|---|
| 1 | **Enterprise unit instead of optional** | ↑↑↑ | Producer premium **halves** (0.0249 vs 0.0504 per $ liability); net per producer $ 1.353 vs 0.769 | Anyone whose losses are broadly correlated across their county acreage; large operations; the capital-constrained | Producers with genuinely independent fields (irrigated + dryland, widely separated ground); anyone whose historical losses were single-field | **[C]** high — 15 yrs, 1,642 matched cells |
| 2 | **Move to the top of your subsidy band** | ↑↑↑ | EU at 70% → 75%: +$49/ac liability for +$0.48/ac premium (0.97 ¢ per added $) | Every enterprise-unit producer below 75%; every OU/BU producer at 0.50, 0.55 or 0.65 | Nobody — this is dominance, not preference | **[C]** high — arithmetic on the ADM subsidy table |
| 3 | **Elect YE, yield substitution, TA, yield cup** | ↑↑ | Guarantee lift at **zero rate charge**; expected indemnity rises more than proportionally for YE and substitution | Anyone with a county-declared disaster year in their database, or a genuinely trending yield | Producers whose database is already at their true capability (TA becomes a pure scale-up, still not harmful) | **[V]** rule + **[C]** rates; **[R]** on magnitude |
| 4 | **The county layer (SCO/ECO/STAX) at 80% subsidy** | ↑↑ | The cheapest marginal coverage dollar in the 2026 program | Producers whose yields track their county | Producers with high individual-to-county basis — for them it is a lottery ticket | **[C]** subsidy; **[R]** on the ranking |
| 5 | **RP vs RPHPE** | context-dependent | RP costs 30–70% more; subsidized identically; pays only on {short crop} ∧ {price rally} | Forward-sellers; high-volatility-factor years (wheat 0.21, sunflowers 0.22) | Producers who market only after harvest; low-volatility crops (cotton 0.06) | **[V]** mechanism; **[C]** cost ratio with selection caveat |
| 6 | **Basic instead of optional units** | ↑ | Same subsidy, same rate discount factor as EU, 80% of the OU producer rate; realized 1.009 vs 0.769 per producer $ | Producers who cannot meet §34(b)(3)–(4) optional-unit recordkeeping anyway | Producers whose losses genuinely are field-by-field | **[C]** result, **[R]** interpretation — selection not controlled |
| 7 | **Hail & Fire Exclusion + private crop-hail** | ↑ | 10.8% federal gross premium credit (`HF` = 0.8923) | Counties where private crop-hail is cheaply priced | High-hail counties where the private rate exceeds the credit | **[C]** the factor; **[R]** the trade |
| 8 | **Multi-County enterprise unit (`MC`)** | ↑ | Free (rate 1.0000) and moves you down the size-discount curve | Producers straddling a county line | Single-county operations | **[C]** |
| 9 | **Prevented-planting buy-up (`PF`)** | ↑ | +5 pts of PP factor for a 2.6% premium surcharge | Wheat, barley, oats, canola, rye, dry pea growers on wet ground | **Corn and soybean growers — the election no longer exists**; CAT holders | **[C]** availability and rate; **[V]** the rule |
| 10 | **Splitting an EU by practice (`EP`/`EC`)** | **↓↓** | Realized 0.653 (EP) and −0.286 (EC) per producer $, vs plain EU's 1.419 | Almost nobody | Almost everybody — this is a **negative** lever presented as a feature | **[C]** high |

**Biggest structural edge:** the same as LRP and DRP — **the subsidy is the entire edge, and it is a
step function while expected indemnity is continuous.** For RY2026 enterprise units the step is flat
from 50 to 75 percent, so **five of eight coverage levels are strictly dominated** and moving to the
top of the flat band is free liability. That is the single most valuable derivable fact in the
program and it follows from the subsidy schedule alone.

**Biggest corrective:** the naive reading of "enterprise units carry a far higher subsidy" overstates
the case in dollars. In matched cells over 15 years the enterprise unit's *net dollars per acre*
($17.36) barely beat optional units ($16.89) and lost to basic units ($18.59). **The enterprise
advantage is 76 percent better return on premium capital, not more money.** A tool that ranks on net
dollars will not pick it; a tool that ranks on net per premium dollar will. Say which objective you
are optimizing.

**Biggest surprise:** basic units. Same subsidy as optional, same rate-discount factor as enterprise
(in ADM record category 04, verified on 100 percent of rows), 80 percent of the optional-unit
producer rate, and the best realized net dollars per acre of any structure. Worth a proper controlled
study.

---

## 12. What is computed, what is cited, what is reasoned

**Computed [C]** — all from RMA's own published files, scripts in `scripts/analysis/`:

- The RY2026 subsidy schedule by coverage level × unit structure × plan (A00070).
- The pre-2026 schedule, recovered empirically as `subsidy ÷ premium` from 15 years of SOBTPU, and
  hence the exact per-level size of the 2026 increase.
- The coverage-level rate curve (`Rate Differential Factor`) for nine row crops, 3.9 million rows.
- Unit residual factors and unit discount factors, including the BU ≡ EU identity in record
  category 04.
- Option rates for TA, YE, YA, YC, MC, HB, HF, PF, PY, EI, ET, EC — the finding that the
  yield-history tools are all exactly 1.0000 and that PF does not exist for corn or soybeans.
- Loss ratios, subsidy percentages, producer rates and net returns by unit structure and coverage
  level, 2010–2024, including the 1,642-cell matched EU-vs-OU panel.
- Unit-structure availability across all 543,342 RY2026 row-crop offers.
- Irrigated-vs-non-irrigated reference yields and rates.
- Projected prices, harvest prices and price volatility factors for RY2026.

**Cited [V]** — Basic Provisions 26-BR §17, §27, §34 and the unit definitions; CIH FCIC-18010-1
¶923.P/Q/R and ¶1606; 7 U.S.C. 1508(e)(2) and (e)(5); the 2024 SRA §III(a)(4); RMA's agent
compensation FAQ.

**Reasoned [R]** — the economic interpretation of why YE and substitution add expected value while TA
may only scale; the recommendation that the hail/fire exclusion be traded against private crop-hail;
the claim that SCO/ECO now dominate the top of the individual ladder on subsidy grounds; the
whole-farm-unit rate path; the basic-unit interpretation.

### Data that would settle the open questions empirically

1. **RMA Cost Estimator validation of §2.2.** The premium assembly order is my reading of the ADM
   layout, not a quoted RMA formula. Driving `https://ewebapp.rma.usda.gov/apps/costestimator/`
   (ASP.NET WebForms, ViewState-driven, multi-postback) for a handful of known county/crop/coverage
   combinations would convert the absolute dollars in §5.2 from illustrative to verified. **This is
   the highest-value verification available and it is a scraping job, not a modelling job.**
2. **The whole-farm-unit rate path.** `Whole Farm Unit Residual Factor` is 1.0000 in every row-crop
   cell and A01090 has no whole-farm column. Either RMA computes WFU premium as a sum of
   enterprise-unit premiums, or there is a table I did not pull. Resolve from the CIH premium
   exhibit or a Cost Estimator quote.
3. **RMA's revenue simulation for RP vs RPHPE.** All components are in hand: A01020 Beta
   (500 standardized draw pairs × 404 beta IDs), A01030 ComboRevenueFactor (Base Rate, Mean,
   Standard Deviation by commodity × state), A00810 `Price Volatility Factor`. The transform from
   standardized draws to a joint yield-price distribution is **not published** — exactly the same
   gap as DRP's draw transform (`producer_decision_research.md` §4.3 step 3). Validate against a real
   agent quote before trusting any reconstruction.
4. **Written agreements.** Not quantified. A01010/A01040 carry `WA Number` and `WA Land ID`; §34(a)(2)(i)(F)
   makes written-agreement units count toward enterprise qualification.
5. **A controlled basic-vs-optional study.** The §4.4 result needs unit-size and farm-size controls
   before it can be acted on. SOBTPU does not carry acreage per unit; the RMA Cause of Loss files
   might allow partial control.
6. **TA yield-adjustment factors by county.** `Historical Yield Trend ID` is blank on every row-crop
   offer, so the per-county trend factor is not in the ADM tables pulled here. It is published in
   the county actuarial documents (A01200 DocumentBuilder / A01210 Statement, 1.6 GB + 5.5 MB).
7. **Beginning/veteran/first-time farmer tiers.** The +5/+5/+3/+1 point additions do not appear in
   A00070; find where RMA applies them.

---

## 13. Reproduction notes

Everything marked **[C]** came from these sources, all reachable by the repo's existing connectors:

**ADM RY2026**, `https://pubfs-rma.fpac.usda.gov/pub/References/actuarial_data_master/2026/2026_ADM_YTD.zip`,
range-extracted member-by-member using `src/connectors/rma_adm.py`'s `http_range_zip` /
`RangeZip.extract` (helper: `scripts/analysis/adm_pull.py`). Members used, with uncompressed sizes:

```
A00030 InsuranceOffer            362 MB   unit-allowed flags, Unit Discount ID, Beta ID
A00070 SubsidyPercent            0.06 MB  THE subsidy schedule
A00420 Commodity / A00460 Plan   small    code lookups
A00570 InsuranceOption           small    option-code names (resolved `DC` = Downed Commodity)
A00810 Price                    1,106 MB  projected/harvest price, price volatility factor
A01010 BaseRate                   134 MB  reference amount/rate, exponent, fixed rate
A01020 Beta                        13 MB  500 standardized yield/price draw pairs × 404 IDs
A01030 ComboRevenueFactor         278 MB  revenue-rating parameters by commodity × state
A01040 CoverageLevelDifferential 2,706 MB rate differential + unit residual factors
A01060 OptionRate               1,217 MB  TA / YE / YA / YC / PF / HF / MC / HB / EI / ET / EC rates
A01090 UnitDiscount              0.57 MB  BU / EU / OU discount factors by acres × coverage level
A01105 YieldExclusion             108 MB  eligible YE years by offer
A01115 HistoricalYieldTrend        44 MB  county yield trend series
```

**Summary of Business — Type/Practice/Unit Structure**, 2010–2024:
`https://pubfs-rma.fpac.usda.gov/pub/Web_Data_Files/Summary_of_Business/state_county_crop/sobtpu_{year}.zip`
(~5–8 MB each; layout in `SOBTPU_External_All_Years.pdf`, 27 pipe-delimited positional fields, no
header row). **Note: `sobtpu_2010.zip` failed its first download with a truncated central directory
and needed a re-fetch — validate the zip before parsing.** This file is the single most useful
public dataset for this problem and the repo does not currently load it; `src/connectors/rma_sob.py`
loads only `sobcov_<year>.zip`, which lacks unit structure and coverage level.

**Documents:** Basic Provisions 26-BR
(<https://www.rma.usda.gov/sites/default/files/2025-11/Basic-Provisions-26-BR.pdf>) and
CIH FCIC-18010-1, August 2025
(<https://www.rma.usda.gov/sites/default/files/2025-08/2026-18010-1-Crop-Insurance-Handbook.pdf>).
The CIH download truncates repeatedly over HTTP/2; use `--http1.1` and verify the page count.

**Scripts** (all throwaway research helpers, none imported by the app):

```
scripts/analysis/adm_pull.py         range-extract ADM YTD members
scripts/analysis/scan_offers.py      A00030 -> unit flags, unit-discount IDs, trend/beta flags
scripts/analysis/scan_cld.py         A01040 -> RDF/URF aggregates + benchmark-county detail
scripts/analysis/scan_optrate.py     A01060 -> option rates by crop
scripts/analysis/scan_price.py       A00810 -> projected/harvest price, volatility
scripts/analysis/scan_trend.py       A01115 -> county yield trend (returns empty for row crops)
scripts/analysis/scan_sobtpu.py      SOBTPU -> crop x plan x coverage x unit aggregate
scripts/analysis/scan_sobtpu_state.py  same, keeping state, for matched-cell panels
scripts/analysis/sob_report.py       loss ratios / net per producer dollar
scripts/analysis/cov_ladder.py       coverage x unit ladder, relative units
scripts/analysis/worked_example.py   Champaign IL corn, $/acre
scripts/analysis/practice_split.py   irrigated vs non-irrigated
```

Intermediate JSON and the SOBTPU zips live in this session's scratchpad, not in the repo.
