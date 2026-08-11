"""Self-contained DRP product page — one STATE-level map, five metrics.

DRP = Dairy Revenue Protection (plan code 83). Built the same way as src/prfpage.py —
d3 v7, topojson-client and the us-atlas topology embedded inline, every control inside
the page, zero network requests — but at a different grain, because DRP is a different
product.

WHY THIS MAP IS STATE-LEVEL AND PRF'S IS NOT
--------------------------------------------
DRP IS SOLD STATEWIDE. Every plan-83 row in ADM A00030 carries county code '998' (all
counties), and RY2026 is exactly 800 offers = 50 states x 8 quarters x 2 pricing
options. There is no county grain, no grid grain, and no rainfall lattice underneath: a
Wisconsin dairy in Dane County and one in Polk County buy the identical endorsement at
the identical price. So the choropleth shades STATES, the drill-down stops at the state,
and the breadcrumb says so in as many words rather than implying a level that does not
exist. Drilling into a state paints its counties in ONE uniform colour — that is not a
shortcut, it is the 998 fact drawn.

What varies between states at all is the milk YIELD term: DRP revenue is price x yield,
the price side (CME Class III/IV, butter/cheese/whey/NFDM) is national, and only the
state milk-production-per-cow distribution is local. That is why the liability per
hundredweight is near-identical everywhere while the win rate is not, and the page says
so instead of letting a nearly flat map look like a bug.

THE FIVE METRICS
    win     Best win rate (%)                            [drp_opt_best]
    net     Best return per $1 of liability ($)          [drp_opt_best]
    cwt     Best return per hundredweight ($) — COMPUTED
    prem    Producer premium per hundredweight ($) — COMPUTED
    policy  Net return on the whole declaration ($) — COMPUTED

THE DOLLAR FORMULA, AND WHY THE PROTECTION FACTOR IS ONLY IN IT

    liability/cwt = expected milk price x coverage level     [stored per state]
    $/cwt         = best net (per $1 of liability) x liability/cwt x share x PF
    $/policy      = $/cwt x declared production (lb) / 100

M13 exhibit P18-1 puts DeclaredShare and ProtectionFactor in BOTH TotalPremiumAmount and
Liability, and P28-1 puts them in the indemnity; DeclaredCoveredMilkProduction divides by
100 against every $/cwt price. All three therefore scale cost and payout IDENTICALLY.
Moving the protection-factor input on this page changes every dollar figure and cannot
change the win rate, the return per $1, or the ranking of one state against another — the
map literally does not re-colour for `win` or `net`. That is the DRP analogue of PRF's
per-$1-of-protection normalization, and it is why the optimizer searched 84 risk shapes
(4 coverage levels x 21 weighting factors) rather than the 1,848 declarations a naive
count gives. See src/drpopt.py.

WHERE THE PREMIUM COMES FROM
There is no DRP rate table and there cannot be one: premium is a 5,000-iteration Monte
Carlo over RMA's own published uniform draws (P18-1). Both simulation inputs —
drp_daily_price and drp_draw, ~610 MB together — are DROPPED from the shipped app DB, so
this page never touches them. It reads the two numbers the optimizer distilled onto each
drp_opt_best row instead: `best_net_prem` (producer premium per $1 of liability) and
`best_net_liability_cwt` (dollar liability on one hundredweight). Exactly the role
prf_opt_best.best_net_rate_sum plays for PRF.

DRILL-DOWN CHROME
The breadcrumb (#crumb), the log-scaled zoom slider with +/- buttons (#zoomBox /
#zSlider / #zLabel) and d3.zoom pan/wheel are lifted from src/prfpage.py, including two
details that are not optional:

  * ZOOM TRANSITIONS MUST APPLY INSTANTLY WHEN document.hidden. d3's transition scheduler
    is requestAnimationFrame-driven and browsers suspend rAF in a backgrounded tab, so an
    animated zoom started there never advances past CREATED — the map freezes mid-flight
    and stays frozen after you switch back. See `applyTransform` below and in prfpage.

  * POLYGON RINGS MUST BE WOUND CLOCKWISE in (lon, lat). d3-geo treats polygons as
    spherical and takes the interior to be the region LEFT of the ring's travel — the
    opposite of GeoJSON's counter-clockwise-exterior convention — so a counter-clockwise
    ring renders as the whole globe minus the shape and floods the viewport. This page
    draws ONLY us-atlas geometry, which is already wound correctly, so it builds no rings
    of its own; `ring_clockwise` is here, exported and tested, for whoever adds the first
    one. DRP has no sub-state lattice to synthesize, which is exactly why the temptation
    to invent one has to be refused rather than met.

Degrades gracefully: an empty (or missing) drp_opt_best gives a valid all-neutral map
with an honest note naming the sweep to run, never an error.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from .prfpage import STATE_TIMEZONE, load_aip_commission

# Coverage level the page opens on, when the sweep stored it.
DEFAULT_COVERAGE = "0.9"
DEFAULT_OPTION = "Class"
DEFAULT_QUARTER = "0"          # 0 = every quarter pooled

# Declaration inputs (the producer's own numbers; they scale dollars and nothing else).
PROD_DEFAULT_LB = 1_000_000    # lb of covered milk production in the quarter
PROD_MIN_LB = 1_000
PROD_MAX_LB = 500_000_000
SHARE_DEFAULT_PCT = 100
# RMA's protection-factor election range.
PF_MIN = 1.00
PF_MAX = 1.50
PF_STEP = 0.05
PF_DEFAULT = 1.00

QUARTER_LABELS = {
    "0": "All quarters", "1": "Jan–Mar", "2": "Apr–Jun",
    "3": "Jul–Sep", "4": "Oct–Dec",
}


def _fips2(value) -> str:
    """Normalize a state code to the atlas's 2-digit string form."""
    s = str(value or "").strip()
    if not s:
        return ""
    return s.zfill(2) if s.isdigit() else s


def _cov_key(cov) -> str:
    """Canonical coverage-level key: 0.9 and 0.90 must not become two axes."""
    try:
        return f"{float(cov):g}"
    except (TypeError, ValueError):
        return str(cov)


