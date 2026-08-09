#!/usr/bin/env python
"""Reproduce every [C] number in docs/lgm_backtest.md. Read-only; safe to run any time.

Five sections, each independently selectable with --only:

  archive      what the pubfs LGM tree actually holds, and how much of it is settled
  actuals      the evidence that A00600's Actual columns ARE populated after settlement,
               and the evidence that a forward-looking file proves nothing either way
  structure    the marketing-month bundle, the national margin, and the observation count
               that survives the three collapses
  ladder       the measured deductible ladder against the forward-looking one, pooled and
               by reinsurance year
  crosscheck   the reconstruction against RMA's own Summary of Business loss ratios

Everything runs off data/cache/lgm/history/ and data/cache/lgm/history_draws/, which
`python -m src.lgmbacktest --harvest --years 2014-2027` fills from pubfs. NOTHING here
writes to any database or to the ADM cache.

    .venv/bin/python scripts/analysis/lgm_backtest.py
    .venv/bin/python scripts/analysis/lgm_backtest.py --only ladder
"""
from __future__ import annotations

import argparse
import collections
import gzip
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import lgm, lgmbacktest as B                                # noqa: E402

WINDOW = tuple(range(B.FIRST_BACKTESTABLE_RY, 2027))
ARCHIVE_YEARS = tuple(range(B.ARCHIVE_FIRST_RY, 2028))

# docs/lgm.md s2.2: the ladder computed off RMA's rate draws, before any measurement.
FORWARD_OPTIMUM = {("0803", "807"): 70.0, ("0803", "808"): 70.0,
                   ("0815", "804"): 10.0, ("0815", "805"): 10.0, ("0815", "806"): 10.0,
                   ("0847", "997"): 1.00}

# docs/lgm.md s3.1, from the cached sobtpu files: realized plan-82 loss ratios, crop years
# 2021-2024, national, blended over whatever deductibles producers actually elected.
SOB_LOSS_RATIO = {"0803": 0.21, "0815": 0.98, "0847": 1.01}


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _label(cc: str, tc: str) -> str:
    return f"{lgm.COMMODITY_NAMES.get(cc, cc)} / {lgm.TYPE_NAMES.get((cc, tc), tc)}"


# ---------------------------------------------------------------------------
# 1. Archive coverage
# ---------------------------------------------------------------------------

def section_archive() -> None:
    _rule("1. WHAT THE pubfs LGM ARCHIVE ACTUALLY HOLDS")
    print("adm_livestock/{RY}/{RY}_ADMLivestockLgm_Daily_{YYYYMMDD}.zip, member A00600.\n")
    print(f"{'RY':>5} {'files':>6} {'layout':>7} {'sed?':>5} {'sales dates':>12} "
          f"{'settled keys':>13}  {'span of published files':<21}")
    for ry in ARCHIVE_YEARS:
        files = B.history_files(ry)
        if not files:
            continue
        stamps = sorted(f.name.split("_")[3] for f in files)
        merged = B.load_history(ry)
        head = gzip.decompress(files[0].read_bytes()).decode(
            "utf-8", "replace").split("\n")[0]
        layout = "wide" if "Month2 Expected Gross Margin Amount" in head else "long"
        sed_col = "yes" if "Sales Effective Date" in head else "NO"
        seds = {k[4] for k in merged}
        settled = sum(1 for v in merged.values() if v.settled)
        print(f"{ry:>5} {len(files):>6} {layout:>7} {sed_col:>5} {len(seds):>12} "
              f"{settled:>13}  {stamps[0]} .. {stamps[-1]}")
    print(f"\nThe layout change is the window boundary: 'long' years carry no Sales "
          f"Effective\ncolumn before RY2022, so the guarantee cannot be attached to the "
          f"purchase that\nstruck it. Backtest window = RY{B.FIRST_BACKTESTABLE_RY} "
          f"onward.")


# ---------------------------------------------------------------------------
# 2. Are the Actual columns populated?
# ---------------------------------------------------------------------------

def section_actuals() -> None:
    _rule("2. THE Actual Gross Margin COLUMNS — forward files vs settled files")
    print("A forward-looking file shows Actual only where an input leg's purchase month is\n"
          "already past, and every value it shows EQUALS the expected value. That is why\n"
          "the two snapshots in data/cache/lgm/ prove nothing on their own.\n")
    ry = 2026
    files = sorted(B.history_files(ry))
    if not files:
        print("  (nothing harvested)")
        return
    for tag, path in (("first file of the year", files[0]),
                      ("last file harvested", files[-1])):
        text = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
        rows = B.parse_gross_margin(text)
        n_e = sum(1 for r in rows for v in r.expected if v is not None)
        n_a = sum(1 for r in rows for v in r.actual if v is not None)
        same = sum(1 for r in rows for e, a in zip(r.expected, r.actual)
                   if a is not None and e == a)
        print(f"  RY{ry} {tag:<24} {path.name.split('_')[4]}: "
              f"{len(rows):>5} rows  expected cells {n_e:>6}  actual cells {n_a:>6}  "
              f"of which equal to expected {same:>6}")

    print("\nAfter merging EVERY published file for a reinsurance year the actuals are real\n"
          "and they differ from the guarantee:")
    for ry in WINDOW:
        merged = B.load_history(ry)
        if not merged:
            continue
        settled = [v for v in merged.values() if v.settled]
        diff = [abs(a - e) for v in settled
                for e, a in zip(v.expected, v.actual) if e is not None and a is not None]
        print(f"  RY{ry}: {len(settled):>6} settled keys, "
              f"mean |actual - expected| = {np.mean(diff):.3f} "
              f"(zero would mean the column is a copy)")


