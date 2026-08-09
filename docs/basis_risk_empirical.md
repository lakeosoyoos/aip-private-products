# Basis risk, measured — the observed miss rate from realized indemnities

**Companion to `docs/basis_risk.md`.** That document estimates how often an area-triggered band
(SCO/ECO) fails to pay a producer who had a real loss, by *simulation*, resting on one imported
parameter: the farm-to-county yield correlation ρ, assumed at **0.70** nationwide. This document
builds an estimator that uses no ρ at all — it counts, from the Summary of Business, how often
individual policies actually collected in a county-year where the area band actually paid nothing —
and then asks what that observed record implies about the 0.70.

**The verdict, up front:** the observed estimator should **CALIBRATE and CROSS-CHECK** ρ. It should
not replace it. Section 10 argues that from the data rather than asserting it.

---

## 0. How to read this document

Tags follow `docs/rowcrop_private_products.md`:

- **[V]** — verified against a primary source (statute, RMA bulletin/handbook, or a quotation
  already verified to the page in `docs/rowcrop_endorsement_stacking.md`, which is cited by
  section).
- **[C]** — computed by me from `data/catalog_app.db` in this session, and reproducible from
  `scripts/analysis/build_basis_risk_empirical.py`.
- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis.

**Status of the numbers in this document.** Everything tagged **[C]** that describes the *national
book*, the *loss-year record*, the *unit-structure mix*, or the *coverage-level mix* is computed and
reproducible today. Everything that would be a **county × crop × year observed miss rate** is
**NOT YET COMPUTED**: `sob_sales` — the county-grain Summary of Business, ~3.23M rows — was
mid-rebuild while this was written and stands at 0 rows. The module, its tests and the CLI are
complete and fixture-tested against synthetic data; the estimator refuses to run rather than
guessing, and `scripts/analysis/build_basis_risk_empirical.py --headline` will produce the real
numbers the moment the table lands. Where a headline figure would go, this document says so.

---

## 1. The question this exists to answer

`src/basisrisk.py` is honest about its own weak spot and reports it on every row: **[C]**

| Crop, `SCO86`, RP, farm CL 0.85 | ρ = 0.55 | ρ = 0.70 | ρ = 0.85 |
|---|---|---|---|
| Corn (n = 1,902 counties) | 0.469 | **0.375** | 0.246 |
| Soybeans (1,628) | 0.492 | **0.392** | 0.255 |
| Wheat (1,405) | 0.393 | **0.307** | 0.198 |
| Corn, `ECO95` | 0.263 | **0.174** | 0.072 |

The ρ swing is roughly a factor of two on the headline. It is larger than the spread across most
states. So the absolute level of the shipped miss rate is more assumption than measurement — and
the row-crop opportunity ranking multiplies unclaimed subsidy by `(1 − miss_rate)`, so the
assumption propagates into the recommendation.

**The opportunity.** RMA's Summary of Business records realized indemnities per county × crop ×
year × plan × coverage level. For the same county-year we hold both an **individual** plan, which
settles on the producer's own unit, and an **area** plan, which settles on the county index. When
individual policies collected and the area plan paid nothing, that is an **observed** miss. The
plan pairing is not inferred — CIH FCIC-18010 (06-2025) ¶916E maps the underlying plan to the SCO
plan mechanically: **YP-01 → 31, RP-02 → 32, RP-HPE-03 → 33** **[V]**
(`docs/rowcrop_endorsement_stacking.md` §3.1).

---

## 2. The estimator, precisely

### 2.1 The universe

One **cell** = (crop, county, year). A cell enters only if:

| Filter | Why |
|---|---|
| `coverage_type = 'A'` (buy-up) | CAT (`'C'`) is 100% subsidised and the administrative fee is absent from these files, so every producer-economics denominator collapses. `'L'` and `'E'` are dropped for the same comparability reason. |
| `sob_year.settled = 1` | 2025 and 2026 are still developing. The RY2026 file loads at a **0.082** national loss ratio against a mature 0.91–0.93. **[C]** An unsettled year enters as an almost pure *fabricated* miss, because the area leg develops later than the individual leg. |
| area liability > 0 | Without an area book we cannot observe whether the index fired. |
| individual policies-earning-premium > 0 and premium > 0 | Nothing to miss, and no denominator. |

### 2.2 The headline

```
area_fired  :=  area indemnity > fire_eps × area liability          (default: > 0)

                 Σ  ind_policies_indemnified   over cells where NOT area_fired
miss_policy = ───────────────────────────────────────────────────────────────
                 Σ  ind_policies_indemnified   over all cells
```

> Of every individual policy that collected an indemnity in a county-year where the area band was
> on sale, what share sat in a county-year where the band paid **nothing**.

### 2.3 Why policy counts and not loss ratios — the one design decision that matters

The obvious construction is loss ratio against loss ratio: "how often is the individual-plan loss
ratio high while the area loss ratio is ≈ 0?" That construction walks straight into the aggregation
objection. A county's individual-plan loss ratio is a **county aggregate** — an average over farms.
It understates how bad individual farms got, and conditioning on it selects years that were
*systemically* bad, which are exactly the years the index fires. It would understate the miss rate,
and by an unknown amount.

`policies_indemnified` is not an aggregate. It is a **count of farms that collected**. An individual
policy pays exactly when the insured's own realized yield or revenue falls below their own coverage
level — which is, word for word, the simulator's event `farm loss := farm ratio < coverage_level`.
Numerator and denominator are farm-level counts, so **the aggregation objection largely dissolves
for the headline statistic**. It does not dissolve for the loss-ratio statistics, which are reported
alongside and labelled as such precisely so the gap between them can be read. §6 measures what
survives.

### 2.4 Everything else the estimator reports

| Statistic | Meaning |
|---|---|
| `miss_dollar` | share of individual indemnity **dollars** arriving in a no-fire cell |
| `miss_cell` | the literal loss-ratio form: share of cells with individual LR ≥ threshold that did not fire |
| `miss_cell_unweighted` | share of cells with any indemnified policy that did not fire |
| `windfall_rate` | P(index fired \| an individual policy was **not** indemnified) — the transfer, not the insurance |
| `p_ind_loss` | Σ policies indemnified / Σ policies earning premium |
| `p_area_fires_cell` | how often the index fell below its trigger |
| `corr_lr_within_county` | corr(individual LR, area LR) across years **within** a county, county means removed — "when *this* county has a bad year, does *its* index fire?" rather than "do bad counties have bad indexes", which is mostly rating adequacy |
| `participation_share` | area net acres / individual net acres |

### 2.5 The three limits

`tests/test_basisrisk_empirical.py` pins them, and they mirror the two limits
`basisrisk.metrics_from_draws` is pinned to. If a simulated and an observed estimator disagree at
the limits, comparing them in the middle means nothing.

- index fires in **every** cell that had an indemnified policy → `miss_policy = 0`
- index **never** fires → `miss_policy = 1`
- index fires **independently** of the individual book → `miss_policy = 1 − P(fire)`, because
  knowing a policy collected tells you nothing about its county.

---

## 3. What this can and cannot establish

**Can:**

- That a miss of some measured magnitude happens, on real money, in the years we can see.
- The **rank** of counties, states and crops by observed miss frequency. Rank survives level bias.
- A **range for ρ consistent with the observed record**, inside the simulator's own model (§10).
- A direct, checkable statement about the *product as sold*: `miss_cell` and `windfall_rate` are
  frequencies of events in RMA's own accounting.

**Cannot:**

- A **farm-level** miss rate. There are no farms in the Summary of Business, only policies, and a
  policy is not a farm (§6).
- An **unbiased long-run** rate. The observation window excludes every systemic year in the settled
  record (§5).
