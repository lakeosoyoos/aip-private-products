# The Private Side of Row-Crop Protection

**What the non-reinsured half of the market actually covers, what it costs, and when it is
worth buying alongside a federal policy.**

Author: research pass, 2026-08-07. Companion to `docs/producer_decision_research.md`, which
does the same job for LRP and DRP.

---

## 0. How to read this document

Every factual claim is tagged:

- **[V]** — verified against a primary source (statute, RMA bulletin, state DOI guidance
  document, or a carrier's own published policy description). URL given.
- **[C]** — computed by me from `data/catalog_app.db` in this session. Every number tagged
  `[C]` is reproduced by `scripts/analysis/private_products_profile.py`, which is read-only
  and prints the whole set:

  ```
  .venv/bin/python scripts/analysis/private_products_profile.py
  .venv/bin/python scripts/analysis/private_products_profile.py --only economics
  ```

- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis.

### Scope boundary

**This document is about legally choosing and combining products.** Every mechanism described
here is a purchase decision a producer makes at signup with accurate information about their
own operation.

Misrepresenting acres, yields, practices, planting dates, unit structure, or shares in order to
qualify for or enlarge a payment is **fraud**, and so is presenting a single physical loss to
two carriers in a way that recovers more than the loss. Nothing below turns on doing either.
Where two policies can legitimately both pay on the same storm — and §5 shows that they
sometimes can, by design — that is a feature of the *forms as filed*, not a workaround, and it
is bounded by the actual-cash-value cap inside the crop-hail policy itself.

### The one-sentence version

> A federal product's edge for the producer **is the premium subsidy**. A private product has
> no subsidy and must also cover the carrier's expenses out of the same premium dollar, so its
> expected indemnity per producer dollar is **below 1 by construction**. Private products are
> therefore never "a better deal"; they are worth buying only where the federal policy does not
> reach at all, or as a deliberate variance trade at a known cost.

---

## 1. What is actually in the catalog

The database holds **182 products**: 166 in `bucket='private'`
(`program='private_nonreinsured'`) and 16 in `bucket='508h'`. **[C]**

```
private  private_nonreinsured   166
508h     federal_508h            12
508h     federal_farm_bill        2
508h     federal_rma              2
```

Those two buckets are in **different economic categories** and §3 is devoted to why.

### 1.1 The private bucket by stack layer

Classified with `src.stack.classify()` — the same deterministic rule set the app's "Stack"
sheet uses, reused here rather than inventing a second vocabulary. **[C]**

| Layer (from `src/stack.py`) | n | Subsidized? |
|---|---:|---|
| 4. Standalone named-peril | 76 | **No — farmer pays 100%** |
| 3. Private bands / buy-ups | 37 | **No** |
| 5. Utility endorsements | 27 | **No** |
| 6. Other / unclassified | 26 | **No** |

Nothing lands in layers 1, 2, 2a or 2b — those are federal by definition, and `classify()`
deliberately leaves unmatched private products in `other` rather than forcing them into a
layer. The 26 in `other` are mostly whole *programs* rather than single covers (REVCO, APCO,
Select Programs, Xtra Bundle, Weather Insurance Policy, Biotech Yield Assurance).

### 1.2 By AIP

Twelve AIPs carry private row-crop products. **[C]**

| AIP | named-peril | private band | endorsement | other | total |
|---|---:|---:|---:|---:|---:|
| Rural Community Insurance Company (EF/RCIS) | 18 | 3 | 8 | 2 | **31** |
| ACE American Insurance Company (RH/Rain and Hail) | 15 | 0 | 6 | 2 | **23** |
| Producers Agriculture Insurance Company (PL/ProAg) | 9 | 6 | 3 | 4 | **22** |
| Great American Insurance Company (GA) | 11 | 5 | 2 | 3 | **21** |
| Hudson Insurance Company (HU) | 5 | 6 | 1 | 5 | **17** |
| NAU Country Insurance Company (NA) | 4 | 7 | 1 | 1 | **13** |
| American Agri-Business Insurance Company (WN/Rain & Hail–AgriBusiness) | 2 | 3 | 1 | 6 | **12** |
| Farmers Mutual Hail Insurance Company of Iowa (FH) | 6 | 2 | 2 | 1 | **11** |
| Country Mutual Insurance Company (CM) | 3 | 2 | 2 | 0 | **7** |
| Clear Blue Insurance Company (CP) | 1 | 1 | 1 | 1 | **4** |
| American Agricultural Insurance Company (FA/Farm Bureau) | 1 | 2 | 0 | 0 | **3** |
| Palomar Specialty Insurance Company (PS) | 1 | 0 | 0 | 1 | **2** |

Two shapes of company are visible. **[R]** Rain and Hail (RH) and RCIS (EF) are *hail houses*
— deep named-peril and endorsement menus, almost no private bands. NAU and Hudson are *band
houses* — thin hail menus, the richest supplemental-band shelves. ProAg and Great American run
both. This matters for product selection: the private band you want and the hail form you want
may not live at the same AIP, and moving the MPCI policy to get a private product is exactly
the behavior MGR-18-005 (§4.2) was written about.

### 1.3 By peril and coverage type

**[C]** `peril_type`: hail 49, unclassified 40, revenue 23, fire 14, replant 11, wind 8,
named-peril 8, freeze 7, rain 3, margin 2, area 1.
`coverage_type`: unclassified 57, endorsement 37, named-peril 36, supplemental 32, gap 2,
bundle 2.

**Hail plus fire is 63 of 166 rows (38%)** — the largest single block, before counting the
wind/green-snap and replant endorsements that ride on a hail policy. **[C]**

### 1.4 Reach

**[C]** 104 of 166 private products carry at least one state row; 69 carry at least one crop
row; **zero** carry county rows — correctly, because private products are filed and approved
**statewide**, not by county (`src/db.py` documents this design decision explicitly).

Private products appear in **47 states**, but the mass is the Corn Belt and northern Plains:
IA 67, NE 63, IL 63, WI 61, IN 59, SD 58, MO 58, KS 57, OH 55, ND 55.

Crops named: Corn 35, Soybeans 25, Cotton 12, Wheat 11, Hay/Forage 10, then a specialty tail
(Citrus 6, Pasture/Rangeland 5, Tobacco 4, Rice 4, Tomatoes 3, Sugar Beets 3, Grain Sorghum 3,
Almonds 3).

### 1.5 How much of this is verified — read this before trusting any number below

**[C]** Provenance of the 166 private rows:

| source_type | n | verified |
|---|---:|---|
| `aip_site` | 124 | 0 |
| `serff_derived` | 30 | 0 |
| `manual_seed` | 7 | **1** |
| `brochure_derived` | 5 | 0 |

**Only 7 of 166 private rows (4.2%) carry `verified=1`.** The catalog is a *menu*: it is a
reliable record of **which AIP advertises which product in which state**, harvested from the
AIPs' own public product pages and from SERFF filing titles. It is **not** a term sheet. It
contains no rates, no deductible tables, no policy forms, no limits, no exclusions. Every
statement in this document about *how a product works* comes from a carrier's published
description or a regulator's document, cited inline — never from the database.

---

## 2. The central economic difference

### 2.1 The identity

For any insurance product, define the **target loss ratio** TLR = E[indemnity] / gross premium
that the rate is built to hit. Then:

```
E[indemnity] / producer_premium  =  TLR / (1 − subsidy_share)
```

That is arithmetic, not modelling. Everything in this document falls out of it.

**Federal side.** Two things are true simultaneously:

1. FCIC is required by statute to set rates "to achieve an overall projected loss ratio of not
   greater than 1.0" — 7 U.S.C. §1506(n)(2). **[V]**
   <https://uscode.house.gov/view.xhtml?req=(title:7%20section:1506%20edition:prelim)>
2. The statutory definition of "loss ratio" measures indemnities against "that portion of the
   premium designated for anticipated losses and a reasonable reserve, **other than that
   portion of the premium designated for operating and administrative expenses**." **[V]**
   The AIP's delivery cost is reimbursed **separately** by FCIC (A&O under the Standard
   Reinsurance Agreement) and is *not* loaded into what the producer pays. So on the federal
   side, essentially the whole gross premium is available to pay losses, and TLR ≈ 1.0 (a
   little under, for the reserve).

