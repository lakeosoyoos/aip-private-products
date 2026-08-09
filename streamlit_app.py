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
from src.prfpage import build_prf_page_payload, render_prf_page_html
from src.stack import FEDERAL_BANDS, LAYERS, classified_products
from src.webapp import auth, data
from src.webmap import build_payload, ensure_assets, render_html

# DRP (Dairy Revenue Protection) page — optional. The module is being built
# separately; until it lands the DRP tab renders a short notice instead of
# taking the whole app down with an ImportError. Deliberately broad: a
# half-written module can raise anything at import time.
try:
    from src import drppage
except Exception:
    drppage = None

# LGM (Livestock Gross Margin, plan 82) page — guarded for the same reason as DRP.
# src/lgmpage.py pulls in numpy and src/lgm.py's premium engine; if it is missing or
# raises at import time the LGM tab says so rather than taking every other tab with it.
try:
    from src import lgmpage
except Exception:
    lgmpage = None

st.set_page_config(
    page_title="AIP Crop-Insurance Catalog",
    page_icon="🌾",
    layout="wide",
)

# Which catalog the app reads, in priority order:
#   1. AIP_DB_PATH        — a verification run pointing at a copy with synthetic rows
#   2. data/catalog_app.db — the SHIPPED slim DB (scripts/build_app_db.py). The working
#      catalog carries ~11.5M raw PRF index rows the app never queries and exceeds 1 GB,
#      far past GitHub's 100 MB file limit, so only this trimmed copy is committed.
#   3. config.DB_PATH      — the full working catalog (local development)
_APP_DB = config.DATA_DIR / "catalog_app.db"
DB_PATH = (os.environ.get("AIP_DB_PATH")
           or (str(_APP_DB) if _APP_DB.exists() else config.DB_PATH))


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


@st.cache_resource
def _warm_matplotlib_fonts():
    """Build matplotlib's font cache in the background, once per process.

    On a cold Streamlit Cloud container the first `import matplotlib.pyplot`
    spends ~60 s building the font cache — and without this it lands on
    whoever opens the LRP tab first, where it looks like a hang. Kicking it
    off on a daemon thread right after the passcode gate means it is usually
    finished (or well underway) by the time anyone reaches LRP, and it never
    blocks the gate, the maps, or any other tab.

    Failures are swallowed on purpose: this is pure warm-up: if matplotlib is
    missing or errors here, _tab_lrp still surfaces the real error properly.
    """
    import threading

    def _warm():
        try:
            os.environ.setdefault("MPLBACKEND", "Agg")
            import matplotlib.pyplot  # noqa: F401  (import IS the work)
        except Exception:
            pass

    t = threading.Thread(target=_warm, name="mpl-font-warm", daemon=True)
    t.start()
    return t


def _db_mtime() -> float:
    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0.0


def _render_ver() -> float:
    """Cache-buster for the embedded maps: newest mtime of the render modules. A code-only
    change (e.g. the PRF slider) doesn't touch the DB, so without this the DB-mtime cache key
    would serve the old map HTML on a reused container. Git checkout stamps a fresh mtime each
    deploy, so this busts the cache whenever the map code changes."""
    import src.prfpage
    import src.webmap
    try:
        return max(os.path.getmtime(m.__file__)
                   for m in (src.prfpage, src.webmap))
    except OSError:
        return 0.0


@st.cache_data(show_spinner="Building the interactive map…")
def _map_html(db_mtime: float, render_ver: float) -> str:
    """Full offline map HTML, generated in-memory. Cached on DB mtime + render-code version."""
    assets = ensure_assets()
    payload = build_payload(_conn())
    atlas = json.loads(assets["counties-10m.json"])
    return render_html(
        payload,
        d3_js=assets["d3.v7.min.js"],
        topojson_js=assets["topojson-client.min.js"],
        atlas=atlas,
    )


def _prf_seed_mtime() -> float:
    """Cache-buster for the PRF page's hand-edited seed input.

    data/seed/aip_commission.csv carries the agency's negotiated commission rate per AIP,
    which the "commission per acre" metric multiplies into every shaded county. Editing it
    touches neither the DB nor any render module, so without this key the cached map HTML
    would keep serving the rates that were in the file when the container warmed."""
    import src.prfpage

    try:
        return os.path.getmtime(src.prfpage.COMMISSION_CSV)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _prf_row_counts(db_mtime: float) -> tuple[int, int]:
    """(prf_county rows, prf_opt_best rows). 0 — not an error — when empty/missing."""
    def _n(table: str) -> int:
        try:
            return _conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            return 0

    return _n("prf_county"), _n("prf_opt_best")


