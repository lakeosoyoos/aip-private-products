"""Unit tests for the rma_sob parsing/mapping/aggregation helpers — no network, no downloads."""
from __future__ import annotations

import sqlite3

import pytest

from src import db
from src.connectors import rma_sob


def _cov_line(*, plan, commodity, state="19", county="169", state_abbrev="IA",
              policies="1", qty_type="Acres", net="0", endorsed="0", liability="0",
              premium="0", subsidy="0", indemnity="0", plan_abbrev="XX",
              category="A", level=".7500"):
    """Build one 28-field pipe-delimited sobcov line with the fields the connector reads."""
    f = ["2026", state, state_abbrev, county, "County Name", commodity, "Crop", plan,
         plan_abbrev, category, "RBUP", level, policies, policies, "0", "0", "0", qty_type,
         net, endorsed, liability, premium, subsidy, "0", "0", "0", indemnity, ".00"]
    assert len(f) == len(rma_sob.SOBCOV_FIELDS)
    return "|".join(f)


def _tpu_line(*, plan, commodity, unit="OU", state="19", county="169", state_abbrev="IA",
              qty_type="Acres", net="0", endorsed="0", liability="0", premium="0",
              subsidy="0", indemnity="0", plan_abbrev="XX", category="A", level=".7500"):
    """Build one 27-field pipe-delimited sobtpu line (the variant that carries unit structure)."""
    f = ["2024", state, "Iowa", state_abbrev, county, "County Name", commodity, "Crop", plan,
         plan_abbrev, category, level, "R", "000", "No Type Specified", "000",
         "No Practice Specified", unit, "Optional Unit", net, qty_type, liability, premium,
         subsidy, indemnity, ".00", endorsed]
    assert len(f) == len(rma_sob.SOBTPU_FIELDS)
    return "|".join(f)


# ---------------------------------------------------------------------------
# record framing: sobcov is CRLF, sobtpu is a BARE CR
# ---------------------------------------------------------------------------

def test_iter_records_splits_crlf_lf_and_bare_cr():
    assert list(rma_sob.iter_records([b"a|b\r\nc|d\r"])) == ["a|b", "c|d"]
    assert list(rma_sob.iter_records([b"a|b\nc|d"])) == ["a|b", "c|d"]
    # The sobtpu framing: CR only. Naive line iteration would return a single record.
    assert list(rma_sob.iter_records([b"a|b\rc|d\re|f"])) == ["a|b", "c|d", "e|f"]


def test_iter_records_reassembles_records_split_across_chunks():
    chunks = [b"2024|01|Alab", b"ama\r2024|02|Alaska\r"]
    assert list(rma_sob.iter_records(chunks)) == ["2024|01|Alabama", "2024|02|Alaska"]


def test_iter_records_skips_blank_records():
    assert list(rma_sob.iter_records([b"a\r\r\rb\r"])) == ["a", "b"]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def test_parse_sob_rows_positional():
    rows = list(rma_sob.parse_sob_rows([_cov_line(plan="31", commodity="0041"), "", "\n"]))
    assert len(rows) == 1
    r = rows[0]
    assert r["plan_code"] == "31"
    assert r["commodity_code"] == "0041"
    assert r["state_abbrev"] == "IA"
    assert r["coverage_level"] == ".7500"


def test_parse_sob_rows_tpu_layout():
    rows = list(rma_sob.parse_sob_rows([_tpu_line(plan="02", commodity="0041", unit="EU")],
                                       rma_sob.SOBTPU_FIELDS))
    r = rows[0]
    assert r["plan_code"] == "02"
    assert r["state_abbrev"] == "IA"
    assert r["unit_structure"] == "EU"
    assert r["quantity_type"] == "Acres"


def test_parse_sob_rows_skips_short_lines():
    assert list(rma_sob.parse_sob_rows(["a|b|c"])) == []


def test_number_coercion():
    assert rma_sob._to_float("") == 0.0
    assert rma_sob._to_float(None) == 0.0
    assert rma_sob._to_float("junk") == 0.0
    assert rma_sob._to_float("1234.5") == 1234.5
    assert rma_sob._to_int("15297.0") == 15297


