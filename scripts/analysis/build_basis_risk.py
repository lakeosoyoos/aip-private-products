#!/usr/bin/env python3
"""build_basis_risk.py -- precompute basis_risk_county from the loaded NASS yield history.

This is the prf_opt_best pattern applied to basis risk: nass_county_yield (~2.6M rows) is the
estimator's INPUT and stays in the local working DB; this script boils it down to one compact
row per county x crop x band x plan x coverage level that survives dropping the input, and
that is what the app ships.

    .venv/bin/python scripts/analysis/build_basis_risk.py                 # build everything
    .venv/bin/python scripts/analysis/build_basis_risk.py --crops Corn --limit 50 --dry-run
    .venv/bin/python scripts/analysis/build_basis_risk.py --calibrate-rho # the rho cross-check
    .venv/bin/python scripts/analysis/build_basis_risk.py --report        # summarize what's there

WHAT EACH ROW MEANS, and the sentence that has to travel with it
---------------------------------------------------------------
Every probability written here is for a TYPICAL farm in that county, not for any actual farm.
We hold no farm-level yield data and cannot get it. The county side is measured; the farm side
is modelled from the county series plus one imported parameter (rho, the farm-county yield
correlation). A producer's real answer comes from the farm calculator
(scripts/analysis/farm_basis_risk.py), which uses their own APH schedule.

SPEED. One simulated sample per (county, rho) serves every band and coverage level -- see
basisrisk.draw_joint. Without that, a national build is hours instead of minutes, and the bands
would be compared on independent simulations rather than on identical weather.
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src import basisrisk as B                                      # noqa: E402
from src import config, db                                          # noqa: E402

CROPS = ["Corn", "Soybeans", "Wheat"]

# Harvest-price volatility factor, per crop. MEASURED: these are the medians of the
# "Price Volatility Factor" field in the 2026 ADM Price record (A00810), read out of
# data/cache/adm/2026_A00810_Price_YTD.txt --
#     corn (0041)  median 0.15, range 0.00-0.16   (n=227,796 rows)
#     soybeans (0081) median 0.13, range 0.12-0.13 (n=351,498)
#     wheat (0011) median 0.19, range 0.16-0.21    (n=116,166)
# Only used for plan_type='RP'; the YP variants have no price leg at all.
PRICE_VOL = {"Corn": 0.15, "Soybeans": 0.13, "Wheat": 0.19}

# The single national parameter behind the natural hedge: how a national yield shortfall moves
# the harvest price. ASSUMED. A county participates only through its own measured correlation
# to the national crop, so a small county in an off-Belt state gets very little of it.
CORR_NATIONAL_PRICE = -0.6

DEFAULT_MIN_YEAR = 1975      # linear-trend era; see docs/basis_risk.md
DEFAULT_MAX_YEAR = 2025      # last complete crop year (2026 is partial/forecast in NASS)

# Nominal acreages for the aggregation-scaling cross-check on rho.
FARM_ACRES = 500.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- national series

def national_ratios(conn, crop: str, min_year: int, max_year: int,
                    detrend_method: str) -> dict[str, dict[int, float]]:
    """Detrended NATIONAL yield ratio by class, for the county-to-national correlation.

    Keyed by class so a WINTER-wheat county is correlated against the national WINTER series
    rather than against a blend it is not part of.
    """
    out: dict[str, dict[int, float]] = {}
    rows = conn.execute(
        "SELECT DISTINCT class_desc FROM nass_county_yield WHERE crop=? AND stat='YIELD' "
        "AND agg_level='NATIONAL'", (crop,)).fetchall()
    for (cls,) in rows:
        s = B.load_series(conn, crop, "US", agg_level="NATIONAL", class_desc=cls,
                          practice="ALL PRODUCTION PRACTICES", min_year=min_year,
                          max_year=max_year, min_last_year=None)
        if not s or len(s[0]) < B.MIN_YEARS:
            continue
        try:
            out[cls] = B.detrend(s[0], s[1], detrend_method).ratio_by_year()
        except ValueError:
            continue
    return out


def corr_to_national(county_fit: B.TrendFit, nat: dict[int, float] | None) -> float | None:
    if not nat:
        return None
    cr = county_fit.ratio_by_year()
    common = sorted(set(cr) & set(nat))
    if len(common) < 10:
        return None
    a = np.array([cr[y] for y in common])
    b = np.array([nat[y] for y in common])
    if a.std() <= 0 or b.std() <= 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------- the build

def build(conn, args) -> dict:
    bands = args.bands
    levels = args.coverage_levels
    rhos = (args.rho_lo, args.rho, args.rho_hi)
    stats = defaultdict(int)
    written: list[tuple] = []
    dist: dict[tuple, list[float]] = defaultdict(list)

    for crop in args.crops:
        nat = national_ratios(conn, crop, args.min_year, args.max_year, args.detrend)
        counties = [r[0] for r in conn.execute(
            "SELECT DISTINCT loc_key FROM nass_county_yield WHERE crop=? AND stat='YIELD' "
            "AND agg_level='COUNTY' AND year >= ? ORDER BY loc_key",
            (crop, B.DEFAULT_MIN_LAST_YEAR)).fetchall()]
        if args.limit:
            counties = counties[:args.limit]
        t0 = time.time()
        price_vol = PRICE_VOL.get(crop, 0.15)

        for i, fips in enumerate(counties):
            s = B.load_series(conn, crop, fips, min_year=args.min_year, max_year=args.max_year)
            if s is None:
                stats[f"{crop}: no live series"] += 1
                continue
            years, values, cls, prac = s
            if len(years) < B.MIN_YEARS:
                stats[f"{crop}: under {B.MIN_YEARS} years"] += 1
                continue
            try:
                fit = B.detrend(years, values, args.detrend)
            except ValueError:
                stats[f"{crop}: undetrendable"] += 1
                continue
            if not (0 < fit.cv < 1.0):
                stats[f"{crop}: implausible CV"] += 1
                continue

            meta = conn.execute(
                "SELECT state, county_name FROM nass_county_yield WHERE crop=? AND stat='YIELD' "
                "AND agg_level='COUNTY' AND loc_key=? LIMIT 1", (crop, fips)).fetchone()
            state, cname = (meta[0], meta[1]) if meta else (None, None)
            cn = corr_to_national(fit, nat.get(cls) or nat.get("ALL CLASSES"))
            grade = B.grade_for(len(years))
            if grade is None:
                stats[f"{crop}: under {B.MIN_YEARS} years"] += 1
                continue

            # Empirical: how often would the index itself have fired, no model involved.
            p_below = {b: float(np.mean(fit.ratio < B.BAND_SPECS[b]["trigger"])) for b in bands}

            kw = dict(plan_type=args.plan_type, price_vol=price_vol,
                      corr_county_national=cn if cn is not None else 0.5,
                      corr_national_price=CORR_NATIONAL_PRICE, idio=args.idio,
                      n_draws=args.draws, seed=args.seed)
            draws = {r: B.draw_joint(fit.ratio, rho=r, **kw) for r in rhos}
            boot = bootstrap_bands(fit, bands, levels, rhos[1], kw, args) if args.boot else {}

            for band in bands:
                for cl in levels:
                    try:
                        m = {r: B.metrics_from_draws(
                            d.farm_ratio, d.county_ratio, band=band, coverage_level=cl,
                            plan_type=args.plan_type, rho=r, county_cv=d.county_cv,
                            farm_cv=d.farm_cv, clipped_share=d.clipped_share)
                            for r, d in draws.items()}
                    except ValueError:
                        # SCO at a coverage level >= 86%: there is nothing to buy.
                        stats[f"{crop}: {band} degenerate at CL {cl}"] += 1
                        continue
                    ref = m[rhos[1]]
                    lo_ci, hi_ci = boot.get((band, cl), (None, None))
                    written.append((
                        crop, fips, state, cname, band, args.plan_type, cl,
                        len(years), min(years), max(years), cls, prac, args.detrend,
                        fit.slope, fit.pct_per_year, fit.r2, fit.mean_yield, fit.cv, fit.skew,
                        p_below[band], cn,
                        rhos[1], ref.miss_rate, ref.p_hard_miss, ref.p_farm_loss_given_no_pay,
                        ref.deep_miss_rate, ref.windfall_rate, ref.uncovered_share,
                        ref.payout_corr,
                        rhos[0], m[rhos[0]].miss_rate, rhos[2], m[rhos[2]].miss_rate,
                        lo_ci, hi_ci, grade, "nass_qs + basisrisk", _now_iso(),
                    ))
                    dist[(crop, band, cl)].append(ref.miss_rate)
                    stats[f"{crop}: rows"] += 1

            if args.progress and (i + 1) % args.progress == 0:
                el = time.time() - t0
                print(f"    {crop}: {i+1}/{len(counties)} counties  "
                      f"{el:.0f}s  ({(i+1)/max(el,1e-9):.1f}/s)", flush=True)

    if not args.dry_run and written:
        conn.execute("DELETE FROM basis_risk_county")
        conn.executemany(
            """INSERT OR REPLACE INTO basis_risk_county
               (crop, county_fips, state, county_name, band, plan_type, coverage_level,
                n_years, year_min, year_max, class_used, practice_used, detrend_method,
                trend_bu_per_year, trend_pct_per_year, trend_r2, mean_yield, county_cv,
                county_skew, p_county_below_trigger, corr_national,
                rho_ref, miss_rate, p_hard_miss, p_farm_loss_given_no_pay, deep_miss_rate,
                windfall_rate, uncovered_share, payout_corr,
                rho_lo, miss_rate_rho_lo, rho_hi, miss_rate_rho_hi,
                miss_rate_ci_lo, miss_rate_ci_hi, grade, source, fetched_at)
               VALUES (""" + ",".join("?" * 38) + ")", written)
        conn.commit()
    return {"stats": dict(stats), "dist": dist, "n": len(written)}


def bootstrap_bands(fit: B.TrendFit, bands, levels, rho, kw, args) -> dict:
    """Bootstrap CI on miss_rate, resampling YEARS and refitting the trend each time.

    Shares one simulated sample across bands within each resample, exactly like the main path,
    so the interval reflects sampling error in the county series rather than Monte Carlo noise.
    """
    rng = np.random.default_rng(args.seed + 1)
    x, y = np.asarray(fit.years, int), np.asarray(fit.values, float)
    got: dict[tuple, list[float]] = defaultdict(list)
    bkw = dict(kw, n_draws=args.boot_draws)
    bkw.pop("seed", None)
    for _ in range(args.boot):
        idx = rng.integers(0, len(x), len(x))
        xi, yi = x[idx], y[idx]
        if len(np.unique(xi)) < 5:
            continue
        try:
            f2 = B.detrend(xi, yi, args.detrend)
            d = B.draw_joint(f2.ratio, rho=rho, rng=np.random.default_rng(rng.integers(1 << 31)),
                             **bkw)
        except ValueError:
            continue
        for band in bands:
            for cl in levels:
                try:
                    got[(band, cl)].append(B.metrics_from_draws(
                        d.farm_ratio, d.county_ratio, band=band, coverage_level=cl).miss_rate)
                except ValueError:
                    continue
    out = {}
    for k, v in got.items():
        v = [z for z in v if not math.isnan(z)]
        if len(v) >= 10:
            out[k] = (float(np.quantile(v, 0.05)), float(np.quantile(v, 0.95)))
    return out


# ---------------------------------------------------------------- rho cross-check

def calibrate_rho(conn, args) -> None:
    """Estimate rho from how yield variance decays with aggregation area — no citation needed.

    NASS publishes the same yield at four nested levels. Fitting var ~ area^b over the three
    orders of magnitude we CAN see, then extrapolating one order further down to farm scale,
    gives an independent handle on sigma_farm/sigma_county = 1/rho. Read the caveats in
    basisrisk.aggregation_scaling before believing it: it is biased toward too high a rho.
    """
    print("=" * 96)
    print("rho CROSS-CHECK: yield variance vs aggregation area (NASS, all four levels)")
    print("=" * 96)
    for crop in args.crops:
        variances: dict[str, list[float]] = defaultdict(list)
        areas: dict[str, list[float]] = defaultdict(list)
        for level in ("COUNTY", "DISTRICT", "STATE", "NATIONAL"):
            keys = [r[0] for r in conn.execute(
                "SELECT DISTINCT loc_key FROM nass_county_yield WHERE crop=? AND stat='YIELD' "
                "AND agg_level=? AND year>=?", (crop, level, B.DEFAULT_MIN_LAST_YEAR))]
            if args.limit and level == "COUNTY":
                keys = keys[:args.limit]
            for k in keys:
                s = B.load_series(conn, crop, k, agg_level=level, min_year=args.min_year,
                                  max_year=args.max_year)
                if not s or len(s[0]) < B.GRADE_B_YEARS:
                    continue
                try:
                    f = B.detrend(s[0], s[1], args.detrend)
                except ValueError:
                    continue
                a = B.load_area(conn, crop, k, agg_level=level, class_desc=s[2],
                                min_year=args.min_year)
                if a and 0 < f.cv < 1:
                    variances[level].append(f.cv ** 2)
                    areas[level].append(a)
        level_areas = {k: float(np.median(v)) for k, v in areas.items() if v}
        if len(level_areas) < 2:
            print(f"  {crop}: not enough levels with data")
            continue
        fit = B.aggregation_scaling(variances, level_areas, farm_acres=args.farm_acres,
                                    county_acres=level_areas.get("COUNTY", 1e5))
        print(f"\n  {crop}:  var ~ area^{fit.exponent:.3f}   (R^2 {fit.r2:.3f}, "
              f"{fit.n_levels} levels)")
        print(f"    {'level':<10} {'n units':>8} {'median acres':>14} {'median CV':>10}")
        for level, area, var in fit.points:
            print(f"    {level:<10} {len(variances[level]):>8,} {area:>14,.0f} "
                  f"{math.sqrt(var):>10.3f}")
        print(f"    extrapolated to a {args.farm_acres:,.0f}-acre farm in a "
              f"{level_areas.get('COUNTY', 0):,.0f}-acre county:")
        for fa in (200, 500, 1_000, 2_500):
            print(f"      {fa:>5,}-acre farm -> implied rho {fit.rho_for(fa, level_areas['COUNTY']):.3f}")
        print(f"    module default RHO_REF = {B.RHO_REF} (sensitivity band "
              f"{B.RHO_LO}-{B.RHO_HI})")
    print("\n  CAVEAT: this extrapolates a power law BEYOND its observed range. Within-county")
    print("  spatial correlation is far higher than between-state, so the fitted decay is too")
    print("  steep at farm scale: it OVERSTATES rho and UNDERSTATES basis risk. Use it as a")
    print("  floor and a sanity check on the literature value, never as a replacement.")


# ---------------------------------------------------------------- reporting

def report(conn, args) -> None:
    n = conn.execute("SELECT COUNT(*) FROM basis_risk_county").fetchone()[0]
    if not n:
        print("basis_risk_county is empty — run the build first.")
        return
    print("=" * 108)
    print("BASIS RISK BY COUNTY — distribution of miss_rate = P(band pays nothing | farm loss)")
    print("Every figure is for a TYPICAL farm in the county, at the reference rho. Not any real farm.")
    print("=" * 108)
    print(f"  {'crop':<10} {'band':<7} {'CL':>5} {'counties':>9} {'p10':>7} {'p25':>7} "
          f"{'median':>7} {'p75':>7} {'p90':>7} {'mean yrs':>9}")
    for row in conn.execute(
        """SELECT crop, band, coverage_level, COUNT(*) n, AVG(n_years) ny
           FROM basis_risk_county GROUP BY 1,2,3 ORDER BY 1,2,3"""):
        crop, band, cl, cnt, ny = row
        v = sorted(r[0] for r in conn.execute(
            "SELECT miss_rate FROM basis_risk_county WHERE crop=? AND band=? AND coverage_level=?",
            (crop, band, cl)) if r[0] is not None)
        if not v:
            continue
        q = lambda p: v[min(len(v) - 1, int(p * len(v)))]           # noqa: E731
        print(f"  {crop:<10} {band:<7} {cl:>5.2f} {cnt:>9,} {q(.10):>7.1%} {q(.25):>7.1%} "
              f"{q(.50):>7.1%} {q(.75):>7.1%} {q(.90):>7.1%} {ny:>9.0f}")

    print("\n  Worst-served and best-served states (ECO95, RP, CL 0.85, counties with grade A/B):")
    for direction, label in (("DESC", "WORST (area band misses most)"),
                             ("ASC", "BEST (area band tracks the farm)")):
        print(f"\n    {label}")
        print(f"      {'state':<6} {'crop':<10} {'counties':>9} {'median miss':>12} "
              f"{'median CV':>10} {'median corr_nat':>16}")
        for r in conn.execute(
            f"""SELECT state, crop, COUNT(*) n, AVG(miss_rate) mr, AVG(county_cv) cv,
                       AVG(corr_national) cn
                FROM basis_risk_county
                WHERE band='ECO95' AND coverage_level=0.85 AND grade IN ('A','B')
                      AND state IS NOT NULL
                GROUP BY state, crop HAVING n >= 10
                ORDER BY mr {direction} LIMIT 10"""):
            print(f"      {r[0]:<6} {r[1]:<10} {r[2]:>9,} {r[3]:>12.1%} {r[4]:>10.3f} "
                  f"{(r[5] if r[5] is not None else float('nan')):>16.2f}")

    print("\n  Sensitivity to rho (the one imported parameter), ECO95 / RP / CL 0.85:")
    r = conn.execute(
        """SELECT AVG(miss_rate_rho_lo), AVG(miss_rate), AVG(miss_rate_rho_hi),
                  AVG(rho_lo), AVG(rho_ref), AVG(rho_hi)
           FROM basis_risk_county WHERE band='ECO95' AND coverage_level=0.85""").fetchone()
    print(f"      rho {r[3]:.2f} -> miss {r[0]:.1%}   |   rho {r[4]:.2f} -> miss {r[1]:.1%}   "
          f"|   rho {r[5]:.2f} -> miss {r[2]:.1%}")
    print(f"      swing across the rho band: {r[0]-r[2]:+.1%} — larger than the spread across "
          "most states, which is the honest limit on how far this can be pushed.")

    print("\n  Uncertainty from series length (ECO95 / RP / CL 0.85):")
    print(f"      {'grade':<7} {'counties':>9} {'median yrs':>11} {'median CI width':>16}")
    for g in ("A", "B", "C"):
        rows = [r for r in conn.execute(
            "SELECT n_years, miss_rate_ci_lo, miss_rate_ci_hi FROM basis_risk_county "
            "WHERE band='ECO95' AND coverage_level=0.85 AND grade=?", (g,))]
        w = [r[2] - r[1] for r in rows if r[1] is not None and r[2] is not None]
        if not rows:
            continue
        print(f"      {g:<7} {len(rows):>9,} {statistics.median(r[0] for r in rows):>11.0f} "
              f"{(statistics.median(w) if w else float('nan')):>16.1%}")


# ---------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--crops", default=",".join(CROPS))
    ap.add_argument("--bands", default="ECO95,ECO90,SCO86")
    ap.add_argument("--coverage-levels", default="0.85",
                    help="the FARM's own MPCI coverage level(s) = its deductible")
    ap.add_argument("--plan-type", default="RP", choices=("RP", "YP"))
    ap.add_argument("--detrend", default="ols", choices=("ols", "theilsen", "mean"))
    ap.add_argument("--rho", type=float, default=B.RHO_REF)
    ap.add_argument("--rho-lo", type=float, default=B.RHO_LO)
    ap.add_argument("--rho-hi", type=float, default=B.RHO_HI)
    ap.add_argument("--idio", default="normal", choices=("normal", "skewed"))
    ap.add_argument("--draws", type=int, default=60_000)
    ap.add_argument("--boot", type=int, default=40, help="bootstrap resamples (0 = skip)")
    ap.add_argument("--boot-draws", type=int, default=6_000)
    ap.add_argument("--min-year", type=int, default=DEFAULT_MIN_YEAR)
    ap.add_argument("--max-year", type=int, default=DEFAULT_MAX_YEAR)
    ap.add_argument("--farm-acres", type=float, default=FARM_ACRES)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--limit", type=int, help="only the first N counties per crop (testing)")
    ap.add_argument("--progress", type=int, default=250)
    ap.add_argument("--dry-run", action="store_true", help="compute but do not write")
    ap.add_argument("--calibrate-rho", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    args.crops = [c.strip() for c in args.crops.split(",") if c.strip()]
    args.bands = [b.strip() for b in args.bands.split(",") if b.strip()]
    args.coverage_levels = [float(x) for x in args.coverage_levels.split(",") if x.strip()]

    conn = db.connect(args.db)
    conn.execute("PRAGMA busy_timeout = 120000")
    db.init_db(conn)

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='nass_county_yield'").fetchone():
        sys.exit("nass_county_yield is missing — run "
                 "`.venv/bin/python -m src.connectors.nass_yield --force` first.")

    if args.report:
        report(conn, args)
        return 0
    if args.calibrate_rho:
        calibrate_rho(conn, args)
        return 0

    print(f"Building basis_risk_county: crops={args.crops} bands={args.bands} "
          f"CL={args.coverage_levels} plan={args.plan_type} detrend={args.detrend} "
          f"rho={args.rho_lo}/{args.rho}/{args.rho_hi} draws={args.draws:,}", flush=True)
    t0 = time.time()
    res = build(conn, args)
    print(f"\n{res['n']:,} rows in {time.time()-t0:.0f}s"
          f"{' (dry run — nothing written)' if args.dry_run else ''}")
    for k, v in sorted(res["stats"].items()):
        print(f"  {k:<44} {v:>8,}")
    if res["dist"]:
        print("\n  miss_rate distribution (P(band pays nothing | farm loss)):")
        for key, v in sorted(res["dist"].items()):
            v = sorted(v)
            q = lambda p: v[min(len(v) - 1, int(p * len(v)))]        # noqa: E731
            print(f"    {key[0]:<10} {key[1]:<7} CL {key[2]:.2f}  n={len(v):>5,}  "
                  f"p10 {q(.10):.1%}  median {q(.50):.1%}  p90 {q(.90):.1%}")
    if not args.dry_run:
        print("\n  REMINDER: nass_county_yield must be added to build_app_db.py's DROP_TABLES, "
              "and basis_risk_county to REQUIRED.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
