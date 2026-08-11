"""LGM (plan 82) — the Streamlit tab. A DEDUCTIBLE LADDER CALCULATOR, not a map.

`src/lgm.py` is the engine; this file is the only thing that makes it reachable. The page
leads with a calculator rather than a choropleth on purpose, and the reason is structural
rather than aesthetic:

  * LGM's premium subsidy keys off the **deductible**, not a coverage level — ADM `A00070`
    carries plan 82 under record category 05, whose key column is `Deductible Amount`, and
    `Coverage Level Percent` is blank on every plan-82 row. Every other plan in this
    catalog (LRP 81, DRP 83, and the row-crop plans) keys off a coverage level.
  * The filed ladder is **identical in all 50 states** — it is a national A00070 schedule,
    not a county or state actuarial. A choropleth of it would shade the whole country one
    colour and would be answering "is LGM sold here?", which is not the producer's
    question.

So the map that would carry the decision is a *curve*, and the curve runs along the
deductible axis. What varies by state is the margin distribution RMA publishes, which the
page exposes as a state selector feeding the same calculator.

WHAT THE PAGE ANSWERS, IN ORDER
-------------------------------
1. **The ladder.** Commodity, type, size, and number of marketing months in; every filed
   deductible rung out, with its subsidy rate, producer premium, and net expected gain, and
   the net-gain peak marked. Measured optima are $70/head cattle, $10/head swine,
   $1.00–$1.10/cwt dairy — always at or one rung below the point where the ladder caps at
   0.50, never $0 and never the top of the grid.
2. **Why the peak is interior, shown rather than asserted.** Three charts on one x-axis:
   the subsidy RATE (rising, capped), the total premium BASE it applies to (falling), and
   their product, net expected gain (peaked). The producer can see both curves; a single
   recommended number would hide the trade.
3. **The marketing-months trap, prominently.** Subsidy is 0.00 at EVERY deductible unless
   the operation target-markets in two or more months (FCIC-20080 §21 D(8)). Because Step 5
   loads premium by 1.03, break-even needs a 2.91% subsidy — so an unpooled LGM purchase is
   value-destroying at every deductible, the only such configuration in this catalog's
   federal products. Setting the month count to 1 turns the page red; it does not merely
   show a worse number.
4. **The head-to-heads** — LGM-Dairy vs DRP, LGM-Cattle vs LRP, on realized settled
   experience, plus the RY2027 concurrent-coverage change that turns them from an either/or
   into a portfolio question.
5. **Ration divergence** via `lgm.ration_divergence()`, keeping the module's distinction
   between the offsettable LEVEL gap and the untracked VARIANCE that is the real analogue of
   `basisrisk.py`'s miss rate. Only swine is locked to a fixed ration.

HONESTY, WIRED IN RATHER THAN FOOTNOTED
---------------------------------------
  * Everything on the ladder is FORWARD-LOOKING. Realized loss ratio by deductible does not
    exist in any public RMA file — `sobtpu` reports `Coverage Level` as `.0000` for every
    plan-82 row from 2008 forward. The page says so next to the table, not in an expander.
  * The optimum is a property of THIS year's price spread, not of the product. The curve is
    recomputed per (commodity, type, state, sales date) on every render; no optimum is
    cached and re-presented as a constant. The scenario mode exists partly so a producer can
    widen the spread and watch the optimum move.
  * Maximising NET EXPECTED GAIN and maximising PROTECTION are different questions with
    different answers, and both are shown side by side. $0 is maximum protection and
    near-worst value; a producer who cannot absorb the deductible in a bad year is
    rationally buying variance reduction.
  * Return per producer dollar is `1/(1-subsidy)` at rated experience, so it is CONSTANT
    across the cap plateau. The page computes the plateau live and states how far net gain
    falls across it, because that is exactly where the familiar metric goes blind.

DATA
----
Margin draws come from RMA's published `{RY}_ADMLivestockLgm_Daily_*.zip` (`A00600`
expected margins, `A00610` 500 draws), read out of `data/cache/lgm/` — which is
`.gitignore`d, so a deployed container generally has none. The page therefore has two
sources and says which one it is on:

    "RMA published draws"  — the real thing, per state, with the sales effective date and
                             the Monte Carlo standard error shown.
    "Illustrative scenario" — correlated lognormal draws built from an expected margin and
                             a spread the producer sets. Labelled as illustrative
                             everywhere it appears. It is not RMA's rating and the page
                             never pretends it is.

Nothing here fetches over the network, and nothing here writes to the database.

STREAMLIT NOTES
---------------
`streamlit` is imported lazily inside the helpers, never at module scope, for the same
reason `src/drppage.py` does it: the tests import this module and `import streamlit` is
~2 s. The `@st.cache_data` cache-busters are NOT underscore-prefixed — st.cache_data
excludes underscore-prefixed arguments from the cache key, so an underscored buster would
serve the first render forever (`tests/test_cache_keys.py` enforces this and globs
`src/*page*.py`).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from . import config, lgm
from .prfpage import load_aip_commission
from .webmap import STATE_FIPS

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# FIPS -> USPS abbreviation. Built by inverting webmap.STATE_FIPS rather than by adding a
# second copy of the table; src/enrich.py has the full names but imports bs4, which is a
# PIPELINE dependency and is deliberately absent from requirements.txt.
FIPS_TO_ABBREV: dict[str, str] = {v: k for k, v in STATE_FIPS.items()}

# Ordered for the selector. Dairy last because it is the one whose RY2027 margin rows had
# not published at the time of writing (docs/lgm.md §5.2).
COMMODITY_ORDER: tuple[str, ...] = ("0803", "0815", "0847")

# The producer-facing label for the exposure input, per commodity.
SIZE_LABEL = {
    "0803": "Head marketed per marketing month",
    "0815": "Head marketed per marketing month",
    "0847": "Cwt of milk marketed per marketing month",
}

# Notional default exposure. Only the scale of the printed dollars depends on these — every
# ratio and every argmax is invariant to them (tests/test_lgm.py pins that) — but the
# defaults matter anyway, because RMA's Step 5 rounds total premium to WHOLE DOLLARS and a
# one-head-per-month curve is mostly rounding noise.
DEFAULT_SIZE = {"0803": 100.0, "0815": 1000.0, "0847": 10000.0}

# Per-leg price draws are recoverable only for the commodities RMA publishes by COMPONENT.
# Swine (0815) publishes one composite margin row with no Market Symbol Code, so the risk
# layer of ration_divergence() cannot be computed for it from the public file at all.
LEG_TO_PRICE_KEY = {"output": "output_price", "corn": "corn_price",
                    "soybean_meal": "soybean_meal_price", "feeder": "feeder_price"}

# Human labels for the ration legs, per commodity, in the units src.lgm.Ration works in.
LEG_LABELS = {
    "corn_bu": "Corn (bu per unit)",
    "soybean_meal_ton": "Soybean meal (tons per unit)",
    "feeder_cwt": "Feeder animal in (cwt)",
    "output_cwt": "Live animal / milk out (cwt)",
}


# ---------------------------------------------------------------------------
# The prose that carries the argument. Kept as constants so the page cannot drift from
# what the tests assert, and so the citations stay attached to the claims.
# ---------------------------------------------------------------------------

ONE_SENTENCE = (
    "LGM's subsidy is the only one in this catalog keyed on the **deductible** rather than "
    "a coverage level. A $0 deductible is **not** unsubsidised — it draws 18%. The "
    "genuinely unsubsidised case is a **single-month marketing plan**. And because the "
    "ladder caps at 50% while premium keeps shrinking, the deductible that maximises "
    "expected dollars sits strictly **inside** the grid."
)

TRAP_HEADLINE = "Unpooled coverage — the subsidy is 0.00 at EVERY deductible"

TRAP_BODY = (
    "You have target marketings in **one month**, so this purchase is *unpooled* and draws "
    "**no premium subsidy at any deductible**. A $150 deductible is unsubsidised exactly as "
    "hard as a $0 deductible: the cliff is on the marketing plan, not on the deductible "
    "dial.\n\n"
    "> \"The producer is only eligible for premium subsidy if they target market in two (2) "
    "or more months of an insurance period. This is calculated for each SCE.\"\n"
    "> — *LGM for Dairy Cattle Handbook 2026* (FCIC-20080, April 2025), Part 2 §21 D(8); "
    "the same sentence appears at §21 D(8) of the Cattle and Swine handbooks.\n\n"
    "RMA's own premium instructions print this as a second column of the subsidy table, "
    "and that column is **0.00 from $0 through $150**.\n\n"
    "**This is worse than paying full freight.** Step 5 of RMA's premium calculation sets "
    "`total premium = 1.03 × premium`, so at RMA's own rating the expected indemnity is "
    "`total premium / 1.03` and break-even needs a subsidy of **{be:.4%}**. An unpooled LGM "
    "purchase therefore loses **{be:.2%} of total premium in expectation at every rung of "
    "the ladder** — the only configuration in this catalog's federal products that is "
    "value-destroying by construction.\n\n"
    "**The fix is not a different deductible.** Move target marketings into a second month "
    "and the whole ladder switches on."
)

POOLED_NOTE = (
    "**Pooled** — target marketings in {k} months, so the ladder below is live. Subsidy "
    "eligibility turns on the *count* of months with target marketings, not on how much is "
    "in each (FCIC-20080 §21 D(8)). Drop to one month and every rung goes to 0.00 subsidy "
    "and to a {be:.2%} expected loss."
)

# REPLACES an earlier note reading "This table is forward-looking and cannot be backtested."
# The premise was right and the conclusion wrong: sobtpu genuinely reports Coverage Level as
# .0000 for every plan-82 row, but the Summary of Business is the wrong file. ADM A00600
# publishes Month2..Month11 ACTUAL Gross Margin alongside the expected columns, back-filled
# after each marketing month settles, so the indemnity at every filed deductible is
# arithmetic. src/lgmbacktest.py does exactly that. Leaving "cannot be backtested" standing
# next to a backtest would be worse than either sentence alone.
FORWARD_LOOKING_NOTE = (
    "**This table is a forward-looking price, not an observed outcome.** It runs RMA's "
    "published Steps 1–7 against RMA's own margin draws — how an AIP's system actually "
    "prices the policy. Realized loss ratio *by deductible* is absent from the Summary of "
    "Business (`sobtpu` reports `Coverage Level` as `.0000` for every plan-82 row), but it "
    "**can** be reconstructed from ADM `A00600`, which publishes actual gross margins "
    "alongside expected ones. See the measured results immediately below."
)

BACKTEST_NOTE = (
    "**Measured against realized margins, RY2022–RY2026.** Reconstructed from ADM `A00600`'s "
    "actual gross margins — no modelling, just `MAX(0, expected − deductible − actual)`.\n\n"
    "* **Swine — the forward optimum holds.** $10/head wins in every sub-window tested.\n"
    "* **Dairy — the optimum sits BELOW $1.00/cwt** ($0.10–$0.80 depending on window). The "
    "rated model assumes the loss ratio is flat at 1/1.03 across the ladder; measured, it "
    "falls from 1.17 at $0 to 0.53 at $2.00.\n"
    "* **Cattle — every rung lost money, and the $70 rung paid NOTHING.** LGM-Cattle produced "
    "no indemnity at any deductible of $60/head or more across five reinsurance years.\n\n"
    "**Read that against its sample.** LGM margins are *national*, so all 50 states are ONE "
    "observation, and consecutive monthly periods share nine of their ten marketing months — "
    "leaving only **6–11 non-overlapping observations** per commodity. Swine is stable across "
    "sub-windows. Dairy's direction is robust but its level is not. The cattle result "
    "describes the extraordinary 2021–2026 cattle-margin regime, not how LGM-Cattle is rated "
    "in general."
)

SPREAD_NOTE = (
    "**The optimum is a fact about this year's price spread, not about the product.** The "
    "argmax depends on how volatile the *total* simulated margin is relative to the "
    "deductible grid: widen the margin distribution and the optimum rises, tighten it and it "
    "falls, all the way to $0. This page recomputes the curve for the commodity, type, "
    "state and sales date you selected on every render — no optimum is stored and reused."
)

SCENARIO_WARNING = (
    "**Illustrative scenario — not RMA's rating.** These draws are correlated lognormal "
    "margins generated from the expected margin and spread you set, not RMA's published "
    "`A00610` draws. The *shape* of the trade-off is real; the dollars are not a quote. "
    "Put an LGM ADM zip in `data/cache/lgm/` (`.venv/bin/python -m src.lgm --margins "
    "--year 2027`) to price against RMA's own numbers."
)

CONCURRENT_NOTE = (
    "**From RY2027 this is becoming a portfolio question rather than an either/or.** The "
    "26-LGM Dairy Cattle policy still bars the pairing at §3(i) — you \"may not have any "
    "other FCIC reinsured livestock policy covering the same class of livestock for any "
    "month for which you have target marketings\" — but RMA's 2027 announcement lists "
    "\"Permitting concurrent coverage between similar livestock programs\" among the changes "
    "effective for the 2027 crop year. Neither `src/lgm.py` nor this page models a stacked "
    "LGM+DRP position; both legs are reported separately."
)

RATION_LEVEL_VS_RISK = (
    "**The level gap is not basis risk.** It shifts the guarantee up or down by a known "
    "amount, and the deductible dial can be moved to offset it. The basis risk is the "
    "*untracked variance* — the fraction of your operation's real margin risk the policy "
    "does not follow, measured across RMA's own published draws. It is the LGM analogue of "
    "`basisrisk.py`'s miss rate, and the two numbers are usually very different sizes."
)

RATION_ELIMINABLE_NOTE = (
    "**Ration basis risk is ELIMINABLE for cattle and dairy inside RMA's declaration band, "
    "and IRREDUCIBLE outside it and for swine at all times.** An operation that simply "
    "accepts the default ration is taking *avoidable* basis risk in two of the three "
    "commodities. That is a different piece of advice from \"LGM has basis risk\"."
)

SWINE_NO_RISK_LAYER = (
    "Swine publishes its margin as a single composite row with no per-component price paths "
    "(`A00600` carries a Market Symbol Code for cattle and dairy only), so the *risk* layer "
    "cannot be computed for swine from the public file. It would not change the advice: the "
    "swine ration is FIXED, no election exists, and whatever divergence an operation has is "
    "what it keeps."
)

RATION_IDENTITY_NOTE = (
    "**These boxes start on RMA's declared ration, so the numbers below are currently "
    "comparing that ration to itself.** A zero gap and a 1.0000 correlation are the correct "
    "answer to the question as posed — an operation that feeds exactly what RMA declares has "
    "no ration basis risk by construction — not a failed calculation. Change a box above to "
    "what the operation actually feeds and the three layers start measuring something."
)


# ---------------------------------------------------------------------------
# Head-to-head, on realized experience
# ---------------------------------------------------------------------------
# From the cached `sobtpu` files, settled crop years only, national, using the same
# loss_ratio / (1 - subsidy) metric sob_national.indemnity_per_producer_dollar uses.
# Computed 2026-08-08 by scripts/analysis/lgm_deductible.py --only headtohead and recorded
# in docs/lgm.md §3; pinned here because the plan-82 rows never reach the catalog DB (the
# row-crop gate in src/connectors/rma_sob.py drops them — see lgm.SOB_GATE_NOTE), so the app
# cannot recompute them from what it ships. Every row satisfies
# per_dollar == loss_ratio / (1 - subsidy) to rounding, which tests/test_lgmpage.py checks.

HEAD_TO_HEAD_ASOF = "2026-08-08"
HEAD_TO_HEAD_LAST_SETTLED_YEAR = 2024
HEAD_TO_HEAD_FIRST_SUBSIDISED_YEAR = 2021

HEAD_TO_HEAD_SUBSIDISED: tuple[dict, ...] = (
    {"plan": "LGM Dairy Cattle", "total_premium": 78_503_078, "subsidy": 0.479,
     "loss_ratio": 1.01, "per_dollar": 1.93},
    {"plan": "LGM Swine", "total_premium": 147_309_662, "subsidy": 0.440,
     "loss_ratio": 0.98, "per_dollar": 1.76},
    {"plan": "DRP (all)", "total_premium": 1_595_724_412, "subsidy": 0.441,
     "loss_ratio": 0.75, "per_dollar": 1.34},
    {"plan": "LRP (all)", "total_premium": 2_053_098_233, "subsidy": 0.352,
     "loss_ratio": 0.64, "per_dollar": 0.99},
    {"plan": "LGM Cattle", "total_premium": 48_942_234, "subsidy": 0.478,
     "loss_ratio": 0.21, "per_dollar": 0.40},
)

HEAD_TO_HEAD_ALL_SETTLED: tuple[dict, ...] = (
    {"plan": "LGM Swine", "total_premium": 161_984_349, "subsidy": 0.400,
     "loss_ratio": 0.99, "per_dollar": 1.65},
    {"plan": "DRP (all)", "total_premium": 1_690_705_878, "subsidy": 0.441,
     "loss_ratio": 0.75, "per_dollar": 1.33},
    {"plan": "LGM Dairy Cattle", "total_premium": 173_377_876, "subsidy": 0.457,
     "loss_ratio": 0.63, "per_dollar": 1.16},
    {"plan": "LRP (all)", "total_premium": 2_126_228_487, "subsidy": 0.345,
     "loss_ratio": 0.67, "per_dollar": 1.02},
    {"plan": "LGM Cattle", "total_premium": 51_127_128, "subsidy": 0.458,
     "loss_ratio": 0.21, "per_dollar": 0.39},
)

DAIRY_VS_DRP = (
    "**LGM-Dairy beat DRP in the subsidised era, 1.93 vs 1.34** — despite a *lower* subsidy "
    "ceiling (0.50 against DRP's 0.55 at the 80% coverage level). The whole difference is "
    "rating: LGM-Dairy came in at a loss ratio of 1.01 against DRP's 0.75.\n\n"
    "**Over the longer window the ranking reverses, 1.16 vs 1.33**, because LGM-Dairy's "
    "2011–2019 experience was poor (loss ratios of 0.00, 0.07, 0.16 and 0.32 in 2011–2014). "
    "Four years of a favourable regime is not a durable edge, and the two windows are shown "
    "together because they disagree."
)

CATTLE_VS_LRP = (
    "**LRP wins decisively: 0.99 against 0.40.** Price-only beats margin on the same herd, "
    "and LGM-Cattle is the standout finding — the mirror image of this repo's row-crop "
    "result, where an 85% coverage level returns the worst number because its subsidy "
    "collapses. Here the subsidy is at the *top* of the ladder (47.8%, better than LRP's "
    "blended 35.2%) and the product still returns 40 cents on the producer dollar, because "
    "`0.21 / (1 − 0.478) = 0.40`. **A generous subsidy rate cannot rescue a loss ratio of "
    "0.21.**\n\n"
    "Caveats, in order of importance: 2021–2024 was an extraordinary cattle-margin regime "
    "(record fed-cattle prices against a feeder market that has not kept up), and low loss "
    "ratios are partly *why* nobody needed the coverage rather than evidence of permanent "
    "mispricing; the premium base is small ($49M over four years against $2.05B for LRP), "
    "so the ratio is noisy — though consistently low, at 0.06, 0.26, 0.02 and 0.29; and the "
    "RY2027 ADM shows some states' yearling-finishing expected margins **negative** in most "
    "months, which is a different instrument from the one those historic loss ratios "
    "describe."
)

BLENDED_DEDUCTIBLE_CAVEAT = (
    "These are **realized** numbers, blended across whatever deductibles producers actually "
    "elected — there is no way to split them by deductible, because `sobtpu` carries "
    "`.0000` in the coverage-level column for every plan-82 row. The observed blended "
    "subsidy of 46–48% implies most business already sits at or near the 0.50 cap. Section 1 "
    "is forward-looking; this section is backward-looking; neither can be converted into "
    "the other."
)


# ---------------------------------------------------------------------------
# Reading RMA's published margin draws out of the local ADM cache
# ---------------------------------------------------------------------------

@dataclass
class AdmCase:
    """One (reinsurance year, commodity, type, state) out of the LGM ADM, ready to price.

    `expected` and `draws` are the composite gross margin per unit of exposure, exactly as
    `lgm.build_panels()` assembles them. `leg_expected` / `leg_draws` are the per-COMPONENT
    price paths behind that composite, which `lgm.MarginPanel` does not retain — they are
    re-derived here because `ration_divergence()`'s risk layer needs price draws per leg and
    there is no public accessor for them (see the module docstring).
    """
    reinsurance_year: int
    zip_name: str
    commodity_code: str
    type_code: str
    state_code: str
    sales_effective_date: str
    months: tuple[int, ...]
    expected: np.ndarray                       # (n_months,)
    draws: np.ndarray                          # (n_draws, n_months)
    ration: lgm.Ration | None = None
    liability_price: float | None = None
    leg_expected: dict[str, np.ndarray] | None = None   # leg -> (n_months,)
    leg_draws: dict[str, np.ndarray] | None = None      # leg -> (n_draws, n_months)

    @property
    def n_draws(self) -> int:
        return int(self.draws.shape[0])

    @property
    def has_leg_prices(self) -> bool:
        return bool(self.leg_draws)


def cached_adm_zips(cache_dir: Path | None = None) -> list[Path]:
    """Every LGM ADM zip sitting in the local cache, newest reinsurance year first.

    `data/cache/` is `.gitignore`d, so this is normally empty on a deployed container and
    the page falls back to the illustrative scenario. Populate it with
    `.venv/bin/python -m src.lgm --margins --year 2027`.
    """
    d = cache_dir or (config.CACHE_DIR / "lgm")
    if not d.exists():
        return []
    return sorted(d.glob("*_ADMLivestockLgm_Daily_*.zip"), reverse=True)


def zip_reinsurance_year(name: str) -> int | None:
    m = re.match(r"(\d{4})_ADMLivestockLgm_Daily_", Path(name).name)
    return int(m.group(1)) if m else None


def read_members(path: Path | str) -> dict[str, str]:
    """{'A00600': text, 'A00610': text} from one LGM ADM zip. Local read; no network."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        for n in zf.namelist():
            if not n.lower().endswith(".txt"):
                continue
            tag = "A00600" if "A00600" in n else ("A00610" if "A00610" in n else n)
            out[tag] = zf.read(n).decode("utf-8", "replace")
    return out


