import re


def test_chart_type_is_sized_for_the_size_it_is_VIEWED_at():
    """st.pyplot renders this figure ~1460 px wide and the browser fits it to the container at
    ~809 px, so every glyph lands on screen at 55% of its drawn size. matplotlib's 10pt default
    arrives as ~5pt and the axis becomes unreadable — which is what a user reported.

    Raising dpi does NOT fix it: dpi scales the whole image and the browser scales it straight
    back down. Only point size relative to figure size moves the on-screen result. So the sizes
    are stated explicitly, and this pins them against drifting back to the defaults.
    """
    import inspect

    import lrp_signal

    src = inspect.getsource(lrp_signal.build_chart_figure)
    assert "TICK_FS, LABEL_FS, TITLE_FS, ANNOT_FS" in src, "sizes must be named in one place"
    ns: dict = {}
    exec(next(ln.strip() for ln in src.splitlines()
              if ln.strip().startswith("TICK_FS,")), ns)
    assert ns["TICK_FS"] >= 14, f"tick labels at {ns['TICK_FS']}pt read as ~{ns['TICK_FS']*.55:.0f}pt"
    assert ns["LABEL_FS"] >= 14
    assert ns["ANNOT_FS"] >= 9

    # no panel may reintroduce a hardcoded small size
    assert "fontsize=9)" not in src and "fontsize=10)" not in src

    # the sweep that catches the axes seaborn creates: y ticks and colour bars
    assert 'tick_params(axis="both", labelsize=TICK_FS)' in src
    assert "cb.ax.tick_params" in src


def test_panels_are_stacked_full_width_and_the_figure_is_narrow():
    """Two compounding gains, and the narrowness is the one that is easy to miss.

    Streamlit fits the image to the container, so on-screen scale is (container px) / (figure
    inches). At the old 18in wide that was 809/18 = 45 px per inch; at 13in it is 62. So every
    point of type renders 1.4x larger for free. Stacking then gives each panel the whole width
    instead of half, roughly doubling a cell. Together that is what made the two-line cell
    annotations readable.

    A wide 2x2 would undo both, so both are pinned.
    """
    import inspect

    import lrp_signal

    src = inspect.getsource(lrp_signal.build_chart_figure)
    assert "plt.subplots(n_panels, 1," in src, "panels must be stacked, one per row"
    assert "plt.subplots(2, 2" not in src
    m = re.search(r"figsize=\((\d+(?:\.\d+)?),", src)
    assert m and float(m.group(1)) <= 14, "a wide figure shrinks every glyph on screen"


def test_the_history_panels_are_not_created_when_there_is_no_history():
    """The 2x2 grid always made four axes and blanked two, leaving a hole. Stacked, the count
    is decided up front so the image is shorter instead of half empty."""
    import inspect

    import lrp_signal

    src = inspect.getsource(lrp_signal.build_chart_figure)
    assert "n_panels = 4 if has_history else 2" in src
    assert "set_visible(False)" not in src, "empty panels should not exist to be hidden"
