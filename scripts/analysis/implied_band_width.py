#!/usr/bin/env python3
"""
implied_band_width.py -- infer, from loaded data only, HOW WIDE the insured band
actually is for each area endorsement.

The band is the whole argument. An area endorsement's liability per acre is

    liability/acre  =  band width (in coverage points)  x  expected county revenue/acre
                       x  any protection/payment factor

So if we take the SoB's liability-per-acre and divide by the ADM's Expected Revenue
Amount for the same state x county x commodity x plan, the quotient IS the band width
(times the protection factor). That gives us the band without reading a fact sheet,
and it lets us check any claimed band against what producers were actually charged for.

Sources:
  data/catalog.db  sob_sales                         liability, net_acres
  data/cache/adm/2026_A00810_Price_YTD.txt           Expected Revenue Amount,
                                                     Expected Margin Amount
                                                     keyed by state/county/plan/commodity

Usage: .venv/bin/python scripts/analysis/implied_band_width.py
"""
from __future__ import annotations

import os
import sqlite3
import statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(ROOT, "data", "catalog.db")
ADM = os.path.join(ROOT, "data", "cache", "adm")

AREA_PLANS = {
    "31": "SCO-YP", "32": "SCO-RP", "33": "SCO-RPHPE",
    "35": "STAX-RP", "36": "STAX-RPHPE",
    "67": "MCO-YP", "68": "MCO-RP", "69": "MCO-RPHPE",
    "87": "ECO-YP", "88": "ECO-RP", "89": "ECO-RPHPE",
}


def adm_expected_value():
    """
    (plan, state_code, county_code, commodity_code) ->
        (median Expected Revenue Amount, median Expected Margin Amount, n)
    Averaged over type/practice/irrigation, which is the same aggregation the SoB
    county roll-up performs, so the comparison is like-for-like at county grain.
    """
    path = [os.path.join(ADM, f) for f in sorted(os.listdir(ADM))
            if "A00810_Price" in f][-1]
    with open(path, encoding="utf-8", errors="replace") as fh:
        hdr = fh.readline().rstrip("\r\n").split("|")
    ix = {n: i for i, n in enumerate(hdr)}
    i_plan, i_st, i_cty = ix["Insurance Plan Code"], ix["State Code"], ix["County Code"]
    i_comm, i_del = ix["Commodity Code"], ix["Deleted Date"]
    i_rev, i_marg = ix["Expected Revenue Amount"], ix["Expected Margin Amount"]
    i_cl = ix["Coverage Level Percent"]
    rev = defaultdict(list)
    marg = defaultdict(list)
    cls = defaultdict(set)
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.readline()
        for line in fh:
            r = line.rstrip("\r\n").split("|")
            if len(r) <= i_del or r[i_del].strip():
                continue
            plan = r[i_plan]
            if plan not in AREA_PLANS:
                continue
            k = (plan, r[i_st], r[i_cty], r[i_comm])
            if r[i_rev].strip():
                try:
                    rev[k].append(float(r[i_rev]))
                except ValueError:
                    pass
            if r[i_marg].strip():
                try:
                    marg[k].append(float(r[i_marg]))
                except ValueError:
                    pass
            if r[i_cl].strip():
                cls[plan].add(r[i_cl])
    out = {}
    for k in set(rev) | set(marg):
        out[k] = (statistics.median(rev[k]) if rev.get(k) else None,
                  statistics.median(marg[k]) if marg.get(k) else None,
                  len(rev.get(k, ())) or len(marg.get(k, ())))
    return out, {p: sorted(v) for p, v in cls.items()}