Therefore, for a federal product, `E[indemnity] / producer dollar ≈ 1 / (1 − s)`.

**Private side.** `s = 0`, and the expense and profit load comes out of the *same* premium
dollar the producer pays. Nebraska DOI's crop-hail filing guidance describes exactly this
construction: the filed rate equals the advisory loss cost times a **loss cost multiplier**,
which equals the **expense multiplier** (production expenses, general expenses, LAE, taxes,
licenses and fees, plus "a reasonable profit provision [that] reflects insurance risk and the
insurer's cost of capital") times any loss-cost deviation. **[V]**
<https://doi.nebraska.gov/sites/default/files/doc/IGD%20-%20-%20C13.pdf>

So `TLR_private = 1 / (1 + expense&profit load) < 1`, necessarily, and
`E[indemnity] / producer dollar = TLR_private < 1`.

### 2.2 The size of the gap, computed

`sob_sales` holds the RY2026 sold book for every federal supplemental plan. **[C]**

| plan | acres (M) | liab/ac | gross prem/ac | subsidy | producer/ac | E[ind] per producer $ |
|---|---:|---:|---:|---:|---:|---:|
| ECO-RP | 99.80 | $61 | $28.90 | 80.5% | $5.64 | **5.12×** |
| SCO-RP | 56.77 | $59 | $15.04 | 80.4% | $2.95 | **5.10×** |
| HIP-WI | 6.74 | $143 | $28.90 | 80.3% | $5.69 | **5.08×** |
| MCO-RP | 1.89 | $63 | $32.63 | 80.4% | $6.38 | **5.11×** |
| ECO-YP | 1.01 | $59 | $14.63 | 80.2% | $2.90 | **5.04×** |
| SCO-YP | 0.74 | $95 | $8.84 | 80.1% | $1.76 | **5.03×** |
| MP-HPO | 0.27 | $1,056 | $61.78 | 44.3% | $34.43 | **1.79×** |
| STAX-RP | 0.19 | $90 | $39.68 | 80.0% | $7.95 | **4.99×** |

The 80% subsidy share on SCO/ECO/MCO/STAX is *computed from the sold book*, and it confirms
the post-July-2025 schedule that `src/stack.py` already documents. **[C]**

Against that, the private side. The Insurance Information Institute's archived NCIS crop-hail
tables report crop-hail loss ratios ranging **44 to 122** over 2004–2015 on direct premiums of
roughly $0.4B–$1.0B. **[V]** <https://www.iii.org/table-archive/20674> A long-run TLR in the
**0.55–0.80** range is the honest bracket, and it is what the script uses.

**Headline, on corn ECO-RP — the band that private products imitate most: [C]**

- Federal: **$7.31/ac** of producer money buys **$79/ac** of band. E[ind] per dollar **5.12×**
  (**4.61×** if the realized loss ratio is 0.90 rather than the statutory 1.00 ceiling).
- Private, for the *same* band: the carrier must charge at least the **$37.43/ac** gross,
  plus load. E[ind] per dollar **0.55–0.80×**.
- **The federal band is 5.8× to 9.3× better per producer dollar. A private carrier must charge
  at least 5.1× what the producer pays federally, for identical protection.**

### 2.3 What follows, stated bluntly

**A private product cannot beat a federal product on expected value where the two cover the
same thing.** Not "usually doesn't" — cannot. The subsidy is a transfer the private carrier
does not receive and cannot replicate.

So the value of a private product, when it exists, comes from exactly four places, and it is
worth naming them precisely because they are commonly blurred together in marketing:

1. **A peril or intensity band the federal policy excludes or dilutes** — spot hail, wind and
   green snap, fire, freeze, replant beyond the federal allowance, quality/grade rejection.
2. **Buying down the federal deductible** — the most expensive band in the whole structure to
   self-insure, because it is the one that gets hit most often.
3. **Timing gaps** — early-season binder coverage, post-application windows, alternative price
   discovery windows.
4. **Variance reduction rather than mean improvement** — a legitimate reason to buy
   negative-expected-value insurance, and it must be argued as such.

Item 4 deserves to be said out loud, because it is the true economic description of most of
this market. **Buying crop-hail is a variance trade, not an expected-return trade.** It is
rational when (a) the loss is large relative to the operation's equity, so concave utility
makes the certainty equivalent worth more than the load, or (b) it unlocks something worth more
than the load — lender collateral, or the ability to forward-sell bushels that would otherwise
have to be bought back at a spike price after a spot loss. Both are real. Neither is "a better
deal than the federal policy," and any presentation that says a private product **raises
expected return** is wrong unless it explicitly identifies which constraint is being relaxed
and prices that relaxation.

---

## 3. The 16 508(h) products — the most confusing thing in this market

**A 508(h) product is privately *developed* and federally *reinsured and subsidized*. It sits
on the federal side of the line drawn in §2, not the private side.** This is the single
distinction most often lost, including in AIP marketing, because both categories get described
as "private products."

Under §508(h) of the Federal Crop Insurance Act, a private party may submit a policy, policy
provisions, or premium rates to RMA. Submissions are accepted in the first five business days
of January, April, July and October; they go to five external reviewers plus internal RMA
review; and the FCIC Board votes to approve or disapprove. Approved products become "eligible
for reinsurance and potential subsidy to producers," the developer is reimbursed for reasonable
research and development expenses, and up to four years of maintenance expenses are covered,
after which the developer may charge user fees or transfer the product to FCIC. **[V]**
<https://www.rma.usda.gov/about-rma/fcic/private-sector-developed-plans>

The 16 in the catalog, all `verified=1`: **[C]**

| Product | Developer | Plan code(s) |
|---|---|---|
| Supplemental Coverage Option (SCO) | USDA RMA (2014 Farm Bill, statutory) | 31;32;33 |
| Enhanced Coverage Option (ECO) | Watts and Associates | 87;88;89 |
| Margin Coverage Option (MCO) | Watts and Associates | 67;68;69 |
| Stacked Income Protection Plan (STAX) | USDA RMA (2014 Farm Bill, statutory) | 35;36 |
| Margin Protection (MP) | Watts and Associates | 16;17 |
| Whole-Farm Revenue Protection (WFRP) | USDA RMA | 76 |
| Hurricane Insurance Protection – Wind Index (HIP-WI) | USDA RMA | 37 |
| Post-Application Coverage Endorsement (PACE) | Zea Mays Foundation (G. Schnitkey, U. Illinois) w/ Ag-Analytics | 26;27;28 |
| Trend-Adjusted APH Yield Endorsement (TA-APH) | iFAR / U. Illinois (B. Sherrick) | — |
| Downed Rice Endorsement | AgriLogic Consulting | — |
| Cottonseed Endorsement | Watts and Associates | — |
| Malting Barley Revenue Endorsement | Watts and Associates | — |
| Specialty Soybeans | Watts and Associates | — |
| Peanut Revenue | AgriLogic Consulting | — |
| Popcorn Revenue | Watts and Associates | — |
| Pulse Crop Revenue | Watts and Associates | — |

Note that four of these are RMA/farm-bill products living in the `508h` bucket rather than
true §508(h) submissions — the bucket is "privately-developed *or* federally-authored
non-base plan," which the `program` column separates (`federal_508h` 12, `federal_farm_bill`
2, `federal_rma` 2). **[C]**

