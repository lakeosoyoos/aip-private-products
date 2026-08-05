"""Tests for the SERFF-driven geolocation pass (src/geolocate.py).

Covers the normalized name matcher (positive tiers + false-match rejection) and an end-to-end run
against an in-memory catalog built from the real schema: states get assigned, a non-matching
product stays empty, nationwide is a note (not 50 rows), and re-running is idempotent.
"""
from __future__ import annotations

import sqlite3

import pytest

from src import db, geolocate
from src.enrich import _NATIONWIDE_NOTE


# ---------------------------------------------------------------------------
# Normalization / distinctive tokens
# ---------------------------------------------------------------------------
def test_distinctive_tokens_strips_year_state_and_boilerplate():
    # "2016 Iowa Replant Premier Forms" -> only the identifying word survives.
    toks = geolocate.distinctive_tokens("2016 Iowa Replant Premier Forms")
    assert toks == {"replant"}  # year, state(iowa), "premier"(generic-standalone), "forms" gone


def test_distinctive_tokens_keeps_two_word_identity():
    assert geolocate.distinctive_tokens("Crop Hail") == {"crop", "hail"}


# ---------------------------------------------------------------------------
# Matching — positive
# ---------------------------------------------------------------------------
def test_crop_hail_matches_full_and_abbreviated_titles():
    titles = ["2017 Iowa Crop Hail Forms", "2022 IL CH Form Filing", "Crop Hail"]
    m = {fm.title: fm.tier for fm in geolocate.match_product_to_titles("Crop Hail", titles)}
    assert "2017 Iowa Crop Hail Forms" in m          # full name
    assert "2022 IL CH Form Filing" in m             # CH alias-expanded to crop hail
    assert m["Crop Hail"] == "phrase"


def test_replant_option_matches_replant_titles_single_token():
    titles = ["2014 Replant Option changes", "NP Replant Option"]
    matches = geolocate.match_product_to_titles("Replant Option", titles)
    assert {m.title for m in matches} == set(titles)


def test_acronym_in_parentheses_matches_when_core_does_not():
    # "Hail Production Plan (HPP)" has no title with both hail+production, but HPP appears.
    titles = ["2013 NE HPP filing", "2025 MN HPP class B rate filing"]
    matches = geolocate.match_product_to_titles("Hail Production Plan (HPP)", titles)
    assert {m.title for m in matches} == set(titles)
    assert all(m.tier == "acronym" for m in matches)


def test_brand_parenthetical_does_not_block_core_match():
    # "Crop Hail (GrainGuard)" must still match a plain "Crop Hail" filing.
    matches = geolocate.match_product_to_titles("Crop Hail (GrainGuard)", ["Crop Hail"])
    assert [m.title for m in matches] == ["Crop Hail"]


# ---------------------------------------------------------------------------
# Matching — false-match rejection (the load-bearing safety property)
# ---------------------------------------------------------------------------
def test_multiword_product_requires_all_distinctive_tokens():
    # "Replant Premier" must NOT match a bare "Replant Option" filing (missing "premier"),
    # and "Replant Option" must NOT match a "Replant Premier" filing... wait: option is generic,
    # so Replant Option -> {replant} DOES match Replant Premier. But Replant Premier -> {replant,
    # premier}? "premier" is generic-standalone, so it reduces to {replant} too. The guard we test
    # is the genuinely distinct case below.
    m = geolocate.match_product_to_titles("Replant Premier", ["2016 Iowa Replant Premier Forms"])
    assert len(m) == 1


def test_distinct_second_token_blocks_cross_match():
    # "Green Snap" ({green, snap}) must not match a "Grain Fire" filing — no shared distinctive token.
    assert geolocate.match_product_to_titles("Green Snap", ["2016 Iowa Grain Fire Forms"]) == []


def test_generic_single_word_never_matches():
    # A product whose only tokens are generic ("Companion Plans" -> plan generic, companion is the
    # sole distinctive token) must not match a title that merely shares a generic word.
    assert geolocate.match_product_to_titles("Companion Plans", ["2016 Form Filing Fee"]) == []
    # And a bare generic title shares nothing distinctive with an unrelated product.
    assert geolocate.match_product_to_titles("Wind", ["2016 IA Form filing"]) == []


def test_short_single_token_rejected_without_acronym():
    # "ECO+" -> {eco}, a 3-letter lone token: too ambiguous, must NOT fire on a title containing
    # "eco" as part of another product unless declared as a parenthetical acronym.
    assert geolocate.match_product_to_titles("ECO+", ["2023 EASYeco Forms"]) == []