def adm_index(gross_margin_text: str) -> dict[tuple[str, str], list[str]]:
    """{(commodity, type): [state codes]} from the small A00600 member alone.

    Reads only the expected-margin member (~128 KB) so the selectors can be built without
    parsing the 40 MB draw file. RY2027 currently carries cattle and swine only; dairy's
    margin rows had not published as of the 20260806 pull (docs/lgm.md §5.2).
    """
    out: dict[tuple[str, str], set[str]] = {}
    for r in lgm.parse_pipe(gross_margin_text):
        if str(r.get("Insurance Plan Code", "")).strip() != lgm.PLAN_CODE:
            continue
        cc = str(r.get("Commodity Code", "")).strip()
        tc = str(r.get("Type Code", "")).strip()
        sc = str(r.get("State Code", "")).strip()
        if cc and tc and sc:
            out.setdefault((cc, tc), set()).add(sc)
    return {k: sorted(v) for k, v in sorted(out.items())}


def leg_price_paths(gross_margin_text: str, draw_text: str, commodity_code: str,
                    type_code: str, state_code: str,
                    ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]] | None:
    """Per-COMPONENT expected prices and draws for one cell, or None when not published.

    `lgm.build_panels()` collapses the three cattle rows (LE / GF / C) and the three dairy
    rows (DA / C / SM) into one composite margin and does not keep the component paths, so
    `MarginPanel` cannot feed `ration_divergence(price_draws=...)`. Everything needed to
    rebuild them is public — `lgm.COMPONENT_LEGS`, `lgm.INSURED_MONTHS`, `lgm.parse_pipe`
    and `lgm.monthly` — so this reassembles them rather than reaching into `_component_panel`.

    Returns (expected, draws) keyed by leg name ('output', 'corn', 'soybean_meal',
    'feeder'), or None for swine, which publishes no component rows at all.
    """
    spec = lgm.COMPONENT_LEGS.get(commodity_code)
    if not spec:
        return None
    months = lgm.INSURED_MONTHS.get(commodity_code, tuple(range(2, 12)))

    def want(r: dict[str, str]) -> bool:
        return (str(r.get("Insurance Plan Code", "")).strip() == lgm.PLAN_CODE
                and str(r.get("Commodity Code", "")).strip() == commodity_code
                and str(r.get("Type Code", "")).strip() == type_code
                and str(r.get("State Code", "")).strip() == state_code)

    symbol_to_leg = {sym: leg for leg, (sym, _) in spec.items()}
    by_leg: dict[str, dict[str, str]] = {}
    for r in lgm.parse_pipe(gross_margin_text):
        if not want(r):
            continue
        leg = symbol_to_leg.get((r.get("Market Symbol Code") or "").strip())
        if leg is not None:
            by_leg[leg] = r
    if set(by_leg) != set(spec):
        return None

    draw_rows = [r for r in lgm.parse_pipe(draw_text) if want(r)]
    if not draw_rows:
        return None

    expected: dict[str, np.ndarray] = {}
    draws: dict[str, np.ndarray] = {}
    for leg, (_, prefix) in spec.items():
        e = lgm.monthly(by_leg[leg], "Month{m} Expected Gross Margin Amount", months)
        d = [lgm.monthly(row, prefix + "Month{m} Margin Draw Amount", months)
             for row in draw_rows]
        if any(v is None for v in e) or any(v is None for row in d for v in row):
            return None
        expected[leg] = np.asarray(e, float)
        draws[leg] = np.asarray(d, float)
    return expected, draws


