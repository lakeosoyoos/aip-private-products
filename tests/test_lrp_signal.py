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


def test_the_grid_carries_return_per_producer_dollar_both_ways():
    """LRP was presented ONLY as a cost comparison — "cheaper than the CME put by $X/cwt" —
    which speaks only to someone who already wanted the hedge. These two columns answer the
    question every other product in this app is ranked by: what does a dollar of the
    producer's own money buy?

        ret_sub = actuarial / producer = 1/(1-subsidy)   RMA's own valuation, always > 1
        ret_mkt = cme_put  / producer                    the market's, and it CAN be < 1

    ret_mkt being able to fall below 1.00 is the point. RMA's rate can exceed the market's by
    more than the subsidy covers, and a metric that cannot express that would only ever
    recommend buying.
    """
    import datetime as dt
    import glob
    import pathlib

    import pandas as pd
    import pytest

    import lrp_signal as L

    files = sorted(glob.glob(str(pathlib.Path(__file__).resolve().parents[1]
                                 / "lrp_cache" / "lrp_fed_*.csv")))
    if not files:
        pytest.skip("no cached RMA rate file")
    df = pd.read_csv(files[-1])
    spot = float(df["coverage_price"].max())
    base = dt.date(2026, 8, 11)

    def add_months(d, k):
        y, m = divmod(d.month - 1 + k, 12)
        return dt.date(d.year + y, m + 1, 1)

    curve = {f"{add_months(base, k).strftime('%b')} {add_months(base, k).year}":
             spot * (1 + 0.002 * k) for k in range(15)}
    g = L.build_grid(df, curve, r=0.045, base_vol=0.18, asof=base)

    assert {"ret_sub", "ret_mkt"} <= set(g.columns)
    priced = g[g["producer_prem"] > 0]
    # The identity holds to within rounding, NOT exactly, and that is the correct behaviour:
    # the ratio is taken on the full-precision premiums before either is rounded to the 4dp
    # the columns store. Recomputing it from the rounded columns is what drifts — dividing
    # 0.103 by 0.0463 gives 2.2246 where the true ratio is 2.2222. Comparing on a relative
    # tolerance rather than an absolute one keeps this honest at every premium size.
    for _, r in priced.head(20).iterrows():
        assert r["ret_sub"] == pytest.approx(r["actuarial_prem"] / r["producer_prem"], rel=0.01)
        assert r["ret_mkt"] == pytest.approx(r["cme_put"] / r["producer_prem"], rel=0.01)
    # RMA's own valuation can never say you lose; the market's can, and does
    assert (priced["ret_sub"] > 1.0).all(), "1/(1-subsidy) must exceed 1 everywhere"
    assert (priced["ret_mkt"] < 1.0).any(), (
        "ret_mkt must be able to fall below 1.00 — otherwise it cannot express RMA "
        "out-pricing the market")


def test_the_average_panel_explains_its_blank_rows():
    """"Why does the Average Savings chart have blank white rows?" — because six coverage
    levels have three days of history against a five-day minimum, and nothing on the chart
    said so.

    Those six (0.875, 0.925, 0.96, 0.97, 0.98, 0.99) first appear in lrp_gap_history.csv on
    2026-08-07, the day COVERAGE_LEVELS was corrected to include them; the other six go back
    to June. So the blanks are new levels, not missing data, and they fill themselves in.

    The gate is right — an average of three observations printed beside averages of thirty
    would read as equally solid. What was wrong was the silence. The sibling richness panel
    already explained its own blanks; this one did not.
    """
    import inspect

    import lrp_signal

    assert lrp_signal.MIN_HIST_DAYS == 5
    src = inspect.getsource(lrp_signal.build_chart_figure)
    assert "blank = fewer than " in src, "the panel must say what a blank row means"
    assert "MIN_HIST_DAYS" in src, "and quote the gate rather than restate a literal"
    # the headline count is a maximum, not a figure every cell shares
    assert "up to {n_days} recorded day" in src

    hist = inspect.getsource(lrp_signal.add_history_from_snapshots)
    assert "min_days=MIN_HIST_DAYS" in hist or "min_days=MIN_HIST_DAYS," in hist, (
        "the gate and the caption must come from one constant, or they can disagree")


def test_a_thin_cell_yields_no_average_and_no_richness(monkeypatch):
    """Below the minimum, everything downstream must be ABSENT rather than computed from too
    little: no average, no richness multiple, BUY off. A richness ratio built on three days is
    exactly the kind of number that reads as a signal when it is noise.

    load_gap_history is stubbed rather than reading the real CSV — the point under test is the
    gate, and binding it to whatever happens to be recorded today would make the test drift.
    """
    import datetime as dt

    import pandas as pd

    import lrp_signal as L

    rows = ([{"date": f"2026-08-{d:02d}", "commodity": "feeder", "weeks": 13,
              "coverage_level": 0.99, "gap": 0.9, "gap_pct": 0.35} for d in range(1, 4)] +
            [{"date": f"2026-08-{d:02d}", "commodity": "feeder", "weeks": 13,
              "coverage_level": 0.95, "gap": 0.9, "gap_pct": 0.35} for d in range(1, 31)])
    monkeypatch.setattr(L, "load_gap_history", lambda *_a, **_k: pd.DataFrame(rows))

    grid = pd.DataFrame([
        {"weeks": 13, "coverage_level": 0.99, "gap": 1.0, "gap_pct": 0.4},
        {"weeks": 13, "coverage_level": 0.95, "gap": 1.0, "gap_pct": 0.4}])
    out = L.add_history_from_snapshots(grid, "feeder", 60,
                                       today_date=dt.date(2026, 9, 1))

    thin = out[out["coverage_level"] == 0.99].iloc[0]
    thick = out[out["coverage_level"] == 0.95].iloc[0]
    # pandas stores the None as NaN in a float column, so test for MISSING rather than for
    # the identity None — the behaviour is "blank", not "the literal None object".
    assert pd.isna(thin["hist_avg_gap"]) and thin["n_hist"] == 0, "3 days must not average"
    assert pd.isna(thin["richness"]) and not thin["buy_ok"]
    assert pd.notna(thick["hist_avg_gap"]) and thick["n_hist"] == 30
