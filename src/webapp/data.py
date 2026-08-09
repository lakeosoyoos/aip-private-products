"""Read-only data access + filtering for the web app.

All catalog logic is imported from the pipeline (`src.stack`), not reimplemented
here. The functions that shape and filter the products table are pure pandas so
they can be unit-tested without Streamlit. The DB is always opened read-only /
immutable so cached reads across sessions are safe.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .. import config
from ..stack import classified_products


def open_ro(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the catalog strictly read-only via a sqlite URI.

    check_same_thread=False is required because the app caches this one connection with
    @st.cache_resource and Streamlit executes reruns (and different sessions) on different
    threads — the default check_same_thread=True raises sqlite3.ProgrammingError when the cached
    connection is used from another thread. Safe here: the DB is opened read-only, and SQLite's
    default serialized threading mode allows concurrent reads on one connection.

    `immutable=1` is applied ONLY when the database has no WAL sidecar. It promises SQLite the
    file cannot change, which lets it skip all locking — a real win for the SHIPPED catalog
    (scripts/build_app_db.py writes it in DELETE journal mode, one self-contained file, never
    written again). But it also makes SQLite ignore the -wal file entirely, and on a WAL-mode
    database that is not a consistent view: opening the 4 GB working catalog this way raises
    "disk I/O error" outright. Same family as the "database disk image is malformed" this repo
    hit when the app DB was built with a plain file copy of a WAL database.

    Presence of a sidecar is the test, rather than querying PRAGMA journal_mode — the query
    would itself need a connection, which is the thing that fails.
    """
    dbp = Path(db_path or config.DB_PATH)
    has_wal = dbp.with_name(dbp.name + "-wal").exists() or \
        dbp.with_name(dbp.name + "-shm").exists()
    uri = f"file:{dbp}?mode=ro" + ("" if has_wal else "&immutable=1")
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def derive_subsidized(bucket: str) -> bool:
    """Subsidy rule: everything except truly-private products is subsidized."""
    return bucket != "private"


def _split_list(value) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(";") if v.strip()]


def products_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per product, with stack layer + subsidy derived. Pure read."""
    rows = []
    for p in classified_products(conn):
        crops = _split_list(p.get("crops"))
        states = _split_list(p.get("sts"))
        subsidized = derive_subsidized(p["bucket"])
        rows.append({
            "name": p["name"],
            "AIP": p["aip_name"] if p.get("aip_code") else "All AIPs",
            "aip_code": p.get("aip_code"),
            "bucket": p["bucket"],
            "subsidy": "subsidized" if subsidized else "private (unsubsidized)",
            "subsidized": subsidized,
            "layer": p["layer"],
            "federal_analog": p.get("federal_analog"),
            "peril_type": p.get("peril_type"),
            "coverage_type": p.get("coverage_type"),
            "crops": ", ".join(crops),
            "_crops_list": crops,
            "states": ", ".join(states),
            "doc_url": p.get("doc_url") or p.get("source_url"),
            "developer": p.get("developer"),
            "status": p.get("status"),
        })
    return pd.DataFrame(rows)


def filter_products(
    df: pd.DataFrame,
    *,
    bucket: str | None = None,
    subsidy: str | None = None,
    aips: list[str] | None = None,
    crops: list[str] | None = None,
    peril: str | None = None,
    coverage_type: str | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    """Filter the products frame. Each argument is independent (AND-combined).

    - bucket: '508h' | 'private' | None (all)
    - subsidy: 'subsidized' | 'private' | None (all)  [derived from bucket]
    - aips: list of AIP display names to keep (empty/None = all)
    - crops: list of crops; keep a product if it lists ANY of them
    - peril / coverage_type: exact match on that column
    - search: case-insensitive substring on the product name
    """
    out = df
    if bucket:
        out = out[out["bucket"] == bucket]
    if subsidy == "subsidized":
        out = out[out["subsidized"]]
    elif subsidy == "private":
        out = out[~out["subsidized"]]
    if aips:
        out = out[out["AIP"].isin(aips)]
    if crops:
        wanted = set(crops)
        out = out[out["_crops_list"].apply(lambda cl: bool(wanted & set(cl)))]
    if peril:
        out = out[out["peril_type"] == peril]
    if coverage_type:
        out = out[out["coverage_type"] == coverage_type]
    if search:
        out = out[out["name"].str.contains(search, case=False, na=False)]
    return out


def serff_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """The serff_filings table as a frame (filing grain, 5 states)."""
    return pd.read_sql_query(
        "SELECT serff_tracking_number, state, aip_code, company_name, product_name, "
        "sub_toi, filing_type, filing_status, disposition_status, submission_date, "
        "disposition_date, filing_url FROM serff_filings "
        "ORDER BY state, company_name, submission_date",
        conn,
    )


def catalog_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts used on the About tab."""
    tables = [
        "products", "product_crops", "product_states", "product_counties",
        "serff_filings", "aips", "documents",
    ]
    out: dict[str, int] = {}
    for t in tables:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    for r in conn.execute("SELECT bucket, COUNT(*) n FROM products GROUP BY bucket"):
        out[f"products_{r['bucket']}"] = r["n"]
    return out