def load_case(path: Path | str, commodity_code: str, type_code: str,
              state_code: str) -> AdmCase | None:
    """One priceable cell out of one ADM zip, with its component price paths where they exist.

    Filters at `build_panels()` so only the requested cell is assembled; the 40 MB draw
    member still has to be parsed, which is the ~1.5 s this call costs and the reason the
    Streamlit wrapper memoizes it.
    """
    path = Path(path)
    ry = zip_reinsurance_year(path.name)
    if ry is None:
        return None
    members = read_members(path)
    gm, dr = members.get("A00600", ""), members.get("A00610", "")
    panels = lgm.build_panels(gm, dr, commodity_code=commodity_code,
                              type_code=type_code, state_code=state_code)
    if not panels:
        return None
    p = max(panels, key=lambda q: q.sales_effective_date)   # newest sales date wins
    legs = leg_price_paths(gm, dr, commodity_code, type_code, state_code)
    return AdmCase(
        reinsurance_year=ry, zip_name=path.name, commodity_code=p.commodity_code,
        type_code=p.type_code, state_code=p.state_code,
        sales_effective_date=p.sales_effective_date, months=p.months,
        expected=np.asarray(p.expected, float), draws=np.asarray(p.draws, float),
        ration=p.ration, liability_price=p.liability_price,
        leg_expected=legs[0] if legs else None, leg_draws=legs[1] if legs else None)