**Why the distinction is economically load-bearing.** Look back at §2.2. Every 508(h) product
in that table returns **more than 1× per producer dollar**, because every one of them is
subsidized — but the multiple varies enormously with the subsidy schedule, not with who wrote
the product:

- ECO / SCO / MCO / STAX at ~80% subsidy → **~5×** **[C]**
- WFRP at 68.2% subsidy → **~3.1×** **[C]**
- Margin Protection (MP-HPO) at 44.3% subsidy → **~1.79×** **[C]**
- PACE-RP at 44.1% subsidy → **~1.79×** **[C]**

Every private product in §1 returns **less than 1×**. **The dividing line is the subsidy, not
the authorship.** A producer choosing between "MPowerD" (private, Great American / NAU / ProAg
/ Hudson / RCIS) and "MCO" (508(h), every AIP) is not choosing between two similar things: MCO
returns roughly 5.1× per producer dollar and MPowerD cannot return more than about 0.8×.
**Exhaust the subsidized 508(h) shelf before buying its private imitation.** **[R]**

---

## 4. Category-by-category

### 4.1 Crop-hail — the anchor of the private market

Hail plus fire is 38% of the private catalog by row count. **[C]**

**What it is.** A named-peril policy paying **acre by acre** on the *percent of physical damage*
to the crop, up to a dollar limit of liability the producer elects, typically up to the crop's
actual cash value. It is written on a separate application from MPCI, it is state-regulated, and
it is not reinsured by FCIC.

**Why acre-by-acre is the whole point.** From ProAg's own product page: **[V]**
<https://www.proag.com/products/crop-hail/annual-crop-hail-policies/>

> "Hail is one catastrophe that is most likely to totally destroy a part of your crop and leave
> the rest undamaged. The acres and loss of crop yield caused by hail damage may be less than
> the deductible of your federal crop insurance policy… Crop hail is especially important to
> those with area plan policies, like ARP, ARP-HPE, or AYP, which leaves individuals exposed to
> spot losses due to hail."

That is the honest case, from a seller, and §5.2 shows it is arithmetically correct.

**The four plan structures**, using Great American's published menu, which is representative of
the industry. **[V]** <https://greatamericancrop.com/products---policies/crop-hail-products>

| Structure | Deductible | Mechanism |
|---|---|---|
| **Basic hail** | none | Pays physical hail damage from the first percent, up to actual cash value, acre by acre. Most expensive per dollar of liability. |
| **Deductible hail** | 5%–30% elected | Pays once damage exceeds the elected deductible. Some forms offer *increased payment factors* or a *disappearing deductible* so the deductible erodes as damage grows. |
| **Companion hail** | 0%–15% | Explicitly written to cover **the portion of the crop MPCI does not protect**. Applies a multiplier once damage exceeds the deductible; indemnity capped at 100%. |
| **Production plan** | — | Unit-based rather than acre-based. Pays the **lesser of field loss or production loss**. |

