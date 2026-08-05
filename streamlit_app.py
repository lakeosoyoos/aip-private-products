"""AIP crop-insurance catalog — Streamlit web app (passcode-gated).

Deploys on Streamlit Community Cloud (main file: streamlit_app.py). The whole UI
sits behind a passcode gate; the passcode is read from st.secrets / APP_PASSCODE
and is never hardcoded. Everything below the gate is a thin view over the existing
pipeline modules (src.db, src.webmap, src.stack, src.export_xlsx) — imported, not
rebuilt.
"""
from __future__ import annotations

import json
import os
import tempfile

import streamlit as st

from src import config
from src.prfmap import build_prf_payload, render_prf_html
from src.stack import FEDERAL_BANDS, LAYERS, classified_products
from src.webapp import auth, data
from src.webmap import build_payload, ensure_assets, render_html

st.set_page_config(
    page_title="AIP Crop-Insurance Catalog",
    page_icon="🌾",
    layout="wide",
)

# DB_PATH is config.DB_PATH in production; AIP_DB_PATH lets a verification run
# point the app at a copy with synthetic rows without touching the real catalog.
DB_PATH = os.environ.get("AIP_DB_PATH") or config.DB_PATH


# --------------------------------------------------------------------- gate
def _passcode_gate() -> bool:
    """Block the app until a correct passcode is entered. Returns True if authed."""
    if st.session_state.get("authed"):
        return True

    try:
        secrets = dict(st.secrets)
    except Exception:
        secrets = {}
    allowed = auth.allowed_passcodes(secrets)

    st.title("🌾 AIP Crop-Insurance Catalog")
    st.caption("Restricted access — enter the passcode to continue.")

    if not allowed:
        st.error(
            "No passcode is configured. Set `app_passcode` in Streamlit secrets "
            "(or the `APP_PASSCODE` environment variable) before using the app."
        )
        return False

    with st.form("gate", clear_on_submit=False):
        candidate = st.text_input("Passcode", type="password")
        submitted = st.form_submit_button("Enter")
    if submitted:
        if auth.verify_passcode(candidate, allowed):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect passcode.")
    return False


# ----------------------------------------------------------------- caching
@st.cache_resource
def _conn():
    return data.open_ro(DB_PATH)


def _db_mtime() -> float:
    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0.0


@st.cache_data(show_spinner="Building the interactive map…")
def _map_html(_mtime: float) -> str:
    """Full offline map HTML, generated in-memory. Cached on the DB mtime."""
    assets = ensure_assets()
    payload = build_payload(_conn())
    atlas = json.loads(assets["counties-10m.json"])
    return render_html(
        payload,
        d3_js=assets["d3.v7.min.js"],
        topojson_js=assets["topojson-client.min.js"],
        atlas=atlas,
    )


@st.cache_data(show_spinner=False)
def _prf_row_count(_mtime: float) -> int:
    """Rows in prf_county; 0 (not an error) when empty or the table is missing."""
    try:
        return _conn().execute("SELECT COUNT(*) FROM prf_county").fetchone()[0]
    except Exception:
        return 0


@st.cache_data(show_spinner="Building the PRF heat map…")
def _prf_html(_mtime: float) -> str:
    """Self-contained PRF County Base Value choropleth. Cached on the DB mtime."""
    assets = ensure_assets()
    payload = build_prf_payload(_conn())
    atlas = json.loads(assets["counties-10m.json"])
    return render_prf_html(
        payload,
        d3_js=assets["d3.v7.min.js"],
        topojson_js=assets["topojson-client.min.js"],
        atlas=atlas,
    )


@st.cache_data(show_spinner=False)
def _products_df(_mtime: float):
    return data.products_dataframe(_conn())


@st.cache_data(show_spinner=False)
def _serff_df(_mtime: float):
    return data.serff_dataframe(_conn())


@st.cache_data(show_spinner=False)
def _classified(_mtime: float):
    return classified_products(_conn())


@st.cache_data(show_spinner=False)
def _counts(_mtime: float):
    return data.catalog_counts(_conn())


@st.cache_data(show_spinner="Building the workbook…")
def _xlsx_bytes(_mtime: float) -> bytes:
    """Full catalog workbook generated in-memory (no committed xlsx needed). Cached on DB mtime."""
    from src.export_xlsx import build_workbook

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        path = tmp.name
    try:
        build_workbook(_conn(), out_path=path)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# -------------------------------------------------------------------- tabs
def _tab_map(mtime: float) -> None:
    st.subheader("Interactive availability map")
    st.caption(
        "Zoom US → state → counties. The embedded map has its own crop / AIP / "
        "subsidy filters. Private products shade at state grain (statewide "
        "filings); federal products at ADM county grain where loaded."
    )
    st.components.v1.html(_map_html(mtime), height=820, scrolling=True)


