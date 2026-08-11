

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