@st.cache_data(show_spinner="Building the PRF map…")
def _prf_page_html(db_mtime: float, render_ver: float, seed_mtime: float) -> str:
    """Self-contained merged PRF choropleth (all five metrics in one page).

    Cached on DB mtime + render-code version + commission-seed mtime.

    NOTE THE PARAMETER NAMES. st.cache_data deliberately EXCLUDES underscore-prefixed
    arguments from the cache key (cache_utils: "Not hashing %s because it starts with _"),
    which is how you pass an unhashable connection. A cache-BUSTER must therefore not be
    underscore-prefixed, or the key is empty and the first render is served forever — which
    is exactly what happened when editing data/seed/aip_commission.csv changed nothing on a
    warm container.
    """
    assets = ensure_assets()
    payload = build_prf_page_payload(_conn())
    atlas = json.loads(assets["counties-10m.json"])
    return render_prf_page_html(
        payload,
        d3_js=assets["d3.v7.min.js"],
        topojson_js=assets["topojson-client.min.js"],
        atlas=atlas,
    )


@st.cache_data(show_spinner=False)
def _products_df(db_mtime: float):
    return data.products_dataframe(_conn())


@st.cache_data(show_spinner=False)
def _serff_df(db_mtime: float):
    return data.serff_dataframe(_conn())


@st.cache_data(show_spinner=False)
def _classified(db_mtime: float):
    return classified_products(_conn())


@st.cache_data(show_spinner=False)
def _counts(db_mtime: float):
    return data.catalog_counts(_conn())


@st.cache_data(show_spinner="Building the workbook…")
def _xlsx_bytes(db_mtime: float) -> bytes:
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
#
# The tab bar is PRODUCT-FIRST: one top-level tab per insurance product line
# (Row Crop / PRF / LRP / DRP). Everything that is *about the row-crop catalog*
# — the availability map, the product table, the coverage-stack analysis and
# the SERFF filing history — lives as a sub-section inside "Row Crop" rather
# than as four sibling tabs competing with the product lines.
def _tab_row_crop(mtime: float) -> None:
    """Row-crop catalog: Map / My Farm / Products / Stack / SERFF Filings as sub-tabs.

    Nested st.tabs is intentional — each sub-section keeps its own full body,
    and the widget keys inside them are namespaced (`rc_prod_*`, `rc_serff_*`,
    `rc_farm_*`) so nesting can never raise DuplicateWidgetID against another
    product tab.

    "My Farm" sits SECOND, directly after the map, because it is the only thing
    in this whole tab that is about one operation rather than about a market.
    Everything else here — including every basis-risk figure the map draws — is
    county-typical, and county-typical rests on an assumed farm-to-county yield
    correlation of 0.70 applied to every county in the country. That single
    assumption moves the answer roughly 2x. A producer who reads ten years off
    their own APH schedule replaces it with a measurement, which is the
    difference between "counties like yours typically…" and "your farm".
    """
    st.subheader("Row crop")
    st.caption(
        "The row-crop private/508(h) catalog — availability map, the per-farm "
        "basis-risk calculator, product table, coverage-stack analysis, and the "
        "SERFF filing history behind it."
    )
    sub = st.tabs(["Map", "My Farm", "Products", "Stack", "SERFF Filings"])
    with sub[0]:
        _tab_map(mtime)
    with sub[1]:
        _tab_farm()
    with sub[2]:
        _tab_products(mtime)
    with sub[3]:
        _tab_stack(mtime)
    with sub[4]:
        _tab_serff(mtime)


def _tab_farm() -> None:
    """The per-farm basis-risk calculator (src/rowcroppage.render_farm_calculator).

    The import is LAZY and the whole body is guarded, for the same reason the
    LRP and DRP tabs are: this module pulls in numpy and the simulation code,
    and a row-crop sub-tab must never be able to take the rest of the app down
    with it. It also does no work at all until the producer enters a series, so
    opening the tab costs one small query against basis_risk_county.
    """
    try:
        from src.rowcroppage import render_farm_calculator
    except Exception as exc:                            # pragma: no cover - import guard
        st.error(f"The farm calculator could not be loaded: {exc}")
        return
    try:
        render_farm_calculator()
    except Exception as exc:
        st.error(f"The farm calculator could not be rendered: {exc}")


