"""Suite-wide safety rails.

These are set for EVERY test automatically rather than per-test, because the failure they
prevent is one a test author cannot see: it happens inside application code that a render
happens to call, and it leaves no trace in the test's own assertions.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_writes_to_app_data():
    """Stop the test suite from mutating production data files.

    THE INCIDENT THIS PREVENTS: lrp_page renders by fetching rates, recording a snapshot and
    backfilling any missing days — writing to lrp_gap_history.csv as a SIDE EFFECT of drawing
    the page. That is correct in the app. But the suite renders the whole app headlessly to
    check for exceptions, so running the tests grew that file from 1,954 to 5,515 rows.

    The rows were not wrong; that is what made it dangerous. lrp_gap_history.csv is the
    baseline the BUY threshold (MIN_RICHNESS_BUY) is calibrated against, so a test run
    silently moved a production calibration, and the only symptom was a git diff nobody had
    a reason to look at.

    autouse + session scope because the point is that no one has to remember. A per-test
    fixture protects the tests whose authors thought of it, which are exactly the tests that
    did not need protecting.
    """
    os.environ["LRP_HISTORY_READONLY"] = "1"
    yield
    os.environ.pop("LRP_HISTORY_READONLY", None)