# ---------------------------------------------------------------------------
# net-acres rule (base plan vs endorsement vs non-acre quantity)
# ---------------------------------------------------------------------------

def test_sob_net_acres_base_plan_uses_net():
    row = {"quantity_type": "Acres", "net_reported_quantity": "11316275",
           "endorsed_companion_acres": "0"}
    assert rma_sob.sob_net_acres(row) == 11316275.0


def test_sob_net_acres_endorsement_uses_endorsed():
    row = {"quantity_type": "Acres", "net_reported_quantity": "0",
           "endorsed_companion_acres": "3338541"}
    assert rma_sob.sob_net_acres(row) == 3338541.0


def test_sob_net_acres_non_acre_quantity_is_zero():
    # Tons/Head/Colonies/Trees rows must not leak into an "acres" total.
    row = {"quantity_type": "Tons", "net_reported_quantity": "500",
           "endorsed_companion_acres": "0"}
    assert rma_sob.sob_net_acres(row) == 0.0


# ---------------------------------------------------------------------------
# THE BUG: the catalog product map must LABEL, never GATE
# ---------------------------------------------------------------------------

def _std_maps():
    # SCO 31/32/33 -> product 3; MP 16/17 -> product 1 (Spring Wheat); WFRP 76 -> product 7.
    plan_to_pid = {"31": 3, "32": 3, "33": 3, "16": 1, "17": 1, "76": 7, "35": 2}
    product_crop_set = {(3, "Corn"), (3, "Wheat"), (1, "Spring Wheat"),
                        (7, "All crops (whole-farm)"), (2, "Cotton")}
    return plan_to_pid, product_crop_set


@pytest.mark.parametrize("plan", ["01", "02", "03", "90", "44", "45", "25", "42"])
def test_base_plans_are_kept_even_though_no_catalog_product_has_them(plan):
    """Regression: YP/RP/RPHPE/APH/RA/CRC are the bulk of the row-crop market and have no
    508(h) catalog product. The old connector filtered on the catalog plan map and dropped
    every one of them, leaving a table of endorsements only."""
    plan_to_pid, crops = _std_maps()
    assert plan not in plan_to_pid
    assert rma_sob.sob_crop(plan, "0041", plan_to_pid, crops) == "Corn"


def test_sob_crop_drops_non_row_crops():
    plan_to_pid, crops = _std_maps()
    assert rma_sob.sob_crop("02", "0054", plan_to_pid, crops) is None   # apples
    assert rma_sob.sob_crop("81", "0801", plan_to_pid, crops) is None   # LRP feeder cattle
    assert rma_sob.sob_crop("13", "0088", plan_to_pid, crops) is None   # PRF pasture


def test_sob_crop_spring_wheat_relabel_is_label_only():
    plan_to_pid, crops = _std_maps()
    # MP (plan 16) maps to a product whose product_crops says Spring Wheat, so wheat relabels.
    assert rma_sob.sob_crop("16", "0011", plan_to_pid, crops) == "Spring Wheat"
    # A base plan on the same commodity stays plain Wheat...
    assert rma_sob.sob_crop("02", "0011", plan_to_pid, crops) == "Wheat"
    # ...and with no catalog maps supplied at all, nothing is dropped and nothing relabels.
    assert rma_sob.sob_crop("16", "0011") == "Wheat"
    assert rma_sob.sob_crop("02", "0011") == "Wheat"


def test_sob_crop_wfrp_pseudo_crop():
    plan_to_pid, crops = _std_maps()
    assert rma_sob.sob_crop("76", "0076", plan_to_pid, crops) == "All crops (whole-farm)"
    assert rma_sob.sob_crop("76", "9110", plan_to_pid, crops) is None   # Micro Farm


# ---------------------------------------------------------------------------
# canonicalisation + aggregation
# ---------------------------------------------------------------------------

