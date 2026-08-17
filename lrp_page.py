"""
LRP Savings Signal — embeddable Streamlit page.

Exposes render() for use inside an existing app:

    import lrp_page
    lrp_page.render()

Designed to coexist with a host app:
  - no st.set_page_config (the host owns that)
  - every widget key is namespaced "lrp_"
  - controls live in the page body, not the sidebar
"""
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lrp_signal import (
    COVERAGE_LEVELS, CWT_PER_HEAD, TENORS_WEEKS,
    fetch_lrp_current, fetch_lrp_reference, fetch_cme_futures_curve,
    get_cme_source_label,
    build_grid, record_gap_snapshot, ensure_gap_history,
    add_history_from_snapshots, load_gap_history, build_chart_figure,
    size_delta_hedge, sales_today,
)


@st.cache_data(ttl=600, show_spinner=False)
def _run_pipeline(commodity, vol_pct, rate_pct, lookback, _cache_day):
    """Full signal pipeline. _cache_day busts the cache at CT date roll."""
    r = rate_pct / 100.0
    base_vol = vol_pct / 100.0
    curve = fetch_cme_futures_curve(commodity)
    # Overnight window (before 8:25 AM CT) serves yesterday's still-live rates
    lrp, eff_date = fetch_lrp_current(commodity)
    status = "live"
    if lrp.empty:
        # Dead zone / weekend: last posted rates as EXPIRED reference
        ref, ref_date = fetch_lrp_reference(commodity)
        if not ref.empty:
            lrp, eff_date, status = ref, ref_date, "expired"
        else:
            status = "none"
    grid = build_grid(lrp, curve, r, base_vol, asof=eff_date)
    # Only genuinely LIVE rates enter the gap history — recording an
    # expired day against today's curve would corrupt the baseline
    if status == "live" and grid["live"].any():
        record_gap_snapshot(grid, commodity, eff_date, source="live")
    ensure_gap_history(commodity, lookback, r, base_vol, verbose=False)
    grid = add_history_from_snapshots(grid, commodity, lookback,
                                      today_date=eff_date)

    if not lrp.empty:
        spot = float(lrp["expected_value"].iloc[0])
    elif curve:
        spot = next(iter(curve.values()))
    else:
        spot = 350.0 if commodity == "feeder" else 230.0
    return grid, curve, spot, get_cme_source_label(curve), eff_date, status


