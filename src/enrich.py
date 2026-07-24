"""Document enrichment — fill crops/states/peril/coverage from each product's doc_url.

Most private products scraped off AIP marketing sites carry a doc_url (detail page or brochure
PDF) that names the crops, states, and perils the product actually covers, even when the listing
page did not. This stage downloads those documents through src.http (url_cache => re-runs are
cheap), extracts text (pypdf for PDFs, BeautifulSoup for HTML), and applies deterministic
keyword/regex matching — no guessing: a document that names nothing extractable leaves the
product untouched.

Idempotent by construction: child rows are INSERT OR IGNORE, peril/coverage only fill where NULL,
documents upsert on (product_id, url), and the nationwide note is only appended once. A second
run against an unchanged catalog writes nothing.

Run standalone via `python -m src.refresh --enrich`; a normal refresh runs it automatically after
the connectors (skip with --no-enrich).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from . import rowcrops
# Reuse the exact peril/coverage keyword conventions the site scrapers use.
from .connectors.aip_sites.base import _guess_coverage, _guess_peril


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Crop extraction: rowcrops matcher + a secondary lexicon for the specialty
# crops private products commonly name. Multi-word phrases that contain a
# row-crop word ("seed corn") are masked out before the row-crop pass so a
# seed-corn product doesn't also get tagged "Corn".
# ---------------------------------------------------------------------------
SPECIALTY_CROPS: dict[str, list[str]] = {
    "Citrus": ["citrus", "oranges", "orange grove", "grapefruit", "lemons", "tangerines", "mandarins"],
    "Grapes": ["grapes", "wine grapes", "table grapes", "vineyard", "vineyards"],
    "Raisins": ["raisins", "raisin"],
    "Tomatoes": ["tomatoes", "tomato", "processing tomatoes", "fresh market tomatoes"],
    "Almonds": ["almonds", "almond"],
    "Walnuts": ["walnuts", "walnut"],
    "Pistachios": ["pistachios", "pistachio"],
    "Pecans": ["pecans", "pecan"],
    "Tobacco": ["tobacco"],
    "Hay/Forage": ["hay", "forage", "alfalfa", "haylage", "silage"],
    "Pasture/Rangeland": ["pasture", "rangeland", "grazing"],
    "Potatoes": ["potatoes", "potato"],
    "Sweet Potatoes": ["sweet potatoes", "sweet potato"],
    "Seed Corn": ["seed corn", "hybrid seed corn"],
    "Sweet Corn": ["sweet corn"],
    "Popcorn": ["popcorn"],
    "Sugarcane": ["sugarcane", "sugar cane"],
    "Apples": ["apples", "apple orchard", "apple orchards"],
    "Cherries": ["cherries", "tart cherries", "sweet cherries"],
    "Peaches": ["peaches"],
    "Pears": ["pears"],
    "Blueberries": ["blueberries", "blueberry"],
    "Cranberries": ["cranberries", "cranberry"],
    "Strawberries": ["strawberries", "strawberry"],
    "Onions": ["onions"],
    "Garlic": ["garlic"],
    "Hops": ["hops"],
    "Nursery": ["nursery stock", "nursery crops"],
    "Chickpeas": ["chickpeas", "chickpea", "garbanzo beans", "garbanzos"],
    "Lentils": ["lentils", "lentil"],
    "Avocados": ["avocados", "avocado"],
    "Olives": ["olives"],
    "Pumpkins": ["pumpkins", "pumpkin"],
    "Melons": ["melons", "watermelon", "watermelons", "cantaloupe", "cantaloupes"],
    "Sweet Peas": ["green peas", "sweet peas"],
    "Mint": ["peppermint", "spearmint"],
}


def extract_crops(text: str, extra: list[str] | None = None) -> list[str]:
    """Canonical crops named in text: specialty lexicon first (masking matched
    phrases), then the shared row-crop matcher on what remains."""
    if not text:
        return []
    masked = text.lower()
    found: set[str] = set()
    for canonical, variants in SPECIALTY_CROPS.items():
        for kw in sorted(variants, key=len, reverse=True):
            pat = re.compile(rf"\b{re.escape(kw)}\b")
            if pat.search(masked):
                found.add(canonical)
                masked = pat.sub(" ", masked)   # mask so "seed corn" != "Corn"
    found.update(rowcrops.match_crops(masked, extra))
    return sorted(found)


# ---------------------------------------------------------------------------
# State extraction. Full state names (longest-first alternation, so "West
# Virginia" never also yields "Virginia") plus comma/and-separated lists of
# 2-letter USPS codes ("IA, IL, NE and MN" — at least two valid codes required,
# so bare English words like "IN"/"OR" don't fire). Lines containing a ZIP code
# look like addresses/footers and are ignored (mitigates "Madison, Wisconsin
# 53703" tagging Wisconsin). "nationwide"/"all states" is returned as a flag
# and recorded in notes rather than exploded into 50 rows.
# ---------------------------------------------------------------------------
STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY",
}
_STATE_CODES = set(STATE_NAMES.values())

_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
# Licensing disclaimers name states without covering crops there
# ("Doing business as ... in California, CA Entity License #0F34212").
_LICENSE_RE = re.compile(r"\blicen[cs]e", re.I)
_NATIONWIDE_RE = re.compile(
    r"\b(nationwide|all\s+50\s+states|all\s+states|every\s+state)\b", re.I)
_STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in STATE_NAMES), key=len, reverse=True)) + r")\b",
    re.I,
)
# A run of >=2 two-letter uppercase tokens separated by comma / slash / "and" /
# Oxford ", and" ("Available in AZ, CO, ... WI, and WY.").
_ABBR_LIST_RE = re.compile(
    r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])"
    r"(?:\s*(?:,\s*(?:and\s+)?|/|&|\band\b)\s*(?<![A-Za-z])[A-Z]{2}(?![A-Za-z]))+")


def extract_states(text: str) -> tuple[list[str], bool]:
    """Return (sorted 2-letter codes, nationwide_flag) for states named in text."""
    if not text:
        return [], False
    codes: set[str] = set()
    nationwide = False
    for line in text.splitlines():
        if _ZIP_RE.search(line) or _LICENSE_RE.search(line):
            continue  # address- or license-disclaimer-shaped line — HQ-city false positives
        if _NATIONWIDE_RE.search(line):
            nationwide = True
        for m in _STATE_NAME_RE.finditer(line):
            codes.add(STATE_NAMES[m.group(1).lower()])
        for run in _ABBR_LIST_RE.finditer(line):
            toks = re.findall(r"[A-Z]{2}", run.group(0))
            valid = [t for t in toks if t in _STATE_CODES]
            if len(valid) >= 2:
                codes.update(valid)
    return sorted(codes), nationwide


# ---------------------------------------------------------------------------
# Peril / coverage: same keyword conventions as the connectors (_guess_peril /
# _guess_coverage from aip_sites), applied to the product name first (usually
# decisive: "Crop Hail" => hail) and then only the head of the document, so a
# revenue brochure's hail-exclusion boilerplate on page 4 can't flip the peril.
# A couple of perils the connectors never see (freeze, rain) are added here.
# ---------------------------------------------------------------------------
_HEAD_CHARS = 2000
_EXTRA_PERILS = (
    ("freeze", "freeze"), ("frost", "freeze"),
    ("excess rain", "rain"), ("excess moisture", "rain"), ("rainfall", "rain"),
    ("drought", "drought"),
)


def _extra_peril(text: str) -> str | None:
    t = text.lower()
    for kw, label in _EXTRA_PERILS:
        if kw in t:
            return label
    return None


def extract_peril(name: str, text: str) -> str | None:
    head = (text or "")[:_HEAD_CHARS]
    return (_guess_peril(name or "") or _extra_peril(name or "")
            or _guess_peril(head) or _extra_peril(head))


def extract_coverage(name: str, text: str) -> str | None:
    return _guess_coverage(name or "") or _guess_coverage((text or "")[:_HEAD_CHARS])


# ---------------------------------------------------------------------------
# Text extraction from a cached download.
# ---------------------------------------------------------------------------
def _is_pdf(path: Path, url: str) -> bool:
    try:
        with open(path, "rb") as fh:
            if fh.read(5).startswith(b"%PDF"):
                return True
    except OSError:
        pass
    return url.lower().split("?")[0].endswith(".pdf")


def extract_text(path: Path, url: str) -> tuple[str, str]:
    """Return (text, content_type) for a cached document. Empty text = unreadable."""
    if _is_pdf(path, url):
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            text = ""
        return text, "application/pdf"
    try:
        html = path.read_text(errors="replace")
    except OSError:
        return "", "text/html"
    soup = BeautifulSoup(html, "html.parser")
    # Drop site chrome before reading: nav/footer/header carry sitewide product menus
    # (crop-named links tag every page with every crop) and select/option dropdowns are
    # agent-locator "Choose a State" lists that would tag all 50 states.
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header",
                     "select", "option", "form", "aside"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return root.get_text("\n", strip=True), "text/html"


# ---------------------------------------------------------------------------
# Section scoping for shared listing pages. Several products often point at the
# same doc_url (e.g. Rain & Hail's coverages pages describe every endorsement,
# each with its own "Availability:" line). Extracting from the whole page would
# credit every product with every sibling's crops and states, so when siblings
# share the URL we cut the text down to the lines between this product's name
# and the next sibling product's name. If the product's name never appears, the
# full text is used (single-product docs are unaffected: they have no siblings).
# ---------------------------------------------------------------------------
def _norm_heading(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _is_heading_for(line_norm: str, name_norm: str) -> bool:
    # The line is this name, possibly with a little decoration ((WE), ®, etc.).
    return bool(name_norm) and (
        line_norm == name_norm
        or (name_norm in line_norm and len(line_norm) <= len(name_norm) + 30))


def scope_to_product(text: str, name: str, sibling_names: list[str]) -> str:
    """Return the slice of a shared listing doc that belongs to `name`."""
    lines = text.splitlines()
    target = _norm_heading(name)
    start = next((i for i, ln in enumerate(lines)
                  if _is_heading_for(_norm_heading(ln), target)), None)
    if start is None:
        return text
    sibs = [n for n in (_norm_heading(s) for s in sibling_names) if n and n != target]
    end = next((j for j in range(start + 1, len(lines))
                if any(_is_heading_for(_norm_heading(lines[j]), s) for s in sibs)),
               len(lines))
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
_NATIONWIDE_NOTE = "[enrich] availability: nationwide per document"

_TARGET_SQL = """
SELECT p.product_id, p.name, p.aip_code, p.doc_url, p.peril_type, p.coverage_type, p.notes,
       NOT EXISTS (SELECT 1 FROM product_crops  c WHERE c.product_id = p.product_id) AS needs_crops,
       NOT EXISTS (SELECT 1 FROM product_states s WHERE s.product_id = p.product_id) AS needs_states