# ---------------------------------------------------------------------------
# 3. Structure and the observation count
# ---------------------------------------------------------------------------

def section_structure() -> None:
    _rule("3. THE MARKETING-MONTH BUNDLE, AND WHAT AN OBSERVATION IS")
    print("Insurable months, straight out of the ADM (month 1 is never insured):")
    for cc, months in sorted(lgm.INSURED_MONTHS.items()):
        print(f"  {lgm.COMMODITY_NAMES[cc]:<14} months {months[0]}..{months[-1]} "
              f"({len(months)} insurable)")
    print("\nA backtest that assumed ONE month would be unpooled, and unpooled LGM is\n"
          "unsubsidised at every deductible. The neutral plan used here is equal target\n"
          "marketings in every insurable month.\n")

    raw = 0
    for ry in WINDOW:
        merged = B.load_history(ry)
        national, n_states = B.collapse_states(merged)
        settled = sum(1 for v in national.values() if v.settled)
        raw += len(merged)
        print(f"  RY{ry}: {len(merged):>6} settled+unsettled state-level keys -> "
              f"{len(national):>5} national ({n_states} states collapsed), "
              f"{settled:>4} settled")

    print("\nThen the two time collapses:")
    periods: list[B.SettledPeriod] = []
    for ry in WINDOW:
        periods.extend(B.settled_periods(ry))
    monthly = B.one_per_sales_month(periods)
    indep = B.independent_blocks(monthly)
    by_ct = collections.Counter(p.commodity_type for p in periods)
    mo_ct = collections.Counter(p.commodity_type for p in monthly)
    in_ct = collections.Counter(p.commodity_type for p in indep)
    print(f"  {'commodity / type':<38} {'weekly':>8} {'monthly':>8} {'independent':>12}")
    for k in sorted(by_ct):
        print(f"  {_label(*k):<38} {by_ct[k]:>8} {mo_ct[k]:>8} {in_ct[k]:>12}")
    print("\nRead every number in section 4 against the last column.")


# ---------------------------------------------------------------------------
# 4. The measured ladder
# ---------------------------------------------------------------------------

def _run():
    return B.run(list(WINDOW))


