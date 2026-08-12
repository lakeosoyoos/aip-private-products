"""The tab-depth colour scheme, and the selectors it depends on.

Main (product) tabs are blue, sub (view) tabs green. This is CSS against Streamlit's
internal DOM, which is not a public API — so the point of these tests is that a Streamlit
upgrade which renames those hooks FAILS here rather than silently reverting the app to one
colour, which nobody would notice for months.
"""
import pathlib
import re

APP = (pathlib.Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text()


def test_the_two_levels_get_different_coloured_BARS():
    """Filled bars, not tinted text. On a white page a row of coloured words does not read as
    a control — the eye has to hunt for it — which is the complaint this answers."""
    assert "--tab-main: #1a63d8" in APP      # blue, level 1
    assert "--tab-sub: #1a7f37" in APP       # green, level 2
    assert "background: var(--tab-main)" in APP
    assert "background: var(--tab-sub)" in APP


def test_labels_stay_full_white_and_the_bars_clear_AA():
    """Contrast measured in the browser, not eyeballed: 5.50:1 blue, 5.08:1 green, against the
    4.5:1 AA threshold for normal text. Every label is pure white and the SELECTED tab is
    marked by weight plus a translucent pill — deliberately not by dimming the others, since
    dimming is exactly what would drop unselected labels under the threshold. It also keeps
    the distinction readable in greyscale.
    """
    def contrast(hexstr):
        n = int(hexstr.lstrip("#"), 16)
        ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
        f = [(v / 255) / 12.92 if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4
             for v in ch]
        lum = 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
        return 1.05 / (lum + 0.05)

    for var in ("--tab-main", "--tab-sub"):
        hexstr = re.search(rf"{var}: (#[0-9a-fA-F]{{6}})", APP).group(1)
        assert contrast(hexstr) >= 4.5, f"{var} {hexstr} is {contrast(hexstr):.2f}:1, under AA"

    assert "color: #fff;" in APP
    assert "font-weight: 700" in APP          # selected marked by weight
    assert "rgba(255,255,255,0.20)" in APP    # ...and a pill, not by dimming others


def test_the_sub_rule_is_scoped_by_NESTING_not_by_label():
    """`.stTabs .stTabs` matches a tab list inside a tab list. Keying off nesting rather than
    tab order or label text means the rule cannot be broken by renaming or reordering a tab,
    and a third level would inherit the sub styling rather than reading as top level."""
    assert '.stTabs .stTabs [role="tablist"]' in APP
    assert '.stTabs .stTabs [data-testid="stTab"]' in APP


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
    def size_in(selector):
        # the rule body may hold several properties, so scan the block rather than assume
        i = APP.index(selector + " {")
        block = APP[i:APP.index("}", i)]
        m = re.search(r"font-size: ([\d.]+)rem", block)
        return float(m.group(1)) if m else None

    main = size_in('.stTabs [data-testid="stTab"]')
    sub = size_in('.stTabs .stTabs [data-testid="stTab"]')
    assert main and sub, "both levels must state a font-size"
    assert sub < main, f"sub tabs ({sub}rem) must be smaller than main ({main}rem)"


def test_the_distinction_survives_greyscale():
    """Colour alone excludes some readers. Size carries the same information."""
    assert "font-size" in APP.split(":root { --tab-main")[1][:2000]


def test_the_lens_looks_the_same_on_every_product():
    """Five products, two implementations, one appearance.

    PRF, row crop and DRP carry the lens INSIDE their map, because switching a Streamlit
    widget would rerun and re-emit an iframe up to 31 MB. LGM and LRP have no iframe and use
    the native widget. The two cannot be shared, so they are matched: the same joined-pill
    shape and the same ink-on-white active state.

    And deliberately NOT the green the filter controls use. Every other .seg on those maps
    selects a value within the current view; the lens changes whose numbers the whole page
    shows. Same shape, different weight, so the eye does not file it with the filters.
    """
    import pathlib as _p

    root = _p.Path(__file__).resolve().parents[1]

    for f in ("src/prfpage.py", "src/rowcroppage.py", "src/drppage.py"):
        src = (root / f).read_text()
        assert "#lensSeg button.on { background: var(--ink); color: #fff;" in src, f
        assert '.seg button.on { background: #238b45' in src, (
            f"{f}: the filter segs should stay green — the lens is what differs")

    # the two no-iframe tabs use the widget that matches that shape
    for f in ("src/lgmpage.py", "lrp_page.py"):
        src = (root / f).read_text()
        assert "st.segmented_control(" in src, f"{f} should use the pill control"
        assert "st.radio(" not in src.split("Lens")[0][-400:], f"{f} still uses a radio"

    app = (root / "streamlit_app.py").read_text()
    # Scoped by widget KEY, not widget type. Streamlit emits the key as a class on the
    # element container, and the control's own test id (stButtonGroup) is shared with every
    # other segmented control in the app — styling by type would repaint unrelated widgets.
    # The active state is aria-checked; aria-selected is not set on this control.
    assert ".st-key-lgm_lens button[aria-checked=\"true\"]" in app
    assert ".st-key-lrp_lens button[aria-checked=\"true\"]" in app
    assert "#0b0b0b" in app, "active state must match the maps' ink"
    assert '[data-testid="stSegmentedControl"]' not in app, (
        "that test id does not exist in this Streamlit — the control is stButtonGroup")


def test_every_product_offers_the_same_two_lens_labels():
    """Identical wording everywhere. "Buy" and "Producer view" would be the same idea and a
    different product, as far as a reader scanning five tabs is concerned."""
    import pathlib as _p

    root = _p.Path(__file__).resolve().parents[1]
    for f in ("src/prfpage.py", "src/rowcroppage.py", "src/drppage.py",
              "src/lgmpage.py", "lrp_page.py"):
        src = (root / f).read_text()
        assert "Buy — producer" in src, f"{f} missing the Buy label"
        assert "Sell — agency" in src, f"{f} missing the Sell label"
