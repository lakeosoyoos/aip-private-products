"""Product-DEPTH discovery — surface ADDITIONAL genuine private products that are missing from
the catalog because an AIP's public website lists only a handful (Palomar, American Agricultural,
Clear Blue, American Agri-Business, Hudson all look thin for exactly this reason).

Two conservative sources, no fabrication:

  1. SERFF filing product names (serff_filings.product_name, read-only). A filing title only
     becomes a candidate when, after we strip the administrative decoration (year, state, and the
     Rate/Rule/Form filing-type codes), a recognizable PRODUCT core remains and that core matches a
     curated allow-lexicon of real crop-insurance product nouns. Titles like "2022 Crop Hail - F",
     "Rate Filing", "RRF", "Form Filing", a bare year, "IACHFILING2021", or "endorsement 457" carry
     no product core and are rejected.

  2. Brochure / document text already linked from products.doc_url (the cached HTML pages and PDF
     brochures the catalog already downloaded). Headings on those pages frequently name sibling
     products/endorsements the listing scraper never captured (Hudson's "eZ-Hail", "Production
     Hail", "MyYield Max"...). The same allow-lexicon gates them.

Everything is deduped against the existing catalog (same aip + normalized name / acronym, mirroring
models.product_key) and against itself, then written to a HUMAN-GATED review CSV
(data/seed/derived_products_candidates.csv). This module never writes the real catalog.db — the
reviewer imports selectively, exactly like data/seed/private_products_manual.csv.

Run:  python -m src.deepen              # writes the candidates CSV
      python -m src.deepen --show       # also prints accepted + a sample of rejects
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from . import config
from .connectors.aip_sites.base import _guess_coverage, _guess_peril
from .enrich import _extra_peril
from .stack import classify

CSV_HEADER = ["aip_code", "name", "peril_type", "coverage_type",
              "source_type", "evidence", "confidence"]

# Loader note emitted at the top of the CSV (importer must skip leading '#' lines). Kept here so the
# file is self-documenting for the human reviewer.
LOADER_NOTE = [
    "# derived_products_candidates.csv - HUMAN-GATED product-depth candidates (src/deepen.py).",
    "# NOT auto-imported. Review each row, then import selectively like private_products_manual.csv.",
    "# source_type: serff_derived  = product core recovered from a SERFF filing title (evidence =",
    "#   SERFF tracking number). brochure_derived = product named in a doc_url brochure/page",
    "#   (evidence = the doc URL). confidence: high = matched a named-product pattern; low = matched",
    "#   only a peril noun / distinctive acronym and may be an endorsement or filing variant - verify.",
    "# bucket=private, program=private_nonreinsured for every row. Dedup already run vs existing",
    "# catalog (same aip + normalized name/acronym) and within this file.",
]


# ---------------------------------------------------------------------------
# Administrative decoration that is NOT part of a product name. Stripped from a
# filing title before we look for a product core.
# ---------------------------------------------------------------------------
_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
}
_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY",
}

# Filing-type codes and administrative words. These are the tail/'-' decorations on filing titles
# (Rate/Rule/Form and their SERFF shorthand) plus year/parenthetical status words. NONE of these
# name a product.
_FILING_TYPE_CODES = {
    "rrf", "rr", "ru", "ru2", "f", "f2", "fr", "frr", "fru", "r/f", "rf", "frr2",
}
_ADMIN_WORDS = {
    "filing", "filings", "form", "forms", "rate", "rates", "rule", "rules",
    "reference", "update", "logo", "correction", "corrected", "revised", "revision",
    "initial", "new", "renewal", "renew", "policy", "endorsement",
    "endorsements", "coverage", "insurance", "the", "and", "&", "for", "of", "with",
    "aaic", "prm", "ch",  # company/line shorthands seen in titles (AAIC, PRM/CH)
    # NB: "program"/"programs" and "product"/"products" are deliberately NOT admin words -
    # they are load-bearing in real product names ("Select Programs", "Weather Products").
}
# Parenthetical status words that are decoration (strip); other parentheticals (e.g. "(PAR)",
# "(ICE)") are product acronyms and kept.
_PAREN_STATUS = re.compile(
    r"\((?:new|correction|corrected|revised|revision|initial|renewal|renew|updated|update|pending|"
    r"withdrawn|approved)\)", re.I)


def _strip_states(text: str) -> str:
    low = text
    for name in sorted(_STATE_NAMES, key=len, reverse=True):
        low = re.sub(rf"(?<![a-z]){re.escape(name)}(?![a-z])", " ", low, flags=re.I)
    # bare 2-letter state codes as standalone tokens
    low = re.sub(r"(?<![A-Za-z])(" + "|".join(_STATE_CODES) + r")(?![A-Za-z])", " ", low)
    return low


def normalize_title(raw: str) -> str:
    """Strip year / state / filing-type / admin decoration from a filing title, returning the
    residual product core (lowercased, whitespace-collapsed). Empty string = nothing left."""
    if not raw:
        return ""
    t = _PAREN_STATUS.sub(" ", raw)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)                 # years (2026, 2021...)
    t = re.sub(r"\b\d{2}\b", " ", t)                        # trailing 2-digit year ("...19")
    t = _strip_states(t)
    t = t.replace("/", " ").replace("-", " ").replace(",", " ").replace(".", " ")
    tokens = [tok for tok in t.split() if tok]
    kept = []
    for tok in tokens:
        low = tok.lower()
        if low in _FILING_TYPE_CODES or low in _ADMIN_WORDS:
            continue
        kept.append(tok)
    return " ".join(kept).lower().strip()


# ---------------------------------------------------------------------------
# Hard-reject patterns: titles that are unambiguously administrative even before
# normalization. (Belt-and-suspenders; normalize+allow-lexicon rejects most.)
# ---------------------------------------------------------------------------
_DENY_RAW = [
    re.compile(r"^\s*$"),
    re.compile(r"endorsement\s+\d+", re.I),               # "endorsement 457"
    re.compile(r"\b(logo|reference filing|form update|form logo|rate filing)\b", re.I),
    # glued all-caps admin blobs: IACHFILING2021, 2020STPFILING, IASTPFORMFILING2021
    re.compile(r"^\S*(?:filing|stp|rrf)\S*$", re.I),
]


def denied_raw(raw: str) -> bool:
    r = (raw or "").strip()
    if " " not in r and re.search(r"filing|rrf|stp", r, re.I):
        return True
    return any(p.search(r) for p in _DENY_RAW)


# ---------------------------------------------------------------------------
# Allow-lexicon. Each entry: (regex on the normalized core, canonical display name, confidence).
# Ordered most-specific-first; first match wins. HIGH = a named product line; LOW = a peril noun or
# distinctive acronym that may be an endorsement/filing variant and needs a human look.
# ---------------------------------------------------------------------------
_ALLOW: list[tuple[re.Pattern, str, str]] = [
    # -- named product lines (high confidence) --
    (re.compile(r"revenue boost|rev boost"), "Revenue Boost", "high"),
    (re.compile(r"magnum yield protection|magnum"), "Magnum Yield Protection", "high"),
    (re.compile(r"total revenue coverage|total revenue|\btrc\b"), "Total Revenue Coverage", "high"),
    (re.compile(r"private area revenue coverage|\bpar\b(?!\s*flex)|\bpar flex|parflex"),
     "Private Area Revenue Coverage (PAR)", "high"),
    (re.compile(r"production cost"), "Production Cost Insurance Policy", "high"),
    (re.compile(r"weather insurance|weather product|\bweather\b"), "Weather Insurance Policy", "high"),
    (re.compile(r"biotech yield assurance|\bbya\b"), "Biotech Yield Assurance", "high"),
    (re.compile(r"dairy price enhancement"), "Dairy Price Enhancement Coverage", "high"),
    (re.compile(r"commercial nursery"), "Commercial Nursery Supplement", "high"),
    (re.compile(r"boost max|boost-max"), "Boost-Max", "high"),
    (re.compile(r"\bboost\b"), "BOOST", "high"),
    (re.compile(r"\brpowerd\b"), "RPowerD", "high"),
    (re.compile(r"\bmpowerd\b"), "MPowerD", "high"),
    (re.compile(r"\bapco\b"), "APCO", "high"),
    (re.compile(r"\brevco\b"), "REVCO", "high"),
    (re.compile(r"price[- ]?flex|priceflex"), "Price-Flex", "high"),
    (re.compile(r"revenue band|yield band"), "Revenue Band & Yield Band Coverage", "high"),
    (re.compile(r"select program"), "Select Programs", "high"),
    (re.compile(r"\bpeco\b"), "Personal Enhanced Coverage Option (PECO)", "high"),
    (re.compile(r"\bmyeco\b"), "MyECO", "high"),
    (re.compile(r"\bmysco\b"), "MySCO", "high"),
    (re.compile(r"\bmymco\b"), "MyMCO", "high"),
    (re.compile(r"eco/sco band|\bband\b"), "BAND", "high"),
    (re.compile(r"ez[- ]?hail"), "eZ-Hail", "high"),
    (re.compile(r"production hail"), "Production Hail", "high"),
    (re.compile(r"myyield"), "MyYield Max", "high"),
    # -- peril / utility cores (lower confidence: may be an endorsement or a re-file variant) --
    (re.compile(r"np fire|named peril fire|grain fire"), "Grain Fire (Named Peril)", "low"),
    (re.compile(r"pasture fire"), "Pasture Fire", "low"),
    (re.compile(r"np replant|named peril replant|replant supplement|mpci replant"),
     "Named Peril Replant", "low"),
    (re.compile(r"excess moisture"), "Excess Moisture", "low"),
    (re.compile(r"adjusted rainfall index|rainfall index"), "Adjusted Rainfall Index", "low"),
    (re.compile(r"over ?/ ?under|over under"), "PRF Over/Under", "low"),
    (re.compile(r"flex lease"), "Flex Lease", "low"),
    (re.compile(r"\barch\b"), "ARCH Program", "low"),
    (re.compile(r"\bcliff\b"), "CLIFF", "low"),
    (re.compile(r"\bbrp\b"), "Band Revenue Protection (BRP)", "low"),
    (re.compile(r"\bvip\b|variable interval"), "Variable Interval Product (VIP)", "low"),
    (re.compile(r"input cost|\bice\b"), "Input Cost Endorsement (ICE)", "low"),
    (re.compile(r"green snap"), "Green Snap Endorsement", "low"),
    (re.compile(r"seed corn"), "Seed Corn Endorsement", "low"),
    (re.compile(r"\bnamed peril\b"), "Named Peril", "low"),
    (re.compile(r"crop hail"), "Crop Hail", "low"),
    (re.compile(r"\bwind\b"), "Wind Endorsement", "low"),
    (re.compile(r"\bfire\b"), "Fire Coverage", "low"),
    (re.compile(r"\bhail\b"), "Crop Hail", "low"),
    (re.compile(r"\breplant\b"), "Replant Option", "low"),
]

def product_from_core(core: str) -> tuple[str | None, str]:
    """Map a normalized product core to (canonical_name, confidence) or (None, '').

    Allow-lexicon only - no generic acronym fallback. An earlier version accepted any lone all-caps
    residual token, which manufactured junk products from admin residue (FEE, FILNG, JACKET, PAGE,
    RCIC, COMBO...). Every real brand acronym seen in the data (BYA, APCO, REVCO, RPowerD, PAR, VIP,
    BRP, ICE, CLIFF, BOOST) is listed explicitly instead."""
    if not core:
        return None, ""
    for pat, name, conf in _ALLOW:
        if pat.search(core):
            return name, conf
    return None, ""


def product_from_filing(raw: str) -> tuple[str | None, str]:
    """Full pipeline for one SERFF filing title -> (canonical_name, confidence) or (None, '')."""
    if denied_raw(raw):
        return None, ""
    return product_from_core(normalize_title(raw))


# ---------------------------------------------------------------------------
# Dedup against the existing catalog and within the candidate set.
# ---------------------------------------------------------------------------
def norm_key(name: str) -> str:
    """Loose normalized key: drop trademark marks and any parenthetical, keep alnum only."""
    n = re.sub(r"\([^)]*\)", " ", name or "")
    n = n.replace("®", " ").replace("™", " ").replace("©", " ")
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def acronym(name: str) -> str:
    """Initialism of a multi-word name (Band Revenue Protection -> BRP). '' for single words."""
    words = re.findall(r"[A-Za-z][a-z]+", re.sub(r"\([^)]*\)", " ", name or ""))
    return "".join(w[0] for w in words).upper() if len(words) >= 2 else ""


def _existing_index(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """aip_code -> set of dedup tokens (normalized names + their acronyms) already in the catalog."""
    idx: dict[str, set[str]] = {}
    for r in conn.execute(
            "SELECT aip_code, name FROM products WHERE bucket='private' AND aip_code IS NOT NULL"):
        toks = idx.setdefault(r["aip_code"], set())
        nk = norm_key(r["name"])
        if nk:
            toks.add(nk)
        ac = acronym(r["name"])
        if ac:
            toks.add(ac.lower())
        # parenthetical acronym in the name itself, e.g. "...(PECO)"
        for m in re.findall(r"\(([A-Za-z]{2,8})\)", r["name"]):
            toks.add(m.lower())
    return idx


def _is_dup(name: str, existing: set[str]) -> bool:
    nk = norm_key(name)
    ac = acronym(name).lower()
    for tok in existing:
        if not tok:
            continue
        if nk and nk == tok:                       # same normalized name
            return True
        if ac and ac == tok:                       # same acronym
            return True
        # Containment only when the SHORTER token is >=5 chars, so specific enough to be the same
        # product. (Prevents short existing tokens like 'band'/'ice'/'par' matching any longer name
        # that merely contains those letters - e.g. WN 'BAND' vs 'Revenue Band & Yield Band'.)
        if nk and tok in nk and len(tok) >= 5:
            return True
        if nk and nk in tok and len(nk) >= 5:
            return True
    # candidate's own parenthetical acronym vs existing tokens
    for m in re.findall(r"\(([A-Za-z]{2,8})\)", name):
        if m.lower() in existing:
            return True
    return False


# ---------------------------------------------------------------------------
# Classification of the accepted candidate (peril / coverage), same conventions
# as the site connectors + enrich, validated against the stack layer model.
# ---------------------------------------------------------------------------
def classify_candidate(name: str, context: str = "") -> tuple[str | None, str | None, str]:
    blob = f"{name} {context}"
    peril = _guess_peril(name) or _extra_peril(name) or _guess_peril(blob) or _extra_peril(blob)
    coverage = _guess_coverage(name) or _guess_coverage(blob)
    layer, _analog = classify(name, "private", "private_nonreinsured", peril, coverage)
    return peril, coverage, layer


# ---------------------------------------------------------------------------
# Candidate record + collectors
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    aip_code: str
    name: str
    peril_type: str | None
    coverage_type: str | None
    source_type: str          # serff_derived | brochure_derived
    evidence: str
    confidence: str           # high | low
    raw: str = ""             # provenance: the raw title/heading it came from
    layer: str = ""

    def row(self) -> list[str]:
        return [self.aip_code, self.name, self.peril_type or "", self.coverage_type or "",
                self.source_type, self.evidence, self.confidence]


def candidates_from_serff(conn: sqlite3.Connection) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Return (accepted candidates, rejected [(aip, raw_title)]) from serff_filings."""
    accepted: list[Candidate] = []
    rejected: list[tuple[str, str]] = []
    rows = conn.execute(
        """SELECT aip_code, product_name, MIN(serff_tracking_number) tn, COUNT(*) n
           FROM serff_filings
           WHERE product_name IS NOT NULL AND aip_code IS NOT NULL
           GROUP BY aip_code, product_name""").fetchall()
    for r in rows:
        aip, title = r["aip_code"], r["product_name"]
        name, conf = product_from_filing(title)
        if not name:
            rejected.append((aip, title))
            continue
        peril, coverage, layer = classify_candidate(name, title)
        accepted.append(Candidate(
            aip_code=aip, name=name, peril_type=peril, coverage_type=coverage,
            source_type="serff_derived", evidence=f"SERFF {r['tn']}",
            confidence=conf, raw=title, layer=layer))
    return accepted, rejected


