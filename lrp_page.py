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
    CWT_PER_HEAD, TENORS_WEEKS,
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
    # Overnight window (before 9 AM CT) serves yesterday's still-live rates
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
    """LRP sales window: opens ~3:30 PM CT, closes 9:00 AM CT next day."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    ct = datetime.now(ZoneInfo("America/Chicago"))
    hm = ct.hour * 60 + ct.minute
    if hm >= 930:
        left = (24 * 60 - hm) + 540
        return True, f"open — {left // 60}h {left % 60}m to close"
    if hm < 540:
        left = 540 - hm
        return True, f"open — {left // 60}h {left % 60}m to close"
    return False, "closed — opens ~3:30 PM CT"


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
    if top5.button("🔄 Refresh", key="lrp_refresh", use_container_width=True):
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
                   f"window closed at 9:00 AM CT and they are no longer "
                   f"purchasable. New rates post ~3:30 PM CT on the next "
                   f"sales day. The CME comparison uses today's curve, so "
                   f"the gap will shift when fresh rates arrive.")
    elif eff_date != sales_today():
        st.info(f"Overnight window — showing rates effective "
                f"**{eff_date}**, purchasable until 9:00 AM CT this "
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

    # ── Tabs ─────────────────────────────────────────────────────────────
    tab_chart, tab_grid, tab_history, tab_delta = st.tabs(
        ["📊 Dashboard", "🔢 Full grid", "📈 Gap history", "🎯 Delta hedge"])

    with tab_chart:
        chart_banner = (f"EXPIRED — rates effective {eff_date} — window "
                        f"closed, reference only"
                        if status == "expired" else None)
        fig = build_chart_figure(grid, commodity, spot, cme_source, head,
                                 banner=chart_banner)
        st.pyplot(fig, use_container_width=True)
        import matplotlib.pyplot as plt
        plt.close(fig)

    with tab_grid:
        show = grid.copy()
        show["total_$"] = (show["gap"] * cwt).round(0)
        cols = ["weeks", "coverage_pct", "coverage_price", "F",
                "producer_prem", "cme_put", "gap", "total_$",
                "subsidy_gap", "vol_gap", "hist_avg_gap", "richness",
                "buy_ok", "live"]
        show = show[[c for c in cols if c in show.columns]]
        show = show.sort_values("gap", ascending=False)
        st.dataframe(
            show, use_container_width=True, height=560, hide_index=True,
            column_config={
                "weeks": st.column_config.NumberColumn("Tenor (w)"),
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
            pick = st.selectbox(
                "Cell", [f"{int(c * 100)}% / {w}w"
                         for w in TENORS_WEEKS
                         for c in [1.0, 0.95, 0.90, 0.85, 0.80,
                                   0.75, 0.70]],
                index=0, key="lrp_hist_cell")
            cov_s, wk_s = pick.split(" / ")
            cov_v = int(cov_s.rstrip("%")) / 100.0
            wk_v = int(wk_s.rstrip("w"))
            cell = hist[(hist["weeks"] == wk_v)
                        & (hist["coverage_level"].round(4)
                           == round(cov_v, 4))]
            if cell.empty:
                st.info("No history for this cell.")
            else:
                cell = cell.sort_values("date").set_index("date")
                st.line_chart(cell[["gap"]], height=280)
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
            show_sz, use_container_width=True, height=560,
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
