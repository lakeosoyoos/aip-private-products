"""The tab-depth colour scheme, and the selectors it depends on.

Main (product) tabs are blue, sub (view) tabs green. This is CSS against Streamlit's
internal DOM, which is not a public API — so the point of these tests is that a Streamlit
upgrade which renames those hooks FAILS here rather than silently reverting the app to one
colour, which nobody would notice for months.
"""
import pathlib
import re

APP = (pathlib.Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text()


def test_the_two_levels_get_different_colours():
    assert "--tab-main: #1f6feb" in APP      # blue, level 1
    assert "--tab-sub: #1a7f37" in APP       # green, level 2
    assert 'color: var(--tab-main)' in APP
    assert 'color: var(--tab-sub)' in APP


def test_the_sub_rule_is_scoped_by_NESTING_not_by_label():
    """`.stTabs .stTabs` matches a tab list inside a tab list. Keying off nesting rather than
    tab order or label text means the rule cannot be broken by renaming or reordering a tab,
    and a third level would inherit the sub styling rather than reading as top level."""
    assert '.stTabs .stTabs [data-testid="stTab"][aria-selected="true"]' in APP


def test_the_dom_hooks_are_the_ones_this_streamlit_actually_emits():
    """Verified against the rendered page: this version emits div[data-testid="stTab"] and a
    child .react-aria-SelectionIndicator. The older [data-baseweb="tab"] /
    [data-baseweb="tab-highlight"] selectors match NOTHING here and fail silently — which is
    exactly what the first version of this CSS did."""
    assert '[data-testid="stTab"]' in APP
    assert ".react-aria-SelectionIndicator" in APP
    # strip CSS comments first: the note explaining WHY data-baseweb is wrong legitimately
    # mentions it, and a bare substring check flags its own documentation.
    css = re.sub(r"/\*.*?\*/", "", APP, flags=re.S)
    assert "data-baseweb" not in css, "stale selector for this Streamlit version"


def test_both_levels_state_their_own_font_size():
    """Styling only the sub level with a rem value made it LARGER than the parent (theme
    default 14px vs 0.94rem = 15.04px), inverting the hierarchy the colour reinforces. Both
    are stated so the result does not depend on the theme default."""
    main = re.search(r'\.stTabs \[data-testid="stTab"\] \{ font-size: ([\d.]+)rem', APP)
    sub = re.search(r'\.stTabs \.stTabs \[data-testid="stTab"\] \{ font-size: ([\d.]+)rem', APP)
    assert main and sub, "both levels must state a font-size"
    assert float(sub.group(1)) < float(main.group(1)), "sub tabs must be smaller than main"


def test_the_distinction_survives_greyscale():
    """Colour alone excludes some readers. Size carries the same information."""
    assert "font-size" in APP.split(":root { --tab-main")[1][:2000]
