# The Row-Crop Endorsement / Supplemental Layer, 2026

**What this is.** An analysis of the products that stack *on top of* an underlying federal
row-crop policy: SCO, ECO, MCO, STAX, MP/MP-HPO, PACE, HIP-WI and WFRP, plus the 508(h)
privately-developed products in this repo's `products` table. It answers four questions —
what band each product covers and what triggers it, which stacks are legal together, where
the best expected return per producer dollar is, and how much basis risk the area-triggered
products carry.

**Crop year.** 2026 throughout. This matters more than usual: the *One Big Beautiful Bill
Act* (P.L. 119-21, enacted 2025-07-04) changed this layer substantially, and it changed it
**again** between 2026 and 2027. Most published RMA fact sheets are stale. Section 2 is
the reconciliation.

---

## 0. Scope boundary

**The subject is choosing legally among endorsements a producer is entitled to elect.**
Every rule below is an eligibility rule with a citation, and the whole exercise is
optimisation inside those rules.

Misreporting acres, yields, practices, shares, FSA farm serial numbers, ARC/PLC enrollment
status or irrigation practice is **fraud**, not a strategy, and it is nowhere considered
here as an option. The policies themselves make the point: STAX voids the acreage and still
charges 60% of premium for misreported ARC/PLC status
(23-STAX-0021 §4(g)), and SCO did the same
(20-SCO §4(b)(2)). Beyond the contractual penalty this is 18 U.S.C. 1014/1040 territory.

Nothing here is individualised financial, tax, legal or insurance advice. Coverage
availability is county-specific and lives in the Actuarial Documents; every figure below
that describes an individual producer's offer must be confirmed against the Actuarial
Information Browser for that state, county, crop, type and practice.

---

## 1. What is actually being sold

Computed from this repository's `sob_sales` table (RMA Summary of Business, `sobcov_2026`
pull; `data/catalog.db`), by `scripts/analysis/endorsement_economics.py`.

Definitions used throughout: **producer premium** = `total_premium − subsidy`;
**producer cost per $1 of liability** = producer premium / liability; **premium rate** =
total premium / liability, which is RMA's estimate of expected indemnity per dollar of
liability.

| plan | family | trigger | liability | acres (m) | $ liab/ac | premium rate | subsidy | **producer $ per $1 liab** | producer $/ac |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ECO-RP | ECO | AREA (county) | $6.11bn | 99.80 | 61.23 | 47.2% | 80.5% | **0.0922** | 5.64 |
| SCO-RP | SCO | AREA (county) | $3.33bn | 56.77 | 58.72 | 25.6% | 80.4% | **0.0502** | 2.95 |
| WFRP | WFRP | INDIVIDUAL (whole farm) | $2.57bn | n/a | n/a | 8.2% | 68.2% | **0.0260** | n/a |
| HIP-WI | HIP-WI | INDEX (wind) | $962.6m | 6.74 | 142.91 | 20.2% | 80.3% | **0.0398** | 5.69 |
| MP-HPO | MP | AREA (county margin) | $285.7m | 0.27 | 1056.40 | 5.8% | 44.3% | **0.0326** | 34.43 |
| MCO-RP | MCO | AREA (county margin) | $119.7m | 1.89 | 63.36 | 51.5% | 80.4% | **0.1008** | 6.38 |
| SCO-YP | SCO | AREA (county) | $69.9m | 0.74 | 94.73 | 9.3% | 80.1% | **0.0186** | 1.76 |
| ECO-YP | ECO | AREA (county) | $59.2m | 1.01 | 58.65 | 25.0% | 80.2% | **0.0495** | 2.90 |
| ECO-RPHPE | ECO | AREA (county) | $32.2m | 0.38 | 84.80 | 34.2% | 80.4% | **0.0672** | 5.70 |
| MP | MP | AREA (county margin) | $20.8m | 0.02 | 888.43 | 3.9% | 44.6% | **0.0216** | 19.19 |
| STAX-RP | STAX | AREA (county) | $17.2m | 0.19 | 90.24 | 44.0% | 80.0% | **0.0881** | 7.95 |
| SCO-RPHPE | SCO | AREA (county) | $12.4m | 0.22 | 56.82 | 13.5% | 80.5% | **0.0262** | 1.49 |
| MCO-RPHPE | MCO | AREA (county margin) | $0.5m | 0.00 | 129.22 | 34.9% | 83.3% | **0.0582** | 7.51 |
| MCO-YP | MCO | AREA (county margin) | $0.1m | 0.00 | 81.72 | 19.3% | 80.0% | **0.0385** | 3.15 |
| PACE-RP | PACE | INDIVIDUAL (unit) | $0.1m | 0.00 | 48.55 | 6.6% | 44.1% | **0.0368** | 1.79 |
| STAX-RPHPE | STAX | AREA (county) | $0.0m | 0.00 | 72.00 | 45.6% | 80.0% | **0.0912** | 6.56 |
| **TOTAL** | | | **$13.59bn** | **168.02** | | | 79.7% | **0.0637** | |

Family roll-up:

| family | liability | share of layer | producer premium | producer $ / $1 liab | realized subsidy | policies |
|---|---:|---:|---:|---:|---:|---:|
| ECO | $6.20bn | 45.6% | $568.3m | 0.0916 | 80.5% | 521,821 |
| SCO | $3.42bn | 25.1% | $169.0m | 0.0495 | 80.4% | 303,402 |
| WFRP | $2.57bn | 18.9% | $66.6m | 0.0260 | 68.2% | 1,703 |
| HIP-WI | $962.6m | 7.1% | $38.3m | 0.0398 | 80.3% | 73,446 |
| MP | $306.5m | 2.3% | $9.8m | 0.0319 | 44.3% | 1,779 |
| MCO | $120.4m | 0.9% | $12.1m | 0.1005 | 80.4% | 8,847 |
| STAX | $17.2m | 0.1% | $1.5m | 0.0881 | 80.0% | 6,523 |
| PACE | $0.1m | 0.0% | $0.0m | 0.0368 | 44.1% | 21 |

Three things to read off this immediately.

1. **The realized subsidy share equals the statutory rate.** SCO/ECO/MCO/STAX/HIP-WI all
   come in at 80.0–80.5% against a statutory 80% (§3). That is a clean cross-validation of
   the SoB against the ADM and confirms the OBBBA subsidy increase is live in 2026 pricing.
   MP at 44.3% confirms MP buyers are almost all at the 90–95% coverage levels, where MP's
   subsidy factor is 0.44.
2. **ECO's premium rate (47.2%) is nearly double SCO's (25.6%).** That is not a markup —
   it is the band. ECO sits from 86% up to 95% of expected county revenue, which is
   in-the-money territory; SCO sits below 86%.
3. **The whole layer costs producers $866m for $13.59bn of liability** — 6.4 cents per
   dollar of coverage, against a 79.7% average subsidy.

### 1.1 Why ECO carries roughly twice SCO's liability

Decomposed on the RP variants (same script, Table 2). Liability = acres × liability/acre,
so the 1.83× gap must come from one or the other:

| | SCO-RP | ECO-RP | ratio |
|---|---:|---:|---:|
| county×crop cells with sales | 7,244 | 7,319 | 1.01× |
| policies sold | 296,002 | 512,587 | **1.73×** |
| net acres | 56,766,018 | 99,795,125 | **1.76×** |
| liability | $3.33bn | $6.11bn | 1.83× |
| liability per acre | $58.72 | $61.23 | **1.04×** |
| premium rate | 0.2562 | 0.4721 | 1.84× |
| producer $ per $1 liability | 0.0502 | 0.0922 | 1.84× |

`1.758 (acres) × 1.043 ($/acre) = 1.833×`, exactly the observed liability ratio.

**So the answer is uptake, not band width.** ECO is elected on 1.76× the acres. Liability
per acre is within 4%. And the offer footprints are effectively identical — the ADM
(`A00030 InsuranceOffer`, 2026) shows 175,240 live offers for both SCO-RP (plan 32) and
ECO-RP (plan 88), with matching crop lists. Availability explains none of it.

Four causes, in descending order of confidence:

- **ECO is full-size for a high-coverage producer; SCO is a sliver.** ECO's band is a fixed
  86%→95% (9 points) regardless of the underlying level. SCO's band is
  `86% − underlying coverage level`. For a producer at 85% RP — the modal Corn Belt
  election — SCO is **one coverage point wide**. There is very little to buy. This is
  structural and permanent.
- **The relative price cut was much larger for ECO.** OBBBA raised ECO's subsidy from
  0.44 (revenue plans) / 0.51 (yield plans) to 0.80, cutting the producer's share of premium
  from 56% to 20% — a **64% price cut**. SCO went 0.65→0.80, cutting the producer share from
  35% to 20% — a **43% price cut**. Same direction, very different magnitude.
- **RMA explicitly routed 2026 business into ECO.** MGR-25-006 (2025-08-20): *"RMA will
  update the SCO policy for the 2027 crop year to increase the maximum coverage level from
  86 to 90 percent. For the 2026 CY, insureds can cover this band of insurance with ECO and
  will receive the same 80 percent premium subsidy on their ECO coverage that is now offered
  for SCO. This will functionally allow producers to access SCO coverage up to the 90
  percent level for the 2026 crop year."*
- **ARC legacy.** Through CY2025, ARC-elected acreage was barred from SCO but never from
  ECO. The bar was repealed for 2026 (§2), but 2026 is the first year and elections were
  made within months of the August 2025 bulletin. Some of the acre gap is a habit that has
  not caught up yet — and is therefore the part most likely to close.

### 1.2 The band, measured rather than quoted

`scripts/analysis/implied_band_width.py` divides SoB liability-per-acre by the ADM's
`Expected Revenue Amount` (`A00810 Price`) for the same state × county × commodity × plan.
The quotient is the insured band in coverage points, derived without reference to any fact
sheet.

| plan | cells | acres (m) | p25 | median | acre-wt mean | p75 |
|---|---:|---:|---:|---:|---:|---:|
| ECO-RP | 5,816 | 99.77 | 7.5p | **8.6p** | 8.9p | 9.1p |
| ECO-RPHPE | 405 | 0.38 | 8.5p | 9.1p | 8.9p | 9.4p |
| SCO-RP | 5,448 | 55.99 | 6.3p | **7.9p** | 10.1p | 9.9p |
| SCO-RPHPE | 228 | 0.22 | 1.5p | 4.8p | 5.6p | 6.3p |
| MCO-RP | 824 | 1.89 | 10.2p | **10.8p** | 10.9p | 11.4p |
| STAX-RP | 156 | 0.17 | 26.5p | 33.0p | 34.3p | 40.0p |