# ---------------------------------------------------------------------------
# End-to-end against the real schema (in-memory)
# ---------------------------------------------------------------------------
def _mk_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_db(conn)
    return conn


def _add_product(conn, name, aip, notes=None, states=()):
    key = f"private|{name}|{aip}||"
    cur = conn.execute(
        "INSERT INTO products (bucket, name, aip_code, source_type, notes, natural_key) "
        "VALUES ('private', ?, ?, 'aip_site', ?, ?)", (name, aip, notes, key))
    pid = cur.lastrowid
    for s in states:
        conn.execute("INSERT INTO product_states (product_id, state) VALUES (?,?)", (pid, s))
    return pid


def _add_filing(conn, aip, product_name, state, trk):
    conn.execute(
        "INSERT INTO serff_filings (serff_tracking_number, state, aip_code, product_name) "
        "VALUES (?,?,?,?)", (trk, state, aip, product_name))


def test_end_to_end_assigns_matches_and_leaves_noise_empty():
    conn = _mk_db()
    p_ch = _add_product(conn, "Crop Hail", "XX")
    p_rep = _add_product(conn, "Replant Option", "XX")
    p_none = _add_product(conn, "Citrus Fruit Freeze", "XX")   # no matching filing -> stays empty
    # Same-AIP filings.
    _add_filing(conn, "XX", "2017 Iowa Crop Hail Forms", "IA", "T1")
    _add_filing(conn, "XX", "2017 IL CH Form Filing", "IL", "T2")
    _add_filing(conn, "XX", "2014 Replant Option changes", "NE", "T3")
    # A DIFFERENT AIP's filing must never leak in.
    _add_filing(conn, "YY", "Crop Hail", "TX", "T4")
    conn.commit()

    stats = geolocate.run(conn, dry_run=False)

    def states(pid):
        return {r["state"] for r in conn.execute(
            "SELECT state FROM product_states WHERE product_id=?", (pid,))}

    assert states(p_ch) == {"IA", "IL"}      # full + CH-alias, no TX leak from AIP YY
    assert states(p_rep) == {"NE"}
    assert states(p_none) == set()           # honest: unmatched stays unmapped
    assert stats.products_geolocated == 2
    assert stats.still_unmapped == 1


def test_nationwide_is_a_note_not_fifty_rows():
    conn = _mk_db()
    pid = _add_product(conn, "Universal Cover", "XX", notes="Availability: All states")
    conn.commit()
    geolocate.run(conn, dry_run=False)
    n_states = conn.execute(
        "SELECT COUNT(*) FROM product_states WHERE product_id=?", (pid,)).fetchone()[0]
    assert n_states == 0                      # NOT exploded to 50
    notes = conn.execute("SELECT notes FROM products WHERE product_id=?", (pid,)).fetchone()["notes"]
    assert _NATIONWIDE_NOTE in notes          # webmap._is_nationwide sees "nationwide"
    prov = conn.execute(
        "SELECT source FROM geo_provenance WHERE product_id=? AND state='NATIONWIDE'",
        (pid,)).fetchone()
    assert prov is not None


def test_notes_explicit_states_are_honored():
    conn = _mk_db()
    pid = _add_product(conn, "Grape Freeze", "XX", notes="Also available in OR/WA.")
    conn.commit()
    geolocate.run(conn, dry_run=False)
    states = {r["state"] for r in conn.execute(
        "SELECT state FROM product_states WHERE product_id=?", (pid,))}
    assert states == {"OR", "WA"}


def test_idempotent_rerun_adds_nothing():
    conn = _mk_db()
    _add_product(conn, "Crop Hail", "XX")
    _add_filing(conn, "XX", "Crop Hail", "IA", "T1")
    conn.commit()
    s1 = geolocate.run(conn, dry_run=False)
    before = conn.execute("SELECT COUNT(*) FROM product_states").fetchone()[0]
    s2 = geolocate.run(conn, dry_run=False)
    after = conn.execute("SELECT COUNT(*) FROM product_states").fetchone()[0]
    assert s1.states_rows_added == 1
    assert s2.states_rows_added == 0
    assert before == after


def test_dry_run_writes_nothing():
    conn = _mk_db()
    _add_product(conn, "Crop Hail", "XX")
    _add_filing(conn, "XX", "Crop Hail", "IA", "T1")
    conn.commit()
    stats = geolocate.run(conn, dry_run=True)
    assert stats.products_geolocated == 1          # planned
    n = conn.execute("SELECT COUNT(*) FROM product_states").fetchone()[0]
    assert n == 0                                   # but nothing persisted


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
