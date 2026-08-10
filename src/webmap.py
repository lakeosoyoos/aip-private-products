"""Self-contained interactive US availability map (output/product_map.html).

Generates a single offline HTML file — d3 v7, topojson-client and the us-atlas
counties-10m topology are embedded inline (data/assets/, fetched once), so the
result makes ZERO network requests and works when double-clicked from disk.

Data-grain honesty rules (enforced in build_payload + surfaced in the UI):
  * private products are STATE-grain (statewide SERFF filings): at county zoom
    they shade every county of their filed states and carry a "statewide" badge.
  * federal products use COUNTY-grain rows from product_counties where they
    exist; states without county rows fall back to whole-state shading with a
    "county detail pending ADM" note (banner shown at county zoom while any
    displayed federal product lacks county rows).
  * products whose notes mark them nationwide count everywhere ("nationwide"
    badge).
  * products with NO states/counties data are never painted — they appear only
    in the "unmapped products" list.

Regenerate:  .venv/bin/python -m src.webmap
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import urllib.request
from pathlib import Path

from . import config
from .stack import LAYERS, classified_products

ASSETS_DIR = config.DATA_DIR / "assets"
OUT_PATH = config.OUTPUT_DIR / "product_map.html"

# The only network calls this module is allowed to make, and only when the
# cached copy is missing from data/assets/.
ASSETS = {
    "d3.v7.min.js": "https://d3js.org/d3.v7.min.js",
    "topojson-client.min.js":
        "https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js",
    "counties-10m.json": "https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json",
}

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}


def _is_nationwide(notes: str | None) -> bool:
    return "nationwide" in (notes or "").lower()


def build_payload(conn: sqlite3.Connection) -> dict:
    """Build the JSON data payload the map runs on. Pure read; testable."""
    # county rows grouped per product: {pid: {fips: {"state":.., "crops": set}}}
    county_rows = 0
    counties_by_pid: dict[int, dict[str, dict]] = {}
    for r in conn.execute(
            "SELECT product_id, crop, state, county_fips FROM product_counties"):
        county_rows += 1
        ent = counties_by_pid.setdefault(r["product_id"], {}).setdefault(
            r["county_fips"], {"state": r["state"], "crops": set()})
        ent["crops"].add(r["crop"])

    products = []
    all_crops: set[str] = set()
    for p in classified_products(conn):
        pid = p["product_id"]
        crops = sorted({c.strip() for c in (p["crops"] or "").split(";") if c.strip()})
        state_rows = sorted({s.strip() for s in (p["sts"] or "").split(";") if s.strip()})
        cmap = counties_by_pid.get(pid, {})
        county_states = sorted({e["state"] for e in cmap.values()})
        county_crops = sorted({c for e in cmap.values() for c in e["crops"]})
        states = sorted(set(state_rows) | set(county_states))
        nationwide = _is_nationwide(p["notes"])

        if nationwide:
            scope = "nationwide"
        elif states:
            scope = "mapped"
        else:
            scope = "unmapped"

        subsidized = p["bucket"] != "private"
        # Federal county detail pending: no ADM county rows at all (including
        # unmapped/nationwide products), or filed states not yet covered by
        # county rows. Painted at state grain wherever rows are missing.
        county_pending = subsidized and (
            not cmap or bool(set(states) - set(county_states)))

        prod_all_crops = sorted(set(crops) | set(county_crops))
        all_crops.update(prod_all_crops)
        products.append({
            "id": pid,
            "name": p["name"],
            "bucket": p["bucket"],
            "subsidized": subsidized,
            "aip_code": p["aip_code"],
            "aip": p["aip_name"] if p["aip_code"] else "All AIPs",
            "layer": p["layer"],
            "analog": p["federal_analog"],
            "crops": crops,
            "all_crops": prod_all_crops,
            "doc_url": p["doc_url"] or p["source_url"],
            "scope": scope,
            "states": states,
            "county_states": county_states,
            "counties": {f: sorted(e["crops"]) for f, e in cmap.items()},
            "county_pending": county_pending,
        })

    aips = [dict(r) for r in conn.execute(
        "SELECT aip_code AS code, name FROM aips ORDER BY name")]
    return {
        "generated": _dt.date.today().isoformat(),
        "products": products,
        "crops": sorted(all_crops),
        "aips": aips,
        "county_rows": county_rows,
        "layer_labels": {k: lbl for k, lbl, _, _ in LAYERS},
        "state_fips": STATE_FIPS,
    }


# ------------------------------------------------------------------ assets

def ensure_assets() -> dict[str, str]:
    """Return asset-name -> file contents, downloading any missing file once."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in ASSETS.items():
        path = ASSETS_DIR / name
        if not path.exists() or path.stat().st_size == 0:
            print(f"fetching {url} -> {path}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "aip-products-catalog/0.1 (webmap asset fetch)"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                path.write_bytes(resp.read())
        out[name] = path.read_text(encoding="utf-8")
    return out


def _js_embed_json(obj) -> str:
    """JSON serialized for safe inline embedding inside a <script> block."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


# ------------------------------------------------------------------ html

def render_html(payload: dict, d3_js: str, topojson_js: str, atlas: dict) -> str:
    for blob in (d3_js, topojson_js):
        if "</script" in blob.lower():
            raise ValueError("asset JS contains '</script'; cannot inline safely")
    html = _TEMPLATE
    html = html.replace("__GENERATED__", payload["generated"])
    html = html.replace("__D3__", d3_js)
    html = html.replace("__TOPOJSON__", topojson_js)
    html = html.replace("__ATLAS__", _js_embed_json(atlas))
    html = html.replace("__PAYLOAD__", _js_embed_json(payload))
    return html


def generate(db_path: Path | str | None = None, out_path: Path | str | None = None) -> Path:
    assets = ensure_assets()
    dbp = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)  # read-only
    conn.row_factory = sqlite3.Row
    try:
        payload = build_payload(conn)
    finally:
        conn.close()
    atlas = json.loads(assets["counties-10m.json"])
    html = render_html(payload, assets["d3.v7.min.js"],
                       assets["topojson-client.min.js"], atlas)
    out = Path(out_path or OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    n = len(payload["products"])
    print(f"wrote {out} ({out.stat().st_size/1e6:.2f} MB, {n} products, "
          f"{payload['county_rows']} county rows)")
    return out


# The template uses __TOKENS__ (not str.format) so the JS braces stay literal.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIP crop-insurance product availability map</title>
<style>
  :root {
    color-scheme: light;
    --surface: #fcfcfb; --page: #f9f9f7;
    --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --zero: #f0efec; --accent: #2a78d6;
  }
  * { box-sizing: border-box; margin: 0; }
  html, body { height: 100%; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink); font-size: 14px;
    display: flex; flex-direction: column;
  }
  header { padding: 14px 18px 10px; }
  header h1 { font-size: 17px; font-weight: 650; }
  header .sub { color: var(--ink-2); font-size: 12.5px; margin-top: 2px; }
  .filters {
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 8px 18px 10px; border-bottom: 1px solid var(--grid);
    background: var(--surface);
  }
  .filters label { color: var(--ink-2); font-size: 12px; }
  .filters select {
    font: inherit; font-size: 13px; padding: 4px 6px; max-width: 230px;
    border: 1px solid var(--baseline); border-radius: 6px; background: var(--surface);
    color: var(--ink);
  }
  /* ---- drill-down chrome: breadcrumb + zoom control (matches the PRF map) ---- */
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
  #zSlider { writing-mode: vertical-lr; direction: rtl; width: 22px; height: 104px; accent-color: var(--accent); }
  #zLabel { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  #main { flex: 1; display: flex; min-height: 0; }
  #mapWrap { flex: 1; position: relative; min-width: 0; }
  #map { width: 100%; height: 100%; display: block; }
  .state, .county { stroke: var(--surface); cursor: pointer; vector-effect: non-scaling-stroke; }
  .state { stroke-width: 0.7; }
  .county { stroke-width: 0.6; }
  .state.dimmed { opacity: 0.25; pointer-events: none; }
  .state.hovered, .county.hovered { stroke: var(--ink); stroke-width: 1.4; }
  /* Hover readout — a dedicated top-most outline, NOT only a stroke on the hovered shape.
     Borders are SHARED between neighbours and in SVG the later sibling paints over the
     earlier one, so a stroke on the shape alone is whole on some edges and erased on others.
     The pale casing under the dark line keeps it legible at both ends of the blue ramp;
     non-scaling so it holds its weight when zoomed into a state. */
  .hovercase { fill: none; stroke: var(--surface); stroke-width: 3.4; stroke-linejoin: round;
               pointer-events: none; vector-effect: non-scaling-stroke; opacity: 0.85; }
  .hoverline { fill: none; stroke: var(--ink); stroke-width: 1.5; stroke-linejoin: round;
               pointer-events: none; vector-effect: non-scaling-stroke; }
  #stateOutline { fill: none; stroke: var(--ink); stroke-width: 1.2; pointer-events: none;
                  vector-effect: non-scaling-stroke; }
  #tooltip {
    position: absolute; pointer-events: none; display: none; z-index: 5;
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.12); padding: 7px 10px; font-size: 12.5px;
    max-width: 260px;
  }
  #tooltip .t-name { font-weight: 650; }
  #tooltip .t-count { color: var(--ink-2); }
  #legend {
    position: absolute; left: 16px; bottom: 14px; background: var(--surface);
    border: 1px solid var(--ring); border-radius: 8px; padding: 8px 10px; font-size: 11.5px;
  }
  #legend .l-title { color: var(--ink-2); margin-bottom: 5px; }
  #legend .l-row { display: flex; align-items: center; gap: 0; }
  #legend .l-cell { width: 26px; height: 10px; }
  #legend .l-labels { display: flex; font-size: 10.5px; color: var(--muted); }
  #legend .l-labels span { width: 26px; text-align: left; }
  #pendingNote {
    position: absolute; top: 12px; left: 16px; right: 16px; z-index: 4; display: none;
    background: #fdf6e7; border: 1px solid #eda100; border-radius: 8px;
    color: #6b4b00; padding: 7px 11px; font-size: 12.5px;
  }
  #panel {
    width: 360px; flex: none; overflow-y: auto; background: var(--surface);
    border-left: 1px solid var(--grid); padding: 14px 16px 20px;
  }
  #panel h2 { font-size: 14.5px; font-weight: 650; }
  #panel .p-sub { color: var(--ink-2); font-size: 12px; margin: 2px 0 10px; }
  .prod {
    border: 1px solid var(--grid); border-radius: 8px; padding: 8px 10px;
    margin-bottom: 8px; background: var(--page);
  }
  .prod .p-name { font-weight: 600; font-size: 13px; }
  .prod .p-name a { color: var(--accent); text-decoration: none; }
  .prod .p-name a:hover { text-decoration: underline; }
  .prod .p-meta { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
  .prod .p-crops { color: var(--muted); font-size: 11.5px; margin-top: 3px; }
  .badges { margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px; }
  .badge {
    display: inline-block; font-size: 10.5px; font-weight: 600; border-radius: 999px;
    padding: 1.5px 8px; border: 1px solid transparent;
  }
  .b-sub   { background: #e2f3e2; color: #006300; border-color: #9ed49e; }
  .b-unsub { background: #fdeeee; color: #8f2727; border-color: #eec2c2; }
  .b-grain { background: var(--zero); color: var(--ink-2); border-color: var(--baseline); }
  .b-pending { background: #fdf6e7; color: #6b4b00; border-color: #eda100; }
  details.unmapped { margin-top: 14px; }
  details.unmapped summary { cursor: pointer; color: var(--ink-2); font-size: 12.5px; }
  details.unmapped .prod { opacity: 0.85; }
  .empty { color: var(--muted); font-size: 12.5px; padding: 8px 0; }
  footer { padding: 6px 18px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--grid); }
</style>
</head>
<body>
<header>
  <h1>Crop-insurance product availability</h1>
  <div class="sub">Shading = number of matching products available in each state / county.
  Click a state to zoom to counties; click the background or the breadcrumb to zoom out.
  Scroll, drag, or use the zoom control to move around. Generated __GENERATED__.</div>
</header>
<div class="filters">
  <label>Crop <select id="fCrop"><option value="">All crops</option></select></label>
  <label>AIP <select id="fAip"><option value="">All AIPs</option></select></label>
  <label>Subsidy <select id="fSub">
    <option value="">All products</option>
    <option value="sub">Subsidized federal</option>
    <option value="unsub">Unsubsidized private</option>
  </select></label>
  <span id="countLine" style="color:var(--muted);font-size:12px;margin-left:auto"></span>
</div>
<div id="main">
  <div id="mapWrap">
    <div id="pendingNote"></div>
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
  <div id="panel"></div>
</div>
<footer>Private products are statewide filings (state grain). Federal products show county grain
where ADM county rows are loaded; otherwise whole-state shading with a "county detail pending ADM"
flag. Products with no availability data are listed under "unmapped", never painted.</footer>

<script>__D3__</script>
<script>__TOPOJSON__</script>
<script>
var US_ATLAS = __ATLAS__;
var DATA = __PAYLOAD__;

(function () {
  "use strict";
  var FIPS2ST = {};
  Object.keys(DATA.state_fips).forEach(function (st) { FIPS2ST[DATA.state_fips[st]] = st; });
  var STATE_NAMES = {};

  // Per-product per-state county index: p._byState[ST] = {fips: [crops]}
  DATA.products.forEach(function (p) {
    p._byState = {};
    Object.keys(p.counties).forEach(function (f) {
      var st = FIPS2ST[f.slice(0, 2)];
      if (!st) return;
      (p._byState[st] = p._byState[st] || {})[f] = p.counties[f];
    });
  });

  // ---------------- filters
  var fCrop = document.getElementById("fCrop"),
      fAip = document.getElementById("fAip"),
      fSub = document.getElementById("fSub");
  DATA.crops.forEach(function (c) {
    var o = document.createElement("option"); o.value = c; o.textContent = c;
    fCrop.appendChild(o);
  });
  DATA.aips.forEach(function (a) {
    var o = document.createElement("option"); o.value = a.code;
    o.textContent = a.name + " (" + a.code + ")";
    fAip.appendChild(o);
  });

  function filt() {
    return { crop: fCrop.value, aip: fAip.value, sub: fSub.value };
  }
  function matches(p, f) {
    if (f.sub === "sub" && !p.subsidized) return false;
    if (f.sub === "unsub" && p.subsidized) return false;
    // Federal products (aip_code null) are offered through every AIP.
    if (f.aip && p.aip_code && p.aip_code !== f.aip) return false;
    if (f.crop && p.all_crops.indexOf(f.crop) < 0) return false;
    return true;
  }
  function inState(p, st) {
    return p.scope === "nationwide" || p.states.indexOf(st) >= 0;
  }

  // Grain honesty: how product p reaches state `st` under filter f.
  // null = not available | "county" = honored ADM county rows |
  // "statewide" = private statewide filing | "nationwide" = counts everywhere |
  // "pending" = FEDERAL product painted at state grain because its ADM county
  //             rows are missing (county detail pending ADM).
  function modeInState(p, st, f) {
    if (p.scope === "unmapped") return null;
    var cs = p._byState[st];
    if (cs) {
      // County detail exists for this state. If a crop filter is set but this
      // product's ADM rows in this state don't list that crop at all, fall
      // back to state grain (partial ADM); else honor the county rows.
      if (f.crop) {
        var anyCrop = Object.keys(cs).some(function (k) { return cs[k].indexOf(f.crop) >= 0; });
        if (!anyCrop) {
          if (p.crops.indexOf(f.crop) >= 0 && inState(p, st))
            return p.subsidized ? "pending" : "statewide";
          return null;
        }
      }
      return "county";
    }
    if (p.scope === "nationwide") return p.subsidized ? "pending" : "nationwide";
    if (p.states.indexOf(st) < 0) return null;
    return p.subsidized ? "pending" : "statewide";
  }

  // Per-county contribution: same tags; "county" is checked against the fips.
  function countyGrain(p, st, fips, f) {
    var m = modeInState(p, st, f);
    if (m !== "county") return m;
    var cc = p._byState[st][fips];
    if (!cc) return null;
    if (f.crop && cc.indexOf(f.crop) < 0) return null;
    return "county";
  }

  function stateAvail(p, st, f) {
    return matches(p, f) && modeInState(p, st, f) !== null;
  }

  // ---------------- geometry
  var statesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.states).features
      .filter(function (d) { return FIPS2ST[d.id]; });
  statesFC.forEach(function (d) { STATE_NAMES[FIPS2ST[d.id]] = d.properties.name; });
  var countiesAll = topojson.feature(US_ATLAS, US_ATLAS.objects.counties).features;
  // counties-10m.json ships unprojected (lon/lat); project with the same
  // AlbersUSA parameters us-atlas uses for its pre-projected 975x610 files.
  var path = d3.geoPath(d3.geoAlbersUsa().scale(1300).translate([487.5, 305]));

  var svg = d3.select("#map");
  svg.append("rect").attr("x", 0).attr("y", 0).attr("width", 975).attr("height", 610)
     .attr("fill", "transparent").on("click", zoomOut);
  var g = svg.append("g");
  var gStates = g.append("g"), gCounties = g.append("g");
  var outline = g.append("path").attr("id", "stateOutline");
  // Appended last so nothing overdraws it. mark() drives it from the same hovered/pinned
  // state the tooltip and side panel use, so all three always agree about what is under the
  // cursor -- including the PINNED county, which otherwise had no visual anchor at all.
  var gHoverCase = g.append("path").attr("class", "hovercase");
  var gHoverLine = g.append("path").attr("class", "hoverline");
  function showHover(feat) {
    var d = feat ? path(feat) : null;
    gHoverCase.attr("d", d);
    gHoverLine.attr("d", d);
  }

  // ---------------- zoom
  // The transform used to be written straight onto `g`, which meant there was no wheel or
  // drag panning and nothing a slider could bind to. Routing every change through a real
  // d3.zoom gives one source of truth that the buttons, the slider and the drill-down all
  // share. Ceiling is 12x: this map's finest grain is the county, so magnifying past the
  // point where county lines are legible would show nothing further.
  var K_MIN = 1, K_MAX = 12, curK = 1;
  var zoom = d3.zoom().scaleExtent([K_MIN, K_MAX]).on("zoom", function (ev) {
    g.attr("transform", ev.transform);
    curK = ev.transform.k;
    syncZoomUI();
  });
  svg.call(zoom).on("dblclick.zoom", null);

  // Animate, EXCEPT in a hidden tab. d3's transition scheduler is driven by
  // requestAnimationFrame, which browsers suspend while a tab is backgrounded, so an
  // animated zoom started there never advances past its CREATED state — the map stays
  // frozen at whatever zoom it had, and stays frozen after you switch back. Applying the
  // transform directly when document.hidden keeps the map correct either way.
  function applyTransform(t, dur) {
    if (dur === 0 || document.hidden) svg.call(zoom.transform, t);
    else svg.transition().duration(dur).call(zoom.transform, t);
  }
  function zoomToFeature(d, dur) {
    var b = path.bounds(d),
        dx = b[1][0] - b[0][0], dy = b[1][1] - b[0][1],
        x = (b[0][0] + b[1][0]) / 2, y = (b[0][1] + b[1][1]) / 2,
        k = Math.max(K_MIN, Math.min(K_MAX, 0.9 / Math.max(dx / 975, dy / 610)));
    applyTransform(d3.zoomIdentity.translate(975 / 2 - k * x, 610 / 2 - k * y).scale(k),
                   dur === undefined ? 700 : dur);
  }
  function resetZoom(dur) {
    applyTransform(d3.zoomIdentity, dur === undefined ? 600 : dur);
  }

  var zSlider = document.getElementById("zSlider"), zLabel = document.getElementById("zLabel");
  // Logarithmic so each step of the thumb is the same PROPORTIONAL change.
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

  // ---------------- breadcrumb
  var crumb = document.getElementById("crumb");
  function updateCrumb() {
    var h = '<span class="' + (currentState ? "c-step" : "c-here") + '" data-lv="0">United States</span>';
    if (currentState) {
      h += '<span class="c-sep">&rsaquo;</span><span class="c-here">' +
           esc(currentState.name) + '</span>';
    }
    // No third level: product availability is published per COUNTY and there is nothing
    // finer to drill into. (The PRF map has a grid level because RMA prices a 0.25-degree
    // rainfall lattice; product availability has no such grain.)
    h += '<span class="c-hint">' +
         (currentState ? "county grain &middot; click away to go back"
                       : "click a state to zoom") + '</span>';
    crumb.innerHTML = h;
    crumb.querySelectorAll(".c-step").forEach(function (el) {
      el.addEventListener("click", function (ev) { ev.stopPropagation(); zoomOut(); });
    });
  }

  var stateSel = gStates.selectAll("path").data(statesFC).join("path")
      .attr("class", "state").attr("d", path)
      .on("click", function (ev, d) { ev.stopPropagation(); zoomToState(d); })
      .on("mousemove", function (ev, d) { hover(ev, { type: "state", st: FIPS2ST[d.id], name: d.properties.name }); })
      .on("mouseout", unhover);

  // ---------------- color: sequential blue ramp (light->dark = few->many)
  var RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  var ZERO = getComputedStyle(document.documentElement).getPropertyValue("--zero").trim() || "#f0efec";
  function makeScale(max) {
    if (max < 1) max = 1;
    var n = Math.min(RAMP.length, Math.max(2, max));
    var ramp = RAMP.slice(0, n);
    return { scale: d3.scaleQuantize().domain([1, max + 1]).range(ramp), max: max, ramp: ramp };
  }
  function fillFor(count, sc) { return count > 0 ? sc.scale(count) : ZERO; }

  function legend(sc, what) {
    var el = document.getElementById("legend");
    var bins = sc.ramp.length;
    var step = sc.max / bins;
    var cells = sc.ramp.map(function (c) { return '<div class="l-cell" style="background:' + c + '"></div>'; }).join("");
    var labels = '<span>0</span>' + sc.ramp.map(function (_, i) {
      return "<span>" + (i === bins - 1 ? sc.max : Math.max(1, Math.round((i + 1) * step))) + "</span>";
    }).join("");
    el.innerHTML = '<div class="l-title">matching products per ' + what + '</div>' +
      '<div class="l-row"><div class="l-cell" style="background:' + ZERO + ';border:1px solid var(--grid)"></div>' + cells + "</div>" +
      '<div class="l-labels"><span>&nbsp;</span>' + labels + "</div>";
  }

  // ---------------- zoom state machine
  var currentState = null;   // {st, name, feature}
  var hovered = null, pinned = null;

  function zoomToState(d) {
    var st = FIPS2ST[d.id];
    if (currentState && currentState.st === st) return;
    currentState = { st: st, name: d.properties.name, feature: d };
    pinned = null; hovered = null;
    var fips2 = d.id;
    var cts = countiesAll.filter(function (c) { return c.id.slice(0, 2) === fips2; });
    gCounties.selectAll("path").data(cts, function (c) { return c.id; }).join("path")
        .attr("class", "county").attr("d", path)
        .on("click", function (ev, c) {
          ev.stopPropagation();
          pinned = { type: "county", st: st, fips: c.id, name: c.properties.name + " County" };
          refresh();
        })
        .on("mousemove", function (ev, c) { hover(ev, { type: "county", st: st, fips: c.id, name: c.properties.name + " County" }); })
        .on("mouseout", unhover);
    outline.attr("d", path(d));
    stateSel.classed("dimmed", function (s) { return s.id !== d.id; })
            .style("display", function (s) { return s.id === d.id ? "none" : null; });
    zoomToFeature(d);
    updateCrumb();
    refresh();
  }

  function zoomOut() {
    if (!currentState) return;
    currentState = null; pinned = null; hovered = null;
    gCounties.selectAll("path").remove();
    outline.attr("d", null);
    stateSel.classed("dimmed", false).style("display", null);
    resetZoom();
    updateCrumb();
    refresh();
  }

  // ---------------- hover / tooltip
  var tip = document.getElementById("tooltip");
  function hover(ev, region) {
    hovered = region;
    var n = countFor(region, filt());
    tip.style.display = "block";
    tip.innerHTML = '<div class="t-name">' + region.name + "</div>" +
        '<div class="t-count">' + n + " matching product" + (n === 1 ? "" : "s") + "</div>";
    var wrap = document.getElementById("mapWrap").getBoundingClientRect();
    var x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 10;
    if (x > wrap.width - 240) x -= 260;
    tip.style.left = x + "px"; tip.style.top = y + "px";
    mark(); renderPanel();
  }
  function unhover() {
    hovered = null; tip.style.display = "none"; mark(); renderPanel();
  }
  function mark() {
    var h = hovered || pinned;
    var feat = null;
    gStates.selectAll(".state").classed("hovered", function (d) {
      var on = h && h.type === "state" && FIPS2ST[d.id] === h.st;
      if (on) feat = d;
      return on;
    });
    gCounties.selectAll(".county").classed("hovered", function (d) {
      var on = h && h.type === "county" && d.id === h.fips;
      if (on) feat = d;
      return on;
    });
    showHover(feat);
  }

  function countFor(region, f) {
    var n = 0;
    DATA.products.forEach(function (p) {
      if (!matches(p, f)) return;
      if (region.type === "state") { if (stateAvail(p, region.st, f)) n++; }
      else if (countyGrain(p, region.st, region.fips, f)) n++;
    });
    return n;
  }

  // ---------------- recolor + panel
  function refresh() {
    var f = filt();
    var matching = DATA.products.filter(function (p) { return matches(p, f); });
    var unmapped = matching.filter(function (p) { return p.scope === "unmapped"; });
    document.getElementById("countLine").textContent =
        matching.length + " of " + DATA.products.length + " products match filters" +
        (unmapped.length ? " (" + unmapped.length + " unmapped)" : "");

    if (!currentState) {
      var counts = {};
      statesFC.forEach(function (d) {
        var st = FIPS2ST[d.id];
        counts[st] = matching.reduce(function (n, p) { return n + (stateAvail(p, st, f) ? 1 : 0); }, 0);
      });
      var max = d3.max(Object.keys(counts), function (k) { return counts[k]; }) || 0;
      var sc = makeScale(max);
      stateSel.transition().duration(250)
          .attr("fill", function (d) { return fillFor(counts[FIPS2ST[d.id]], sc); });
      legend(sc, "state");
      document.getElementById("pendingNote").style.display = "none";
    } else {
      var st = currentState.st;
      var ccounts = {};
      gCounties.selectAll(".county").each(function (d) {
        ccounts[d.id] = matching.reduce(function (n, p) {
          return n + (countyGrain(p, st, d.id, f) ? 1 : 0);
        }, 0);
      });
      // pending = federal products contributing to this state at state grain
      var pendingProds = matching.filter(function (p) {
        return modeInState(p, st, f) === "pending";
      });
      var cmax = d3.max(Object.keys(ccounts), function (k) { return ccounts[k]; }) || 0;
      var csc = makeScale(cmax);
      gCounties.selectAll(".county").transition().duration(250)
          .attr("fill", function (d) { return fillFor(ccounts[d.id], csc); });
      legend(csc, "county in " + currentState.name);
      var note = document.getElementById("pendingNote");
      var unmappedFed = matching.filter(function (p) {
        return p.scope === "unmapped" && p.subsidized;
      });
      if (pendingProds.length) {
        note.style.display = "block";
        note.textContent = "County shading is approximate here: " + pendingProds.length +
            " federal product" + (pendingProds.length === 1 ? " is" : "s are") +
            " shown at state grain — county detail pending ADM load" +
            (DATA.county_rows === 0 ? " (no ADM county rows in the catalog yet)" : "") + ".";
      } else if (DATA.county_rows === 0 && unmappedFed.length) {
        note.style.display = "block";
        note.textContent = "No ADM county rows loaded yet: " + unmappedFed.length +
            " matching federal product" + (unmappedFed.length === 1 ? " has" : "s have") +
            " no mapped availability (county detail pending ADM) — see the unmapped list in the panel.";
      } else {
        note.style.display = "none";
      }
    }
    mark();
    renderPanel();
  }

  function badgeHtml(p, grain) {
    var b = [];
    b.push(p.subsidized
        ? '<span class="badge b-sub">subsidized federal</span>'
        : '<span class="badge b-unsub">unsubsidized private</span>');
    if (grain === "nationwide") b.push('<span class="badge b-grain">nationwide</span>');
    else if (grain === "statewide") b.push('<span class="badge b-grain">statewide</span>');
    else if (grain === "county") b.push('<span class="badge b-grain">county-level (ADM)</span>');
    else if (grain === "pending") {
      if (p.scope === "nationwide") b.push('<span class="badge b-grain">nationwide</span>');
      b.push('<span class="badge b-pending">county detail pending ADM</span>');
    }
    if (p.analog) b.push('<span class="badge b-grain">analog: ' + p.analog + "</span>");
    return '<div class="badges">' + b.join("") + "</div>";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function prodHtml(p, grain) {
    var name = p.doc_url
        ? '<a href="' + esc(p.doc_url) + '" target="_blank" rel="noopener">' + esc(p.name) + "</a>"
        : esc(p.name);
    return '<div class="prod"><div class="p-name">' + name + "</div>" +
        '<div class="p-meta">' + esc(p.aip) + " &middot; " + esc(DATA.layer_labels[p.layer] || p.layer) + "</div>" +
        (p.all_crops.length ? '<div class="p-crops">' + esc(p.all_crops.join(", ")) + "</div>" : "") +
        badgeHtml(p, grain) + "</div>";
  }

  function renderPanel() {
    var f = filt();
    var region = hovered || pinned;
    var panel = document.getElementById("panel");
    var html = "";
    var listed = [];

    if (!region && currentState) region = { type: "state", st: currentState.st, name: currentState.name };

    if (region) {
      DATA.products.forEach(function (p) {
        if (!matches(p, f)) return;
        var grain = null;
        if (region.type === "county") {
          grain = countyGrain(p, region.st, region.fips, f);
          if (!grain) return;
        } else {
          if (!matches(p, f)) return;
          grain = modeInState(p, region.st, f);
          if (!grain) return;
        }
        listed.push({ p: p, grain: grain });
      });
      html += "<h2>" + esc(region.name) + "</h2>" +
          '<div class="p-sub">' + listed.length + " matching product" + (listed.length === 1 ? "" : "s") +
          (region.type === "state" ? " available in this state" : " available in this county") + "</div>";
      html += listed.length
          ? listed.map(function (e) { return prodHtml(e.p, e.grain); }).join("")
          : '<div class="empty">No matching products here under the current filters.</div>';
    } else {
      var matching = DATA.products.filter(function (p) { return matches(p, f); });
      var painted = matching.filter(function (p) { return p.scope !== "unmapped"; });
      html += "<h2>United States</h2>" +
          '<div class="p-sub">Hover a state for its products; click to zoom to counties. ' +
          painted.length + " mappable product" + (painted.length === 1 ? "" : "s") + " under current filters.</div>";
    }

    // unmapped products (never painted)
    var unm = DATA.products.filter(function (p) { return matches(p, f) && p.scope === "unmapped"; });
    if (unm.length) {
      html += '<details class="unmapped" id="unmappedList"><summary>' + unm.length +
          " unmapped product" + (unm.length === 1 ? "" : "s") +
          " (no state/county availability data — not painted on the map)</summary>" +
          unm.map(function (p) {
            return prodHtml(p, p.county_pending ? "pending" : null);
          }).join("") + "</details>";
    }
    panel.innerHTML = html;
  }

  [fCrop, fAip, fSub].forEach(function (el) { el.addEventListener("change", refresh); });
  refresh();
  updateCrumb();
  syncZoomUI();
})();
</script>
</body>
</html>
"""


def _main() -> None:
    generate()


if __name__ == "__main__":
    _main()
