

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