def _tab_prf(mtime: float) -> None:
    st.subheader("PRF County Base Value heat map")
    st.caption(
        "PRF (Pasture, Rangeland, Forage — rainfall index). The **County Base "
        "Value (CBV)** is the per-acre county dollar figure that scales PRF "
        "protection: protection = acres × productivity factor × coverage level × "
        "CBV. The embedded map has its own intended-use (Grazing / Haying), "
        "irrigation-practice (Irrigated / Non-Irrigated), organic, and year "
        "dropdowns; darker counties carry a higher $/acre CBV, and counties with "
        "no value for the current selection are shown neutral."
    )
    if _prf_row_count(mtime) == 0:
        st.info(
            "PRF data not loaded yet — run the `prf_adm` connector to populate the "
            "`prf_county` table (County Base Values). The heat map will appear here "
            "once values are loaded."
        )
        return
    st.components.v1.html(_prf_html(mtime), height=820, scrolling=True)


def _tab_products(mtime: float) -> None:
    df = _products_df(mtime)
    st.subheader("Products")
    st.caption(f"{len(df)} products — 508(h) federal (all-AIP) + truly-private (per-AIP).")

    c1, c2, c3 = st.columns(3)
    with c1:
        bucket = st.selectbox("Bucket", ["all", "508h", "private"], index=0)
        subsidy = st.selectbox(
            "Subsidy", ["all", "subsidized", "private"], index=0,
            help="Derived: subsidized = bucket is not 'private'.",
        )
    with c2:
        aip_opts = sorted(df["AIP"].dropna().unique().tolist())
        aips = st.multiselect("AIP", aip_opts)
        crop_opts = sorted({c for cl in df["_crops_list"] for c in cl})
        crops = st.multiselect("Crop", crop_opts)
    with c3:
        peril_opts = ["all"] + sorted(df["peril_type"].dropna().unique().tolist())
        peril = st.selectbox("Peril type", peril_opts, index=0)
        cov_opts = ["all"] + sorted(df["coverage_type"].dropna().unique().tolist())
        coverage = st.selectbox("Coverage type", cov_opts, index=0)
    search = st.text_input("Search name", placeholder="e.g. hail, ECO, replant…")

    filtered = data.filter_products(
        df,
        bucket=None if bucket == "all" else bucket,
        subsidy=None if subsidy == "all" else subsidy,
        aips=aips or None,
        crops=crops or None,
        peril=None if peril == "all" else peril,
        coverage_type=None if coverage == "all" else coverage,
        search=search or None,
    )

    st.markdown(f"**{len(filtered)}** of {len(df)} products match.")
    view = filtered[[
        "name", "AIP", "bucket", "subsidy", "layer", "federal_analog",
        "peril_type", "coverage_type", "crops", "states", "doc_url",
    ]]
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "doc_url": st.column_config.LinkColumn("doc / source", display_text="open"),
            "federal_analog": st.column_config.TextColumn("analog"),
        },
    )
    st.download_button(
        "Download filtered as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="aip_products_filtered.csv",
        mime="text/csv",
    )


def _tab_stack(mtime: float) -> None:
    import pandas as pd

    prods = _classified(mtime)
    st.subheader("Coverage-stack analysis")
    st.markdown(
        "A grower builds a **stack**: subsidized federal MPCI + federal bands "
        "(SCO/ECO/MCO/STAX) at the bottom, then **unsubsidized private** bands, "
        "named-peril, and utility endorsements above. Federal layers are "
        "reinsured and premium-subsidized; private layers are full-freight "
        "(farmer pays 100%). Layer assignment is rule-based (`stack.classify`); "
        "unmatched products stay in *other* rather than being forced."
    )

    # Part A — layer table
    st.markdown("#### A. The stack (layers)")
    layer_rows = []
    for key, label, sub, desc in LAYERS:
        layer_rows.append({
            "layer": label,
            "subsidized?": sub,
            "# products": sum(1 for p in prods if p["layer"] == key),
            "description": desc,
        })
    st.dataframe(pd.DataFrame(layer_rows), use_container_width=True, hide_index=True)

    # Part B — AIP x private-layer matrix
    st.markdown("#### B. Private layers by AIP")
    st.caption("Federal layers are offered through every AIP, so only private layers vary.")
    private_layers = ["private_band", "named_peril", "endorsement", "other"]
    labels = {k: lbl for k, lbl, _, _ in LAYERS}
    aips = sorted({(p["aip_code"], p["aip_name"]) for p in prods if p["aip_code"]},
                  key=lambda t: t[1] or "")
    matrix = []
    for code, aname in aips:
        row = {"AIP": f"{aname} ({code})"}
        for layer in private_layers:
            names = sorted(p["name"] for p in prods
                           if p["aip_code"] == code and p["layer"] == layer)
            row[labels[layer]] = "; ".join(names) or "—"
        matrix.append(row)
    st.dataframe(pd.DataFrame(matrix), use_container_width=True, hide_index=True)

    # Part C — federal band vs private analogs
    st.markdown("#### C. Federal band vs private analogs (the subsidy decision)")
    band_rows = []
    for key, fname, cov, sub in FEDERAL_BANDS:
        analogs = sorted(
            f"{p['name']} [{p['aip_code']}{', ' + p['sts'] if p.get('sts') else ''}]"
            for p in prods
            if p["bucket"] == "private" and p["federal_analog"] and key in p["federal_analog"])
        band_rows.append({
            "federal band": f"{fname} ({key})",
            "coverage": cov,
            "premium subsidy": sub,
            "private analogs (unsubsidized)": "; ".join(analogs) or "none cataloged",
        })
    st.dataframe(pd.DataFrame(band_rows), use_container_width=True, hide_index=True)
    st.info(
        "A private analog listed against a federal band is an **unsubsidized** "
        "product marketed to play the same role or stack above it. The grower's "
        "trade-off is full-freight private premium vs the subsidized federal "
        "premium (SCO/ECO/STAX ~80% subsidy after the July 2025 law). Named-peril "
        "and endorsement layers have no federal analog."
    )


