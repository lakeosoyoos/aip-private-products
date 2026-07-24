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
        for t in ("aips", "products", "product_crops", "product_states", "documents", "fetch_log"):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t:16} {n}")
    conn.close()


if __name__ == "__main__":
    _main()