def _f(value, nd: int | None = None):
    """float(value) rounded, or None — payload numbers are never guessed."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:          # NaN: a metric that could not be computed
        return None
    return round(v, nd) if nd is not None else v


def ring_clockwise(ring):
    """Return `ring` wound CLOCKWISE in (lon, lat), reversing it if it is not.

    d3-geo is spherical: the interior of a polygon is the region to the LEFT of the
    ring's direction of travel, which is the opposite of GeoJSON's counter-clockwise
    convention. A counter-clockwise ring therefore renders as the entire globe minus the
    shape and floods the viewport with a solid fill — the failure that bit src/prfpage.py
    when it first drew PRF grid cells.

    Orientation is the sign of the shoelace sum: positive means clockwise in a
    conventional x-right / y-up frame, which (lon, lat) is.

    This page draws only us-atlas geometry and so calls this on nothing. It is exported
    and tested anyway, because the next contributor who hand-builds a ring here will
    otherwise rediscover the bug rather than the rule.
    """
    pts = list(ring)
    if len(pts) < 3:
        return pts
    area = 0.0
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        area += (x2 - x1) * (y2 + y1)
    return pts if area > 0 else pts[::-1]


# ----------------------------------------------------------------- payload
def build_drp_page_payload(conn: sqlite3.Connection) -> dict:
    """Everything the page needs, from drp_opt_best + drp_state. Pure read; testable.

    Shape:
        states[fips2][option][quarter_key][cov_key] = {
            "win":  best win rate (share of settled quarters with a positive net)
            "net":  best mean net return per $1 of liability
            "prem": producer premium per $1 of liability, on the BEST-NET shape
            "liab": mean $ liability on one hundredweight, on the best-net shape
            "nw":   best-net weighting factor      "ww": best-win weighting factor
            "wnet": the best-win shape's mean net  "nwin": the best-net shape's win rate
            "med":  median mean-net over the shapes scored
            "pos":  share of shapes with a positive mean net
            "n":    settled quarters scored        "pin": how many RMA pinned
            "sh":   weighting factors scored       "dry": draw reinsurance year
            "q0"/"q1": first / last settled quarter label
        }

    Note what is NOT in here: no protection factor and no declared production. Both are
    page inputs applied client-side, because both cancel out of every stored metric (see
    the module docstring). Storing a PF-scaled number would be storing the same map five
    times over.

    `avail` carries drp_state's own availability rollup for the newest reinsurance year,
    so a state with offers but no sweep result reads as "not scored yet" rather than "not
    offered" — those are different claims.
    """
    states: dict[str, dict] = {}
    options: set[str] = set()
    quarters: set[str] = set()
    coverages: set[str] = set()
    wins: list[float] = []
    nets: list[float] = []

    try:
        rows = conn.execute("SELECT * FROM drp_opt_best").fetchall()
    except sqlite3.OperationalError:
        rows = []           # table not created yet — degrade to an empty, honest map

    for r in rows:
        fips = _fips2(r["state_code"])
        if not fips:
            continue
        option = (r["pricing_option"] or "").strip()
        qk = str(int(r["quarter"] or 0))
        ck = _cov_key(r["coverage_level"])
        options.add(option)
        quarters.add(qk)
        coverages.add(ck)
        cell = {
            # 5dp on the two rate-like metrics: a win rate has at most 30 distinct values
            # and a net-per-$1 runs in the thousandths, so this is well below display
            # precision and keeps the embedded payload small.
            "win": _f(r["best_win_rate"], 5),
            "net": _f(r["best_net"], 6),
            "prem": _f(r["best_net_prem"], 6),
            "liab": _f(r["best_net_liability_cwt"], 4),
            "nw": _f(r["best_net_weight"], 2),
            "ww": _f(r["best_win_weight"], 2),
            "wnet": _f(r["best_win_net"], 6),
            "nwin": _f(r["best_net_win_rate"], 5),
            "med": _f(r["median_net"], 6),
            "pos": _f(r["pct_positive"], 4),
            "n": r["n_obs"],
            "pin": r["n_pinned"],
            "sh": r["n_shapes"],
            "dry": r["premium_draw_ry"],
            "q0": r["quarter_min"],
            "q1": r["quarter_max"],
        }
        (states.setdefault(fips, {})
               .setdefault(option, {})
               .setdefault(qk, {}))[ck] = cell
        if cell["win"] is not None:
            wins.append(cell["win"])
        if cell["net"] is not None:
            nets.append(cell["net"])

    # Availability + display names straight from drp_state, for the newest RY it holds.
    avail: dict[str, dict] = {}
    state_names: dict[str, str] = {}
    avail_ry = None
    try:
        avail_ry = conn.execute(
            "SELECT MAX(reinsurance_year) FROM drp_state").fetchone()[0]
        if avail_ry is not None:
            for r in conn.execute(
                    "SELECT state_code, state_abbrev, state_name, n_quarters, "
                    "n_pricing_options FROM drp_state WHERE reinsurance_year = ?",
                    (avail_ry,)):
                fips = _fips2(r["state_code"])
                if not fips:
                    continue
                avail[fips] = {"q": r["n_quarters"], "o": r["n_pricing_options"],
                               "ab": r["state_abbrev"]}
                if r["state_name"]:
                    state_names[fips] = str(r["state_name"]).strip()
    except sqlite3.OperationalError:
        pass

    def _qsort(k: str):
        return (0, 0) if k == "0" else (1, int(k))

    def _csort(k: str):
        try:
            return float(k)
        except ValueError:
            return float("inf")

    # AGENCY SIDE. Commission is a percent of TOTAL premium, but every stored DRP metric is
    # normalised on the PRODUCER's premium, so the subsidy schedule is what converts one into
    # the other: total = producer / (1 - subsidy). Carried per coverage level because DRP's
    # subsidy varies with it (0.59 at 0.70 down to 0.44 at 0.95).
    #
    # The roster is loaded with product="DRP" and NOT PRF's. Commission is negotiated per
    # product line and DRP is reinsured under the LPRA, whose A&O is 22.2% against the SRA's
    # 20.1% for area plans — borrowing PRF's card would understate DRP by a third.
    subsidy = {}
    try:
        ry = conn.execute("SELECT MAX(reinsurance_year) FROM drp_subsidy").fetchone()[0]
        for cl, sub in conn.execute(
                "SELECT coverage_level, MAX(subsidy_pct) FROM drp_subsidy "
                "WHERE reinsurance_year = ? GROUP BY coverage_level", (ry,)):
            subsidy[_cov_key(cl)] = float(sub)
    except (sqlite3.OperationalError, TypeError):
        pass                      # no schedule: the commission metric renders as unavailable

    return {
        "generated": _dt.date.today().isoformat(),
        "subsidy": subsidy,
        "comm": load_aip_commission(product="DRP"),
        # state -> commission region, the same axis PRF and row crop use, so one rate card
        # serves every product rather than each inventing its own geography.
        "state_zone": dict(STATE_TIMEZONE),
        "states": states,
        "state_names": state_names,
        "avail": avail,
        "avail_ry": avail_ry,
        "options": sorted(options) or [DEFAULT_OPTION],
        "quarters": sorted(quarters, key=_qsort) or [DEFAULT_QUARTER],
        "quarter_labels": QUARTER_LABELS,
        "coverages": sorted(coverages, key=_csort),
        "min_win": min(wins) if wins else None,
        "max_win": max(wins) if wins else None,
        "min_net": min(nets) if nets else None,
        "max_net": max(nets) if nets else None,
        "row_count": len(rows),
        "state_count": len(states),
        "decl": {"prod": PROD_DEFAULT_LB, "prod_min": PROD_MIN_LB,
                 "prod_max": PROD_MAX_LB, "share": SHARE_DEFAULT_PCT,
                 "pf_min": PF_MIN, "pf_max": PF_MAX, "pf_step": PF_STEP,
                 "pf": PF_DEFAULT},
        "default_coverage": DEFAULT_COVERAGE,
        "default_option": DEFAULT_OPTION,
        "default_quarter": DEFAULT_QUARTER,
    }


def _js_embed_json(obj) -> str:
    """JSON serialized for safe inline embedding inside a <script> block."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_drp_page_html(payload: dict, d3_js: str, topojson_js: str,
                         atlas: dict) -> str:
    """Render the self-contained DRP state choropleth as one HTML string."""
    for blob in (d3_js, topojson_js):
        if "</script" in blob.lower():
            raise ValueError("asset JS contains '</script'; cannot inline safely")
    html = _TEMPLATE
    html = html.replace("__GENERATED__", payload.get("generated", ""))
    html = html.replace("__D3__", d3_js)
    html = html.replace("__TOPOJSON__", topojson_js)
    html = html.replace("__ATLAS__", _js_embed_json(atlas))
    html = html.replace("__PAYLOAD__", _js_embed_json(payload))
    return html