# ---------------------------------------------------------------------------
# The illustrative fallback
# ---------------------------------------------------------------------------

def scenario_draws(expected_per_month: float, n_months: int, *, spread: float = 0.30,
                   idio: float = 0.10, n_draws: int = 2000,
                   seed: int = 20260808) -> tuple[np.ndarray, np.ndarray]:
    """Correlated lognormal margins — the shape of RMA's draws, none of their authority.

    The correlation is the part that must not be skipped. RMA's real draws share ONE price
    path across the whole insurance period, so the TOTAL margin stays volatile; independent
    monthly draws diversify most of that away, put premium at ~3% of expected total margin
    instead of the 12–24% the published draws produce, and move the optimum all the way to
    $0. `spread` is the common (period-wide) log sd and `idio` the per-month one; the mean
    correction keeps E[margin] at `expected_per_month`.

    Same construction as tests/test_lgm.py::_panel, deliberately.
    """
    if n_months < 1:
        raise ValueError("need at least one month")
    rng = np.random.default_rng(seed)
    expected = np.full(int(n_months), float(expected_per_month))
    z = (rng.normal(0.0, float(spread), size=(int(n_draws), 1))
         + rng.normal(0.0, float(idio), size=(int(n_draws), expected.size)))
    draws = expected * np.exp(z - 0.5 * (float(spread) ** 2 + float(idio) ** 2))
    return expected, draws


# ---------------------------------------------------------------------------
# Pure shaping for the page
# ---------------------------------------------------------------------------

def marketing_plan(n_months: int, n_marketing_months: int,
                   per_month: float) -> list[float]:
    """`per_month` of exposure in the first k insurable months, zero after.

    The subsidy gate counts MONTHS WITH TARGET MARKETINGS, not quantity, so k is the dial
    that turns pooling on and off (`lgm.is_pooled` wants k >= 2). Which months carry the
    exposure changes the premium — later months are further out and more volatile — but not
    the eligibility, so the page asks for a count rather than eleven separate boxes.
    """
    n = int(n_months)
    k = max(0, min(int(n_marketing_months), n))
    return [float(per_month)] * k + [0.0] * (n - k)


def subsidy_ladder_source(db_path: str | None, reinsurance_year: int,
                          ) -> tuple[dict[str, dict[float, float]], str]:
    """(ladder, provenance label). Prefers the ADM rows in `lgm_subsidy` over the constant.

    The ladder is byte-identical in RY2026 and RY2027, but "identical so far" is not
    "frozen" — PM-26-024's OBBBA language reads like a change to it. So the live table wins
    whenever it has rows, and the page says which one it is showing.
    """
    fallback = (lgm.SUBSIDY_BY_DEDUCTIBLE,
                f"module constant (verified identical in RY{lgm.SUBSIDY_SOURCE_YEARS[0]} "
                f"and RY{lgm.SUBSIDY_SOURCE_YEARS[1]})")
    if not db_path:
        return fallback
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                               check_same_thread=False)
        try:
            table = lgm.subsidy_table(conn, int(reinsurance_year))
        finally:
            conn.close()
    except Exception:
        return fallback
    if table is lgm.SUBSIDY_BY_DEDUCTIBLE:
        return fallback
    return table, f"ADM A00070, loaded into lgm_subsidy for RY{reinsurance_year}"


def ladder_rows(curve: Sequence[lgm.DeductibleCell], unit: str = "unit") -> list[dict]:
    """The ladder as table rows, with the three argmaxes marked.

    All three markers are computed and shown together because they answer three different
    questions and give three different answers — net dollars, return per producer dollar,
    and protection retained. Presenting only the first would be advice; presenting all three
    is the actual decision.

    An UNPOOLED curve gets no argmax markers. One still exists arithmetically — the top
    rung, because it buys the least coverage and therefore loses the least — but every rung
    is negative, so marking one as "best" would read as a recommendation where the honest
    answer is that the deductible is not the dial to move.
    """
    cells = list(curve)
    if not cells:
        return []
    pooled = cells[0].pooled
    best_gain = lgm.optimal_deductible(cells, "gain")
    best_pd = lgm.optimal_deductible(cells, "per_dollar")
    best_prot = lgm.optimal_deductible(cells, "protection")
    rows = []
    for c in cells:
        marks = []
        if not pooled:
            if c is best_gain:
                marks.append("least-bad rung — still negative")
        else:
            if c is best_gain:
                marks.append("◀ max net gain")
            if c is best_pd:
                marks.append("max return per $1")
            if c is best_prot:
                marks.append("max protection")
        rows.append({
            "Deductible": c.deductible,
            "Subsidy": c.subsidy,
            "Total premium": c.total_premium,
            "Producer premium": c.producer_premium,
            "E[indemnity]": c.expected_indemnity,
            "Net expected gain": c.net_expected_gain,
            "Return per $1": c.return_per_producer_dollar,
            "Guarantee retained": c.guarantee_retained,
            "± MC s.e.": lgm.LOADING_FACTOR * c.premium_stderr,
            "": "  ·  ".join(marks),
        })
    return rows


def curve_frame_rows(curve: Sequence[lgm.DeductibleCell]) -> list[dict]:
    """Long-form rows for the three charts that make the interior peak visible."""
    return [{"Deductible": c.deductible,
             "Subsidy rate": c.subsidy,
             "Total premium": c.total_premium,
             "Net expected gain": c.net_expected_gain}
            for c in curve]


def objective_summary(curve: Sequence[lgm.DeductibleCell]) -> dict:
    """The three argmaxes, the cap plateau, and how far net gain falls across it.

    `plateau_gain_fall` is the number that matters for the honesty requirement: return per
    producer dollar is `1/(1-subsidy)`, so it is CONSTANT everywhere the subsidy is at its
    cap, while net expected gain keeps falling. Ranking within the plateau on the familiar
    metric is ranking on a constant.
    """
    cells = list(curve)
    if not cells:
        raise ValueError("empty curve")
    gain = lgm.optimal_deductible(cells, "gain")
    per_dollar = lgm.optimal_deductible(cells, "per_dollar")
    protection = lgm.optimal_deductible(cells, "protection")
    top_subsidy = max(c.subsidy for c in cells)
    plateau = [c for c in cells if c.subsidy == top_subsidy]
    first, last = plateau[0], plateau[-1]
    fall = None
    if len(plateau) > 1 and first.net_expected_gain > 0:
        fall = 1.0 - last.net_expected_gain / first.net_expected_gain
    zero = cells[0]
    uplift = (gain.net_expected_gain / zero.net_expected_gain
              if zero.net_expected_gain > 0 else None)
    return {
        "gain": gain, "per_dollar": per_dollar, "protection": protection,
        "zero": zero, "top": cells[-1],
        "uplift_vs_zero": uplift,
        "pooled": cells[0].pooled,
        "plateau": plateau,
        "plateau_subsidy": top_subsidy,
        "plateau_return_per_dollar": first.return_per_producer_dollar,
        "plateau_gain_fall": fall,
        "any_negative_guarantee": any(c.guarantee_retained < 0 for c in cells),
    }


def ration_from_inputs(commodity_code: str, type_code: str,
                       values: dict[str, float]) -> lgm.Ration:
    """Build a `Ration` for the producer's own numbers, defaulting any leg not supplied.

    Legs the insured ration does not have (a dairy buys no feeder animal; cattle is fed no
    soybean meal) stay None, which is what `_leg_values()` keys off.
    """
    insured = lgm.ration_for(commodity_code, type_code)
    def pick(field: str):
        base = getattr(insured, field)
        if base is None:
            return None
        v = values.get(field)
        return float(v) if v is not None else base

    return lgm.Ration(commodity_code, type_code,
                      corn_bu=pick("corn_bu"),
                      soybean_meal_ton=pick("soybean_meal_ton"),
                      feeder_cwt=pick("feeder_cwt"),
                      output_cwt=pick("output_cwt"),
                      electable=insured.electable)


