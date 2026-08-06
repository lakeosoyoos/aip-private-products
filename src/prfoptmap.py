"""Self-contained PRF Optimizer county choropleth.

Visualizes the prf_opt_best sweep results (src/prfopt.py enumerates all 59,536
valid PRF interval-allocation policies per grid; src/prfsweep.py stores the
best-of-sweep summary per grid x intended use x coverage level). Metrics are
stored normalized per $1 of annual protection, so one grid row serves every
county the grid touches ($/acre = value x county CBV x coverage x productivity,
applied by the reader, not here).

This module mirrors src/prfmap.py's zero-network, self-contained D3 approach:
d3 v7, topojson-client and the us-atlas counties-10m topology are embedded
inline; a US county choropleth is shaded by the SELECTED metric (best win rate
or best average net return per $1) with a metric toggle, intended-use and
coverage dropdowns, and a dual-thumb range slider (value bubbles above the
thumbs) that filters counties by metric value — all INSIDE the embedded HTML,
re-shading client-side.

AGGREGATION RULE: a county can touch several grids. For each county x use x
coverage the county takes the BEST value among its grids INDEPENDENTLY per
metric (max best_win_rate over grids; max best_net over grids — the winning
grid may differ between the two). The tooltip keeps the per-grid detail: each
grid's best win-rate policy and best net policy (intervals + % allocations)
with both metrics.

Degrades gracefully: empty prf_opt_best -> valid all-neutral map with a
"sweep not run yet" note; partially-swept data shades what exists and renders
everything else neutral with a "not swept" legend entry.
"""
from __future__ import annotations

import ast
import datetime as _dt
import json
import sqlite3


def _fips5(value) -> str:
    """Normalize a county FIPS to the atlas's 5-digit string form."""
    s = str(value or "").strip()
    if not s:
        return s
    return s.zfill(5)


def _cov_key(cov) -> str:
    """Canonical string key for a coverage level (0.90 / '0.9' / 0.9 -> '0.9').

    JSON object keys must be strings; '%g' collapses trailing zeros so the
    Python-built key always equals JavaScript's String(parseFloat(key)).
    """
    try:
        return "%g" % float(cov)
    except (TypeError, ValueError):
        return str(cov)


def _parse_list(text) -> list:
    """Parse a combo/props column into a plain list.

    The sweep stores JSON (e.g. '["JUN-JUL","AUG-SEP"]' / '[50,50]'), but the
    optimizer's export path historically used Python reprs with single quotes,
    so fall back to ast.literal_eval. Anything unparseable -> [].
    """
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        return list(text)
    s = str(text).strip()
    if not s:
        return []
    try:
        val = json.loads(s)
    except ValueError:
        try:
            val = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


