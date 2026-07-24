"""Orchestrator CLI — run connectors, upsert into the catalog, optionally export.

Usage:
  python -m src.refresh --source all --year 2026 --states IA,IL,NE,MN,IN --export
  python -m src.refresh --source rma_aip_listing,aip_sites
  python -m src.refresh --source rma_adm --force        # opt-in heavy ADM download
  python -m src.refresh --export-only                   # just rebuild the xlsx from the DB
  python -m src.refresh --enrich                        # doc-url enrichment only (no connectors)

--source accepts 'all' (every connector enabled in config.ini) or a comma list (runs those
regardless of the config toggle, so you can spot-run one source).

After the connectors run, the doc-url enrichment stage (src/enrich.py) fills missing
crops/states/peril/coverage from each product's brochure or detail page; --no-enrich skips it.
"""
from __future__ import annotations

import argparse
import sys

from . import config, db, enrich, export_xlsx, http
from .connectors.aip_sites.base import AipSites
from .connectors.base import Context
from .connectors.manual_seed import ManualSeed
from .connectors.rma_adm import RmaAdm
from .connectors.rma_aip_listing import RmaAipListing
from .connectors.rma_plans import RmaPlans
from .connectors.serff import Serff

# name -> connector factory. Order = run order (AIPs first so private products can link to them).
REGISTRY = {
    "rma_aip_listing": RmaAipListing,
    "rma_plans": RmaPlans,
    "rma_adm": RmaAdm,
    "serff": Serff,
    "aip_sites": AipSites,
    "manual_seed": ManualSeed,
}


def _selected_sources(arg: str | None, cfg: config.Config) -> list[str]:
    if not arg or arg == "all":
        # config order-independent; use REGISTRY order, filtered by config toggles.
        return [n for n in REGISTRY if cfg.source_enabled(n)]
    names = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        sys.exit(f"Unknown source(s): {', '.join(unknown)}. Known: {', '.join(REGISTRY)}")
    # Preserve REGISTRY run order even if user lists them out of order.
    return [n for n in REGISTRY if n in names]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresh the AIP private-products catalog.")
    ap.add_argument("--source", default="all",
                    help="'all' or comma list: " + ", ".join(REGISTRY))
    ap.add_argument("--year", type=int, help="Reinsurance/crop year (default from config.ini).")
    ap.add_argument("--states", help="Comma list of state codes for SERFF (default from config).")
    ap.add_argument("--force", action="store_true",
                    help="Bypass URL cache freshness; required for the heavy rma_adm download.")
    ap.add_argument("--export", action="store_true", help="Write an xlsx after refreshing.")
    ap.add_argument("--export-only", action="store_true",
                    help="Skip connectors; just rebuild the xlsx from the current DB.")
    ap.add_argument("--enrich", action="store_true",
                    help="Skip connectors; run the doc-url enrichment stage standalone.")
    ap.add_argument("--no-enrich", action="store_true",
                    help="Skip the automatic enrichment pass after connectors run.")
    ap.add_argument("--db", help="Override DB path (for tests).")
    args = ap.parse_args(argv)

    cfg = config.load()
    year = args.year or cfg.reinsurance_year
    states = [s.strip().upper() for s in args.states.split(",")] if args.states else cfg.serff_states

    conn = db.connect(args.db)
    db.init_db(conn)

    coverage: list[str] = []
    if not args.export_only:
        client = http.Client(cfg, conn)
        n_products = 0
        if args.enrich:
            print("Enrich-only run (no connectors).\n")
        else:
            ctx = Context(cfg=cfg, conn=conn, client=client, force=args.force, year=year,
                          states=states)
            sources = _selected_sources(args.source, cfg)
            print(f"Refresh: sources={sources} year={year} states={states} force={args.force}\n")
            for name in sources:
                connector = REGISTRY[name]()
                print(f"  running {name} ...")
                result = connector.run(ctx)
                coverage.extend(result.coverage)
                n_products += len(result.products)

        # Enrichment: standalone via --enrich, or automatically after a refresh that
        # returned products (new or changed) unless --no-enrich.
        if args.enrich or (n_products and not args.no_enrich):
            print("  running enrich (doc-url documents) ...")
            stats = enrich.run(conn, client, cfg, force=args.force)
            coverage.extend(stats.coverage_lines())

        print("\n=== Coverage report ===")
        for line in coverage:
            print("  " + line)

    if args.export or args.export_only:
        out = export_xlsx.build_workbook(conn, coverage_lines=coverage)
        print(f"\nExported: {out}")

    # Always print a short DB summary so the user sees the catalog size.
    n_prod = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    n_aip = conn.execute("SELECT COUNT(*) FROM aips").fetchone()[0]
    print(f"\nCatalog: {n_prod} products, {n_aip} AIPs  ({config.DB_PATH})")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