def section_ladder(bt=None) -> None:
    _rule("4. THE MEASURED LADDER vs THE FORWARD-LOOKING ONE")
    bt = bt or _run()
    print(f"{len(bt.periods)} settled monthly periods priced, "
          f"{len(bt.skipped_no_draws)} skipped for want of a harvested draw member.\n")
    print(f"{'commodity / type':<38} {'forward':>8} {'measured':>9} {'measured':>9} "
          f"{'LR at':>7} {'per prod $':>11}")
    print(f"{'':<38} {'(rated)':>8} {'net $':>9} {'per prod$':>9} {'forward':>7} "
          f"{'at forward':>11}")
    for k in sorted({p.commodity_type for p in bt.periods}):
        rungs = bt.ladder(*k)
        fwd = FORWARD_OPTIMUM[k]
        at_fwd = next(r for r in rungs if abs(r.deductible - fwd) < 1e-9)
        if B.is_degenerate(rungs):
            print(f"  {_label(*k):<36} {fwd:>8g} {'none':>9} {'none':>9} "
                  f"{at_fwd.loss_ratio:>7.2f} {at_fwd.return_per_producer_dollar:>11.2f}"
                  "   NO RUNG PAID")
            continue
        bn = B.best_rung(rungs, "net")
        bp = B.best_rung(rungs, "per_dollar")
        print(f"  {_label(*k):<36} {fwd:>8g} {bn.deductible:>9g} {bp.deductible:>9g} "
              f"{at_fwd.loss_ratio:>7.2f} {at_fwd.return_per_producer_dollar:>11.2f}")

    print("\nFull ladders:")
    for k in sorted({p.commodity_type for p in bt.periods}):
        rungs = bt.ladder(*k)
        n = sum(1 for p in bt.periods if p.commodity_type == k)
        print(f"\n{_label(*k)} — {n} monthly periods, "
              f"{bt.n_independent(*k)} non-overlapping")
        print(B.format_ladder(rungs, lgm.COMMODITY_UNIT.get(k[0], "unit")))

    print("\n\nBY REINSURANCE YEAR — does the optimum hold every year?")
    print(f"{'commodity / type':<38} " + " ".join(f"RY{y:>6}" for y in WINDOW))
    for k in sorted({p.commodity_type for p in bt.periods}):
        cells = []
        for ry in WINDOW:
            rungs = bt.ladder(*k, reinsurance_year=ry)
            if not rungs:
                cells.append("     --")
            elif B.is_degenerate(rungs):
                cells.append("  nopay")
            else:
                cells.append(f"{B.best_rung(rungs, 'net').deductible:>7g}")
        print(f"  {_label(*k):<36} " + " ".join(cells))
    print("\n'nopay' = no rung paid anything that year, so no rung is best.")

    print("\n\nWINDOW SENSITIVITY — the same ladder on three overlapping spans.")
    print("A conclusion that moves when a year is added or dropped is not a conclusion.")
    spans = [(2022, 2024), (2022, 2025), (2023, 2026), (2022, 2026)]
    runs = {s: (bt if s == (2022, 2026) else B.run(list(range(s[0], s[1] + 1))))
            for s in spans}
    print(f"{'commodity / type':<38} " + " ".join(f"{a}-{b}".rjust(10) for a, b in spans))
    for k in sorted({p.commodity_type for p in bt.periods}):
        cells = []
        for s in spans:
            rungs = runs[s].ladder(*k)
            cells.append("     nopay" if (not rungs or B.is_degenerate(rungs))
                         else f"{B.best_rung(rungs, 'net').deductible:>10g}")
        print(f"  {_label(*k):<36} " + " ".join(cells))

    print("\n\nTHE ASSUMPTION UNDER TEST: the rated model treats the loss ratio as CONSTANT")
    print("across the ladder (1/1.03 = 0.971 at every rung). Measured, it is not:")
    print(f"{'commodity / type':<38} {'LR at bottom':>13} {'LR at cap':>11} {'LR at top':>11}")
    for k in sorted({p.commodity_type for p in bt.periods}):
        rungs = bt.ladder(*k)
        cap = next((r for r in rungs if r.subsidy >= 0.4999), rungs[-1])
        print(f"  {_label(*k):<36} {rungs[0].loss_ratio:>13.3f} "
              f"{cap.loss_ratio:>11.3f} {rungs[-1].loss_ratio:>11.3f}")


# ---------------------------------------------------------------------------
# 5. Cross-check against the Summary of Business
# ---------------------------------------------------------------------------

def section_crosscheck(bt=None) -> None:
    _rule("5. CROSS-CHECK — reconstruction vs RMA's own Summary of Business")
    bt = bt or _run()
    print("sobtpu reports plan-82 loss ratios blended over the deductibles producers\n"
          "actually elected, so the check is whether SoB's number falls inside the range\n"
          "this reconstruction produces across the ladder. It is not an identity: the\n"
          "windows differ (SoB crop years 2021-2024, here RY2022-RY2026) and the\n"
          "reconstruction holds the marketing plan fixed.\n")
    print(f"{'commodity':<16} {'SoB 2021-24':>12} {'measured range across the ladder':>36}")
    for cc in sorted(SOB_LOSS_RATIO):
        lrs = [r.loss_ratio for k in {p.commodity_type for p in bt.periods}
               if k[0] == cc for r in bt.ladder(*k)]
        if not lrs:
            continue
        inside = min(lrs) <= SOB_LOSS_RATIO[cc] <= max(lrs)
        print(f"{lgm.COMMODITY_NAMES[cc]:<16} {SOB_LOSS_RATIO[cc]:>12.2f} "
              f"{min(lrs):>16.3f} .. {max(lrs):<16.3f}"
              f"{'  inside' if inside else '  OUTSIDE'}")

    print("\nDraw-assembly check — mean of RMA's 500 published draws against RMA's own")
    print("published expected margin, per settled period:")
    gaps = []
    for p in bt.periods:
        d = B.load_draws(p)
        if d is not None:
            gaps.append(B.validate_draws(p, d))
    if gaps:
        print(f"  {len(gaps)} periods: median {np.median(gaps) * 100:.3f}%, "
              f"90th pct {np.percentile(gaps, 90) * 100:.2f}%, "
              f"max {max(gaps) * 100:.2f}%")


SECTIONS = {"archive": section_archive, "actuals": section_actuals,
            "structure": section_structure, "ladder": section_ladder,
            "crosscheck": section_crosscheck}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=sorted(SECTIONS), action="append")
    args = ap.parse_args(argv)
    want = args.only or list(SECTIONS)
    bt = _run() if ({"ladder", "crosscheck"} & set(want)) else None
    for name in SECTIONS:
        if name in want:
            SECTIONS[name](bt) if name in ("ladder", "crosscheck") else SECTIONS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