- A **per-county** rate. A county contributes at most ten SCO years and four ECO years; the
  year-block bootstrap interval on that is wider than the entire ρ sensitivity band (§4).
- Anything about the producers who did **not** buy — except by the argument in §7, which says the
  question does not require them.

---

## 4. Precision: the year-block bootstrap, and why it is the honest interval

Cells inside a crop year are not independent observations. Every county in the Corn Belt sees the
same drought; whether the index fires is decided at the weather level, not the county level. The
effective sample size is therefore roughly the **number of years**, not the number of cells.

`bootstrap_ci(cells, by="year")` resamples whole crop years. `by="cell"` is the naive i.i.d.
interval and exists only so the gap can be printed next to it — `--headline` prints both, labelled.
On a synthetic ten-year panel of 60 counties where firing is decided entirely at the year level, the
year-block interval is more than **4×** wider than the i.i.d. one, and spans more than 30 points.
**[C]** (`test_year_block_bootstrap_is_wider_than_the_naive_cell_bootstrap`)

`leave_one_year_out()` is printed alongside, because with ten years the more informative statement
is not an interval but a name: *which year* the answer rests on.

**This is the finding that decides how the estimator may be used.** Ten years cannot pin a county.
They can pin a national or crop-level number, loosely.

---

## 5. Hard part 1 — the short history, and the systemic years it never saw

SCO begins in 2015, ECO in 2021. Both miss 2012. **[C]**, from `sob_year`, 36 settled crop years
1989–2024:

| | SCO window 2015–2024 | ECO window 2021–2024 | Full settled record |
|---|---|---|---|
| settled years | 10 | 4 | 36 (1989–2024) |
| mean national loss ratio | **0.736** | 0.858 | **0.916** |
| max national loss ratio in window | 1.072 (2019) | 0.976 (2022) | 2.316 (1993) |
| years with LR ≥ 1.2 | **0** | **0** | **6** — 1989, 1991, 1992, 1993, 2002, 2012 |
| base rate of such years | 0.0% | 0.0% | **16.7%** |
| share of settled-era indemnity dollars inside the window | 45.7% | 27.0% | 100% |

**Neither window contains a single systemic year.** The worst year SCO has ever seen ran a 1.07
national loss ratio; 2012 ran 1.65 and 1993 ran 2.32.

### The direction of the bias, and why the sign is knowable **[R]**

A systemic year is *by definition* a year the county index falls — that is what "systemic" means in
this context. It is therefore a year the area band **fires**, and the individual losses standing
beside it are **hits**, not misses. A window with no systemic years is a window whose losses are
disproportionately **local**, and local losses are exactly what an area index misses.

> **The observed miss rate is biased UPWARD. Any ρ backed out of it is biased DOWNWARD.**

That is the opposite of the direction one might fear, and it matters for the verdict in §10: if the
observed record already implies a ρ at or below 0.70 *before* correcting for this, the correction
pushes the implied ρ back **up** toward the reference, not away from it.

### The bound, and why it is a bound and not a correction

You cannot reweight into a stratum with zero observations. `systemic_bounds()` therefore imputes
rather than reweights: at the 16.7% historical base rate the SCO window "should" have contained
about **2 more systemic years**; impute them at their historical frequency, count them as pure hits,
and the miss rate falls to

```
miss_lower = M / (L + k · loss_intensity · L/n)
```

with `loss_intensity = 1.0` meaning "a systemic year carries as many indemnified policies as an
average year". That is conservative to the point of being wrong in the safe direction — 2012 is the
largest indemnity year in the settled record at **$16.46B** and a **1.647** loss ratio, against a
0.916 mean **[C]** — and a higher intensity pushes the corrected rate lower still. `miss_upper` is
the observed value, because the imputation can only add hits.

---

## 6. Hard part 3 — aggregation, quantified rather than asserted

§2.3 disposed of the *county-aggregate* form of the objection by counting policies instead of
dollars. One gap survives, and it is not the one usually named.