def _f(value):
    """float() or None (bad/missing values become None, never raise)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_opt_payload(conn: sqlite3.Connection) -> dict:
    """Build the JSON payload the optimizer map runs on. Pure read; testable.

    Shape:
        counties[fips][use][cov_key] = {
            "win":  max best_win_rate over the county's grids (or None),
            "net":  max best_net over the county's grids (or None),
            "grids": [per-grid detail dicts, best win rate first],
        }
    plus axes (uses / coverages), county display names, per-metric min/max over
    every aggregated county value (the color-scale domains), and row counts so
    the client can distinguish "sweep not run" from "no grid->county mapping".
    """
    # --- grid -> counties mapping -----------------------------------------
    grid_counties: dict = {}
    county_names: dict[str, str] = {}
    mapping_rows = 0
    try:
        for r in conn.execute(
            "SELECT grid_id, state, county_fips, county_name FROM prf_grid_county"
        ):
            mapping_rows += 1
            fips = _fips5(r["county_fips"])
            if not fips:
                continue
            grid_counties.setdefault(r["grid_id"], []).append(fips)
            if r["county_name"] and fips not in county_names:
                county_names[fips] = str(r["county_name"]).strip()
    except sqlite3.OperationalError:
        pass  # table not created yet — degrade to empty

    # --- best-of-sweep rows ------------------------------------------------
    try:
        rows = conn.execute("SELECT * FROM prf_opt_best").fetchall()
    except sqlite3.OperationalError:
        rows = []

    counties: dict = {}
    uses: set[str] = set()
    coverages: set[str] = set()
    unmatched: set = set()

    for r in rows:
        use = (r["intended_use"] or "").strip()
        ck = _cov_key(r["coverage_level"])
        uses.add(use)
        coverages.add(ck)
        gid = r["grid_id"]
        fipses = grid_counties.get(gid)
        if not fipses:
            unmatched.add(gid)  # swept grid with no county mapping (yet)
            continue
        detail = {
            "grid": gid,
            "win": _f(r["best_win_rate"]),
            "win_combo": _parse_list(r["best_win_combo"]),
            "win_props": _parse_list(r["best_win_props"]),
            "win_net": _f(r["best_win_avg_net"]),
            "net": _f(r["best_net"]),
            "net_combo": _parse_list(r["best_net_combo"]),
            "net_props": _parse_list(r["best_net_props"]),
            "net_win": _f(r["best_net_win_rate"]),
            "median_net": _f(r["median_net"]),
            "pct_positive": _f(r["pct_positive"]),
            "year_min": r["year_min"],
            "year_max": r["year_max"],
        }
        for fips in fipses:
            cell = (counties
                    .setdefault(fips, {})
                    .setdefault(use, {})
                    .setdefault(ck, {"win": None, "net": None, "grids": []}))
            cell["grids"].append(detail)
            # BEST-per-metric aggregation: max over grids, independently.
            if detail["win"] is not None and (cell["win"] is None
                                              or detail["win"] > cell["win"]):
                cell["win"] = detail["win"]
            if detail["net"] is not None and (cell["net"] is None
                                              or detail["net"] > cell["net"]):
                cell["net"] = detail["net"]

    # Sort each cell's grid detail best-win-rate first; collect metric domains
    # over the AGGREGATED county values (what the map actually shades).
    wins: list[float] = []
    nets: list[float] = []
    for by_use in counties.values():
        for by_cov in by_use.values():
            for cell in by_cov.values():
                cell["grids"].sort(
                    key=lambda g: (-(g["win"] if g["win"] is not None else float("-inf")),
                                   str(g["grid"])))
                if cell["win"] is not None:
                    wins.append(cell["win"])
                if cell["net"] is not None:
                    nets.append(cell["net"])

    def _covsort(k: str):
        try:
            return float(k)
        except ValueError:
            return float("inf")

    return {
        "generated": _dt.date.today().isoformat(),
        "counties": counties,
        "county_names": county_names,
        "uses": sorted(uses),
        "coverages": sorted(coverages, key=_covsort),
        "min_win": min(wins) if wins else None,
        "max_win": max(wins) if wins else None,
        "min_net": min(nets) if nets else None,
        "max_net": max(nets) if nets else None,
        "row_count": len(rows),
        "mapping_rows": mapping_rows,
        "county_count": len(counties),
        "unmatched_grids": len(unmatched),
    }


def _js_embed_json(obj) -> str:
    """JSON serialized for safe inline embedding inside a <script> block."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_opt_html(payload: dict, d3_js: str, topojson_js: str, atlas: dict) -> str:
    """Render the self-contained PRF Optimizer county choropleth HTML string."""
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


# The template uses __TOKENS__ (not str.format) so the JS braces stay literal.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRF Optimizer heat map</title>
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
  .filters select {
    font: inherit; font-size: 13px; padding: 4px 6px; max-width: 230px;
    border: 1px solid var(--baseline); border-radius: 6px; background: var(--surface);
    color: var(--ink);
  }
  .seg { display: inline-flex; border: 1px solid var(--baseline); border-radius: 6px;
    overflow: hidden; }
  .seg button {
    font: inherit; font-size: 12.5px; padding: 4px 11px; border: none;
    background: var(--surface); color: var(--ink-2); cursor: pointer;
  }
  .seg button + button { border-left: 1px solid var(--baseline); }
  .seg button.on { background: #238b45; color: #fff; }
  /* Metric range slider (dual-thumb) — filters which counties are shaded. */
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
  .county { stroke: var(--surface); stroke-width: 0.4; vector-effect: non-scaling-stroke; }
  .statelines { fill: none; stroke: var(--baseline); stroke-width: 0.7;
                pointer-events: none; vector-effect: non-scaling-stroke; }
  .county.hovered { stroke: var(--ink); stroke-width: 1.3; }
  #tooltip {
    position: absolute; pointer-events: none; display: none; z-index: 5;
    background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
    box-shadow: 0 2px 10px rgba(11,11,11,0.12); padding: 7px 10px; font-size: 12.5px;
    max-width: 340px;
  }
  #tooltip .t-name { font-weight: 650; }
  #tooltip .t-val { color: var(--ink-2); margin-top: 1px; }
  #tooltip .t-grid { margin-top: 5px; border-top: 1px solid var(--grid); padding-top: 4px; }
  #tooltip .t-gid { font-weight: 600; font-size: 12px; }
  #tooltip .t-line { color: var(--ink-2); font-size: 11.5px; margin-top: 1px; }
  #tooltip .t-more { color: var(--muted); font-size: 11px; margin-top: 4px; }
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
</style>
</head>
<body>
<header>
  <h1>PRF Optimizer — best interval allocation by county</h1>
  <div class="sub">All 59,536 valid interval allocations simulated per grid over the
  historical rainfall-index record; each county shows the <b>best</b> result among the grids
  it touches. Net return is per $1 of protection. Generated __GENERATED__.</div>