FROM products p
WHERE p.doc_url IS NOT NULL
  AND (NOT EXISTS (SELECT 1 FROM product_crops  c WHERE c.product_id = p.product_id)
       OR NOT EXISTS (SELECT 1 FROM product_states s WHERE s.product_id = p.product_id)
       OR p.peril_type IS NULL OR p.coverage_type IS NULL)
ORDER BY p.product_id
"""


@dataclass
class EnrichStats:
    targets: int = 0
    enriched: int = 0            # products that gained at least one fact
    nothing_found: int = 0       # doc read fine but named nothing we still needed
    fetch_failed: int = 0
    unreadable: int = 0          # fetched but no text (e.g. scanned PDF)
    gained_crops: int = 0        # products that gained >=1 crop row
    gained_states: int = 0
    filled_peril: int = 0
    filled_coverage: int = 0
    nationwide: int = 0
    per_aip: dict[str, int] = field(default_factory=dict)   # aip_code -> products enriched
    failures: list[str] = field(default_factory=list)       # "name: reason" examples

    def coverage_lines(self) -> list[str]:
        lines = [
            f"enrich: {self.targets} targets, {self.gained_crops} gained crops, "
            f"{self.gained_states} gained states, {self.filled_peril} peril filled, "
            f"{self.filled_coverage} coverage filled, {self.nationwide} nationwide-noted, "
            f"{self.unreadable} docs unreadable, {self.fetch_failed} fetch-failed, "
            f"{self.nothing_found} nothing-found"
        ]
        if self.per_aip:
            per = ", ".join(f"{k or '??'}: {v}" for k, v in sorted(self.per_aip.items()))
            lines.append(f"enrich per-AIP (products enriched): {per}")
        for f in self.failures[:5]:
            lines.append(f"enrich FAIL {f}")
        return lines


def _insert_child(conn: sqlite3.Connection, table: str, col: str,
                  product_id: int, values: list[str]) -> int:
    n = 0
    for v in values:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO {table} (product_id, {col}) VALUES (?,?)", (product_id, v))
        n += cur.rowcount if cur.rowcount > 0 else 0
    return n


def _record_document(conn: sqlite3.Connection, product_id: int, url: str,
                     content_type: str) -> None:
    cache = conn.execute(
        "SELECT local_path, sha256 FROM url_cache WHERE url=?", (url,)).fetchone()
    local_path = cache["local_path"] if cache else None
    sha256 = cache["sha256"] if cache else None
    existing = conn.execute(
        "SELECT doc_id FROM documents WHERE product_id=? AND url=?", (product_id, url)).fetchone()
    if existing:
        conn.execute(
            """UPDATE documents SET local_path=?, sha256=?, content_type=?, fetched_at=?
               WHERE doc_id=?""",
            (local_path, sha256, content_type, _now_iso(), existing["doc_id"]))
    else:
        conn.execute(
            """INSERT INTO documents (product_id, url, local_path, sha256, content_type, fetched_at)
               VALUES (?,?,?,?,?,?)""",
            (product_id, url, local_path, sha256, content_type, _now_iso()))


def run(conn: sqlite3.Connection, client, cfg, force: bool = False) -> EnrichStats:
    """Enrich every product whose doc_url may fill a gap. Deterministic + idempotent."""
    started = _now_iso()
    stats = EnrichStats()
    ua = {"User-Agent": cfg.serff_user_agent}  # marketing sites block non-browser UAs

    targets = conn.execute(_TARGET_SQL).fetchall()
    stats.targets = len(targets)

    for row in targets:
        pid, url = row["product_id"], row["doc_url"]
        try:
            path = client.download(url, force=force, headers=ua)
        except Exception as exc:
            stats.fetch_failed += 1
            if len(stats.failures) < 20:
                stats.failures.append(f"{row['name']} [{url}]: {type(exc).__name__}: {exc}")
            continue

        text, content_type = extract_text(path, url)
        _record_document(conn, pid, url, content_type)
        if not text.strip():
            stats.unreadable += 1
            if len(stats.failures) < 20:
                stats.failures.append(f"{row['name']} [{url}]: no extractable text")
            conn.commit()
            continue

        # Shared listing page? Scope the text to this product's own section.
        siblings = [s["name"] for s in conn.execute(
            "SELECT name FROM products WHERE doc_url=? AND product_id != ?", (url, pid))]
        if siblings:
            text = scope_to_product(text, row["name"], siblings)

        gained = False

        if row["needs_crops"]:
            crops = extract_crops(text, cfg.rowcrops_extra)
            if _insert_child(conn, "product_crops", "crop", pid, crops):
                stats.gained_crops += 1
                gained = True

        if row["needs_states"]:
            states, nationwide = extract_states(text)
            if _insert_child(conn, "product_states", "state", pid, states):
                stats.gained_states += 1
                gained = True
            if nationwide and _NATIONWIDE_NOTE not in (row["notes"] or ""):
                conn.execute(
                    "UPDATE products SET notes = COALESCE(notes || ' | ', '') || ? WHERE product_id=?",
                    (_NATIONWIDE_NOTE, pid))
                stats.nationwide += 1
                gained = True

        if row["peril_type"] is None:
            peril = extract_peril(row["name"], text)
            if peril:
                conn.execute(
                    "UPDATE products SET peril_type=? WHERE product_id=? AND peril_type IS NULL",
                    (peril, pid))
                stats.filled_peril += 1
                gained = True

        if row["coverage_type"] is None:
            coverage = extract_coverage(row["name"], text)
            if coverage:
                conn.execute(
                    "UPDATE products SET coverage_type=? WHERE product_id=? AND coverage_type IS NULL",
                    (coverage, pid))
                stats.filled_coverage += 1
                gained = True

        if gained:
            stats.enriched += 1
            stats.per_aip[row["aip_code"] or ""] = stats.per_aip.get(row["aip_code"] or "", 0) + 1
        else:
            stats.nothing_found += 1
        conn.commit()

    conn.execute(
        """INSERT INTO fetch_log (source, target, status, http_status, rows, started_at,
                                  finished_at, message)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("enrich", None, "ok" if not stats.fetch_failed else "partial", None,
         stats.enriched, started, _now_iso(),
         f"{stats.targets} targets: {stats.enriched} enriched, {stats.nothing_found} nothing-found, "
         f"{stats.fetch_failed} fetch-failed, {stats.unreadable} unreadable"))
    conn.commit()
    return stats
