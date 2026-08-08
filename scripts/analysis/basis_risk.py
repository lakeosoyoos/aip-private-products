#!/usr/bin/env python3
"""
basis_risk.py -- quantify how often an AREA-triggered endorsement fails to pay a
producer who had a genuine loss, and how much of the in-band loss it leaves uncovered.

Three pieces of evidence, kept separate because they have different standing:

PART A -- MEASURED, from the loaded ADM.
  RMA prices individual risk by irrigation practice inside the SAME county. The gap
  between the irrigated and non-irrigated Reference Rate in a county is RMA's own
  published statement that those two operations do not share a loss distribution.
  A county index blends them. That gap is a direct measure of the within-county
  heterogeneity that creates basis risk.
  Source: data/cache/adm/2026_A01010_BaseRate_YTD.txt, plan 02 (Revenue Protection),
  Reference Rate by Irrigation Practice Code. Codes per ADM A00490 IrrigationPractice:
  002 = Irrigated, 003 = Non-Irrigated, 997 = no practice specified. (Note the order --
  002 is IRRIGATED, which is the reverse of the intuitive reading.)

  The Reference Rate is the rate at that practice's own reference yield: RMA's continuous
  rating formula is base rate = reference rate x (reference amount / approved yield)^exponent
  + fixed rate, so at approved yield = reference amount the rate collapses to the reference
  rate (plus the fixed rate). Comparing reference rates across practices is therefore a
  like-for-like comparison of a typical irrigated farm against a typical non-irrigated farm
  in the same county. Counties where RMA publishes the SAME reference rate for both
  practices are reported separately, since they carry no information about the gap.

PART B -- MEASURED, from the loaded SoB + ADM.
  Decompose the expected payment of a revenue band into the part driven by PRICE
  (common to every producer in the country -- zero basis risk) and the part driven
  by county YIELD (the only part that can miss an individual). This reframes the
  whole basis-risk question for revenue-band products.

PART C -- MODEL. A transparent Monte Carlo.
  Factor model: farm yield y_f and county yield y_c share a systemic factor, with
  sigma_county = rho * sigma_farm (so the county is always the LESS variable of the
  two, as aggregation requires). Left-skewed Beta marginals. Harvest/projected price
  ratio lognormal at the volatility factor RMA published in the 2026 ADM. sigma_farm
  is calibrated so the model reproduces the ECO-RP premium rate measured in this
  repo's SoB table. rho is then swept, because rho is the thing a producer's own
  situation moves.

Usage: .venv/bin/python scripts/analysis/basis_risk.py [--draws 400000] [--seed 7]
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import statistics
from collections import defaultdict

import numpy as np
from scipy.stats import norm, beta as beta_dist

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(ROOT, "data", "catalog.db")
ADM = os.path.join(ROOT, "data", "cache", "adm")

CROPS = {"0041": "Corn", "0081": "Soybeans", "0011": "Wheat", "0021": "Cotton",
         "0047": "Grain Sorghum", "0067": "Rice"}
YMAX = 1.7          # assumed maximum attainable yield ratio for the Beta marginals


# =============================================================== PART A (MEASURED)
def irrigation_rate_gap():
    path = [os.path.join(ADM, f) for f in sorted(os.listdir(ADM))
            if "A01010_BaseRate" in f][-1]
    with open(path, encoding="utf-8", errors="replace") as fh:
        hdr = fh.readline().rstrip("\r\n").split("|")
    ix = {n: i for i, n in enumerate(hdr)}
    i_plan, i_comm, i_st, i_cty = (ix["Insurance Plan Code"], ix["Commodity Code"],
                                   ix["State Code"], ix["County Code"])
    i_irr, i_ref, i_del = (ix["Irrigation Practice Code"], ix["Reference Rate"],
                           ix["Deleted Date"])
    buckets = defaultdict(list)
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.readline()
        for line in fh:
            r = line.rstrip("\r\n").split("|")
            if len(r) <= i_del or r[i_del].strip():
                continue
            if r[i_plan] != "02" or r[i_comm] not in CROPS:
                continue
            if r[i_irr] not in ("002", "003") or not r[i_ref].strip():
                continue
            try:
                buckets[(r[i_comm], r[i_st], r[i_cty], r[i_irr])].append(float(r[i_ref]))
            except ValueError:
                pass
    out = defaultdict(list)
    for comm, st, cty in {k[:3] for k in buckets}:
        irr = buckets.get((comm, st, cty, "002"))       # 002 = IRRIGATED
        non = buckets.get((comm, st, cty, "003"))       # 003 = NON-IRRIGATED
        if irr and non:
            out[comm].append(((st, cty), statistics.median(irr), statistics.median(non)))
    return out


def part_a():
    print("=" * 102)
    print("PART A (MEASURED, 2026 ADM A01010). Within-county NON-IRRIGATED vs IRRIGATED")
    print("individual Reference Rate, Revenue Protection. These are counties where RMA")
    print("publishes both practices -- i.e. counties whose ONE area index necessarily")
    print("blends two operations RMA itself prices as different risks.")
    print("(ADM A00490: irrigation practice code 002 = Irrigated, 003 = Non-Irrigated.)")
    print("=" * 102)
    gap = irrigation_rate_gap()
    print(f"  {'crop':<15} {'counties':>9} {'same rate':>10} {'med irr':>9} "
          f"{'med non-irr':>12} | where the two DIFFER: non-irr / irr")
    print(f"  {'':<15} {'w/ both':>9} {'both prac':>10} {'rate':>9} {'rate':>12} "
          f"| {'p10':>7} {'median':>8} {'p90':>7}")
    for comm, rows in sorted(gap.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 20:
            continue
        irr = [r[1] for r in rows]
        non = [r[2] for r in rows]
        # ratio expressed the intuitive way: how many times the irrigated rate is the
        # non-irrigated rate.
        ratios = [r[2] / r[1] for r in rows if r[1] > 0]
        same = sum(1 for x in ratios if abs(x - 1.0) < 1e-9)
        diff = sorted(x for x in ratios if abs(x - 1.0) >= 1e-9)
        m = len(diff)
        if not m:
            continue
        print(f"  {CROPS[comm]:<15} {len(rows):>9,} {same/len(ratios):>9.0%} "
              f"{statistics.median(irr):>9.4f} {statistics.median(non):>12.4f} "
              f"| {diff[int(.1*(m-1))]:>6.2f}x {diff[m//2]:>7.2f}x "
              f"{diff[int(.9*(m-1))]:>6.2f}x")
    print("\n  Read: a median of 2.8x means RMA charges the NON-IRRIGATED operation about")
    print("  2.8 times the pure rate it charges the IRRIGATED one in the same county --")
    print("  RMA's own published statement that they are not the same risk. One county")
    print("  index triggers, or fails to, for both of them alike. Counties where RMA")
    print("  publishes an identical reference rate for both practices are excluded from")
    print("  the ratio columns: they carry no information about the gap.")


# =============================================================== PART B (MEASURED)
def part_b(rng, draws, eco_rate, band, vol, rho_yp, sigma_f, rho):
    lo, hi = band
    print("\n" + "=" * 102)
    print("PART B. PRICE vs YIELD decomposition of the ECO-RP band payment.")
    print("Price is national. Every insured acre in the country sees the SAME harvest")
    print("price. Whatever share of the expected payment is price-driven carries NO")
    print("basis risk at all. Only the yield share can miss an individual producer.")
    print("=" * 102)
    scenarios = [
        ("full model (price + county yield)", vol, sigma_f),
        ("price frozen at projected (yield only)", 0.0, sigma_f),
        ("county yield frozen at trend (price only)", vol, 1e-6),
    ]
    base = None
    for label, v, sf in scenarios:
        y_f, y_c, p = draw(rng, draws, sf, rho, v, rho_yp)
        m = band_metrics(y_f, y_c, p, 0.85, lo, hi)
        if base is None:
            base = m["loss_cost_per_dollar_band"]
        print(f"  {label:<42} E[pay]/$1 band = "
              f"{m['loss_cost_per_dollar_band']:.4f}   "
              f"P(pays) = {m['p_area_pays']:.1%}")
    y_f, y_c, p = draw(rng, draws, sigma_f, rho, 0.0, rho_yp)
    yield_only = band_metrics(y_f, y_c, p, 0.85, lo, hi)["loss_cost_per_dollar_band"]
    y_f, y_c, p = draw(rng, draws, 1e-6, rho, vol, rho_yp)
    price_only = band_metrics(y_f, y_c, p, 0.85, lo, hi)["loss_cost_per_dollar_band"]
    print(f"\n  price-only share of the full expected payment : "
          f"{price_only/base:>6.1%}   <- zero basis risk")
    print(f"  yield-only share of the full expected payment : "
          f"{yield_only/base:>6.1%}   <- all the basis risk lives here")
    print("  (the two shares need not sum to 100%: the interaction term is the balance)")
    print("\n  Same decomposition, YIELD-triggered variants (ECO-YP / SCO-YP) for contrast:")
    y_f, y_c, p = draw(rng, draws, sigma_f, rho, 0.0, 0.0)
    myp = band_metrics(y_f, y_c, p, 0.85, lo, hi)
    print(f"    ECO-YP style band, no price leg: E[pay]/$1 band = "
          f"{myp['loss_cost_per_dollar_band']:.4f}, "
          f"P(pays) = {myp['p_area_pays']:.1%}")
    print(f"    MEASURED for comparison: ECO-YP premium rate from sob_sales = "
          f"{ECO_YP_RATE:.4f}, ECO-RP = {eco_rate:.4f}")
    print("    The yield-triggered variant is far cheaper because the price leg -- the")
    print("    part with no basis risk -- is exactly what it drops. A producer buying")
    print("    ECO-YP/SCO-YP is buying almost pure basis risk.")


# =============================================================== PART C (MODEL)
def beta_params(cv, ymax=YMAX):
    m = 1.0 / ymax
    s = cv / ymax
    k = m * (1 - m) / (s * s) - 1
    if k <= 0:
        raise ValueError(f"CV {cv} too large for ymax {ymax}")
    return m * k, (1 - m) * k


def draw(rng, n, sigma_f, rho, vol, rho_yp):
    """
    Factor model. sigma_county = rho * sigma_farm, which is what a linear factor
    structure y_f = y_c + idiosyncratic implies and guarantees the county is the
    less variable series. Gaussian copula, left-skewed Beta marginals.
    """
    sigma_c = max(1e-6, rho * sigma_f)
    cov = np.array([[1.0, rho, rho_yp * rho],
                    [rho, 1.0, rho_yp],
                    [rho_yp * rho, rho_yp, 1.0]])
    w, V = np.linalg.eigh(cov)
    cov = V @ np.diag(np.clip(w, 1e-9, None)) @ V.T
    L = np.linalg.cholesky(cov)
    z = rng.standard_normal((n, 3)) @ L.T
    u = norm.cdf(z[:, :2])
    if sigma_f > 1e-5:
        af, bf = beta_params(sigma_f)
        y_f = beta_dist.ppf(u[:, 0], af, bf) * YMAX
    else:
        y_f = np.ones(n)
    if sigma_c > 1e-5:
        ac, bc = beta_params(sigma_c)
        y_c = beta_dist.ppf(u[:, 1], ac, bc) * YMAX
    else:
        y_c = np.ones(n)
    if vol > 1e-9:
        sig = math.sqrt(math.log(1 + vol ** 2))
        p = np.exp(sig * z[:, 2] - 0.5 * sig ** 2)
    else:
        p = np.ones(n)
    return y_f, y_c, p


def band_metrics(y_f, y_c, p, cl_u, band_lo, band_hi, harvest_price=True):
    adj = np.maximum(1.0, p) if harvest_price else np.ones_like(p)
    r_f = (y_f * p) / adj
    r_c = (y_c * p) / adj
    width = band_hi - band_lo
    farm_band_loss = np.clip(band_hi - r_f, 0.0, width)
    area_pay = np.clip(band_hi - r_c, 0.0, width)
    shortfall = farm_band_loss - area_pay
    has_farm_loss = farm_band_loss > 1e-9
    pays = area_pay > 1e-9
    deep = r_f < (cl_u - 0.10)
    return dict(
        loss_cost_per_dollar_band=float(area_pay.mean() / width),
        p_farm_band_loss=float(has_farm_loss.mean()),
        p_area_pays=float(pays.mean()),
        p_hard_miss=float((has_farm_loss & ~pays).mean()),
        p_miss_given_farm_loss=float((has_farm_loss & ~pays).sum() /
                                     max(1, has_farm_loss.sum())),
        p_zero_pay_given_deep_farm_loss=float((deep & ~pays).sum() / max(1, deep.sum())),
        p_deep=float(deep.mean()),
        uncovered_share=float(np.clip(shortfall, 0, None).mean() /
                              max(1e-12, farm_band_loss.mean())),
        windfall_share=float(np.clip(-shortfall, 0, None).mean() /
                             max(1e-12, area_pay.mean())),
    )


def calibrate_sigma_f(rng, target, n, rho, vol, rho_yp, band):
    lo, hi = 0.05, 0.55
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        y_f, y_c, p = draw(rng, n, mid, rho, vol, rho_yp)
        got = band_metrics(y_f, y_c, p, 0.85, band[0], band[1])["loss_cost_per_dollar_band"]
        if got < target:
            lo = mid
        else:
            hi = mid
    y_f, y_c, p = draw(rng, n, 0.5 * (lo + hi), rho, vol, rho_yp)
    got = band_metrics(y_f, y_c, p, 0.85, band[0], band[1])["loss_cost_per_dollar_band"]
    return 0.5 * (lo + hi), got


ECO_YP_RATE = 0.0


def main():
    global ECO_YP_RATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=300_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--eco-band", default="0.86,0.95")
    ap.add_argument("--vol", type=float, default=0.15,
                    help="harvest price volatility; 2026 ADM corn range is 0.13-0.16")
    ap.add_argument("--rho-yp", type=float, default=-0.25)
    ap.add_argument("--sigma-f-lit", type=float, default=0.25,
                    help="farm-level yield CV for the 'realistic' scenario; Corn Belt "
                         "farm corn yield CV is commonly put at 0.20-0.30")
    args = ap.parse_args()

    part_a()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    def rate(plan):
        l, p = conn.execute("""select sum(liability), sum(total_premium) from sob_sales
                               where year=(select max(year) from sob_sales)
                                 and plan_code=?""", (plan,)).fetchone()
        return p / l

    eco_rate, sco_rate = rate("88"), rate("32")
    ECO_YP_RATE = rate("87")
    band = tuple(float(x) for x in args.eco_band.split(","))

    print("\n" + "=" * 102)
    print("PART C (MODEL). Assumptions, all stated up front:")
    print(f"  ECO-RP band                : {band[0]:.2f} -> {band[1]:.2f} "
          f"({(band[1]-band[0])*100:.0f} coverage points)")
    print(f"  ECO-RP premium rate ANCHOR : {eco_rate:.4f}   MEASURED "
          "(sob_sales plan 88: total_premium / liability)")
    print(f"  SCO-RP premium rate        : {sco_rate:.4f}   MEASURED (plan 32)")
    print(f"  ECO-YP premium rate        : {ECO_YP_RATE:.4f}   MEASURED (plan 87)")
    print(f"  price volatility factor    : {args.vol:.2f}     MEASURED range from ADM "
          "A00810 (corn 0.13-0.16)")
    print(f"  county yield / price corr  : {args.rho_yp:+.2f}    ASSUMED")
    print(f"  yield marginals            : Beta on [0,{YMAX}], mean 1   ASSUMED shape")
    print(f"  sigma_county               : rho * sigma_farm   ASSUMED factor structure")
    print(f"  draws                      : {args.draws:,}")
    print("=" * 102)

    rng = np.random.default_rng(args.seed)
    rho_cal = 0.85
    sigma_f, achieved = calibrate_sigma_f(rng, eco_rate, min(args.draws, 150_000),
                                          rho_cal, args.vol, args.rho_yp, band)
    print(f"\n  CALIBRATION at rho={rho_cal}: farm yield CV = {sigma_f:.3f} "
          f"(=> county yield CV {rho_cal*sigma_f:.3f}) reproduces an ECO-RP band loss")
    print(f"  cost of {achieved:.4f} against the measured premium rate {eco_rate:.4f}.")
    if abs(achieved - eco_rate) / eco_rate > 0.03:
        print(f"  *** CALIBRATION DID NOT CONVERGE to the measured rate. Gap = "
              f"{(eco_rate-achieved)/eco_rate:+.1%}. The measured premium therefore")
        print("  *** exceeds what a fair model of the band produces at any plausible")
        print("  *** yield CV -- i.e. the observed rate carries a load and/or reflects")
        print("  *** adverse selection into higher-risk counties. Report this, do not")
        print("  *** hide it. The basis-risk RATIOS below are still informative because")
        print("  *** they depend on rho far more than on the absolute rate level.")

    # Two scenarios, run side by side, because the calibrated CV is implausibly high
    # and an inflated yield CV mechanically inflates every basis-risk statistic.
    scenarios = [
        ("LIT", args.sigma_f_lit,
         "farm yield CV set to a realistic Corn Belt value; the model then UNDER-prices "
         "the band relative to the market"),
        ("CAL", sigma_f,
         "farm yield CV forced up until the model reproduces the measured ECO-RP rate; "
         "over-weights the yield leg, so its basis-risk figures are an UPPER BOUND"),
    ]
    for tag, sf, note in scenarios:
        y_f, y_c, p = draw(rng, min(args.draws, 150_000), sf, rho_cal, args.vol,
                           args.rho_yp)
        lc = band_metrics(y_f, y_c, p, 0.85, band[0], band[1])["loss_cost_per_dollar_band"]
        print(f"\n  scenario {tag}: farm CV {sf:.3f} -> county CV {rho_cal*sf:.3f}; "
              f"model band loss cost {lc:.4f} vs measured {eco_rate:.4f} "
              f"({(lc-eco_rate)/eco_rate:+.0%})")
        print(f"    {note}")

    part_b(rng, args.draws, eco_rate, band, args.vol, args.rho_yp,
           args.sigma_f_lit, rho_cal)

    for tag, sf, _note in scenarios:
        print("\n" + "=" * 102)
        print(f"C1[{tag}]. ECO-RP band ({band[0]:.2f}->{band[1]:.2f}), farm yield CV "
              f"{sf:.3f}. Does the county index pay the producer who lost?")
        print("=" * 102)
        print(f"  {'rho':>5} {'P(farm has':>11} {'P(ECO':>7} "
              f"{'P(ECO=0 &':>10} {'P(ECO=0 |':>11} {'P(ECO=0 |':>11} "
              f"{'uncovrd':>8} {'windfall':>9}")
        print(f"  {'':>5} {'band loss)':>11} {'pays)':>7} {'farm lost)':>10} "
              f"{'farm lost)':>11} {'deep loss)':>11} {'share':>8} {'share':>9}")
        for rho in (0.95, 0.90, 0.85, 0.80, 0.70, 0.60, 0.50, 0.40):
            y_f, y_c, p = draw(rng, args.draws, sf, rho, args.vol, args.rho_yp)
            m = band_metrics(y_f, y_c, p, 0.85, band[0], band[1])
            print(f"  {rho:>5.2f} {m['p_farm_band_loss']:>11.1%} "
                  f"{m['p_area_pays']:>7.1%} {m['p_hard_miss']:>10.1%} "
                  f"{m['p_miss_given_farm_loss']:>11.1%} "
                  f"{m['p_zero_pay_given_deep_farm_loss']:>11.1%} "
                  f"{m['uncovered_share']:>8.1%} {m['windfall_share']:>9.1%}")

    print("\n" + "=" * 102)
    print(f"C2. SCO-RP band (underlying coverage level -> {band[0]:.2f}), farm yield CV "
          f"{args.sigma_f_lit:.3f}. Narrower and lower in the distribution.")
    print("=" * 102)
    print(f"  {'CL_u':>5} {'rho':>5} {'band':>6} {'P(SCO pays)':>12} "
          f"{'P(SCO=0 | farm lost)':>21} {'P(SCO=0 | deep loss)':>21} {'uncovrd':>8}")
    for cl_u in (0.85, 0.80, 0.75, 0.70):
        for rho in (0.90, 0.80, 0.70, 0.60):
            y_f, y_c, p = draw(rng, args.draws, args.sigma_f_lit, rho, args.vol,
                               args.rho_yp)
            m = band_metrics(y_f, y_c, p, cl_u, cl_u, band[0])
            print(f"  {cl_u:>5.2f} {rho:>5.2f} {(band[0]-cl_u)*100:>5.0f}p "
                  f"{m['p_area_pays']:>12.1%} {m['p_miss_given_farm_loss']:>21.1%} "
                  f"{m['p_zero_pay_given_deep_farm_loss']:>21.1%} "
                  f"{m['uncovered_share']:>8.1%}")

    print("\n" + "=" * 102)
    print("C3. Expected return per producer dollar, and the honest version of it.")
    print(f"    (farm yield CV {args.sigma_f_lit:.3f}; rates rescaled to the MEASURED")
    print(f"     ECO-RP premium rate {eco_rate:.4f} so the dollar figures are real)")
    print("=" * 102)
    subsidy = 0.80
    print(f"  {'rho':>5} {'E[pay]/$1 liab':>15} {'producer $/$1':>14} "
          f"{'gross return':>13} {'risk-transfer return':>21}")
    for rho in (0.95, 0.90, 0.80, 0.70, 0.60, 0.50):
        y_f, y_c, p = draw(rng, args.draws, args.sigma_f_lit, rho, args.vol, args.rho_yp)
        m = band_metrics(y_f, y_c, p, 0.85, band[0], band[1])
        lc = eco_rate                      # measured; the model supplies only the shares
        prod = lc * (1 - subsidy)
        useful = lc * (1 - m["windfall_share"])
        print(f"  {rho:>5.2f} {lc:>15.4f} {prod:>14.4f} {lc/prod:>12.2f}x "
              f"{useful/prod:>20.2f}x")
    print("\n  'gross return' = 1/(1-subsidy) = 5.00x. That is an ARITHMETIC IDENTITY at")
    print("  any actuarially fair rate, identical for every 80%-subsidised endorsement,")
    print("  and it is the number the sales pitch quotes. 'risk-transfer return' strips")
    print("  out the dollars that arrived in years the farm had no in-band loss. Those")
    print("  dollars are real income -- but they are a transfer, not insurance, and they")
    print("  are exactly offset by the years the loss came and the cheque did not.")


if __name__ == "__main__":
    main()