### Optional units

RMA counts a policy **indemnified** when **any unit** paid, not when the whole farm was short. A
one-unit loss is more frequent and more idiosyncratic than a whole-farm loss, so the estimator
conditions on a broader, more local event than the simulator does. **Direction: biases the observed
miss rate UPWARD.**

`simulate_cells()` measures how much. It reproduces `basisrisk.draw_joint`'s generative model —
same variance-corrected smoothed bootstrap for the county, same `σ_e = σ_c·√(1/ρ²−1)` farm shock,
same `max(1,p)` harvest-price reset — with many farms per county-year and optionally several units
per farm, so the SoB's own observables can be constructed and the estimator run on a world where the
true farm-level answer is known. `test_single_farm_matches_the_simulator` pins the reimplementation
to `basisrisk.basis_risk` at one farm and one unit; without that test, any bias measured here would
be indistinguishable from a coding difference.

**[C]** synthetic county, CV 0.153, `SCO86`, farm coverage level 0.80, RP
(`build_basis_risk_empirical.py --bias`):

| ρ | units/farm | P(farm loss) | P(policy indemnified) | true farm miss | estimator | **bias** |
|---|---|---|---|---|---|---|
| 0.55 | 1 | 0.401 | 0.401 | 0.312 | 0.312 | **+0.000** |
| 0.55 | 2 | 0.399 | 0.549 | 0.318 | 0.386 | **+0.068** |
| 0.55 | 4 | 0.398 | 0.682 | 0.310 | 0.431 | **+0.120** |
| 0.70 | 1 | 0.372 | 0.372 | 0.221 | 0.221 | **+0.000** |
| 0.70 | 2 | 0.369 | 0.498 | 0.225 | 0.307 | **+0.082** |
| 0.70 | 4 | 0.369 | 0.618 | 0.218 | 0.366 | **+0.148** |
| 0.85 | 1 | 0.341 | 0.341 | 0.106 | 0.106 | **+0.000** |
| 0.85 | 2 | 0.337 | 0.428 | 0.108 | 0.181 | **+0.073** |
| 0.85 | 4 | 0.337 | 0.521 | 0.103 | 0.245 | **+0.143** |

At one unit the bias is exactly zero — that is the whole content of §2.3, and it is a theorem, not
an empirical result. At four units it reaches +0.15, which is **the same order as the entire ρ
sensitivity band**.

### Which row applies

The mix is measurable. RY2015–2024 individual RP (`plan_code='02'`, `coverage_type='A'`, settled
years), by liability: **[C]**

| unit structure | liability | share |
|---|---|---|
| **EU** — enterprise unit | $524.5B | **59.1%** |
| OU — optional unit | $222.4B | 25.1% |
| BU — basic unit | $112.1B | 12.6% |
| EP / EC / UD / UA / WU | $28.5B | 3.2% |

An **enterprise unit pools every acre of that crop the insured has in the county into one unit**, so
for three fifths of the book "indemnified" *already means* a whole-farm shortfall and the bias is
zero. The liability-weighted effective units per policy is roughly **1.5**. **[R]** The relevant row
above is therefore **units = 2**, i.e. a bias of about **+0.07 to +0.08**, not the +0.15 at four
units.

### The bias that runs the other way, and is not quantified here

RMA publishes a **separate county index by type and practice**. A cell reads `area_fired` because
*some* index in that county fell — possibly the irrigated one, while the dryland farmer settles on a
different index that did not. **Direction: biases the observed miss rate DOWNWARD.** **[R]** Its
size is not estimated. `docs/basis_risk.md` §8.3 already flags the mirror image of this on the
simulated side (the NASS series used is `ALL PRODUCTION PRACTICES`), so the two sides carry the same
unmeasured blend and it is not obvious that it favours either.

---

## 7. Hard part 2 — selection: narrower than it looks, and not gone

### Why it is narrower than it looks