def test_canonical_records_from_sobcov():
    lines = [_cov_line(plan="2", commodity="0041", net="100", liability="1000", premium="80",
                       subsidy="48", indemnity="120", plan_abbrev="RP", level=".8000")]
    rec = next(rma_sob.canonical_records(rma_sob.parse_sob_rows(lines), 2026))
    assert rec.plan_code == "02" and rec.plan_abbrev == "RP"
    assert rec.state == "IA" and rec.county_fips == "19169"
    assert rec.crop == "Corn" and rec.commodity_code == "0041"
    assert rec.coverage_type == "A" and rec.coverage_level == 0.80
    assert rec.unit_structure == "NA"          # sobcov does not publish it
    assert rec.net_acres == 100.0 and rec.liability == 1000.0
    assert rec.producer_premium == 32.0        # 80 total premium - 48 subsidy
    assert rec.policies_sold == 1


def test_canonical_records_from_sobtpu_carry_unit_structure():
    lines = [_tpu_line(plan="02", commodity="0081", unit="EU", net="50", liability="900",
                       premium="70", subsidy="40", indemnity="10")]
    rec = next(rma_sob.canonical_records(rma_sob.parse_sob_rows(lines, rma_sob.SOBTPU_FIELDS),
                                         2024))
    assert rec.crop == "Soybeans" and rec.unit_structure == "EU"
    assert rec.liability == 900.0 and rec.producer_premium == 30.0
    # The tpu file has no policy counts; they must read as 0, not crash.
    assert rec.policies_sold == 0


def test_accumulator_sums_into_grain_and_separates_coverage_levels():
    lines = [
        _cov_line(plan="02", commodity="0041", level=".8000", liability="100", premium="20",
                  policies="5", endorsed="1000"),
        _cov_line(plan="02", commodity="0041", level=".8000", liability="50", premium="10",
                  policies="3", endorsed="500"),
        # Same county/crop/plan, DIFFERENT coverage level -> its own row.
        _cov_line(plan="02", commodity="0041", level=".8500", liability="25", premium="5",
                  policies="2", endorsed="200"),
        # CAT coverage of the same plan -> its own row again (coverage_type differs).
        _cov_line(plan="02", commodity="0041", level=".5000", category="C", liability="9",
                  premium="1", policies="1", endorsed="10"),
    ]
    acc = rma_sob.Accumulator(rma_sob.GRAIN_COUNTY)
    n = acc.add_all(rma_sob.canonical_records(rma_sob.parse_sob_rows(lines), 2026))
    assert n == 4 and len(acc) == 3
    by_key = {k: t for k, _tags, t in acc.rows()}
    at80 = by_key[(2026, "IA", "19169", "Corn", "02", "A", 0.80)]
    assert at80["liability"] == 150.0 and at80["total_premium"] == 30.0
    assert at80["net_acres"] == 1500.0 and at80["policies_sold"] == 8
    assert (2026, "IA", "19169", "Corn", "02", "C", 0.50) in by_key


def test_accumulator_national_grain_drops_geography():
    lines = [_cov_line(plan="02", commodity="0041", state="19", state_abbrev="IA",
                       liability="100"),
             _cov_line(plan="02", commodity="0041", state="17", state_abbrev="IL",
                       county="019", liability="300")]
    acc = rma_sob.Accumulator(rma_sob.GRAIN_NATIONAL)
    acc.add_all(rma_sob.canonical_records(rma_sob.parse_sob_rows(lines), 2026))
    assert len(acc) == 1
    (_key, _tags, tot), = acc.rows()
    assert tot["liability"] == 400.0


def test_accumulator_unit_grain_splits_by_unit_structure():
    lines = [_tpu_line(plan="02", commodity="0041", unit="EU", liability="100"),
             _tpu_line(plan="02", commodity="0041", unit="OU", liability="40"),
             _tpu_line(plan="02", commodity="0041", unit="EU", county="001", liability="60")]
    acc = rma_sob.Accumulator(rma_sob.GRAIN_UNIT_STATE)
    acc.add_all(rma_sob.canonical_records(
        rma_sob.parse_sob_rows(lines, rma_sob.SOBTPU_FIELDS), 2024))
    got = {k[-1]: t["liability"] for k, _tags, t in acc.rows()}
    assert got == {"EU": 160.0, "OU": 40.0}     # counties collapse, unit structures do not


