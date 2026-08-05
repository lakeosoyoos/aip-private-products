"""Geolocation pass — infer product_states for private products that lack them.

Only a minority of private products carry state availability (product_states). The map can only
paint a product where it knows the product is filed. SERFF filings, however, record WHERE each AIP
files each product: serff_filings has one row per (tracking number, state) with an aip_code and a
product_name (really a filing *title*: "2016 Iowa Replant Premier Forms", "2022 IL CH Form
Filing"). Every filing for an AIP whose title names the same product tells us a state that product
is filed in.

So: for each private product missing states, find the same-AIP filings whose title matches the
product name, and assign the DISTINCT states of those filings. We also honor explicit state lists
and "nationwide" already noted in products.notes / the product name (reusing enrich's parser).

Conservative by design — a wrong state is worse than a missing one:
  * Matching is by NORMALIZED distinctive-token containment, not raw substring. Year prefixes,
    state names/codes, and filing boilerplate (Forms, Rate, Rule, Filing, Endorsement, ...) are
    stripped before comparison so they can never be the thing that "matches".
  * A single common/generic word (crop, coverage, plan, option, ...) can never carry a match: those
    are in the generic stoplist and removed. A single distinctive word only carries a match when it
    is >= 4 letters (so "eco"/"sco"/"gap" alone do not fire); shorter identifiers only match via an
    acronym the product itself declares in parentheses ("Hail Production Plan (HPP)" -> "HPP").
  * Multi-word products require ALL their distinctive tokens present in the filing title, so
    "Replant Premier" does not match a bare "Replant Option" filing and vice-versa.
  * Everything is scoped to the SAME aip_code, so one AIP's filings never leak into another's.
  * Products that match nothing confidently stay empty — honest: they remain "unmapped" on the map.

Nationwide is NOT exploded into 50 rows: webmap._is_nationwide() only checks for the word
"nationwide" in notes, so a nationwide product is recorded as a note (matching enrich's convention)
and left un-painted-per-state.

Provenance is tracked in a companion table (geo_provenance) this module owns and creates on demand
— product_states itself has no source column and db.py is not ours to change. product_states rows
are only ever ADDED (INSERT OR IGNORE), never deleted, so states from the connectors/enrich are
left intact and re-running assigns exactly the same rows (idempotent).

This module owns only itself and its test. It does not write the real catalog.db as part of any
import; callers pass a connection. Run standalone against a copy with `python -m src.geolocate
--db /tmp/geo_test.db`.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Reuse enrich's state vocabulary + note convention so we align with, not fight, the existing
# extractor. enrich.extract_states already guards address/license lines and returns a nationwide
# flag instead of 50 rows.
from . import enrich
from .enrich import _NATIONWIDE_NOTE, _STATE_CODES, STATE_NAMES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
# Filing-title and product-name boilerplate that carries no product identity. Anything here is
# dropped before matching, so it can never be the token that makes two names "match".
GENERIC_TOKENS: frozenset[str] = frozenset({
    # filing vocabulary
    "forms", "form", "rate", "rates", "rule", "rules", "ruling", "filing", "filings", "file",
    "filed", "policy", "policies", "jacket", "jackets", "endorsement", "endorsements",
    "revision", "revisions", "change", "changes", "update", "updates", "logo", "fee", "fees",
    "application", "applications", "extension", "extention", "initial", "under", "only", "class",
    "prov", "rr", "ru", "frr", "fru", "ru2", "f2", "sp",
    # product vocabulary that is descriptive, not identifying
    "coverage", "coverages", "plan", "plans", "option", "options", "policy", "program", "programs",
    "product", "products", "insurance", "insured", "protection", "protect", "tailored", "private",
    "new", "annual", "supplemental", "premier",  # "premier" only generic when standing alone;
    # kept out of core so "Replant Premier" still needs "replant" -- see note below.
    # connectors/glue words
    "and", "or", "the", "of", "for", "a", "an", "with", "including", "also", "available", "in",
})
# NOTE on "premier"/"supplemental": these ARE part of some product names, but they never appear
# ALONE as a product (there is no product just called "Premier"). Keeping them generic means a
# single-word match can't hinge on them, while multi-word products keep their other distinctive
# token (Replant Premier -> "replant"; Supplemental Replant Coverage -> "replant"). Removing them
# slightly loosens two products to their shared "replant" identity, which for *geolocation* (what
# states does this AIP file replant coverage in) is the intended, safe behavior.

# Single-word state names contribute their words as noise (so a filing titled "Iowa ..." doesn't
# let "iowa" match anything). Two-word states contribute both words.
_STATE_WORD_TOKENS: frozenset[str] = frozenset(
    w for name in STATE_NAMES for w in name.split()
) | frozenset(c.lower() for c in _STATE_CODES)

_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_PAREN_RE = re.compile(r"\(([^)]*)\)")

# Tiny, well-established, domain-unambiguous abbreviation expansions applied to FILING titles only
# (never to invent product tokens). In crop insurance "CH" is Crop Hail, full stop; expanding it
# lets a product named "Crop Hail" match an early-year "... CH Form Filing" and pick up that state.
_FILING_ALIASES: dict[str, tuple[str, ...]] = {
    "ch": ("crop", "hail"),
}

_MIN_SINGLE_TOKEN_LEN = 4   # a lone distinctive token must be >= this to carry a match
_MIN_ACRONYM_LEN = 3        # a parenthetical acronym must be >= this to carry a match


def _raw_tokens(s: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT_RE.split((s or "").lower()) if t]


def _is_noise(tok: str) -> bool:
    return (
        len(tok) < 2
        or tok.isdigit()
        or _YEAR_RE.match(tok) is not None
        or tok in GENERIC_TOKENS
        or tok in _STATE_WORD_TOKENS
    )


def distinctive_tokens(s: str) -> set[str]:
    """Content tokens of a name with years, states, digits and boilerplate removed."""
    return {t for t in _raw_tokens(s) if not _is_noise(t)}


def _core_and_paren(name: str) -> tuple[str, str]:
    """Split "Name (BRAND/ACRONYM)" into ("Name", "BRAND/ACRONYM"). Core drives required tokens;
    the parenthetical supplies optional acronyms/brands that need not all be present."""
    paren = " ".join(m.group(1) for m in _PAREN_RE.finditer(name or ""))
    core = _PAREN_RE.sub(" ", name or "")
    return core, paren


def _filing_token_set(title: str) -> set[str]:
    """All tokens of a filing title, alias-expanded (CH -> crop hail). Kept raw (generic words
    included) because containment only ever tests for DISTINCTIVE product tokens, and having the
    generic words present is harmless."""
    out: set[str] = set()
    for t in _raw_tokens(title):
        out.update(_FILING_ALIASES.get(t, (t,)))
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
# Ordered best-first; used both to pick a product's best evidence and to gate acceptance.
_TIER_RANK = {"phrase": 4, "strong": 3, "single": 2, "acronym": 1}


@dataclass
class FilingMatch:
    title: str
    tier: str                       # phrase | strong | single | acronym
    matched_tokens: frozenset[str]


def match_product_to_titles(name: str, titles: list[str]) -> list[FilingMatch]:
    """Return the confident matches of a product name against a list of filing titles.

    Tiers (all accepted; anything below them is *not* returned):
      phrase  - the product's normalized core is a contiguous substring of the title (strongest).
      strong  - the title contains ALL of the product's >= 2 distinctive core tokens.
      single  - the product has exactly one distinctive core token, it is >= 4 letters, present.
      acronym - core tier failed, but a >= 3-letter acronym the product declares in parentheses
                appears as a standalone token in the title.
    """
    core, paren = _core_and_paren(name)
    core_norm = " ".join(_raw_tokens(core))
    required = distinctive_tokens(core)
    acronyms = {t for t in distinctive_tokens(paren) if len(t) >= _MIN_ACRONYM_LEN}

    out: list[FilingMatch] = []
    for title in titles:
        ftok = _filing_token_set(title)
        tier: str | None = None
        matched: frozenset[str] = frozenset()

        if required and required <= ftok:
            if len(required) >= 2:
                tier, matched = "strong", frozenset(required)
            else:
                (tok,) = tuple(required)
                if len(tok) >= _MIN_SINGLE_TOKEN_LEN:
                    tier, matched = "single", frozenset(required)
                # else: single short token -> too weak, leave unmatched

        if tier is None and acronyms:
            hit = acronyms & ftok
            if hit:
                tier, matched = "acronym", frozenset(hit)

        # Upgrade to the strongest tier when the core name appears verbatim in the title.
        if tier is not None and core_norm and core_norm in " ".join(_raw_tokens(title)):
            tier = "phrase"

        if tier is not None:
            out.append(FilingMatch(title=title, tier=tier, matched_tokens=matched))
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
_PROVENANCE_DDL = """
CREATE TABLE IF NOT EXISTS geo_provenance (
    product_id  INTEGER NOT NULL,
    state       TEXT NOT NULL,          -- 2-letter code, or 'NATIONWIDE' for the nationwide flag
    source      TEXT NOT NULL,          -- serff_match | notes | notes_nationwide
    tier        TEXT,                   -- phrase | strong | single | acronym | (null for notes)
    evidence    TEXT,                   -- an example filing title / the note fragment
    created_at  TEXT,
    PRIMARY KEY (product_id, state, source)
);
"""

# Targets: private products with NO state rows at all (the honest gap). We only ever ADD, so
# products that already carry curated/enriched states are left untouched.
_TARGET_SQL = """
SELECT p.product_id, p.name, p.aip_code, p.notes
FROM products p
WHERE p.bucket = 'private'
  AND NOT EXISTS (SELECT 1 FROM product_states s WHERE s.product_id = p.product_id)
