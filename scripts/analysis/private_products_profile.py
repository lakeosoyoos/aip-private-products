"""Profile + economics for the PRIVATE (non-reinsured) side of the row-crop catalog.

Produces every number tagged [C] in docs/rowcrop_private_products.md. Read-only against
data/catalog_app.db; writes nothing but stdout.

    .venv/bin/python scripts/analysis/private_products_profile.py            # all sections
    .venv/bin/python scripts/analysis/private_products_profile.py --only economics

Sections
--------
catalog      shape of the private bucket: AIP x layer, peril, coverage type, source/verification
geography    state and crop reach of private products
serff        what the 11,287 state filings can and cannot tell us (the knowability matrix)
economics    the central comparison: expected indemnity per PRODUCER dollar,
             federal (subsidized) vs private (market-priced)
band         AIP-by-AIP private analogs of each federal supplemental band

The economics section is the point of the file. It is arithmetic, not estimation:

    federal:  E[indemnity] / producer_premium  =  TLR / (1 - subsidy_share)
    private:  E[indemnity] / producer_premium  =  TLR_private        (subsidy_share = 0)

where TLR is the target loss ratio the rate is built to. FCIC's statutory target is 1.0
(7 U.S.C. 1506(n)); a private carrier's target is 1 / (1 + expense & profit load), which is
below 1 by construction. Everything else in the doc follows from that one asymmetry.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.stack import LAYERS, classify  # noqa: E402

DB = ROOT / "data" / "catalog_app.db"

# Private crop-hail / named-peril loss-ratio band. NOT computed here — the industry series is
# not in this database. Sourced in the doc (Insurance Information Institute's archived NCIS
# crop-hail tables, loss ratios 44-122 over 2004-2015). Used only to bracket the private side.
PRIVATE_TLR_LOW, PRIVATE_TLR_HIGH = 0.55, 0.80
FCIC_TARGET_LOSS_RATIO = 1.00  # 7 U.S.C. 1506(n)


def conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def rule(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def private_rows(c):
    rows = []
    for r in c.execute(
        "SELECT p.*, a.name AS aip_name,"
        " (SELECT GROUP_CONCAT(crop, '; ') FROM product_crops WHERE product_id=p.product_id) crops,"
        " (SELECT GROUP_CONCAT(state, '; ') FROM product_states WHERE product_id=p.product_id) sts"
        " FROM products p LEFT JOIN aips a ON a.aip_code=p.aip_code WHERE p.bucket='private'"
    ):
        d = dict(r)
        d["layer"], d["analog"] = classify(
            d["name"], d["bucket"], d["program"], d["peril_type"], d["coverage_type"])
        rows.append(d)
    return rows


# --------------------------------------------------------------------------- catalog
def sec_catalog(c):
    rule("1. CATALOG SHAPE")
    for r in c.execute("SELECT bucket, program, COUNT(*) n FROM products GROUP BY 1,2 ORDER BY 3 DESC"):
        print(f"  {r['bucket']:8s} {r['program']:22s} {r['n']:4d}")

    rows = private_rows(c)
    labels = {k: lbl for k, lbl, _, _ in LAYERS}

    print("\n  Private products by stack layer (src/stack.py classify()):")
    for k, lbl, sub, _ in LAYERS:
        n = sum(1 for r in rows if r["layer"] == k)
        if n:
            print(f"    {lbl:34s} {n:4d}   subsidized: {sub}")

    print("\n  AIP x layer (private bucket only):")
    keys = ["named_peril", "private_band", "endorsement", "other"]
    print(f"    {'AIP':46s} " + " ".join(f"{k[:12]:>12s}" for k in keys) + "   total")
    for code, name in sorted({(r["aip_code"], r["aip_name"]) for r in rows}, key=lambda t: -sum(
            1 for r in rows if r["aip_code"] == t[0])):
        cnt = Counter(r["layer"] for r in rows if r["aip_code"] == code)
        print(f"    {(name or '?')[:44]:46s} " + " ".join(f"{cnt.get(k, 0):12d}" for k in keys)
              + f" {sum(cnt.values()):7d}")

    for field in ("peril_type", "coverage_type"):
        print(f"\n  Private by {field}:")
        cnt = Counter((r[field] or "(unclassified)") for r in rows)
        for k, n in cnt.most_common():
            print(f"    {n:4d}  {k}")

    print("\n  Provenance / verification of the private bucket:")
    for r in c.execute(
        "SELECT source_type, verified, COUNT(*) n FROM products WHERE bucket='private'"
        " GROUP BY 1,2 ORDER BY 3 DESC"
    ):
        print(f"    {r['n']:4d}  source_type={r['source_type']:18s} verified={r['verified']}")
    v = c.execute("SELECT COUNT(*) FROM products WHERE bucket='private' AND verified=1").fetchone()[0]
    print(f"    -> {v}/{len(rows)} private rows carry verified=1 "
          f"({100*v/len(rows):.1f}%). Everything else is a MENU ENTRY, not a term sheet.")


# --------------------------------------------------------------------------- geography
def sec_geography(c):
    rule("2. GEOGRAPHY AND CROPS")
    n_state = c.execute(
        "SELECT COUNT(DISTINCT product_id) FROM product_states ps JOIN products p USING(product_id)"
        " WHERE p.bucket='private'").fetchone()[0]
    n_crop = c.execute(
        "SELECT COUNT(DISTINCT product_id) FROM product_crops pc JOIN products p USING(product_id)"
        " WHERE p.bucket='private'").fetchone()[0]
    n_cty = c.execute(
        "SELECT COUNT(*) FROM product_counties pc JOIN products p USING(product_id)"
        " WHERE p.bucket='private'").fetchone()[0]
    print(f"  private products with >=1 state row : {n_state} / 166")
    print(f"  private products with >=1 crop row  : {n_crop} / 166")
    print(f"  private products with county rows   : {n_cty}  (by design: private filings are statewide)")

    print("\n  Private product count by state (top 20):")
    for r in c.execute(
        "SELECT ps.state, COUNT(*) n FROM product_states ps JOIN products p USING(product_id)"
        " WHERE p.bucket='private' GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ):
        print(f"    {r['state']}  {r['n']:3d}")

    print("\n  Crops named on private products (top 15):")
    for r in c.execute(
        "SELECT pc.crop, COUNT(*) n FROM product_crops pc JOIN products p USING(product_id)"
        " WHERE p.bucket='private' GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
    ):
        print(f"    {r['n']:3d}  {r['crop']}")


# --------------------------------------------------------------------------- serff
def sec_serff(c):
    rule("3. SERFF — THE KNOWABILITY MATRIX")
    tot = c.execute("SELECT COUNT(*) FROM serff_filings").fetchone()[0]
    sts = c.execute("SELECT COUNT(DISTINCT state) FROM serff_filings").fetchone()[0]
    print(f"  {tot} filings across {sts} states.\n")
    print(f"  {'ST':4s} {'filings':>8s} {'rate-bearing':>13s} {'rate%':>6s} {'AIPs':>5s} {'dated':>6s}")
    agg = [0, 0, 0]
    for r in c.execute("""
        SELECT state, COUNT(*) n,
               SUM(CASE WHEN filing_type LIKE '%Rate%' OR filing_type LIKE '%Loss Cost%'
                        THEN 1 ELSE 0 END) rate_n,
               SUM(CASE WHEN submission_date IS NOT NULL THEN 1 ELSE 0 END) dated_n,
               COUNT(DISTINCT aip_code) aips
        FROM serff_filings GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"  {r['state']:4s} {r['n']:8d} {r['rate_n']:13d} {100*r['rate_n']/r['n']:5.0f}% "
              f"{r['aips']:5d} {r['dated_n']:6d}")
        agg[0] += r["n"]; agg[1] += r["rate_n"]; agg[2] += r["dated_n"]
    print(f"  {'ALL':4s} {agg[0]:8d} {agg[1]:13d} {100*agg[1]/agg[0]:5.0f}% "
          f"{'':5s} {agg[2]:6d}")

    print("\n  Sub-TOI split (what kind of private crop coverage the filing is):")
    for r in c.execute("SELECT COALESCE(sub_toi,'(none)') s, COUNT(*) n FROM serff_filings"
                       " GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {r['n']:6d}  {r['s']}")

    print("\n  Filings per AIP (regulatory footprint, not product count):")
    for r in c.execute("SELECT COALESCE(aip_code,'(none)') a, COUNT(*) n FROM serff_filings"
                       " GROUP BY 1 ORDER BY 2 DESC"):
        prods = c.execute("SELECT COUNT(*) FROM products WHERE bucket='private' AND aip_code=?",
                          (r["a"],)).fetchone()[0]
        print(f"    {r['a']:6s} filings={r['n']:5d}  catalog products={prods:3d}")

    serff_states = {r[0] for r in c.execute("SELECT DISTINCT state FROM serff_filings")}
    prod_states = {r[0] for r in c.execute(
        "SELECT DISTINCT state FROM product_states ps JOIN products p USING(product_id)"
        " WHERE p.bucket='private'")}
    print(f"\n  States where private products are SOLD but no filings are loaded "
          f"({len(prod_states - serff_states)}):")
    print("    " + ", ".join(sorted(prod_states - serff_states)))


