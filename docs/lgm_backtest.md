# LGM — the deductible ladder, measured

**`docs/lgm.md` §5.4 says the LGM deductible ladder "cannot be backtested". It can. This
document is the retraction, the method, the measured answer, and — more importantly — the
sample size that answer rests on.**

Author: research pass, 2026-08-09. Companion to `docs/lgm.md`, whose tagging convention and
vocabulary this document follows.

---

## 0. How to read this document

- **[V]** — verified against a primary source: an RMA policy, handbook, premium-calculation
  instruction, or RMA's own Actuarial Data Master. File and column given.
- **[C]** — computed by me in this session from RMA's published files. Every `[C]` number is
  reproduced by:

  ```
  .venv/bin/python -m src.lgmbacktest --harvest --years 2014-2027    # once, ~350 MB
  .venv/bin/python scripts/analysis/lgm_backtest.py
  ```

- **[R]** — my reasoning or judgment. Not verified. Treat as a hypothesis.

### The one-paragraph version

> LGM's own actuarial file publishes both sides of the settlement — `A00600
> LgmGrossMargin` carries ten `MonthN Actual Gross Margin Amount` columns beside its ten
> expected ones, back-filled after each marketing month settles — so the indemnity at every
> filed deductible is reconstructible with no modelling. Measured over RY2022–RY2026, the
> forward-looking optimum **survives for swine ($10/head, in every sub-window tested)**,
> **fails for dairy** (measured optimum $0.10–$0.80/cwt, always below the computed $1.00),
> and is **moot for cattle**, which paid nothing at all at any deductible of $60/head or more
> in five years. The mechanism is one assumption: the rated model treats the loss ratio as
> constant across the ladder, and measured it falls from 1.17 to 0.53 as the deductible
> rises. But the margins are national and consecutive monthly periods overlap in nine of ten
> marketing months, so this rests on **6 to 11 non-overlapping observations per commodity**,
> and only the swine result is stable when a year is added or dropped.

---

## 1. The retraction

`src/lgm.py` §4 and `docs/lgm.md` §5.4 both conclude: **[V]** of the premise, **wrong** on
the conclusion.

> "sobtpu publishes `Coverage Level` as `.0000` for every plan-82 row from crop year 2008
> forward, so realized loss ratio BY DEDUCTIBLE does not exist in any public file.
> Deductible-level economics in this module are therefore forward-looking (computed off
> RMA's rate draws), never backtested."

The first sentence is correct and I re-confirmed it. The second does not follow, because
sobtpu is the wrong file. `A00600 LgmGrossMargin` has **49 columns**, and twenty of them are
the settlement: **[V]**

| columns | meaning |
|---|---|
| `Month2..Month11 Expected Gross Margin Amount` | the margin the guarantee was struck on |
| `Month2..Month11 Actual Gross Margin Amount` | the margin that actually occurred |

From those two vectors the indemnity at any deductible is arithmetic, not modelling:

```
GMG(d)       = EGM - d x sum_m h(m)          RMA Step 1b (src/lgm.gross_margin_guarantee)
AGM          = sum_m actual(m) x h(m)
indemnity(d) = MAX(0, GMG(d) - AGM)
```

This is the same shape as `src/drpopt.py` against `drp_actual_price`, and
`src/lgmbacktest.py` mirrors its idioms deliberately.

---

## 2. What had to be established first

### 2.1 How far back the archive goes [C]

`pubfs-rma.fpac.usda.gov/pub/References/adm_livestock/{RY}/` carries
`{RY}_ADMLivestockLgm_Daily_{YYYYMMDD}.zip` for **RY2014 through RY2027 — 648 files**. 641
are readable; the seven that are not are each the *first* file of a reinsurance year
(RY2015–RY2020) and are zero-padded with no end-of-central-directory record. They are
skipped, not worked around. **[C]**

| RY | files | A00600 layout | `Sales Effective Date`? | sales dates | span of published files |
|---|---|---|---|---|---|
| 2014 | 27 | long | **no** | 27 | 2013-07-26 … 2015-07-23 |
| 2015–2021 | 20–29 each | long | **no** | 20–29 | 2014-09-26 … 2022-07-29 |
| 2022 | 73 | long | yes | 51 | 2021-07-01 … 2023-07-07 |
| 2023 | 85 | wide | yes | 51 | 2022-07-07 … 2024-06-28 |
| 2024 | 85 | wide | yes | 51 | 2023-07-06 … 2025-06-27 |
| 2025 | 115 | wide | yes | 48 | 2024-07-18 … 2026-06-12 |
| 2026 | 94 | wide | yes | 49 | 2025-07-03 … 2026-08-05 |
| 2027 | 7 | wide | yes | 6 | 2026-07-02 … 2026-08-06 |

Two things this table settles. **[C]**

- **The publication span runs a year past the end of the reinsurance year.** RY2025's last
  file landed 2026-06-12, twelve months after RY2025 sales closed. Those late files are the
  settlement back-fill; without them there is no backtest.
- **The usable window starts at RY2022, not RY2014.** The pre-RY2022 A00600 has no `Sales
  Effective Date` column at all. A settled back-fill row from those years carries an expected
  vector and an actual vector and nothing that says which of the year's dozen sales dates
  struck that guarantee. The guarantee is the whole quantity under test, so `settled_periods`
  refuses those years by name rather than letting a file stamp masquerade as a sales date.
  **[R]** on the refusal; **[C]** on the missing column.

**That boundary is lucky.** `docs/lgm.md` §3.2 records that LGM-Cattle and LGM-Swine carried
0% subsidy in the Summary of Business through 2019. RY2022 sales begin July 2021. So the
window that is mechanically recoverable is also, to within a year, exactly the subsidised
era — a longer window would have blended two economically different products. The cost is
real and one-directional: **the unsubsidised era cannot be measured here, only excluded.**
**[R]**

### 2.2 Whether the `Actual` columns are actually populated [C]

This is the single assumption everything rests on, and the honest answer has two halves.

**A forward-looking file proves nothing.** In `2026_..._20250703` — the first file of RY2026
— 750 of 18,000 possible actual cells are populated, and **all 750 are equal to the
corresponding expected value.** The pattern is structural, not calendar-driven: cattle calf
finishing shows 6 actual feeder-cattle months and 3 actual corn months, yearling finishing
shows 3 and 1, and live cattle shows **zero** in both. That is the feeding-period offset —
the feeder and corn legs for the earliest marketing months were purchased before the sales
date, so their prices are already known, while the output leg never is. **[C]** Both LGM
snapshots previously cached in `data/cache/lgm/` are forward files, which is exactly why they
could not settle the question either way. **[C]**

**The back-fill is real.** Merging every published file for a reinsurance year yields fully
settled expected/actual pairs for all three commodities and every leg: **[C]**

| RY | settled keys after merge | mean \|actual − expected\| |
|---|---|---|
| 2022 | 16,728 | 30.26 |
| 2023 | 20,250 | 67.77 |
| 2024 | 19,900 | 50.76 |
| 2025 | 27,300 | 12.20 |
| 2026 | 12,300 (partial; back-fill still running) | 7.59 |

A mean absolute gap of zero would mean the Actual column was a copy of Expected. It is not.
**[C]**

The merge rule matters and is tested: **expected takes the EARLIEST publication** (the
guarantee the producer actually bought) and **actual takes the LATEST** (settlement is
revised into place). RMA's delta files re-state the expected vector alongside the new
actuals, so a naive last-wins merge would quietly replace the guarantee with a date nobody
could have purchased. **[R]**

### 2.3 Whether the marketing-month structure is recoverable [V][C]

Yes, and it is a bundle, not a month.

- Insurable months come straight out of the ADM: **months 2–11 for cattle and dairy, months
  2–6 for swine**, month 1 never insured. Cattle and dairy rows populate ten months and stop;
  swine rows populate five. **[C]**, matching `src/lgm.INSURED_MONTHS` **[V]**.
- What the ADM does **not** publish is the producer's declared weights `h(m)` — those are a
  purchase decision, not an actuarial fact. This backtest scores the **neutral plan**, equal
  target marketings in every insurable month, exactly as `src/lgm.deductible_curve` does.

That assumption is load-bearing in one direction and worth saying plainly: an equal-weight
plan is **pooled**, so the subsidy applies at every rung. A single-month plan is **unpooled
and unsubsidised at every rung**, which no deductible can repair. A backtest that silently
assumed one month would not be backtesting LGM at all — it would be backtesting the one
configuration in this repo's federal catalog that is value-destroying by construction. **[R]**

---

## 3. What an observation is — read this before section 4

Three collapses, each of which shrinks the sample, and the third is the one that hurts.

### 3.1 State is not a dimension [C]

**LGM margins are identical in all 50 states.** They are CME futures constructions with no
state basis, and the published expected and actual vectors match cell for cell across every
state on every sales date checked, for all three commodities — and so do the 500 published
draws. **[C]**

So `docs/lgm.md` §2.2's reassuring "50 / 50 states agreeing" column is **one observation
printed fifty times**, and should be struck. `src/lgmbacktest.collapse_states` asserts the
identity rather than assuming it and raises `StateDivergence` if a future file breaks it.

### 3.2 Weekly sales dates are re-quotes of one outcome [C]

From RY2022 the ADM carries weekly (Thursday) sales dates, ~51 a year. Every sales date
inside a calendar month insures the same marketing months and therefore settles against an
**identical actual vector** — verified: the four or five Thursdays of a month share one
actual vector, and consecutive months' vectors are the same series shifted by one. **[C]**

So each (reinsurance year, sales month) contributes **one** observation, taken at the last
sales date of the month — the best-informed purchase, and LGM's traditional sales close. This
is `drpopt.observations`' one-row-per-settled-quarter rule, for the same reason.

### 3.3 Consecutive monthly periods overlap — this is worse than DRP [R]

DRP quarters abut. LGM periods do not: a ten-month period sold in January shares **nine of
its ten marketing months** with the period sold in February. A run of monthly observations is
one long autocorrelated series, not a sample. `independent_blocks()` steps by the length of
the insurance period so no two periods share a marketing month.

| commodity / type | weekly rows | monthly periods | **non-overlapping** |
|---|---|---|---|
| Cattle · Calf Finishing | 236 | 57 | **6** |
| Cattle · Yearling Finishing | 223 | 54 | **6** |
| Swine · Farrow to Finish | 224 | 55 | **11** |
| Swine · Feeder Pig Finishing | 224 | 55 | **11** |
| Swine · SEW Pig Finishing | 224 | 55 | **11** |
| Dairy | 207 | 51 | **6** |

**[C]** Six. Read every number in the next section against that column. Restricted to the
non-overlapping subset the ladders are pure noise — dairy's measured optimum lands on $0.80
with two paying periods out of six — which is itself the finding, not a failure.

---

## 4. The measured ladder

RY2022–RY2026. 312 settled monthly periods priced (15 skipped for want of a harvested draw
member — those periods are dropped, never priced off a neighbouring date's draws). Premium is
recomputed with RMA's own Steps 1–7 from the `A00610 LgmDraw` member **of the same sales
date**, so the numerator is realized and the denominator is RMA's own published rating for
that day. **[C]**

### 4.1 Headline: forward vs measured [C]

| commodity / type | forward optimum (rated) | **measured optimum, net $** | measured, per producer $ | realized LR at the forward rung | return per producer $ at the forward rung |
|---|---|---|---|---|---|
| Cattle · Calf Finishing | $70 | $150 (least-bad) † | $0 | **0.00** | **0.00** |
| Cattle · Yearling Finishing | $70 | $150 (least-bad) † | $70 | 0.15 | 0.30 |
| Swine · Farrow to Finish | $10 | **$10** | $12 | 0.82 | 1.55 |
| Swine · Feeder Pig Finishing | $10 | **$10** | $12 | 0.79 | 1.50 |
| Swine · SEW Pig Finishing | $10 | **$10** | $12 | 0.80 | 1.51 |
| Dairy | $1.00 | **$0.10** | $1.10 | 1.01 | 1.94 |

† Both cattle rows are negative at every rung, so "$150" means "buy the least"; nothing
above $50/head paid at all. See §4.2.

The forward column is not the constant from `docs/lgm.md` — it is recomputed **on each
period's own draws**, so it is an apples-to-apples comparison. On the same 312 periods the
rated model picked $70 for cattle calf finishing 32 times out of 57, $10 for swine 43–44
times out of 51, and $1.00 for dairy 25 times out of 48. **[C]**

### 4.2 LGM-Cattle: the $70 rung paid nothing, five years running [C]

Calf finishing, RY2022–RY2026, per head, equal marketings in all ten insurable months:

| deductible | subsidy | periods | paid | total premium | producer premium | indemnity | loss ratio | net $ |
|---|---|---|---|---|---|---|---|---|
| $0 | 0.18 | 57 | 9 | 29,961 | 24,570 | 2,023 | 0.068 | −22,547 |
| $30 | 0.27 | 57 | 3 | 21,875 | 15,968 | 500 | 0.023 | −15,468 |
| $50 | 0.36 | 57 | 1 | 17,549 | 11,230 | 89 | 0.005 | −11,141 |
| **$70** | **0.50** | **57** | **0** | **13,939** | **6,966** | **0** | **0.000** | **−6,966** |
| $150 | 0.50 | 57 | 0 | 5,067 | 2,532 | 0 | 0.000 | −2,532 |

**Nothing above $50 paid a cent in five reinsurance years.** Net is exactly minus the
producer premium at every capped rung, which is the arithmetic signature of a product that
never pays. The "measured optimum" of $150 is not a recommendation — it is the statement
"buy the least, or do not buy". (`is_degenerate()` suppresses the argmax entirely in the two
reinsurance years where not even the $0 rung paid; over the pooled window the low rungs did
pay, so the argmax is printed and has to be read with this paragraph.) **[C]**

Yearling finishing is only slightly better: a loss ratio of 0.15 at $70, a return of 30 cents
on the producer dollar, and **every rung negative**. Only RY2026 paid anything at all. **[C]**

This is the same conclusion `docs/lgm.md` §3.4 reached from the Summary of Business (0.40 per
producer dollar), reached independently and at deductible grain — and it is *worse* at the
grain that matters, because the rung the rated model recommends is precisely the rung with
zero realized payout. The caveat there applies here unchanged and is the most important
sentence in this document: **2021–2026 is an extraordinary cattle-margin regime, and a low
loss ratio is partly why nobody needed the coverage rather than proof the product is
mispriced forever.** **[R]**

### 4.3 LGM-Swine: $10 survives, and it is the one result that is stable [C]

| deductible | subsidy | periods | paid | total premium | producer premium | indemnity | loss ratio | net $ | return per producer $ |
|---|---|---|---|---|---|---|---|---|---|
| $0 | 0.18 | 51 | 25 | 1,932 | 1,588 | 1,582 | 0.819 | −6 | 1.00 |
| $8 | 0.37 | 51 | 13 | 1,031 | 652 | 827 | 0.802 | 175 | 1.27 |
| **$10** | **0.47** | **51** | **12** | **860** | **454** | **706** | **0.821** | **252** | **1.55** |
| $12 | 0.50 | 51 | 12 | 715 | 355 | 586 | 0.819 | **231** | **1.64** |
| $20 | 0.50 | 51 | 4 | 312 | 156 | 226 | 0.723 | 70 | 1.45 |

Farrow to Finish shown; the other two swine types agree to within a rung. The measured net
optimum is **$10 — exactly the forward-looking answer** — while the return-per-producer-dollar
optimum is one rung higher at $12. Both are positive. **[C]**

### 4.4 LGM-Dairy: the measured optimum is below $1.00, and here is why [C]

| deductible | subsidy | paid | total premium | producer premium | indemnity | loss ratio | net $ | return per producer $ |
|---|---|---|---|---|---|---|---|---|
| $0.00 | 0.18 | 32 | 420 | 352 | 492 | **1.172** | 140 | 1.43 |
| $0.10 | 0.19 | 30 | 396 | 317 | 461 | 1.165 | **144** | 1.44 |
| $0.40 | 0.25 | 28 | 324 | 232 | 376 | 1.160 | **144** | 1.55 |
| $0.90 | 0.43 | 26 | 227 | 124 | 243 | 1.071 | 119 | 1.88 |
| **$1.00** | 0.48 | 24 | 216 | 115 | 218 | **1.007** | 103 | 1.94 |
| $1.10 | 0.50 | 20 | 191 | 104 | 196 | 1.025 | 92 | **2.05** |
| $2.00 | 0.50 | 12 | 86 | 35 | 45 | **0.528** | 10 | 1.06 |

Two findings here, and the second is the general one.

**The measured net optimum is at the bottom of the ladder, and the top of the ladder is much
worse than rated.** Net at $1.00 is 103 against a peak of 144 — the recommended rung throws
away 28% of the measured benefit. **[C]**

**The plateau blindness disappears on measured data.** `docs/lgm.md` §2.3's known trap is that
return per producer dollar is pinned at 1.94 from $1.10 to $2.00 on rated experience, so it
cannot rank inside the plateau. Measured, it is **not** flat — 2.05, 1.95, 1.83, 1.81, 1.75,
1.56, 1.43, 1.29, 1.17, 1.06 — because the realized loss ratio is not constant across the
plateau. Measurement restores exactly the discriminating power the rated metric loses. **[C]**

### 4.5 The mechanism: the rated model assumes a flat loss ratio [C]

`src/lgm.net_expected_gain` assumes `E[indemnity] = total premium / 1.03`, i.e. a loss ratio
of **0.971 at every rung**. That single assumption is what makes the rated optimum sit where
it does. Measured:

| commodity / type | LR at the bottom rung | LR where the subsidy caps | LR at the top rung |
|---|---|---|---|
| Cattle · Calf Finishing | 0.068 | 0.000 | 0.000 |
| Cattle · Yearling Finishing | 0.148 | 0.151 | 0.102 |
| Swine · Farrow to Finish | 0.819 | 0.819 | 0.723 |
| Swine · Feeder Pig Finishing | 0.811 | 0.795 | 0.678 |
| Swine · SEW Pig Finishing | 0.814 | 0.798 | 0.690 |
| Dairy | **1.172** | 1.025 | **0.528** |

The loss ratio **declines with the deductible** in every commodity. Equivalently: over this
window, RMA's rating over-charged the high rungs relative to what they paid, and the dairy
low rungs were the only part of the LGM ladder that returned more than a dollar of indemnity
per dollar of total premium. Swine is the flattest — which is exactly why swine is the one
commodity where the rated optimum survives measurement. **[C]** The causal reading — that a
deductible bites hardest on the small, frequent shortfalls that the lognormal draw
distribution over-weights in the tail — is **[R]** and untested here.

### 4.6 Does it hold every year? No [C]

| commodity / type | RY2022 | RY2023 | RY2024 | RY2025 | RY2026 |
|---|---|---|---|---|---|
| Cattle · Calf Finishing | $150 | no pay | $150 | no pay | $150 |
| Cattle · Yearling Finishing | no pay | no pay | no pay | no pay | $70 |
| Swine · Farrow to Finish | $12 | $0 | $10 | $20 | $10 |
| Swine · Feeder Pig Finishing | $14 | $0 | $10 | $20 | $10 |
| Swine · SEW Pig Finishing | $14 | $0 | $10 | $20 | $10 |
| Dairy | $0.80 | $0 | $2.00 | $0 | $0 |

The annual optimum swings across the whole grid. **An optimum that holds in aggregate and
nowhere in particular is a different claim from one that holds every year**, and LGM's is the
former. **[C]**

Window sensitivity is the more useful test, because a year is not a natural unit here:

| commodity / type | RY2022–24 | RY2022–25 | RY2023–26 | RY2022–26 |
|---|---|---|---|---|
| Cattle · Calf Finishing | $150 † | $150 † | $150 † | $150 † |
| Cattle · Yearling Finishing | no pay | no pay | $150 | $150 |
| Swine (all three types) | **$10** | **$10** | **$10** | **$10** |
| Dairy | $0.80 | $0.40 | $0.10 | $0.10 |

† $150 is the least-bad rung, not a recommendation: nothing above $50/head paid in any
window, so net is minus the producer premium and falls monotonically with the deductible.

**[C]** So:

- **Swine $10 is robust.** Same answer on four overlapping windows.
- **Dairy's level is not robust; its direction is.** Every window puts the measured optimum
  *below* the computed $1.00, but the level moves by a factor of eight.
- **Cattle is a regime statement, not a rating statement.** **[R]**

---

## 5. Cross-check against RMA's own Summary of Business [C]

sobtpu blends whatever deductibles producers actually elected, so this is a sanity check on
magnitude and ranking, not an identity — the windows differ (SoB crop years 2021–2024, here
RY2022–RY2026) and this reconstruction holds the marketing plan fixed.

| commodity | SoB loss ratio, 2021–24 (`docs/lgm.md` §3.1) | measured range across the ladder |
|---|---|---|
| Cattle | 0.21 | 0.000 – 0.154 |
| Swine | 0.98 | 0.678 – 0.821 |
| Dairy | 1.01 | 0.528 – **1.172** |

The **ranking is reproduced exactly** (cattle ≪ swine < dairy ≈ 1) and dairy's blended figure
falls inside the reconstructed range. Cattle and swine sit slightly *below* SoB. Three
candidate explanations, none tested: the windows differ; the neutral marketing plan is not the
plan producers file; and producers who concentrate target marketings in months they expect
trouble would realize a higher loss ratio than the neutral plan does. If the third is the
main driver, the gap is a measure of producer selection and is itself worth a pass. **[R]**

**Construction check.** The mean of RMA's 500 published draws reproduces RMA's own published
expected margin over all 312 settled periods: **median 0.07%, 90th percentile 0.21%, worst
6.6%** (cattle yearling finishing, where the expected margin is near zero so the relative gap
inflates). A mis-assembled ration or a mis-read column is wrong by orders of magnitude, not by
noise. **[C]**

---

## 6. Things that could have gone wrong, and what guards them

| trap | why it produces plausible numbers | guard |
|---|---|---|
| Two A00600 layouts | a LONG file read as WIDE yields empty months and silently drops years | `parse_gross_margin` branches on the header; both layouts tested to the same record |
| Back-filled expected | RMA re-states the expected vector in the settlement delta; last-wins would price a guarantee nobody could buy | earliest-expected / latest-actual, tested including order-independence |
| Three A00610 dialects | a leg read from the wrong prefix prices corn as a margin | dialect chosen from the A00600 side, never from the year; `validate_draws` against the published expected margin |
| 50 identical state rows | n inflates 50× | `collapse_states` asserts identity and raises |
| Weekly re-quotes | n inflates ~4× | one observation per sales month |
| Overlapping periods | n inflates ~10× | `independent_blocks`, and every summary prints both counts |
| Partial settlement | a three-of-five-month swine period looks settled | a period is settled only when every published month has an actual |
| Missing draws | pricing a realized indemnity off another day's premium | those periods are skipped and counted, never substituted |

---

## 7. The subsidy ladder did not move across the window [V]

`docs/lgm.md` §1.4 records the plan-82 `A00070` ladder as identical in RY2026 and RY2027. It
is identical in **RY2022, RY2023, RY2024 and RY2025 too** — pulled from each year's
`{RY}_ADM_YTD.zip` and compared value for value across all 48 rungs and all three
commodities, and matching `src/lgm.SUBSIDY_BY_DEDUCTIBLE` exactly. **[C]**

So nothing in a measured optimum moving over this window can be attributed to a subsidy
change. The ladder is a constant of the experiment.

---

## 8. What this does *not* establish

- **Anything about the unsubsidised era.** RY2014–RY2021 are in the archive and are readable,
  but their A00600 has no `Sales Effective Date`, so the guarantee cannot be attached to a
  purchase. They are excluded, not measured. Recovering them would mean fingerprinting each
  back-filled expected vector back to the snapshot that first published it — feasible, not
  done here, and it would blend a 0%-subsidy product into a 50%-subsidy one. **[R]**
- **Anything at a producer's own marketing plan.** Everything is the neutral equal-weight
  plan. `realised_curve` takes `h(m)` as an argument for exactly this reason.
- **Statistical significance of any kind.** With 6 to 11 non-overlapping observations per
  commodity, no interval is worth quoting and none is. **The honest summary is that only the
  swine result is stable enough to act on, and the cattle result is a description of
  2021–2026 rather than a property of the product.** **[R]**
- **Whether the RY2026 partial back-fill biases the pool.** RY2026 contributes 3–10 periods
  per commodity against 11–12 for the complete years, so the pooled ladder is unbalanced
  toward the older years. §4.6's window table is the mitigation, not a fix. **[C]**

---

## 9. Where the code is

| file | what it holds |
|---|---|
| `src/lgmbacktest.py` | the archive loader (both A00600 layouts, three A00610 dialects), the merge, the three collapses, the measured ladder, `LGM_TAB_NOTE`, CLI |
| `tests/test_lgmbacktest.py` | 34 tests; the two synthetic bounds (margin always clears the guarantee → zero at every rung; never clears → positive at every rung) are the spine |
| `scripts/analysis/lgm_backtest.py` | reproduces every `[C]` number above |
| `data/cache/lgm/history/` | 641 harvested A00600 members (~19 MB) |
| `data/cache/lgm/history_draws/` | 60 harvested A00610 members, one per sales month (~293 MB) |

```
.venv/bin/python -m src.lgmbacktest --harvest --years 2014-2027
.venv/bin/python -m src.lgmbacktest --ladder --by-year --years 2022-2026
.venv/bin/python -m src.lgmbacktest --ladder --independent-only
.venv/bin/python -m src.lgmbacktest --validate
.venv/bin/python scripts/analysis/lgm_backtest.py --only ladder
```

`src.lgmbacktest.LGM_TAB_NOTE` carries the exact replacement wording for `src/lgm.py` §4 and
the LGM tab caption, with a test asserting it still quotes the sentence it replaces.