**(a) The area book is not a sample of losses. It is a revealed indicator of the county index.**
Whether the index fell below its trigger in a county-year is a **county-level fact**, identical for
every acre of that crop/type/practice whether or not its owner bought the endorsement. The area
indemnity is simply how that fact is read off the file. The denominator can therefore be the
**whole** individual book, buyers and non-buyers alike. **[R]**

**(b) That is also the right population.** The question a recommendation has to answer is what a
*prospective* buyer should expect, not what current buyers got. Restricting the denominator to
buyers would be the wrong estimand even if it were possible. **[R]**

**(c) SCO is not elected acre by acre.** 20-SCO §5(a), as replaced by 25-OBBA: *"All planted acreage
of the crop in the county that is insured by the underlying policy must be insured under this
Endorsement, except this Endorsement will not insure acreage that is designated as covered by
STAX."* **[V]** (`docs/rowcrop_endorsement_stacking.md` §2b, §3.1.) So for an electing policy the
SCO acres **are** the underlying acres. The selection is between *policies*, not within them, and
`participation_share` is close to the share of the county's insured acres whose policies elected the
endorsement — which is what makes the stratification probe in §7.2 meaningful rather than decorative.

### 7.1 The three channels that survive

1. **Sample confinement.** The estimator only sees county-years where somebody bought the
   endorsement. Counties with no SCO book contribute nothing and are unlikely to be a random draw.
   Direction unknown. **[R]**
2. **Which index we observe.** See §6, last block. Direction: **down**.
3. **The ARC bar, through RY2025.** This is the sharpest identifiable selection mechanism in the
   window and it is worth stating precisely. 20-SCO §5(a)(2) excluded *"acreage on land identified
   by a FSA farm serial number for which ARC has been elected for the crop"*, and CIH ¶916J made it
   operate *"regardless of ARC enrollment status"* **[V]**; OBBBA §10303(b) repealed it, effective
   for RY2026 **[V]** (both quoted to the page in `docs/rowcrop_endorsement_stacking.md` §2b).
   ARC-CO is itself a **county-index** program, elected by producers who expect county-visible
   revenue shortfalls. So for **every year in the SCO window except the last**, the SCO book was
   systematically short of exactly the acres most likely to see the index fire. **Direction: biases
   the observed miss rate UPWARD.** **[R]** Note that this compounds with §5 rather than offsetting
   it: both push the same way.

### 7.2 What can actually be done — the stability probe

`by_participation_decile()` stratifies the estimate by area acres / individual acres.

- A **flat** profile means a selection story has to be one that operates equally at 3% and 60%
  participation. That is weak comfort, not proof.
- A **sloped** profile is affirmative evidence that selection is live. In that case the **level is
  not interpretable** and only the within-stratum ordering survives.

`--selection` prints the profile with the spread and calls it. **Not yet run on real data.**

### 7.3 The honest bottom line on selection

Selection cannot be eliminated and it cannot be signed as a whole. What can be said is that the two
channels that *can* be signed (the ARC bar, and the missing systemic years) both push the observed
miss rate **up**, and the one that pushes it down (practice-blended index reading) is mirrored on
the simulated side. **[R]** The estimator is therefore more likely to be an **upper** estimate of the
true frequency than a lower one — which is the reverse of the intuition that a county-aggregate
statistic must understate farm-level risk, and it is a direct consequence of counting policies
rather than dollars.

---

## 8. The comparability trap: coverage level

This is not a subtlety and it will produce a wrong answer if ignored.

`basis_risk_county` as shipped is built at farm coverage level **0.85 only** — 14,805 rows, all at
0.85. **[C]** `SCO86` at a farm coverage level of 0.85 is a band **one point wide**.

The SCO book is not at 0.85. From `sob_national`, SCO-RP (`plan_code='32'`, `coverage_type='A'`,
RY2015–2026), where `coverage_level` records the **underlying** election: **[C]**

