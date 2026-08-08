#!/usr/bin/env python3
"""
endorsement_economics.py -- what the 2026 supplemental/endorsement layer actually costs
a producer per $1 of liability, and how big each product's book is, computed from this
repo's loaded tables.

Sources (all local):
  data/catalog.db  sob_sales          RMA Summary of Business, "sobcov_2026" pull:
                                      net_acres, liability, total_premium, subsidy,
                                      policies_sold by year x state x county x crop x plan
  data/cache/adm/2026_A00070_SubsidyPercent_YTD.txt   statutory subsidy percent
  data/cache/adm/2026_A00030_InsuranceOffer_YTD.txt   offer footprint + Private 508H Flag
  data/cache/adm/2026_A00810_Price_YTD.txt            expected margin / allowable cost
                                                      (margin plans only)

Definitions used throughout:
  producer premium      = total_premium - subsidy            (SoB accounting identity)
  producer cost per $1  = producer premium / liability
  subsidy share         = subsidy / total_premium            (realized, not statutory)
  liability per acre    = liability / net_acres

Nothing here is taken from a fact sheet. Rule text is cited separately in
docs/rowcrop_endorsement_stacking.md.

Usage: .venv/bin/python scripts/analysis/endorsement_economics.py [--csv-dir DIR]
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(ROOT, "data", "catalog.db")
ADM = os.path.join(ROOT, "data", "cache", "adm")

ENDORSEMENT_PLANS = {
    "16": "MP", "17": "MP-HPO",
    "26": "PACE-YP", "27": "PACE-RP", "28": "PACE-RPHPE",
    "31": "SCO-YP", "32": "SCO-RP", "33": "SCO-RPHPE",
    "35": "STAX-RP", "36": "STAX-RPHPE",
    "37": "HIP-WI",
    "67": "MCO-YP", "68": "MCO-RP", "69": "MCO-RPHPE",
    "76": "WFRP",
    "87": "ECO-YP", "88": "ECO-RP", "89": "ECO-RPHPE",
}
FAMILY = {
    "16": "MP", "17": "MP", "26": "PACE", "27": "PACE", "28": "PACE",
    "31": "SCO", "32": "SCO", "33": "SCO", "35": "STAX", "36": "STAX",
    "37": "HIP-WI", "67": "MCO", "68": "MCO", "69": "MCO", "76": "WFRP",
    "87": "ECO", "88": "ECO", "89": "ECO",
}
TRIGGER = {
    "SCO": "AREA (county)", "ECO": "AREA (county)", "MCO": "AREA (county margin)",
    "STAX": "AREA (county)", "MP": "AREA (county margin)",
    "PACE": "INDIVIDUAL (unit)", "HIP-WI": "INDEX (wind grid)",
    "WFRP": "INDIVIDUAL (whole farm)",
}


def q(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def money(x):
    return f"${x/1e9:,.2f}bn" if abs(x) >= 1e9 else f"${x/1e6:,.1f}m"


# --------------------------------------------------------------- ADM subsidy percents
def adm_subsidy():
    path = None
    for f in sorted(os.listdir(ADM)):
        if "A00070_SubsidyPercent" in f:
            path = os.path.join(ADM, f)
    if not path:
        return {}
    out = defaultdict(dict)
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.readline()
        for line in fh:
            r = line.rstrip("\r\n").split("|")
            if len(r) < 19 or r[18].strip():
                continue
            plan, cl, unit, sub = r[5], r[6], r[4], r[15]
            if plan in ENDORSEMENT_PLANS and sub:
                out[plan].setdefault(cl, set()).add(float(sub))
    return out


# --------------------------------------------------------------- margin plan pricing
def margin_price_stats():
    """
    Pull Expected Margin Amount / Allowable Cost Price for the margin plans (16/17 MP,
    67/68/69 MCO) out of A00810 Price so we can say what a margin policy is actually
    insuring per acre. Returns plan -> list of (expected_margin, allowable_cost_price).
    """
    path = None
    for f in sorted(os.listdir(ADM)):
        if "A00810_Price" in f:
            path = os.path.join(ADM, f)
    if not path:
        return {}
    want = {"16", "17", "67", "68", "69", "31", "32", "33", "87", "88", "89", "35", "36"}
    out = defaultdict(list)
    with open(path, encoding="utf-8", errors="replace") as fh:
        hdr = fh.readline().rstrip("\r\n").split("|")
        ix = {name: i for i, name in enumerate(hdr)}
        i_plan = ix["Insurance Plan Code"]
        i_del = ix["Deleted Date"]
        i_marg = ix.get("Expected Margin Amount")
        i_cost = ix.get("Allowable Cost Price")
        i_rev = ix.get("Expected Revenue Amount")
        i_cbv = ix.get("County Base Value")
        i_cl = ix["Coverage Level Percent"]
        for line in fh:
            r = line.rstrip("\r\n").split("|")
            if len(r) <= i_del or r[i_del].strip():
                continue
            plan = r[i_plan]
            if plan not in want:
                continue
            def g(i):
                if i is None or i >= len(r) or not r[i].strip():
                    return None
                try:
                    return float(r[i])
                except ValueError:
                    return None
            out[plan].append((g(i_marg), g(i_cost), g(i_rev), g(i_cbv), r[i_cl]))
    return out


def summarize(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    return dict(n=n, p10=vals[int(.10 * (n - 1))], med=vals[int(.50 * (n - 1))],
                p90=vals[int(.90 * (n - 1))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir")
    args = ap.parse_args()
    if not os.path.exists(DB):
        sys.exit(f"missing {DB}")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    year = conn.execute("select max(year) from sob_sales").fetchone()[0]
    print(f"# SoB crop year in this database: {year}")
    print(f"# source tags: "
          f"{[r[0] for r in conn.execute('select distinct source from sob_sales')]}")

    # ------------------------------------------------------- 1. plan-level economics
    sql = """
      select plan_code, plan_abbrev,
             count(*) rows_, sum(policies_sold) pol, sum(net_acres) acres,
             sum(liability) liab, sum(total_premium) prem, sum(subsidy) subs
      from sob_sales where year=? group by 1,2
    """
    _, rows = q(conn, sql, (year,))
    recs = []
    for plan, ab, nrows, pol, acres, liab, prem, subs in rows:
        if plan not in ENDORSEMENT_PLANS:
            continue
        prod = (prem or 0) - (subs or 0)
        recs.append(dict(
            plan=plan, abbrev=ab, family=FAMILY[plan], trigger=TRIGGER[FAMILY[plan]],
            county_rows=nrows, policies=pol or 0, acres=acres or 0.0,
            liability=liab or 0.0, premium=prem or 0.0, subsidy=subs or 0.0,
            producer_premium=prod,
            cost_per_dollar_liab=(prod / liab) if liab else None,
            premium_rate=(prem / liab) if liab else None,
            realized_subsidy_share=(subs / prem) if prem else None,
            liab_per_acre=(liab / acres) if acres else None,
            producer_cost_per_acre=(prod / acres) if acres else None,
        ))
    recs.sort(key=lambda d: -d["liability"])

    print("\n" + "=" * 118)
    print(f"TABLE 1. 2026 endorsement layer: what it costs the producer per $1 of liability")
    print("=" * 118)
    hdr = (f"{'plan':<11} {'family':<7} {'trigger':<22} {'liability':>10} {'acres(m)':>9} "
           f"{'$liab/ac':>9} {'prem rate':>10} {'subsidy':>8} {'PROD $/ $1 liab':>16} "
           f"{'prod $/ac':>10}")
    print(hdr)
    print("-" * 118)
    for d in recs:
        print(f"{d['abbrev']:<11} {d['family']:<7} {d['trigger']:<22} "
              f"{money(d['liability']):>10} {d['acres']/1e6:>9.2f} "
              f"{(d['liab_per_acre'] or 0):>9.2f} "
              f"{pct(d['premium_rate']):>10} {pct(d['realized_subsidy_share']):>8} "
              f"{(d['cost_per_dollar_liab'] or 0):>16.5f} "
              f"{(d['producer_cost_per_acre'] or 0):>10.2f}")

    tot_l = sum(d["liability"] for d in recs)
    tot_p = sum(d["producer_premium"] for d in recs)
    tot_s = sum(d["subsidy"] for d in recs)
    print("-" * 118)
    print(f"{'TOTAL':<11} {'':<7} {'':<22} {money(tot_l):>10} "
          f"{sum(d['acres'] for d in recs)/1e6:>9.2f} {'':>9} {'':>10} "
          f"{pct(tot_s/(tot_s+tot_p)):>8} {tot_p/tot_l:>16.5f}")

    # family roll-up
    fam = defaultdict(lambda: defaultdict(float))
    for d in recs:
        for k in ("liability", "premium", "subsidy", "producer_premium", "acres"):
            fam[d["family"]][k] += d[k]
        fam[d["family"]]["policies"] += d["policies"]
    print("\nFamily roll-up (all plan variants combined):")
    print(f"  {'family':<8} {'liability':>11} {'share of layer':>15} {'prod prem':>11} "
          f"{'PROD $/ $1':>11} {'subsidy share':>14} {'policies':>10}")
    fam_recs = []
    for f, d in sorted(fam.items(), key=lambda kv: -kv[1]["liability"]):
        cpd = d["producer_premium"] / d["liability"] if d["liability"] else None
        fam_recs.append(dict(family=f, **{k: v for k, v in d.items()},
                             cost_per_dollar_liab=cpd))
        print(f"  {f:<8} {money(d['liability']):>11} {d['liability']/tot_l:>15.1%} "
              f"{money(d['producer_premium']):>11} {(cpd or 0):>11.5f} "
              f"{pct(d['subsidy']/d['premium'] if d['premium'] else None):>14} "
              f"{int(d['policies']):>10,}")

    # ---------------------------------------------- 2. ECO vs SCO: why ECO is bigger
    print("\n" + "=" * 118)
    print("TABLE 2. Why ECO carries ~2x SCO liability. Decomposition on the RP variants.")
    print("=" * 118)
    d_eco = next(d for d in recs if d["abbrev"] == "ECO-RP")
    d_sco = next(d for d in recs if d["abbrev"] == "SCO-RP")
    print(f"  {'':<28}{'SCO-RP':>16}{'ECO-RP':>16}{'ECO / SCO':>14}")
    for label, key in [("county rows (uptake breadth)", "county_rows"),
                       ("policies sold", "policies"),
                       ("net acres", "acres"),
                       ("liability $", "liability"),
                       ("liability per acre $", "liab_per_acre"),
                       ("premium rate (prem/liab)", "premium_rate"),
                       ("producer $ per $1 liab", "cost_per_dollar_liab"),
                       ("producer $ per acre", "producer_cost_per_acre")]:
        a, b = d_sco[key], d_eco[key]
        r = (b / a) if a else None
        fmt = (lambda v: f"{v:,.4f}") if key in ("premium_rate",
                                                 "cost_per_dollar_liab") \
            else (lambda v: f"{v:,.2f}")
        print(f"  {label:<28}{fmt(a):>16}{fmt(b):>16}"
              f"{('%.2fx' % r) if r else 'n/a':>14}")
    print("\n  Read: acres x liability-per-acre is the whole story. If acres explain most")
    print("  of the gap, the difference is UPTAKE; if liability-per-acre does, it is the")
    print("  width of the insured BAND.")
    ac_ratio = d_eco["acres"] / d_sco["acres"]
    lpa_ratio = d_eco["liab_per_acre"] / d_sco["liab_per_acre"]
    print(f"  acres ratio      = {ac_ratio:.3f}   (contributes {ac_ratio:.2f}x)")
    print(f"  $/acre ratio     = {lpa_ratio:.3f}   (contributes {lpa_ratio:.2f}x)")
    print(f"  product          = {ac_ratio*lpa_ratio:.3f}x   vs actual liability ratio "
          f"{d_eco['liability']/d_sco['liability']:.3f}x")

    # ---------------------------------------------- 3. co-election / stacking evidence
    print("\n" + "=" * 118)
    print("TABLE 3. Observed co-election. Counties (county x crop cells) where two")
    print("families both show liability > 0 in 2026 -- direct evidence of legal stacking.")
    print("=" * 118)
    cells = defaultdict(set)
    _, rows = q(conn, """select state, county_fips, crop, plan_code, liability
                         from sob_sales where year=? and liability>0""", (year,))
    for st, cf, crop, plan, liab in rows:
        if plan in FAMILY:
            cells[(st, cf, crop)].add(FAMILY[plan])
    fams = sorted({f for s in cells.values() for f in s})
    pair = defaultdict(int)
    solo = defaultdict(int)
    for s in cells.values():
        for f in s:
            solo[f] += 1
        for i, a in enumerate(sorted(s)):
            for b in sorted(s)[i + 1:]:
                pair[(a, b)] += 1
    print(f"  {'':<9}" + "".join(f"{f:>9}" for f in fams))
    for a in fams:
        line = f"  {a:<9}"
        for b in fams:
            if a == b:
                line += f"{solo[a]:>9,}"
            else:
                k = (a, b) if (a, b) in pair else (b, a)
                line += f"{pair.get(k, 0):>9,}"
        print(line)
    print("  diagonal = county-crop cells where that family sold at all;")
    print("  off-diagonal = cells where BOTH families sold. Non-zero off-diagonal means")
    print("  the pair is at minimum not universally prohibited. It is county-level, not")
    print("  producer-level, so it is a NECESSARY-not-sufficient test for legal stacking.")

    zero_pairs = [(a, b) for i, a in enumerate(fams) for b in fams[i + 1:]
                  if pair.get((a, b), 0) == 0]
    print(f"\n  Pairs never observed together in ANY county-crop cell: "
          f"{zero_pairs if zero_pairs else 'none'}")

    # ---------------------------------------------- 4. crop-level cost dispersion
    print("\n" + "=" * 118)
    print("TABLE 4. Producer cost per $1 of liability, by family x crop (top crops).")
    print("This is the raw 'price' a producer pays for each dollar of stacked coverage.")
    print("=" * 118)
    _, rows = q(conn, """select crop, plan_code, sum(liability), sum(total_premium),
                                sum(subsidy), sum(net_acres)
                         from sob_sales where year=? and liability>0
                         group by 1,2""", (year,))
    byfc = defaultdict(lambda: defaultdict(float))
    for crop, plan, liab, prem, subs, ac in rows:
        if plan not in FAMILY:
            continue
        d = byfc[(FAMILY[plan], crop)]
        d["liab"] += liab or 0
        d["prem"] += prem or 0
        d["subs"] += subs or 0
        d["acres"] += ac or 0
    crop_rows = []
    for (f, crop), d in byfc.items():
        if d["liab"] < 5e6:
            continue
        prod = d["prem"] - d["subs"]
        crop_rows.append(dict(family=f, crop=crop, liability=d["liab"],
                              acres=d["acres"],
                              cost_per_dollar_liab=prod / d["liab"],
                              producer_cost_per_acre=prod / d["acres"] if d["acres"] else None,
                              liab_per_acre=d["liab"] / d["acres"] if d["acres"] else None,
                              subsidy_share=d["subs"] / d["prem"] if d["prem"] else None))
    crop_rows.sort(key=lambda d: (d["family"], -d["liability"]))
    print(f"  {'family':<8} {'crop':<16} {'liability':>10} {'$liab/ac':>9} "
          f"{'prod $/ac':>10} {'PROD $/ $1 liab':>16}")
    for d in crop_rows:
        print(f"  {d['family']:<8} {d['crop']:<16} {money(d['liability']):>10} "
              f"{(d['liab_per_acre'] or 0):>9.2f} "
              f"{(d['producer_cost_per_acre'] or 0):>10.2f} "
              f"{d['cost_per_dollar_liab']:>16.5f}")

    # ---------------------------------------------- 5. statutory subsidy from ADM
    print("\n" + "=" * 118)
    print("TABLE 5. Statutory subsidy percent, 2026 ADM A00070 (endorsement plans).")
    print("Compare with the REALIZED subsidy share in Table 1 -- they should agree.")
    print("=" * 118)
    sub = adm_subsidy()
    for plan in sorted(sub):
        lv = sorted(sub[plan].items())
        s = "  ".join(f"{float(cl):.0%}->{'/'.join(f'{v:.0%}' for v in sorted(vs))}"
                      for cl, vs in lv)
        print(f"  {plan} {ENDORSEMENT_PLANS[plan]:<11} {s}")

    # ---------------------------------------------- 6. margin-plan pricing from ADM
    print("\n" + "=" * 118)
    print("TABLE 6. Margin plans: what a margin policy insures per acre (ADM A00810).")
    print("=" * 118)
    mp = margin_price_stats()
    for plan in sorted(mp):
        marg = summarize([t[0] for t in mp[plan]])
        cost = summarize([t[1] for t in mp[plan]])
        rev = summarize([t[2] for t in mp[plan]])
        cbv = summarize([t[3] for t in mp[plan]])
        name = ENDORSEMENT_PLANS.get(plan, plan)
        parts = []
        for label, s in (("ExpMargin$/ac", marg), ("AllowCostPrice", cost),
                         ("ExpRevenue$/ac", rev), ("CountyBaseValue", cbv)):
            if s:
                parts.append(f"{label} n={s['n']:,} p10={s['p10']:.2f} "
                             f"med={s['med']:.2f} p90={s['p90']:.2f}")
        print(f"  {plan} {name:<11} " + ("\n" + " " * 16).join(parts) if parts
              else f"  {plan} {name:<11} (no priced fields)")

    # ---------------------------------------------- CSV out
    if args.csv_dir:
        os.makedirs(args.csv_dir, exist_ok=True)
        for name, data in (("plan_economics", recs), ("family_economics", fam_recs),
                           ("family_crop_economics", crop_rows)):
            p = os.path.join(args.csv_dir, f"{name}.csv")
            with open(p, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
            print(f"wrote {p}")


if __name__ == "__main__":
    main()