# ---------------------------------------------------------------------------
# the two ratios
# ---------------------------------------------------------------------------

def test_loss_ratio_and_per_producer_dollar():
    assert rma_sob.loss_ratio(120.0, 100.0) == pytest.approx(1.20)
    assert rma_sob.loss_ratio(120.0, 0.0) is None
    # $100 premium, $60 subsidy -> the producer paid $40; $120 back is $3.00 per own dollar.
    assert rma_sob.indemnity_per_producer_dollar(120.0, 100.0, 60.0) == pytest.approx(3.0)
    # A fully subsidised row has no producer denominator at all.
    assert rma_sob.indemnity_per_producer_dollar(120.0, 100.0, 100.0) is None
    assert rma_sob.indemnity_per_producer_dollar(0.0, 0.0, 0.0) is None


# ---------------------------------------------------------------------------
# schema + reporting against a real (in-memory) DB
# ---------------------------------------------------------------------------

def _mem_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def _seed_national(conn, rows):
    conn.executemany(
        "INSERT INTO sob_national (year, crop, plan_code, plan_abbrev, coverage_type, "
        "coverage_level, liability, total_premium, subsidy, producer_premium, indemnity, "
        "policies_sold) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def test_new_tables_exist_with_the_two_dials():
    conn = _mem_db()
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sob_sales", "sob_national", "sob_unit", "sob_unit_national",
            "sob_year"} <= have
    sales = {r[1] for r in conn.execute("PRAGMA table_info(sob_sales)")}
    assert {"coverage_type", "coverage_level", "producer_premium"} <= sales
    unit = {r[1] for r in conn.execute("PRAGMA table_info(sob_unit)")}
    assert "unit_structure" in unit


def test_sob_sales_primary_key_separates_coverage_levels():
    conn = _mem_db()
    base = ("IA", "19169", "Corn", "02", "A")
    conn.execute("INSERT INTO sob_sales (year, state, county_fips, crop, plan_code, "
                 "coverage_type, coverage_level, liability) VALUES (?,?,?,?,?,?,?,?)",
                 (2024, *base, 0.80, 100.0))
    conn.execute("INSERT INTO sob_sales (year, state, county_fips, crop, plan_code, "
                 "coverage_type, coverage_level, liability) VALUES (?,?,?,?,?,?,?,?)",
                 (2024, *base, 0.85, 200.0))
    assert conn.execute("SELECT COUNT(*) FROM sob_sales").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sob_sales (year, state, county_fips, crop, plan_code, "
                     "coverage_type, coverage_level, liability) VALUES (?,?,?,?,?,?,?,?)",
                     (2024, *base, 0.85, 5.0))


def test_migrate_sob_sales_carries_legacy_rows_forward():
    """An existing catalog.db has the pre-coverage-level table; init_db must rebuild it."""
    conn = db.connect(":memory:")
    conn.executescript("""
        CREATE TABLE sob_sales (
            year INTEGER NOT NULL, state TEXT NOT NULL, county_fips TEXT NOT NULL,
            crop TEXT NOT NULL, commodity_code TEXT, plan_code TEXT NOT NULL,
            plan_abbrev TEXT, net_acres REAL, liability REAL, total_premium REAL,
            subsidy REAL, indemnity REAL, policies_sold INTEGER, source TEXT,
            fetched_at TEXT,
            PRIMARY KEY (year, state, county_fips, crop, plan_code));
        INSERT INTO sob_sales VALUES
            (2026,'IA','19169','Corn','0041','32','SCO-RP',10,100,20,12,0,3,'sobcov_2026','t');
    """)
    conn.commit()
    db.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sob_sales)")}
    assert {"coverage_type", "coverage_level", "producer_premium"} <= cols
    row = conn.execute("SELECT * FROM sob_sales").fetchone()
    assert row["plan_code"] == "32" and row["liability"] == 100
    assert row["coverage_type"] == "ALL" and row["coverage_level"] == 0
    assert row["producer_premium"] == 8      # 20 premium - 12 subsidy
    assert not conn.execute("SELECT name FROM sqlite_master WHERE "
                            "name='sob_sales_pre_coverage_level'").fetchall()
    # Idempotent: running it again is a no-op.
    assert db.migrate_sob_sales(conn) is None