def marketing_weighted_prices(case: AdmCase, marketings: Sequence[float],
                              ) -> tuple[dict[str, float], dict[str, np.ndarray]] | None:
    """Component prices averaged over the marketing plan: one observation per RMA draw.

    Weighting by the marketing plan rather than picking a single month is the honest choice
    for a divergence measure that sits under a deductible calculator — it measures the
    operation's exposure over the period it actually insured. With 500 published draws that
    yields 500 observations, and the residual sd / tracking correlation come out per unit of
    exposure in the same units as the ladder above.
    """
    if not case.has_leg_prices or case.leg_expected is None or case.leg_draws is None:
        return None
    h = np.asarray(marketings, float)
    if h.size != len(case.months) or h.sum() <= 0:
        return None
    w = h / h.sum()
    prices = {LEG_TO_PRICE_KEY[leg]: float(np.dot(vals, w))
              for leg, vals in case.leg_expected.items()}
    draws = {LEG_TO_PRICE_KEY[leg]: arr @ w for leg, arr in case.leg_draws.items()}
    return prices, draws


def state_label(fips: str) -> str:
    ab = FIPS_TO_ABBREV.get(str(fips).zfill(2))
    return f"{fips} — {ab}" if ab else str(fips)


def commodity_label(cc: str) -> str:
    return lgm.COMMODITY_NAMES.get(cc, cc)


def type_label(cc: str, tc: str) -> str:
    return lgm.TYPE_NAMES.get((cc, tc), tc)


# ---------------------------------------------------------------------------
# Streamlit helpers — created once per process, never re-decorated per rerun
# ---------------------------------------------------------------------------

_HELPERS: dict = {}


def _streamlit_helpers() -> dict:
    """Memoized cached functions.

    Built lazily so importing this module costs nothing outside Streamlit, and stashed in a
    module-level dict rather than rebuilt inside `render()`, because a decorator re-applied
    on every rerun produces a NEW function object and silently defeats the cache it was
    added for.

    NOTE THE PARAMETER NAMES. `st.cache_data` excludes underscore-prefixed arguments from
    the cache key, so every cache-buster here (`mtime`) is bare. tests/test_cache_keys.py
    globs `src/*page*.py` and fails the build if that regresses.
    """
    if _HELPERS:
        return _HELPERS
    import streamlit as st

    @st.cache_data(show_spinner=False)
    def index(zip_path: str, mtime: float) -> dict:
        """{(commodity, type): [states]} — parses only the small A00600 member."""
        members = read_members(zip_path)
        return {f"{cc}|{tc}": states
                for (cc, tc), states in adm_index(members.get("A00600", "")).items()}

    @st.cache_data(show_spinner="Reading RMA's published margin draws…")
    def case(zip_path: str, mtime: float, commodity_code: str, type_code: str,
             state_code: str) -> AdmCase | None:
        return load_case(zip_path, commodity_code, type_code, state_code)

    _HELPERS.update(index=index, case=case)
    return _HELPERS


def _db_path() -> str | None:
    """Same priority order streamlit_app and drppage use; None when nothing exists."""
    import os

    app_db = config.DATA_DIR / "catalog_app.db"
    p = (os.environ.get("AIP_DB_PATH")
         or (str(app_db) if app_db.exists() else str(config.DB_PATH)))
    return p if p and Path(p).exists() else None


def _mtime(path) -> float:
    import os

    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# Section 1 — the ladder
# ---------------------------------------------------------------------------