# --------------------------------------------------------------------------- economics
def sec_economics(c):
    rule("4. THE CENTRAL ECONOMIC ASYMMETRY")
    print("""
  Identity (no estimation):

      E[indemnity] / producer_premium = TLR / (1 - subsidy_share)

  For a FEDERAL product the producer pays (1 - s) of the gross premium and the AIP's delivery
  expense is reimbursed SEPARATELY by FCIC (A&O), so the whole gross premium is available to
  pay losses. For a PRIVATE product s = 0 AND the expense load comes out of the same premium
  dollar, so TLR_private = 1 / (1 + expense&profit load) < 1 by construction.
""")
    print("  Federal supplemental bands, RY2026 sold book (computed from sob_sales):\n")
    print(f"  {'plan':11s} {'acres(M)':>9s} {'liab/ac':>8s} {'gross prem/ac':>14s} "
          f"{'subsidy':>8s} {'producer/ac':>12s} {'E[ind]/$prod':>13s}")
    for r in c.execute("""
        SELECT plan_abbrev, SUM(net_acres) a, SUM(liability) l,
               SUM(total_premium) p, SUM(subsidy) s
        FROM sob_sales GROUP BY 1 HAVING SUM(net_acres) > 100000 ORDER BY 2 DESC"""):
        a, l, p, s = r["a"], r["l"], r["p"], r["s"]
        share = s / p
        prod = p - s
        print(f"  {r['plan_abbrev']:11s} {a/1e6:9.2f} {l/a:8.0f} {p/a:14.2f} "
              f"{share:7.1%} {prod/a:12.2f} {FCIC_TARGET_LOSS_RATIO/(1-share):13.2f}x")

    print(f"\n  Same identity for a private product (s = 0, TLR "
          f"{PRIVATE_TLR_LOW:.2f}-{PRIVATE_TLR_HIGH:.2f}):")
    print(f"    E[indemnity] / producer dollar = {PRIVATE_TLR_LOW:.2f}x to "
          f"{PRIVATE_TLR_HIGH:.2f}x  -- BELOW 1 by construction.\n")

    # The headline ratio, on the largest band.
    r = c.execute("""SELECT SUM(net_acres) a, SUM(liability) l, SUM(total_premium) p,
                     SUM(subsidy) s FROM sob_sales WHERE plan_abbrev='ECO-RP' AND crop='Corn'
                  """).fetchone()
    share = r["s"] / r["p"]
    fed = FCIC_TARGET_LOSS_RATIO / (1 - share)
    print(f"  Headline (corn ECO-RP, the largest private-band analog):")
    print(f"    federal band : ${(r['p']-r['s'])/r['a']:.2f}/ac buys ${r['l']/r['a']:.0f}/ac of band; "
          f"E[ind]/$ = {fed:.2f}x")
    print(f"    private band : the SAME band must be sold at >= the gross ${r['p']/r['a']:.2f}/ac "
          f"(+load); E[ind]/$ = {PRIVATE_TLR_LOW:.2f}-{PRIVATE_TLR_HIGH:.2f}x")
    print(f"    ratio        : the federal band is {fed/PRIVATE_TLR_HIGH:.1f}x to "
          f"{fed/PRIVATE_TLR_LOW:.1f}x better per producer dollar.")
    print(f"    (at a realized federal loss ratio of 0.90 rather than the statutory 1.00 target,"
          f" the federal multiple is {0.90/(1-share):.2f}x -- still {0.90/(1-share)/PRIVATE_TLR_HIGH:.1f}x+"
          f" the private side.)")
    print(f"    price ratio  : a private carrier must charge >= {r['p']/(r['p']-r['s']):.1f}x "
          f"what the producer pays for the federal band, for the same protection.")

    print("\n  => A private product NEVER wins on expected value against a federal band that")
    print("     covers the same thing. It can only win where the federal band does not reach,")
    print("     or by reducing variance at a known, accepted cost.")


