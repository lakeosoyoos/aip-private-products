#!/usr/bin/env python
"""Reproduce every [C] number in docs/lgm.md. Read-only; safe to run any time.

Four sections, each independently selectable with --only:

  subsidy      the plan-82 ladder as filed, and how it differs in KIND from LRP and DRP
  curve        the deductible curve and where the net-gain optimum sits, per commodity
               and type, checked across all 50 states
  headtohead   LGM-Dairy vs DRP and LGM-Cattle vs LRP on realized RMA experience
  ration       RMA's declared ration, the election bands, and a worked divergence

The curve section reads RMA's published margin draws out of data/cache/lgm/. If the cache
is empty it will fetch the latest LGM ADM zip (~4 MB) once. The head-to-head section reads
the cached sobtpu zips in data/cache/ and needs no network. NOTHING here writes to any
database — the plan-82 rows never reach the catalog anyway until rma_sob.py's row-crop gate
is relaxed (see src/lgm.SOB_GATE_NOTE).

    .venv/bin/python scripts/analysis/lgm_deductible.py
    .venv/bin/python scripts/analysis/lgm_deductible.py --only curve
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import config, lgm                                          # noqa: E402
from src.connectors.rma_sob import (SOBTPU_FIELDS, _read_chunks,     # noqa: E402
                                    iter_records, parse_sob_rows)

# Notional exposure per insured month. Only the scale of the printed dollars depends on
# these; every ratio and every argmax is invariant to them (tests pin that).
SCALE = {"0803": 100.0, "0815": 1000.0, "0847": 10_000.0}

# A crop year keeps developing for about two years, so the newest years understate their own
# indemnity. Same rule and reasoning as rma_sob.SETTLED_LAG_YEARS.
LAST_SETTLED_YEAR = 2024
# LGM-Cattle and LGM-Swine show 0% subsidy in the Summary of Business until crop year 2021.
FIRST_SUBSIDISED_YEAR = 2021


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# 1. The subsidy ladder
# ---------------------------------------------------------------------------

def section_subsidy() -> None:
    _rule("1. THE PLAN-82 SUBSIDY LADDER — keyed on the DEDUCTIBLE, not a coverage level")
    print("ADM A00070 Subsidy Percent, record category 05. Identical in RY2026 and RY2027.")
    for cc, tbl in lgm.SUBSIDY_BY_DEDUCTIBLE.items():
        grid = sorted(tbl)
        cap = min(d for d in grid if tbl[d] == 0.50)
        print(f"\n  {lgm.COMMODITY_NAMES[cc]} ({cc}), ${grid[0]:g}-${grid[-1]:g} "
              f"per {lgm.COMMODITY_UNIT[cc]}, {len(grid)} rungs; caps at 0.50 from ${cap:g}")
        print("    " + "  ".join(f"{d:g}:{tbl[d]:.2f}" for d in grid))

    print("\n  The same ADM file, same year, other livestock plans — a different KEY:")
    print("    plan 81 LRP  cat 08, keyed on coverage level: "
          + " ".join(f"{k:.3f}:{v:.2f}" for k, v in
                     sorted(lgm.LRP_SUBSIDY_BY_COVERAGE.items())))
    print("    plan 83 DRP  cat 04, keyed on coverage level: "
          + " ".join(f"{k:.2f}:{v:.2f}" for k, v in
                     sorted(lgm.DRP_SUBSIDY_BY_COVERAGE.items())))

    print(f"\n  A $0 deductible draws {lgm.subsidy_rate('0803', 0.0):.2f}, not 0.00.")
    print("  The zero-subsidy case is UNPOOLED coverage (target marketings in exactly one")
    print("  month), which zeroes it at EVERY deductible:")
    print("    $0 pooled   -> " f"{lgm.subsidy_rate('0803', 0.0, pooled=True):.2f}")
    print("    $150 pooled -> " f"{lgm.subsidy_rate('0803', 150.0, pooled=True):.2f}")
    print("    $0 unpooled -> " f"{lgm.subsidy_rate('0803', 0.0, pooled=False):.2f}")
    print("    $150 unpooled -> " f"{lgm.subsidy_rate('0803', 150.0, pooled=False):.2f}")
    be = lgm.break_even_subsidy()
    print(f"\n  Step 5 loads premium by {lgm.LOADING_FACTOR}, so at RMA's own rating the")
    print(f"  break-even subsidy is {be:.4%}, not 0%. Unsubsidised LGM therefore loses")
    print(f"  {be:.2%} of total premium in expectation — small, but strictly negative.")


# ---------------------------------------------------------------------------
# 2. The deductible curve
# ---------------------------------------------------------------------------

def _cached_zips() -> list[Path]:
    d = config.CACHE_DIR / "lgm"
    return sorted(d.glob("*_ADMLivestockLgm_Daily_*.zip")) if d.exists() else []


def _fetch_latest(year: int) -> Path | None:
    import requests
    s = requests.Session()
    html = s.get(lgm.LIVESTOCK_BASE.format(year=year), timeout=120).text
    names = lgm.parse_listing(html, year)
    if not names:
        return None
    dest = config.CACHE_DIR / "lgm" / names[-1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = s.get(lgm.LIVESTOCK_BASE.format(year=year) + names[-1], timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def _panels(path: Path) -> list[lgm.MarginPanel]:
    with zipfile.ZipFile(path) as zf:
        mem = {("A00600" if "A00600" in n else "A00610"): zf.read(n).decode("utf-8",
                                                                            "replace")
               for n in zf.namelist() if n.lower().endswith(".txt")}
    return lgm.build_panels(mem.get("A00600", ""), mem.get("A00610", ""))


def section_curve(fetch: bool = True) -> None:
    _rule("2. THE DEDUCTIBLE CURVE — where the interior optimum sits")
    paths = _cached_zips()
    if not paths and fetch:
        for y in (2027, 2026):
            p = _fetch_latest(y)
            if p:
                paths.append(p)
    if not paths:
        print("  no LGM ADM zip in data/cache/lgm/ and fetching is off — skipped")
        return

    seen: set[tuple[str, str]] = set()
    for path in sorted(paths, reverse=True):
        ry = int(re.match(r"(\d{4})_", path.name).group(1))
        panels = _panels(path)
        groups = sorted({(p.commodity_code, p.type_code) for p in panels})
        for cc, tc in groups:
            if (cc, tc) in seen:
                continue
            seen.add((cc, tc))
            here = [p for p in panels if (p.commodity_code, p.type_code) == (cc, tc)]
            argmax_gain: collections.Counter = collections.Counter()
            argmax_pd: collections.Counter = collections.Counter()
            uplift, shown = [], None
            for p in here:
                h = lgm.uniform_marketings(len(p.months), SCALE[cc])
                curve = lgm.deductible_curve(cc, tc, p.state_code, p.expected, p.draws, h)
                g = lgm.optimal_deductible(curve, "gain")
                argmax_gain[g.deductible] += 1
                argmax_pd[lgm.optimal_deductible(curve, "per_dollar").deductible] += 1
                uplift.append(g.net_expected_gain / curve[0].net_expected_gain)
                if shown is None:
                    shown = (p, curve)

            name = lgm.TYPE_NAMES.get((cc, tc), tc)
            unit = lgm.COMMODITY_UNIT[cc]
            print(f"\n  {lgm.COMMODITY_NAMES[cc]} / {name} — RY{ry}, "
                  f"{len(here)} states, {here[0].n_draws} draws, "
                  f"{len(here[0].months)} insured months")
            print(f"    argmax net gain      : "
                  + ", ".join(f"${d:g} ({n} states)" for d, n in
                              sorted(argmax_gain.items())))
            print(f"    argmax return per $1 : "
                  + ", ".join(f"${d:g} ({n} states)" for d, n in
                              sorted(argmax_pd.items())))
            print(f"    net gain at the optimum vs at $0: {np.mean(uplift):.2f}x")

            p, curve = shown
            print(f"    curve for state {p.state_code} at {SCALE[cc]:,.0f} "
                  f"{unit}/month:")
            print(f"      {'deduct':>9} {'subsidy':>8} {'total prem':>12} "
                  f"{'producer':>11} {'net gain':>11} {'per $1':>7} {'guar':>7}")
            bg = lgm.optimal_deductible(curve, "gain")
            for c in curve:
                mark = " <-" if c is bg else ""
                print(f"      {c.deductible:>9.2f} {c.subsidy:>8.2f} "
                      f"{c.total_premium:>12,.0f} {c.producer_premium:>11,.0f} "
                      f"{c.net_expected_gain:>11,.0f} "
                      f"{c.return_per_producer_dollar:>7.2f} "
                      f"{c.guarantee_retained * 100:>6.1f}%{mark}")

    print("\n  Read the two argmax lines together. Return per producer dollar is")
    print("  1/(1-subsidy) at rated experience, so it is flat across every rung above the")
    print("  0.50 cap and cannot distinguish them; net gain falls steadily across that")
    print("  same plateau. The familiar metric goes blind exactly where the money is lost.")


# ---------------------------------------------------------------------------
# 3. Head-to-head on realized experience
# ---------------------------------------------------------------------------

def _livestock_sob() -> list[dict]:
    """Plan 81/82/83 rows out of every cached sobtpu zip. No network."""
    out = []
    for p in sorted(config.CACHE_DIR.glob("*sobtpu_*.zip*")):
        m = re.search(r"sobtpu_(\d{4})", p.name)
        if not m:
            continue
        year = int(m.group(1))
        with zipfile.ZipFile(p) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
            if member is None:
                continue
            with zf.open(member) as fh:
                for row in parse_sob_rows(iter_records(_read_chunks(fh)), SOBTPU_FIELDS):
                    plan = str(row["plan_code"]).strip().zfill(2)
                    if plan not in lgm.LIVESTOCK_PLAN_CODES:
                        continue
                    row["_year"] = year
                    row["_plan"] = plan
                    out.append(row)
    return out


def _num(v) -> float:
    try:
        return float(str(v or "0").strip() or 0)
    except ValueError:
        return 0.0


def section_headtohead() -> None:
    _rule("3. HEAD-TO-HEAD — realized RMA experience, settled crop years only")
    rows = _livestock_sob()
    if not rows:
        print("  no cached sobtpu zips in data/cache/ — skipped")
        return
    years = sorted({r["_year"] for r in rows})
    print(f"  {len(rows):,} livestock rows from cached sobtpu, crop years "
          f"{years[0]}-{years[-1]}; settled = through {LAST_SETTLED_YEAR}.")
    print("  sobtpu is the ONLY public file carrying plans 81/82/83; sobcov omits them.")

    def label(r) -> str:
        if r["_plan"] != "82":
            return "LRP (all)" if r["_plan"] == "81" else "DRP (all)"
        cc = str(r["commodity_code"]).zfill(4)
        if cc == "9999":
            cc = lgm.commodity_from_sob(r["type_code"], r["quantity_type"]) or "9999"
        return "LGM " + lgm.COMMODITY_NAMES.get(cc, cc)

    for lo, tag in ((FIRST_SUBSIDISED_YEAR,
                     f"subsidised era ({FIRST_SUBSIDISED_YEAR}-{LAST_SETTLED_YEAR})"),
                    (0, f"all settled years (through {LAST_SETTLED_YEAR})")):
        agg: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        for r in rows:
            if not lo <= r["_year"] <= LAST_SETTLED_YEAR:
                continue
            a = agg[label(r)]
            a[0] += _num(r["total_premium"])
            a[1] += _num(r["subsidy"])
            a[2] += _num(r["indemnity"])
        print(f"\n  {tag}")
        print(f"    {'plan':20} {'total premium':>16} {'subsidy':>7} {'loss ratio':>11} "
              f"{'indemnity/producer $':>21}")
        for k in sorted(agg):
            tp, su, ind = agg[k]
            if tp <= 0:
                continue
            print(f"    {k:20} {tp:>16,.0f} {su / tp:>7.1%} {ind / tp:>11.2f} "
                  f"{ind / (tp - su):>21.2f}")

    print("\n  LGM-Cattle is the row to look at. Its subsidy is at the top of the ladder")
    print("  and its return per producer dollar is still far below 1.00, because")
    print("  loss_ratio / (1 - subsidy) cannot rescue a loss ratio of 0.21. That is the")
    print("  mirror image of the row-crop 85% finding: there a good loss ratio was ruined")
    print("  by a collapsed subsidy; here a top-of-ladder subsidy is ruined by the rating.")


# ---------------------------------------------------------------------------
# 4. The ration
# ---------------------------------------------------------------------------

def section_ration() -> None:
    _rule("4. THE RATION — LGM's basis risk, and which commodities can escape it")
    print(f"  {'commodity':14} {'type':22} {'corn':>9} {'sbm ton':>9} {'in cwt':>8} "
          f"{'out cwt':>8}  election")
    for (cc, tc), r in sorted(lgm.DECLARED_RATION.items()):
        band = lgm.RATION_BANDS.get((cc, tc), {})
        note = ("electable: " + ", ".join(f"{k} {lo:g}-{hi:g}"
                                          for k, (lo, hi) in band.items())) \
            if r.electable else "FIXED — no election exists"
        print(f"  {lgm.COMMODITY_NAMES[cc]:14} {r.name:22} "
              f"{(r.corn_bu if r.corn_bu is not None else float('nan')):>9.4g} "
              f"{(r.soybean_meal_ton if r.soybean_meal_ton is not None else float('nan')):>9.4g} "
              f"{(r.feeder_cwt if r.feeder_cwt is not None else float('nan')):>8.4g} "
              f"{(r.output_cwt if r.output_cwt is not None else float('nan')):>8.4g}  {note}")

    print("\n  Worked divergence: a dairy feeding 0.9 bu corn and 0.0035 t soybean meal")
    print("  per cwt against RMA's 0.5 bu / 0.002 t default.")
    prices = {"output_price": 18.00, "corn_price": 4.58, "soybean_meal_price": 328.0}
    rng = np.random.default_rng(20260808)
    n = 5000
    draws = {"output_price": 18.0 * np.exp(rng.normal(0, 0.14, n) - 0.5 * 0.14 ** 2),
             "corn_price": 4.58 * np.exp(rng.normal(0, 0.18, n) - 0.5 * 0.18 ** 2),
             "soybean_meal_price": 328.0 * np.exp(rng.normal(0, 0.20, n) - 0.5 * 0.20 ** 2)}
    heavy = lgm.Ration("0847", "997", corn_bu=0.9, soybean_meal_ton=0.0035, output_cwt=1.0)
    d = lgm.ration_divergence("0847", "997", heavy, prices=prices, price_draws=draws)
    print(f"    verdict                      : {d.verdict}")
    for k, v in d.deltas.items():
        b = d.within_band.get(k)
        print(f"    delta {k:<22}: {v:+.5f}"
              + ("" if b is None else ("  (in band)" if b else "  (OUTSIDE BAND)")))
    print(f"    expected margin, insured     : ${d.expected_margin_insured:.3f}/cwt")
    print(f"    expected margin, actual      : ${d.expected_margin_actual:.3f}/cwt")
    print(f"    LEVEL gap                    : ${d.expected_margin_gap:+.3f}/cwt "
          f"(shifts the guarantee; move the deductible to offset)")
    print(f"    RISK: residual sd            : ${d.residual_sd:.3f}/cwt")
    print(f"    RISK: insured margin sd      : ${d.insured_sd:.3f}/cwt")
    print(f"    RISK: tracking correlation   : {d.tracking_corr:.4f}")
    print(f"    RISK: variance NOT tracked   : {d.unexplained_variance_share:.2%}")
    print("\n  The level gap is not basis risk — it is an offsettable bias. The last line")
    print("  is the basis risk, and it is the LGM analogue of basisrisk.py's miss rate.")
    print("  For cattle and dairy it can be driven to zero by declaring your own ration")
    print("  inside RMA's band. For swine no election exists, so whatever it measures is")
    print("  what you keep.")


SECTIONS = {"subsidy": section_subsidy, "curve": section_curve,
            "headtohead": section_headtohead, "ration": section_ration}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=sorted(SECTIONS), action="append")
    ap.add_argument("--no-fetch", action="store_true",
                    help="never hit the network; skip the curve if the cache is empty")
    args = ap.parse_args(argv)
    for name in (args.only or ["subsidy", "curve", "headtohead", "ration"]):
        fn = SECTIONS[name]
        if name == "curve":
            fn(fetch=not args.no_fetch)
        else:
            fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