def _render_ladder(st, lens: str = "buy") -> None:
    helpers = _streamlit_helpers()
    zips = cached_adm_zips()

    st.markdown("### 1. The deductible ladder")
    st.caption(
        "Pick the operation; the page prices **every filed deductible** against RMA's "
        "published Steps 1–7 and marks where net expected gain peaks. The ladder itself is "
        "national — the same rungs and the same subsidy rates in all 50 states — so what "
        "the state selector changes is the margin distribution, not the schedule."
    )

    # ---------------------------------------------------------------- inputs
    c1, c2, c3, c4 = st.columns([1.1, 1.4, 1.1, 1.2])
    with c1:
        cc = st.selectbox("Commodity", COMMODITY_ORDER, index=0,
                          format_func=commodity_label, key="lgm_commodity")
    types = [t for (c, t) in sorted(lgm.DECLARED_RATION) if c == cc]
    with c2:
        tc = st.selectbox("Type / operation", types, index=0,
                          format_func=lambda t: type_label(cc, t), key="lgm_type")
    with c3:
        size = st.number_input(SIZE_LABEL[cc], min_value=1.0,
                               value=DEFAULT_SIZE[cc], step=max(1.0, DEFAULT_SIZE[cc] / 10),
                               key=f"lgm_size_{cc}")
    n_months = len(lgm.INSURED_MONTHS.get(cc, tuple(range(2, 12))))
    with c4:
        k = st.slider("Months with target marketings", min_value=1, max_value=n_months,
                      value=n_months, key=f"lgm_months_{cc}",
                      help="The subsidy eligibility gate counts MONTHS, not quantity. "
                           "One month = unpooled = zero subsidy at every deductible.")

    # Which ADM file, if any, and which state.
    source_options = (["RMA published draws (ADM A00610)"] if zips else []) + \
        ["Illustrative scenario"]
    s1, s2, s3 = st.columns([1.4, 1.0, 1.4])
    with s1:
        source = st.radio("Margin draws", source_options, index=0, horizontal=True,
                          key="lgm_source")
    use_adm = source.startswith("RMA")

    case: AdmCase | None = None
    scenario_spread = 0.30
    scenario_level = 0.0
    if use_adm:
        with s2:
            zname = st.selectbox("ADM file", [p.name for p in zips], index=0,
                                 key="lgm_zip")
        zpath = next(p for p in zips if p.name == zname)
        combos = helpers["index"](str(zpath), _mtime(zpath))
        states = combos.get(f"{cc}|{tc}", [])
        if not states:
            st.warning(
                f"**{commodity_label(cc)} / {type_label(cc, tc)} is not in "
                f"`{zname}`.** As of the 20260806 pull the RY2027 livestock ADM carries "
                "cattle and swine only — LGM-Dairy's margin and draw rows publish on their "
                "own cadence and had not landed, even though dairy's full 21-rung subsidy "
                "ladder IS filed in the RY2027 A00070. Choose an RY2026 file for dairy, or "
                "switch to the illustrative scenario."
            )
            use_adm = False
        else:
            with s3:
                default_state = "19" if "19" in states else states[0]
                sc = st.selectbox("State", states,
                                  index=states.index(default_state),
                                  format_func=state_label, key=f"lgm_state_{cc}_{tc}")
            case = helpers["case"](str(zpath), _mtime(zpath), cc, tc, sc)
            if case is None:
                st.warning("That state has no usable margin row in this file — "
                           "falling back to the illustrative scenario.")
                use_adm = False

    if not use_adm:
        with s2:
            scenario_level = st.number_input(
                f"Expected margin per {lgm.COMMODITY_UNIT[cc]} per month ($)",
                min_value=0.01,
                value={"0803": 300.0, "0815": 45.0, "0847": 5.0}[cc],
                step=1.0, key=f"lgm_scen_level_{cc}")
        with s3:
            scenario_spread = st.slider(
                "Margin spread (period-wide log sd)", min_value=0.05, max_value=0.80,
                value=0.30, step=0.05, key="lgm_scen_spread",
                help="Widen this and watch the optimum move. That is the point: the "
                     "optimum is a property of the price spread, not of the product.")

    with st.expander("Beginning farmer or rancher, and which subsidy ladder is in force"):
        bfr = st.checkbox("Beginning farmer or rancher", value=False, key="lgm_bfr")
        bfr_year = None
        if bfr:
            bfr_year = st.slider("Year of BFR status", 1, lgm.BFR_MAX_YEARS, 1,
                                 key="lgm_bfr_year")
        st.caption(
            "Policy §5(f) adds a flat 10 percentage points; RMA's 2027 announcement layers "
            "the OBBBA ladder on top — an extra 5 points in BFR years one and two, 3 in "
            "year three, 1 in year four. Both are gated behind the pooling rule: an "
            "unpooled beginning farmer is still unsubsidised."
        )

    ry = case.reinsurance_year if case else (zip_reinsurance_year(zips[0].name) if zips
                                             else 2027)
    table, ladder_source = subsidy_ladder_source(_db_path(), ry)
    with st.expander("Subsidy ladder in force", expanded=False):
        st.caption(f"Source: {ladder_source}.")
        st.dataframe(
            [{"Deductible": d, "Subsidy": table.get(cc, {}).get(d, float("nan"))}
             for d in lgm.deductible_grid(cc, table)],
            width='stretch', hide_index=True)
        st.caption(
            "ADM `A00070 Subsidy Percent` carries plan 82 under record category 05, keyed "
            "on **Deductible Amount**; `Coverage Level Percent` is blank on every plan-82 "
            "row. Plan 81 (LRP) is keyed on coverage level under category 08 and plan 83 "
            "(DRP) under category 04. This is the structural difference the whole tab turns "
            "on. Do not treat the ladder as frozen — it is read per year, and the module "
            "constant is a documented fallback, not the source of truth."
        )

    # ------------------------------------------------ the pooling gate, up front
    break_even = lgm.break_even_subsidy()
    if k < 2:
        st.error(f"#### {TRAP_HEADLINE}\n\n" + TRAP_BODY.format(be=break_even))
    else:
        st.success(POOLED_NOTE.format(k=k, be=break_even))

    # ------------------------------------------------------------ the curve
    if case is not None:
        expected, draws = case.expected, case.draws
        months = case.months
    else:
        expected, draws = scenario_draws(scenario_level, n_months,
                                         spread=scenario_spread)
        months = lgm.INSURED_MONTHS.get(cc, tuple(range(2, 12)))
        st.warning(SCENARIO_WARNING)

    h = marketing_plan(len(months), k, size)
    try:
        curve = lgm.deductible_curve(cc, tc, case.state_code if case else "--",
                                     expected, draws, h, bfr_year=bfr_year, table=table)
    except Exception as exc:                                # never take the tab down
        st.error(f"Could not price the ladder: {type(exc).__name__}: {exc}")
        return
    summary = objective_summary(curve)
    unit = lgm.COMMODITY_UNIT[cc]

    # ONE CURVE, TWO READINGS. The agency view branches here rather than living in its own
    # section, because it must price the SAME ladder the producer sees — same commodity,
    # type, state, marketing plan and subsidy table. A second section rebuilding its own
    # curve could disagree with this one, and the whole point of the divergence warning is
    # that the two numbers describe one policy.
    if lens == "sell":
        _agency_table(st, curve, unit)
        return

    if case is not None:
        st.caption(
            f"RY{case.reinsurance_year} · `{case.zip_name}` · sales effective "
            f"{case.sales_effective_date} · {state_label(case.state_code)} · "
            f"{case.n_draws} published margin draws over {len(case.months)} insurable "
            f"months. RMA's premium instructions specify 5,000 draws and divide by 5,000; "
            f"the file RMA actually publishes carries {case.n_draws}, so every premium here "
            f"is a {case.n_draws}-draw estimate of the number an AIP's system produces and "
            f"the ± column is its Monte Carlo standard error."
        )

    # ------------------------------------------------------------- headline
    #
    # There is deliberately NO recommended deductible when the plan is unpooled. The
    # argmax still exists arithmetically — it is the top rung, because that buys the least
    # coverage and therefore loses the least — but presenting "$150" as the answer next to
    # a red banner would be exactly the "just show a worse number" failure the banner is
    # there to prevent. Every rung is negative; the decision is not which rung.
    g = summary["gain"]
    if not summary["pooled"]:
        worst = min(c.net_expected_gain for c in curve)
        m1, m2, m3 = st.columns(3)
        m1.metric("Recommended deductible", "none",
                  help="Every rung has a negative expected value while unpooled. The "
                       "least-bad rung is least bad only because it buys the least "
                       "coverage — that is not a recommendation.")
        m2.metric("Subsidy at every rung", "0%")
        m3.metric("Expected loss, best to worst rung",
                  f"${g.net_expected_gain:,.0f} to ${worst:,.0f}")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Deductible that maximises net gain ($/{unit})",
                  f"${g.deductible:,.2f}")
        m2.metric("Subsidy there", f"{g.subsidy:.0%}")
        m3.metric("Net expected gain", f"${g.net_expected_gain:,.0f}")
        m4.metric("vs a $0 deductible",
                  "n/a" if summary["uplift_vs_zero"] is None
                  else f"{summary['uplift_vs_zero']:.2f}×")

    if summary["any_negative_guarantee"]:
        st.warning(
            "**Some rungs show a negative guarantee retained.** This cell's expected gross "
            "margin is near or below zero — the RY2027 ADM shows yearling-finishing "
            "expected margins negative in most months in some states, with feeder cattle "
            "bid above fed cattle. A margin product written on a non-positive expected "
            "margin has degenerate protection metrics and is a different instrument from "
            "the one the realized loss ratios in section 2 describe. Treat these numbers "
            "with care."
        )

    # --------------------------------------------------------------- ladder
    st.markdown("#### Every filed rung")
    rows = ladder_rows(curve, unit)
    st.dataframe(
        rows, width='stretch', hide_index=True,
        column_config={
            "Deductible": st.column_config.NumberColumn(
                f"Deductible ($/{unit})", format="%.2f"),
            "Subsidy": st.column_config.NumberColumn(format="%.2f"),
            "Total premium": st.column_config.NumberColumn(format="$%,.0f"),
            "Producer premium": st.column_config.NumberColumn(format="$%,.0f"),
            "E[indemnity]": st.column_config.NumberColumn(format="$%,.0f"),
            "Net expected gain": st.column_config.NumberColumn(format="$%,.0f"),
            "Return per $1": st.column_config.NumberColumn(format="%.2f"),
            "Guarantee retained": st.column_config.NumberColumn(format="percent"),
            "± MC s.e.": st.column_config.NumberColumn(
                "± MC s.e.", format="$%,.0f",
                help="Monte Carlo standard error of the simulated mean loss, carried "
                     "through the 1.03 load. Not part of RMA's algorithm — it exists "
                     "because the published file has 500 draws, not the 5,000 the "
                     "instructions describe."),
        })
    # `format="percent"` is the preset that multiplies by 100 and appends the sign;
    # a printf "%.1f%%" would render the 0.934 fraction as "0.9%". The Subsidy column
    # keeps two decimals of the raw rate on purpose — 0.18 / 0.50 is how the ADM files
    # it, and matching the source makes the table checkable against A00070.
    st.info(FORWARD_LOOKING_NOTE)
    st.warning(BACKTEST_NOTE)

    # ------------------------------------------- 2. why the peak is interior
    st.markdown("#### Why the peak is interior")
    st.markdown(
        "Raising the deductible lifts the subsidy **rate** but shrinks the **premium base** "
        "the rate applies to. The rate stops rising at the 0.50 cap; the base keeps "
        "falling. Their product — what the producer actually nets — therefore peaks "
        "strictly inside the grid. It cannot be at the top, and it is at the bottom only if "
        "premium decays faster than the rate climbs over the first rungs. Both curves are "
        "below, on the same x-axis, so the trade is visible rather than asserted."
    )
    import pandas as pd

    frame = pd.DataFrame(curve_frame_rows(curve))
    k1, k2, k3 = st.columns(3)
    with k1:
        st.caption("**The rate** — rises, then caps")
        st.line_chart(frame, x="Deductible", y="Subsidy rate", height=230)
    with k2:
        st.caption("**The base** — total premium, falls throughout")
        st.line_chart(frame, x="Deductible", y="Total premium", height=230)
    with k3:
        st.caption("**Their product** — net expected gain, peaked")
        st.line_chart(frame, x="Deductible", y="Net expected gain", height=230)
    st.caption(
        f"Net expected gain = total premium × (1/{lgm.LOADING_FACTOR:g} − 1 + subsidy). "
        f"The 1/{lgm.LOADING_FACTOR:g} is RMA's Step 5 load, which the usual "
        "'premium × subsidy' shorthand drops — it is why break-even needs "
        f"{break_even:.4%} of subsidy rather than 0%."
    )

    # --------------------------------------------- the objectives disagree
    if not summary["pooled"]:
        st.caption(
            "The three-objective comparison is suppressed while the plan is unpooled. "
            "Return per producer dollar is `loss ratio / (1 − 0)` at every rung — below "
            "1.00 everywhere — and net expected gain is negative everywhere, so ranking "
            "the rungs against each other answers a question that no longer has a good "
            "answer. Add a second marketing month first."
        )
        st.info(SPREAD_NOTE)
        return

    st.markdown("#### Three objectives, three answers")
    pd_cell, prot = summary["per_dollar"], summary["protection"]
    st.dataframe(
        [
            {"Objective": "Maximise NET EXPECTED DOLLARS",
             "Deductible": g.deductible, "Subsidy": g.subsidy,
             "Net expected gain": g.net_expected_gain,
             "Return per $1": g.return_per_producer_dollar,
             "Guarantee retained": g.guarantee_retained,
             "What it is really asking": "How much money does this policy make me?"},
            {"Objective": "Maximise RETURN PER PRODUCER DOLLAR",
             "Deductible": pd_cell.deductible, "Subsidy": pd_cell.subsidy,
             "Net expected gain": pd_cell.net_expected_gain,
             "Return per $1": pd_cell.return_per_producer_dollar,
             "Guarantee retained": pd_cell.guarantee_retained,
             "What it is really asking": "How efficient is each dollar I put in?"},
            {"Objective": "Maximise PROTECTION",
             "Deductible": prot.deductible, "Subsidy": prot.subsidy,
             "Net expected gain": prot.net_expected_gain,
             "Return per $1": prot.return_per_producer_dollar,
             "Guarantee retained": prot.guarantee_retained,
             "What it is really asking": "How much of my margin is still insured?"},
        ],
        width='stretch', hide_index=True,
        column_config={
            "Deductible": st.column_config.NumberColumn(f"$/{unit}", format="%.2f"),
            "Subsidy": st.column_config.NumberColumn(format="%.2f"),
            "Net expected gain": st.column_config.NumberColumn(format="$%,.0f"),
            "Return per $1": st.column_config.NumberColumn(format="%.2f"),
            "Guarantee retained": st.column_config.NumberColumn(format="percent"),
        })

    plateau_msg = ""
    if len(summary["plateau"]) > 1:
        lo = summary["plateau"][0].deductible
        hi = summary["plateau"][-1].deductible
        fall = summary["plateau_gain_fall"]
        plateau_msg = (
            f"\n\n**And the middle row's metric goes blind exactly where the money is "
            f"lost.** Return per producer dollar is `1/(1 − subsidy)` at rated experience, "
            f"so once the ladder caps at {summary['plateau_subsidy']:.0%} it is pinned at "
            f"**{summary['plateau_return_per_dollar']:.2f} from ${lo:,.2f} all the way to "
            f"${hi:,.2f}** — it cannot tell those rungs apart at all"
            + (f", while net expected gain falls **{fall:.0%}** across that same plateau."
               if fall is not None else ".")
            + " Do not use it as the ranking metric inside the plateau."
        )
    st.warning(
        "**These are not the same question, and $0 is not the safe default.** A $0 "
        "deductible is maximum protection and near-worst value; the net-gain optimum gives "
        "up some guarantee to buy a much better subsidy rate. **A producer who cannot "
        "absorb the deductible in a bad year is rationally buying variance reduction and "
        "paying for it in expected value — that is a different objective, not an error, and "
        "the top row is not advice to them.**" + plateau_msg
    )
    st.info(SPREAD_NOTE)