# --------------------------------------------------------------------------- band overlap
def sec_band(c):
    rule("5. PRIVATE ANALOGS OF FEDERAL BANDS (overlap map)")
    rows = [r for r in private_rows(c) if r["layer"] == "private_band"]
    by_analog = defaultdict(list)
    for r in rows:
        by_analog[r["analog"] or "(no federal analog — own band/price design)"].append(r)
    for analog in sorted(by_analog, key=lambda k: -len(by_analog[k])):
        rs = by_analog[analog]
        print(f"\n  federal analog: {analog}   ({len(rs)} private products, "
              f"{len({x['aip_code'] for x in rs})} AIPs)")
        for r in sorted(rs, key=lambda x: (x["aip_code"] or "", x["name"])):
            nst = len((r["sts"] or "").split("; ")) if r["sts"] else 0
            print(f"    [{r['aip_code']}] {r['name'][:44]:46s} states={nst:2d}  src={r['source_type']}")

    print("\n  Named-peril layer: perils covered that no federal row-crop plan names separately")
    cnt = Counter((r["peril_type"] or "(unclassified)")
                  for r in private_rows(c) if r["layer"] in ("named_peril", "endorsement"))
    for k, n in cnt.most_common():
        print(f"    {n:4d}  {k}")


# --------------------------------------------------------------------------- gap
def sec_gap(c):
    rule("6. WHAT THE FEDERAL STACK LEAVES ON THE TABLE")
    r = c.execute("""SELECT SUM(net_acres) a, SUM(liability) l FROM sob_sales
                     WHERE plan_abbrev='ECO-RP' AND crop='Corn'""").fetchone()
    band_liab = r["l"] / r["a"]
    # ECO-RP covers the 86%-95% area-revenue band = 9 points of the 100% expected revenue.
    implied_100 = band_liab / 0.09
    print(f"  ECO-RP corn band liability          : ${band_liab:.2f}/ac   [C]")
    print(f"  ECO band width                      : 86% -> 95% = 9 points of expected revenue")
    print(f"  => implied 100% expected revenue    : ${implied_100:.0f}/ac  [C, derived]")
    print(f"\n  {'coverage':>9s} {'guarantee/ac':>13s} {'deductible/ac':>14s} "
          f"{'covered by SCO+ECO':>19s} {'left over':>10s}")
    for cov in (0.70, 0.75, 0.80, 0.85):
        gtee = implied_100 * cov
        ded = implied_100 - gtee
        band = implied_100 * (0.95 - cov)   # SCO cov->86 plus ECO 86->95
        left = implied_100 * 0.05
        print(f"  {cov:9.0%} {gtee:13.0f} {ded:14.0f} {band:19.0f} {left:10.0f}")
    print("""
  BUT: SCO, ECO, MCO and STAX all settle on a COUNTY (area) index, not on the farm. A loss
  that does not move the county index pays zero no matter how big it is on one field. So the
  dollars in the table above are only reachable when the whole county is short.

  Unit-dilution arithmetic (the spot-loss hole), for an individual YP/RP unit of A acres at
  coverage level c, when a hailstorm totally destroys `a` acres and the rest is normal:

      unit yield ratio = (A - a) / A          MPCI pays only if (A - a)/A < c
      => the storm must take more than (1 - c) of the WHOLE UNIT to pay $1 federally.
""")
    print(f"  {'coverage':>9s} {'% of unit that must be destroyed before MPCI pays anything':>60s}")
    for cov in (0.70, 0.75, 0.80, 0.85):
        print(f"  {cov:9.0%} {1-cov:60.0%}")
    print("""
  On an enterprise unit (whole county, one crop) A is the entire planted acreage, so a storm
  that flattens 150 acres of a 1,000-acre enterprise unit at 80% coverage moves the unit yield
  to 85% -- above the 80% trigger -- and the federal indemnity is ZERO. Crop-hail pays on the
  150 damaged acres. This, not price, is the structural reason crop-hail survives.

  Break-even identity for any UNSUBSIDIZED cover (the honest version):

      premium         = LC x LCM          (LC = pure loss cost, LCM = expense+profit multiplier)
      E[indemnity]    = LC
      E[indemnity]/$  = 1 / LCM  < 1

  and because the standard crop-hail form carries NO PRO-RATA clause and MPCI's production to
  count is not reduced by a hail recovery, the two indemnities do not offset -- so the crop-hail
  payout IS the incremental recovery. Its expected value is still below its price. Buying it is
  a variance trade, not an expected-return trade. It is rational when:

      (a) the loss it covers is large relative to the operation's equity (concave utility), or
      (b) it unlocks something worth more than the load -- lender collateral, or the ability to
          forward-sell bushels that would otherwise have to be bought back after a spot loss.

  Both are real. Neither is 'a better deal than the federal policy'.
""")


SECTIONS = {"catalog": sec_catalog, "geography": sec_geography, "serff": sec_serff,
            "economics": sec_economics, "band": sec_band, "gap": sec_gap}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=sorted(SECTIONS), action="append")
    a = ap.parse_args()
    c = conn()
    for k in (a.only or list(SECTIONS)):
        SECTIONS[k](c)


if __name__ == "__main__":
    main()