ECO-RP measures 8.6–8.9 points against a maximum possible 9 (86→95). **This independently
confirms that ECO still attaches at 86% in 2026** — had ECO moved to a 90% attachment its
maximum band would be 5 points — and implies roughly 86% of ECO acres elect the 95% trigger
rather than 90%.

SCO-RP measures 7.9 points at the median, implying a weighted-average underlying coverage
level near 78% among SCO buyers, with a long left tail (acre-weighted mean 10.1 points) from
lower-coverage wheat, sorghum and pulse elections.

**The STAX and cotton rows in this table are not trustworthy** — STAX measures 33 points
against a structural maximum of 20 points × 1.20 protection factor = 24. The cotton
`Expected Revenue Amount` in A00810 does not line up with the SoB liability basis for
cotton (lint vs. lint-plus-seed, and ELS/upland commodity-code splits). Cotton figures from
this method are excluded from every conclusion below.

---

## 2. The 2026 regime change — read this before anything else

The *One Big Beautiful Bill Act* (P.L. 119-21, 2025-07-04) rewrote this layer. RMA
implemented it through **MGR-25-006** (2025-08-20, Administrator Patricia Swanson) with
attachment **25-OBBA, "One Big Beautiful Amendment"**, effective *"for all policies with a
sales closing date (SCD) on or after July 1, 2025"* — i.e. the whole 2026 crop year.

Three changes, and one non-change that is constantly reported wrong:

**(a) Subsidy 65% → 80%, extended to the whole area-endorsement family.** MGR-25-006:

> "(2) SCO, ECO, MCO, HIP-WI, FIP-SI - The premium subsidy rate for the Supplemental
> Coverage Option (SCO) has increased from 65 to 80 percent. This increase will also be
> applied to similar coverages to SCO. These are the Enhanced Coverage Option (ECO), the
> Margin Coverage Option (MCO), the Hurricane Insurance Protection Wind Index (HIP-WI), and
> the Fire Insurance Protection Smoke Index (FIP-SI)."

Statutory basis, OBBBA §10502(b): *"Section 508(e)(2)(H)(i) of the Federal Crop Insurance
Act (7 U.S.C. 1508(e)(2)(H)(i)) is amended by striking ``65'' and inserting ``80''."*
Note the statute amends only the SCO subsection; RMA extended the rate to ECO/MCO/HIP-WI/
FIP-SI administratively as *"similar coverages to SCO."* The 2026 ADM confirms the result —
`A00070 SubsidyPercent` returns 0.800 for every coverage level of plans 31/32/33 (SCO),
35/36 (STAX), 37 (HIP-WI), 67/68/69 (MCO) and 87/88/89 (ECO).

**(b) THE ARC BAR ON SCO IS GONE.** This is the single most important correction in this
document, and it reverses the conventional wisdom.

The old rule, verbatim from **20-SCO §5(a)**:

> "(a) All planted acreage of the crop in the county that is insured by the underlying
> policy must be insured under this Endorsement, except this Endorsement will not insure:
> (1) Acreage that is designated as covered by STAX; or
> (2) Acreage on land identified by a FSA farm serial number for which ARC has been elected
> for the crop."

and the **2026 Crop Insurance Handbook, FCIC-18010 (06-2025), ¶916J**, which set the level
at which the bar operated:

> "ARC is elected on an FSA crop/FN basis and SCO is elected on a crop/county basis.
> Benefits cannot be received for both ARC and SCO on the same acreage/FN(s) of the crop.
> If these elections have been made, the insured is required to report which acreage/FN(s)
> of the crop are covered under the SCO Endorsement and which acreage/FN(s) of the crop
> have elected ARC. If ARC has been elected on the acreage/FN(s) the same acreage/FN(s) of
> the crop are ineligible for SCO coverage regardless, of ARC enrollment status."

Note: the bar operated at the **FSA farm serial number × crop** level, not policy-wide and
not acre-by-acre; ARC **election** triggered it *"regardless of ARC enrollment status"*;
and PLC never triggered it.

The repeal, **OBBBA §10303(b)**:

> "Section 508(c)(4)(C)(iv) of the Federal Crop Insurance Act (7 U.S.C. 1508(c)(4)(C)(iv))
> is amended by striking ``Crops for which the producer has elected under section 1116 of
> the Agricultural Act of 2014 to receive agriculture risk coverage and acres'' and
> inserting ``Acres''."

The surviving statute, **7 U.S.C. 1508(c)(4)(C)(iv)**:

> "**(iv) Ineligible crops and acres** — Acres that are enrolled in the stacked income
> protection plan under section 1508b of this title shall not be eligible for supplemental
> coverage under this subparagraph."

RMA's implementation, **25-OBBA**, which replaces 20-SCO §5(a) with:

> "All planted acreage of the crop in the county that is insured by the underlying policy
> must be insured under this Endorsement, except this Endorsement will not insure acreage
> that is designated as covered by STAX."

and removes §5(a)(1) and (2), reserves §4 entirely, strikes *"or the Agriculture Risk
Coverage (ARC) program"* from the introductory paragraph, and directs *"Replace all
references to premium subsidy rates of 65% (0.65) with 80% (0.80) in the examples."*

**MGR-25-006** states the operational effect:

> "(3) Additional SCO Changes: Insureds can now purchase the SCO regardless of their Area
> Risk Coverage (ARC) elections with the Farm Service Agency. Insureds will no longer need
> to report acreage for their SCO policy under which ARC is elected."

Confirmed downstream: the 2027 CIH ¶916A now reads *"...excluding acreage insured under
STAX,"* ¶916J is deleted, and the 2027 handbook contains zero occurrences of "Agriculture
Risk Coverage." 27-SCO's Summary of Changes: *"Removed restriction on purchasing this
Endorsement with the Agriculture Risk Coverage (ARC) program."*

**Consequence: for the 2026 crop year the SCO-vs-ARC joint optimisation described in most
extension material no longer exists.** ARC-CO, ARC-IC and PLC are all neutral to SCO
eligibility. A producer who declined SCO in order to keep ARC is, from 2026, giving up
coverage for nothing. Note carefully that this does **not** transfer to STAX — see §4.

**(c) WFRP maximum coverage level 85% → 90%.** Confirmed in the ADM: `A00070` returns a
0.90 coverage level for plan 76, carrying the 85% level's 0.56 subsidy.

**(d) The non-change: the SCO cap is still 86% in 2026.** OBBBA §10502(a)(2)(B) struck "86"
and inserted "90" in 7 U.S.C. 1508(c)(4)(C)(iii), but RMA did not implement it until 2027.
MGR-25-006 is explicit (quoted in §1.1 above), as is the RMA news release of 2025-08-20:
*"SCO coverage will also expand to a coverage level of 90% (from 86%). Producers will have
access to this option in 2026 via the ECO product... USDA will then change the SCO policy
for the 2027 crop year."* 27-SCO §1 for CY2027: *"The area loss trigger is 90 percent."*

This is why the ECO band measured in §1.2 comes out at 8.6–8.9 points and not 5.

> **Do not cite RMA's SCO fact sheet for 2026.** The only one RMA publishes is dated
> January 2022 and still says *"The Federal Government pays 65 percent of the premium cost
> for SCO"* and *"Any crop on a farm that you elected to participate in the Agriculture Risk
> Coverage (ARC) program ... is not eligible for SCO coverage."* Both statements are false
> for CY2026. Conversely, **RMA's ECO FAQ is dated July 2026 and describes the CY2027
> structure** (ECO 90→95, SCO 75→90); its band language is wrong for CY2026 even though its
> stacking and ARC answers are correct.

---

## 3. Product by product — band, trigger, subsidy, price

Every eligibility rule below is quoted verbatim from the governing instrument. Subsidy
percentages marked **[ADM]** are computed from `data/cache/adm/2026_A00070_SubsidyPercent_YTD.txt`.

### 3.1 SCO — Supplemental Coverage Option (plans 31 / 32 / 33)

Governing document for CY2026: **20-SCO** (released June 2019), as amended by **25-OBBA**.
There is no 2026-specific SCO endorsement. Statutory home is 7 U.S.C. 1508(c)(4)(C) and
1508(e)(2)(H); SCO is **not** codified in 7 CFR part 457.

**Band.** 20-SCO §1:

> "**Area loss trigger** - The percent of expected area yield or revenue, as applicable,
> below which an indemnity is paid. The area loss trigger is 86 percent."

> "**Supplemental coverage range** - The percent of your expected crop value that can be
> covered by this Endorsement. It is the difference between the area loss trigger and the
> coverage level of the underlying policy, expressed as a whole percentage."

> "**Coverage percentage** - The percentage you choose that is used to calculate the dollar
> amount of insurance under this Endorsement. The maximum coverage is the difference between
> 86 percent and the coverage level selected by you and the coverage percent is multiplied
> by this amount to give you your dollar amount of insurance."

§2(c): *"You may select a coverage percentage, from 50 percent to 100 percent... The default
coverage percentage is 100 percent."*

**Trigger — AREA, and RMA says so in terms.** 20-SCO §9(a):

> "(a) An indemnity is due under this Endorsement if:
> (1) For revenue protection underlying policies, the final area revenue is less than the
> expected area yield multiplied by the higher of the projected price or harvest price and
> by the area loss trigger;
> (2) For revenue protection underlying policies with the harvest price exclusion, the final
> area revenue is less than the expected area revenue multiplied by the area loss trigger; or
> (3) For all other underlying policies, the final area yield is less than the expected area
> yield multiplied by the area loss trigger."

20-SCO §8(b), which is the whole basis-risk argument in RMA's own words:

> "Individual farm yields and revenues are not considered under this Endorsement when
> determining the final area yield and final area revenue: (1) It is possible that your
> individual farm may experience reduced revenue or reduced yield and you do not receive an
> indemnity under this Endorsement."

"Production area" is *"designated generally as a county, but may be a smaller or larger
geographical area as specified in the actuarial documents."*

**Eligibility.** CIH FCIC-18010 (06-2025) ¶916C: *"To be eligible for the SCO Endorsement,
the insured must: (1) have an insurance policy under the CCIP and the applicable CP
(referred to as the underlying policy) from the same AIP as the underlying policy; (2) elect
the SCO Endorsement on or before the SCD for the underlying crop policy; and (3) comply with
all terms and conditions of the SCO Endorsement."* ¶916L: *"The SCO Endorsement is not
available with ARPI."*

**Plan follows the underlying, mechanically.** CIH ¶916E maps YP-01→31, RP-02→32,
RP-HPE-03→33, Yield-Based Dollar Amount-55→31, APH-90→31. And 20-SCO §3(c): *"If you change
the coverage level or plan of insurance of the underlying policy, this Endorsement will
remain in effect and will provide supplemental coverage based on the coverage level and plan
of insurance you selected for the underlying policy."*

