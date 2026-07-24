"""Normalized records + idempotent upserts.

Connectors build plain AIP / Product dataclasses and hand them to upsert_aip / upsert_product.
Upserts are keyed so re-running a connector updates rows in place instead of duplicating them
(verified by tests/test_models.py).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AIP:
    aip_code: str
    name: str
    parent_company: str | None = None
    agreement_type: str | None = None
    reinsurance_year: int | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    website: str | None = None
    source_url: str | None = None


@dataclass
class Product:
    bucket: str            # '508h' | 'private'
    name: str
    source_type: str
    program: str | None = None
    aip_code: str | None = None
    developer: str | None = None
    plan_code: str | None = None
    peril_type: str | None = None
    coverage_type: str | None = None
    status: str | None = None
    effective_date: str | None = None
    source_url: str | None = None
    doc_url: str | None = None
    filing_id: str | None = None
    verified: bool = False
    notes: str | None = None
    raw: object | None = None
    crops: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)


def upsert_aip(conn: sqlite3.Connection, aip: AIP) -> None:
    conn.execute(
        """INSERT INTO aips (aip_code, name, parent_company, agreement_type, reinsurance_year,
                             city, state, phone, website, source_url, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(aip_code) DO UPDATE SET
             name=excluded.name, parent_company=excluded.parent_company,
             agreement_type=excluded.agreement_type, reinsurance_year=excluded.reinsurance_year,
             city=excluded.city, state=excluded.state, phone=excluded.phone,
             website=excluded.website, source_url=excluded.source_url,
             fetched_at=excluded.fetched_at""",
        (aip.aip_code, aip.name, aip.parent_company, aip.agreement_type, aip.reinsurance_year,
         aip.city, aip.state, aip.phone, aip.website, aip.source_url, _now_iso()),
    )


def product_key(p: Product) -> str:
    """Stable dedup key. NULL-ish fields normalize to '' so re-runs match (see db.natural_key)."""
    return "|".join([p.bucket, p.name, p.aip_code or "", p.plan_code or "", p.filing_id or ""])


def upsert_product(conn: sqlite3.Connection, p: Product) -> int:
    """Insert or update a product by its natural key; refresh crop/state child rows. Returns id."""
    now = _now_iso()
    raw = p.raw
    if raw is not None and not isinstance(raw, str):
        raw = json.dumps(raw, default=str)

    key = product_key(p)
    existing = conn.execute(
        "SELECT product_id, first_seen FROM products WHERE natural_key=?", (key,)
    ).fetchone()
    first_seen = existing["first_seen"] if existing else now

    conn.execute(
        """INSERT INTO products
             (bucket, program, name, aip_code, developer, plan_code, peril_type, coverage_type,
              status, effective_date, source_type, source_url, doc_url, filing_id, verified,
              notes, raw, first_seen, fetched_at, natural_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(natural_key) DO UPDATE SET
             program=excluded.program, developer=excluded.developer, peril_type=excluded.peril_type,
             coverage_type=excluded.coverage_type, status=excluded.status,
             effective_date=excluded.effective_date, source_type=excluded.source_type,
             source_url=excluded.source_url, doc_url=excluded.doc_url, verified=excluded.verified,
             notes=excluded.notes, raw=excluded.raw, fetched_at=excluded.fetched_at""",
        (p.bucket, p.program, p.name, p.aip_code, p.developer, p.plan_code, p.peril_type,
         p.coverage_type, p.status, p.effective_date, p.source_type, p.source_url, p.doc_url,
         p.filing_id, int(p.verified), p.notes, raw, first_seen, now, key),
    )
    pid = conn.execute(
        "SELECT product_id FROM products WHERE natural_key=?", (key,)
    ).fetchone()["product_id"]

    # Child tables: replace so stale crops/states from a prior run don't linger.
    conn.execute("DELETE FROM product_crops WHERE product_id=?", (pid,))
    conn.executemany(
        "INSERT OR IGNORE INTO product_crops (product_id, crop) VALUES (?,?)",
        [(pid, c) for c in sorted(set(p.crops))],
    )
    conn.execute("DELETE FROM product_states WHERE product_id=?", (pid,))
    conn.executemany(
        "INSERT OR IGNORE INTO product_states (product_id, state) VALUES (?,?)",
        [(pid, s) for s in sorted(set(p.states))],
    )
    return pid


def add_document(conn: sqlite3.Connection, product_id: int, url: str,
                 local_path: str | None = None, sha256: str | None = None,
                 content_type: str | None = None) -> None:
    conn.execute(
        """INSERT INTO documents (product_id, url, local_path, sha256, content_type, fetched_at)
           VALUES (?,?,?,?,?,?)""",
        (product_id, url, local_path, sha256, content_type, _now_iso()),
    )
