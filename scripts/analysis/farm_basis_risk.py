#!/usr/bin/env python3
"""farm_basis_risk.py -- a producer's OWN basis risk, from their OWN APH yield history.

The county table (basis_risk_county) describes a TYPICAL farm. Nobody farms a typical farm.
This is the tool that gets to a real answer, and it needs no private data we do not have:
the producer reads a short yield series off their own APH / production schedule and supplies
it. Everything else -- the county history, the trend, the band mechanics -- we already hold.

    # yields typed in directly, oldest first, matched to --start-year
    scripts/analysis/farm_basis_risk.py --county 19153 --crop Corn --start-year 2016 \
        --yields 178,201,165,212,109,198,206,183,214,190 --coverage-level 0.85

    # or year:yield pairs in any order
    scripts/analysis/farm_basis_risk.py --county 19153 --crop Corn \
        --yields 2016:178,2017:201,2018:165 ...

    # or a CSV with year,yield columns
    scripts/analysis/farm_basis_risk.py --county 19153 --crop Corn --csv myaph.csv

    # compare every band at once
    scripts/analysis/farm_basis_risk.py --county 19153 --crop Corn --csv myaph.csv --all-bands

WHAT THE PRODUCER GETS THAT THE MAP CANNOT GIVE THEM
----------------------------------------------------
1. THEIR measured correlation to the county -- and its confidence interval, because ten APH
   years buy a wide one and a point estimate would be a lie of precision.
2. THEIR own history, year by year: which years they lost, which of those the county index
   would have paid, and which it would have missed. Small sample, but it is their sample.
3. The modelled miss rate at THEIR rho, bracketed by that confidence interval.

Every number the model produces still rests on the assumption stated in src/basisrisk.py:
farm = county + independent idiosyncratic shock. What changes here is that rho is MEASURED
from the producer's own yields instead of imported.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src import basisrisk as B                                      # noqa: E402
from src import config, db                                          # noqa: E402

# MEASURED from the 2026 ADM Price record (A00810 "Price Volatility Factor") medians.
PRICE_VOL = {"Corn": 0.15, "Soybeans": 0.13, "Wheat": 0.19}


def parse_yields(args) -> dict[int, float]:
    """Accept year:yield pairs, a bare list plus --start-year, or a CSV."""
    out: dict[int, float] = {}
    if args.csv:
        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        for row in rows:
            if len(row) < 2:
                continue
            try:
                out[int(str(row[0]).strip())] = float(str(row[1]).strip())
            except ValueError:
                continue        # header or blank line
        if not out:
            sys.exit(f"no year,yield rows found in {args.csv}")
        return out

    if not args.yields:
        sys.exit("supply --yields or --csv")
    parts = [p.strip() for p in args.yields.split(",") if p.strip()]
    if ":" in parts[0]:
        for p in parts:
            y, v = p.split(":", 1)
            out[int(y)] = float(v)
        return out
    if not args.start_year:
        sys.exit("--yields without year labels needs --start-year (the OLDEST year)")
    for i, p in enumerate(parts):
        out[args.start_year + i] = float(p)
    return out


def fmt(x, pct=True, nan="n/a") -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return nan
    return f"{x:.1%}" if pct else f"{x:.3f}"


def show(r: B.FarmBasisRisk, band: str, crop: str, county_name: str, args) -> None:
    print("\n" + "=" * 92)
    print(f"{band}  |  {crop}  |  {county_name}  |  your coverage level "
          f"{args.coverage_level:.0%}  |  {r.modelled.plan_type}")
    print(f"band: pays from {r.modelled.trigger:.0%} of expected county revenue down to "
          f"{r.modelled.exit:.0%}  ({(r.modelled.trigger-r.modelled.exit)*100:.0f} points wide)")
    print("=" * 92)

    print("\n  YOUR SERIES vs THE COUNTY (measured — this part is not modelled)")
    print(f"    overlapping years            : {r.n_common_years}  ({min(r.years)}-{max(r.years)})")
    print(f"    county series behind it      : {r.county_n_years} years")
    print(f"    your detrended yield CV      : {r.farm_cv:.3f}")
    print(f"    county detrended yield CV    : {r.county_cv:.3f}")
    print(f"    your correlation to the county: {r.rho_measured:+.3f}   "
          f"(90% CI {r.rho_ci_lo:+.2f} .. {r.rho_ci_hi:+.2f})")
    print(f"    same thing implied by the CVs : {r.rho_implied_by_cv:+.3f}   "
          "(county CV / your CV — should agree)")
    print(f"    detrended by                  : farm='{r.farm_detrend}' "
          f"({r.farm_trend_pct_per_year:+.2%}/yr), county='ols'")

    print("\n  WHAT ACTUALLY HAPPENED, in your own years")
    yrs = lambda v: ", ".join(str(y) for y in v) if v else "none"      # noqa: E731
    print(f"    years you were below {args.coverage_level:.0%} of trend : "
          f"{len(r.farm_shortfall_years)} of {r.n_common_years}  [{yrs(r.farm_shortfall_years)}]")
    print(f"    years the county index would have paid : "
          f"{len(r.historical_pay_years)}  [{yrs(r.historical_pay_years)}]")
    print(f"    YOU LOST AND IT WOULD NOT HAVE PAID   : "
          f"{len(r.historical_miss_years)}  [{yrs(r.historical_miss_years)}]")
    print(f"    it would have paid with no loss to you: "
          f"{len(r.historical_windfall_years)}  [{yrs(r.historical_windfall_years)}]")
    if r.n_common_years < 15:
        print(f"    ^ {r.n_common_years} years is a small sample. These counts are your record, "
              "not a frequency.")

    m, lo, hi = r.modelled, r.modelled_rho_lo, r.modelled_rho_hi
    print(f"\n  MODELLED, at your measured correlation (rho = {r.rho_used:.2f})")
    print(f"    {'':<52}{'at rho ' + f'{lo.rho:.2f}':>12}{'YOURS':>10}{'at rho ' + f'{hi.rho:.2f}':>12}")
    rows = [
        ("P(you have a loss beyond your deductible)", "p_farm_loss"),
        ("P(the band pays anything)", "p_band_pays"),
        ("P(band pays NOTHING | you had a loss)  <-- basis risk", "miss_rate"),
        ("P(band pays nothing AND you had a loss), per year", "p_hard_miss"),
        ("P(band pays nothing | you lost 10+ points deep)", "deep_miss_rate"),
        ("P(band pays | you had NO loss)  <-- transfer, not cover", "windfall_rate"),
        ("share of your in-band loss dollars left uncovered", "uncovered_share"),
    ]
    for label, attr in rows:
        print(f"    {label:<52}{fmt(getattr(lo, attr)):>12}{fmt(getattr(m, attr)):>10}"
              f"{fmt(getattr(hi, attr)):>12}")
    print(f"    {'correlation of the payment with your actual loss':<52}"
          f"{fmt(lo.payout_corr, False):>12}{fmt(m.payout_corr, False):>10}"
          f"{fmt(hi.payout_corr, False):>12}")

    subsidy = args.subsidy
    print(f"\n  WHAT IT IS WORTH TO YOU")
    print(f"    gross expected return per producer dollar : {1/(1-subsidy):.2f}x")
    print(f"      = 1/(1-{subsidy:.0%}) at FCIC's statutory target loss ratio of 1.0 "
          "(7 U.S.C. 1506(n)(2)).")
    print("      This is an ARITHMETIC IDENTITY. It is the same for every farm in the country,")
    print("      and it is the number the sales pitch quotes.")
    useful = (1 - m.windfall_share) / (1 - subsidy)
    print(f"    of which arrives in a year you actually lost : {useful:.2f}x")
    print(f"      The rest ({m.windfall_share:.0%} of expected payments) lands in years you had no")
    print("      in-band loss. That is real income, but it is a transfer, not insurance — and it")
    print("      is exactly offset by the years the loss came and the cheque did not.")

    for w in r.warnings:
        print(f"\n  !! {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--county", required=True, help="5-digit county FIPS, e.g. 19153 (Polk, IA)")
    ap.add_argument("--crop", required=True, choices=("Corn", "Soybeans", "Wheat"))
    ap.add_argument("--yields", help="comma list: '178,201,165' with --start-year, or '2016:178,...'")
    ap.add_argument("--start-year", type=int, help="year of the FIRST value in --yields")
    ap.add_argument("--csv", help="CSV with year,yield columns")
    ap.add_argument("--coverage-level", type=float, default=0.85,
                    help="YOUR underlying MPCI coverage level (your deductible)")
    ap.add_argument("--band", default="ECO95", choices=sorted(B.BAND_SPECS))
    ap.add_argument("--all-bands", action="store_true")
    ap.add_argument("--plan-type", default="RP", choices=("RP", "YP"))
    ap.add_argument("--farm-detrend", default="county", choices=("county", "own", "none"))
    ap.add_argument("--detrend", default="ols", choices=("ols", "theilsen", "mean"))
    ap.add_argument("--class-desc", help="force a NASS wheat class (WINTER, 'SPRING, (EXCL DURUM)')")
    ap.add_argument("--practice", help="force a NASS practice (IRRIGATED / NON-IRRIGATED)")
    ap.add_argument("--rho", type=float, help="override the measured correlation")
    ap.add_argument("--subsidy", type=float, default=0.80)
    ap.add_argument("--min-year", type=int, default=1975)
    ap.add_argument("--max-year", type=int, default=2025)
    ap.add_argument("--draws", type=int, default=200_000)
    args = ap.parse_args()

    farm = parse_yields(args)
    conn = db.connect(args.db)
    conn.execute("PRAGMA busy_timeout = 60000")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='nass_county_yield'").fetchone():
        sys.exit("nass_county_yield is missing — run "
                 "`.venv/bin/python -m src.connectors.nass_yield --force` first.")

    s = B.load_series(conn, args.crop, args.county, min_year=args.min_year,
                      max_year=args.max_year, class_desc=args.class_desc,
                      practice=args.practice)
    if s is None:
        sys.exit(f"no usable {args.crop} yield series for county {args.county}. "
                 "Check the FIPS, or try --class-desc / --practice.")
    years, values, cls, prac = s
    meta = conn.execute(
        "SELECT state, county_name FROM nass_county_yield WHERE crop=? AND stat='YIELD' "
        "AND agg_level='COUNTY' AND loc_key=? LIMIT 1", (args.crop, args.county)).fetchone()
    cname = f"{(meta[1] or '?').title()} County, {meta[0]}" if meta else args.county

    nat = None
    ns = B.load_series(conn, args.crop, "US", agg_level="NATIONAL", class_desc=cls,
                       practice="ALL PRODUCTION PRACTICES", min_year=args.min_year,
                       max_year=args.max_year, min_last_year=None)
    if ns:
        cfit = B.detrend(years, values, args.detrend)
        nfit = B.detrend(ns[0], ns[1], args.detrend)
        cr, nr = cfit.ratio_by_year(), nfit.ratio_by_year()
        common = sorted(set(cr) & set(nr))
        if len(common) >= 10:
            import numpy as np
            nat = float(np.corrcoef([cr[y] for y in common], [nr[y] for y in common])[0, 1])

    print(f"county series : {args.crop} / {cls} / {prac} / BU per ACRE — "
          f"{len(years)} years {min(years)}-{max(years)} in {cname}")
    print(f"data grade    : {B.grade_for(len(years))}   "
          f"(A >= 30 years, B 20-29, C 12-19)")
    print(f"your series   : {len(farm)} years {min(farm)}-{max(farm)}")
    if nat is not None:
        print(f"county-to-national yield correlation: {nat:+.2f} "
              "(drives how much of the natural price hedge this county gets)")

    bands = sorted(B.BAND_SPECS) if args.all_bands else [args.band]
    for band in bands:
        try:
            B.band_bounds(band, args.coverage_level)
        except ValueError as exc:
            print(f"\n{band}: skipped — {exc}")
            continue
        # BOTH sequences must be in the SAME year order. list(farm) yields dict INSERTION
        # order while the comprehension below yields SORTED order, so `--yields
        # 2018:165,2016:178` silently paired 2018 with 178 and 2016 with 165 — a mis-pairing
        # that produces a plausible wrong correlation rather than an error.
        farm_years = sorted(farm)
        r = B.farm_basis_risk(
            farm_years, [farm[y] for y in farm_years], years, values,
            crop=args.crop, county_fips=args.county, band=band,
            coverage_level=args.coverage_level, detrend_method=args.detrend,
            farm_detrend=args.farm_detrend, plan_type=args.plan_type,
            price_vol=PRICE_VOL.get(args.crop, 0.15),
            corr_county_national=nat if nat is not None else 0.5,
            n_draws=args.draws, rho_override=args.rho)
        show(r, band, args.crop, cname, args)

    print("\n" + "-" * 92)
    print("HOW TO READ THIS. The county side is measured; the farm side is a model whose one")
    print("free parameter (your correlation to the county) has here been measured from YOUR")
    print("yields rather than assumed. The confidence interval on that correlation is the")
    print("honest width of the answer — with a 10-year APH it is wide, and no amount of")
    print("modelling narrows it. What narrows it is more years of your own records.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