| underlying CL | liability | share | resulting SCO band width |
|---|---|---|---|
| 0.75 | $3.77B | **42.0%** | 11 points |
| 0.80 | $1.86B | 20.7% | 6 points |
| 0.70 | $1.60B | 17.8% | 16 points |
| 0.50 | $0.80B | 8.9% | 36 points |
| 0.60 | $0.50B | 5.6% | 26 points |
| 0.65 | $0.33B | 3.6% | 21 points |
| **0.85** | **$0.08B** | **0.9%** | **1 point** |
| 0.55 | $0.04B | 0.4% | 31 points |

**Under one percent of the SCO book sits at the coverage level the simulated table is built at.**
An unrestricted observed rate compared against the shipped simulated rows compares two different
products. This is consistent with the independent measurement in
`docs/rowcrop_endorsement_stacking.md` §2, which puts the SCO-RP median band at 7.9 points and
implies a weighted-average underlying level near 78%. **[V]**

Two ways out, both supported:

1. `load_cells(coverage_levels=[0.85])` — a matched comparison. Honest, but it throws away 99% of
   the book and the residual is a very thin sample.
2. Rebuild the simulated side at the observed modal level. `basisrisk.basis_risk()` takes
   `coverage_level` directly, and `build_basis_risk.py --coverage-levels 0.70 0.75 0.80 0.85` is the
   fix `docs/basis_risk.md` already names. **This is the higher-value path and it is a change to a
   file owned elsewhere.**

**ECO does not have this problem.** For ECO, `sob_sales.coverage_level` records the **trigger**, not
the underlying, and **98.4%** of ECO-RP liability ($11.93B of $12.12B) elects the 95% trigger.
**[C]** `PAIR_SPECS["ECO-RP"]` restricts to 0.95 and maps to `ECO95`, which is exactly the shipped
simulated band. ECO is the cleaner comparison on the band axis and the worse one on sample size —
four settled years.

---

## 9. Comparing observed against simulated

`compare_to_simulated()` joins the per-county observed rates onto `basis_risk_county` and returns:

| Output | How to read it |
|---|---|
| median observed vs median simulated | the **level** gap. Interpret only with §5–§8 in hand. |
| share of counties inside the simulated `[rho_lo, rho_hi]` band | does the record fall inside the sensitivity the shipped table already advertises? |
| **Spearman rank correlation** | does the simulator **order** counties the way the realized record does? This is the number that survives level bias, and the most useful single output of the comparison. |
| individual county rows | **do not read them.** See §4. |

`by_county()` gates on `min_loss_policies` (default 30), which is deliberately too small rather than
defensibly right — no threshold rescues ten years, and the bootstrap is the real guard.

**Not yet run on real data.**

---

## 10. ρ — replace, calibrate, or cross-check?

### 10.1 The inversion

`implied_rho()` bisects the simulator: which ρ would have produced the observed miss rate? It is
monotone (a farm more like its county is missed less often), so bisection is valid, and a target
outside the reachable range returns `None` with a note rather than a clipped number that looks like
a result.

Two metrics:

- `metric="estimator"` (**default**) — match what the SoB estimator itself would report in a world
  with that ρ, carrying the same optional-unit structure. Like-for-like: the §6 bias sits on both
  sides and cancels instead of being charged to ρ.
- `metric="farm"` — match the clean farm-level `basisrisk.basis_risk().miss_rate`. Only valid if the
  estimator were unbiased for the farm concept, which §6 refutes. Provided for contrast.

Feed it the **year-block bootstrap endpoints**, not the point. The interval endpoints swap: a
*higher* observed miss implies a *lower* ρ.

For a pooled crop-level target the inversion needs one county yield series to invert against.
`_reference_county()` picks the real county whose `county_cv` sits at the exposure-weighted median
for that crop. There is no honest "average county series" — averaging counties produces a *state*
series, whose variance is far lower, which would silently raise the implied ρ.

### 10.2 The argument

**REPLACE — no.** Four reasons, in descending order of force:

1. **The estimator is not measured at farm level.** It counts policies, and a policy is not a farm
   (§6). Substituting it for ρ would substitute one modelled quantity for another while *losing* the
   thing ρ has going for it: ρ is a parameter a producer can measure on their own APH schedule
   (`basisrisk.farm_basis_risk`). An observed national frequency cannot be personalised; ρ can.
2. **The observation window is not a sample of the loss distribution.** Zero of six systemic years
   (§5). An estimate built on a decade with no 2012 in it does not describe the long run, and the
   correction is a bound, not a point.
3. **The per-county estimate is noise.** Ten years, one weather draw per year (§4). The shipped
   table has 14,805 county rows; the observed record cannot fill them.
4. **The ARC bar contaminated nine of the ten SCO years** in a direction correlated with exactly the
   event being measured (§7.1.3).

**CALIBRATE — yes, at national and crop grain, and with the interval quoted.** The inversion is
model-internal but it is the only construction that puts a *number* from the realized record onto
the axis the shipped table is parameterised on. It answers a question nothing else in the repo can:
*is the observed record consistent with ρ = 0.70 at all?* The `build` path therefore populates
`implied_rho` at **crop** grain only, and leaves it NULL at county grain, because inverting a
four-loss-year county target would be noise dressed as a parameter.

**CROSS-CHECK — yes, and this is the highest-confidence use.** The rank comparison in §9 is nearly
free of the level biases catalogued above. If the simulator orders counties the way the realized
record does, the county map is doing its job as a **screening tool** — which is all
`docs/basis_risk.md` §2 ever claims for it — even if the absolute level is soft.

### 10.3 The decision rule, stated in advance

Committing to the reading before seeing the number, so the number cannot pick the reading: **[R]**

| Implied ρ (crop grain, `metric="estimator"`, units = 2, interval from the year-block bootstrap) | Reading |
|---|---|
| interval **overlaps 0.55–0.85** | The observed record does not contradict the reference. **Keep ρ = 0.70**, cite this as corroboration, and change nothing in `basis_risk_county`. Add the observed rate to the documentation as an independent check. |
| interval falls **entirely below 0.55** | The shipped **sensitivity band itself is wrong**, which is a larger finding than the point estimate. Widen `RHO_LO` before touching `RHO_REF`, and re-derive after applying the §5 systemic bound — which pushes implied ρ **up**, so check whether the bound alone closes the gap. |
| interval falls **entirely above 0.85** | Same in reverse, and additionally suspicious: §5 and §7.1.3 both bias the observed miss rate up, so an implied ρ above the band would have to have overcome two biases pointing the other way. Investigate the practice-blend channel (§6) before believing it. |
| **`None`** — no ρ reproduces the target | The observed outcome is not consistent with the model at *any* correlation. That is the most interesting outcome available and it invalidates the `farm = county + independent shock` decomposition, not just its parameter. |

There is one asymmetry worth flagging in advance. The two signable biases (§5, §7.1.3) both push the
observed miss rate **up** and the implied ρ **down**. So a raw implied ρ that comes in *below* 0.70
is the **expected** result and is weak evidence against the reference; a raw implied ρ that comes in
*at or above* 0.70 despite those biases would be much stronger evidence **for** it. **[R]**

### 10.4 What would actually settle ρ

Not this. The estimator that would settle it is `basisrisk.farm_basis_risk()` run over real APH
schedules — the producer supplies the private data we cannot get — and the aggregation-scaling
calibration in `docs/basis_risk.md` §5a, whose own bias is documented and signed. This document adds
a third, independent line of evidence with a different bias structure from either. Three biased
estimators that disagree are more informative than one clean-looking assumption; three that agree
are close to a result. **[R]**

---

## 11. What we could not determine

1. **Any real number.** `sob_sales` is at 0 rows mid-rebuild. Every observed figure in this document
   is a placeholder. The module refuses rather than guesses.