def test_experience_by_plan_and_coverage_level_excludes_unsettled_years():
    conn = _mem_db()
    _seed_national(conn, [
        # settled year: RP at 0.85 pays 1.20x premium, 3.00x the producer's own money
        (2023, "Corn", "02", "RP", "A", 0.85, 1000.0, 100.0, 60.0, 40.0, 120.0, 7),
        (2023, "Corn", "01", "YP", "A", 0.75, 500.0, 50.0, 27.5, 22.5, 25.0, 3),
        # open year: premium booked, no indemnity yet -> must not drag the ratios down
        (2026, "Corn", "02", "RP", "A", 0.85, 9000.0, 900.0, 540.0, 360.0, 0.0, 9),
    ])
    conn.executemany("INSERT INTO sob_year (year, settled) VALUES (?,?)",
                     [(2023, 1), (2026, 0)])
    conn.commit()

    by_plan = {r["grp"]: r for r in rma_sob.experience_by(conn, "plan_code")}
    assert set(by_plan) == {"01", "02"}
    assert by_plan["02"]["total_premium"] == 100.0            # the open year is excluded
    assert by_plan["02"]["loss_ratio"] == pytest.approx(1.20)
    assert by_plan["02"]["indemnity_per_producer_dollar"] == pytest.approx(3.0)
    assert by_plan["01"]["loss_ratio"] == pytest.approx(0.50)

    # ...and including the open year visibly destroys the ratio, which is why the gate exists.
    open_too = {r["grp"]: r for r in rma_sob.experience_by(conn, "plan_code",
                                                          settled_only=False)}
    assert open_too["02"]["loss_ratio"] == pytest.approx(120.0 / 1000.0)

    by_level = {r["grp"]: r for r in rma_sob.experience_by(conn, "coverage_level")}
    assert set(by_level) == {0.75, 0.85}
    assert by_level["0.85" if "0.85" in by_level else 0.85]["indemnity"] == 120.0


def test_experience_by_rejects_an_unknown_dimension():
    conn = _mem_db()
    with pytest.raises(ValueError):
        rma_sob.experience_by(conn, "county_fips")


def test_experience_by_year_window_and_min_premium():
    conn = _mem_db()
    _seed_national(conn, [
        (2010, "Corn", "02", "RP", "A", 0.80, 100.0, 10.0, 6.0, 4.0, 5.0, 1),
        (2020, "Corn", "02", "RP", "A", 0.80, 900.0, 90.0, 54.0, 36.0, 45.0, 9),
        (2020, "Rye", "01", "YP", "A", 0.65, 3.0, 1.0, 0.5, 0.5, 0.4, 1),
    ])
    conn.executemany("INSERT INTO sob_year (year, settled) VALUES (?,?)",
                     [(2010, 1), (2020, 1)])
    conn.commit()
    got = rma_sob.experience_by(conn, "crop", year_min=2015)
    assert {r["grp"] for r in got} == {"Corn", "Rye"}
    assert next(r for r in got if r["grp"] == "Corn")["total_premium"] == 90.0
    # min_premium filters the long tail of tiny crop/plan cells whose ratios are noise
    assert {r["grp"] for r in rma_sob.experience_by(conn, "crop", year_min=2015,
                                                   min_premium=10.0)} == {"Corn"}


