#!/usr/bin/env python3
"""build_basis_risk_empirical.py -- the OBSERVED basis-risk estimator, from realized indemnities.

Companion to build_basis_risk.py, which SIMULATES basis risk from NASS county yields plus an
assumed farm-county correlation rho=0.70. This one measures how often the area band actually
failed to pay in a county-year where individual policies actually collected, out of the
Summary of Business, and asks what that implies about rho.

    # the three diagnostics that need no sob_sales and run today
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --exposure   # hard part 1
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --bias       # hard part 3

    # these need sob_sales (3.23M rows; rebuilt by scripts/rebuild_rest.sh)
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --headline
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --selection  # hard part 2
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --calibrate
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py --compare
    .venv/bin/python scripts/analysis/build_basis_risk_empirical.py              # write the table

READ THIS BEFORE QUOTING ANY NUMBER THIS PRINTS
-----------------------------------------------
The estimator is real — realized dollars, realized policy counts, no simulation in the
numerator or the denominator. It is also biased in three directions whose SIGNS are known and
whose SIZES are only partly known:

  * the observation window (SCO 2015-, ECO 2021-) contains NONE of the six systemic years in
    the 1989-2024 settled record, which biases the miss rate UP;
  * the SoB counts a policy indemnified when any OPTIONAL UNIT paid, not when the whole farm
    was short, which biases it UP again (--bias measures how much);
  * a county index is published by type and practice, so a cell can read as "fired" on the
    strength of an index no given farm settles on, which biases it DOWN.

And the acres under the area plan are not the acres under the individual plan, which is not a
bias with a sign at all — it is an identification problem these files cannot solve.

So: this is a CALIBRATION and a CROSS-CHECK on rho, not a replacement for it. See
docs/basis_risk_empirical.md.
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src import basisrisk as B                                      # noqa: E402
from src import basisrisk_empirical as E                            # noqa: E402
from src import config, db                                          # noqa: E402

PRICE_VOL = {"Corn": 0.15, "Soybeans": 0.13, "Wheat": 0.19}
DEFAULT_APP_DB = str(config.DATA_DIR / "catalog_app.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def _pct(x) -> str:
    return "     n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:8.1%}"


# ---------------------------------------------------------------- hard part 1

def report_exposure(conn, args) -> None:
    print("HARD PART 1 — the systemic years the estimator can never see\n" + "=" * 78)
    for pair_name in args.pairs:
        spec = E.PAIR_SPECS[pair_name]
        ex = E.systemic_year_exposure(conn, window_min=spec.first_year,
                                      window_max=args.max_year, systemic_lr=args.systemic_lr)
        print(f"\n{pair_name}  (plan starts {spec.first_year})")
        print(f"  window                       {ex.window_min}-{ex.window_max}, "
              f"{len(ex.window_years)} settled years")
        print(f"  national loss ratio in window mean {ex.window_mean_lr:.3f}, "
              f"max {ex.window_max_lr:.3f}")
        print(f"  national loss ratio, full     mean {ex.full_mean_lr:.3f} over "
              f"{len(ex.full_years)} settled years {min(ex.full_years)}-{max(ex.full_years)}")
        print(f"  systemic years (LR >= {ex.systemic_lr})   base rate "
              f"{ex.base_rate_systemic:.1%}, in window {ex.window_rate_systemic:.1%}")
        print(f"  never observed                {ex.missed_systemic_years}")
        print(f"  share of settled-era indemnity dollars inside the window "
              f"{ex.indemnity_share_in_window:.1%}")
        print(f"  DIRECTION: {ex.direction}")
    print("\n  Why the sign is what it is: a systemic year is by definition a year the COUNTY")
    print("  INDEX falls, so it is a year the band FIRES and the individual losses beside it")
    print("  are hits. A window with no systemic years is a window whose losses are")
    print("  disproportionately local — and local losses are exactly what an index misses.")


# ---------------------------------------------------------------- hard part 3

def report_bias(args) -> None:
    print("HARD PART 3 — what the estimator measures vs what basisrisk.py means\n" + "=" * 78)
    print("""
  The SoB's `policies_indemnified` is a COUNT OF FARMS that collected, not a county-aggregate
  loss ratio, so the usual aggregation objection ("a county average understates how bad
  individual farms got") does not apply to the headline statistic. One gap survives: RMA counts
  a policy indemnified when ANY OPTIONAL UNIT paid. A one-unit loss is more frequent and more
  idiosyncratic than a whole-farm loss, so the estimator conditions on a broader, more local
  event than the simulator does.

  Below: the same generative model as basisrisk.draw_joint, but with many farms per county-year
  so the SoB estimator can be run on synthetic data where the true farm-level answer is known.
  `true` is basisrisk.py's estimand (whole farm below its coverage level); `est` is what the
  SoB estimator would report on the same world.
""")
    rng = np.random.default_rng(args.seed)
    ratios = 1.0 + rng.normal(0, args.county_cv, 45)
    ratios[3], ratios[17] = 0.55, 0.62                # a county's two drought years
    ratios = np.clip(ratios, 0.15, None)
    print(f"  synthetic county: cv {float(np.std(ratios, ddof=1)):.3f}, "
          f"band {args.band}, farm coverage level {args.coverage_level:.2f}, plan RP")
    print(f"\n  {'rho':>5} {'units':>6} {'P(farm loss)':>13} {'P(policy ind)':>14} "
          f"{'true miss':>10} {'est miss':>9} {'bias':>7}")
    for row in E.estimator_bias(ratios, rhos=tuple(args.rhos), units=tuple(args.units),
                                n_farms=args.sim_farms, n_cells=args.sim_cells,
                                coverage_level=args.coverage_level, band=args.band,
                                within_farm_rho=args.within_farm_rho, seed=args.seed):
        print(f"  {row.rho:>5.2f} {row.units_per_farm:>6} {row.p_farm_loss:>13.3f} "
              f"{row.p_policy_loss:>14.3f} {row.true_farm_miss:>10.3f} "
              f"{row.est_miss_policy:>9.3f} {row.bias_policy:>+7.3f}")
    print("\n  Read the bias column against the rho sensitivity it is supposed to inform: the")
    print("  shipped corn SCO86 miss rate moves 0.469 -> 0.246 across rho 0.55 -> 0.85. If the")
    print("  unit-structure bias is of that order, the observed number cannot set rho's LEVEL")
    print("  unless the inversion carries the same unit structure — which is why")
    print("  implied_rho(metric='estimator') is the default and metric='farm' is not.")
    print("\n  WHICH ROW APPLIES. The RY2015-2024 individual RP book (coverage_type A, settled")
    print("  years) is 59.1% ENTERPRISE units by liability, 12.6% basic, 25.1% optional")
    print("  (sob_unit_national). An enterprise unit pools all of the insured's acres of that")
    print("  crop in the county into ONE unit, so for three fifths of the book a policy is")
    print("  indemnified only on a whole-farm shortfall and there is no bias at all. The")
    print("  liability-weighted effective units-per-farm is roughly 1.5, so the units=2 row is")
    print("  the relevant one, not units=4.")
    print("\n  NOT quantified here, and pushing the other way: a county index is published by")
    print("  TYPE AND PRACTICE, so an irrigated index firing marks the whole cell as a hit for")
    print("  dryland farmers who settle on a different index. That biases the miss rate DOWN.")


# ---------------------------------------------------------------- the estimate

def _load(conn, args, pair: str, crops=None, coverage_levels=None):
    """`args.settled` is resolved in main() because sob_year and sob_sales can live in
    different files: catalog_app.db ships sob_year, the county-grain sob_sales does not."""
    return E.load_cells(conn, pair=pair, crops=crops or args.crops,
                        min_year=args.min_year, max_year=args.max_year,
                        coverage_levels=coverage_levels or args.coverage_levels,
                        states=args.states, settled=args.settled)


def report_headline(conn, args) -> None:
    print("THE OBSERVED MISS RATE\n" + "=" * 78)
    for pair in args.pairs:
        try:
            cells = _load(conn, args, pair)
        except E.EmptySourceError as exc:
            print(f"\n{pair}: {exc}")
            continue
        if not cells:
            print(f"\n{pair}: no paired cells")
            continue
        e = E.empirical_miss(cells, pair=pair, fire_eps=args.fire_eps,
                             lr_threshold=args.lr_threshold)
        _, lo, hi = E.bootstrap_ci(cells, by="year", n_boot=args.boot, seed=args.seed,
                                   pair=pair, fire_eps=args.fire_eps,
                                   lr_threshold=args.lr_threshold)
        _, clo, chi = E.bootstrap_ci(cells, by="cell", n_boot=args.boot, seed=args.seed,
                                     pair=pair, fire_eps=args.fire_eps,
                                     lr_threshold=args.lr_threshold)
        print(f"\n{pair}  {e.year_min}-{e.year_max}  {e.n_years} years, {e.n_cells:,} cells, "
              f"{e.n_counties:,} counties")
        print(f"  individual policies earning premium   {e.ind_policies_earning:>14,.0f}")
        print(f"  individual policies INDEMNIFIED       {e.ind_policies_indemnified:>14,.0f}"
              f"   <- the denominator: observed farm losses")
        print(f"  of those, in a cell where the index paid NOTHING "
              f"{e.n_missed_policies:>10,.0f}")
        print(f"  MISS RATE (policy-weighted)           {e.miss_policy:>14.1%}")
        print(f"    year-block 90% interval             "
              f"{f'[{lo:.1%}, {hi:.1%}]':>14}   <- quote this one")
        print(f"    naive i.i.d. interval               "
              f"{f'[{clo:.1%}, {chi:.1%}]':>14}   (wrong; shown for the contrast)")
        print(f"  miss, indemnity-dollar weighted       {_pct(e.miss_dollar)}")
        print(f"  miss, county loss-ratio form >= {args.lr_threshold:.2f}  {_pct(e.miss_cell)}"
              f"   ({e.n_cells_over_threshold:,} cells clear the threshold)")
        print(f"  windfall rate (index paid, no farm loss) {_pct(e.windfall_rate)}")
        print(f"  P(individual policy indemnified)      {_pct(e.p_ind_loss)}")
        print(f"  P(index fires), cell-weighted         {_pct(e.p_area_fires_cell)}")
        print(f"  loss ratio: individual {e.ind_loss_ratio:.3f}   area {e.area_loss_ratio:.3f}")
        print(f"  corr(ind LR, area LR) within county   {e.corr_lr_within_county:>14.3f}")
        print(f"  area acres / individual acres         "
              f"{(e.area_acres / e.ind_acres if e.ind_acres else float('nan')):>14.1%}")

        print("\n  leave-one-year-out (the years the answer rests on):")
        for y, v, n in E.leave_one_year_out(cells, pair=pair, fire_eps=args.fire_eps,
                                            lr_threshold=args.lr_threshold)[:5]:
            print(f"    drop {y}: {v:.1%}  ({v - e.miss_policy:+.1%}, {n:,} cells)")

        try:
            ex = E.systemic_year_exposure(conn, window_min=e.year_min, window_max=e.year_max,
                                          systemic_lr=args.systemic_lr)
            b = E.systemic_bounds(e, ex)
            print(f"\n  systemic-year bound: [{b.miss_lower:.1%}, {b.miss_upper:.1%}]")
            print(f"    {b.note}")
        except E.EmptySourceError as exc:
            print(f"\n  systemic bound unavailable: {exc}")


# ---------------------------------------------------------------- hard part 2

def report_selection(conn, args) -> None:
    print("HARD PART 2 — selection, and the one thing that can be done about it\n" + "=" * 78)
    print("""
  Narrower than it first looks. The area book is not a sample of losses; it is a REVEALED
  INDICATOR OF THE COUNTY INDEX. Whether the index fell below its trigger is a county-level
  fact, the same for every acre of that crop/type/practice whether or not its owner bought the
  endorsement. So the denominator can be the WHOLE individual book — which is also the right
  population, since the question is what a PROSPECTIVE buyer should expect. And SCO is not
  elected acre by acre: 20-SCO 5(a) as replaced by 25-OBBA requires ALL planted acreage of the
  crop in the county insured by the underlying policy to be insured under the endorsement, so
  for an electing policy the two books cover the SAME acres.

  Three channels survive:
    (a) the sample only contains county-years where SOMEBODY bought it;
    (b) the index we see firing is the index the BOOK settles on — a mostly-irrigated SCO book
        marks the cell as a hit off the irrigated index a dryland farm never settles on;
    (c) through RY2025 the ARC bar (20-SCO 5(a)(2), repealed by OBBBA 10303(b)) excluded any
        FSA farm serial number with an ARC election, "regardless of ARC enrollment status".
        ARC-CO is itself a county-index program chosen by producers who expect county-visible
        shortfalls, so the pre-2026 SCO book is short of exactly the acres most likely to see
        the index fire. Direction: biases the observed miss rate UP.

  The available evidence is a stability probe: does the answer move with participation?
    flat profile  -> a selection story must operate equally at 3% and 60% participation.
                     Weak comfort, not proof.
    sloped profile-> selection is live. The LEVEL is uninterpretable; only the within-stratum
                     ordering survives.
""")
    for pair in args.pairs:
        try:
            cells = _load(conn, args, pair)
        except E.EmptySourceError as exc:
            print(f"\n{pair}: {exc}")
            continue
        if not cells:
            continue
        s = E.participation_summary(cells)
        print(f"\n{pair}: individual {s['ind_acres']:,.0f} ac, area {s['area_acres']:,.0f} ac, "
              f"overall participation {s['overall_participation']:.1%}")
        print(f"  county participation: median {s['median_county_participation']:.1%}, "
              f"p90 {s['p90_county_participation']:.1%}, "
              f"{s['share_of_cells_under_5pct']:.1%} of cells below 5%")
        print(f"  {'stratum':>8} {'share range':>16} {'cells':>8} {'counties':>9} "
              f"{'losses':>12} {'miss':>8}")
        strata = E.by_participation_decile(cells, n_strata=args.strata, pair=pair,
                                           fire_eps=args.fire_eps,
                                           lr_threshold=args.lr_threshold)
        for st in strata:
            print(f"  {st.label:>8} {f'{st.lo:.1%}-{st.hi:.1%}':>16} {st.n_cells:>8,} "
                  f"{st.n_counties:>9,} {st.policies_indemnified:>12,.0f} "
                  f"{st.miss_policy:>8.1%}")
        if len(strata) >= 2:
            spread = max(x.miss_policy for x in strata) - min(x.miss_policy for x in strata)
            print(f"  spread across strata: {spread:.1%}  -> "
                  f"{'SLOPED: level not interpretable' if spread > 0.10 else 'flat'}")


# ---------------------------------------------------------------- calibration

def _reference_county(app_conn, crop: str, band: str, coverage_level: float,
                      exposure: dict[str, float] | None) -> tuple[str, float] | None:
    """The county whose simulated county_cv sits at the exposure-weighted median for the crop.

    Calibrating a POOLED miss rate needs one county yield series to invert against, and there
    is no honest "average county series": averaging counties produces a state series, whose
    variance is far lower, which would silently raise the implied rho. Picking a real county at
    the middle of the exposure-weighted CV distribution keeps the series real and its risk
    typical. It is still one county standing in for a thousand — the per-county distribution
    printed alongside is the check on that.
    """
    rows = app_conn.execute(
        "SELECT county_fips, county_cv FROM basis_risk_county WHERE crop=? AND band=? "
        "AND ABS(coverage_level - ?) < 1e-6 AND county_cv IS NOT NULL",
        (crop, band, coverage_level)).fetchall()
    if not rows:
        return None
    fips = [r[0] for r in rows]
    cvs = np.array([float(r[1]) for r in rows])
    if exposure:
        w = np.array([exposure.get(f, 0.0) for f in fips], float)
        if w.sum() <= 0:
            w = np.ones(len(fips))
    else:
        w = np.ones(len(fips))
    order = np.argsort(cvs)
    cw = np.cumsum(w[order]) / w[order].sum()
    pick = order[int(np.searchsorted(cw, 0.5))]
    return fips[pick], float(cvs[pick])


def report_calibrate(conn, app_conn, args) -> None:
    print("CALIBRATION — the rho implied by what actually happened\n" + "=" * 78)
    print("""
  This inverts the simulator: which farm-county correlation rho would have produced the
  observed miss rate? It is model-internal. Every bias in the observed target passes straight
  into rho, and the inversion cannot test the model that generated it. Read the INTERVAL,
  which comes from the year-block bootstrap on the target, not the point.
""")
    if not E.has_table(conn, "nass_county_yield"):
        print("  nass_county_yield is not loaded in this DB — the inversion needs a county")
        print("  yield series. Run `.venv/bin/python -m src.connectors.nass_yield --force`.")
        return
    for pair in args.pairs:
        spec = E.PAIR_SPECS[pair]
        if spec.band is None:
            continue
        for crop in args.crops:
            try:
                cells = _load(conn, args, pair, crops=[crop])
            except E.EmptySourceError as exc:
                print(f"\n{pair}/{crop}: {exc}")
                continue
            if not cells:
                continue
            e = E.empirical_miss(cells, pair=pair, fire_eps=args.fire_eps,
                                 lr_threshold=args.lr_threshold)
            _, lo, hi = E.bootstrap_ci(cells, by="year", n_boot=args.boot, seed=args.seed,
                                       pair=pair, fire_eps=args.fire_eps,
                                       lr_threshold=args.lr_threshold)
            exposure = defaultdict(float)
            for c in cells:
                exposure[c.county_fips] += c.ind_policies_indemnified
            cl = args.coverage_levels[0] if args.coverage_levels else args.sim_coverage_level
            ref = _reference_county(app_conn, crop, spec.band, args.compare_level, exposure)
            if not ref:
                print(f"\n{pair}/{crop}: no basis_risk_county rows to pick a reference county")
                continue
            fips, cv = ref
            series = B.load_series(conn, crop, fips, min_year=1975, max_year=2025)
            if not series:
                print(f"\n{pair}/{crop}: no NASS series for reference county {fips}")
                continue
            ratios = B.detrend(series[0], series[1], "ols").ratio
            for units in args.units:
                ir = E.implied_rho(
                    e.miss_policy, ratios, metric="estimator",
                    target_lo=lo, target_hi=hi,
                    band=spec.band, coverage_level=cl, plan_type=spec.plan_type,
                    price_vol=PRICE_VOL.get(crop, 0.15),
                    units_per_farm=units, within_farm_rho=args.within_farm_rho,
                    n_cells=args.sim_cells, n_farms=args.sim_farms, seed=args.seed)
                head = (f"\n{pair}/{crop}  observed miss {e.miss_policy:.1%} "
                        f"[{lo:.1%}, {hi:.1%}]  band {spec.band} @ CL {cl:.2f}  "
                        f"ref county {fips} (cv {cv:.3f})") if units == args.units[0] else ""
                if head:
                    print(head)
                if ir.rho is None:
                    print(f"    units={units}: NO rho reproduces it. {ir.note}")
                else:
                    iv = (f"[{ir.rho_lo:.2f}, {ir.rho_hi:.2f}]"
                          if ir.rho_lo and ir.rho_hi else "[n/a]")
                    print(f"    units={units}: implied rho {ir.rho:.2f}  interval {iv}"
                          f"   (reference assumption: {B.RHO_REF})")
    print("\n  If the implied rho lands inside basisrisk.py's own 0.55-0.85 sensitivity band,")
    print("  the observed record does not contradict the 0.70 reference and the right move is")
    print("  to keep 0.70 and cite this as corroboration. If it lands outside, the sensitivity")
    print("  band itself is wrong, which is a bigger finding than the point estimate.")


# ---------------------------------------------------------------- comparison

def report_compare(conn, app_conn, args) -> None:
    print("OBSERVED vs SIMULATED, county by county\n" + "=" * 78)
    print(f"""
  Coverage-level caveat, and it is not small. basis_risk_county as shipped is built at farm
  coverage level {args.compare_level:.2f} only. The SCO book is dominated by underlying 0.75 and 0.80
  (RY2015-2026 SCO-RP liability $3.77B at 0.75, $1.86B at 0.80, $0.08B at 0.85). SCO86 at 0.85
  is a ONE-POINT band; at 0.75 it is eleven points. Unless --coverage-levels {args.compare_level:.2f} is
  passed, the observed and simulated sides are not the same product.

  Read the RANK correlation, not the rows. A county contributes at most ten SCO years.
""")
    for pair in args.pairs:
        spec = E.PAIR_SPECS[pair]
        if spec.band is None:
            print(f"\n{pair}: no simulated band to compare against (basisrisk.py writes none)")
            continue
        for crop in args.crops:
            try:
                cells = _load(conn, args, pair, crops=[crop])
            except E.EmptySourceError as exc:
                print(f"\n{pair}/{crop}: {exc}")
                return
            if not cells:
                continue
            cm = E.by_county(cells, min_loss_policies=args.min_loss_policies, pair=pair,
                             fire_eps=args.fire_eps, lr_threshold=args.lr_threshold)
            comp = E.compare_to_simulated(app_conn, cm, band=spec.band, crop=crop,
                                          coverage_level=args.compare_level,
                                          plan_type=spec.plan_type)
            print(f"\n{pair}/{crop} vs {spec.band} @ CL {args.compare_level:.2f}: "
                  f"{comp.n_matched:,} counties matched")
            if not comp.n_matched:
                continue
            print(f"  median observed  {comp.empirical_median:.1%}")
            print(f"  median simulated {comp.simulated_median:.1%}  "
                  f"(rho 0.55 {comp.simulated_median_rho_lo:.1%} / "
                  f"rho 0.85 {comp.simulated_median_rho_hi:.1%})")
            print(f"  observed above simulated in {comp.share_empirical_above_simulated:.1%} "
                  f"of counties")
            print(f"  observed inside the simulated rho band in "
                  f"{comp.share_empirical_inside_rho_band:.1%} of counties")
            print(f"  Spearman rank correlation {comp.spearman:.3f}   <- the number that "
                  f"survives the level bias")


# ---------------------------------------------------------------- the build

def _invert(conn, app_conn, args, spec, crop, e, lo, hi):
    """(rho, rho_lo, rho_hi) implied by one observed miss rate, or (None, None, None).

    Silent about its failures on purpose: this runs inside the row loop, and a missing NASS
    series for one crop must not stop a build. `--calibrate` is the mode that explains itself.
    """
    if not E.has_table(conn, "nass_county_yield") or not E.has_table(app_conn,
                                                                     "basis_risk_county"):
        return (None, None, None)
    exposure = None
    ref = _reference_county(app_conn, crop, spec.band, args.compare_level, exposure)
    if not ref:
        return (None, None, None)
    series = B.load_series(conn, crop, ref[0], min_year=1975, max_year=2025)
    if not series:
        return (None, None, None)
    try:
        ratios = B.detrend(series[0], series[1], "ols").ratio
        cl = args.coverage_levels[0] if args.coverage_levels else args.sim_coverage_level
        ir = E.implied_rho(e.miss_policy, ratios, metric="estimator",
                           target_lo=lo, target_hi=hi, band=spec.band, coverage_level=cl,
                           plan_type=spec.plan_type, price_vol=PRICE_VOL.get(crop, 0.15),
                           units_per_farm=args.build_units,
                           within_farm_rho=args.within_farm_rho,
                           n_cells=args.build_cells, n_farms=args.build_farms, seed=args.seed)
        return (ir.rho, ir.rho_lo, ir.rho_hi)
    except (ValueError, KeyError):
        return (None, None, None)


def build(conn, app_conn, args) -> int:
    if not args.dry_run:
        E.init_tables(conn)
    now = _now_iso()
    rows: list[tuple] = []
    for pair in args.pairs:
        spec = E.PAIR_SPECS[pair]
        cells = _load(conn, args, pair)
        if not cells:
            continue
        cl = args.coverage_levels[0] if args.coverage_levels else 0.0
        kw = dict(pair=pair, fire_eps=args.fire_eps, lr_threshold=args.lr_threshold)

        def emit(grp, grain, crop="", state="", fips=""):
            try:
                e = E.empirical_miss(grp, **kw)
            except ValueError:
                return
            if grain in ("national", "crop") or args.county_ci:
                _, lo, hi = E.bootstrap_ci(grp, by="year", n_boot=args.boot,
                                           seed=args.seed, **kw)
            else:
                lo = hi = float("nan")
            # The inversion is only run where the target is worth inverting: at county grain
            # the target is a handful of years and the implied rho would be pure noise.
            rho = (None, None, None)
            if grain == "crop" and spec.band and not args.no_rho:
                rho = _invert(conn, app_conn, args, spec, crop, e, lo, hi)
            sim = (None, None, None)
            if grain == "county" and spec.band:
                r = app_conn.execute(
                    "SELECT miss_rate, miss_rate_rho_lo, miss_rate_rho_hi FROM "
                    "basis_risk_county WHERE crop=? AND county_fips=? AND band=? "
                    "AND plan_type=? AND ABS(coverage_level - ?) < 1e-6",
                    (crop, fips, spec.band, spec.plan_type, args.compare_level)).fetchone()
                if r:
                    sim = tuple(None if v is None else float(v) for v in r)
            rows.append(E.row_for(e, pair=pair, grain=grain, crop=crop, state=state,
                                  county_fips=fips, coverage_level=cl, band=spec.band,
                                  ci=(lo, hi), rho=rho, sim=sim, fetched_at=now))

        emit(cells, "national")
        for crop in sorted({c.crop for c in cells}):
            emit([c for c in cells if c.crop == crop], "crop", crop=crop)
        for key in sorted({(c.crop, c.state) for c in cells}):
            emit([c for c in cells if (c.crop, c.state) == key], "state",
                 crop=key[0], state=key[1])
        groups: dict[tuple[str, str, str], list] = defaultdict(list)
        for c in cells:
            groups[(c.crop, c.state, c.county_fips)].append(c)
        for (crop, state, fips), grp in sorted(groups.items()):
            if sum(g.ind_policies_indemnified for g in grp) < args.min_loss_policies:
                continue
            emit(grp, "county", crop=crop, state=state, fips=fips)
        print(f"  {pair}: {len(rows):,} rows so far")
    if args.dry_run:
        print(f"\n{len(rows):,} rows computed (dry run — nothing written)")
        return len(rows)
    n = E.upsert_rows(conn, rows)
    print(f"\n{n:,} rows written to basis_risk_empirical")
    print("  REMINDER: add 'basis_risk_empirical' to scripts/build_app_db.py REQUIRED if the "
          "app is to read it (that file is owned elsewhere).")
    return n


def report(conn, args) -> None:
    if not E.has_table(conn, "basis_risk_empirical"):
        print("basis_risk_empirical does not exist yet.")
        return
    print(f"{'pair':<10} {'grain':<10} {'rows':>7} {'mean miss':>12} {'mean rho':>11}")
    for r in conn.execute(
            "SELECT pair, grain, COUNT(*), AVG(miss_policy), AVG(implied_rho) "
            "FROM basis_risk_empirical GROUP BY pair, grain ORDER BY pair, grain"):
        print(f"{r[0]:<10} {r[1]:<10} {r[2]:>7,} "
              f"{(r[3] if r[3] is not None else float('nan')):>12.1%} "
              f"{(r[4] if r[4] is not None else float('nan')):>11.3f}")


# ---------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(config.DB_PATH),
                    help="working DB: sob_sales, sob_year, nass_county_yield")
    ap.add_argument("--app-db", default=DEFAULT_APP_DB,
                    help="DB holding basis_risk_county (14,805 rows ship in catalog_app.db)")
    ap.add_argument("--pairs", default="SCO-RP",
                    help=f"comma-separated; known: {','.join(E.PAIR_SPECS)}")
    ap.add_argument("--crops", default=",".join(E.CROPS))
    ap.add_argument("--states", default="")
    ap.add_argument("--min-year", type=int)
    ap.add_argument("--max-year", type=int, default=2024,
                    help="last SETTLED year; 2025/2026 are excluded regardless")
    ap.add_argument("--coverage-levels", default="",
                    help="restrict both books to these farm coverage levels (matched comparison)")
    ap.add_argument("--compare-level", type=float, default=0.85,
                    help="the coverage_level of the basis_risk_county rows to compare against")
    ap.add_argument("--fire-eps", type=float, default=E.DEFAULT_FIRE_EPS)
    ap.add_argument("--lr-threshold", type=float, default=1.0)
    ap.add_argument("--systemic-lr", type=float, default=E.SYSTEMIC_LR)
    ap.add_argument("--min-loss-policies", type=int, default=E.MIN_LOSS_POLICIES)
    ap.add_argument("--strata", type=int, default=5)
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--county-ci", action="store_true",
                    help="bootstrap county rows too (slow, and the answer is always 'too wide')")
    # simulation knobs
    ap.add_argument("--rhos", default="0.55,0.70,0.85")
    ap.add_argument("--units", default="1,2,4", help="optional units per farm, for --bias")
    ap.add_argument("--within-farm-rho", type=float, default=0.5)
    ap.add_argument("--sim-farms", type=int, default=60)
    ap.add_argument("--sim-cells", type=int, default=6000)
    ap.add_argument("--build-farms", type=int, default=40, help="inversion size during a build")
    ap.add_argument("--build-cells", type=int, default=3000)
    ap.add_argument("--build-units", type=int, default=2,
                    help="units per policy assumed when inverting during a build; the "
                         "liability-weighted mix (59% enterprise / 13% basic / 25% optional) "
                         "implies about 1.5")
    ap.add_argument("--no-rho", action="store_true",
                    help="skip the implied-rho inversion during a build")
    ap.add_argument("--sim-coverage-level", type=float, default=0.80,
                    help="farm coverage level used when --coverage-levels is not set")
    ap.add_argument("--coverage-level", type=float, default=0.80, help="for --bias")
    ap.add_argument("--band", default="SCO86", help="for --bias")
    ap.add_argument("--county-cv", type=float, default=0.16, help="for --bias")
    ap.add_argument("--seed", type=int, default=7)
    # modes
    ap.add_argument("--exposure", action="store_true")
    ap.add_argument("--bias", action="store_true")
    ap.add_argument("--headline", action="store_true")
    ap.add_argument("--selection", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    args.pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    for p in args.pairs:
        if p not in E.PAIR_SPECS:
            sys.exit(f"unknown pair {p!r}; known: {', '.join(E.PAIR_SPECS)}")
    args.crops = [c.strip() for c in args.crops.split(",") if c.strip()]
    args.states = [s.strip() for s in args.states.split(",") if s.strip()] or None
    args.coverage_levels = [float(x) for x in args.coverage_levels.split(",") if x.strip()] or None
    args.rhos = [float(x) for x in args.rhos.split(",") if x.strip()]
    args.units = [int(x) for x in args.units.split(",") if x.strip()]

    if args.bias:
        report_bias(args)
        return 0

    conn = _ro(args.db) if (args.dry_run or args.exposure or args.headline or args.selection
                            or args.calibrate or args.compare) else db.connect(args.db)
    conn.execute("PRAGMA busy_timeout = 120000")
    app_conn = _ro(args.app_db) if os.path.exists(args.app_db) else conn

    # sob_year lives wherever the SoB was loaded; fall back to the app DB, which ships it.
    year_conn = conn
    if not E.has_table(conn, "sob_year") or not conn.execute(
            "SELECT COUNT(*) FROM sob_year").fetchone()[0]:
        year_conn = app_conn
    try:
        args.settled = E.settled_years(year_conn)
    except E.EmptySourceError as exc:
        print(f"\nCANNOT RUN: {exc}")
        return 2

    try:
        if args.exposure:
            report_exposure(year_conn, args)
        elif args.report:
            report(conn, args)
        elif args.headline:
            report_headline(conn, args)
        elif args.selection:
            report_selection(conn, args)
        elif args.calibrate:
            report_calibrate(conn, app_conn, args)
        elif args.compare:
            report_compare(conn, app_conn, args)
        else:
            build(conn, app_conn, args)
    except E.EmptySourceError as exc:
        print(f"\nCANNOT RUN: {exc}")
        return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