# ---------------------------------------------------------------------------
# Section 2 — the head-to-heads
# ---------------------------------------------------------------------------

def _render_head_to_head(st) -> None:
    st.markdown("### 2. The head-to-heads — LGM-Dairy vs DRP, LGM-Cattle vs LRP")
    st.caption(
        f"Realized experience from RMA's Summary of Business (`sobtpu`), settled crop years "
        f"only (through {HEAD_TO_HEAD_LAST_SETTLED_YEAR}), national, on the same "
        f"`loss ratio / (1 − subsidy)` metric this repo uses everywhere else. Computed "
        f"{HEAD_TO_HEAD_ASOF}; see `docs/lgm.md` §3."
    )

    cfg = {
        "total_premium": st.column_config.NumberColumn("Total premium", format="$%,.0f"),
        "subsidy": st.column_config.NumberColumn("Subsidy", format="percent"),
        "loss_ratio": st.column_config.NumberColumn("Loss ratio", format="%.2f"),
        "per_dollar": st.column_config.NumberColumn("Indemnity per producer $",
                                                    format="%.2f"),
        "plan": st.column_config.TextColumn("Plan"),
    }
    a, b = st.columns(2)
    with a:
        st.markdown(f"**Subsidised era ({HEAD_TO_HEAD_FIRST_SUBSIDISED_YEAR}–"
                    f"{HEAD_TO_HEAD_LAST_SETTLED_YEAR})** — the regime a producer faces now")
        st.dataframe(list(HEAD_TO_HEAD_SUBSIDISED), width='stretch', hide_index=True,
                     column_config=cfg)
    with b:
        st.markdown(f"**All settled years (through {HEAD_TO_HEAD_LAST_SETTLED_YEAR})**")
        st.dataframe(list(HEAD_TO_HEAD_ALL_SETTLED), width='stretch', hide_index=True,
                     column_config=cfg)
    st.caption(
        "LGM-Cattle and LGM-Swine were effectively **unsubsidised before crop year 2021** — "
        "the Summary of Business reports 0% subsidy on their rows through 2019, while "
        "LGM-Dairy shows subsidy from 2011. The long window therefore blends two different "
        "products. Both are shown because they disagree."
    )

    d, c = st.columns(2)
    with d:
        st.markdown("#### 🥛 LGM-Dairy vs DRP")
        st.caption("Same milk, two subsidised products. The question is whether FEED COST "
                   "risk is worth insuring.")
        st.markdown(DAIRY_VS_DRP)
        st.info(CONCURRENT_NOTE)
    with c:
        st.markdown("#### 🐂 LGM-Cattle vs LRP")
        st.caption("Price-only against margin, on the same herd.")
        st.markdown(CATTLE_VS_LRP)
    st.warning(BLENDED_DEDUCTIBLE_CAVEAT)


# ---------------------------------------------------------------------------
# Section 3 — ration divergence
# ---------------------------------------------------------------------------