</header>
<div class="filters">
  <label>Metric</label>
  <div class="seg" id="mSeg">
    <button type="button" data-m="win" class="on">Best win rate</button>
    <button type="button" data-m="net">Best avg net return / $1</button>
  </div>
  <label>Intended use <select id="fUse"></select></label>
  <label id="covWrap" style="display:none">Coverage
    <span class="seg" id="covSeg"></span>
  </label>
  <span id="countLine" style="color:var(--muted);font-size:12px;margin-left:auto"></span>
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
    <svg id="map" viewBox="0 0 975 610" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="legend"></div>
    <div id="tooltip"></div>
  </div>
</div>
<footer>Metrics are normalized per $1 of protection (multiply by County Base Value &times;
coverage level &times; productivity factor for $/acre). A county spanning several grids shows
the best grid per metric; hover for the per-grid winning policies. Counties with no swept
grid for the current selection are shown neutral.</footer>

<script>__D3__</script>
<script>__TOPOJSON__</script>
<script>
var US_ATLAS = __ATLAS__;
var DATA = __PAYLOAD__;

(function () {
  "use strict";

  var NONE = getComputedStyle(document.documentElement).getPropertyValue("--none").trim() || "#ececea";
  // Same sequential green ramp as the PRF CBV map (light->dark = low->high).
  var RAMP = ["#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"];
  var UNITS = 1000;  // slider resolution (0..UNITS mapped onto [lo, hi])

  // ---------------- geometry (same AlbersUSA params us-atlas pre-projects to)
  var path = d3.geoPath(d3.geoAlbersUsa().scale(1300).translate([487.5, 305]));
  var countiesFC = topojson.feature(US_ATLAS, US_ATLAS.objects.counties).features;
  var stateMesh = topojson.mesh(US_ATLAS, US_ATLAS.objects.states, function (a, b) { return true; });

  var svg = d3.select("#map");
  var g = svg.append("g");
  var gCounties = g.append("g");
  var countySel = gCounties.selectAll("path").data(countiesFC).join("path")
      .attr("class", "county").attr("d", path)
      .on("mousemove", function (ev, d) { hover(ev, d); })
      .on("mouseout", unhover);
  g.append("path").attr("class", "statelines").attr("d", path(stateMesh));

  // ---------------- metric + filters
  var metric = "win";
  var METRIC_LABEL = { win: "Best win rate", net: "Best avg net return / $1" };
  var fUse = document.getElementById("fUse");

  function fill(sel, items, preferred) {
    sel.innerHTML = "";
    items.forEach(function (v) {
      var o = document.createElement("option"); o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
    if (!items.length) { sel.disabled = true; return; }
    var want = null;
    (preferred || []).forEach(function (p) {
      if (want === null && items.indexOf(p) >= 0) want = p;
    });
    sel.value = want !== null ? want : items[0];
  }
  fill(fUse, DATA.uses, ["Grazing"]);

  // Coverage: 5 discrete PRF choices (70..90%) -> segmented radio-style buttons
  // built from whatever coverage levels the sweep actually stored. Hidden while
  // only one coverage exists (the year-selector pattern in the CBV map); the
  // plumbing supports many, so future sweeps light it up with no code change.
  var coverage = DATA.coverages.length
      ? (DATA.coverages.indexOf("0.9") >= 0
          ? "0.9" : DATA.coverages[DATA.coverages.length - 1])
      : null;
  function covLabel(c) { return Math.round(parseFloat(c) * 100) + "%"; }
  var covButtons = [];
  (function () {
    var seg = document.getElementById("covSeg");
    DATA.coverages.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button"; b.dataset.c = c; b.textContent = covLabel(c);
      b.classList.toggle("on", c === coverage);
      b.addEventListener("click", function () {
        if (coverage === c) return;
        coverage = c;
        covButtons.forEach(function (x) { x.classList.toggle("on", x === b); });
        refresh();
      });
      seg.appendChild(b);
      covButtons.push(b);
    });
    if (DATA.coverages.length > 1) document.getElementById("covWrap").style.display = "";
  })();

  function cellFor(fips) {
    var c = DATA.counties[fips];
    if (!c) return null;
    var a = c[fUse.value]; if (!a) return null;
    return a[coverage] || null;
  }
  function valFor(fips) {
    var cell = cellFor(fips);
    if (!cell) return null;
    var v = cell[metric];
    return (v === undefined || v === null) ? null : v;
  }

  // ---------------- formatting (win rate = %, net = $ per $1 of protection)
  function fmtWin(v) { return v === null || v === undefined ? "&mdash;" : (v * 100).toFixed(1) + "%"; }
  function fmtNet(v) { return v === null || v === undefined ? "&mdash;" : "$" + v.toFixed(3); }
  function fmtShort(v) {
    if (metric === "win") return Math.round(v * 100) + "%";
    var digits = Math.abs(hi - lo) < 1 ? 3 : 2;
    return "$" + v.toFixed(digits);
  }

  // ---------------- metric-dependent color scale + range slider
  var lo = 0, hi = 1, hasData = false, scale = null;
  var rMin = document.getElementById("rMin"),
      rMax = document.getElementById("rMax"),
      rFill = document.getElementById("rFill"),
      rReadout = document.getElementById("rReadout"),
      rBar = document.getElementById("rangebar"),
      bubbleLo = document.getElementById("rBubbleLo"),
      bubbleHi = document.getElementById("rBubbleHi");
  [rMin, rMax].forEach(function (r) { r.min = 0; r.max = UNITS; r.step = 1; });

  function applyMetric() {
    var mm = metric === "win" ? [DATA.min_win, DATA.max_win] : [DATA.min_net, DATA.max_net];
    hasData = mm[0] !== null && mm[0] !== undefined && mm[1] !== null && mm[1] !== undefined;
    lo = hasData ? mm[0] : 0;
    hi = hasData ? mm[1] : 1;
    if (hi <= lo) hi = lo + (metric === "win" ? 0.05 : 0.01);
    scale = d3.scaleQuantize().domain([lo, hi]).range(RAMP);
    rMin.value = 0; rMax.value = UNITS;
    rBar.style.display = hasData ? "" : "none";
    document.getElementById("rangeLabel").textContent = METRIC_LABEL[metric] + " range";
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
    // Value label above each thumb, offset for the 16px thumb width so it tracks the handle.
    bubbleLo.textContent = fmtShort(rangeLo());
    bubbleLo.style.left = "calc(" + (a * 100) + "% - " + (a * 16 - 8) + "px)";
    bubbleHi.textContent = fmtShort(rangeHi());
    bubbleHi.style.left = "calc(" + (b * 100) + "% - " + (b * 16 - 8) + "px)";
    rReadout.textContent = fmtShort(rangeLo()) + " – " + fmtShort(rangeHi());
  }

  function drawLegend() {
    var el = document.getElementById("legend");
    if (!hasData) { el.style.display = "none"; return; }
    el.style.display = "";
    var cells = RAMP.map(function (c) {
      return '<div class="l-cell" style="background:' + c + '"></div>';
    }).join("");
    // scaleQuantize thresholds() gives the internal breakpoints (n-1 of them).
    var thr = scale.thresholds();
    var labels = '<span>' + fmtShort(lo) + '</span>' +
      thr.map(function (t) { return '<span>' + fmtShort(t) + '</span>'; }).join("");
    el.innerHTML =
      '<div class="l-title">' + METRIC_LABEL[metric] + '</div>' +
      '<div class="l-row">' + cells + '</div>' +
      '<div class="l-labels">' + labels + '</div>' +
      '<div class="l-none"><span class="sw"></span>not swept for this selection</div>';
  }

  // ---------------- hover / tooltip (county + per-grid winning policies)
  var tip = document.getElementById("tooltip");
  function nameFor(d) {
    return DATA.county_names[d.id] || (d.properties && d.properties.name) || "County";
  }
  function comboStr(combo, props) {
    if (!combo || !combo.length) return "?";
    return combo.map(function (iv, i) {
      var p = props && props[i] !== undefined ? props[i] + "%" : "?";
      return iv + " " + p;
    }).join(" · ");
  }
  function tipHtml(d) {
    var selLbl = esc(fUse.value) + (coverage !== null ? " @ " + covLabel(coverage) + " coverage" : "");
    var name = esc(nameFor(d)) + " County";
    var cell = cellFor(d.id);
    if (!cell) {
      return '<div class="t-name">' + name + '</div>' +
             '<div class="t-val">not swept for ' + (selLbl || "this selection") + '</div>';
    }
    var n = cell.grids.length;
    var h = '<div class="t-name">' + name + ' &mdash; ' + selLbl + '</div>' +
      '<div class="t-val">best win rate ' + fmtWin(cell.win) +
      ' &middot; best net ' + fmtNet(cell.net) + ' per $1 &middot; ' +
      n + ' grid' + (n === 1 ? '' : 's') + '</div>';
    cell.grids.slice(0, 5).forEach(function (gr) {
      h += '<div class="t-grid"><div class="t-gid">Grid ' + esc(gr.grid) + '</div>';
      if (gr.win !== null && gr.win !== undefined) {
        h += '<div class="t-line">win-rate best: ' + fmtWin(gr.win) + ' &middot; net ' +
             fmtNet(gr.win_net) + ' &mdash; ' + esc(comboStr(gr.win_combo, gr.win_props)) + '</div>';
      }
      if (gr.net !== null && gr.net !== undefined) {
        h += '<div class="t-line">net best: ' + fmtNet(gr.net) + ' &middot; win ' +
             fmtWin(gr.net_win) + ' &mdash; ' + esc(comboStr(gr.net_combo, gr.net_props)) + '</div>';
      }
      h += '</div>';
    });
    if (n > 5) h += '<div class="t-more">+' + (n - 5) + ' more grids</div>';
    return h;
  }
  function hover(ev, d) {
    d3.select(this).classed("hovered", true);
    tip.style.display = "block";
    tip.innerHTML = tipHtml(d);
    var wrap = document.getElementById("mapWrap").getBoundingClientRect();
    var x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 10;
    if (x > wrap.width - 340) x -= 360;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function unhover() {
    d3.select(this).classed("hovered", false);
    tip.style.display = "none";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ---------------- render / recolor
  function refresh() {
    var rlo = rangeLo(), rhi = rangeHi();
    var eps = (hi - lo) * 1e-9;
    var shaded = 0;
    countySel.attr("fill", function (d) {
      var v = valFor(d.id);
      if (v === null || v < rlo - eps || v > rhi + eps) return NONE;  // outside range -> neutral
      shaded++;
      return scale(v);
    });
    var line = document.getElementById("countLine");
    if (!hasData || coverage === null) {
      line.textContent = "";
    } else {
      var forSel = fUse.value + " @ " + covLabel(coverage) + " coverage";
      line.textContent = isFullRange()
        ? shaded + " counties swept for " + forSel
        : shaded + " counties with " + METRIC_LABEL[metric].toLowerCase() + " " +
          fmtShort(rlo) + "–" + fmtShort(rhi) + " for " + forSel;
    }
    var note = document.getElementById("note");
    if (DATA.row_count === 0) {
      note.style.display = "block";
      note.textContent = "Optimizer sweep not run yet — the prf_opt_best table is empty. " +
        "Run the sweep to populate per-grid best allocations; the map will shade as results land.";
    } else if (DATA.mapping_rows === 0) {
      note.style.display = "block";
      note.textContent = "Sweep results exist for " + DATA.row_count + " grid rows, but the " +
        "grid-to-county mapping (prf_grid_county) is empty, so counties can't be shaded yet.";
    } else if (shaded === 0) {
      note.style.display = "block";
      note.textContent = "No swept grids match this use / coverage" +
        (isFullRange() ? "" : " / range") + " selection.";
    } else {
      note.style.display = "none";
    }
    drawLegend();
  }

  // ---------------- wiring
  var segButtons = Array.prototype.slice.call(
      document.getElementById("mSeg").querySelectorAll("button"));
  segButtons.forEach(function (b) {
    b.addEventListener("click", function () {
      if (metric === b.dataset.m) return;
      metric = b.dataset.m;
      segButtons.forEach(function (x) { x.classList.toggle("on", x === b); });
      applyMetric();  // domain, slider reset, legend + reshade
    });
  });
  fUse.addEventListener("change", refresh);
  [rMin, rMax].forEach(function (r) {
    r.addEventListener("input", function () { updateRange(); refresh(); });
  });
  document.getElementById("rReset").addEventListener("click", function () {
    rMin.value = 0; rMax.value = UNITS; updateRange(); refresh();
  });
  applyMetric();
})();
</script>
</body>
</html>
"""