def _tab_map(mtime: float) -> None:
    st.subheader("Interactive availability map")
    st.caption(
        "Zoom US → state → counties. The embedded map has its own crop / AIP / "
        "subsidy filters. Private products shade at state grain (statewide "
        "filings); federal products at ADM county grain where loaded."
    )
    # st.iframe supersedes st.components.v1.html (removal was slated after 2026-06-01).
    # It auto-detects an HTML string and iframes it; `scrolling` no longer exists, and
    # the iframe scrolls its own document by default, which is what scrolling=True did.
    st.iframe(_map_html(mtime, _render_ver()), height=820)


def _tab_prf(mtime: float) -> None:
    st.subheader("PRF — Pasture, Rangeland, Forage (rainfall index)")
    st.caption(
        "One map, five views — pick one from the **Show** dropdown inside the map:\n\n"
        "- **County multiplier — CBV (\\$/acre)** — the RMA per-acre county dollar "
        "figure that scales PRF protection (acres × productivity factor × coverage "
        "level × CBV).\n"
        "- **Best win rate (%)** — share of historical years the best interval "
        "allocation returned a positive net.\n"
        "- **Best return per \\$1 of protection** — average net return per \\$1, "
        "the sweep's stored, scale-free figure.\n"
        "- **Best return per ACRE (\\$)** — computed as `best net × CBV × coverage "
        "level × productivity factor`; the productivity factor is your own election "
        "(RMA allows 60–150%, default 100%) and appears as an input on the page.\n"
        "- **Commission per acre (\\$)** — your side of the deal, not the producer's: "
        "`CBV × coverage × productivity × Σ(allocation × premium rate) × commission %`, "
        "priced on the optimizer's **recommended** (best-net) allocation. Agent "
        "commission is a percent of **total** premium, and premium is the CBV scaled by a "
        "*premium rate* the CBV view leaves out — one that varies several-fold between "
        "grids at the same coverage, so this map ranks counties differently from the CBV "
        "map. Pick which AIP's rate to apply with the **AIP** selector; rates are your "
        "own negotiated numbers, hand-entered in `data/seed/aip_commission.csv` "
        "(they ship blank, and the map says so until you fill them in).\n\n"
        "Optimizer figures come from simulating all **59,536 valid interval-allocation "
        "policies** (2–5 non-adjacent two-month intervals, 5% steps, 10–60% each, "
        "summing to 100%) per grid over the RMA rainfall-index history; a county shows "
        "the **best result among the grids it touches**. One intended-use control "
        "(Grazing / Haying / Haying-Irrigated) drives both datasets. Counties with no "
        "data for the current selection stay neutral — nothing is inferred."
    )
    cbv_rows, opt_rows = _prf_row_counts(mtime)
    if cbv_rows == 0 and opt_rows == 0:
        st.info(
            "No PRF data loaded yet — run the `prf_adm` connector to populate "
            "`prf_county` (County Base Values) and the sweep to populate "
            "`prf_opt_best`. The map appears here once either lands."
        )
        return
    if cbv_rows == 0:
        st.warning(
            "County Base Values (`prf_county`) are empty — the CBV and "
            "return-per-acre views will render neutral until the `prf_adm` "
            "connector is run."
        )
    if opt_rows == 0:
        st.warning(
            "The optimizer sweep (`prf_opt_best`) is empty — the win-rate, "
            "return-per-\\$1 and return-per-acre views will render neutral "
            "until the sweep is run."
        )
    st.iframe(_prf_page_html(mtime, _render_ver(), _prf_seed_mtime()), height=860)