ORDER BY p.product_id
"""


@dataclass
class ProductPlan:
    product_id: int
    name: str
    aip_code: str | None
    serff_states: dict[str, tuple[str, str]] = field(default_factory=dict)  # state -> (tier, title)
    notes_states: set[str] = field(default_factory=set)
    nationwide: bool = False
    nationwide_note_needed: bool = False

    @property
    def all_states(self) -> set[str]:
        return set(self.serff_states) | self.notes_states

    @property
    def geolocated(self) -> bool:
        return bool(self.all_states) or self.nationwide


@dataclass
class GeoStats:
    targets: int = 0
    products_geolocated: int = 0          # gained >=1 state OR a (new-or-existing) nationwide flag
    products_via_serff: int = 0
    products_via_notes: int = 0
    products_nationwide: int = 0
    states_rows_added: int = 0            # new product_states rows
    still_unmapped: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    per_aip: dict[str, int] = field(default_factory=dict)   # aip -> products geolocated

    def summary(self) -> str:
        pct = (100.0 * self.products_geolocated / self.targets) if self.targets else 0.0
        tiers = ", ".join(f"{k}:{v}" for k, v in sorted(self.tier_counts.items()))
        return (
            f"geolocate: {self.targets} zero-state private targets, "
            f"{self.products_geolocated} geolocated ({pct:.1f}%), "
            f"{self.still_unmapped} still unmapped | "
            f"via serff={self.products_via_serff}, via notes={self.products_via_notes}, "
            f"nationwide={self.products_nationwide} | +{self.states_rows_added} product_states rows | "
            f"match tiers [{tiers}]"
        )


def _load_titles_by_aip(conn: sqlite3.Connection) -> dict[str, list[str]]:
    by_aip: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT aip_code, product_name FROM serff_filings "
        "WHERE aip_code IS NOT NULL AND aip_code != '' AND product_name IS NOT NULL"
    ):
        by_aip.setdefault(row["aip_code"], []).append(row["product_name"])
    return by_aip


def _states_for_titles(conn: sqlite3.Connection, aip_code: str,
                       titles: set[str]) -> dict[str, set[str]]:
    """title -> set(states) for the given AIP, restricted to the matched titles."""
    result: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT product_name, state FROM serff_filings WHERE aip_code = ?", (aip_code,)
    ):
        if row["product_name"] in titles and row["state"] in _STATE_CODES:
            result.setdefault(row["product_name"], set()).add(row["state"])
    return result


def build_plan(conn: sqlite3.Connection) -> list[ProductPlan]:
    """Compute (without writing) the state assignments for every zero-state private product."""
    titles_by_aip = _load_titles_by_aip(conn)
    plans: list[ProductPlan] = []

    for row in conn.execute(_TARGET_SQL):
        plan = ProductPlan(product_id=row["product_id"], name=row["name"], aip_code=row["aip_code"])

        # (1) SERFF: match the product name against this AIP's filing titles.
        titles = titles_by_aip.get(row["aip_code"] or "", [])
        if titles:
            matches = match_product_to_titles(row["name"], titles)
            if matches:
                title_to_states = _states_for_titles(
                    conn, row["aip_code"], {m.title for m in matches})
                best_for_title = {}
                for m in matches:
                    prev = best_for_title.get(m.title)
                    if prev is None or _TIER_RANK[m.tier] > _TIER_RANK[prev.tier]:
                        best_for_title[m.title] = m
                for title, m in best_for_title.items():
                    for st in title_to_states.get(title, ()):
                        prev = plan.serff_states.get(st)
                        if prev is None or _TIER_RANK[m.tier] > _TIER_RANK[prev[0]]:
                            plan.serff_states[st] = (m.tier, title)

        # (2) notes + name: explicit state lists and nationwide (reuse enrich's guarded parser).
        blob = f"{row['name']}\n{row['notes'] or ''}"
        codes, nationwide = enrich.extract_states(blob)
        plan.notes_states.update(codes)
        if nationwide:
            plan.nationwide = True
            plan.nationwide_note_needed = _NATIONWIDE_NOTE not in (row["notes"] or "")
        elif _NATIONWIDE_NOTE in (row["notes"] or ""):
            # already flagged nationwide by a prior enrich pass — count it, don't re-add.
            plan.nationwide = True

        plans.append(plan)
    return plans


def apply_plan(conn: sqlite3.Connection, plans: list[ProductPlan],
               dry_run: bool = False) -> GeoStats:
    """Write the plan (INSERT OR IGNORE states + provenance + nationwide note). Idempotent."""
    conn.executescript(_PROVENANCE_DDL)
    stats = GeoStats(targets=len(plans))
    now = _now_iso()

    for plan in plans:
        if not plan.geolocated:
            stats.still_unmapped += 1
            continue

        gained_serff = gained_notes = False

        for st, (tier, title) in sorted(plan.serff_states.items()):
            cur = conn.execute(
                "INSERT OR IGNORE INTO product_states (product_id, state) VALUES (?,?)",
                (plan.product_id, st))
            if cur.rowcount > 0:
                stats.states_rows_added += 1
            conn.execute(
                """INSERT OR REPLACE INTO geo_provenance
                   (product_id, state, source, tier, evidence, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (plan.product_id, st, "serff_match", tier, title, now))
            stats.tier_counts[tier] = stats.tier_counts.get(tier, 0) + 1
            gained_serff = True

        for st in sorted(plan.notes_states):
            cur = conn.execute(
                "INSERT OR IGNORE INTO product_states (product_id, state) VALUES (?,?)",
                (plan.product_id, st))
            if cur.rowcount > 0:
                stats.states_rows_added += 1
            conn.execute(
                """INSERT OR REPLACE INTO geo_provenance
                   (product_id, state, source, tier, evidence, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (plan.product_id, st, "notes", None, "explicit state list in notes/name", now))
            gained_notes = True

        if plan.nationwide:
            if plan.nationwide_note_needed:
                conn.execute(
                    "UPDATE products SET notes = COALESCE(notes || ' | ', '') || ? "
                    "WHERE product_id=?",
                    (_NATIONWIDE_NOTE, plan.product_id))
                gained_notes = True
            conn.execute(
                """INSERT OR REPLACE INTO geo_provenance
                   (product_id, state, source, tier, evidence, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (plan.product_id, "NATIONWIDE", "notes_nationwide", None,
                 "nationwide in notes/name", now))
            stats.products_nationwide += 1

        stats.products_geolocated += 1
        if gained_serff:
            stats.products_via_serff += 1
        if gained_notes or plan.notes_states or plan.nationwide:
            if plan.notes_states or plan.nationwide:
                stats.products_via_notes += 1
        stats.per_aip[plan.aip_code or "??"] = stats.per_aip.get(plan.aip_code or "??", 0) + 1

    if dry_run:
        conn.rollback()
    else:
        conn.execute(
            """INSERT INTO fetch_log (source, target, status, rows, started_at, finished_at, message)
               VALUES (?,?,?,?,?,?,?)""",
            ("geolocate", None, "ok", stats.states_rows_added, now, _now_iso(), stats.summary()))
        conn.commit()
    return stats


def run(conn: sqlite3.Connection, dry_run: bool = False) -> GeoStats:
    """Full pass: build the plan, then apply it. Safe to run repeatedly."""
    plans = build_plan(conn)
    return apply_plan(conn, plans, dry_run=dry_run)


def _main() -> None:
    from . import db

    ap = argparse.ArgumentParser(description="Infer product_states for private products via SERFF.")
    ap.add_argument("--db", default=None, help="Path to a catalog DB (default: configured DB).")
    ap.add_argument("--dry-run", action="store_true", help="Compute + report, write nothing.")
    args = ap.parse_args()

    conn = db.connect(args.db)
    try:
        stats = run(conn, dry_run=args.dry_run)
        print(stats.summary())
        if stats.per_aip:
            print("per-AIP geolocated:",
                  ", ".join(f"{k}:{v}" for k, v in sorted(stats.per_aip.items())))
    finally:
        conn.close()


if __name__ == "__main__":
    _main()