def _tab_serff(mtime: float) -> None:
    df = _serff_df(mtime)
    st.subheader("SERFF filings")
    st.caption(
        f"{len(df)} filing-grain regulatory records for 5 states (IA/IL/NE/MN/IN) — "
        "one row per state rate/form filing, NOT a product menu. An AIP re-files "
        "yearly, so filings vastly outnumber products."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        states = st.multiselect("State", sorted(df["state"].dropna().unique().tolist()))
    with c2:
        aip_codes = st.multiselect("AIP code", sorted(df["aip_code"].dropna().unique().tolist()))
    with c3:
        sub_tois = st.multiselect("Sub-TOI", sorted(df["sub_toi"].dropna().unique().tolist()))

    view = df
    if states:
        view = view[view["state"].isin(states)]
    if aip_codes:
        view = view[view["aip_code"].isin(aip_codes)]
    if sub_tois:
        view = view[view["sub_toi"].isin(sub_tois)]

    st.markdown(f"**{len(view)}** of {len(df)} filings match.")
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "filing_url": st.column_config.LinkColumn("filing", display_text="open"),
        },
    )
    st.download_button(
        "Download filtered as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="serff_filings_filtered.csv",
        mime="text/csv",
    )


def _tab_about(mtime: float) -> None:
    counts = _counts(mtime)
    st.subheader("About this catalog")
    st.markdown(
        "This app catalogs the **private** products Approved Insurance Providers "
        "(AIPs) offer in row-crop crop insurance. *Private* means two different "
        "things, treated separately and honestly:\n\n"
        "- **`508h`** — privately-developed / 508(h) plans approved by the FCIC "
        "Board and sold inside the federal program (reinsured, subsidized). Once "
        "approved, *every* AIP may offer them — a shared, source-cited reference.\n"
        "- **`private`** — truly private products sold outside the federal "
        "program (not reinsured, unsubsidized) — crop-hail, named-peril, wind, "
        "replant, supplemental/gap, price modifiers. The menu genuinely varies "
        "by company."
    )

    st.markdown("#### Grain honesty")
    st.markdown(
        "- **Private products are state grain** — statewide SERFF filings; the "
        "map shades every county of a filed state and badges it *statewide*.\n"
        "- **Federal products are county grain** via the Actuarial Data Master "
        "(ADM); states without ADM county rows fall back to whole-state shading "
        "flagged *county detail pending ADM*.\n"
        "- **SERFF filings are filing grain** (regulatory history), not products.\n"
        "- Products with no availability data are never painted — they appear "
        "only in the map's *unmapped* list."
    )

    st.markdown("#### Counts")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Products", counts.get("products", 0))
    c2.metric("— 508(h) federal", counts.get("products_508h", 0))
    c3.metric("— private", counts.get("products_private", 0))
    c4.metric("AIPs", counts.get("aips", 0))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SERFF filings", counts.get("serff_filings", 0))
    c2.metric("County×crop rows", counts.get("product_counties", 0))
    c3.metric("Product-state rows", counts.get("product_states", 0))
    c4.metric("Documents", counts.get("documents", 0))

    st.markdown("#### Excel export")
    st.caption("Full catalog — Products, AIPs, Stack, SERFF Filings, and Coverage sheets.")
    st.download_button(
        "Download full catalog (.xlsx)",
        _xlsx_bytes(mtime),
        file_name="aip_products_catalog.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.caption(
        "All data pulled is public. Sources: live RMA AIP API, curated 508(h) "
        "reference, per-AIP websites, state SERFF Filing Access, and the RMA "
        "Actuarial Data Master (RY 2026)."
    )


# -------------------------------------------------------------------- main
def main() -> None:
    if not _passcode_gate():
        return

    st.title("🌾 AIP Crop-Insurance Catalog")
    with st.sidebar:
        st.caption("Restricted-access catalog of AIP row-crop private products.")
        if st.button("Log out"):
            st.session_state["authed"] = False
            st.rerun()

    mtime = _db_mtime()
    tabs = st.tabs(["Map", "PRF", "Products", "Stack", "SERFF Filings", "About"])
    with tabs[0]:
        _tab_map(mtime)
    with tabs[1]:
        _tab_prf(mtime)
    with tabs[2]:
        _tab_products(mtime)
    with tabs[3]:
        _tab_stack(mtime)
    with tabs[4]:
        _tab_serff(mtime)
    with tabs[5]:
        _tab_about(mtime)


if __name__ == "__main__":
    main()
