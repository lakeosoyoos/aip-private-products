#!/usr/bin/env python3
"""Rebuild lrp_gap_history.csv after the producer-premium correction.

Every row in the history was recorded while lrp_signal treated RMA's `cost_per_cwt_amount`
(the TOTAL premium) as the producer's share, so `producer_prem` holds the gross figure and
`gap` = cme_put - producer_prem is understated by the whole subsidy — 1.54x too much
premium at 95-100% coverage, rising to 2.22x at 75%.

The fix is an EXACT transformation, not a re-pricing:

    producer_prem_correct = producer_prem_recorded * (1 - subsidy(coverage_level))
    gap                   = cme_put - producer_prem_correct
    gap_pct               = gap / coverage_price

`cme_put` is a Black-76 price in F, the strike (RMA's coverage_price), tenor and vol —
none of which the premium bug touched — so it carries over untouched and no futures curve
needs refetching. `F`, `coverage_price` and `source` likewise carry over.

NOT rebuilt: the fine coverage levels (0.875, 0.925, 0.96-0.99). The old COVERAGE_LEVELS
list never requested them, so RMA's rate file has them but the history has no F or vol
recorded for those cells. They populate going forward rather than being back-invented here.

    .venv/bin/python scripts/rebuild_gap_history.py [--dry-run]

Writes a .bak alongside the original before touching it.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import lrp_signal as L  # noqa: E402

HIST = Path(L.GAP_HISTORY_FILE)


def rebuild(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    out = df.copy()
    subsidy = out["coverage_level"].map(L.get_subsidy_rate)
    if subsidy.isna().any():
        bad = sorted(out.loc[subsidy.isna(), "coverage_level"].unique())
        sys.exit(f"REFUSING: no subsidy rate for coverage levels {bad}")

    gross = out["producer_prem"].astype(float)
    out["producer_prem"] = (gross * (1 - subsidy)).round(4)
    out["gap"] = (out["cme_put"].astype(float) - out["producer_prem"]).round(4)
    # PERCENT, matching build_grid's `round(gap_pct * 100, 3)`. Writing a FRACTION
    # here is what silently inflated every richness value by 100x: the ratio compares
    # this column against build_grid's, and both numbers look plausible alone.
    out["gap_pct"] = (out["gap"] / out["coverage_price"].astype(float) * 100).round(3)

    stats = {
        "rows": len(out),
        "prem_before": float(gross.mean()),
        "prem_after": float(out["producer_prem"].mean()),
        "gap_before": float(df["gap"].astype(float).mean()),
        "gap_after": float(out["gap"].mean()),
        "pos_before": int((df["gap"].astype(float) > 0).sum()),
        "pos_after": int((out["gap"] > 0).sum()),
    }
    return out, stats


def migrate_cache(dry_run: bool) -> dict:
    """Fix the day caches, which store the PARSED frame and so bypass the parser fix.

    fetch_lrp() writes lrp_cache/lrp_<commodity>_<date>.csv from the already-parsed
    DataFrame and returns it verbatim on a hit — so every cached day still carries
    producer_prem == actuarial_prem (the gross). Deleting the cache is not an option:
    RMA does not serve arbitrary past sales days, so those files are the only copy.

    Idempotent: a file whose producer_prem is already below actuarial_prem is left alone.
    """
    cache = Path(L.CACHE_DIR)
    fixed = skipped = 0
    for f in sorted(cache.glob("lrp_*.csv")):
        d = pd.read_csv(f)
        if not {"producer_prem", "actuarial_prem", "coverage_level"} <= set(d.columns):
            skipped += 1
            continue
        # Contaminated iff the producer's share is essentially the total. Compare on the
        # RATIO, not row-wise inequality: the cache rounds producer_prem to 3 decimals
        # while actuarial_prem keeps full precision, so an exact >= test fails on
        # whichever rows happened to round down and wrongly reports the file clean.
        # Correct data puts the producer at 45-65% of the total, so a median ratio
        # above 0.9 is unambiguous contamination.
        ratio = (d["producer_prem"] / d["actuarial_prem"]).median()
        if ratio < 0.9:
            skipped += 1
            continue
        subsidy = d["coverage_level"].map(L.get_subsidy_rate)
        d["producer_prem"] = (d["actuarial_prem"] * (1 - subsidy)).round(6)
        if not dry_run:
            d.to_csv(f, index=False)
        fixed += 1
    return {"fixed": fixed, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="report the effect without writing")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the history even though it already has been")
    args = ap.parse_args()

    c = migrate_cache(args.dry_run)
    print(f"day caches           : {c['fixed']} migrated, {c['skipped']} already clean\n")

    if not HIST.exists():
        sys.exit(f"no history file at {HIST}")
    # The correction is NOT idempotent -- running it twice would subtract the subsidy
    # from an already-net premium. The .bak is the marker that it has already run.
    bak = HIST.with_suffix(".csv.bak")
    if bak.exists() and not args.force:
        print(f"history already rebuilt ({bak.name} exists) — skipping.\n"
              f"Pass --force to redo it from scratch (restore {bak.name} over "
              f"{HIST.name} first, or you will double-correct).")
        return 0
    df = pd.read_csv(HIST)
    out, s = rebuild(df)

    print(f"rows                : {s['rows']:,}")
    print(f"mean producer premium: ${s['prem_before']:.4f} -> ${s['prem_after']:.4f}/cwt")
    print(f"mean gap             : ${s['gap_before']:+.4f} -> ${s['gap_after']:+.4f}/cwt")
    print(f"cells where LRP wins : {s['pos_before']:,} -> {s['pos_after']:,} "
          f"of {s['rows']:,} ({s['pos_before']/s['rows']:.0%} -> {s['pos_after']/s['rows']:.0%})")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    bak = HIST.with_suffix(".csv.bak")
    shutil.copy2(HIST, bak)
    out.to_csv(HIST, index=False)
    print(f"\nwrote {HIST}  (original preserved at {bak.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