def generate(db_path=None, out_path=None):
    """Write the page to a file — the offline path, and what the tests exercise."""
    from pathlib import Path

    from . import config
    from .webmap import ensure_assets

    assets = ensure_assets()
    dbp = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload = build_drp_page_payload(conn)
    finally:
        conn.close()
    html = render_drp_page_html(payload, assets["d3.v7.min.js"],
                                assets["topojson-client.min.js"],
                                json.loads(assets["counties-10m.json"]))
    out = Path(out_path or (config.OUTPUT_DIR / "drp_page.html"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB, "
          f"{payload['row_count']} drp_opt_best rows, "
          f"{payload['state_count']} states)")
    return out


# The Streamlit-cached helpers, built ONCE per process. They are created lazily (so
# importing this module costs nothing when Streamlit is not the caller — the tests import
# it, and `import streamlit` is ~2 s) but memoized here rather than rebuilt inside
# render(), because a decorator re-applied on every rerun is a new function object and an
# easy way to defeat the cache it was added for.
_HELPERS: dict = {}


def _streamlit_helpers() -> dict:
    if _HELPERS:
        return _HELPERS
    import streamlit as st

    from .webmap import ensure_assets

    @st.cache_resource
    def _open(path: str):
        # Read-only + immutable, and check_same_thread=False because Streamlit runs
        # reruns and sessions on different threads (same reasoning as webapp.data.open_ro).
        c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True,
                            check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    @st.cache_data(show_spinner="Building the DRP map…")
    def _html(db_mtime: float, render_ver: float, path: str) -> str:
        # NOTE THE PARAMETER NAMES: st.cache_data excludes underscore-prefixed arguments
        # from the cache key, so a cache-BUSTER must not be underscore-prefixed or the
        # first render is served forever on a warm container.
        assets = ensure_assets()
        payload = build_drp_page_payload(_open(path))
        return render_drp_page_html(payload, assets["d3.v7.min.js"],
                                    assets["topojson-client.min.js"],
                                    json.loads(assets["counties-10m.json"]))

    _HELPERS.update(open=_open, html=_html)
    return _HELPERS


def render() -> None:
    """Draw the DRP tab inside Streamlit. Called by streamlit_app as drppage.render().

    The map HTML is cached on the DB's mtime plus this module's own mtime, for the same
    reason streamlit_app caches the PRF page that way: a code-only change does not touch
    the database, so without the second key a warm container keeps serving the old map.

    Opens its OWN read-only connection rather than borrowing streamlit_app's, using the
    same priority order (AIP_DB_PATH, then the shipped slim DB, then the working
    catalog) — the tab is meant to drop into that app without it having to hand anything
    over.
    """
    import os

    import streamlit as st

    from . import config

    helpers = _streamlit_helpers()
    app_db = config.DATA_DIR / "catalog_app.db"
    db_path = (os.environ.get("AIP_DB_PATH")
               or (str(app_db) if app_db.exists() else str(config.DB_PATH)))

    def _mtime(path) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    try:
        n_rows = helpers["open"](db_path).execute(
            "SELECT COUNT(*) FROM drp_opt_best").fetchone()[0]
    except Exception:
        n_rows = 0
    if not n_rows:
        st.info(
            "The DRP optimizer has not been run against this database yet — "
            "`drp_opt_best` is empty. Run "
            "`.venv/bin/python -m src.drpopt --all` to populate it. The map below "
            "still renders; every state will simply be neutral."
        )

    try:
        html = helpers["html"](_mtime(db_path), _mtime(__file__), db_path)
    except Exception as exc:                     # never take the tab down
        st.error(f"Could not build the DRP map: {exc}")
        return
    # st.iframe replaces st.components.v1.html, which was slated for removal after
    # 2026-06-01. It auto-detects an HTML string and sandboxes it in an iframe, same as
    # before. `scrolling` is gone from the signature; the page sizes itself to the frame,
    # and letting an overflowing document scroll is better than clipping it.
    st.iframe(html, height=820)


# The template uses __TOKENS__ (not str.format) so the JS braces stay literal.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DRP — Dairy Revenue Protection</title>
<style>
  :root {
    color-scheme: light;
    --surface: #fcfcfb; --page: #f9f9f7;
    --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --none: #ececea; --accent: #2a78d6;
  }
  * { box-sizing: border-box; margin: 0; }
  html, body { height: 100%; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink); font-size: 14px;
    display: flex; flex-direction: column;
  }
  header { padding: 12px 18px 8px; }
  header h1 { font-size: 16px; font-weight: 650; }
  header .sub { color: var(--ink-2); font-size: 12.5px; margin-top: 2px; }
  .filters {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    padding: 8px 18px 10px; border-bottom: 1px solid var(--grid);
    background: var(--surface);
  }
  .filters label { color: var(--ink-2); font-size: 12px; }
  .filters select, .filters input[type=number] {
    font: inherit; font-size: 13px; padding: 4px 6px; max-width: 300px;
    border: 1px solid var(--baseline); border-radius: 6px; background: var(--surface);
    color: var(--ink);
  }
  .filters input[type=number] { width: 92px; }
  #mSel { font-weight: 600; max-width: 320px; }
  .seg { display: inline-flex; border: 1px solid var(--baseline); border-radius: 6px;
    overflow: hidden; }
  .seg button {
    font: inherit; font-size: 12.5px; padding: 4px 11px; border: none;
    background: var(--surface); color: var(--ink-2); cursor: pointer;
  }
  .seg button + button { border-left: 1px solid var(--baseline); }
  .seg button.on { background: #238b45; color: #fff; }
  #formulaNote {
    padding: 6px 18px; font-size: 11.5px; color: var(--ink-2);
    background: var(--surface); border-bottom: 1px solid var(--grid); display: none;
  }
  #formulaNote code { font-size: 11.5px; background: var(--page);
    border: 1px solid var(--grid); border-radius: 4px; padding: 0 4px; }
  #formulaNote .fn { display: none; }
  #formulaNote .fn.on { display: block; }
  /* Metric range slider (dual-thumb) — filters which states are shaded. */
  .rangebar {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    padding: 24px 18px 9px; border-bottom: 1px solid var(--grid); background: var(--surface);
  }
  .rangebar > label { color: var(--ink-2); font-size: 12px; white-space: nowrap; }
  .dual { position: relative; flex: 1; min-width: 220px; max-width: 520px; height: 26px; }
  .dual .track { position: absolute; top: 11px; left: 0; right: 0; height: 4px;
    background: var(--grid); border-radius: 3px; }
  .dual .fill { position: absolute; top: 11px; height: 4px; background: #41ab5d; border-radius: 3px; }
  .dual .bubble {
    position: absolute; top: -16px; transform: translateX(-50%);
    font-size: 11px; font-variant-numeric: tabular-nums; color: var(--ink);
    background: var(--surface); border: 1px solid var(--baseline); border-radius: 4px;
    padding: 0 4px; line-height: 15px; white-space: nowrap; pointer-events: none;
  }
  .dual input[type=range] {
    position: absolute; top: 0; left: 0; width: 100%; height: 26px; margin: 0;
    -webkit-appearance: none; appearance: none; background: transparent; pointer-events: none;
  }
  .dual input[type=range]::-webkit-slider-runnable-track { height: 26px; background: transparent; }
  .dual input[type=range]::-moz-range-track { height: 26px; background: transparent; }
  .dual input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; pointer-events: auto;
    width: 16px; height: 16px; border-radius: 50%; background: var(--surface);
    border: 2px solid #238b45; box-shadow: 0 1px 3px var(--ring); cursor: pointer;
  }
  .dual input[type=range]::-moz-range-thumb {
    pointer-events: auto; width: 16px; height: 16px; border-radius: 50%;
    background: var(--surface); border: 2px solid #238b45; cursor: pointer;
  }
  .rangebar .readout { font-size: 12.5px; color: var(--ink);
    font-variant-numeric: tabular-nums; white-space: nowrap; }
  .rangebar .reset { font: inherit; font-size: 12px; color: var(--accent);
    background: none; border: none; cursor: pointer; padding: 0; }
  #main { flex: 1; display: flex; min-height: 0; }
  #mapWrap { flex: 1; position: relative; min-width: 0; }
  #map { width: 100%; height: 100%; display: block; }
  .state { stroke: var(--surface); stroke-width: 0.6; vector-effect: non-scaling-stroke; }
  .state.hovered { stroke: var(--ink); stroke-width: 1.4; }
  .state.dimmed { opacity: 0.30; }
  .statelines { fill: none; stroke: var(--baseline); stroke-width: 0.7;
                pointer-events: none; vector-effect: non-scaling-stroke; }
  /* The uniform county wash drawn when a state is focused: DRP's county code 998,
     rendered. Only ever the focused state's counties, so a few dozen paths. */
  .countycell { stroke: rgba(11,11,11,0.22); stroke-width: 0.5;
                vector-effect: non-scaling-stroke; cursor: default; }
  .countycell.hovered { stroke: var(--ink); stroke-width: 1.4; }
  .focusline { fill: none; stroke: var(--ink); stroke-width: 2.2; stroke-linejoin: round;
               pointer-events: none; vector-effect: non-scaling-stroke; }
  #tooltip {
    position: absolute; pointer-events: none; display: none; z-index: 5;
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.12); padding: 7px 10px; font-size: 12.5px;
    max-width: 350px;
  }
  #tooltip .t-name { font-weight: 650; }
  #tooltip .t-val { color: var(--ink-2); margin-top: 1px; }
  #tooltip .t-math { color: var(--ink-2); font-size: 11.5px; margin-top: 3px;
    font-variant-numeric: tabular-nums; }
  #tooltip .t-grid { margin-top: 5px; border-top: 1px solid var(--grid); padding-top: 4px; }
  #tooltip .t-line { color: var(--ink-2); font-size: 11.5px; margin-top: 1px; }
  #tooltip .t-warn { color: #8a5a00; font-size: 11.5px; margin-top: 3px; }
  #legend {
    position: absolute; left: 16px; bottom: 14px; background: var(--surface);
    border: 1px solid var(--ring); border-radius: 8px; padding: 8px 10px; font-size: 11.5px;
  }
  #legend .l-title { color: var(--ink-2); margin-bottom: 5px; }
  #legend .l-row { display: flex; align-items: center; gap: 0; }
  #legend .l-cell { width: 34px; height: 10px; }
  #legend .l-labels { display: flex; font-size: 10px; color: var(--muted); margin-top: 1px; }
  #legend .l-labels span { width: 34px; text-align: left; }
  #legend .l-none { display: flex; align-items: center; gap: 6px; margin-top: 7px; color: var(--muted); }
  #legend .l-none .sw { width: 14px; height: 10px; background: var(--none); border: 1px solid var(--grid); }
  #note {
    position: absolute; top: 12px; left: 16px; right: 16px; z-index: 4; display: none;
    background: #fdf6e7; border: 1px solid #eda100; border-radius: 8px;
    color: #6b4b00; padding: 8px 12px; font-size: 12.5px;
  }
  footer { padding: 6px 18px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--grid); }

  /* ---- drill-down: breadcrumb + zoom control (mirrors src/prfpage.py) ---- */
  #crumb {
    position: absolute; top: 12px; left: 16px; z-index: 4; display: flex; align-items: center;
    gap: 6px; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    padding: 5px 9px; font-size: 12px; box-shadow: 0 1px 4px rgba(11,11,11,0.06);
  }
  #crumb .c-step { color: var(--accent); cursor: pointer; }
  #crumb .c-step:hover { text-decoration: underline; }
  #crumb .c-here { color: var(--ink); font-weight: 600; }
  #crumb .c-sep { color: var(--muted); }
  #crumb .c-hint { color: var(--muted); border-left: 1px solid var(--grid); padding-left: 8px; }
  #zoomBox {
    position: absolute; right: 16px; bottom: 14px; z-index: 4; display: flex; flex-direction: column;
    align-items: center; gap: 6px; background: var(--surface); border: 1px solid var(--ring);
    border-radius: 8px; padding: 9px 7px; box-shadow: 0 1px 4px rgba(11,11,11,0.06);
  }
  #zoomBox button {
    font: inherit; font-size: 15px; line-height: 1; width: 24px; height: 22px; cursor: pointer;
    border: 1px solid var(--baseline); border-radius: 5px; background: var(--surface); color: var(--ink);
  }
  #zoomBox button:hover { border-color: var(--accent); color: var(--accent); }
  /* Vertical slider: up = closer in, which is the direction the map moves. */
  #zSlider { writing-mode: vertical-lr; direction: rtl; width: 22px; height: 104px; accent-color: var(--accent); }
  #zLabel { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<header>
  <h1 id="pageTitle">DRP — Dairy Revenue Protection</h1>
  <div class="sub" id="pageSub">Generated __GENERATED__.</div>
