"""SQLite schema + connection helpers.

Raw sqlite3, no ORM (matches morgan_septic). DDL lives here as module string constants and is
applied idempotently by init_db(). The catalog is the tool's source of truth; the xlsx export is
just a view of it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
-- Approved Insurance Providers (from the live RMA AIP API).
CREATE TABLE IF NOT EXISTS aips (
    aip_code        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_company  TEXT,
    agreement_type  TEXT,
    reinsurance_year INTEGER,
    city            TEXT,
    state           TEXT,
    phone           TEXT,
    website         TEXT,
    source_url      TEXT,
    fetched_at      TEXT
);

-- One row per product. bucket = '508h' (privately-developed federal plan, offered by all AIPs)
-- or 'private' (truly private, non-reinsured, varies by AIP).
CREATE TABLE IF NOT EXISTS products (
    product_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket          TEXT NOT NULL,
    program         TEXT,              -- federal_508h | private_nonreinsured
    name            TEXT NOT NULL,
    aip_code        TEXT,              -- NULL for federal plans (all AIPs); set for private products
    developer       TEXT,              -- 508(h) submitter / developing company
    plan_code       TEXT,              -- RMA insurance plan code, when known
    peril_type      TEXT,              -- e.g. hail, wind, margin, revenue, multi-peril
    coverage_type   TEXT,              -- e.g. named-peril, supplemental, gap, area
    status          TEXT,
    effective_date  TEXT,
    source_type     TEXT NOT NULL,     -- rma_api | rma_plans_seed | serff | aip_site | rma_adm
    source_url      TEXT,
    doc_url         TEXT,              -- brochure / filing document
    filing_id       TEXT,              -- SERFF filing id, when applicable
    verified        INTEGER DEFAULT 0, -- 1 = attributes confirmed against a primary source
    notes           TEXT,
    raw             TEXT,              -- original JSON/text blob for provenance
    first_seen      TEXT,
    fetched_at      TEXT,
    -- Dedup key. A single column (not a multi-col UNIQUE) because SQLite treats NULLs as distinct,
    -- which would let rows with NULL plan_code/filing_id duplicate. Built by models.product_key().
    natural_key     TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS product_crops (
    product_id      INTEGER NOT NULL,
    crop            TEXT NOT NULL,
    PRIMARY KEY (product_id, crop),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS product_states (
    product_id      INTEGER NOT NULL,
    state           TEXT NOT NULL,
    PRIMARY KEY (product_id, state),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- County-grain availability (federal products only — private products are filed statewide, so
-- their grain is product_states). Populated by the rma_adm connector from ADM county lists.
CREATE TABLE IF NOT EXISTS product_counties (
    product_id      INTEGER NOT NULL,
    crop            TEXT NOT NULL,
    state           TEXT NOT NULL,     -- 2-letter code
    county_fips     TEXT NOT NULL,     -- 5-digit FIPS (state+county)
    county_name     TEXT,
    source          TEXT,              -- e.g. adm_2026
    PRIMARY KEY (product_id, crop, county_fips),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- PRF (Pasture, Rangeland, Forage — rainfall index, plan code 13) County Base Values: the RMA
-- per-acre dollar value by county that scales protection (acres x productivity factor x coverage
-- level x CBV). County-level (the rainfall index/rates are grid-level, but the CBV is by county).
-- Varies by intended use (Grazing vs Haying) and practice (Irrigated vs Non-Irrigated, and
-- organic where applicable). Populated by the prf_adm connector from the ADM. Drives the app's
-- PRF county heat map. NOT part of the row-crop private-products catalog — a companion dataset.
CREATE TABLE IF NOT EXISTS prf_county (
    year               INTEGER NOT NULL,
    state              TEXT NOT NULL,     -- 2-letter USPS
    county_fips        TEXT NOT NULL,     -- 5-digit FIPS
    county_name        TEXT,
    intended_use       TEXT NOT NULL,     -- Grazing | Haying
    irrigation_practice TEXT NOT NULL,    -- Irrigated | Non-Irrigated
    organic_practice   TEXT NOT NULL DEFAULT 'Conventional',  -- Conventional | Organic | Transitional
    county_base_value  REAL,              -- $/acre
    source             TEXT,              -- e.g. adm_2026
    fetched_at         TEXT,
    PRIMARY KEY (year, county_fips, intended_use, irrigation_practice, organic_practice)
);

-- Market reality (Summary of Business): which FEDERAL plans actually SOLD, WHERE, and HOW MUCH.
-- Populated by the rma_sob connector from RMA's public State/County/Crop-with-Coverage-Level file
-- (sobcov_<year>.zip), aggregated up from its coverage-level grain to one row per
-- year x state x county x crop x plan. Joins the catalog's federal products at query time via
-- products.plan_code (semicolon lists). The public file carries no AIP/company identifier, so this
-- is PLAN grain, not AIP grain (RMA does not publish AIP-identified SoB at this granularity).
-- net_acres = insured acres for the plan (base plans report in Net Reported Quantity, endorsements
-- like SCO/STAX/ECO/MCO in Endorsed/Companion Acres); the connector takes whichever applies.
CREATE TABLE IF NOT EXISTS sob_sales (
    year            INTEGER NOT NULL,
    state           TEXT NOT NULL,     -- 2-letter USPS
    county_fips     TEXT NOT NULL,     -- 5-digit FIPS (state+county)
    crop            TEXT NOT NULL,     -- canonical catalog crop (same names as product_crops)
    commodity_code  TEXT,              -- 4-digit RMA commodity code
    plan_code       TEXT NOT NULL,     -- 2-digit RMA insurance plan code
    plan_abbrev     TEXT,              -- e.g. SCO-RP, STAX-RP, ECO-YP
    net_acres       REAL,
    liability       REAL,
    total_premium   REAL,
    subsidy         REAL,
    indemnity       REAL,
    policies_sold   INTEGER,
    source          TEXT,              -- e.g. sobcov_2026
    fetched_at      TEXT,
    PRIMARY KEY (year, state, county_fips, crop, plan_code)
);

-- PRF optimizer sweep results (grid grain): the BEST allocations found by src/prfopt.py's
-- 59,536-policy enumeration, summarized per grid x use x coverage level. Metrics are stored
-- NORMALIZED per $1 of annual protection (win rate is scale-invariant; $/acre = value x
-- county CBV x coverage x productivity, applied at display time), so one grid row serves
-- every county the grid touches. combos/props are JSON. Populated by src/prfsweep.py.
CREATE TABLE IF NOT EXISTS prf_opt_best (
    grid_id         INTEGER NOT NULL,
    intended_use    TEXT NOT NULL,
    coverage_level  REAL NOT NULL,
    year_min        INTEGER, year_max INTEGER,
    n_policies      INTEGER,
    best_win_rate   REAL,               -- max win rate over all policies
    best_win_combo  TEXT, best_win_props TEXT, best_win_avg_net REAL,
    best_net        REAL,               -- max average net return (per $1 protection)
    best_net_combo  TEXT, best_net_props TEXT, best_net_win_rate REAL,
    median_net      REAL,
    pct_positive    REAL,               -- share of policies with positive avg net
    top_json        TEXT,               -- top-N policies by each metric, JSON
    source          TEXT, fetched_at TEXT,
    PRIMARY KEY (grid_id, intended_use, coverage_level)
);

-- Which counties each PRF grid touches (a grid can span several counties and vice versa).
-- From the PrfWebApi GetCountiesAndStatesFromGridId call or the ADM grid-keyed records.
CREATE TABLE IF NOT EXISTS prf_grid_county (
    grid_id         INTEGER NOT NULL,
    state           TEXT NOT NULL,
    county_fips     TEXT NOT NULL,
    county_name     TEXT,
    source          TEXT,
    PRIMARY KEY (grid_id, county_fips)
);

-- PRF historical rainfall index values (grid grain): one row per grid x sample year x
-- two-month index interval. index_value is the index as a decimal "percent of normal"
-- (1.000 = normal rainfall; the support tool displays 0.798 as 79.8%). An indemnity
-- triggers when the final index falls below the coverage level (e.g. < 0.90).
-- Populated by src/prfdata.py from RMA's PRF support tool web API
-- (public-rma.fpac.usda.gov/apps/PrfWebApi, PrfExternalIndexes/GetIndexValues); data run
-- 1948 -> present. Interval codes are the ADM A00480 abbreviations (JAN-FEB ... NOV-DEC).
CREATE TABLE IF NOT EXISTS prf_grid_index (
    grid_id         INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    interval_code   TEXT NOT NULL,     -- 'JAN-FEB' ... 'NOV-DEC' (11 overlapping intervals)
    index_value     REAL NOT NULL,     -- percent of normal, decimal (0.798 = 79.8%)
    source          TEXT,              -- e.g. prfwebapi
    fetched_at      TEXT,
    PRIMARY KEY (grid_id, year, interval_code)
);

-- PRF premium rates (grid grain): one row per grid x reinsurance year x intended use x
-- interval x coverage level. premium_rate is the unloaded rate applied to policy
-- protection (total premium = protection x rate). Populated by src/prfdata.py from the
-- PRF support tool web API (PrfExternalIntervalCodes/GetValidIntervalCodes); the same
-- numbers live in the ADM as A01130 Area Coverage Level (rc 05, keyed by grid) joined to
-- A01135 Area Rate via Area Rate ID (verified to match exactly for grid 27663).
CREATE TABLE IF NOT EXISTS prf_grid_rate (
    grid_id         INTEGER NOT NULL,
    year            INTEGER NOT NULL,  -- reinsurance year the rate applies to
    intended_use    TEXT NOT NULL,     -- Grazing | Haying | Haying-Irrigated
    interval_code   TEXT NOT NULL,     -- 'JAN-FEB' ... 'NOV-DEC'
    coverage_level  REAL NOT NULL,     -- 0.70 | 0.75 | 0.80 | 0.85 | 0.90
    premium_rate    REAL NOT NULL,
    source          TEXT,              -- e.g. prfwebapi_2026
    fetched_at      TEXT,
    PRIMARY KEY (grid_id, year, intended_use, interval_code, coverage_level)
);

-- Per-grid fingerprint of the prf_grid_index scoring window (2006-2024), so the monthly
-- update can re-score ONLY the grids whose index history actually moved. Written by
-- src/prfbulk.py after each bulk load / successful sweep; compared by prfbulk.changed_grids().
CREATE TABLE IF NOT EXISTS prf_index_hash (
    grid_id         INTEGER PRIMARY KEY,
    window_hash     TEXT,
    updated_at      TEXT
);

-- PRF premium subsidy schedule (national, plan 13): subsidy percent by coverage level.
-- From ADM A00070 Subsidy Percent (record category 04, plan 13, RY2026), cross-checked
-- against the support tool's SubsidyLevel. 0.65 is the CAT level (100% subsidized).
CREATE TABLE IF NOT EXISTS prf_subsidy (
    coverage_level  REAL PRIMARY KEY,
    subsidy_pct     REAL NOT NULL,
    source          TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER,
    url             TEXT NOT NULL,
    local_path      TEXT,
    sha256          TEXT,
    content_type    TEXT,
    fetched_at      TEXT,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- SERFF filing-level records (regulatory grain: one row per state filing, not per product —
-- an AIP re-files rates/forms yearly, so filings vastly outnumber products and get their own
-- table instead of swamping `products`). Populated by the serff connector from the JSON payloads
-- that the Playwright extractor (src/connectors/serff_browser.py) writes to data/cache/serff/.
CREATE TABLE IF NOT EXISTS serff_filings (
    serff_tracking_number TEXT NOT NULL,
    state           TEXT NOT NULL,
    filing_id       TEXT,              -- portal-internal id (filingSummary.xhtml?filingId=...)
    company_name    TEXT,              -- as shown on the portal (name variants differ from aips)
    aip_code        TEXT,              -- mapped to aips when the company name matches
    naic_company_code TEXT,
    product_name    TEXT,
    toi             TEXT,
    sub_toi         TEXT,              -- 02.1000/02.1001/02.1002 split lives here
    filing_type     TEXT,              -- Form | Rate/Rule | Form/Rate/Rule
    filing_status   TEXT,
    disposition_status TEXT,
    submission_date TEXT,              -- ISO when available (details phase); else NULL
    disposition_date TEXT,
    filing_url      TEXT,
    fetched_at      TEXT,
    raw             TEXT,
    PRIMARY KEY (serff_tracking_number, state)
);

-- HTTP cache so refresh only re-downloads changed URLs (freshness gate; --force bypasses).
CREATE TABLE IF NOT EXISTS url_cache (
    url             TEXT PRIMARY KEY,
    local_path      TEXT,
    etag            TEXT,
    last_modified   TEXT,
    sha256          TEXT,
    http_status     INTEGER,
    fetched_at      TEXT
);

-- Provenance: which connector ran, when, how much it returned, and any error.
CREATE TABLE IF NOT EXISTS fetch_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    target          TEXT,              -- e.g. state code or AIP name
    status          TEXT,              -- ok | error | skipped
    http_status     INTEGER,
    rows            INTEGER,
    started_at      TEXT,
    finished_at     TEXT,
    message         TEXT
);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Initialize / inspect the catalog database.")
    ap.add_argument("--init", action="store_true", help="Create tables if missing.")
    ap.add_argument("--counts", action="store_true", help="Print row counts.")
    args = ap.parse_args()

    conn = connect()
    if args.init or not args.counts:
        init_db(conn)
        print(f"Schema ready at {config.DB_PATH}")
    if args.counts:
        for t in ("aips", "products", "product_crops", "product_states", "sob_sales",
                  "documents", "fetch_log"):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t:16} {n}")
    conn.close()


if __name__ == "__main__":
    _main()
