

# ── the collapse guard ───────────────────────────────────────────────────────

def test_a_table_losing_most_of_its_rows_is_refused():
    """THE BUG THIS EXISTS FOR: config.ini listed five SERFF states while an ad-hoc harvest
    had loaded twenty-eight, so a routine refresh rebuilt serff_filings with 2,323 rows
    instead of 11,287 and product_states with 373 instead of 1,253.

    Nothing errored. Every test passed. The app rendered. The only symptom was a map quietly
    showing 127 of 182 products as unmapped — and it was found by a human looking at a
    screenshot, which is not a control.
    """
    from scripts.build_app_db import check_no_collapse

    bad = check_no_collapse({"serff_filings": 11287}, {"serff_filings": 2323})
    assert len(bad) == 1 and "79% lost" in bad[0]


def test_ordinary_revision_and_growth_are_not_refused():
    """RMA revises. A guard that fires on normal movement gets disabled, and then guards
    nothing."""
    from scripts.build_app_db import check_no_collapse

    assert check_no_collapse({"t": 1000}, {"t": 950}) == []      # 5% revision
    assert check_no_collapse({"t": 1000}, {"t": 4000}) == []     # growth
    assert check_no_collapse({"t": 1000}, {"t": 1000}) == []


def test_tiny_tables_are_exempt():
    """In a 10-row table one row is 10%, so percentage thresholds are meaningless there."""
    from scripts.build_app_db import check_no_collapse

    assert check_no_collapse({"t": 10}, {"t": 2}) == []


def test_a_vanished_table_is_not_silently_ignored_by_the_shrink_check():
    """A table that disappears entirely is handled by REQUIRED, not here — this pins the
    division of labour so a future edit does not assume this guard covers it."""
    from scripts.build_app_db import REQUIRED, check_no_collapse

    assert check_no_collapse({"gone": 5000}, {}) == []
    assert "serff_filings" in REQUIRED or "sob_national" in REQUIRED


def test_a_deliberate_rollup_is_exempt_from_the_collapse_guard():
    """shrink_prf_max_pct takes prf_max_pct from 142,125 interval rows to 3,071 counties, by
    design — the app reads only MIN(max_pct) per county and the harvest grain was 34 MB of
    the artifact. The generic collapse guard saw a 98% loss and refused the build.

    Exempting it is safe only because the rollup carries its own, TIGHTER assertion: it
    refuses if the county count is not ~3,071, where the guard could only tell that the
    number went down. That pairing is what this test pins.
    """
    import importlib.util
    import inspect
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "_bad", pathlib.Path(__file__).resolve().parents[1] / "scripts/build_app_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert "prf_max_pct" in mod.INTENTIONALLY_ROLLED_UP
    # exempt from the generic guard...
    assert mod.check_no_collapse({"prf_max_pct": 142_125}, {"prf_max_pct": 3_071}) == []
    # ...but any OTHER table collapsing that far still fails it
    assert mod.check_no_collapse({"whatever": 142_125}, {"whatever": 3_071})
    # ...and the rollup has its own floor
    assert "REFUSING" in inspect.getsource(mod.shrink_prf_max_pct)