2. **The size of the practice/type blend bias** (§6), which is the only signed bias pointing
   *downward* and therefore the only counterweight to §5 and §7.1.3.
3. **Whether counties with no SCO book differ systematically** from those with one. Direction
   unknown; not signable from these files.
4. **A farm-level rate.** No farms in the Summary of Business.
5. **STAX.** `PAIR_SPECS["STAX-RP"]` exists and will run, but STAX maps to no simulated band
   (`basisrisk.py` writes none, deliberately), it does not require an underlying policy so its
   selection problem is different in kind, and
   `docs/rowcrop_endorsement_stacking.md` §2 already flags its SoB rows as untrustworthy. **[V]**
6. **MCO.** `sob_national` carries MCO only in RY2026 — MCO-RP 9 rows, $119.7M liability, **zero**
   indemnity; MCO-YP 3 rows; MCO-RPHPE 3 rows — and RY2026 is unsettled. **[C]** Nothing to measure
   for years. `basisrisk.py` writes no MCO rows either, so both sides are silent rather than wrong.
7. **Whether the observed cells' modal coverage level matches the simulated table's.** §8 shows it
   does not, and the fix lives in a file owned elsewhere.
8. **The YP pairs.** `SCO-YP` runs a **1.694** long-run loss ratio against `SCO-RP`'s 0.692, and
   `ECO-YP` 1.206 against `ECO-RP`'s 0.719 (settled years, `coverage_type='A'`). **[C]** The
   yield-triggered area plans are rated very differently from the revenue ones. That is worth its own
   pass and is not explained here.

---

## 12. Operations

```bash
# Diagnostics that need no sob_sales — these run today
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --exposure    # §5
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --bias        # §6

# These need sob_sales (~3.23M rows; rebuilt by scripts/rebuild_rest.sh)
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --headline
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --selection   # §7
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --compare     # §9
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --calibrate   # §10

# Matched-coverage-level comparison (§8), the honest-but-thin version
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --compare --coverage-levels 0.85

# ECO, which is clean on the band axis and thin on years
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --headline --pairs ECO-RP

# Write basis_risk_empirical
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py
.venv/bin/python scripts/analysis/build_basis_risk_empirical.py --report
```

`--calibrate` additionally needs `nass_county_yield` in the working DB, for the county series to
invert against. It says so and returns rather than faking one.

### Files

| File | Role |
|---|---|
| `src/basisrisk_empirical.py` | the estimator, the bias simulation, the ρ inversion, the DDL (new) |
| `scripts/analysis/build_basis_risk_empirical.py` | the six modes above + the table build (new) |
| `tests/test_basisrisk_empirical.py` | 42 tests, all on synthetic fixtures, including the three limits (new) |
| `docs/basis_risk_empirical.md` | this document (new) |
| `src/basisrisk.py` | the simulated estimator this cross-checks (**unchanged**) |
| `docs/basis_risk.md` | the simulated estimator's documentation (**unchanged**) |

### Table

`basis_risk_empirical`, keyed `(pair, grain, crop, state, county_fips, coverage_level)`. Grains:
`national`, `crop`, `state`, `county`. The DDL lives in `src/basisrisk_empirical.SCHEMA` rather than
`src/db.py` so this work can be added, reviewed and dropped without touching a shared file; folding
it into `db.SCHEMA` is a one-line follow-up for whoever owns that file. Size is small — a few
thousand rows at most — but it is **not** wired into `scripts/build_app_db.py`, which is owned
elsewhere. If the app is ever to read it, `basis_risk_empirical` goes in `REQUIRED` there.

**A note for whoever ships this to the app.** The observed miss rate must never be joined into the
opportunity ranking as a substitute for `basis_risk_county.miss_rate`. §4 and §8 make it unfit for
county-level use. Its place is documentation and calibration, and the column that belongs on a
county map from this work is nothing — the cross-check output is a *sentence about the map*, not a
layer on it.