</header>
<div class="filters">
  <!-- WHOSE MONEY. Five producer metrics and one agency metric; the lens picks the question
       and Show then offers only what answers it. -->
  <label>Lens
    <span class="seg" id="lensSeg">
      <button data-lens="buy" class="on">Buy — producer</button>
      <button data-lens="sell">Sell — agency</button>
    </span>
  </label>
  <label>Show <select id="mSel"></select></label>
  <label>Pricing option <span class="seg" id="optSeg"></span></label>
  <label>Quarter <span class="seg" id="qSeg"></span></label>
  <label>Coverage <span class="seg" id="covSeg"></span></label>
  <label id="shareWrap" style="display:none">Share
    <input type="number" id="fShare" min="1" max="100" step="1" value="100"> %
  </label>
  <label id="pfWrap" style="display:none">Protection factor
    <input type="number" id="fPf" min="1" max="1.5" step="0.05" value="1.00">
  </label>
  <label id="prodWrap" style="display:none">Covered production
    <input type="number" id="fProd" min="1000" max="500000000" step="1000" value="1000000"
           style="width:120px"> lb
  </label>
  <span id="countLine" style="color:var(--muted);font-size:12px;margin-left:auto"></span>
</div>
<div id="formulaNote">
  <div class="fn" data-m="win">
    <b>Win rate</b> = share of the settled quarters in which
    <code>indemnity &minus; producer premium &gt; 0</code>, for the best of the 21
    declarable weighting factors at this coverage level. Each quarter is scored ONCE, at
    the last sales date it was quoted on before the period opened.
    <b>The protection factor cannot move this number</b>: RMA's P18-1 puts it in both the
    premium and the liability and P28-1 puts it in the indemnity, so it scales cost and
    payout identically. Change it below and this map will not re-colour — that is the
    point, not a bug.
  </div>
  <div class="fn" data-m="net">
    <b>Return per $1 of liability</b> =
    <code>mean over settled quarters of (indemnity &minus; producer premium) &divide; liability</code>.
    Scale-invariant by construction, which is what makes one state comparable with
    another and what lets the protection factor, the declared share and the declared
    production all be applied afterwards instead of being swept.
  </div>
  <div class="fn" data-m="cwt">
    <b>Return per hundredweight</b> =
    <code>best net (per $1 of liability) &times; liability per cwt &times; share &times; protection factor</code>,
    where <code>liability per cwt = expected milk price &times; coverage level</code>.
    The price side of DRP is national (CME Class III/IV and the butter / cheese / dry whey
    / NFDM strips), so liability per cwt is nearly the same in every state; what differs
    between states is the milk-yield term. Expect this map to look flatter than the win-rate
    map, and read the two together.
  </div>
  <div class="fn" data-m="prem">
    <b>Producer premium per hundredweight</b> =
    <code>simulated total premium &times; (1 &minus; subsidy) &divide; liability &times; liability per cwt &times; share &times; protection factor</code>,
    on the same best-net declaration the other metrics rank. DRP publishes <b>no premium
    rate table and cannot</b>: P18-1 specifies a 5,000-iteration Monte Carlo over RMA's own
    published uniform draws. This is that simulation's output, not a filed rate.
  </div>
  <div class="fn" data-m="policy">
    <b>Net return on the declaration</b> =
    <code>return per hundredweight &times; declared covered milk production &divide; 100</code>.
    Declared production is in POUNDS and every DRP revenue formula divides it by 100
    against a $/cwt price. Production, share and protection factor are one common
    multiplier: they change every dollar on this page and none of the rankings.
  </div>