def _seed_unit(conn):
    conn.executemany(
        "INSERT INTO sob_unit (year, state, crop, commodity_code, plan_code, plan_abbrev, "
        "coverage_type, coverage_level, unit_structure, net_acres, liability, total_premium, "
        "subsidy, producer_premium, indemnity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(2023, "IA", "Corn", "0041", "02", "RP", "A", 0.85, "EU", 10, 500.0, 40.0, 28.0,
          12.0, 20.0),
         (2023, "IL", "Corn", "0041", "02", "RP", "A", 0.85, "EU", 10, 300.0, 20.0, 12.0,
          8.0, 10.0),
         (2023, "IA", "Corn", "0041", "02", "RP", "A", 0.85, "OU", 10, 200.0, 40.0, 24.0,
          16.0, 60.0),
         (2026, "IA", "Corn", "0041", "02", "RP", "A", 0.85, "EU", 10, 900.0, 90.0, 54.0,
          36.0, 0.0)])
    conn.executemany("INSERT INTO sob_year (year, settled) VALUES (?,?)",
                     [(2023, 1), (2026, 0)])
    conn.commit()


def test_rollup_unit_national_sums_states_and_stores_both_ratios():
    conn = _mem_db()
    _seed_unit(conn)
    assert rma_sob.rollup_unit_national(conn, 2023, source="sobtpu_2023", fetched_at="t") == 2
    rows = {r["unit_structure"]: dict(r) for r in
            conn.execute("SELECT * FROM sob_unit_national WHERE year = 2023")}
    assert rows["EU"]["liability"] == 800.0            # IA + IL collapsed
    assert rows["EU"]["plan_abbrev"] == "RP" and rows["EU"]["commodity_code"] == "0041"
    assert rows["EU"]["loss_ratio"] == pytest.approx(30.0 / 60.0)
    assert rows["EU"]["indemnity_per_producer_dollar"] == pytest.approx(30.0 / 20.0)
    assert rows["OU"]["liability"] == 200.0
    # Re-running one year replaces that year only, and leaves other years alone.
    rma_sob.rollup_unit_national(conn, 2026, source="sobtpu_2026", fetched_at="t")
    rma_sob.rollup_unit_national(conn, 2023, source="sobtpu_2023", fetched_at="t")
    assert conn.execute("SELECT COUNT(*) FROM sob_unit_national").fetchone()[0] == 3
    # A year with no premium gets NULL ratios rather than a divide-by-zero.
    conn.execute("INSERT INTO sob_unit (year, state, crop, plan_code, coverage_type, "
                 "coverage_level, unit_structure, total_premium, subsidy, producer_premium, "
                 "indemnity) VALUES (2027,'IA','Corn','02','A',0.85,'EU',0,0,0,0)")
    rma_sob.rollup_unit_national(conn, 2027, source="sobtpu_2027", fetched_at="t")
    r = conn.execute("SELECT * FROM sob_unit_national WHERE year = 2027").fetchone()
    assert r["loss_ratio"] is None and r["indemnity_per_producer_dollar"] is None


def test_experience_by_unit_structure():
    conn = _mem_db()
    _seed_unit(conn)
    for y in (2023, 2026):
        rma_sob.rollup_unit_national(conn, y, source=f"sobtpu_{y}", fetched_at="t")
    conn.commit()
    got = {r["grp"]: r for r in rma_sob.experience_by_unit_structure(conn)}
    assert set(got) == {"EU", "OU"}                    # the open 2026 year is excluded
    assert got["EU"]["loss_ratio"] == pytest.approx(0.50)
    assert got["OU"]["indemnity_per_producer_dollar"] == pytest.approx(60.0 / 16.0)
    # The state-grain table must give the same national answer.
    state = {r["grp"]: r for r in
             rma_sob.experience_by_unit_structure(conn, table="sob_unit")}
    assert state["EU"]["loss_ratio"] == pytest.approx(got["EU"]["loss_ratio"])
    assert state["EU"]["liability"] == got["EU"]["liability"]
    with pytest.raises(ValueError):
        rma_sob.experience_by_unit_structure(conn, table="sob_sales")