**The companion plan is the one to understand mechanically**, because it is the private
product most deliberately engineered *against* the federal deductible. Rain and Hail publishes
the actual factor table for its Companion Plan Insert (CP): **[V]**
<https://www.rainhail.com/d/ps/coverages/crop-hail>

> "Designed to cover that portion of the crop not covered by a policy reinsured or approved by
> FCIC… contains increasing payment factors, which match up with the various coverage levels"

| FCIC coverage level | Increasing payment factor | Elected limit not to exceed market value of |
|---:|---:|---|
| 50% | 2.0 | top half of the crop |
| 65% | 3.0 | top third of the crop |
| 75% | 4.0 | top quarter of the crop |

Read that table carefully: **the factor is the reciprocal of the uninsured band.** At 75% MPCI
coverage the uninsured top quarter is 25% of the crop, so a 1%-of-crop hail loss is 4% of the
band, and the factor is 4.0. The companion plan is a *leveraged* cover on precisely the
deductible band, sized so that a total loss of the band pays the band's full value. It is a
genuinely well-engineered complement, and its design is why it does not double-pay: it insures
the band the federal policy is *not* insuring.

Availability of that specific form: AZ, CO, ID, IL, IN, IA, KS, MI, MN, MO, MT, NE, ND, OH, OK,
OR, SD, TX, WA, WI, WY. **[V]** (same page)

**The production plan** is the other structurally interesting form. FMH describes it as "a Crop
Hail insurance endorsement that is coupled with your federally-subsidized MPCI policy," covering
"the portion of your crop that is left unprotected by your MPCI policy," written at **110–120%
of the insured's APH**, settled **on the MPCI unit basis**, and — critically — "the final hail
loss calculation cannot be completed until harvest when the actual production to count is
known." **[V]**
<https://www.fmh.com/insurance/crop-hail/crop-hail-products/production-plan>

That last clause is the trade-off. A per-acre hail policy pays on the appraised damage
regardless of what the rest of the field does; a production plan nets the damage against actual
harvested production, so a hail loss that the crop grows out of pays nothing. It costs less
because it pays less often. **[R]** A producer whose real fear is a total loss on a portion of
a unit should prefer the acre-based form; a producer whose fear is a genuine bushel shortfall
should prefer the production plan.

**Interaction with the federal policy's hail coverage.** MPCI *does* cover hail — hail is an
insurable cause of loss under the Common Crop Insurance Policy. The reason crop-hail exists
anyway is **not** that hail is excluded federally; it is that federal settlement is on a
**unit** basis against a **deductible**, and hail is the peril most likely to produce a large
loss on a small share of a unit. See §5.2 for the arithmetic.

Two form features make the two policies stack cleanly rather than offset, and they are
advertised as such. FMH: **"NO PRO RATA CLAUSE — Other insurance does not affect hail
payment,"** and **"NO REPLANT CLAUSE — FMH pays the loss."** **[V]**
<https://www.fmh.com/insurance/crop-hail/crop-hail-products/crop-hail> The federal side is symmetric: MPCI settles on
production to count, which a crop-hail recovery does not change. So both can pay on one
storm, by design of both forms, bounded by the crop-hail policy's own actual-cash-value cap.

**When is it worth buying?** [R] The conditions, in order of how much they matter:

1. **You are on enterprise units or area plans.** This is decisive; §5.2 quantifies it.
2. **You have forward-sold bushels.** A spot loss creates a short physical position you must
   buy back. Crop-hail converts that exposure to cash on the acres actually hit.
3. **Your ground is genuinely in a hail corridor** — and note that crop-hail is rated on NCIS
   township-level Final Average Loss Costs (§6.2), so the price already reflects that; you are
   not getting a bargain by being in a hail alley, you are paying for it.
4. **A lender requires it**, in which case the load is a financing cost, not an insurance
   decision.

If none of these hold, you are paying 1.25×–1.8× the pure loss cost to reduce a variance you
may already be able to carry.

### 4.2 Named-peril and supplemental / gap covers

Beyond hail proper, the catalog holds standalone named-peril covers for **fire (14), wind (8),
freeze (7), rain (3)**, plus 8 rows explicitly typed `named-peril`. **[C]** Representative:
Corn Wind and Wind–wheat and cotton (RCIS), Wind and Green Snap (Great American), Green Snap
(FMH, COUNTRY), Corn/Seed Corn/Sweet Corn Wind Endorsement and Cotton Wind and Small Grain Wind
(Rain and Hail), Hurricane Wind Endorsement (NAU, Hawaii), Pasture Fire (FMH, NAU, ProAg,
RCIS), Field Grain Fire, Hay Fire, Barn Fire, Cotton Module fire, Tobacco Theft (Rain and Hail),
Winterkill (Great American).

Green snap is the clearest example of a genuine federal gap. **[R]** Straight-line wind that
snaps corn stalks at a node is a physical loss that MPCI covers as an insurable cause but only
through the same unit-and-deductible filter as everything else, and it is intensely localized —
the classic case of a total loss on 60 acres of a 900-acre unit.

**MGR-18-005 and what "CHNP" means.** The RMA bulletin the task names is the primary source for
how RMA itself characterizes this category. It was issued 2018-05-25 in response to Crop Pro
Insurance Services / GuideOne cancelling Crop Hail Named Peril policies for failure to obtain
reinsurance. Its background paragraph is the cleanest official statement of the boundary: **[V]**
<https://legacy.rma.usda.gov/bulletins/managers/2018/mgr-18-005.pdf>

> "The Risk Management Agency (RMA) has evaluated the current situation related to
> privately-owned supplemental crop insurance policies referred to as Crop Hail Named Peril
> (CHNP) policies… **CHNP policies are not Federally-reinsured or subsidized policies.**
> However, these producers may have moved their Federally-reinsured Multi-Peril Crop Insurance
> (MPCI) policy to CropPro and Guide One Insurance Company in an effort to obtain the CHNP
> policy or changed their MPCI coverage in anticipation of receiving the CHNP coverage."

And the action paragraph:

> "The actions outlined below relate to MPCI policies only and do not affect the private CHNP
> policies. CHNP policies are not subsidized or reinsured by FCIC. **No AIP is required to
> accept any liability for these CHNP policies.**"