**Subsidy: 80% at every coverage level 50%–85% [ADM].** Realized 80.4% in the SoB.
**Producer cost: $0.0502 per $1 of liability, $2.95/acre (SCO-RP).**

### 3.2 ECO — Enhanced Coverage Option (plans 87 / 88 / 89)

Governing document for CY2026: **21-ECO**. FCIC Board approved it under §508(h) on
2020-08-20; the 2026 ADM's own `Private 508H Flag` marks 100% of plan-88/89 offers as `Y`.

**Band.** 21-ECO §1:

> "**Area loss trigger** - The percent of expected area yield or revenue, as applicable,
> below which an indemnity is paid. The area loss trigger is either 95 or 90 percent as
> chosen by you."

> "**ECO coverage range** – The percent of your expected crop value that can be covered by
> this Endorsement. It is the difference between the area loss trigger you select and 86
> percent, expressed as a whole percentage."

§6(a)(1): *"Determine your ECO coverage range by subtracting 86 percent from your selected
area loss trigger."* PM-20-078: *"ECO covers a band from 86 percent (where SCO coverage
ends) up to 90 or 95 percent of expected crop value."*

**Exclusions.** 21-ECO introductory paragraph:

> "The coverage provided by this Endorsement may not be combined with the Stacked Income
> Protection Plan (STAX), Margin Protection, or the Hurricane Insurance Protection-Wind
> Index (HIP-WI) Endorsement on any acreage planted to the insured crop. The coverage
> provided by this Endorsement is only available with an individual plan of insurance that
> insures acreage at an additional coverage level. Insurance will not attach to any acreage
> covered by the Catastrophic Risk Protection Endorsement."

**No ARC restriction, ever.** 21-ECO contains no reference to ARC; 25-OBBA makes no ECO
changes. RMA's ECO FAQ: *"Your choice of ARC has no impact of your eligibility for ECO. If
you elect ECO and ARC for the same crop on a farm, your ECO coverage for that crop on that
farm will be unaffected."*

**ECO does not require SCO.** ECO FAQ: *"Producers may choose to purchase SCO or Stacked
Income Protection Policy (STAX) on acres that are insured under ECO, but are not required to
do so."* And: *"ECO with SCO or STAX are not mutually exclusive because their bands of
coverage do not overlap."* (The STAX half of that sentence is a CY2027 statement — see §4.)

**Subsidy: 80% at both the 90% and 95% triggers [ADM].** Historically it was *not* split by
trigger level but by plan — 21-ECO §12: *"The actuarial documents also contain a premium
subsidy factor of 0.51 for ECO on a Yield Protection underlying policy (producer pays 49%)
and 0.44 for ECO on a Revenue Protection or Revenue Protection HPE underlying policy
(producer pays 56%)."* Realized 80.5% in the SoB.
**Producer cost: $0.0922 per $1 of liability, $5.64/acre (ECO-RP).**

### 3.3 MCO — Margin Coverage Option (plans 67 / 68 / 69), new for 2026

508(h); FCIC Board approved 2024-05-23. **PM-25-029** (2025-04-30):

> "MCO provides a band of insurance from 86 percent up to 95 percent of expected crop value
> to cover producers' operating margins. MCO will be available as an endorsement for corn,
> cotton, grain sorghum, soybeans, rice, and spring wheat for the 2026 and succeeding crop
> years."

**Band, CY2026 — 26-MCO §1:**

> "**Coverage range** – An amount determined by subtracting 0.86 (86 percent) from the
> trigger level you elect for each irrigation practice which can be 0.04 or 0.09 (4 or 9
> percent), unless you have elected STAX ... with an area loss trigger greater than 0.85 (85
> percent), in which case your MCO trigger level must be 95 percent and the MCO coverage
> range is 0.05 (5 percent)."

> "**Trigger level** – Your choice of 0.95 or 0.90 (95 percent or 90 percent) as the point
> at which you become eligible for an indemnity..."

> "**Coverage percentage** – The percentage you choose to calculate the MCO protection under
> this Endorsement that is between 0.50-1.00 (50 to 100 percent)."

