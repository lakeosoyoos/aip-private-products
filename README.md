---
title: AIP Crop-Insurance Catalog
emoji: 🌾
colorFrom: green
colorTo: blue
sdk: streamlit
sdk_version: 1.60.0
app_file: streamlit_app.py
pinned: false
---

# AIP Private Products Catalog (row-crop crop insurance)

A repeatable tool that catalogs the "private" products Approved Insurance Providers (AIPs) offer in
**row-crop** crop insurance, into a SQLite database with an Excel export.

There is no single registry of these products, because "private" means two very different things:

| Bucket | What it is | Where it lives | AIP-specific? |
|--------|------------|----------------|----------------|
| **`508h`** | Privately-developed / 508(h) plans approved by the FCIC Board and sold *inside* the federal program (reinsured) — Margin Protection, STAX, SCO/ECO, HIP-WI, PACE, WFRP… | RMA Actuarial Data Master + published lists | **No** — once approved, *every* AIP may offer them. Shared reference. |
| **`private`** | Truly private products sold *outside* the federal program (not reinsured) — crop-hail, named-peril, wind, replant, supplemental/gap, price modifiers | State **SERFF** filings + each AIP's own website | **Yes** — the menu genuinely varies by company. |

The tool treats these honestly: the federal side is a shared, source-cited reference; the private
side is scraped per-AIP and per-state and its **Coverage** report always states what is and isn't
yet wired, so a partial pull is never mistaken for "complete."

## Install

```bash
cd aip_products
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Use

```bash
# Full refresh (all enabled sources) + Excel export
python -m src.refresh --source all --states IA,IL,NE,MN,IN --export

# One source at a time
python -m src.refresh --source rma_aip_listing        # the ~12 AIPs (live RMA API)
python -m src.refresh --source rma_plans              # federal 508(h) reference (curated)
python -m src.refresh --source aip_sites              # AIP-website private products
python -m src.refresh --source serff --states IA      # SERFF reachability (see Status below)

# Just rebuild the spreadsheet from the current database
python -m src.refresh --export-only