The relief RMA granted was narrow and entirely on the federal side: producers had 15 business
days to withdraw an unprocessed MPCI transfer and return to their prior AIP on 2017 terms, or
to void a processed transfer and have it treated as a change-of-coverage form, or to stay put.

**Three things follow from this bulletin, and they are the most important risk disclosures in
this entire document:**

1. **Counterparty risk is real and asymmetric.** The federal book was never in doubt — "The
   coverage of the Federally-reinsured MPCI crop insurance policies remains in effect and any
   insured losses will be paid." The private book evaporated mid-season on 60 days' notice.
   A private product is only as good as one carrier's reinsurance treaty. **[V]**
2. **Chasing a private product by moving the MPCI policy is a real and documented failure
   mode.** The whole bulletin exists because producers moved a subsidized 5× policy to obtain
   an unsubsidized sub-1× policy, and then lost the latter. **[V]** Per §2.3, the tail should
   never wag that dog.
3. **RMA will not backstop the private side.** It will unwind federal-side consequences and
   nothing more.

### 4.3 Replant, late-plant, and extra harvest expense

**[C]** 11 products typed `replant`, plus late-plant and extra-harvest-expense endorsements:
Replant Option (RCIS, Clear Blue, NAU, AgriBusiness), Replant Premier (FMH), Replant Coverage
(Great American), Supplemental Replant Coverage (ProAg), Corn and Soybean Replant and Winter
Wheat Replant (Rain and Hail), Early Bird Replant Option and Tomato Replant Option (RCIS),
Replant Endorsement (COUNTRY); Late Plant Option (RCIS); Extra Harvest Expense (RCIS, FMH,
Great American, COUNTRY) and Almond Extra Harvest Expense (ProAg); Harvested Stored Grain
(RCIS).

**What the federal policy already does.** The Common Crop Insurance Policy pays a replant
payment only when replanting is practical, the damage exceeds a threshold share of the unit,
and the payment is a **capped per-acre allowance**, not the actual cost of replanting. The
private replant endorsements are sold to (a) pay from the **first acre** rather than after a
unit-level threshold — Great American states its Replant Coverage Endorsement "provides
protection on the very first acre of loss" **[V]** — and (b) top up the per-acre allowance
toward true replant cost.

**When worth buying.** [R] This is the private category with the *tightest* and most defensible
case, for a structural reason: replant is a **high-frequency, low-severity, capped** exposure.
The load a carrier charges is a percentage of a small expected loss, so the absolute dollars at
risk from the negative EV are small, while the timing benefit — cash in hand in May, when the
replanting decision must actually be made — is real. It is still negative-EV. It is just
negative-EV on a small number, in exchange for liquidity at the moment of decision.

Extra Harvest Expense is a different animal: it pays the incremental cost of picking up a
downed crop, an expense the federal policy does not reimburse at all because MPCI insures
production, not cost. That is a **true gap**, not a buy-down.

### 4.4 Quality, grade, and rejection

**This is the thinnest part of the catalog, and the doc should say so.** **[C]** Searching all
166 private rows for quality-related terms returns only: Rename Reject Coverage (Rain and Hail),
Seed corn reject and ELS Cotton Grade (RCIS), Germination Coverage for Hybrid Seed Corn (Rain
and Hail), Raisin Reconditioning (RCIS, ProAg), Canning and Processing Tomatoes (Rain and Hail).
**Zero rows mention vomitoxin, DON, aflatoxin, test weight, or protein.**

The task asked specifically about vomitoxin. **The catalog does not hold a vomitoxin product.**
[R] Two explanations are possible and I cannot distinguish them from the loaded data: either
(a) these covers are sold under generic program names the harvest did not resolve — several of
the 26 `other`-layer program rows (REVCO, Select Programs, Xtra Bundle) are umbrella names that
could contain quality endorsements — or (b) row-crop quality risk is genuinely handled on the
federal side through the Basic Provisions' quality-adjustment machinery, and the private quality
market is concentrated in specialty crops, which is what the catalog actually shows. **This is
an open item, flagged in §7.**

What is knowable: the federal policy's quality adjustment reduces *production to count* using
published discount factors when quality loss is due to an insured cause and meets the policy's
standards. It therefore addresses quality only insofar as quality converts to bushels. A
contract discount for high DON that does not clear the federal QA threshold is uncovered
federally, and that is where a private quality cover would sit. **[R]**

### 4.5 Price-window and price-discovery products

**[C]** Price-Flex (Great American, Hudson, ProAg), Added Price Option (RCIS), Added Price
Protection (Great American), Base Price Modifier and Price Modifier PLUS (NAU), RPowerD
(RCIS, Great American, NAU, ProAg, AgriBusiness), MPowerD (RCIS, Great American, Hudson, NAU,
ProAg), EASYrev (NAU).

The carriers describe the mechanism plainly. NAU on EASYrev: it lets policyholders "complement
the risk coverage of revenue policies through **additional price discovery methods beyond those
offered under the MPCI plans of insurance**." **[V]**
<https://www.naucountry.com/products/private-products/nau-easyrev> Great American on RPowerD: "customizable
price discovery periods and the ability to lock in current market prices." **[V]**
<https://greatamericancrop.com/products---policies/private-products>

**What this actually is, economically.** [R] MPCI's projected price is a fixed average of
futures over a fixed discovery month (February for Corn Belt corn and soybeans; August for
winter wheat) and the harvest price is the October average. A price-window product sells the
producer the right to set the guarantee off a *different* window. That is an **option on the
futures price**, priced by a carrier at market with a load. It is not a subsidized coverage
band and should be evaluated the way you would evaluate any exchange-traded option — against
the price of buying the equivalent CME structure directly, which the producer can do without
paying an insurance expense load.

**This is the private category where I am most skeptical, and the reason is precise: it is the
one where a fully liquid, unloaded substitute exists.** For hail there is no exchange-traded
substitute; for a price window there is. Unless the private form offers something the option
market cannot — most plausibly, settlement in the same claim process as the yield loss, i.e.
correlation between the price leg and the production leg that a fixed-quantity option does not
provide — the producer is paying an insurance load for a payoff they could buy at market. That
correlation benefit is real for a producer whose bushels are uncertain (an option hedges a
fixed quantity; a revenue product hedges price × actual quantity), so the comparison is not a
slam dunk in either direction; it is the specific thing to compute. **[R]**