def test_mark_settled_years_holds_back_the_still_developing_years():
    """Nonzero indemnity is NOT proof a year is done: 2025 and 2026 both had claims on the books
    and both were far too clean to measure returns from."""
    conn = _mem_db()
    conn.executemany("INSERT INTO sob_year (year, indemnity, loss_ratio) VALUES (?,?,?)",
                     [(2022, 15.1e9, 0.98), (2023, 13.5e9, 0.93), (2024, 11.3e9, 0.91),
                      (2025, 7.1e9, 0.55), (2026, 1.0e9, 0.08)])
    conn.commit()
    assert rma_sob.mark_settled_years(conn) == [2025, 2026]
    settled = {r[0] for r in conn.execute("SELECT year FROM sob_year WHERE settled = 1")}
    assert settled == {2022, 2023, 2024}
    # Re-running recomputes rather than accumulating, and a year with no losses never settles.
    conn.execute("INSERT INTO sob_year (year, indemnity) VALUES (2021, 0)")
    conn.commit()
    assert 2021 in rma_sob.mark_settled_years(conn)


def test_rows_per_year_reads_the_manifest():
    conn = _mem_db()
    conn.executemany(
        "INSERT INTO sob_year (year, sob_sales_rows, sob_national_rows, sob_unit_rows, plans, "
        "liability, total_premium, subsidy, indemnity, loss_ratio, settled) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(2024, 10, 5, 4, 12, 1.0, 2.0, 3.0, 4.0, 0.5, 1),
         (2023, 20, 6, 5, 11, 1.0, 2.0, 3.0, 4.0, 0.5, 1)])
    conn.commit()
    got = rma_sob.rows_per_year(conn)
    assert [r["year"] for r in got] == [2023, 2024]
    assert got[1]["sob_sales_rows"] == 10 and got[1]["plans"] == 12


# ---------------------------------------------------------------- livestock gate
def test_livestock_plans_are_admitted_and_gated_on_the_plan_not_the_commodity():
    """LRP/LGM/DRP were invisible: ADM_ROW_CROP_CODES has no 0803/0815/0847, so every
    livestock row fell through to None. LGM in particular did not exist in this project."""
    from src.connectors.rma_sob import sob_crop

    assert sob_crop("82", "0803") == "Cattle"
    assert sob_crop("82", "0815") == "Swine"
    assert sob_crop("82", "0847") == "Dairy Cattle"
    assert sob_crop("81", "0803") == "Cattle"      # LRP
    assert sob_crop("83", "0847") == "Dairy Cattle"  # DRP


def test_a_livestock_commodity_under_a_crop_plan_is_still_dropped():
    """The gate is the PLAN. A cattle commodity code arriving on a row-crop plan is a
    malformed row, not livestock, and must not be admitted by the new branch."""
    from src.connectors.rma_sob import sob_crop

    assert sob_crop("02", "0803") is None
    assert sob_crop("01", "0847") is None


def test_unclassified_livestock_is_labelled_not_dropped_and_not_invented():
    """68% of 2024 and 80% of 2026 plan-82 premium is filed under 9999 'All Other
    Commodities'. Dropping it discards four fifths of recent LGM; guessing a commodity
    invents a split RMA never published. It must survive under an obviously-unclassified
    label so the volume stays visible."""
    from src.connectors.rma_sob import sob_crop, LIVESTOCK_COMMODITY_CODES

    got = sob_crop("82", "9999")
    assert got is not None, "unclassified LGM was dropped"
    assert got not in LIVESTOCK_COMMODITY_CODES.values(), "9999 was folded into a real commodity"
    assert "unclassified" in got.lower()


def test_row_crops_are_completely_unaffected_by_the_livestock_branch():
    """The base-plan bug cost this project the entire row-crop market once already."""
    from src.connectors.rma_sob import sob_crop

    for plan in ("01", "02", "03", "90", "44", "32", "88"):
        assert sob_crop(plan, "0041") == "Corn"
        assert sob_crop(plan, "0081") == "Soybeans"