For CY2027 this becomes a fixed 90→95 band (27-MCO §1; MCO Handbook FCIC-20700U ¶21.I:
*"For the 2027 crop year, due to the change in percent coverage range to SCO from 86 to 90
percent in the One, Big, Beautiful Bill Act (OBBBA), MCO Endorsements will be electable only
at the 90 to 95 percent coverage range."*).

**What makes it a margin, not a revenue, product.** MCO's input basket (per the MCO FAQ) is
diesel, natural gas, urea, DAP and potash depending on crop — note it uses **natural gas**
where MP uses **interest**; the two margin products do not price the same basket. Not
available for organic: *"MCO is currently not available for organic production due to the
input factors being based off conventional production methods."*

**Subsidy: 80% at both triggers [ADM].** PM-25-029 and the June-2025 MCO FAQ both say 65%;
both predate OBBBA and are superseded — MCO's SCD of 30 September 2025 falls after the
1 July 2025 effective date, so the 80% applies. Current FAQ: *"The Federal Government pays
80 percent subsidy for all MCO policies."* Handbook change log: *"Adjusted premium subsidy
to 80 percent."* Realized 80.4% in the SoB — confirming the increase actually flowed
through.

**Producer cost: $0.1008 per $1 of liability, $6.38/acre (MCO-RP) — the most expensive
per dollar of coverage in the whole layer**, because its band sits highest and its trigger
is a margin, which can be breached by a cost move alone.

**ARC is neutral.** MCO FAQ: *"Your choice of ARC has no impact of your eligibility for MCO."*

### 3.4 STAX — Stacked Income Protection Plan (plans 35 / 36), upland cotton only

Not 508(h) — created by statute (2014 Farm Bill), 7 U.S.C. 1508b, and the 2026 ADM's
`Private 508H Flag` is `N` on 100% of plan-35/36 offers. Governing document:
**23-STAX-0021** (newest RMA publishes).

**Band.** 23-STAX-0021 §1:

> "**Area loss trigger** - The percentage of expected area revenue you choose, ranging from
> 90 percent to 75 percent, below which an indemnity is paid and which is contained in the
> actuarial documents."

> "**Coverage range** - A percentage of not less than 0 percent and not more than 20
> percent, which represents the amount of the expected area revenue covered by STAX..."

§5(a): *"You must choose a protection factor: (1) From a range of 80 percent to 120
percent..."* — the only product in this layer that lets the producer scale liability above
100%.

So the selectable item is the **trigger (90% down to 75%, 5-point increments)**; 70% is the
floor produced by the 20-point maximum coverage range, not a selectable attachment.

**STAX can be bought standalone.** 23-STAX-0021 intro: *"...or it may be purchased as the
sole coverage for your cotton crop."* 7 U.S.C. 1508b(b)(3) caps it: *"...except that if a
producer has an individual or area coverage for the same acreage, the maximum coverage
available under the Stacked Income Protection Plan shall not exceed the deductible for the
individual or area coverage."* Operationalised in §10(b), which reduces the coverage range
in 5-point steps until `coverage range + companion coverage level ≤ area loss trigger`, and
voids STAX for that type/practice if that would take the range below 5 points.

**Subsidy: 80% at every trigger [ADM].** 7 U.S.C. 1508b(d)(1); fact sheet: *"The government
will pay for 80 percent of the premium cost for STAX."*
**Producer cost: $0.0881 per $1 of liability, $7.95/acre.**

### 3.5 MP / MP-HPO — Margin Protection (plans 16 / 17)

508(h) (Watts and Associates); the 2026 ADM flags 100% of plan-16/17 offers `Y`. Governing
document **25-MP**.

**A margin, not a revenue, trigger — it can pay when yield and price are both fine.**
Fact sheet:

> "Margin Protection provides you coverage against an unexpected decrease in your operating
> margin (revenue less input costs). Margin Protection is area-based, using county-level
> estimates of average revenue and input costs to establish the amount of coverage and
> indemnity payments. Because Margin Protection is area-based (average for a county), it may
> not reflect your individual experience. A payment may be made when the harvest margin for
> the county is lower than the trigger margin due to a decrease in revenue **and/or an
> increase in input costs**." *(emphasis added)*

> "Expected Margin = Expected Revenue – Expected Costs... Trigger Margin = Expected Margin –
> Deductible, where the deductible is 1.00 minus the coverage level multiplied by the
> expected revenue."

Priced inputs, per crop: corn — diesel, urea, DAP, potash, interest; soybeans — diesel, DAP,
potash, interest; rice — diesel, urea, DAP, potash, interest; wheat — diesel, urea, MAP,
potash, interest. *"Inputs not subject to price change are not specifically identified, but
include, seed, machinery, operating costs (other than fuel), and similar expenses."*

**MP insures the whole margin, not a band.** From the 2026 ADM (`A00810`), plan 16/17
Expected Margin is p10 $156.57 / median $364.31 / p90 $536.58 per acre against an Expected
Revenue of p10 $371.81 / median $641.65 / p90 $958.51. That is why MP's liability per acre
in the SoB is **$1,056** against ECO's $61 — MP is a base-layer-scale product that happens
to be sold alongside one, and its $34.43/acre producer cost is the highest in the layer.

**Coverage levels and subsidy: 70–95%; 0.59 at 70%, 0.55 at 75–80%, 0.49 at 85%, 0.44 at
90–95% [ADM, and MP FAQ verbatim].** MP was **not** raised to 80% — MGR-25-006 does not
list it. Realized 44.3% in the SoB confirms buyers cluster at 90–95%.

**Sales closing date is a year ahead of the underlying.** *"The MP sales closing date for
corn, soybeans, and spring wheat is September 30 of the calendar year prior to the insured
crop year."* This is a genuine planning trap: MP must be elected roughly five months before
the producer knows what the spring RP projected price will be.

**Premium credit when stacked on a base policy.** MP FAQ:

> "If you buy a base policy, you will receive a credit to your MP premium because indemnity
> payments from the base policy are used to offset indemnity payments from the MP policy...
> The amount of the premium credit will depend on the producer's historical unit yields
> relative to the county yields for the same years."

That last clause is worth dwelling on: **RMA prices the producer's own basis risk into the
MP premium credit.** A producer whose unit yields track the county closely gets a larger
credit, because the base policy will more reliably absorb the loss first.

**Availability:** corn in select counties of all states except AK/HI; soybeans in 34 states;
rice in AR/CA/LA/MS/MO/TX; spring wheat (type 012 only) in MN/MT/ND/SD. **No cotton, no
grain sorghum.** The 2026 ADM shows 13,893 offers — corn 7,680, soybeans 5,641, wheat 302,
barley 270.

### 3.6 PACE — Post-Application Coverage Endorsement (plans 26 / 27 / 28)

508(h) (Zea Mays Foundation). Governing document **23-PACE-20660**; no 2026-specific form
exists. **PACE is INDIVIDUAL-triggered, and it is the only individual-triggered
single-crop endorsement in this layer.**

23-PACE-20660 §11(b):

> "We will determine your loss on a PACE insured unit basis. PACE does not use your actual
> loss of yield to determine whether a PACE indemnity is due. A PACE loss is only paid on
> affected PACE loss acres within a PACE insured unit..."

§8(a): *"...insurance under this Endorsement is provided only against the actual physical
inability to post-apply nitrogen during the insurance period, due to insurable causes of
loss specified within the underlying insurance policy."*

§2: *"**Prevented post-application** - The physical inability to apply nitrogen during the
post-application window due to an insured cause of loss. If there is any post-planting
application of nitrogen, then you are not prevented from applying post-application nitrogen,
regardless of whether you were able to apply the full intended post-application percent..."*
— an all-or-nothing test per unit.

§9 excludes *"(b) Fertilizer price risk"* and *"(e) Supply chain disruptions or inability to
purchase fertilizer, equipment, or services."* PACE is a field-conditions product, not an
input-cost product. It does **not** substitute for MP or MCO.

**Conditions.** §1: *"(c) Your underlying insurance policy must be Yield Protection, Revenue
Protection, or Revenue Protection with Harvest Price Exclusion... (g) You are not eligible
for this Endorsement if you have elected Catastrophic Risk Protection coverage... (i)
Acreage designated by FCIC with a high-risk classification is not insurable under this
Endorsement. (j) Only non-irrigated corn is insurable under this Endorsement."*

**It offsets against the underlying.** §11(e): *"The amount of indemnity payment owed under
this Endorsement may be reduced by a PACE offset in the event an indemnity payment is also
owed to you on your underlying insurance policy and the indemnity calculated in (c) above
exceeds the deductible on your underlying insurance policy."* FAQ: *"PACE will not pay out
more than the deductible on your underlying insurance policy."*

72-hour notice of loss required (fact sheet). Coverage levels 75–90%. **Subsidy: 0.60 at
75%, 0.51 at 80%, 0.41 at 85–90% [ADM]** — i.e. PACE carries the ordinary *individual*-plan
subsidy schedule, not the 80% area-endorsement rate. RMA does not publish these numbers in
any fact sheet; they are computed here from the loaded ADM. Realized 44.1% in the SoB.

Available for non-irrigated corn in IL, IN, IA, KS, MI, MN, NE, ND, OH, SD, WI. The 2026
ADM shows 919 offers. Uptake is essentially nil: **21 policies, $105,636 of liability
nationally**.

### 3.7 HIP-WI — Hurricane Insurance Protection – Wind Index (plan 37)

Not 508(h) (RMA-developed under the 2018 Farm Bill hurricane mandate); 2026 ADM flag `N` on
100% of plan-37 offers. Governing document **26-HIP-WI** (released April 2025), PM-25-023.

**Pure index. No individual loss, no loss adjustment, no notice of loss.** §1:

> "**Weather Event** - A named tropical cyclone, as identified by NOAA and determined by
> FCIC in accordance with the HDP... To meet the County Loss Trigger in a county or adjacent
> county: (1) A hurricane must have maximum sustained surface winds of 64 knots (74 mph) or
> greater. (2) A tropical storm must have: (i) Maximum sustained surface winds ranging from
> 39-73 mph (34 to 63 knots); and (ii) A Final Rainfall Amount of at least 6 inches received
> over four days..."

§8(b): *"Individual farm yields and revenues are not considered under this Endorsement. It
is possible that your individual farm may experience reduced revenue or reduced yield and
you do not receive an indemnity under this Endorsement."*
§8(c): *"The notice provisions in section 14(b) of the Basic Provisions do not apply."*
§4: *"You are not required to file a separate report of acreage when you elect this
Endorsement."*
§9(a): *"An indemnity is due when the County Loss Trigger is identified for the insured
county in the Insurance Period."*

**The elected variable is 1–100%, not a coverage level.** §1: *"**Coverage Percentage** - A
factor elected, between 1 and 100 percent in whole percent increments, used to determine the
Hurricane Protection Amount."* The band is defined residually:

> "**Hurricane Coverage Range** - The amount of difference between 95 percent and the higher
> of the coverage level of your Underlying Policy or, if applicable, the upper end of your
> SCO coverage range (if SCO coverage applies), STAX coverage range (if STAX coverage
> applies), or other endorsement coverage where such endorsement provides additional
> coverage for a portion of the Underlying Policy deductible."

**HIP-WI is structurally independent of whether the underlying pays** — there is no offset
provision analogous to PACE's. Liability adjustments on the underlying flow through
(§6(b)(2): *"Any adjustment in liability on the underlying crop policy will apply"*), and
cancellation of the underlying cancels HIP-WI (§3(b)), but an underlying *indemnity* does
not reduce the HIP-WI indemnity. §2(c): *"The coverage provided by this Endorsement may be
combined with other endorsements or plans that provide additional coverage for a portion of
the Underlying Policy deductible if the other endorsement(s) or plan(s) do(es) not provide
the same coverage as the HIP-WI coverage range."*

**Tropical Storm Option** (§12): 50% of the HPA per triggering tropical storm, up to two per
year, total capped at the HPA; premium owed even if a hurricane exhausts the HPA first.

**Subsidy: 80% [ADM, single coverage level 0.95].** CY2026 FAQ: *"The premium subsidy for
the HIP-WI Endorsement is fixed at 80 percent."*
**Producer cost: $0.0398 per $1 of liability, $5.69/acre.** Note HIP-WI's liability per acre
($142.91) is the highest of the true endorsements — it covers everything from the underlying
coverage level (or the top of SCO/STAX) all the way to 95%.

70 crops, 23 states. The 2026 ADM shows 107,494 offers.

### 3.8 WFRP — Whole-Farm Revenue Protection (plan 76)

Not 508(h); RMA-developed under the 2014 Farm Bill. Not really an endorsement — it is a
whole-farm policy that *coexists with* individual policies — but it belongs in this analysis
because it is the third-largest liability pool in the layer ($2.57bn) and because its
interaction rules with underlying policies are the most intricate in the whole system.

**Coverage 50–90% for 2026** (raised from 85% by OBBBA; confirmed in the ADM). Fact sheet:
*"The approved revenue amount is determined on your Farm Operation Report and is the lower of
the expected revenue or your whole-farm historic average revenue. Coverage levels range from
50 percent to 90 percent. Catastrophic Risk Protection (CAT) coverage is not available."*

**$17m cap:** *"Have no more than $17 million in insured revenue, which is the farm revenue
allowed to be insured under the policy multiplied by the coverage level you select..."* with
sub-caps of $2m each on animals/animal products and greenhouse/nursery, and *"no more than
50 percent of total revenue from commodities purchased for resale."*

**The diversification premium discount.** Fact sheet:

> "The Commodity Count in the table above is a measure of the farm's diversification,
> determined by the policy. The calculation determines the minimum proportion of revenue a
> commodity must contribute to the farm to be considered a commodity for WFRP... The minimum
> proportion to be considered a countable commodity is one-third of that amount. In this
> example, for corn, soybeans, spinach, or carrots, each commodity would have to make up at
> least 8.3 percent of the total revenue of the farm to count as a commodity under WFRP.
> Commodities with revenue below the minimum will be grouped together in order to recognize
> farm diversification (this will make the commodity count higher)."

Diversification drives the **premium rate discount**. The **subsidy** is keyed to coverage
level: **80% at 50–75%, 71% at 80%, 56% at 85% and 90% [ADM, plan 76 — matching RMA's
published 2026 FAQ table exactly].** The realized SoB subsidy share of 68.2% places the
average WFRP buyer between the 75% and 80% coverage levels.

*Caveat:* FCIC-18160 ¶53(4) says *"The premium subsidy amount will be based on the commodity
count determined by the commodity count calculation and the table specified in the AD"* —
i.e. RMA asserts a commodity-count × coverage-level subsidy matrix lives in the Actuarial
Documents. The ADM `A00070` table loaded here shows only a coverage-level dimension for plan
76. See §7.

**Interaction with individual policies — FCIC-18160 ¶123:**

> "(1) The insured may insure the same commodity under WFRP and under another FCIC reinsured
> policy, if available, unless otherwise specified in the Special Provisions or not allowed
> by the other policy.
> (2) Any other FCIC reinsured policy purchased by the insured at a buy-up level of coverage
> that insures commodities covered by WFRP will be considered the primary insurance, and any
> indemnity payment received from such policy will be included as RTC unless (3) applies.
> (3) The insured may elect to exclude all FCIC reinsured policies from becoming primary
> insurance at the time they complete the application..."

¶53(2): *"If insured purchases or has purchased individual buy-up coverage levels of FCIC
reinsured policies, the insured revenue will be adjusted to reflect these purchases for
premium calculations only, unless the insured elects, on the application, to exclude such
policies..."* — capped, per the 2026 FAQ, at *"up to 50 percent of your WFRP policy
liability."* CAT-level policies produce no reduction.

**BFR/VFR subsidy add-ons are unusually rich here.** FCIC-18160 ¶53(5): *"(a) A BFR, their
premium subsidy will be increased by: (i) 15 percentage points for the first and second
policy years of benefits; (ii) 13 percentage points for the third policy year..."* and
*"(b) A VFR, their premium subsidy will be increased by 10 percentage points."*

**Producer cost: $0.0260 per $1 of liability — the cheapest coverage in the layer**, despite
the *lowest* subsidy rate of the 80%-class products. That is because WFRP's premium rate is
only 8.2%: whole-farm diversification is genuinely cheaper to insure.

### 3.9 The 508(h) inventory in this repo

`products` table, `bucket='508h'`, 16 rows, joined to `product_crops`:

| # | product | plan codes | crops | layers on row crops? |
|---|---|---|---|---|
| 1 | Margin Protection (MP) | 16;17 | Corn, Rice, Soybeans, Spring Wheat | yes — §3.5 |
| 2 | Stacked Income Protection Plan (STAX) | 35;36 | Cotton | yes — §3.4 |
| 3 | Supplemental Coverage Option (SCO) | 31;32;33 | 12 row crops | yes — §3.1 |
| 4 | Enhanced Coverage Option (ECO) | 87;88;89 | Corn, Cotton, Grain Sorghum, Rice, Soybeans, Wheat | yes — §3.2 |
| 5 | Hurricane Insurance Protection – Wind Index | 37 | Corn, Cotton, Grain Sorghum, Peanuts, Rice, Soybeans | yes — §3.7 |
| 6 | Post-Application Coverage Endorsement (PACE) | 26;27;28 | Corn | yes — §3.6 |
| 7 | Whole-Farm Revenue Protection (WFRP) | 76 | all (whole-farm) | coexists — §3.8 |
| 8 | Margin Coverage Option (MCO) | 67;68;69 | Corn, Cotton, Grain Sorghum, Rice, Soybeans, Spring Wheat | yes — §3.3 |
| 9 | Trend-Adjusted APH Yield Endorsement (TA-APH) | — | Barley, Corn, Cotton, Grain Sorghum, Soybeans, Wheat | **yes — see below** |
| 10 | Downed Rice Endorsement | — | Rice | yes, rice only |
| 11 | Cottonseed Endorsement | — | Cotton | yes, cotton only |
| 12 | Malting Barley Revenue Endorsement | — | Barley | yes, contract barley |
| 13 | Pulse Crop Revenue | — | Chickpeas, Dry Peas, Lentils | plan, not endorsement |
| 14 | Peanut Revenue | — | Peanuts | plan, not endorsement |
| 15 | Popcorn Revenue | — | Popcorn | plan, not endorsement |
| 16 | Specialty Soybeans | — | Soybeans | yes, contract soybeans |

**Two corrections to the catalog itself, both computable from the loaded ADM.**

*(a) The `508h` bucket is mislabelled for four of its sixteen members.* The 2026 ADM carries
RMA's own `Private 508H Flag` on every insurance offer (`A00030`, field 33). Counting live
offers by plan:

| plan | product | offers | flagged 508H = Y |
|---|---|---:|---:|
| 16 / 17 | MP | 13,893 | **100%** |
| 26 / 27 / 28 | PACE | 919 | **100%** |
| 67 / 68 / 69 | MCO | 6,318 | **100%** |
| 87 | ECO-YP | 220,147 | 90% |
| 88 / 89 | ECO-RP / RPHPE | 175,240 | **100%** |
| 31 / 32 / 33 | SCO | 231,838 / 175,240 | **0%** |
| 35 / 36 | STAX | 6,813 | **0%** |
| 37 | HIP-WI | 107,494 | **0%** |
| 76 | WFRP | 18,852 | **0%** |

SCO, STAX, HIP-WI and WFRP are **statutory/RMA products, not 508(h) submissions** — RMA says
so in its own actuarial data. The `products.notes` field already records this correctly for
each of the four; it is the `bucket` value that is wrong. The bucket is functioning as a
"federal supplemental layer" bucket, not a 508(h) bucket. Rows 9–16 could not be checked the
same way because they have no distinct plan code (they are options/endorsements riding on an
existing plan).

*(b) Row 9, TA-APH, is the sleeper.* Trend-Adjusted APH is a 508(h) product that is not an
endorsement to the *deductible* at all — it raises the **approved yield** that every other
product in this document is computed from. It therefore scales SCO, ECO, MCO and the
underlying simultaneously, and it is the only item in the list whose benefit compounds
across the whole stack. It is out of scope for a band/trigger analysis (there is no band),
but any ranking of "return per producer dollar" that omits it is incomplete. **I did not
quantify it** — see §7.

---

## 4. Compatibility matrix

**CY2026 rules.** `Y` = may be carried together on the same acres. `N` = prohibited.
`SPLIT` = both may be carried for the crop in the county, but the producer must designate
which acres go to which, by the sales closing date. `–` = not applicable / never co-offered.

|  | SCO | ECO | MCO | STAX | MP | PACE | HIP-WI | WFRP | ARPI | CAT | ARC | PLC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SCO** | — | **Y** | **Y** | SPLIT | **N** | ? | **Y** | ? | **N** | **N** | **Y** ⚠ | **Y** |
| **ECO** | **Y** | — | **N** | **N**/SPLIT ⚠ | **N** | ? | **N** | ? | **N** | **N** | **Y** | **Y** |
| **MCO** | **Y** | **N** | — | Y (cond.) | **N** | ? | **N** | ? | **N** | **N** | **Y** | **Y** |
| **STAX** | SPLIT | **N**/SPLIT ⚠ | Y (cond.) | — | – | – | Y (cond.) | ? | Y | N (standalone) | **N** | **N** |
| **MP** | **N** | **N** | **N** | – | — | ? | **N** | **N** | – | **N** | Y | Y |
| **PACE** | ? | ? | ? | – | ? | — | – | ? | **N** | **N** | Y | Y |
| **HIP-WI** | **Y** | **N** | **N** | Y (cond.) | **N** | – | — | ? | – | – | Y | Y |
| **WFRP** | ? | ? | ? | ? | **N** | ? | ? | — | – | – | Y | Y |

### The load-bearing cells, with citations

**SCO × ARC — the one everybody gets wrong.** ⚠ **For CY2026 this is `Y`, not `N`.**
Repealed by OBBBA §10303(b), implemented by 25-OBBA and MGR-25-006 for all SCDs on or after
2025-07-01. See §2(b) for the full quoted chain. **Through CY2025 it was `N` at the FSA farm
serial number × crop level, triggered by ARC *election* regardless of enrollment.** PLC never
blocked SCO. RMA's own January 2022 SCO fact sheet still states the obsolete rule.

**STAX × seed-cotton ARC *and* PLC — `N`, and BOTH block it.** This is the one that did
*not* change. **7 U.S.C. 1508b(f)**, added by the Bipartisan Budget Act of 2018
(Pub. L. 115-123 §60101(a)(10)) — note, *not* the 2018 Farm Bill — and untouched by OBBBA:

> "**(f) Limitation** — Effective beginning with the 2019 crop year, a farm shall not be
> eligible for the Stacked Income Protection Plan for upland cotton for a crop year for
> which the farm is enrolled in coverage for seed cotton under—
> (1) price loss coverage under section 9016 of this title; or
> (2) agriculture risk coverage under section 9017 of this title."

Policy text, 23-STAX-0021 §3(b)(6): STAX will not insure acreage *"On land identified by an
FSA farm number that has been enrolled in ARC or PLC for seed cotton for the crop year as of
March 15."*

Three details that decide real cases, from the RMA STAX fact sheet:

> "You may not participate in STAX on a farm if cotton seed base acres are enrolled in ARC
> or PLC.
> • Example 1: If you have a farm with seed cotton base acres and elect and enroll in ARC or
> PLC and plant upland cotton you may not participate in STAX.
> • Example 2: If you have a farm with wheat base acres and elect and enroll in ARC or PLC
> and plant upland cotton you may participate in STAX.
> • Example 3: If you have a farm with seed cotton base acres and elect but do not enroll in
> ARC or PLC but plant upland cotton you may participate in STAX."

> "FSA Election/Enrollment for ARC/PLC is March 15. Regardless of FSA allowing for updated
> enrollment until September 30, RMA will use what the producer selects by March 15 for STAX."

So: it is **seed cotton** base specifically (other-crop base is irrelevant); it is
**enrollment**, not election; and the operative date is **March 15**, notwithstanding FSA's
later window. This is the mirror image of the old SCO rule, which keyed on election
regardless of enrollment.

Reporting duty and penalty, 23-STAX-0021 §4(f)–(g): the acreage report must carry the FSA
farm serial numbers, whether ARC/PLC was enrolled, and *"For acreage with an ARC or PLC
enrollment date later than the acreage reporting date, your intended ARC or PLC enrollment."*
Misreport it and *"Such acreage will be ineligible for any indemnity under this policy
because acreage cannot benefit from STAX and ARC or PLC; and ... You will still be required
to pay 60 percent of the premium due."*

**So the joint USDA-program optimisation has moved, not disappeared.** In 2026 it applies to
*cotton only*: a cotton producer must choose between (seed cotton ARC/PLC) and STAX, and must
make that call by March 15. Everyone else can now take ARC and SCO both.

**SCO × STAX — `SPLIT`.** 23-STAX-0021 §10(c):

> "(c) If you have a companion policy that provides coverage on an individual basis for the
> crop insured by STAX, and you have elected the Supplemental Coverage Option (SCO) for that
> policy: (1) You must designate which acres of the crop in the county will be covered by
> STAX and which acres will be covered by SCO on or before the sales closing date (**the same
> acreage cannot be covered by both STAX and SCO**)..."

And from the SCO side, 27-SCO §2(d): *"The coverage provided by this Endorsement may not be
combined with the Stacked Income Protection Plan (STAX)."* §5(a): *"...except this Endorsement
will not insure acreage that is designated as covered by STAX."*

**ECO × STAX — `N` for CY2026, and RMA's two documents disagree.** ⚠ 21-ECO's introductory
paragraph (governing for CY2026) says ECO *"may not be combined with the Stacked Income
Protection Plan (STAX)... on any acreage planted to the insured crop."* The July 2024 ECO
fact sheet says: *"ECO coverage cannot attach to any acres that are insured by Stacked Income
Protection Policy (STAX). Acres not insured under STAX may be insured under ECO."* But RMA's
current ECO FAQ (July 2026) says *"ECO with SCO or STAX are not mutually exclusive because
their bands of coverage do not overlap."* That FAQ describes CY2027, where SCO tops at 90%
and ECO runs 90→95, genuinely abutting STAX's 90% ceiling. **For CY2026, 21-ECO governs and
the answer is `N` on STAX acres, `Y` on the rest.** I could not find a document that
reconciles them explicitly.

**ECO × SCO — `Y`, and this is the core legal stack.** ECO FAQ: *"Producers may choose to
purchase SCO or Stacked Income Protection Policy (STAX) on acres that are insured under ECO,
but are not required to do so. ECO with SCO or STAX are not mutually exclusive because their
bands of coverage do not overlap."* For CY2026 the bands abut at 86%: underlying CL → 86% is
SCO, 86% → 90/95% is ECO.

**MCO × SCO — `Y`; MCO × ECO — `N`.** MCO FAQ: *"Producers may choose to purchase SCO on
acres that are insured under MCO but are not required to do so. MCO and SCO are not mutually
exclusive because their bands of coverage do not overlap."* 26-MCO §2(j):

> "(j) You may not elect the Enhanced Coverage Option Endorsement, Margin Protection Plan, or
> the Hurricane Insurance Protection-Wind Index Endorsement on the underlying policy or other
> endorsements or plans that provide additional coverage for a portion of the underlying
> policy deductible if the other endorsement(s) or plan(s) provide the same coverage range as
> this Endorsement."

MCO and ECO occupy the *same* 86→95 band in CY2026 — one is a margin trigger, the other a
revenue trigger — so they are alternatives, not layers. **This is the sharpest live choice in
the 2026 layer for a corn/soybean producer in an MCO county.**

**MCO × STAX — conditional.** 26-MCO §2(q): *"This Endorsement is not available with STAX
when the acreage insured under STAX is not also insured under a companion policy."* §2(r):
*"If you have a STAX policy in effect on the MCO sales closing date at the 90 percent area
loss trigger, then you may only elect the 95 percent trigger level for MCO."*

**MP × everything supplemental — `N`.** 25-MP §2(h)–(i):

> "(h) If you elect the Supplemental Coverage Option on the policy issued under the Basic
> Provisions, you are not eligible for MP.
> (i) You may not elect any optional endorsement to the base policy that duplicates coverage
> provided by your MP policy. For example, you may not elect the Supplemental Coverage Option
> Endorsement to the base policy. The optional endorsements will be void for the base policy
> from the date of MP application for the crop year covered by the MP policy."

MP FAQ: *"You may buy any optional coverages or endorsements available for the base policy
except the Supplemental Coverage Option Endorsement (SCO), Enhanced Coverage Option (ECO) and
Hurricane Insurance Protection - Wind Index Endorsement (HIP-WI)... MP cannot be purchased if
you have Whole-Farm Revenue Protection Policy (WFRP) or Micro Farm covering the same crop in
the same county."*

**ECO / MCO × HIP-WI — `N`.** 21-ECO intro (quoted §3.2); 26-MCO §2(j). ECO FAQ: *"Farmers
who buy ECO may not buy Area Risk Protection Insurance (ARPI), Hurricane Insurance Protection
- Wind Index Endorsement (HIP-WI), or Margin Protection (MP) on the same acre in the same
year."*

**SCO × HIP-WI — `Y`, and HIP-WI is designed around it.** 26-HIP-WI defines its band as
*"the difference between 95 percent and the higher of the coverage level of your Underlying
Policy or, if applicable, the upper end of your SCO coverage range."* HIP-WI is only barred
from STAX *"when the acreage insured under STAX is not also insured under a companion
policy"* (§2(c)(2)), and from OLO and CTV.

**ARPI and CAT.** SCO is *"not available with ARPI"* (CIH ¶916L); ECO and MCO likewise; PACE
*"may not be purchased with Area Revenue Protection Insurance (ARPI)"*. All of SCO/ECO/MCO/
PACE require *additional* coverage — none attach to CAT.

### 4.1 The empirical check on the matrix, and why it is only a necessary condition

`endorsement_economics.py` Table 3 counts 2026 county × crop cells in which two families both
recorded liability > 0:

|  | ECO | HIP-WI | MCO | MP | PACE | SCO | STAX | WFRP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ECO | 5,982 | 600 | 802 | 357 | 10 | 5,344 | 147 | 0 |
| HIP-WI | 600 | 1,276 | 5 | 3 | 0 | 740 | 59 | 0 |
| MCO | 802 | 5 | 826 | 250 | 5 | 800 | 17 | 0 |
| MP | 357 | 3 | 250 | 360 | 2 | 355 | 0 | 0 |
| PACE | 10 | 0 | 5 | 2 | 10 | 10 | 0 | 0 |
| SCO | 5,344 | 740 | 800 | 355 | 10 | 5,655 | 157 | 0 |
| STAX | 147 | 59 | 17 | 0 | 0 | 157 | 176 | 0 |
| WFRP | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 95 |

SCO × ECO = 5,344 of SCO's 5,655 cells — the dominant stack, as expected.

**But note ECO × HIP-WI = 600 and ECO × MP = 357, both of which are legally prohibited on the
same acres.** This is exactly why the SoB test is *necessary but not sufficient*: the SoB
aggregates to county × crop, so two mutually exclusive products can appear in the same cell
simply because different producers bought different things. The matrix above is built from
policy text; this table is only a consistency check on the *zeros*.

The zeros are informative: MP × STAX = 0 (MP is not offered on cotton), PACE × STAX = 0 and
PACE × HIP-WI = 0 (PACE is 11 Midwest states, HIP-WI is coastal). **The WFRP row of zeros is
an artifact** — all 95 WFRP rows carry the crop label "All crops (whole-farm)", so it can
never share a crop key with anything. It says nothing about WFRP compatibility.

---

## 5. Where is the best expected return per producer dollar

### 5.1 The uncomfortable identity

RMA rates are set to a target loss ratio, so a plan's premium rate is its expected indemnity
per dollar of liability. Then, for any plan:

```
E[indemnity]          total premium              1
--------------  =  ---------------------  =  ---------
producer premium    total premium × (1-s)      1 - s
```

**Expected return per producer dollar depends only on the subsidy rate.** Not on the band,
not on the trigger, not on the crop, not on the county. Every one of the six 80%-subsidised
products returns the same expected $5.00 per producer dollar; there is no clever selection
among them that beats that. This is confirmed in the loaded data — Table 1's premium rate
divided by its producer-cost column returns 5.00–5.13× for every 80%-class plan.

Anyone quoting a "return" figure that differs across the 80%-class products is either using a
historical loss ratio (legitimate, and I could not compute one — see §7) or making an error.

### 5.2 The ranking

Computed from the SoB (`family_economics.csv`). "Gross return" = 1 / (1 − realized subsidy
share). "Risk-transfer return" strips out payments landing in years the farm had no in-band
loss, using the model in §6 at ρ = 0.80; it is modelled only for the two bands I simulated
(ECO 86→95 and SCO CL→86) and left blank elsewhere rather than guessed.

| rank | product | subsidy | producer $ / $1 liab | producer $/ac | gross return | risk-transfer return (ρ=0.80) | binding condition |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | **ECO** | 80.5% | 0.0916 | $5.64 | **5.13×** | **3.89×** | none — no ARC bar, no SCO prerequisite; widest band available to a high-coverage producer |
| 2 | **SCO** | 80.4% | 0.0495 | $2.95 | **5.10×** | **3.76–3.80×** | band = 86% − underlying CL; **worthless at CL 85%** (1 point) |
| 2= | **MCO** | 80.4% | 0.1005 | $6.38 | **5.10×** | not modelled | mutually exclusive with ECO; select counties only; no organic |
| 4 | **HIP-WI** | 80.3% | 0.0398 | $5.69 | **5.08×** | n/a — pure index | 23 coastal states; blocks ECO and MCO |
| 5 | **STAX** | 80.0% | 0.0881 | $7.95 | **5.00×** | not modelled | upland cotton; killed by seed-cotton ARC **or** PLC enrollment |
| 6 | **WFRP** | 68.2% | **0.0260** | n/a | **3.14×** | ≈ gross — individual trigger | diversified farms; ≤ $17m; blocks MP |
| 7 | **MP / MP-HPO** | 44.3% | 0.0326 | $34.43 | **1.80×** | not modelled (area margin) | blocks SCO, ECO, HIP-WI, WFRP; SCD a year early |
| 8 | **PACE** | 44.1% | 0.0368 | $1.79 | **1.79×** | ≈ gross — individual trigger | non-irrigated corn, 11 states |

Note ρ = 0.80 is the mid-case. At ρ = 0.90 ECO's risk-transfer return is 4.21× and SCO's
4.06–4.13×; at ρ = 0.70, 3.66× and 3.48–3.55×. **SCO and ECO track each other within about
0.1× at every ρ** — the band position barely matters for this ratio, which is a useful
negative result: the choice between them should be made on band *width* and legal
foreclosure, not on basis-risk grounds.

**Reading the ranking honestly.**

- **Rows 1–5 are a tie.** They differ by 2.6% in expected return. Choosing among them on
  "return per dollar" grounds is noise. Choose on *band position*, *trigger quality* and
  *what each one forecloses*.
- **The real ranking variable is what a product blocks.** MP is bottom of the table not
  because 1.80× is bad in isolation — it is a positive-expectation transfer — but because
  electing it forfeits SCO, ECO, HIP-WI and WFRP, each of which returns ~5×. The opportunity
  cost dwarfs the direct return. **MP is the single most expensive election in this layer
  once foreclosure is priced.** The 2026 SoB shows the market agrees: 1,779 MP policies
  against 521,821 ECO.
- **WFRP is the best-value coverage per dollar of liability ($0.026) despite the worst
  subsidy of the 80%-class.** Its premium rate is only 8.2% because whole-farm
  diversification is genuinely cheaper to insure — the producer is buying a portfolio, not a
  crop. And its trigger is individual, so there is no basis risk at all. For a farm that
  qualifies, this is the strongest risk-transfer proposition in the layer. It is also nearly
  unused on row crops — 1,703 policies.
- **SCO's rank is conditional and the condition bites hard.** At an 85% underlying coverage
  level SCO's band is one coverage point. At 75% it is eleven. **SCO is a product for
  producers who deliberately carry a lower underlying coverage level** — and the measured
  band in §1.2 (median 7.9 points, implying an average underlying CL near 78%) shows buyers
  already understand this.
- **MCO vs ECO is the genuine 2026 decision.** Same 86→95 band, same 80% subsidy, mutually
  exclusive. MCO triggers on county *margin*, ECO on county *revenue*. MCO's premium rate
  (51.5%) exceeds ECO's (47.2%) because the margin trigger can be breached by an input-cost
  move alone — the producer is buying a strictly larger set of triggering events, and paying
  ~9% more for it. **In a year of volatile fertiliser or diesel, MCO dominates; in a stable
  input year the extra premium buys nothing.** MCO's practical drawbacks are its September 30
  SCD (before the projected price is known) and its exclusion of organic production.

### 5.3 Conditions: irrigated, county correlation, farm size

**Irrigated vs non-irrigated.** From the 2026 ADM (`A01010`, Revenue Protection Reference
Rate, computed by `scripts/analysis/basis_risk.py`), in counties where RMA publishes both
practices:

| crop | counties with both practices | identical rate for both | median irrigated rate | median non-irr rate | **non-irr / irr, p10** | **median** | **p90** |
|---|---:|---:|---:|---:|---:|---:|---:|
| Corn | 2,358 | 52% | 0.0383 | 0.0653 | 1.21× | **2.84×** | 8.31× |
| Wheat | 2,314 | 53% | 0.0720 | 0.0870 | 1.08× | **1.46×** | 3.26× |
| Soybeans | 2,017 | 28% | 0.0385 | 0.0673 | 1.22× | **2.25×** | 3.48× |
| Cotton | 690 | 14% | 0.0488 | 0.1114 | 1.27× | **2.33×** | 4.24× |
| Rice | 145 | 81% | 0.1579 | 0.1618 | 1.04× | **1.18×** | 1.19× |
| Grain Sorghum | 129 | 20% | 0.0821 | 0.0970 | 1.04× | **1.29×** | 1.57× |

*(ADM A00490: irrigation practice code 002 = Irrigated, 003 = Non-Irrigated — note the
counter-intuitive order. Ratio columns exclude the counties where RMA publishes an identical
reference rate for both practices, since those carry no information. The Reference Rate is
the rate at that practice's own reference yield, because RMA's continuous rating formula
`base rate = reference rate × (reference amount / approved yield)^exponent + fixed rate`
collapses to the reference rate when approved yield equals the reference amount — so this is
a like-for-like comparison of a typical irrigated farm against a typical non-irrigated farm
in the same county.)*

**In the median corn county where RMA distinguishes the two, it charges non-irrigated ground
2.84× the pure rate it charges irrigated ground — and at the 90th percentile, 8.31×.** That
is RMA's own published statement that these are not the same risk. One county index triggers,
or fails to trigger, for both of them alike.

The implication is directional and strong: **an irrigated operation in a
predominantly-dryland county has the worst basis risk in the system.** The county index is
driven by the dryland majority; the irrigated farm's yield is stabilised by water. In a
drought the index triggers and the irrigated producer collects without a loss (a transfer in
their favour); in a localised hail or disease event the irrigated producer loses and the
index does not move. Neither outcome is insurance. **For an irrigated producer, the
individual-triggered options — a higher underlying coverage level, or WFRP — buy more actual
risk transfer per dollar than any area band, even at a worse subsidy rate.**

The converse holds too: a **non-irrigated producer in a uniformly non-irrigated county** is
the best-matched buyer of SCO/ECO/MCO, because the county index and the farm share the same
dominant peril (drought), which is precisely the peril with high spatial correlation.

**County yield correlation (ρ).** This is the master variable and §6 quantifies it. In
summary: at ρ = 0.95 an area band leaves ~12% of in-band farm loss uncovered; at ρ = 0.60 it
leaves ~35%. Producers with land concentrated in one soil type in one part of one county sit
low on ρ; producers spread across a county sit high.

**Farm size.** Larger, more geographically dispersed farms are *mechanically* better matched
to a county index — their own yield is closer to a county average because it is an average
over more of the county. A 5,000-acre operation spread across a county effectively *is* a
large slice of the index. A 300-acre operation on one soil association is not. **Farm size
raises ρ, and ρ is the only thing that improves the value of an area band.** RMA prices this
directly in MP: the premium credit *"will depend on the producer's historical unit yields
relative to the county yields for the same years."*

---

## 6. Basis risk — the counterweight

This section is deliberately placed to be read, not buried. The §5 argument — 5× expected
return — is arithmetically true and simultaneously the most misleading number in crop
insurance, because **an area-triggered product can pay $5 for every $1 in expectation while
failing to pay in exactly the years the producer needs it.** The subsidy is real; the risk
transfer is partial.

RMA says so itself. 20-SCO §8(b) and 26-HIP-WI §8(b), identically: *"It is possible that your
individual farm may experience reduced revenue or reduced yield and you do not receive an
indemnity under this Endorsement."*

Analysis by `scripts/analysis/basis_risk.py`.

### 6.1 Measured: RMA's own rates show within-county heterogeneity

Part A of the script (results table in §5.3) compares RMA's published *individual* Reference
Rate for non-irrigated vs irrigated Revenue Protection **within the same county**. In the
median corn county that distinguishes them, non-irrigated ground is rated at **2.84×** the
irrigated rate (soybeans 2.25×, cotton 2.33×; p90 for corn is 8.31×). RMA is asserting that
two operations in the same county have materially different loss distributions — while a
single county index triggers or fails to trigger for both. This is measured, published,
RMA-sourced evidence of the mechanism, not a model output.

Two caveats on it. About half of corn and wheat counties (and 81% of rice counties) publish
an *identical* reference rate for both practices; those counties are excluded from the ratio
columns because they say nothing either way. And the reference rate is only one term of the
rating formula — the fixed rate and the approved-yield exponent also differ by practice, and
those are not incorporated here, so treat the ratios as indicative of magnitude rather than
as an exact rate comparison.

### 6.2 Measured: most of a revenue band's payment carries NO basis risk

This is the most important and most under-appreciated result here.

Every insured acre in the country faces the **same harvest price**. Whatever share of an
area *revenue* band's expected payment is driven by price movement therefore has **zero**
basis risk — the trigger is national, and it moves identically for the index and for the
farm.

Decomposing the ECO-RP band payment in the model (Part B):

| scenario | E[payment] per $1 of band | P(band pays) |
|---|---:|---:|
| full model (price + county yield) | 0.4365 | 52.1% |
| price frozen at projected (yield leg only) | 0.3266 | 39.9% |
| county yield frozen at trend (price leg only) | 0.2800 | 39.5% |

**Price alone accounts for ~64% of the expected ECO-RP payment.** Only the yield leg can miss
an individual producer.

The corollary is severe and cuts the other way: **ECO-YP and SCO-YP drop the price leg
entirely, so they are close to pure basis risk.** The measured premium rates confirm the
mechanism — ECO-YP 25.0% against ECO-RP 47.2%, SCO-YP 9.3% against SCO-RP 25.6%. The yield
variants are cheaper because they cover less, and what they drop is precisely the part with
no basis risk. **A producer buying ECO-YP or SCO-YP is buying almost entirely the leg that
can fail them.** They are also the least-bought: 1.01m ECO-YP acres against 99.80m ECO-RP.

### 6.3 Model: how often does the county index fail a producer who lost

**Assumptions, stated.** Farm yield and county yield drawn from left-skewed Beta marginals on
[0, 1.7] with mean 1, joined by a Gaussian copula with correlation ρ, under a factor
structure `σ_county = ρ × σ_farm` (which guarantees the county is the less variable series,
as aggregation requires). Harvest/projected price ratio lognormal with the 2026 ADM's
published Price Volatility Factor for corn (0.15; ADM range 0.13–0.16). County-yield/price
correlation −0.25 (assumed). ECO band 86→95. 250,000 draws.

**Calibration caveat, stated up front.** At a realistic Corn Belt farm yield CV of 0.25 the
model produces an ECO-RP band loss cost of 0.4368 against the measured premium rate of
0.4721 — **the model under-prices the market by 7%**. Forcing the farm CV up to 0.55 (county
0.467, which is not physically plausible for a county average) still only reaches 0.4485,
5% short. The measured premium therefore exceeds what a fair model of the band produces at
any plausible yield CV, which is consistent with a rating load and/or adverse selection into
higher-risk counties. **This is reported, not hidden.** The basis-risk *ratios* below are
robust to it because they depend on ρ far more than on the absolute rate level — both
scenarios are shown and they agree closely.

**ECO-RP band (86→95), farm yield CV 0.25:**

| ρ | P(farm has band loss) | P(ECO pays) | P(ECO=0 **and** farm lost) | P(ECO=0 \| farm lost) | P(ECO=0 \| deep farm loss) | uncovered share of farm band loss | windfall share of ECO payment |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.95 | 51.6% | 51.7% | 5.0% | 9.7% | 0.1% | **11.7%** | 11.2% |
| 0.90 | 51.4% | 51.9% | 6.9% | 13.4% | 1.3% | **16.6%** | 15.6% |
| 0.85 | 51.5% | 52.1% | 8.4% | 16.4% | 3.1% | **20.4%** | 18.9% |
| 0.80 | 51.5% | 52.4% | 9.7% | 18.8% | 5.3% | **23.7%** | 21.9% |
| 0.70 | 51.4% | 53.0% | 11.7% | 22.7% | 10.1% | **29.5%** | 26.8% |
| 0.60 | 51.2% | 53.4% | 13.2% | 25.8% | 14.8% | **34.6%** | 30.7% |
| 0.50 | 51.4% | 53.3% | 15.0% | 29.3% | 19.8% | **40.1%** | 33.7% |
| 0.40 | 51.3% | 52.8% | 16.6% | 32.3% | 24.7% | **45.7%** | 36.0% |

(The high-CV upper-bound scenario gives 11.3% / 15.9% / 19.4% / 22.7% / 28.3% / 32.7% /
37.5% / 42.2% for the uncovered share — within a point or two throughout.)

**SCO-RP band (underlying CL → 86%), farm yield CV 0.25.** SCO is worse than ECO at every ρ,
because its band sits lower in the distribution where county and farm outcomes diverge more:

| underlying CL | band | ρ=0.90 | ρ=0.80 | ρ=0.70 | ρ=0.60 |
|---|---|---|---|---|---|
| 85% | 1p | P(SCO=0 \| farm lost) 20.0% | 29.6% | 37.6% | 45.4% |
| 80% | 6p | 20.0% | 30.0% | 37.6% | 45.3% |
| 75% | 11p | 20.1% | 29.6% | 37.9% | 45.4% |
| 70% | 16p | 20.2% | 29.6% | 37.7% | 45.3% |
| | *uncovered share, CL 75%* | **24.4%** | **36.8%** | **47.4%** | **57.0%** |

At ρ = 0.70 — an entirely ordinary value for a single-soil-type farm — **SCO fails to pay in
38% of the years the producer has a real loss in the band, and leaves 47% of that loss
uncovered.**

### 6.4 The two returns

| ρ | E[payment] per $1 liab | producer $ per $1 liab | **gross return** | **risk-transfer return** |
|---:|---:|---:|---:|---:|
| 0.95 | 0.4721 | 0.0944 | 5.00× | **4.44×** |
| 0.90 | 0.4721 | 0.0944 | 5.00× | **4.22×** |
| 0.80 | 0.4721 | 0.0944 | 5.00× | **3.90×** |
| 0.70 | 0.4721 | 0.0944 | 5.00× | **3.66×** |
| 0.60 | 0.4721 | 0.0944 | 5.00× | **3.47×** |
| 0.50 | 0.4721 | 0.0944 | 5.00× | **3.32×** |

(E[payment] rescaled to the measured ECO-RP premium rate so the dollar figures are real; the
model supplies only the windfall share.)

**The gross return is flat at 5.00× by construction. The risk-transfer return falls by a
third across the plausible range of ρ.** The difference — the "windfall share", 11% to 36% of
all payments — is money arriving in years the farm had no in-band loss. That money is real
and spendable. But it is a **transfer, not insurance**, and it is exactly offset by the
symmetric years when the loss arrived and the cheque did not.

**The honest summary: an 80%-subsidised area band is an excellent subsidy capture and a
mediocre-to-good hedge.** Both statements are true at once, and a producer should decide
which one they are buying. A producer who is capturing subsidy should buy the widest band
available (ECO at the 95% trigger) and not care about ρ. A producer who genuinely needs the
loss covered — thin margins, high leverage, an operating lender who will not wait — should
weight individual-triggered coverage (a higher underlying coverage level, WFRP where
eligible, PACE where applicable) more heavily than the raw return numbers suggest, and should
treat ECO/SCO as supplementary income rather than as the thing standing between them and a
bad year.

---

## 7. What I could not verify

Listed so nothing above is read as better-sourced than it is.

**Data / computation**

1. **No realized loss ratios.** `sob_sales` holds a single crop year (2026) and every
   `indemnity` value is 0.0 — the year is incomplete. Every "expected return" figure in §5
   therefore rests on the assumption that RMA rates are actuarially fair (loss ratio 1.0).
   Historical loss ratios by plan would move the ranking and are not in this repo.
2. **SCO/ECO area rates and payment factors are not loaded.** The only `A01130
   AreaCoverageLevel` / `A01135 AreaRate` files in `data/cache/adm/` are daily deltas that
   contain **Rainfall Index (plan 13) records only** — offer IDs 36,505,703–36,771,444, all
   plan 13. I could not compute SCO/ECO base rates or published payment factors directly.
   The band widths in §1.2 were derived indirectly, from SoB liability ÷ ADM expected
   revenue, and the producer costs in §1 come from realized SoB premium rather than ADM
   rates.
3. **Cotton band measurements are unreliable.** STAX measures 33 implied coverage points
   against a structural maximum of 24, and SCO-cotton 38 points. The A00810 `Expected Revenue
   Amount` basis for cotton does not reconcile with the SoB liability basis. All cotton rows
   from `implied_band_width.py` are excluded from conclusions.
4. **The model under-prices the ECO band by 5–7%** at every plausible yield CV (§6.3). I did
   not resolve whether this is rating load, adverse selection, or a defect in the assumed
   yield marginal.
4a. **The irrigation rate gap (§5.3, §6.1) uses only the Reference Rate term.** RMA's
   continuous rating formula also carries a practice-specific fixed rate and exponent, and
   the coverage-level differential factors are in an ADM table not loaded here. The ratios
   are indicative of magnitude, not an exact rate comparison. Roughly half of corn and wheat
   counties publish an identical reference rate for both practices and are excluded.
5. **ρ is not estimated from data.** No farm-level or county-level yield history is in this
   repo. §6 sweeps ρ rather than estimating it. A producer-specific answer requires that
   producer's APH against NASS county yields.
6. **TA-APH is not quantified.** It is a 508(h) product in the catalog that scales the
   approved yield underneath the entire stack, and it is arguably the highest-return item in
   the layer. No band, so it did not fit the framework used here; it deserves its own pass.
7. **WFRP has no acres in the SoB** (`net_acres` = 0 for all 95 rows), so per-acre WFRP
   figures could not be computed.

**Rules / sources**

8. **PACE subsidy percentages are not published by RMA** in any fact sheet, FAQ or
   endorsement — the endorsement points to the Actuarial Documents (§10(a)(7)). The
   0.60/0.51/0.41 schedule in §3.6 is **computed from the loaded ADM `A00070`**, not quoted
   from RMA prose.
9. **Whether SCO or ECO may be carried on WFRP acreage — no RMA statement found either way.**
   FCIC-18160 has zero hits for "Supplemental Coverage", "Enhanced Coverage", "SCO" or "ECO";
   the ECO FAQ says nothing about WFRP. The `?` cells in the matrix are genuine unknowns, not
   omissions. Inference (untested): SCO/ECO attach to the underlying CCIP policy, ¶123(1)
   permits that policy to coexist with WFRP, so they would ride along with their indemnities
   flowing into RTC. **Do not rely on this without confirmation.**
10. **PACE's compatibility with SCO/ECO/MCO** — likewise not found in either direction.
11. **ECO × STAX for CY2026** — 21-ECO and the July-2024 fact sheet say prohibited; the
    July-2026 FAQ says permitted. I read the FAQ as CY2027 and 21-ECO as controlling for
    CY2026, but **found no RMA document reconciling them**.
12. **ARC-CO vs ARC-IC** — no source distinguishes them for SCO purposes. Moot for 2026 since
    the bar is repealed, but it was never verified for prior years.
13. **The WFRP commodity-count × coverage-level subsidy matrix** that FCIC-18160 ¶53(4)
    asserts lives in the Actuarial Documents. The loaded ADM `A00070` shows only a
    coverage-level dimension for plan 76.
14. **RMA's own September 2025 WFRP fact sheet contradicts itself** — page 1 says
    single-commodity farms get an *enterprise* premium subsidy, page 4 says *"all farms
    insured under WFRP receive a whole-farm premium subsidy."* Unresolved.
15. **No newer STAX Crop Provisions than 23-STAX-0021**, no newer STAX handbook than
    FCIC-18170 (Nov 2021), and no 2026-specific PACE form or bulletin (newest are
    23-PACE-20660 and PM-22-075). These were treated as controlling for 2026 but that was not
    affirmatively confirmed by a bulletin.
16. **The amended 2026 CIH (FCIC-18010-1, 08-2025)** — the ARC/SCO repeal was verified in the
    *2027* handbook (complete download, zero "Agriculture Risk Coverage" hits). The 2026
    amended handbook's ¶916/917 body text was not read directly.
17. **MP's 2026 subsidy schedule** — the 0.59/0.55/0.49/0.44 factors come from RMA's
    September 2023 FAQ and are confirmed by the 2026 ADM, but no 2026-dated RMA prose
    restates them. MGR-25-006 does not list MP among the products raised to 80%.
18. **Plan-code assignments** (MP=16/17, MCO=67/68/69, PACE=26/27/28) could not be confirmed
    from RMA prose. They **are** confirmed from the loaded 2026 ADM `A00460 InsurancePlan`
    table, which is the authoritative machine-readable source and is what §1 relies on.
19. **County-level availability** for every product must be confirmed in the Actuarial
    Information Browser. RMA's PACE fact sheet and FAQ disagree on whether all counties in all
    eleven states are eligible.

---

## 8. Reproducing this

```
.venv/bin/python scripts/analysis/endorsement_economics.py --csv-dir output/endorsement_analysis
.venv/bin/python scripts/analysis/implied_band_width.py
.venv/bin/python scripts/analysis/basis_risk.py --draws 250000
.venv/bin/python scripts/analysis/endorsement_bands.py        # ADM subsidy + 508H flag audit
```

Inputs: `data/catalog.db` (`sob_sales`, `products`, `product_crops`) and
`data/cache/adm/2026_A000{30,70,460},A008{10},A010{10}_*.txt`.

### Primary sources cited

| | document | URL |
|---|---|---|
| SCO | Supplemental Coverage Option Endorsement, **20-SCO** (Jun 2019) | rma.usda.gov/sites/default/files/crop-policies/Supplemental-Coverage-Option-20-SCO.pdf |
| SCO | **27-SCO** (Jun 2026, CY2027) | rma.usda.gov/sites/default/files/2026-06/SCO%20Endorsement%2027-SCO.pdf |
| SCO | Crop Insurance Handbook **FCIC-18010** (06-2025), ¶916 | rma.usda.gov/sites/default/files/2026-06/2026-18010-Crop-Insurance-Handbook.pdf |
| ECO | Enhanced Coverage Option Endorsement, **21-ECO** | rma.usda.gov/sites/default/files/crop-policies/Enhanced-Coverage-Option-Endorsement.pdf |
| ECO | **PM-20-078** (Nov 2020) | rma.usda.gov/policy-procedure/bulletins-memos/product-management-bulletin/2020/pm-20-078-enhanced-coverage |
| OBBBA | **MGR-25-006**, One Big Beautiful Bill Act Amendment (Aug 2025) | rma.usda.gov/policy-procedure/bulletins-memos/managers-bulletin/mgr-25-006-one-big-beautiful-bill-act-amendment |
| OBBBA | **25-OBBA**, One Big Beautiful Amendment | rma.usda.gov/sites/default/files/2025-09/25-OBBA-One-Big-Beautiful-Amendment.pdf |
| OBBBA | P.L. 119-21 §§10303(b), 10502 | govinfo.gov/content/pkg/BILLS-119hr1enr/html/BILLS-119hr1enr.htm |
| STAX | Cotton Crop Provisions **23-STAX-0021** | rma.usda.gov/sites/default/files/crop-policies/Stacked-Income-Protection-Plan-Cotton-Crop-Provisions-23-STAX-0021.pdf |
| STAX | **7 U.S.C. 1508b** (esp. (d), (f)) | uscode.house.gov |
| STAX | Fact Sheet (Jan 2024) | rma.usda.gov/sites/default/files/2024-08/Stacked-Income-Protection-Plan-STAX-for-Upland-Cotton.pdf |
| MP | **25-MP** Margin Protection Plan Provisions | rma.usda.gov/sites/default/files/2024-06/Margin-Protection-Plan-25-MP.pdf |
| MP | Fact Sheet (Mar 2023); MP FAQ (Sep 2023) | rma.usda.gov/policy-procedure/general-policies/margin-protection |
| MCO | **PM-25-029** (Apr 2025) | rma.usda.gov/policy-procedure/bulletins-memos/product-management-bulletin/pm-25-029-margin-coverage-option |
| MCO | **26-MCO** Endorsement | rma.usda.gov/sites/default/files/2025-04/Margin%20Coverage%20Option%20Endorsement%2026-MCO.pdf |
| MCO | Insurance Standards Handbook **FCIC-20700U** | rma.usda.gov/sites/default/files/2026-06/Margin%20Coverage%20Option%20Insurance%20Standards%20Handbook_0.pdf |
| PACE | **23-PACE-20660** Endorsement | rma.usda.gov/sites/default/files/2024-07/Post-Application-Coverage-Endorsement-23-20660.pdf |
| PACE | Fact Sheet (Dec 2024) | rma.usda.gov/sites/default/files/2024-02/Post-Application-Coverage-Endorsement-Fact-Sheet.pdf |
| HIP-WI | **26-HIP-WI-TS** Endorsement (Apr 2025) | rma.usda.gov/sites/default/files/2025-04/2026%20HIP-WI-TS%20Endorsement%20v3_0.pdf |
| HIP-WI | **PM-25-023** (Apr 2025) | rma.usda.gov/policy-procedure/bulletins-memos/product-management-bulletin/pm-25-023-hurricane-insurance |
| WFRP | 2026 WFRP Pilot Handbook **FCIC-18160** (Sep 2025) | rma.usda.gov/sites/default/files/2025-09/2026-18160-WFRP-Pilot-Handbook.pdf |
| WFRP | Fact Sheet (Sep 2025) | rma.usda.gov/sites/default/files/2024-02/Whole-Farm-Revenue-Protection-Fact-Sheet.pdf |
