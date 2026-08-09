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
