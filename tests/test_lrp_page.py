"""Import-only smoke tests for the LRP Signal tab.

These deliberately hit NO network. lrp_signal.py fetches RMA rate files and
the CME/Yahoo futures curve at call time, never at import time, so importing
the module proves the deployed runtime carries scipy/matplotlib/seaborn/
tabulate without touching anything live. That is the whole point of these
tests: on Streamlit Cloud a missing LRP-only dep would otherwise surface as a
traceback inside the tab, not at deploy time.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# lrp_signal imports matplotlib.pyplot at module scope; pin the headless
# backend so the import can never reach for a GUI toolkit under pytest.
os.environ.setdefault("MPLBACKEND", "Agg")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_lrp_signal_imports_with_all_runtime_deps():
    """The engine imports cleanly — i.e. scipy/matplotlib/seaborn/tabulate
    are installed and lrp_signal has no import-time side effects."""
    import lrp_signal

    # A few contract constants lrp_page destructures on import.
    assert lrp_signal.CWT_PER_HEAD > 0
    assert lrp_signal.TENORS_WEEKS == [13, 17, 21, 26, 30, 34, 39, 43, 47, 52]
    # Lowest level RMA publishes is 0.75 — this used to assert 0.70, pinning a level
    # that does not exist. The full set is asserted in tests/test_lrp_premium.py.
    assert lrp_signal.COVERAGE_LEVELS[0] == 0.75
    for name in ("fetch_lrp_current", "fetch_cme_futures_curve", "build_grid",
                 "build_chart_figure", "size_delta_hedge", "sales_today"):
        assert callable(getattr(lrp_signal, name)), name


def test_lrp_page_imports_and_exposes_render():
    """The embeddable page imports cleanly and exposes render()."""
    import lrp_page

    assert callable(lrp_page.render)


def test_lrp_page_sets_no_page_config():
    """The host app owns st.set_page_config — the embedded page must not call
    it, or Streamlit raises StreamlitSetPageConfigMustBeFirstCommandError."""
    # match the CALL, not the module docstring that mentions it by name
    src = (ROOT / "lrp_page.py").read_text()
    assert "st.set_page_config(" not in src


def test_lrp_widget_keys_are_namespaced():
    """Every widget key in the page must carry the lrp_ prefix, so the page
    cannot collide with a host-app widget and raise DuplicateWidgetID."""
    import re

    src = (ROOT / "lrp_page.py").read_text()
    keys = re.findall(r'key\s*=\s*["\']([^"\']+)["\']', src)
    assert keys, "expected keyed widgets in lrp_page.py"
    unprefixed = [k for k in keys if not k.startswith("lrp_")]
    assert not unprefixed, f"un-namespaced widget keys: {unprefixed}"


def test_app_wires_the_lrp_tab():
    """streamlit_app.py exposes the tab and imports lrp_page lazily (inside
    the tab body) so the matplotlib/scipy import cost lands after the
    passcode gate rather than on every cold page load."""
    src = (ROOT / "streamlit_app.py").read_text()
    # The TAB is labelled plainly "LRP" since the bar is product-first (Row Crop /
    # PRF / LRP / DRP); the bull stays as the heading inside the tab body.
    assert '"LRP"' in src, "no LRP tab in the tab list"
    assert "🐂 LRP Signal" in src
    assert "_tab_lrp" in src
    # module-scope import would be a line starting at column 0
    assert "\nimport lrp_page" not in src
    assert "lrp_page.render()" in src


@pytest.mark.parametrize("pkg", ["scipy", "matplotlib", "seaborn", "tabulate"])
def test_lrp_only_deps_present(pkg):
    """These four are LRP-only additions to requirements.txt; assert both that
    they are installed and that the runtime requirements file still lists
    them (a trimmed requirements.txt would break the tab on deploy only)."""
    pytest.importorskip(pkg)
    reqs = (ROOT / "requirements.txt").read_text()
    assert pkg in reqs, f"{pkg} missing from runtime requirements.txt"


def test_lrp_has_an_agency_lens_and_uses_the_TOTAL_premium():
    """LRP had no agency figure at all, and its four tabs are organised by artifact — chart,
    table, history, hedge — rather than by question.

    Commission is a percent of TOTAL premium. LRP's grid carries that directly as
    actuarial_prem, so there is no grossing-up step, but it is emphatically NOT the producer
    premium: applying the rate to what the producer pays would understate commission by the
    whole subsidy, roughly 35% at every coverage level LRP sells.
    """
    import inspect

    import lrp_page

    src = inspect.getsource(lrp_page._render_agency)
    assert 'load_aip_commission(product="LRP")' in src, "must read LRP's own card"
    assert 'g["actuarial_prem"] * pct / 100.0' in src, "commission is on TOTAL premium"
    assert "producer_prem" not in src.split("comm_cwt")[0].split("actuarial_prem")[-1]
    assert "No LRP commission rate on file" in src and "LPRA" in src


def test_the_agency_lens_names_the_producers_best_cell_too():
    """Commission tracks premium, so agency revenue peaks at the highest coverage and longest
    tenor — which is not where return per producer dollar peaks. The lens says both."""
    import inspect

    import lrp_page

    src = inspect.getsource(lrp_page._render_agency)
    assert 'g["ret_mkt"].idxmax()' in src
    assert "producer's best cell is elsewhere" in src


def test_the_measured_return_is_stated_not_just_the_modelled_one():
    """0.66x is what LRP actually returned nationally, 2005-2026. The modelled columns are
    what today's rate card implies; a page that showed only those would read as a
    recommendation."""
    import lrp_page

    assert "0.66x" in lrp_page.LRP_MEASURED_NOTE
    assert "Summary of Business" in lrp_page.LRP_MEASURED_NOTE
    assert "0.09x" in lrp_page.LRP_MEASURED_NOTE      # and the range, not just the average