The same logic applies to Added Price Protection ("purchase a set dollar amount of coverage per
bushel or pound — on top of their federal MPCI policy. If there's a yield loss on the MPCI
policy, the APP policy can trigger an additional payment" **[V]**, Great American) and to
Base Price Modifier / ICE, which raise the price election above the federal cap.

### 4.6 Private bands — the area-to-individual conversion

**[C]** 37 products classify as `private_band`. Grouped by the federal band they shadow:

| Federal analog | n | AIPs | Products |
|---|---:|---:|---|
| SCO/ECO | 9 | 6 | RPowerD (RCIS, GA, NAU, ProAg, AgriBusiness), BAND (GA, AgriBusiness), Band Revenue Protection (Hudson), Revenue Band & Yield Band (ProAg) |
| MCO | 6 | 5 | MPowerD (RCIS, GA, Hudson, NAU, ProAg), MyMCO (Hudson) |
| ECO | 5 | 5 | PECO (COUNTRY, Farm Bureau), ECO+ (FMH), GAP (Great American), MyECO (Hudson) |
| SCO | 1 | 1 | SCO+ (FMH) |
| none (own design) | 16 | 9 | Added Price Option, ICE, AIM, EASYeco, EASYrev, BPM, PM+, AVE, APP, VANE, Xtra Bundle, … |

**The genuinely interesting mechanism in this layer is not "more coverage" — it is converting
an area trigger into an individual trigger.** Read the carriers' own descriptions: **[V]**

- FMH, SCO+ (<https://www.fmh.com/insurance/crop-hail/private-products/sco-plus>): "an endorsement to your SCO policy that offers **individual protection above the
  county protection** of your underlying plan up to 86%."
- NAU, EASYeco (<https://www.naucountry.com/products/private-products/easyeco>): "supplementing the Enhanced Coverage Option (ECO) with our **individual-based**
  shallow-loss coverage."
- ProAg, AIM (<https://www.proag.com/products/private-products/>): "a supplemental product to ECO. The AIM policy **extends the ECO coverage at
  harvest time to include the grower's harvested production**."

SCO, ECO, MCO and STAX all settle on a **county** index. A producer who suffers a farm-level
shortfall in a county that is otherwise fine collects **nothing** from the federal band, even
though they bought and paid for it. These private endorsements sell exactly that residual —
and it is a real, non-overlapping exposure.

**But price it against the alternative.** [R] The federal band costs the producer ~$5.64/ac
(ECO-RP) at ~5.1× expected value. The private conversion costs full freight at <1×. Whether
it is worth buying is a question about **basis risk** — how often does your farm go short when
your county does not? — and that is measurable from the producer's own APH history against
county yields. It is the single highest-value calculation this repo could add for the private
side, and it is not currently in the tool. See §7.

---

## 5. Overlap versus complement

### 5.1 The map

| Private category | Relationship to the federal policy | Verdict |
|---|---|---|
| **Companion crop-hail** | Insures the band MPCI explicitly does not (top ½ / ⅓ / ¼ of the crop), with reciprocal payment factors | **Complement, by construction** [V] |
| **Basic / deductible crop-hail** | Same peril, same crop, different settlement basis (acre vs unit). Both can pay; forms are written with no pro-rata clause | **Overlaps in peril, complements in trigger** [V] |
| **Production-plan hail** | Nets against actual production to count, so it cannot pay on damage the crop grows out of | **Complement, self-limiting** [V] |
| **Green snap / wind / fire / freeze** | Insurable causes under MPCI, but dilute to nothing at the unit level | **Complement in practice** [R] |
| **Replant endorsements** | Pays from the first acre and above the federal cap | **Complement (tops up)** [V] |
| **Extra harvest expense** | Reimburses a cost MPCI does not insure at all | **Pure complement** [V] |
| **Private ECO/SCO/MCO clones (RPowerD, MPowerD, GAP, BAND)** | Same band, same purpose, no subsidy | **Overlap — buy the federal one first** [C] |
| **Area→individual conversions (SCO+, EASYeco, AIM, PECO)** | Sells the basis residual the area band leaves behind | **Complement, but only if your basis risk is real** [V]/[R] |
| **Price-window products** | Sells a price-discovery option outside the federal windows | **Complement to the policy, substitute for a CME option** [R] |

### 5.2 Why "same peril" is not the same as "double recovery" — the arithmetic

This is the point most often gotten wrong in both directions, so here it is computed. **[C]**

From the RY2026 sold book, ECO-RP on corn carries **$79.15/ac** of band liability across a
86%→95% band, i.e. 9 points of expected revenue. That implies a **100% expected revenue of
~$879/ac**:

| Coverage | Guarantee/ac | Deductible/ac | Covered by SCO+ECO | Left uninsured |
|---:|---:|---:|---:|---:|
| 70% | $616 | $264 | $220 | $44 |
| 75% | $660 | $220 | $176 | $44 |
| 80% | $704 | $176 | $132 | $44 |
| 85% | $748 | $132 | $88 | $44 |

On paper the federal stack covers everything from 95% down. **But SCO, ECO, MCO and STAX all
settle on a county index**, so those dollars are only reachable when the whole county is short.

Now the individual side. For a YP/RP unit of A acres at coverage level c, when a hailstorm
totally destroys `a` acres and the rest yields normally:

```
unit yield ratio = (A − a) / A        MPCI pays only if (A − a)/A < c
⇒ the storm must take more than (1 − c) of the WHOLE UNIT before MPCI pays $1.
```

| Coverage level | Share of the unit that must be destroyed before MPCI pays anything |
|---:|---:|
| 70% | 30% |
| 75% | 25% |
| 80% | 20% |
| 85% | 15% |

**On an enterprise unit — one crop, whole county — A is the entire planted acreage.** A storm
that flattens 150 acres of a 1,000-acre enterprise unit at 80% coverage moves the unit yield to
85%, above the 80% trigger, and the federal indemnity is **zero**. Crop-hail pays on the 150
damaged acres.

That is the structural reason crop-hail has survived a century of federal expansion, and it is
why "both policies cover hail" is not the same statement as "both policies pay for this hail."
They are insuring different *slices of the loss distribution* of the same peril.

### 5.3 Where double recovery would actually be improper

Not from stacking crop-hail on MPCI — the forms are written for that. The improper cases are:

- **Electing liability above the crop's actual cash value** so total recoveries exceed the
  loss. Crop-hail forms cap at ACV precisely to prevent this; electing above it, or electing
  full ACV on two hail policies at two carriers, defeats the cap.
- **Over-declaring share or acres** on either policy.
- **Presenting appraised damage on a production plan while also claiming the same acres were
  never planted** — internally inconsistent claims across policies.

Each of these is fraud, not optimization, and none of them is required by anything in this
document.

One more compliance point that surprises people, from the Nebraska guidance: **package
discounts are prohibited.** "No other discounts are permitted. This includes… package discounts
for the purchase of MPCI supplemental policies or any other non-crop insurance policies in
combination with a Crop-Hail policy." **[V]** So a quoted "bundle savings" on crop-hail in
Nebraska is not a rate discount; if it is real it must be a difference in the filed rate
itself.

---

## 6. What can and cannot be determined from public data

### 6.1 What the catalog holds — 11,287 filings across 28 states **[C]**

| Dimension | Value |
|---|---|
| Filings loaded | 11,287 |
| States with a loaded portal | **28** of the 47 states where private products are sold |
| Filings carrying a rate/loss-cost component | **4,926 (44%)** |
| Filings with a resolved submission date | **255 (2.3%)** |
| Sub-TOI 02.1001 Crop-Hail Non-Federally Reinsured Only | 9,861 |
| Sub-TOI 02.1000 Crop-Hail Sub-TOI Combinations | 1,413 |
| Sub-TOI 02.1002 Crop-Hail Federally Reinsured Only | 13 |

Per-state, the share of filings carrying a rate component varies enormously, and this is the
single most important fact about knowability: **[C]**

| High disclosure | | Low disclosure | |
|---|---:|---|---:|
| CO | 84% | IL | **2%** |
| ND | 57% | AR | **3%** |
| KS | 56% | SC | **7%** |
| IN, TN, NE | 54% | KY | **17%** |
| IA, MO, OH | 53% | AL, LA, OK | 35–37% |

**Do not read a low percentage as "that state's rates are secret."** It means that state's
portal classifies filings differently — Illinois at 2% is a filing-type taxonomy artifact, not
evidence that Illinois crop-hail rates are unfiled. What it does mean operationally is that
**you cannot build a cross-state rate comparison out of this table**, because the denominator
is not comparable across states.

### 6.2 What is genuinely knowable, and how the rating actually works

This is the part that makes private rates *partially* tractable. The Nebraska DOI guidance
document is the clearest public statement of the mechanism, and the structure it describes is
standard across crop-hail states: **[V]**
<https://doi.nebraska.gov/sites/default/files/doc/IGD%20-%20-%20C13.pdf>

1. **NCIS publishes Final Average Loss Costs (FALCs) at TOWNSHIP grain.** These are industry
   pooled advisory loss costs — the pure hail loss cost per $100 of liability, by township, by
   crop. NCIS is "the industry actuarial statistical agent and advisory organization" for the
   state-regulated segment. **[V]** <https://ag-risk.org/>
2. **Each carrier files rate = FALC × loss cost multiplier**, where LCM = expense multiplier ×
   loss-cost modification.
3. **A carrier may deviate ±25% from the FALC without actuarial justification.** Beyond that it
   must supply actuarial support "showing these rates are not inadequate." Deviations for
   corn-wind, green snap and extra harvest expense are excluded from the cumulative 25% test.
4. **Every crop-hail writer must file annually**, by January 15 in Nebraska, with five years of
   Nebraska and countrywide expense data (production expenses, general expenses, LAE, taxes,
   licenses and fees) and a rationale for the profit and contingencies provision.
5. **Expense multipliers may legitimately differ by product** — "Crop-Hail versus companion
   hail" — and by marketing type and crop, if the expense difference is justified.
6. **Cash discount capped at 3%** for premium received by August 30. No other discounts.

**Consequences for what you can know:** **[R]**

- **Knowable:** the *structure* of every carrier's crop-hail rate; the fact that carriers'
  rates cluster within ±25% of a common industry loss cost, which bounds how much price
  dispersion is possible on the hail line; the filing cadence; which carriers file in which
  states; the existence and approval status of each product.
- **Knowable with effort:** the actual FALCs and filed rate pages, from state DOI filing
  records where the rate exhibits are public. This is per-state and per-filing work, not a
  bulk download, and the SERFF Filing Access portal indexes filings without necessarily
  exposing their attachments.
- **Not knowable from public data:** each carrier's realized loss ratio by product; the actual
  expense multiplier any given AIP uses; **any rate at all for the private supplemental-MPCI
  band products** — and this last one is explicit in the Nebraska document, which states that
  the guidance "does not apply to state-regulated independent supplemental Multiple Peril Crop
  Insurance (MPCI) products, except that rates and forms for these products are subject to the
  same filing deadline as Crop-Hail." **[V]** In other words: **the private band products
  (RPowerD, MPowerD, GAP, BAND, ECO+, PECO, AIM, ICE) sit outside the NCIS advisory-loss-cost
  framework entirely.** There is no industry pooled loss cost for them, no ±25% corridor, and
  no public benchmark. Their pricing is genuinely opaque.

That asymmetry — hail rates semi-transparent and anchored to a common loss cost, private band
rates fully opaque — is the most actionable finding in this section. **[R]** It means the
consumer-protection concern is not concentrated where the volume is (hail), but where the
disclosure is weakest (the bands), which is also where the federal alternative is 5× better.

### 6.3 The 19-state blind spot

Private products in the catalog are sold in 47 states; filings are loaded for 28. The 19
states with products but no loaded filings: **[C]**

> AZ, CA, CT, DE, FL, HI, MA, MD, NH, NJ, NM, NV, NY, PA, RI, UT, VA, VT, WY

Two of these are known to run their own portals rather than the shared NAIC one —
`src/connectors/serff_states.py` records CA (interactive.web.insurance.ca.gov) and NY (NY DFS)
as custom, and the connector reports them as *pending* rather than pretending to search them.
The rest are simply unharvested. Note that this blind spot is mostly **not** row-crop country;
the row-crop states are all covered. **[C]**

### 6.4 What is not knowable at all from any public source

- **Whether a given producer's private product actually paid.** There is no private analogue of
  the RMA Summary of Business. `sob_sales` exists for federal plans and there is nothing
  equivalent for the private side, at any grain. This is why §2.2 has to bracket the private
  loss ratio from an archived industry table rather than compute it.
- **AIP-identified federal data.** Even on the federal side, `src/db.py` notes that RMA does
  not publish AIP-identified Summary of Business at county grain — so "which AIP writes the
  most ECO" is unanswerable, let alone the private equivalent.
- **Terms.** As §1.5 established, 4.2% of the private catalog is verified. Deductible tables,
  limits, exclusions, and payment factors exist only in policy forms, most of which are not
  published.

---

## 7. Conclusions, tagged

**Computed from the loaded data [C]:**

1. The private bucket is 166 products across 12 AIPs, 47 states, and 24 named crops; 38% of it
   is hail-and-fire.
2. Federal supplemental bands returned **~5.0–5.1× per producer dollar** in RY2026 at an 80%
   subsidy share, and **1.79× for Margin Protection** at 44.3%. Every subsidized product is
   above 1×.
3. A private product at a 0.55–0.80 target loss ratio returns **0.55–0.80× per producer
   dollar**. The corn ECO band is **5.8×–9.3× better** per producer dollar than a private
   product covering the same band, and a private carrier must charge **≥5.1×** the producer's
   federal price for identical protection.
4. Implied 2026 corn expected revenue of ~$879/ac; the federal deductible at 80% coverage is
   ~$176/ac; the unit-dilution threshold at 80% coverage is **20% of the whole unit**.
5. Only **4.2%** of the private catalog is primary-source verified. 44% of 11,287 SERFF filings
   carry a rate component, with per-state disclosure ranging 2% (IL) to 84% (CO). 19 of 47
   product-selling states have no loaded filings.

**Cited to primary sources [V]:**

6. FCIC's statutory target loss ratio is 1.0, measured **excluding** the operating-and-
   administrative portion of premium — so the producer's federal premium carries no expense
   load, while a private premium necessarily does (7 U.S.C. §1506(n)(2); Nebraska DOI IGD-C13).
7. CHNP policies "are not Federally-reinsured or subsidized," RMA will not require any AIP to
   assume liability for them, and a carrier's withdrawal can and did cancel live coverage
   mid-season on 60 days' notice (MGR-18-005).
8. The companion crop-hail plan's increasing payment factors (2.0 / 3.0 / 4.0 at 50 / 65 / 75%
   FCIC coverage) are the reciprocal of the uninsured band, making it a leveraged cover on
   exactly the federal deductible (Rain and Hail).
9. Crop-hail is rated off NCIS township-level Final Average Loss Costs with a ±25% deviation
   corridor and an annual filing requirement; private supplemental-MPCI band products are
   explicitly **outside** that framework (Nebraska DOI IGD-C13).
10. 508(h) products are federally reinsured and subsidized, with R&D reimbursement and up to
    four years of maintenance funding, despite being privately developed (RMA).

**Reasoning, unverified [R]:**

11. The right decision rule is **exhaust the subsidized shelf first**: base MPCI at the right
    coverage level, then SCO/ECO/MCO/STAX, then 508(h) endorsements — and only then consider
    private products, and only for exposures the federal stack genuinely cannot reach.
12. The strongest private cases are **companion/deductible crop-hail on enterprise units or
    area plans**, **extra harvest expense** (a cost MPCI does not insure), and **replant**
    (small absolute load, real liquidity benefit).
13. The weakest are the **private band clones** of SCO/ECO/MCO, which lose 5×–9× on expected
    value to the product they imitate, and are also the least price-transparent.
14. **Price-window products should be benchmarked against an exchange-traded option**, since a
    liquid unloaded substitute exists. Their defensible edge is that they hedge price × actual
    quantity rather than a fixed quantity; that edge is computable and should be computed.
15. Nothing in this market raises expected return. The honest framing for every private
    purchase is: *this reduces variance at a cost of X cents on the dollar, and here is the
    constraint it relaxes that makes X worth paying.*

### Open items worth chasing

- **Basis-risk calculator (highest value).** For the area→individual conversions (SCO+,
  EASYeco, AIM, PECO), compute from a producer's own APH history against county yields how
  often the farm goes short when the county does not. That frequency is the entire value of
  the product and this repo has the county-yield plumbing to compute it.
- **The vomitoxin/quality gap (§4.4).** The catalog holds zero row-crop quality products. Test
  whether these live inside the 26 unclassified umbrella programs, or genuinely do not exist
  on the private side, by resolving REVCO / APCO / Select Programs / Xtra Bundle to their
  component covers.
- **FALC anchoring.** If NCIS township FALCs can be obtained for even one state, the ±25%
  corridor makes it possible to bound every carrier's crop-hail rate in that state — turning
  the largest private line from opaque to semi-transparent.
- **`peril_type`/`coverage_type` are unclassified on 40 and 57 rows respectively.** Those
  fields drive `stack.classify()`, so the 26 rows in the `other` layer are partly a data gap,
  not a genuine taxonomy residue.
- **Extend the SERFF harvest** to the remaining row-crop-relevant states, and wire the CA/NY
  custom portals that `serff_states.py` already flags.

---

## 8. Reproduction

```
.venv/bin/python scripts/analysis/private_products_profile.py
```

Sections: `catalog`, `geography`, `serff`, `economics`, `band`, `gap`. Read-only against
`data/catalog_app.db`; reuses `src.stack.classify()` for the layer vocabulary and `sob_sales`
for the federal comparison. The only inputs not from the database are the private target
loss-ratio bracket (0.55–0.80, sourced to the III/NCIS archived crop-hail tables) and FCIC's
statutory 1.0 target loss ratio, both declared as named constants at the top of the file.