# --- brochure text -----------------------------------------------------------
_CHROME_TAGS = ["script", "style", "noscript", "nav", "footer", "header",
                "select", "option", "form", "aside"]


def _headings_from_html(path: Path) -> list[str]:
    try:
        html = path.read_text(errors="replace")
    except OSError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_CHROME_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    out = []
    for h in root.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
        txt = " ".join(h.get_text(" ", strip=True).split())
        if 3 <= len(txt) <= 60:
            out.append(txt)
    return out


def _headings_from_pdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return []
    # Short standalone lines on a brochure are usually product/section names.
    return [ln.strip() for ln in text.splitlines()
            if 3 <= len(ln.strip()) <= 60 and len(ln.strip().split()) <= 6]


# A brochure "heading" is only a product name if it is product-SHAPED, not a prose sentence. These
# guard against descriptive copy ("Adverse weather conditions", "How Tomato Named Peril Insurance
# Works") that happens to contain a peril word.
_PROSE_MARKERS = re.compile(
    r"\b(how|why|what|when|where|which|adverse|available|please|learn|following|information|"
    r"about|contact|provides?|includes?|works?|conditions?|against|damage|protect(s|ion)?)\b", re.I)
_JOINERS = {"and", "or", "of", "for", "the", "a", "an", "to", "with", "on", "in", "by", "&", "+"}
_BARE_PERIL = {"fire", "hail", "wind", "rain", "freeze", "frost", "replant", "named peril", "crop"}