def _window_status():
    """LRP sales window: opens ~3:30 PM CT, closes 8:25 AM CT next day."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    ct = datetime.now(ZoneInfo("America/Chicago"))
    hm = ct.hour * 60 + ct.minute
    # 8:25 AM CT close (505 min past midnight) — see lrp_signal.check_window.
    if hm >= 930:
        left = (24 * 60 - hm) + 505
        return True, f"open — {left // 60}h {left % 60}m to close"
    if hm < 505:
        left = 505 - hm
        return True, f"open — {left // 60}h {left % 60}m to close"
    return False, "closed — opens ~3:30 PM CT"



LRP_MEASURED_NOTE = (
    "**Measured LRP experience nationally is 0.66x** — producers have received 66 cents of "
    "indemnity per dollar of premium they paid, across 2005-2026 (RMA Summary of Business, "
    "plan 81: loss ratio 0.43, subsidy 34.8%, and 0.43 / (1 - 0.348) = 0.66). It swings hard "
    "by year, from 0.09x to 4.40x, and the recent heavy-volume years have been the poor ones "
    "because cattle prices rose and a price floor does not pay when prices rise. Neither "
    "column below is a forecast; both are what today's rate card implies."
)


def _render_agency(st, grid, commodity, cwt, head):
    """The Sell lens: agency revenue across the same coverage x tenor grid.

    LRP had no agency figure at all. Commission is a percent of TOTAL premium, and LRP's grid
    carries that directly as `actuarial_prem` — the unsubsidised premium per cwt — so there is
    no grossing-up step. What matters is that it is NOT the producer premium: applying the
    rate to what the producer pays would understate commission by the whole subsidy, about
    35% at every coverage level LRP sells.
    """
    import pandas as pd

    from src.prfpage import load_aip_commission

    st.subheader("Sell — agency commission across the grid")
    comm = load_aip_commission(product="LRP")
    rated = [a for a in comm["aips"] if a["by_region"] or a["pct"] is not None]
    if not rated:
        st.warning(
            "No LRP commission rate on file. LRP is reinsured under the LPRA, whose A&O is "
            "22.2% of net book premium (LPRA IV(b)(2)(D)) and which contains no agent "
            "compensation cap. Enter your negotiated schedule in "
            "`data/seed/aip_commission.csv` under product=LRP.")
        return

    def _rate(a):
        vals = [v for v in (a["by_region"] or {}).values() if v is not None]
        return (sum(vals) / len(vals)) if vals else a["pct"]

    rates = [r for r in (_rate(a) for a in rated) if r is not None]
    pct = sum(rates) / len(rates)
    st.caption(
        f"At **{pct:.2f}%** of total premium — the LPRA ceiling (22.2% A&O, no compensation "
        f"cap in that agreement). Read it as *at most*. Sized to {head:,} head "
        f"({cwt:,.0f} cwt).")

    g = grid[grid["actuarial_prem"] > 0].copy()
    if g.empty:
        st.info("No priced cells in the current grid.")
        return
    g["comm_cwt"] = g["actuarial_prem"] * pct / 100.0
    g["comm_total"] = g["comm_cwt"] * cwt

    piv = g.pivot(index="coverage_pct", columns="weeks", values="comm_total")
    order = [c for c in
             (f"{int(v * 100)}%" for v in sorted(grid["coverage_level"].unique(), reverse=True))
             if c in piv.index]
    st.dataframe(piv.reindex(order), width="stretch")
    st.caption(f"Agency commission in dollars on {head:,} head, by coverage level and tenor.")

    best = g.loc[g["comm_total"].idxmax()]
    prod = g.loc[g["ret_mkt"].idxmax()] if "ret_mkt" in g.columns else None
    st.info(
        f"**Agency revenue peaks at {best['coverage_pct']} / {int(best['weeks'])}w** — "
        f"${best['comm_total']:,.0f} on {head:,} head. Commission tracks PREMIUM, so it is "
        f"largest where the producer pays most: the highest coverage and the longest tenor.")
    if prod is not None and (prod["coverage_pct"], prod["weeks"]) != (best["coverage_pct"],
                                                                     best["weeks"]):
        st.warning(
            f"**The producer's best cell is elsewhere.** Return per producer dollar peaks at "
            f"{prod['coverage_pct']} / {int(prod['weeks'])}w ({prod['ret_mkt']:.2f}x), where "
            f"agency commission is ${prod['actuarial_prem'] * pct / 100.0 * cwt:,.0f} — "
            f"${best['comm_total'] - prod['actuarial_prem'] * pct / 100.0 * cwt:,.0f} less "
            f"than the agency's best cell. Recommending the first while quoting the second is "
            f"the conflict this lens exists to make visible.")
    st.info(LRP_MEASURED_NOTE)


def render():
    """Draw the full LRP Savings Signal page."""

    # ── Controls (page body, namespaced keys) ────────────────────────────
    top1, top2, top3, top4, top5 = st.columns([1.2, 1, 1.2, 1.4, 0.9])
    commodity = top1.selectbox(
        "Commodity", ["feeder", "fed"], key="lrp_commodity",
        format_func=lambda c: "Feeder Cattle" if c == "feeder"
        else "Fed Cattle")
    head = top2.number_input("Head count", min_value=50, max_value=20000,
                             value=1000, step=50, key="lrp_head")
    lookback = top3.slider("Baseline lookback (days)", 10, 90, 30,
                           key="lrp_lookback")
    with top4.expander("Pricing assumptions"):
        vol_pct = st.number_input("Base vol % (B76)", 5.0, 40.0, 14.0, 0.5,
                                  key="lrp_vol")
        rate_pct = st.number_input("Risk-free rate %", 0.0, 10.0, 5.0, 0.25,
                                   key="lrp_rate")
    if top5.button("🔄 Refresh", key="lrp_refresh", width='stretch'):
        _run_pipeline.clear()
        st.rerun()

    is_open, win_msg = _window_status()
    (st.success if is_open else st.info)(f"LRP window {win_msg}")

    # ── Pipeline ─────────────────────────────────────────────────────────
    with st.spinner("Fetching RMA rates and CME curve..."):
        try:
            grid, curve, spot, cme_source, eff_date, status = _run_pipeline(
                commodity, vol_pct, rate_pct, lookback,
                sales_today().isoformat())
        except Exception as e:
            st.error(f"LRP pipeline failed: {e}")
            return

    label = "Fed Cattle" if commodity == "fed" else "Feeder Cattle"
    cwt = head * CWT_PER_HEAD

    st.subheader(f"LRP Savings Signal — {label}")
    st.caption(f"Rates effective {eff_date}  |  CME source: {cme_source}"
               f"  |  sized to {head:,} head ({cwt:,.0f} cwt)")

    if status == "none":
        st.error("**ESTIMATED — NO RMA RATES AVAILABLE.** Premiums below "
                 "are model estimates, not actual RMA quotes. Do not "
                 "trade off these numbers.")
    elif status == "expired":
        st.warning(f"**EXPIRED — FOR REFERENCE ONLY.** These are the last "
                   f"posted rates (effective **{eff_date}**); their sales "
                   f"window closed at 8:25 AM CT and they are no longer "
                   f"purchasable. New rates post ~3:30 PM CT on the next "
                   f"sales day. The CME comparison uses today's curve, so "
                   f"the gap will shift when fresh rates arrive.")
    elif eff_date != sales_today():
        st.info(f"Overnight window — showing rates effective "
                f"**{eff_date}**, purchasable until 8:25 AM CT this "
                f"morning.")

    # ── Headline metrics ─────────────────────────────────────────────────
    valid = grid[grid["gap"] > 0]
    best = valid.loc[valid["gap_pct"].idxmax()] if not valid.empty else None
    buys = grid[grid.get("buy_ok", pd.Series(False, index=grid.index))]
    n_days = int(grid["n_hist"].max()) if "n_hist" in grid.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot (RMA expected value)", f"${spot:.2f}/cwt")
    if best is not None:
        c2.metric(f"Best cell — {best['coverage_pct']} / "
                  f"{int(best['weeks'])}w",
                  f"${best['gap']:.2f}/cwt",
                  f"${best['gap'] * cwt:,.0f} on {head:,} head")
        rx = best.get("richness")
        c3.metric("Best cell vs normal",
                  f"{rx:.1f}x" if pd.notna(rx) else "n/a",
                  f"normal ${best['hist_avg_gap']:.2f}/cwt"
                  if pd.notna(best.get("hist_avg_gap")) else "no baseline")
    else:
        c2.metric("Best cell", "—")
        c3.metric("Best cell vs normal", "—")
    c4.metric("BUY signals", f"{len(buys)}",
              f"baseline: {n_days} recorded days")

    if not buys.empty and status == "live":
        st.success("**BUY cells today:** " + "  •  ".join(
            f"{r['coverage_pct']}/{int(r['weeks'])}w "
            f"(${r['gap']:.2f}/cwt, {r['richness']:.1f}x)"
            for _, r in buys.iterrows()))

    # ── Lens ─────────────────────────────────────────────────────────────
    # WHOSE MONEY. The four tabs below are organised by ARTIFACT — a chart, a table, a
    # history, a hedge calculator — not by question, and every one of them describes the
    # producer. There was no agency figure anywhere on this tab.
    # st.segmented_control, not st.radio: it renders as a joined pill row, which is the
    # same shape as the #lensSeg control inside the PRF, row-crop and DRP maps. Those three
    # cannot use a Streamlit widget — switching would rerun and re-emit a 31 MB iframe — so
    # the consistency has to come from picking the widget that already matches them.
    lens = st.segmented_control(
        "Lens", ["Buy — producer", "Sell — agency"], default="Buy — producer",
        key="lrp_lens", label_visibility="collapsed") or "Buy — producer"

    if lens.startswith("Sell"):
        _render_agency(st, grid, commodity, cwt, head)
        return

    # ── Tabs ─────────────────────────────────────────────────────────────
    tab_chart, tab_grid, tab_history, tab_delta = st.tabs(
        ["📊 Dashboard", "🔢 Full grid", "📈 Gap history", "🎯 Delta hedge"])

    with tab_chart:
        chart_banner = (f"EXPIRED — rates effective {eff_date} — window "
                        f"closed, reference only"
                        if status == "expired" else None)
        fig = build_chart_figure(grid, commodity, spot, cme_source, head,
                                 banner=chart_banner)
        st.pyplot(fig, width='stretch')
        import matplotlib.pyplot as plt
        plt.close(fig)

    with tab_grid:
        show = grid.copy()
        show["total_$"] = (show["gap"] * cwt).round(0)
        # ret_mkt and ret_sub sit next to the gap deliberately. The gap is a COST comparison
        # — "LRP is $X/cwt cheaper than the put" — which only speaks to someone who already
        # wanted the hedge. These two say what a dollar of the producer's own money buys,
        # which is the question every other product in this app is ranked by.
        cols = ["weeks", "coverage_pct", "coverage_price", "F",
                "producer_prem", "actuarial_prem", "cme_put", "gap", "total_$",
                "ret_mkt", "ret_sub",
                "subsidy_gap", "vol_gap", "hist_avg_gap", "richness",
                "buy_ok", "live"]
        show = show[[c for c in cols if c in show.columns]]
        show = show.sort_values("gap", ascending=False)
        st.dataframe(
            show, width='stretch', height=560, hide_index=True,
            column_config={
                "weeks": st.column_config.NumberColumn("Tenor (w)"),
                "actuarial_prem": st.column_config.NumberColumn(
                    "Total prem $/cwt", format="%.4f",
                    help="The UNSUBSIDISED premium — what RMA reckons the protection is "
                         "worth, and what agency commission is paid on."),
                "ret_mkt": st.column_config.NumberColumn(
                    "Return per $1 (market)", format="%.2f",
                    help="CME put value / producer premium. What a dollar of your own money "
                         "buys, valued at what the same protection actually costs in the "
                         "market. BELOW 1.00 means you pay more than the protection is worth "
                         "even after the subsidy."),
                "ret_sub": st.column_config.NumberColumn(
                    "Return per $1 (RMA)", format="%.2f",
                    help="Unsubsidised premium / producer premium = 1/(1-subsidy). What the "
                         "subsidy alone hands you IF RMA prices fairly. Always above 1.00, "
                         "which is why it is not the honest column on its own."),
                "coverage_pct": "Coverage",
                "coverage_price": st.column_config.NumberColumn(
                    "Strike $", format="$%.2f"),
                "F": st.column_config.NumberColumn(
                    "Forward $", format="$%.2f"),
                "producer_prem": st.column_config.NumberColumn(
                    "LRP prem", format="$%.2f"),
                "cme_put": st.column_config.NumberColumn(
                    "CME put", format="$%.2f"),
                "gap": st.column_config.NumberColumn(
                    "Gap /cwt", format="$%.2f"),
                "total_$": st.column_config.NumberColumn(
                    f"Total ({head:,} hd)", format="$%.0f"),
                "subsidy_gap": st.column_config.NumberColumn(
                    "Subsidy", format="$%.2f"),
                "vol_gap": st.column_config.NumberColumn(
                    "Vol disc", format="$%.2f"),
                "hist_avg_gap": st.column_config.NumberColumn(
                    "Normal", format="$%.2f"),
                "richness": st.column_config.NumberColumn(
                    "vs normal", format="%.1fx"),
                "buy_ok": "BUY",
                "live": "Live quote",
            })
        st.download_button(
            "⬇️ Download grid CSV",
            grid.to_csv(index=False).encode(),
            file_name=f"lrp_signal_{commodity}_{sales_today()}.csv",
            mime="text/csv", key="lrp_dl_grid")

    with tab_history:
        hist = load_gap_history(commodity)
        if hist.empty:
            st.info("No gap history recorded yet.")
        else:
            st.caption(
                f"{hist['date'].nunique()} recorded days  |  sources: "
                + ", ".join(f"{k}: {v}" for k, v in
                            hist.groupby("source")["date"].nunique()
                                .to_dict().items())
                + "  |  each day priced with its own curve")
            # DRIVEN BY COVERAGE_LEVELS, never a literal list. The hardcoded one here offered
            # 70% — which RMA does not sell, so it always answered "no history for this cell" —
            # and hid 87.5, 92.5, 96, 97, 98 and 99, which it does. Same stale-constant bug as
            # the blank rows on the Average Savings panel: COVERAGE_LEVELS was corrected and
            # this copy was not. A derived list cannot drift from the levels that exist.
            #
            # %g on the label because the list is no longer all integers: 0.875 must read
            # "87.5%", not "87%", or two distinct levels collapse to one string.
            pick = st.selectbox(
                "Cell", [f"{c * 100:g}% / {w}w"
                         for w in TENORS_WEEKS
                         for c in sorted(COVERAGE_LEVELS, reverse=True)],
                index=0, key="lrp_hist_cell")
            cov_s, wk_s = pick.split(" / ")
            cov_v = float(cov_s.rstrip("%")) / 100.0
            wk_v = int(wk_s.rstrip("w"))
            cell = hist[(hist["weeks"] == wk_v)
                        & (hist["coverage_level"].round(4)
                           == round(cov_v, 4))]
            if cell.empty:
                st.info("No history for this cell.")
            else:
                cell = cell.sort_values("date").set_index("date")
                # The series is named "gap" in the frame, and st.line_chart labels the axis
                # with the column name — so the y axis read "gap" with no units anywhere on
                # the chart. The units were in the caption BELOW it, which is not where a
                # reader looks to find out what they are looking at.
                st.line_chart(cell[["gap"]], height=280,
                              x_label="Date", y_label="Gap ($/cwt)")
                st.caption(f"Gap $/cwt by day for {pick} — "
                           f"avg ${cell['gap'].mean():.2f}, "
                           f"last ${cell['gap'].iloc[-1]:.2f}")

    with tab_delta:
        if status == "none":
            st.warning("Estimate mode — premiums (and therefore hedge "
                       "costs) below are modeled, not actual RMA quotes.")
        elif status == "expired":
            st.warning(f"Sizing uses EXPIRED reference rates (effective "
                       f"{eff_date}) — premiums will change at the "
                       f"~3:30 PM CT posting.")

        max_abs_delta = float(grid["put_delta"].abs().max())
        ratio_pct = st.slider("Short delta target (% of herd exposure)",
                              5, 75, 20, 5, key="lrp_delta_ratio")
        ratio = ratio_pct / 100.0

        st.markdown(
            f"Your {head:,} head are long **{cwt:,.0f} cwt** of price "
            f"exposure (+1 delta per cwt). Each cell shows how much LRP "
            f"to buy so its put delta offsets **{ratio_pct}%** of that. "
            f"Max reachable with a single cell today: "
            f"**{max_abs_delta * 100:.0f}%** (the deepest cell's |Δ|).")

        sz = size_delta_hedge(grid, head, ratio)
        n_feasible = int(sz["feasible"].sum())

        d1, d2, d3 = st.columns(3)
        d1.metric("Herd exposure", f"{cwt:,.0f} cwt")
        d2.metric("Target short deltas", f"{ratio * cwt:,.0f} cwt-eq")
        d3.metric("Feasible cells", f"{n_feasible} / {len(sz)}")

        if n_feasible == 0:
            st.info(f"No single cell can reach {ratio_pct}% today — LRP "
                    f"puts max out at |Δ| ≈ {max_abs_delta:.2f}, and RMA "
                    f"won't insure more cwt than you own. Lower the "
                    f"target to {int(max_abs_delta * 100)}% or below.")

        show_sz = sz.copy()
        show_sz = show_sz.sort_values(
            ["feasible", "premium_cost"], ascending=[False, True],
            na_position="last")
        show_sz["Feasible"] = show_sz["feasible"].map(
            {True: "✅", False: "❌"})
        show_sz = show_sz.drop(columns=["feasible"])
        cols_sz = ["weeks", "coverage_pct", "coverage_price", "put_delta",
                   "insured_cwt", "insured_head", "pct_of_herd",
                   "premium_cost", "Feasible", "achievable_ratio"]
        show_sz = show_sz[cols_sz]
        st.dataframe(
            show_sz, width='stretch', height=560,
            hide_index=True,
            column_config={
                "weeks": st.column_config.NumberColumn("Tenor (w)"),
                "coverage_pct": "Coverage",
                "coverage_price": st.column_config.NumberColumn(
                    "Strike $", format="$%.2f"),
                "put_delta": st.column_config.NumberColumn(
                    "Put Δ /cwt", format="%.4f"),
                "insured_cwt": st.column_config.NumberColumn(
                    "Insure (cwt)", format="%.0f"),
                "insured_head": st.column_config.NumberColumn(
                    "Insure (head)", format="%.0f"),
                "pct_of_herd": st.column_config.NumberColumn(
                    "% of herd", format="%.1f%%"),
                "premium_cost": st.column_config.NumberColumn(
                    "Premium cost", format="$%.0f"),
                "Feasible": "Feasible",
                "achievable_ratio": st.column_config.NumberColumn(
                    "Max ratio @100% herd", format="%.2f"),
            })
        st.caption(
            "Deltas are initial (as-of today). Puts gain delta as the "
            "market falls, so the realized hedge deepens in a selloff — "
            "re-check sizing after big moves. Deep-OTM cells (70–80% "
            "coverage) carry tiny deltas, so they are usually infeasible "
            "for meaningful ratios: RMA won't insure more cwt than you "
            "own. 'Max ratio @100% herd' = that cell's |Δ| — the "
            "short-delta ratio delivered if you insure the entire herd. "
            "Sizing rounds up to whole head (RMA endorsements are per "
            "head).")