# Opt-in: download + introspect the full Actuarial Data Master (~900 MB/year)
python -m src.refresh --source rma_adm --force
```

Output: `data/catalog.db` (source of truth) and `output/aip_products_YYYYMMDD.xlsx`
(Products / AIPs / Coverage sheets). Config lives in `config.ini`.

## Sources & status

| Connector | Source | Status |
|-----------|--------|--------|
| `rma_aip_listing` | `public-rma.fpac.usda.gov/Api/AIP/v1/...` (live JSON) | ✅ complete — all 12 AIPs |
| `rma_plans` | Curated 508(h)/federal-supplemental reference (`data/seed/federal_private_plans.csv`) | ✅ 16 plans, **all verified against primary sources** (RMA 508(h) developer list, M13 plan-code exhibit, CRS R43494); `program` distinguishes true 508(h) from statutory farm-bill products |
| `aip_sites` | Per-AIP websites | ✅ **11 of 12 AIPs wired** (124 products). Custom parsers where needed: accordions (Rain & Hail), card grids (FMH, ProAg, Great American), SPA content fragments (RCIS). Brand mappings researched: RH→rainhail.com, WN→agrisompo.com (ARMtech rebrand), FA→AFBIS, CP→Precision Risk Management, PS→palomarcrop.com |
| `manual_seed` | Hand-verified rows for bot-walled sites (`data/seed/private_products_manual.csv`) | ✅ COUNTRY Financial (CM): 7 products browser-verified — countryfinancial.com blocks all automated fetch (Cloudflare TLS fingerprinting) |
| `serff` | State SERFF Filing Access (TOI 02.1 Crop) | ✅ **2,323 filings, 5 states (IA/IL/NE/MN/IN)** in the `serff_filings` table + "SERFF Filings" xlsx sheet. Two-piece design: `src/connectors/serff_browser.py` (Playwright) extracts per-state JSON payloads to `data/cache/serff/` (run manually — the portal WAF challenges sustained automation; the extractor stops at any bot challenge, never bypasses); the `serff` connector imports payloads during refresh. Dates present for 255 IA filings (details phase); other states are search-grain. To add a state: `.venv/bin/python -m src.connectors.serff_browser --state XX --no-details` |
| `rma_adm` | Actuarial Data Master (county availability) | ✅ **41,883 county×crop rows, RY 2026** in `product_counties` — federal plans at true county grain (SCO/ECO 2,804 counties × 16 crops; MP, STAX, HIP-WI, PACE, MCO, WFRP). Range-reads only ~54 MB of the 2.7 GB ADM zip. Verified exactly against RMA's Actuarial Information Browser + Summary of Business (all 24,471 sold combos present). Yearly refresh: `.venv/bin/python -m src.refresh --source rma_adm --force --no-enrich` |

**Interactive map** (`src/webmap.py` → `output/product_map.html`): self-contained offline HTML —
zoom US → state → counties, filter by crop / AIP / subsidy; private products shade at their true
state grain (badged "statewide"), federal products at ADM county grain. Regenerate after any
refresh with `.venv/bin/python -m src.webmap`.

The xlsx includes a **Stack** sheet (`src/stack.py`): a coverage-stack analysis that classifies
every product into layers — base MPCI → subsidized federal bands (SCO/ECO/MCO/STAX) → unsubsidized
private bands/buy-ups → standalone named-peril → utility endorsements — with an AIP × layer matrix
and a federal-band-vs-private-analog comparison (the subsidy decision). Classification is
rule-based (`stack.classify`, unit-tested); unmatched products stay in 'other' rather than being
forced.

Current catalog: **147 products** — 16 federal (all-AIP) + 131 private across all 12 AIPs — plus
**2,323 SERFF filings** (filing grain). Enrichment (`src/enrich.py`, auto after refresh or
`--enrich`): fills crops/states/peril/coverage from each product's doc_url (pypdf/BeautifulSoup,
deterministic keyword matching only) — private products with crops 20→69, with states 0→36
explicit + 15 nationwide; 30 RCIS products unenrichable (JS-only doc pages), 21 docs name no
crop/state (left empty on purpose).

## Web app (Streamlit / Hugging Face Spaces)

A passcode-gated Streamlit app (`streamlit_app.py`) presents the catalog as five
tabs — **Map** (the full interactive map, embedded), **Products** (filterable
table + CSV download), **Stack** (the coverage-stack analysis), **SERFF Filings**
(the 2,323 filing-grain records), and **About** (provenance, counts, xlsx
download). It imports the pipeline modules read-only; it runs none of the
scrapers, so its runtime deps are just `streamlit` + `pandas` (`requirements.txt`;
the full pipeline deps are in `requirements-pipeline.txt`).

```bash
# local run (create .streamlit/secrets.toml from the .example first)
.venv/bin/streamlit run streamlit_app.py
```

The gate reads the passcode from Streamlit secrets (`app_passcode`, or a
`[passcodes]` table) with an `APP_PASSCODE` env-var fallback — never hardcoded.
See **DEPLOY_HF.md** for the Hugging Face Spaces deploy steps and how to restrict
access to specific people.

## Extending

- **Add an AIP website adapter:** create `src/connectors/aip_sites/<aip>.py` subclassing
  `SiteAdapter` (set `aip_name`, `aip_code`, `product_pages`), and append an instance to `ADAPTERS`.
  The default `parse()` pairs product-detail links to their headings by URL slug.
- **Add/verify a federal plan:** edit `data/seed/federal_private_plans.csv` (set `verified=1` once
  confirmed against a primary source).
- **Wire live SERFF:** implement `Serff.extract_with_browser()` with Playwright (accept disclaimer →
  Business Type = Property & Casualty → TOI → AIP legal-entity name → parse results).

## Tests

```bash
python -m pytest -q
```

All data pulled here is public. Requests use a polite delay and identify themselves; no credentials.