def _render_ration(st) -> None:
    st.markdown("### 3. The ration — LGM's basis risk, and who can escape it")
    st.caption(
        "LGM settles on a ration RMA declares, not on your feed bill. That is structurally "
        "the same county-index-vs-my-farm problem `src/basisrisk.py` handles for SCO/ECO — "
        "but the three commodities are **not** equally exposed."
    )

    rows = []
    for (cc, tc), r in sorted(lgm.DECLARED_RATION.items()):
        band = lgm.RATION_BANDS.get((cc, tc), {})
        rows.append({
            "Commodity": commodity_label(cc),
            "Type": type_label(cc, tc),
            "Corn (bu/unit)": r.corn_bu,
            "Soybean meal (t/unit)": r.soybean_meal_ton,
            "In (cwt)": r.feeder_cwt,
            "Out (cwt)": r.output_cwt,
            "Election": ("electable — " + ", ".join(
                f"{k} {lo:g}–{hi:g}" for k, (lo, hi) in band.items())
                if r.electable else "FIXED — no election exists"),
        })
    st.dataframe(rows, width='stretch', hide_index=True)
    st.success(RATION_ELIMINABLE_NOTE)

    st.markdown("#### Measure your own divergence")
    st.caption(
        "Uses the commodity, type, state and marketing plan you set in section 1. Prices "
        "and price draws come from RMA's own published component paths where the ADM has "
        "them, averaged over your marketing plan — so the risk numbers are measured under "
        "exactly the price scenarios RMA priced the policy with, not under a distribution "
        "invented here."
    )

    cc = st.session_state.get("lgm_commodity", COMMODITY_ORDER[0])
    types = [t for (c, t) in sorted(lgm.DECLARED_RATION) if c == cc]
    tc = st.session_state.get("lgm_type", types[0])
    if (cc, tc) not in lgm.DECLARED_RATION:
        tc = types[0]
    insured = lgm.ration_for(cc, tc)
    st.markdown(f"**{commodity_label(cc)} / {type_label(cc, tc)}** — RMA's declared ration "
                f"is the starting value of every box below.")

    legs = [f for f in ("corn_bu", "soybean_meal_ton", "feeder_cwt", "output_cwt")
            if getattr(insured, f) is not None]
    band = lgm.RATION_BANDS.get((cc, tc), {})
    cols = st.columns(len(legs))
    values: dict[str, float] = {}
    for col, field in zip(cols, legs):
        base = float(getattr(insured, field))
        lo_hi = band.get(field)
        helptext = (f"RMA's election band: {lo_hi[0]:.5g} – {lo_hi[1]:.5g}"
                    if lo_hi else "No election band — this leg is fixed.")
        with col:
            values[field] = st.number_input(
                LEG_LABELS[field], value=base,
                step=max(abs(base) / 20.0, 1e-5), format="%.5f",
                key=f"lgm_ration_{cc}_{tc}_{field}", help=helptext)

    actual = ration_from_inputs(cc, tc, values)

    # Rebuild the same case + marketing plan section 1 used, so the two sections agree.
    case = None
    prices = draws = None
    zips = cached_adm_zips()
    zname = st.session_state.get("lgm_zip")
    sc = st.session_state.get(f"lgm_state_{cc}_{tc}")
    if zips and zname and sc:
        path = next((p for p in zips if p.name == zname), None)
        if path is not None:
            case = _streamlit_helpers()["case"](str(path), _mtime(path), cc, tc, sc)
    if case is not None:
        n_months = len(case.months)
        k = int(st.session_state.get(f"lgm_months_{cc}", n_months))
        size = float(st.session_state.get(f"lgm_size_{cc}", DEFAULT_SIZE[cc]))
        got = marketing_weighted_prices(case, marketing_plan(n_months, k, size))
        if got:
            prices, draws = got

    try:
        div = lgm.ration_divergence(cc, tc, actual, prices=prices, price_draws=draws)
    except Exception as exc:
        st.error(f"Could not measure the divergence: {type(exc).__name__}: {exc}")
        return

    verdict = div.verdict
    (st.success if "on the declared" in verdict
     else st.info if div.eliminable else st.warning)(f"**{verdict}**")

    # The section opens on the declared ration, which makes every output an identity: gap
    # 0.000, correlation 1.0000, untracked variance 0.00%. That is right, and it looks exactly
    # like a calculator that failed to run. Say which one it is before the reader guesses.
    if all(abs(d) < 1e-9 for d in div.deltas.values()):
        st.caption(RATION_IDENTITY_NOTE)

    delta_rows = []
    for leg, delta in div.deltas.items():
        in_band = div.within_band.get(leg)
        delta_rows.append({
            "Leg": LEG_LABELS.get(leg, leg),
            "RMA declares": getattr(insured, leg),
            "You feed": getattr(actual, leg),
            "Delta": delta,
            "In RMA's band?": ("—" if in_band is None
                               else "yes" if in_band else "OUTSIDE BAND"),
        })
    if "gain_cwt" in div.within_band:
        ok = div.within_band["gain_cwt"]
        delta_rows.append({
            "Leg": "Gain (out − in), cwt",
            "RMA declares": (insured.output_cwt or 0) - (insured.feeder_cwt or 0),
            "You feed": (actual.output_cwt or 0) - (actual.feeder_cwt or 0),
            "Delta": ((actual.output_cwt or 0) - (actual.feeder_cwt or 0)
                      - ((insured.output_cwt or 0) - (insured.feeder_cwt or 0))),
            "In RMA's band?": "yes" if ok else "EXCEEDS THE FILED MAXIMUM",
        })
    st.dataframe(delta_rows, width='stretch', hide_index=True)

    if prices is None:
        if cc == "0815":
            st.info(SWINE_NO_RISK_LAYER)
        else:
            st.info(
                "Only the **physical** layer is available: the level and risk layers need "
                "RMA's component price paths, which come from an LGM ADM zip in "
                "`data/cache/lgm/` and a state selected in section 1."
            )
        return

    unit = lgm.COMMODITY_UNIT[cc]
    lv1, lv2, lv3 = st.columns(3)
    lv1.metric(f"Expected margin, insured ($/{unit})",
               f"{div.expected_margin_insured:,.3f}")
    lv2.metric(f"Expected margin, yours ($/{unit})",
               f"{div.expected_margin_actual:,.3f}")
    lv3.metric("LEVEL gap", f"{div.expected_margin_gap:+,.3f}",
               help="Offsettable — move the deductible. This is NOT basis risk.")

    if div.tracking_corr is None:
        st.info("The risk layer needs at least two usable draws for every leg.")
        return
    r1, r2, r3 = st.columns(3)
    r1.metric(f"Residual sd ($/{unit})", f"{div.residual_sd:,.3f}",
              help="sd(your margin − insured margin) across RMA's own published draws.")
    r2.metric("Tracking correlation", f"{div.tracking_corr:.4f}")
    r3.metric("Variance NOT tracked", f"{div.unexplained_variance_share:.2%}",
              help="1 − corr². The LGM analogue of basisrisk.py's miss rate.")
    st.caption(
        f"Measured across {len(next(iter(draws.values())))} of RMA's published margin "
        "draws, with each leg's price averaged over your marketing plan — one observation "
        "per draw."
    )
    st.info(RATION_LEVEL_VS_RISK)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


LGM_COMMISSION_NOTE = (
    "**Commission is a percent of TOTAL premium, not of what the producer pays.** LGM's "
    "ladder already carries the total, so no grossing-up is needed here — but it is why the "
    "agency's best rung and the producer's best rung are not the same rung. Total premium "
    "RISES as the deductible falls, so agency revenue is maximised at the LOWEST deductible, "
    "while the producer's net expected gain peaks somewhere in the middle of the ladder. "
    "That divergence is the point of showing this separately rather than as another column."
)


def _agency_table(st, curve, unit: str) -> None:
    """What the agency earns across the rungs the producer is reading.

    LGM had no agency figure at all, so this is a new metric rather than a re-sort. Commission
    is a percent of TOTAL premium and LGM's ladder already carries the total, so unlike DRP
    there is no grossing-up step — but that is also exactly why the two lenses point at
    different rungs: total premium RISES as the deductible falls, so agency revenue is
    maximised at the LOWEST rung while the producer's net expected gain peaks mid-ladder.
    """
    import pandas as pd

    st.subheader("Sell — what the agency earns on this ladder")
    comm = load_aip_commission(product="LGM")
    rated = [a for a in comm["aips"] if a["by_region"] or a["pct"] is not None]
    if not rated:
        st.warning(
            "No LGM commission rate on file. LGM is reinsured under the LPRA, whose A&O is "
            "22.2% of net book premium (LPRA IV(b)(2)(D)) and which contains no agent "
            "compensation cap. Enter your negotiated schedule in "
            "`data/seed/aip_commission.csv` under product=LGM.")
        return

    def _rate(a):
        vals = [v for v in (a["by_region"] or {}).values() if v is not None]
        return (sum(vals) / len(vals)) if vals else a["pct"]

    rates = [r for r in (_rate(a) for a in rated) if r is not None]
    pct = sum(rates) / len(rates)
    st.caption(
        f"At **{pct:.2f}%** of total premium — the LPRA ceiling (22.2% A&O, no compensation "
        f"cap in that agreement). Read it as *at most*: a negotiated rate normally sits below "
        f"the ceiling.")

    rows = [{
        "Deductible": c.deductible,
        "Total premium": c.total_premium,
        "Producer premium": c.producer_premium,
        "Agency commission": c.total_premium * pct / 100.0,
        "Producer net expected gain": c.net_expected_gain,
    } for c in curve]
    if not rows:
        st.info("The ladder produced no priced rungs for this selection.")
        return

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
        "Deductible": st.column_config.NumberColumn(format="$%,.0f"),
        "Total premium": st.column_config.NumberColumn(format="$%,.0f"),
        "Producer premium": st.column_config.NumberColumn(format="$%,.0f"),
        "Agency commission": st.column_config.NumberColumn(format="$%,.2f"),
        "Producer net expected gain": st.column_config.NumberColumn(format="$%,.0f"),
    })

    best_a = max(rows, key=lambda r: r["Agency commission"])
    best_p = max(rows, key=lambda r: r["Producer net expected gain"])
    if best_a["Deductible"] != best_p["Deductible"]:
        st.warning(
            f"**These point at different rungs.** Agency revenue peaks at the "
            f"${best_a['Deductible']:,.0f} deductible (${best_a['Agency commission']:,.2f}); "
            f"the producer's net expected gain peaks at ${best_p['Deductible']:,.0f} "
            f"(${best_p['Producer net expected gain']:,.0f}). Recommending the first while "
            f"quoting the second is the conflict this lens exists to make visible.")
    else:
        st.success(
            f"Both peak at the ${best_a['Deductible']:,.0f} deductible — no conflict on this "
            f"selection.")


def render() -> None:
    """Draw the LGM tab. streamlit_app.py calls this as `lgmpage.render()`.

    Every section is individually guarded: a failure in the head-to-heads must not take the
    ladder down with it, and none of the three may take the rest of the app down.
    """
    import streamlit as st

    st.markdown(ONE_SENTENCE)
    st.caption(
        "Plan code 82 — the MARGIN leg, completing the livestock trio alongside LRP "
        "(plan 81, price only) and DRP (plan 83, revenue). LGM insures revenue minus a "
        "declared feed cost."
    )

    # WHOSE MONEY. Same split as the other four products. LGM's three existing sections are
    # all producer-side; the agency section is new, and reads the SAME ladder rather than
    # recomputing one, so the two lenses cannot disagree about the policy being priced.
    lens = st.radio("Lens", ["Buy — producer", "Sell — agency"],
                    horizontal=True, key="lgm_lens", label_visibility="collapsed")

    buy = lens.startswith("Buy")
    sections = ([("deductible ladder", _render_ladder),
                 ("head-to-heads", _render_head_to_head),
                 ("ration section", _render_ration)] if buy else
                [("agency view", lambda st_: _render_ladder(st_, lens="sell"))])

    for name, fn in sections:
        st.divider()
        try:
            fn(st)
        except Exception as exc:                            # pragma: no cover - guard
            st.error(f"The {name} could not be rendered — "
                     f"{type(exc).__name__}: {exc}")
