#!/usr/bin/env python3
"""
endorsement_bands.py -- compute the coverage BAND and the producer cost per $1 of
protection for each federal row-crop supplemental/endorsement plan, straight out of
the loaded 2026 ADM files in data/cache/adm/.

Sources (all local, all RMA Actuarial Data Master, reinsurance year 2026):
  A00030 InsuranceOffer      -> offer_id -> (plan, state, county, commodity, irr practice,
                                             Private 508H Flag)
  A00070 SubsidyPercent      -> plan x coverage level -> subsidy percent
  A00460 InsurancePlan       -> plan code -> name/abbrev
  A01130 AreaCoverageLevel   -> offer_id x coverage level -> area loss start/end, payment
                                factor, area rate id     (this is the BAND)
  A01135 AreaRate            -> area rate id -> base rate (premium rate per $1 protection)

Everything printed by this script is computed from those files. Nothing is hardcoded
from a fact sheet.

*** KNOWN LIMITATION, read before trusting the band section ***
The only A01130 AreaCoverageLevel / A01135 AreaRate files currently cached under
data/cache/adm/ are DAILY DELTAS that contain Rainfall Index (plan 13) records only --
ADM Insurance Offer IDs 36,505,703 to 36,771,444, every one of them plan 13. They carry
no SCO/ECO/MCO/STAX rows. The "BAND" and "producer cost per $1 of PROTECTION" sections
below will therefore print EMPTY until the YTD A01130/A01135 extracts are fetched.
The A00070 subsidy table and the A00030 Private-508H-Flag audit are unaffected and are
the sections this script is actually relied on for; band widths are instead derived
indirectly in scripts/analysis/implied_band_width.py, and producer costs empirically in
scripts/analysis/endorsement_economics.py.

Usage:  .venv/bin/python scripts/analysis/endorsement_bands.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

ADM = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "adm")
ADM = os.path.abspath(ADM)

# The supplemental / endorsement layer. Individual-plan codes (01/02/03) are carried
# only as the reference point for "what the underlying policy costs".
AREA_ENDORSEMENT_PLANS = {
    "31": "SCO-YP", "32": "SCO-RP", "33": "SCO-RPHPE",
    "35": "STAX-RP", "36": "STAX-RPHPE",
    "67": "MCO-YP", "68": "MCO-RP", "69": "MCO-RPHPE",
    "87": "ECO-YP", "88": "ECO-RP", "89": "ECO-RPHPE",
}
OTHER_ENDORSEMENT_PLANS = {
    "16": "MP", "17": "MP-HPO",
    "26": "PACE-YP", "27": "PACE-RP", "28": "PACE-RPHPE",
    "37": "HIP-WI",
    "76": "WFRP",
}
UNDERLYING_PLANS = {"01": "YP", "02": "RP", "03": "RPHPE"}

ALL_PLANS = {**AREA_ENDORSEMENT_PLANS, **OTHER_ENDORSEMENT_PLANS, **UNDERLYING_PLANS}

# Row-crop commodity codes of interest (ADM A00420 Commodity).
ROW_CROPS = {
    "0011": "Wheat", "0016": "Peanuts", "0018": "Barley", "0021": "Cotton",
    "0041": "Corn", "0047": "Grain Sorghum", "0051": "Cotton Ex Long Staple",
    "0067": "Rice", "0081": "Soybeans", "0091": "Sunflowers", "0015": "Flax",
    "0078": "Rye", "0075": "Oats", "0028": "Dry Beans", "0064": "Popcorn",
    "0034": "Canola/Rapeseed", "0037": "Dry Peas", "9999": "(other)",
}


def _open(path):
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def _rows(path, skip_header=True):
    with _open(path) as fh:
        if skip_header:
            fh.readline()
        for line in fh:
            line = line.rstrip("\r\n")
            if not line:
                continue
            yield line.split("|")


def find(prefix_contains):
    """Latest ADM file matching a fragment (daily files sort after YTD by name date)."""
    cands = sorted(f for f in os.listdir(ADM) if prefix_contains in f and f.endswith(".txt"))
    if not cands:
        sys.exit(f"ADM file matching {prefix_contains!r} not found in {ADM}")
    return os.path.join(ADM, cands[-1])


# ---------------------------------------------------------------- A00070 subsidy
def load_subsidy():
    """(plan, coverage_level) -> subsidy percent. Uses non-deleted rows only."""
    out = {}
    conflicts = defaultdict(set)
    for r in _rows(find("A00070_SubsidyPercent")):
        if len(r) < 19 or r[18].strip():          # Deleted Date
            continue
        plan, cl, subsidy = r[5], r[6], r[15]
        if plan not in ALL_PLANS or not subsidy:
            continue
        key = (plan, cl)
        conflicts[key].add(subsidy)
        out[key] = float(subsidy)
    # A single plan/level can carry several unit-structure rows; flag real disagreement.
    multi = {k: sorted(v) for k, v in conflicts.items() if len(v) > 1}
    return out, multi


# ---------------------------------------------------------------- A00030 offers
def load_offers(plans):
    """offer_id -> (plan, state, county, commodity, irrigation practice, p508h)."""
    keep = {}
    flag_by_plan = defaultdict(lambda: defaultdict(int))
    offers_by_plan_crop = defaultdict(lambda: defaultdict(int))
    for r in _rows(find("A00030_InsuranceOffer")):
        if len(r) < 39 or r[38].strip():          # Deleted Date
            continue
        plan = r[6]
        if plan not in plans:
            continue
        oid, comm, st, cty, irr, p508h = r[2], r[5], r[7], r[8], r[16], r[32]
        keep[oid] = (plan, st, cty, comm, irr, p508h)
        flag_by_plan[plan][p508h] += 1
        offers_by_plan_crop[plan][comm] += 1
    return keep, flag_by_plan, offers_by_plan_crop


# ---------------------------------------------------------------- A01135 area rates
def load_area_rates():
    """area_rate_id -> list of base rates (one per price-volatility factor)."""
    out = defaultdict(list)
    for r in _rows(find("A01135_AreaRate")):
        if len(r) < 9 or r[8].strip():
            continue
        rid, base = r[3], r[5]
        if base:
            out[rid].append(float(base))
    return out


# ---------------------------------------------------------------- A01130 the band
def scan_bands(offers, area_rates):
    """
    For every area-plan offer, read the (coverage level, area loss start, area loss end,
    payment factor) tuple. This IS the band. Also accumulate base rates so we can report
    the premium per $1 of protection and, with the subsidy, the producer's share.
    """
    bands = defaultdict(lambda: defaultdict(int))     # plan -> (cl, start, end, pf) -> n
    rates = defaultdict(list)                          # (plan, cl) -> [base rates]
    rates_by_irr = defaultdict(list)                   # (plan, cl, irr) -> [base rates]
    for r in _rows(find("A01130_AreaCoverageLevel")):
        if len(r) < 16 or r[15].strip():
            continue
        oid = r[3]
        off = offers.get(oid)
        if off is None:
            continue
        plan, st, cty, comm, irr, _p = off
        cl, start, end, pf, rid = r[6], r[9], r[10], r[11], r[12]
        bands[plan][(cl, start, end, pf)] += 1
        for b in area_rates.get(rid, ()):
            rates[(plan, cl)].append(b)
            rates_by_irr[(plan, cl, irr)].append(b)
    return bands, rates, rates_by_irr


def pctl(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the computed tables to this path")
    args = ap.parse_args()

    subsidy, subsidy_conflicts = load_subsidy()
    print("== A00070 SubsidyPercent, 2026 (endorsement layer) ==")
    for plan in sorted(ALL_PLANS):
        lv = sorted((cl, s) for (p, cl), s in subsidy.items() if p == plan)
        if lv:
            print(f"  {plan} {ALL_PLANS[plan]:<10} " +
                  "  ".join(f"{float(cl):.0%}:{s:.0%}" for cl, s in lv))
    if subsidy_conflicts:
        print("  NOTE: plan/level pairs with more than one subsidy value:",
              dict(list(subsidy_conflicts.items())[:10]))

    offers, flag_by_plan, offers_by_crop = load_offers(set(ALL_PLANS))
    print("\n== A00030 InsuranceOffer: RMA's own 'Private 508H Flag' by plan ==")
    for plan in sorted(flag_by_plan):
        d = flag_by_plan[plan]
        tot = sum(d.values())
        y = d.get("Y", 0)
        print(f"  {plan} {ALL_PLANS[plan]:<10} offers={tot:>7,}  508H=Y {y:>7,} ({y/tot:.0%})")

    print("\n== Offer footprint by plan x row crop (top crops) ==")
    for plan in sorted(offers_by_crop):
        if plan not in AREA_ENDORSEMENT_PLANS and plan not in OTHER_ENDORSEMENT_PLANS:
            continue
        d = offers_by_crop[plan]
        top = sorted(d.items(), key=lambda kv: -kv[1])[:6]
        print(f"  {plan} {ALL_PLANS[plan]:<10} " +
              "  ".join(f"{ROW_CROPS.get(c, c)}:{n:,}" for c, n in top))

    area_rates = load_area_rates()
    print(f"\n== A01135 AreaRate: {len(area_rates):,} distinct area rate ids loaded ==")

    area_offers = {k: v for k, v in offers.items() if v[0] in AREA_ENDORSEMENT_PLANS}
    print(f"   scanning A01130 against {len(area_offers):,} area-plan offers "
          "(this reads ~12.8M rows)...")
    bands, rates, rates_by_irr = scan_bands(area_offers, area_rates)

    print("\n== A01130 AreaCoverageLevel: the BAND, by plan ==")
    print("   cov lvl | loss start | loss end | payment factor | n offers")
    for plan in sorted(bands):
        print(f"  -- {plan} {AREA_ENDORSEMENT_PLANS[plan]}")
        for (cl, start, end, pf), n in sorted(bands[plan].items(),
                                              key=lambda kv: (-kv[1]))[:12]:
            print(f"     {cl:>6} | {start:>10} | {end:>8} | {pf:>14} | {n:,}")

    print("\n== Producer cost per $1 of PROTECTION, area endorsements ==")
    print("   (base rate from A01135; producer share = base rate x (1 - subsidy))")
    print(f"   {'plan':<12} {'cl':>5} {'n':>9} {'rate p25':>9} {'rate med':>9} "
          f"{'rate p75':>9} {'subsidy':>8} {'prod p25':>9} {'prod med':>9} {'prod p75':>9}")
    cost_rows = []
    for (plan, cl), vals in sorted(rates.items()):
        s = subsidy.get((plan, cl))
        if s is None:
            # SCO subsidy is keyed on the UNDERLYING coverage level; area coverage
            # level rows for SCO carry the underlying level, so this should resolve.
            s = subsidy.get((plan, f"{float(cl):.2f}"))
        med, p25, p75 = pctl(vals, .5), pctl(vals, .25), pctl(vals, .75)
        row = dict(plan=plan, abbrev=AREA_ENDORSEMENT_PLANS[plan], coverage_level=cl,
                   n=len(vals), rate_p25=p25, rate_med=med, rate_p75=p75, subsidy=s,
                   producer_p25=None if s is None else p25 * (1 - s),
                   producer_med=None if s is None else med * (1 - s),
                   producer_p75=None if s is None else p75 * (1 - s))
        cost_rows.append(row)
        f = lambda x: "  n/a  " if x is None else f"{x:9.4f}"
        print(f"   {row['abbrev']:<12} {cl:>5} {len(vals):>9,} {f(p25)} {f(med)} {f(p75)} "
              f"{'n/a' if s is None else format(s, '8.0%')} "
              f"{f(row['producer_p25'])} {f(row['producer_med'])} {f(row['producer_p75'])}")

    print("\n== Same, split by irrigation practice (002=non-irrigated, 003=irrigated) ==")
    irr_rows = []
    for (plan, cl, irr), vals in sorted(rates_by_irr.items()):
        if irr not in ("002", "003") or len(vals) < 200:
            continue
        s = subsidy.get((plan, cl))
        med = pctl(vals, .5)
        irr_rows.append(dict(plan=plan, abbrev=AREA_ENDORSEMENT_PLANS[plan],
                             coverage_level=cl, irr=irr, n=len(vals), rate_med=med,
                             subsidy=s,
                             producer_med=None if s is None else med * (1 - s)))
        print(f"   {AREA_ENDORSEMENT_PLANS[plan]:<12} cl={cl} irr={irr} n={len(vals):>8,} "
              f"rate_med={med:.4f} "
              f"producer_med={'n/a' if s is None else format(med*(1-s), '.4f')}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(dict(
                subsidy={f"{p}|{c}": v for (p, c), v in subsidy.items()},
                p508h_flag={p: dict(d) for p, d in flag_by_plan.items()},
                bands={p: {"|".join(k): n for k, n in d.items()} for p, d in bands.items()},
                cost_rows=cost_rows, irr_rows=irr_rows,
            ), fh, indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