def _tab_products(mtime: float) -> None:
    df = _products_df(mtime)
    st.subheader("Products")
    st.caption(f"{len(df)} products — 508(h) federal (all-AIP) + truly-private (per-AIP).")

    c1, c2, c3 = st.columns(3)
    with c1:
        bucket = st.selectbox("Bucket", ["all", "508h", "private"], index=0,
                              key="rc_prod_bucket")
        subsidy = st.selectbox(
            "Subsidy", ["all", "subsidized", "private"], index=0,
            help="Derived: subsidized = bucket is not 'private'.",
            key="rc_prod_subsidy",
        )
    with c2:
        aip_opts = sorted(df["AIP"].dropna().unique().tolist())
        aips = st.multiselect("AIP", aip_opts, key="rc_prod_aips")
        crop_opts = sorted({c for cl in df["_crops_list"] for c in cl})
        crops = st.multiselect("Crop", crop_opts, key="rc_prod_crops")
    with c3:
        peril_opts = ["all"] + sorted(df["peril_type"].dropna().unique().tolist())
        peril = st.selectbox("Peril type", peril_opts, index=0, key="rc_prod_peril")
        cov_opts = ["all"] + sorted(df["coverage_type"].dropna().unique().tolist())
        coverage = st.selectbox("Coverage type", cov_opts, index=0, key="rc_prod_coverage")
    search = st.text_input("Search name", placeholder="e.g. hail, ECO, replant…",
                           key="rc_prod_search")

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
        width='stretch',
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
        key="rc_prod_csv",
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
    st.dataframe(pd.DataFrame(layer_rows), width='stretch', hide_index=True)

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
    st.dataframe(pd.DataFrame(matrix), width='stretch', hide_index=True)

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
    st.dataframe(pd.DataFrame(band_rows), width='stretch', hide_index=True)
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
        f"{len(df):,} filing-grain regulatory records across "
        f"{df['state'].nunique()} states — one row per state rate/form filing, NOT a "
        "product menu. An AIP re-files yearly, so filings vastly outnumber products."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        states = st.multiselect("State", sorted(df["state"].dropna().unique().tolist()),
                                key="rc_serff_states")
    with c2:
        aip_codes = st.multiselect("AIP code", sorted(df["aip_code"].dropna().unique().tolist()),
                                   key="rc_serff_aips")
    with c3:
        sub_tois = st.multiselect("Sub-TOI", sorted(df["sub_toi"].dropna().unique().tolist()),
                                  key="rc_serff_subtois")

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
        width='stretch',
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
        key="rc_serff_csv",
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

    st.markdown("#### How this app is organized")
    st.markdown(
        "The tab bar is **product-first** — one tab per product line:\n\n"
        "- **Row Crop** — the catalog above, split into sub-tabs: *Map* "
        "(availability), *Products* (filterable table + CSV), *Stack* "
        "(coverage-layer analysis), and *SERFF Filings* (the regulatory "
        "filing history behind the private products).\n"
        "- **PRF** — Pasture, Rangeland, Forage rainfall index: one map with "
        "five metric views plus the interval optimizer.\n"
        "- **LRP** — Livestock Risk Protection savings signal.\n"
        "- **DRP** — Dairy Revenue Protection (under construction).\n"
        "- **LGM** — Livestock Gross Margin: a deductible-ladder calculator. "
        "Plan 82's subsidy is the only one in this catalog keyed on the "
        "**deductible** rather than a coverage level, and the filed ladder is "
        "identical in all 50 states — so this tab is a calculator, not a map.\n"
        "- **About** — this page: grain caveats, counts, and the Excel export."
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
        "only in the *unmapped* list on **Row Crop → Map**."
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
    st.caption("Full row-crop catalog — Products, AIPs, Stack, SERFF Filings, "
               "and Coverage worksheets.")
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


# ------------------------------------------------------------------ LRP tab
def _tab_lrp() -> None:
    """Livestock Risk Protection savings signal (lrp_page.render()).

    The import is deliberately LAZY — inside the tab body, not at module
    scope. lrp_page pulls in matplotlib/scipy/seaborn via lrp_signal, which
    costs ~1.9 s on top of this app's ~1.8 s module import (measured, warm
    disk), and matplotlib additionally builds its font cache on a cold
    container (a one-off ~60 s). At module scope every visitor — including
    anyone who never gets past the passcode gate — would pay that before the
    gate could even render. Deferred here, the cost is paid once per process
    on the first authenticated render and is free on every later rerun
    (sys.modules cache).

    MPLBACKEND is pinned to Agg before the import: lrp_signal imports
    matplotlib.pyplot at module scope and Streamlit runs scripts off the main
    thread, so the interactive default backend (macosx on a dev Mac) would
    warn or fail. Streamlit Cloud picks Agg on its own; this makes local and
    deployed behaviour identical. Set here rather than in lrp_signal.py,
    which is vendored verbatim.
    """
    st.subheader("🐂 LRP Signal")
    os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        import lrp_page
    except Exception as exc:  # missing LRP-only dep, etc.
        st.error(f"LRP Signal unavailable — {type(exc).__name__}: {exc}")
        st.caption("Needs scipy, matplotlib, seaborn and tabulate "
                   "(see requirements.txt).")
        return
    lrp_page.render()


# ------------------------------------------------------------------ DRP tab
def _tab_drp() -> None:
    """Dairy Revenue Protection — delegates to src/drppage.render().

    The module is optional (see the guarded import at the top of this file):
    if it is missing, half-written, or raises on import, the tab says so
    instead of breaking every other tab on the page.
    """
    st.subheader("🥛 DRP — Dairy Revenue Protection")
    if drppage is None:
        st.info(
            "The DRP optimizer is not built yet. Once `src/drppage.py` lands, "
            "this tab renders it automatically — no change needed here."
        )
        return
    render = getattr(drppage, "render", None)
    if render is None:
        st.info(
            "`src/drppage.py` is present but does not expose a `render()` "
            "function yet — the DRP optimizer is still being built."
        )
        return
    render()


# ------------------------------------------------------------------ LGM tab
def _tab_lgm() -> None:
    """Livestock Gross Margin — delegates to src/lgmpage.render().

    LGM is the MARGIN leg of the livestock trio (LRP is price, DRP is revenue), and its
    tab is a DEDUCTIBLE LADDER CALCULATOR rather than a map: plan 82's subsidy is the only
    one in this catalog keyed on the deductible instead of a coverage level, and the filed
    ladder is identical in all 50 states, so a choropleth of it would be showing
    availability rather than a decision.

    Optional and guarded, exactly like _tab_drp: the module is imported defensively at the
    top of this file so a broken lgmpage cannot break the other five tabs.
    """
    st.subheader("🐄 LGM — Livestock Gross Margin (plan 82)")
    if lgmpage is None:
        st.info(
            "The LGM page is not available in this build. Once `src/lgmpage.py` imports "
            "cleanly, this tab renders it automatically — no change needed here."
        )
        return
    render = getattr(lgmpage, "render", None)
    if render is None:
        st.info(
            "`src/lgmpage.py` is present but does not expose a `render()` function yet."
        )
        return
    render()


# -------------------------------------------------------------------- main
def main() -> None:
    if not _passcode_gate():
        return

    # Authenticated: start matplotlib's font-cache build in the background so the
    # LRP tab does not eat a ~60 s cold-container stall on first open.
    _warm_matplotlib_fonts()

    st.title("🌾 AIP Crop-Insurance Catalog")
    with st.sidebar:
        st.caption("Restricted-access catalog of AIP row-crop private products.")
        if st.button("Log out"):
            st.session_state["authed"] = False
            st.rerun()

    mtime = _db_mtime()
    # PRODUCT-FIRST tab bar: one top-level tab per product line.
    #   Row Crop — the catalog itself, with Map / Products / Stack / SERFF
    #              Filings as sub-tabs (they used to be four sibling tabs).
    #   PRF      — one tab whose embedded page carries the metric dropdown
    #              (CBV / win rate / return per $1 / return per acre / commission).
    #   LRP      — Livestock Risk Protection savings signal.
    #   DRP      — Dairy Revenue Protection (optional module, see _tab_drp).
    #   LGM      — Livestock Gross Margin: a deductible-ladder calculator, not a map,
    #              because plan 82's subsidy keys off the deductible and the ladder is
    #              national (optional module, see _tab_lgm).
    #
    # LGM sits directly after DRP so the three livestock plans — price (LRP), revenue
    # (DRP), margin (LGM) — read left to right as one group.
    tabs = st.tabs(["Row Crop", "PRF", "LRP", "DRP", "LGM", "About"])
    with tabs[0]:
        _tab_row_crop(mtime)
    with tabs[1]:
        _tab_prf(mtime)
    with tabs[2]:
        _tab_lrp()
    with tabs[3]:
        _tab_drp()
    with tabs[4]:
        _tab_lgm()
    with tabs[5]:
        _tab_about(mtime)


if __name__ == "__main__":
    main()