def _looks_like_product_heading(text: str) -> bool:
    if _PROSE_MARKERS.search(text):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z\-]*", text)
    if not words or len(words) > 6:
        return False
    # >=2 lowercase-initial CONTENT words reads as a sentence, not a product name.
    low = [w for w in words if w[0].islower() and w.lower() not in _JOINERS]
    return len(low) < 2


def _heading_to_product(text: str) -> tuple[str | None, str]:
    """A brochure heading -> (canonical_name, confidence). Reuses the allow-lexicon, but only on
    headings that are product-SHAPED (short, title-like) and not a bare generic peril word."""
    if denied_raw(text) or not _looks_like_product_heading(text):
        return None, ""
    low = text.lower().strip()
    if low in _BARE_PERIL:                          # "Fire"/"Hail" alone is a section label, not a product
        return None, ""
    for pat, name, conf in _ALLOW:
        if pat.search(low):
            return name, conf
    return None, ""


def candidates_from_brochures(conn: sqlite3.Connection) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Parse cached docs linked from products.doc_url; harvest product-named headings."""
    accepted: list[Candidate] = []
    rejected: list[tuple[str, str]] = []
    seen_docs: set[tuple[str, str]] = set()
    rows = conn.execute(
        """SELECT DISTINCT p.aip_code, p.doc_url, u.local_path
           FROM products p JOIN url_cache u ON u.url = p.doc_url
           WHERE p.doc_url IS NOT NULL AND p.aip_code IS NOT NULL
             AND u.http_status = 200 AND u.local_path IS NOT NULL""").fetchall()
    for r in rows:
        aip, url, lp = r["aip_code"], r["doc_url"], r["local_path"]
        if (aip, url) in seen_docs:
            continue
        seen_docs.add((aip, url))
        path = Path(lp)
        if not path.exists():
            continue
        is_pdf = url.lower().split("?")[0].endswith(".pdf")
        headings = _headings_from_pdf(path) if is_pdf else _headings_from_html(path)
        for h in headings:
            name, conf = _heading_to_product(h)
            if not name:
                rejected.append((aip, h))
                continue
            peril, coverage, layer = classify_candidate(name, h)
            accepted.append(Candidate(
                aip_code=aip, name=name, peril_type=peril, coverage_type=coverage,
                source_type="brochure_derived", evidence=url,
                confidence=conf, raw=h, layer=layer))
    return accepted, rejected


# ---------------------------------------------------------------------------
# Assemble: dedup vs catalog + within-set (keep highest confidence, one evidence).
# ---------------------------------------------------------------------------
_CONF_RANK = {"high": 2, "low": 1}


def dedupe(cands: list[Candidate], existing: dict[str, set[str]]) -> list[Candidate]:
    kept: dict[tuple[str, str], Candidate] = {}
    for c in cands:
        if _is_dup(c.name, existing.get(c.aip_code, set())):
            continue
        key = (c.aip_code, norm_key(c.name))
        cur = kept.get(key)
        if cur is None:
            kept[key] = c
        else:
            # prefer higher confidence; prefer serff evidence (tracking #) as more citable
            better = _CONF_RANK[c.confidence] > _CONF_RANK[cur.confidence] or (
                c.confidence == cur.confidence
                and c.source_type == "serff_derived" and cur.source_type != "serff_derived")
            if better:
                kept[key] = c
    return sorted(kept.values(), key=lambda c: (c.aip_code, -_CONF_RANK[c.confidence], c.name))


def build_candidates(conn: sqlite3.Connection):
    serff_ok, serff_rej = candidates_from_serff(conn)
    broch_ok, broch_rej = candidates_from_brochures(conn)
    existing = _existing_index(conn)
    final = dedupe(serff_ok + broch_ok, existing)
    return final, serff_ok, broch_ok, serff_rej, broch_rej


def write_csv(cands: list[Candidate], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        for line in LOADER_NOTE:
            fh.write(line + "\n")
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for c in cands:
            w.writerow(c.row())


# ---------------------------------------------------------------------------
def _main() -> None:
    ap = argparse.ArgumentParser(description="Discover additional private products (review CSV).")
    ap.add_argument("--db", default=str(config.DB_PATH), help="catalog DB (read-only).")
    ap.add_argument("--out", default=str(config.SEED_DIR / "derived_products_candidates.csv"))
    ap.add_argument("--show", action="store_true", help="print accepted + sample rejects.")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    final, serff_ok, broch_ok, serff_rej, broch_rej = build_candidates(conn)
    write_csv(final, Path(args.out))

    per_aip: dict[str, int] = {}
    per_src: dict[str, int] = {}
    for c in final:
        per_aip[c.aip_code] = per_aip.get(c.aip_code, 0) + 1
        per_src[c.source_type] = per_src.get(c.source_type, 0) + 1
    print(f"wrote {len(final)} candidates -> {args.out}")
    print(f"  by source: {per_src}")
    print(f"  by aip:    {dict(sorted(per_aip.items()))}")
    print(f"  raw accepted pre-dedup: serff={len(serff_ok)} brochure={len(broch_ok)}; "
          f"rejected: serff={len(serff_rej)} brochure={len(broch_rej)}")
    if args.show:
        print("\n-- ACCEPTED --")
        for c in final:
            print(f"  {c.aip_code} | {c.confidence:4} | {c.name:42} | {c.peril_type or '-':10} | "
                  f"{c.coverage_type or '-':12} | {c.source_type:16} | {c.raw[:40]!r}")
        print("\n-- sample REJECTED serff titles --")
        for aip, t in serff_rej[:25]:
            print(f"  {aip} | {t!r}")
    conn.close()


if __name__ == "__main__":
    _main()