def main():
    exp, coverage_levels = adm_expected_value()
    print(f"# ADM A00810 expected-value keys loaded: {len(exp):,}")
    print("# Coverage Level Percent values present in A00810 by plan "
          "(this is the ELECTABLE level, straight from the ADM):")
    for p in sorted(coverage_levels):
        print(f"   {p} {AREA_PLANS[p]:<11} {coverage_levels[p]}")

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("""
        select plan_code, plan_abbrev, state, county_fips, crop, commodity_code,
               net_acres, liability
        from sob_sales
        where year=(select max(year) from sob_sales)
          and liability>0 and net_acres>0
    """).fetchall()

    matched = defaultdict(list)          # plan -> [(implied band, acres)]
    by_crop = defaultdict(list)          # (plan, crop) -> [(band, acres)]
    unmatched = defaultdict(int)
    for plan, ab, st, fips, crop, comm, acres, liab in rows:
        if plan not in AREA_PLANS or not fips or len(fips) != 5:
            continue
        k = (plan, fips[:2], fips[2:], (comm or "").zfill(4))
        e = exp.get(k)
        if not e:
            unmatched[plan] += 1
            continue
        exp_rev, exp_marg, _n = e
        base = exp_marg if plan in ("67", "68", "69") else exp_rev
        if not base:
            unmatched[plan] += 1
            continue
        band = (liab / acres) / base
        if 0 < band < 0.60:                      # sanity guard
            matched[plan].append((band, acres))
            by_crop[(plan, crop)].append((band, acres))

    def wmean(pairs):
        w = sum(a for _, a in pairs)
        return sum(b * a for b, a in pairs) / w if w else None

    def wpctl(pairs, p):
        pairs = sorted(pairs)
        tot = sum(a for _, a in pairs)
        run = 0.0
        for b, a in pairs:
            run += a
            if run >= p * tot:
                return b
        return pairs[-1][0] if pairs else None

    print("\n" + "=" * 104)
    print("IMPLIED BAND WIDTH = (SoB liability per acre) / (ADM expected county")
    print("revenue per acre, or expected margin for MCO). Expressed in coverage POINTS.")
    print("=" * 104)
    print(f"  {'plan':<11} {'cells':>7} {'acres(m)':>9} {'p25':>8} {'MEDIAN':>8} "
          f"{'w.mean':>8} {'p75':>8} {'p90':>8}   interpretation")
    for plan in sorted(matched):
        pairs = matched[plan]
        m = wmean(pairs)
        print(f"  {AREA_PLANS[plan]:<11} {len(pairs):>7,} "
              f"{sum(a for _, a in pairs)/1e6:>9.2f} "
              f"{wpctl(pairs,.25)*100:>7.1f}p {wpctl(pairs,.50)*100:>7.1f}p "
              f"{m*100:>7.1f}p {wpctl(pairs,.75)*100:>7.1f}p "
              f"{wpctl(pairs,.90)*100:>7.1f}p")
    if unmatched:
        print(f"\n  county-crop cells with no ADM expected value match: "
              f"{ {AREA_PLANS[p]: n for p, n in sorted(unmatched.items())} }")

    print("\nBy crop (acre-weighted mean implied band, points):")
    print(f"  {'plan':<11} {'crop':<16} {'cells':>7} {'acres(m)':>9} {'band pts':>9}")
    agg = []
    for (plan, crop), pairs in sorted(by_crop.items()):
        ac = sum(a for _, a in pairs)
        if ac < 200_000:
            continue
        agg.append((AREA_PLANS[plan], crop, len(pairs), ac, wmean(pairs) * 100))
    for a in sorted(agg, key=lambda t: (t[0], -t[3])):
        print(f"  {a[0]:<11} {a[1]:<16} {a[2]:>7,} {a[3]/1e6:>9.2f} {a[4]:>9.1f}")

    # ---- paired ECO vs SCO in the SAME county-crop cell -------------------------
    print("\n" + "=" * 104)
    print("PAIRED ECO-RP vs SCO-RP in the SAME county x crop cell.")
    print("Same expected county revenue cancels out, so the ratio is purely BAND ratio.")
    print("=" * 104)
    cell = defaultdict(dict)
    for plan, ab, st, fips, crop, comm, acres, liab in rows:
        if plan in ("32", "88") and acres > 0:
            cell[(fips, crop)][plan] = liab / acres
    both = [(d["32"], d["88"]) for d in cell.values() if "32" in d and "88" in d]
    ratios = [b / a for a, b in both if a > 0]
    ratios.sort()
    if ratios:
        n = len(ratios)
        print(f"  paired county-crop cells: {n:,}")
        print(f"  ECO-RP $/ac  /  SCO-RP $/ac :  p10={ratios[int(.1*n)]:.3f}  "
              f"p25={ratios[int(.25*n)]:.3f}  median={ratios[int(.5*n)]:.3f}  "
              f"p75={ratios[int(.75*n)]:.3f}  p90={ratios[int(.9*n)]:.3f}")
        print("  A ratio near 1.0 means the two bands are about equally wide, which is")
        print("  only possible if SCO's top is well above the underlying coverage level.")


if __name__ == "__main__":
    main()