</div>
<div class="rangebar" id="rangebar">
  <label id="rangeLabel">Metric range</label>
  <div class="dual">
    <div class="track"></div>
    <div class="fill" id="rFill"></div>
    <div class="bubble" id="rBubbleLo"></div>
    <div class="bubble" id="rBubbleHi"></div>
    <input type="range" id="rMin">
    <input type="range" id="rMax">
  </div>
  <span class="readout" id="rReadout"></span>
  <button class="reset" id="rReset" type="button">reset</button>
</div>
<div id="main">
  <div id="mapWrap">
    <div id="note"></div>
    <div id="crumb"></div>
    <svg id="map" viewBox="0 0 975 610" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="zoomBox">
      <button id="zIn" type="button" title="Zoom in">+</button>
      <input type="range" id="zSlider" min="0" max="100" value="0">
      <button id="zOut" type="button" title="Zoom out">&minus;</button>
      <span id="zLabel">1&times;</span>
    </div>
    <div id="legend"></div>
    <div id="tooltip"></div>
  </div>
</div>
<footer id="pageFoot"></footer>

<script>__D3__</script>
<script>__TOPOJSON__</script>
<script>
var US_ATLAS = __ATLAS__;
var DATA = __PAYLOAD__;

(function () {
  "use strict";

  var NONE = getComputedStyle(document.documentElement).getPropertyValue("--none").trim() || "#ececea";
  var RAMP = ["#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"];
  // Cost is not a benefit: the premium metric gets its own (warm) ramp so a dark state
  // never means "good" on one map and "expensive" on the next.
  var COST_RAMP = ["#fee8c8", "#fdd49e", "#fdbb84", "#fc8d59", "#ef6548", "#d7301f", "#990000"];
  var UNITS = 1000;

  var ST = DATA.states || {}, AVAIL = DATA.avail || {};

  var METRICS = {
    win:  { label: "Best win rate", legend: "Best win rate (%)", ramp: RAMP,
            title: "DRP optimizer — best win rate by state",
            sub: "Share of settled quarters in which the best weighting factor returned a " +
                 "positive net. DRP is sold statewide, so this is the whole grain there is.",
            none: "not scored for this selection" },
    net:  { label: "Best return per $1", legend: "Best return per $1 of liability", ramp: RAMP,
            title: "DRP optimizer — best return per $1 of liability",
            sub: "Mean net return per $1 of liability for the best of the 21 declarable " +
                 "weighting factors. Multiply by liability per cwt for dollars.",
            none: "not scored for this selection" },
    cwt:  { label: "Return per cwt", legend: "Best return per cwt ($)", ramp: RAMP, sized: true,
            title: "DRP optimizer — best return per HUNDREDWEIGHT ($)",
            sub: "Best return per $1 of liability converted to dollars on 100 lb of covered " +
                 "milk, at your declared share and protection factor.",
            none: "not scored for this selection" },
    prem: { label: "Producer premium per cwt", legend: "Producer premium per cwt ($)",
            ramp: COST_RAMP, sized: true, cost: true,
            title: "DRP producer premium — $ per HUNDREDWEIGHT on the recommended declaration",
            sub: "What the producer pays after subsidy, on the same best-net declaration the " +
                 "other metrics rank. Simulated per P18-1; DRP publishes no rate table.",
            none: "not scored for this selection" },
    comm: { label: "Commission per cwt", legend: "Agency commission per cwt ($)",
            ramp: RAMP, sized: true, needsComm: true,
            title: "DRP agency commission — $ per HUNDREDWEIGHT on the recommended declaration",
            sub: "Your commission on the SAME best-net declaration the producer metrics rank. " +
                 "Commission is a percent of TOTAL premium, so the producer premium is grossed " +
                 "back up by the subsidy before the rate is applied.",
            none: "no commission rate on file, or no subsidy for this coverage level" },
    policy: { label: "Net on the declaration", legend: "Net return on the declaration ($)",
            ramp: RAMP, sized: true, needsProd: true,
            title: "DRP optimizer — net return on the whole declaration ($)",
            sub: "The per-hundredweight figure taken up to your declared covered milk " +
                 "production. Sizing changes the dollars and never the ranking.",
            none: "not scored for this selection" }
  };
  var metric = "win";

  // ---------------- geometry
  // us-atlas ships (lon, lat) rings already wound the way d3-geo's spherical interior
  // rule wants, so NOTHING here builds a ring of its own. If you ever add one, wind it
  // CLOCKWISE in (lon, lat): d3-geo takes the interior to be the region LEFT of the
  // ring's travel, so a counter-clockwise ring renders as the globe minus the shape and
  // floods the viewport. See src/drppage.ring_clockwise and the same note in prfpage.
  var path = d3.geoPath(d3.geoAlbersUsa().scale(1300).translate([487.5, 305]));
  var statesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.states).features;
  var countiesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.counties).features;
  var stateById = {}; statesFC.forEach(function (s) { stateById[String(s.id)] = s; });
  var countiesByState = {};
  countiesFC.forEach(function (c) {
    var st = String(c.id).slice(0, 2);
    (countiesByState[st] = countiesByState[st] || []).push(c);
  });

  var svg = d3.select("#map");
  var g = svg.append("g");
  var gStates = g.append("g");
  var stateSel = gStates.selectAll("path").data(statesFC).join("path")
      .attr("class", "state").attr("d", path)
      .on("mousemove", function (ev, d) { hover.call(this, ev, d); })
      .on("mouseout", unhover)
      .on("click", function (ev, d) { ev.stopPropagation(); stateClicked(d); });
  g.append("path").attr("class", "statelines")
      .attr("d", path(topojson.mesh(US_ATLAS, US_ATLAS.objects.states, function () { return true; })));
  var gCounties = g.append("g");
  var gFocus = g.append("path").attr("class", "focusline");

  // ---------------- controls
  var mSel = document.getElementById("mSel"),
      fShare = document.getElementById("fShare"),
      fPf = document.getElementById("fPf"),
      fProd = document.getElementById("fProd");
  var tip = document.getElementById("tooltip");

  function segment(host, items, labelFn, initial, onPick) {
    var el = document.getElementById(host), buttons = [], value = initial;
    items.forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = labelFn(v); b.dataset.v = v;
      b.classList.toggle("on", v === value);
      b.addEventListener("click", function () {
        if (value === v) return;
        value = v;
        buttons.forEach(function (x) { x.classList.toggle("on", x === b); });
        onPick(v);
      });
      el.appendChild(b); buttons.push(b);
    });
    return function () { return value; };
  }

  function pick(list, preferred) {
    if (!list.length) return null;
    return list.indexOf(preferred) >= 0 ? preferred : list[0];
  }

  var option = pick(DATA.options, DATA.default_option);
  var quarter = pick(DATA.quarters, DATA.default_quarter);
  var coverage = pick(DATA.coverages, DATA.default_coverage);

  segment("optSeg", DATA.options, function (v) { return v; },
                          option, function (v) { option = v; onControlChange(); });
  segment("qSeg", DATA.quarters, function (v) {
      return (DATA.quarter_labels && DATA.quarter_labels[v]) || ("Q" + v);
    }, quarter, function (v) { quarter = v; onControlChange(); });
  segment("covSeg", DATA.coverages, function (v) {
      return Math.round(parseFloat(v) * 100) + "%";
    }, coverage, function (v) { coverage = v; onControlChange(); });

  function shareFactor() {
    var v = parseFloat(fShare.value);
    if (!isFinite(v)) v = DATA.decl.share;
    return Math.min(100, Math.max(1, v)) / 100;
  }
  function pfFactor() {
    var v = parseFloat(fPf.value);
    if (!isFinite(v)) v = DATA.decl.pf;
    return Math.min(DATA.decl.pf_max, Math.max(DATA.decl.pf_min, v));
  }
  function production() {
    var v = parseFloat(fProd.value);
    if (!isFinite(v)) v = DATA.decl.prod;
    return Math.min(DATA.decl.prod_max, Math.max(DATA.decl.prod_min, v));
  }

  // ---------------- value lookups
  function cellFor(fips) {
    var s = ST[fips]; if (!s) return null;
    var o = s[option];  if (!o) return null;
    var q = o[quarter]; if (!q) return null;
    return q[coverage] || null;
  }
  // The one common multiplier: declared share x protection factor. P18-1 puts both in
  // TotalPremiumAmount AND Liability, P28-1 puts them in the indemnity.
  function sizing() { return shareFactor() * pfFactor(); }
  function cwtFrom(perDollar, liab) {
    if (perDollar === null || perDollar === undefined || liab === null || liab === undefined)
      return null;
    return perDollar * liab * sizing();
  }
  // ---------------- agency side
  // Commission is a percent of TOTAL premium; every stored DRP metric is normalised on the
  // PRODUCER's premium. The subsidy converts one to the other:
  //     total = producer / (1 - subsidy)      commission = total x rate
  // Neither input is guessed. No subsidy for the coverage level, or no rate on file for DRP,
  // returns null and the county renders "no value" — never zero, which is a different claim.
  var SUBSIDY = DATA.subsidy || {};
  var STATE_ZONE = DATA.state_zone || {};
  function commPct(fips) {
    // Averaged across the AIPs that carry a rate, in this state's commission region. The
    // shipped card is uniform so the average is that number; it stops being uniform the
    // moment an agency enters its real per-AIP schedule, and this keeps working.
    var aips = (DATA.comm && DATA.comm.aips) || [];
    var zone = STATE_ZONE[String(fips)];
    var vals = [];
    aips.forEach(function (a) {
      var r = (zone && a.by_region && a.by_region[zone] !== undefined)
              ? a.by_region[zone] : a.pct;
      if (r !== null && r !== undefined) vals.push(r);
    });
    if (!vals.length) return null;
    return vals.reduce(function (x, y) { return x + y; }, 0) / vals.length;
  }
  function commFrom(c, fips) {
    var producerPerCwt = cwtFrom(c.prem, c.liab);
    var sub = SUBSIDY[coverage];
    var pct = commPct(fips);
    if (producerPerCwt === null || sub === undefined || pct === null || sub >= 1) return null;
    return (producerPerCwt / (1 - sub)) * (pct / 100);
  }

  function valFor(fips) {
    var c = cellFor(fips);
    if (!c) return null;
    if (metric === "comm") return commFrom(c, fips);
    if (metric === "win") return c.win === undefined ? null : c.win;
    if (metric === "net") return c.net === undefined ? null : c.net;
    if (metric === "prem") return cwtFrom(c.prem, c.liab);
    var perCwt = cwtFrom(c.net, c.liab);
    if (metric === "cwt") return perCwt;
    return perCwt === null ? null : perCwt * production() / 100;   // policy
  }

  // ---------------- formatting
  function fmtWin(v) { return v === null || v === undefined ? "&mdash;" : (v * 100).toFixed(1) + "%"; }
  function fmtPer1(v) { return v === null || v === undefined ? "&mdash;" : "$" + v.toFixed(5); }
  function fmtMoney(v, nd) {
    if (v === null || v === undefined) return "&mdash;";
    return "$" + v.toLocaleString(undefined,
      { minimumFractionDigits: nd, maximumFractionDigits: nd });
  }
  function fmtWeight(v) {
    return v === null || v === undefined ? "&mdash;" : (v * 100).toFixed(0) + "%";
  }
  function fmtFull(v) {
    if (metric === "win") return fmtWin(v);
    if (metric === "net") return fmtPer1(v) + " per $1";
    if (metric === "policy") return fmtMoney(v, 0);
    return fmtMoney(v, 4) + "/cwt";
  }
  function fmtShort(v) {
    if (v === null || v === undefined) return "&mdash;";
    if (metric === "win") return Math.round(v * 100) + "%";
    if (metric === "net") return "$" + v.toFixed(4);
    if (metric === "policy") {
      var a = Math.abs(v);
      if (a >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
      if (a >= 1e3) return "$" + (v / 1e3).toFixed(1) + "k";
      return "$" + v.toFixed(0);
    }
    return "$" + v.toFixed(3);
  }
  function readoutSuffix() {
    if (metric === "win") return "";
    if (metric === "net") return " per $1";
    if (metric === "policy") return " total";
    return "/cwt";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function stateNameOf(fips) {
    if (DATA.state_names && DATA.state_names[fips]) return DATA.state_names[fips];
    var s = stateById[fips];
    return (s && s.properties && s.properties.name) || "State";
  }
  function selLabel() {
    return esc(option) + " &middot; " +
      ((DATA.quarter_labels && DATA.quarter_labels[quarter]) || ("Q" + quarter)) +
      " &middot; " + Math.round(parseFloat(coverage) * 100) + "%";
  }

  // ---------------- colour scale + range slider
  var lo = 0, hi = 1, hasData = false, scale = null;
  var rMin = document.getElementById("rMin"),
      rMax = document.getElementById("rMax"),
      rFill = document.getElementById("rFill"),
      rReadout = document.getElementById("rReadout"),
      rBar = document.getElementById("rangebar"),
      bubbleLo = document.getElementById("rBubbleLo"),
      bubbleHi = document.getElementById("rBubbleHi");
  [rMin, rMax].forEach(function (r) { r.min = 0; r.max = UNITS; r.step = 1; });

  // EVERY metric's domain is recomputed over exactly what is on screen — including the
  // two stored ones, which is where this deliberately parts company with prfpage.
  //
  // prfpage can afford a fixed global domain because a PRF win rate means the same thing
  // in every county: same 19-year denominator, same units. DRP's does not. The pooled
  // "All quarters" row is 30 settled quarters and lands in a 3%-20% band; a single
  // quarter is 7 or 8 and reaches 62%. One shared [0, 0.625] ramp therefore renders the
  // DEFAULT view — pooled, 90%, Class — as 50 states of the same pale green, which is
  // an artefact of the denominator and not a fact about dairy. The legend, the range
  // readout and the tooltip all carry the actual numbers, so nothing is hidden by
  // rescaling; DATA.min_win / max_win stay in the payload as the global context.
  function domainFor() {
    var min = null, max = null;
    for (var fips in ST) {
      var v = valFor(fips);
      if (v === null) continue;
      if (min === null || v < min) min = v;
      if (max === null || v > max) max = v;
    }
    return [min, max];
  }

  function syncControls() {
    var m = METRICS[metric];
    document.getElementById("shareWrap").style.display = m.sized ? "" : "none";
    document.getElementById("pfWrap").style.display = m.sized ? "" : "none";
    document.getElementById("prodWrap").style.display = m.needsProd ? "" : "none";
    var notes = document.querySelectorAll("#formulaNote .fn"), anyNote = false;
    Array.prototype.forEach.call(notes, function (el) {
      var on = el.getAttribute("data-m") === metric;
      el.classList.toggle("on", on);
      if (on) anyNote = true;
    });
    document.getElementById("formulaNote").style.display = anyNote ? "block" : "none";
    document.getElementById("pageTitle").textContent = m.title;
    document.getElementById("pageSub").textContent = m.sub + " Generated " + DATA.generated + ".";
    document.getElementById("pageFoot").textContent =
      "DRP is sold STATEWIDE — every plan-83 offer carries county code 998 — so this map has " +
      "no county or grid level and the drill-down stops at the state. Metrics are stored per " +
      "$1 of liability over the settled quarters listed in each tooltip; the protection factor, " +
      "the declared share and the declared production scale dollars only and never a ranking. " +
      "Premium is SIMULATED per RMA's M13 exhibit P18-1 (5,000 iterations over RMA's published " +
      "draws), because DRP has no premium rate table; it is not a filed quote and is not advice " +
      "on what to sell. States with no swept result for the current selection are shown neutral.";
  }

  function applyMetric() {
    var mm = domainFor();
    hasData = mm[0] !== null && mm[0] !== undefined && mm[1] !== null && mm[1] !== undefined;
    lo = hasData ? mm[0] : 0;
    hi = hasData ? mm[1] : 1;
    if (hi <= lo) hi = lo + (metric === "win" ? 0.05 : 0.01);
    scale = d3.scaleQuantize().domain([lo, hi]).range(METRICS[metric].ramp);
    rMin.value = 0; rMax.value = UNITS;
    rBar.style.display = hasData ? "" : "none";
    document.getElementById("rangeLabel").textContent = METRICS[metric].legend + " range";
    updateRange();
    refresh();
  }

  function unitLo() { return Math.min(+rMin.value, +rMax.value); }
  function unitHi() { return Math.max(+rMin.value, +rMax.value); }
  function toVal(u) { return lo + (hi - lo) * u / UNITS; }
  function rangeLo() { return toVal(unitLo()); }
  function rangeHi() { return toVal(unitHi()); }
  function isFullRange() { return unitLo() <= 0 && unitHi() >= UNITS; }
  function updateRange() {
    var a = unitLo() / UNITS, b = unitHi() / UNITS;
    rFill.style.left = (a * 100) + "%";
    rFill.style.width = ((b - a) * 100) + "%";
    bubbleLo.innerHTML = fmtShort(rangeLo());
    bubbleLo.style.left = "calc(" + (a * 100) + "% - " + (a * 16 - 8) + "px)";
    bubbleHi.innerHTML = fmtShort(rangeHi());
    bubbleHi.style.left = "calc(" + (b * 100) + "% - " + (b * 16 - 8) + "px)";
    rReadout.innerHTML = fmtShort(rangeLo()) + " &ndash; " + fmtShort(rangeHi()) + readoutSuffix();
  }

  function drawLegend() {
    var el = document.getElementById("legend");
    if (!hasData) { el.style.display = "none"; return; }
    el.style.display = "";
    var cells = METRICS[metric].ramp.map(function (c) {
      return '<div class="l-cell" style="background:' + c + '"></div>';
    }).join("");
    var thr = scale.thresholds();
    var labels = '<span>' + fmtShort(lo) + '</span>' +
      thr.map(function (t) { return '<span>' + fmtShort(t) + '</span>'; }).join("");
    el.innerHTML =
      '<div class="l-title">' + METRICS[metric].legend +
      (METRICS[metric].cost ? ' &mdash; darker is MORE expensive' : '') + '</div>' +
      '<div class="l-row">' + cells + '</div>' +
      '<div class="l-labels">' + labels + '</div>' +
      '<div class="l-none"><span class="sw"></span>' + METRICS[metric].none + '</div>';
  }

  // ---------------- tooltip
  function tipHtml(fips) {
    var c = cellFor(fips), v = valFor(fips);
    var h = '<div class="t-name">' + esc(stateNameOf(fips)) + '</div>' +
            '<div class="t-val">' + esc(METRICS[metric].legend) + ': ' + fmtFull(v) + '</div>';
    if (!c) {
      var a = AVAIL[fips];
      h += '<div class="t-line">' + (a
        ? 'DRP is offered here (' + a.q + ' quarterly endorsements, ' + a.o +
          ' pricing options in RY' + DATA.avail_ry + ') but the optimizer has no result ' +
          'for this pricing option / quarter / coverage.'
        : 'No DRP offer rows loaded for this state.') + '</div>';
      return h;
    }
    h += '<div class="t-grid">' +
         '<div class="t-line">best net ' + fmtPer1(c.net) + ' per $1 at weighting factor ' +
         fmtWeight(c.nw) + ' &middot; win ' + fmtWin(c.nwin) + '</div>' +
         '<div class="t-line">best win ' + fmtWin(c.win) + ' at weighting factor ' +
         fmtWeight(c.ww) + ' &middot; net ' + fmtPer1(c.wnet) + '</div>' +
         '<div class="t-line">median shape ' + fmtPer1(c.med) + ' &middot; ' +
         Math.round((c.pos || 0) * 100) + '% of ' + c.sh + ' shapes positive</div>' +
         '</div>';
    h += '<div class="t-math">liability ' + fmtMoney(c.liab * sizing(), 3) + '/cwt' +
         ' &middot; producer premium ' + fmtMoney(cwtFrom(c.prem, c.liab), 4) + '/cwt' +
         '</div>';
    h += '<div class="t-math">' + c.n + ' settled quarters, ' + esc(c.q0) + '&ndash;' +
         esc(c.q1) + ' &middot; premium simulated on RY' + c.dry + ' draws</div>';
    if (c.pin) {
      h += '<div class="t-warn">' + c.pin + ' of ' + c.n + ' quarters had the weighting ' +
           'factor PINNED by RMA (only one side of the market was published), so every ' +
           'shape filed the same declaration there.</div>';
    }
    return h;
  }

  function place(ev, html) {
    tip.style.display = "block";
    tip.innerHTML = html;
    var wrap = document.getElementById("mapWrap").getBoundingClientRect();
    var x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 10;
    if (x > wrap.width - 350) x -= 370;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hover(ev, d) {
    d3.select(this).classed("hovered", true);
    place(ev, tipHtml(String(d.id)));
  }
  function unhover() {
    d3.select(this).classed("hovered", false);
    tip.style.display = "none";
  }
  function hoverCounty(ev, d) {
    d3.select(this).classed("hovered", true);
    var fips = String(d.id).slice(0, 2);
    place(ev, tipHtml(fips) +
      '<div class="t-warn">DRP is sold statewide (county code 998): every county in ' +
      esc(stateNameOf(fips)) + ' carries this same value. There is no county-level DRP ' +
      'number to drill into.</div>');
  }

  // ---------------- drill-down: nation -> state, and NO FURTHER
  // Two levels, because DRP has exactly two grains: the nation and the state. Drilling
  // into a state paints its counties in ONE colour — the county-998 fact drawn — rather
  // than pretending a county number exists.
  var K_MIN = 1, K_MAX = 48;
  var level = 0;
  var focusState = null;
  var curK = 1;

  var zoom = d3.zoom().scaleExtent([K_MIN, K_MAX]).on("zoom", function (ev) {
    g.attr("transform", ev.transform);
    curK = ev.transform.k;
    syncZoomUI();
  });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", function () { drillOut(); });

  // Animate, EXCEPT in a hidden tab. d3's transition scheduler runs on
  // requestAnimationFrame, which browsers suspend while a tab is backgrounded, so an
  // animated zoom started there never advances past CREATED — the map freezes mid-flight
  // and stays frozen after you switch back. Applying the transform directly when
  // document.hidden keeps it correct. Copied from src/prfpage.py; do not "simplify".
  function applyTransform(t, dur) {
    if (dur === 0 || document.hidden) svg.call(zoom.transform, t);
    else svg.transition().duration(dur).call(zoom.transform, t);
  }
  function zoomToFeature(f, dur) {
    var b = path.bounds(f);
    var dx = b[1][0] - b[0][0], dy = b[1][1] - b[0][1];
    var cx = (b[0][0] + b[1][0]) / 2, cy = (b[0][1] + b[1][1]) / 2;
    var k = Math.max(K_MIN, Math.min(K_MAX, 0.85 / Math.max(dx / 975, dy / 610)));
    applyTransform(d3.zoomIdentity.translate(975 / 2 - k * cx, 610 / 2 - k * cy).scale(k),
                   dur === undefined ? 650 : dur);
  }
  function resetZoom(dur) {
    applyTransform(d3.zoomIdentity, dur === undefined ? 650 : dur);
  }

  function stateClicked(d) {
    focusState = String(d.id);
    level = 1;
    zoomToFeature(d);
    applyLevel();
  }
  function drillOut() {
    if (level !== 1) return;
    focusState = null; level = 0; resetZoom();
    applyLevel();
  }
  function drillTo(lv) {
    if (lv === 0) { level = 0; focusState = null; resetZoom(); }
    applyLevel();
  }

  function renderCounties() {
    var feat = focusState ? stateById[focusState] : null;
    gFocus.attr("d", (level === 1 && feat) ? path(feat) : null);
    if (level !== 1 || !focusState) { gCounties.selectAll("path").remove(); return; }
    var v = valFor(focusState);
    var rlo = rangeLo(), rhi = rangeHi(), eps = (hi - lo) * 1e-9;
    var fill = (v === null || v === undefined || v < rlo - eps || v > rhi + eps)
             ? NONE : scale(v);
    gCounties.selectAll("path")
      .data(countiesByState[focusState] || [], function (d) { return d.id; })
      .join("path")
        .attr("class", "countycell")
        .attr("d", path)
        .attr("fill", fill)        // ONE colour: county code 998, drawn
        .on("mousemove", function (ev, d) { hoverCounty.call(this, ev, d); })
        .on("mouseout", unhover);
  }

  function applyLevel() {
    stateSel.classed("dimmed", function (d) {
      return level === 1 && String(d.id) !== focusState;
    });
    renderCounties();
    updateCrumb();
  }

  var crumb = document.getElementById("crumb");
  function updateCrumb() {
    var h = '<span class="' + (level === 0 ? "c-here" : "c-step") + '" data-lv="0">' +
            'United States</span>';
    if (focusState) {
      h += '<span class="c-sep">&rsaquo;</span><span class="c-here">' +
           esc(stateNameOf(focusState)) + '</span>';
    }
    // The breadcrumb stops HERE, and says why. DRP has no county or grid level to offer.
    var n = focusState ? (countiesByState[focusState] || []).length : 0;
    var hint = level === 0
      ? "click a state &mdash; DRP is sold statewide, so that is the finest grain"
      : "statewide rate: all " + n + " counties share this value (county code 998) " +
        "&middot; click away to go back";
    h += '<span class="c-hint">' + hint + '</span>';
    crumb.innerHTML = h;
    crumb.querySelectorAll(".c-step").forEach(function (el) {
      el.addEventListener("click", function (ev) {
        ev.stopPropagation(); drillTo(parseInt(el.getAttribute("data-lv"), 10));
      });
    });
  }

  // ---------------- zoom slider
  // Logarithmic, so each step of the thumb is the same PROPORTIONAL change — a linear
  // map would spend most of its travel in the first 2x.
  var zSlider = document.getElementById("zSlider"), zLabel = document.getElementById("zLabel");
  function kToSlider(k) { return 100 * Math.log(k / K_MIN) / Math.log(K_MAX / K_MIN); }
  function sliderToK(v) { return K_MIN * Math.pow(K_MAX / K_MIN, v / 100); }
  function syncZoomUI() {
    zSlider.value = String(kToSlider(curK));
    zLabel.innerHTML = (curK < 10 ? curK.toFixed(1) : Math.round(curK)) + "&times;";
  }
  function zoomToK(k) {
    var kk = Math.max(K_MIN, Math.min(K_MAX, k));
    if (document.hidden) svg.call(zoom.scaleTo, kk);
    else svg.transition().duration(120).call(zoom.scaleTo, kk);
  }
  zSlider.addEventListener("input", function () { zoomToK(sliderToK(+zSlider.value)); });
  document.getElementById("zIn").addEventListener("click", function (ev) {
    ev.stopPropagation(); zoomToK(curK * 1.6);
  });
  document.getElementById("zOut").addEventListener("click", function (ev) {
    ev.stopPropagation(); zoomToK(curK / 1.6);
  });

  // ---------------- render / recolor
  function refresh() {
    var rlo = rangeLo(), rhi = rangeHi(), eps = (hi - lo) * 1e-9;
    var shaded = 0;
    stateSel.attr("fill", function (d) {
      var v = valFor(String(d.id));
      if (v === null || v < rlo - eps || v > rhi + eps) return NONE;
      shaded++;
      return scale(v);
    });

    document.getElementById("countLine").innerHTML = !hasData ? "" : (isFullRange()
      ? shaded + " states with " + METRICS[metric].legend.toLowerCase() + " for " + selLabel()
      : shaded + " states at " + fmtShort(rlo) + "&ndash;" + fmtShort(rhi) +
        readoutSuffix() + " for " + selLabel());

    var note = document.getElementById("note"), msg = "";
    if (DATA.row_count === 0) {
      msg = "DRP optimizer sweep not run yet — the drp_opt_best table is empty. Run " +
            "`python -m src.drpopt --all` to populate it; the map will shade as results land.";
    } else if (shaded === 0) {
      msg = "No state has a value for this selection" +
            (isFullRange() ? "" : " and range") + ".";
    }
    note.style.display = msg ? "block" : "none";
    note.textContent = msg;
    drawLegend();
    renderCounties();
  }

  // Every metric's domain follows the current selection (see domainFor), so a change of
  // pricing option / quarter / coverage rebuilds the scale. The SIZING controls (share,
  // protection factor, production) only matter to the three dollar metrics: for `win`
  // and `net` they are no-ops, which is the collapse property made visible rather than
  // merely asserted.
  function isDerived() { return !!METRICS[metric].sized; }
  function onControlChange() { applyMetric(); }
  function onSizingChange() {
    if (isDerived()) applyMetric();
  }

  // ---------------- lens
  // Producer premium per cwt sits under BUY: it is what the producer pays, and it is the
  // cost side of their own return. Commission is the only agency metric DRP has.
  var LENS = { buy: ["win", "net", "cwt", "prem", "policy"], sell: ["comm"] };
  var lens = "buy";

  function fillMetricSelect() {
    var keys = LENS[lens];
    mSel.innerHTML = "";
    keys.forEach(function (k) {
      if (!METRICS[k]) return;
      var o = document.createElement("option");
      o.value = k; o.textContent = METRICS[k].legend;
      mSel.appendChild(o);
    });
    if (keys.indexOf(metric) < 0) {
      metric = keys[0];
      mSel.value = metric;
      onControlChange();
    } else {
      mSel.value = metric;
    }
  }

  document.getElementById("lensSeg").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-lens]");
    if (!b || b.dataset.lens === lens) return;
    lens = b.dataset.lens;
    this.querySelectorAll("button").forEach(function (x) {
      x.classList.toggle("on", x.dataset.lens === lens);
    });
    fillMetricSelect();
  });
  fillMetricSelect();

  mSel.addEventListener("change", function () {
    if (metric === mSel.value) return;
    metric = mSel.value;
    syncControls();
    applyMetric();
  });
  ["input", "change"].forEach(function (evt) {
    [fShare, fPf, fProd].forEach(function (el) {
      el.addEventListener(evt, onSizingChange);
    });
  });
  [rMin, rMax].forEach(function (r) {
    r.addEventListener("input", function () { updateRange(); refresh(); });
  });
  document.getElementById("rReset").addEventListener("click", function () {
    rMin.value = 0; rMax.value = UNITS; updateRange(); refresh();
  });

  syncControls();
  applyMetric();     // must precede applyLevel(): it builds the colour scale
  applyLevel();
  syncZoomUI();
})();
</script>
</body>
</html>
"""
