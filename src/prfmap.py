"""Self-contained PRF County Base Value (CBV) choropleth.

PRF = Pasture, Rangeland, Forage (rainfall index, plan code 13). The County
Base Value is the RMA per-acre dollar figure that scales a PRF policy's
protection:  protection = acres x productivity-factor x coverage-level x CBV.
CBV is county-grain and varies by intended use (Grazing vs Haying), irrigation
practice (Irrigated vs Non-Irrigated) and organic practice.

This module mirrors src/webmap.py's zero-network, self-contained D3 approach:
the same cached assets (d3 v7, topojson-client, the us-atlas counties-10m
topology) are embedded inline, and a US county choropleth is shaded by CBV with
5-digit FIPS matched against the atlas. Filters (use / practice / organic / year)
live INSIDE the embedded HTML and re-shade client-side. Counties with no CBV for
the current selection render neutral with a "no value" legend entry.

Data comes from the prf_county table (populated by the prf_adm connector); this
module is a pure read + render and degrades gracefully when the table is empty.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3


def _fips5(value) -> str:
    """Normalize a county FIPS to the atlas's 5-digit string form."""
    s = str(value or "").strip()
    if not s:
        return s
    return s.zfill(5)


def build_prf_payload(conn: sqlite3.Connection) -> dict:
    """Build the JSON payload the PRF map runs on. Pure read; testable.

    Shape (extends the requested county_fips -> use -> practice -> organic -> cbv
    tree with a year leaf so a single build can carry multiple crop years):

        counties[fips][use][practice][organic][year] = cbv  ($/acre float)

    Plus the axes the in-map dropdowns are built from (uses / practices /
    organics / years), county display names, and the min/max CBV over every
    stored value (the color scale's domain). When prf_county is empty (or the
    table is missing) every collection comes back empty and min/max are None —
    the caller shows a "not loaded" note and render_prf_html still produces a
    valid, all-neutral map.
    """
    counties: dict[str, dict] = {}
    county_names: dict[str, str] = {}
    uses: set[str] = set()
    practices: set[str] = set()
    organics: set[str] = set()
    years: set[int] = set()
    values: list[float] = []

    try:
        cur = conn.execute(
            "SELECT year, state, county_fips, county_name, intended_use, "
            "irrigation_practice, organic_practice, county_base_value "
            "FROM prf_county"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        rows = []  # table not created yet — degrade to empty

    for r in rows:
        fips = _fips5(r["county_fips"])
        if not fips:
            continue
        use = (r["intended_use"] or "").strip()
        practice = (r["irrigation_practice"] or "").strip()
        organic = (r["organic_practice"] or "Conventional").strip() or "Conventional"
        try:
            year = int(r["year"])
        except (TypeError, ValueError):
            continue
        cbv = r["county_base_value"]

        # Axes reflect every row present in the data so the dropdowns show the
        # real domain even where some cells lack a CBV.
        uses.add(use)
        practices.add(practice)
        organics.add(organic)
        years.add(year)
        if r["county_name"] and fips not in county_names:
            county_names[fips] = str(r["county_name"]).strip()

        if cbv is None:
            continue  # keep the axis, but no shaded value for this cell
        try:
            cbv = float(cbv)
        except (TypeError, ValueError):
            continue
        values.append(cbv)
        (counties
            .setdefault(fips, {})
            .setdefault(use, {})
            .setdefault(practice, {})
            .setdefault(organic, {})[year]) = cbv

    return {
        "generated": _dt.date.today().isoformat(),
        "counties": counties,
        "county_names": county_names,
        "uses": sorted(uses),
        "practices": sorted(practices),
        "organics": sorted(organics),
        "years": sorted(years),
        "min_cbv": min(values) if values else None,
        "max_cbv": max(values) if values else None,
        "row_count": len(rows),
        "value_count": len(values),
    }


def _js_embed_json(obj) -> str:
    """JSON serialized for safe inline embedding inside a <script> block."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_prf_html(payload: dict, d3_js: str, topojson_js: str, atlas: dict) -> str:
    """Render the self-contained PRF county choropleth HTML string."""
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
<title>PRF County Base Value heat map</title>
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
  /* CBV range slider (dual-thumb) — filters which counties are shaded by $/acre. */
  .rangebar {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    padding: 9px 18px; border-bottom: 1px solid var(--grid); background: var(--surface);
  }
  .rangebar > label { color: var(--ink-2); font-size: 12px; white-space: nowrap; }
  .dual { position: relative; flex: 1; min-width: 220px; max-width: 520px; height: 26px; }
  .dual .track { position: absolute; top: 11px; left: 0; right: 0; height: 4px;
    background: var(--grid); border-radius: 3px; }
  .dual .fill { position: absolute; top: 11px; height: 4px; background: #41ab5d; border-radius: 3px; }
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
    max-width: 260px;
  }
  #tooltip .t-name { font-weight: 650; }
  #tooltip .t-val { color: var(--ink-2); margin-top: 1px; }
  #legend {
    position: absolute; left: 16px; bottom: 14px; background: var(--surface);
    border: 1px solid var(--ring); border-radius: 8px; padding: 8px 10px; font-size: 11.5px;
  }
  #legend .l-title { color: var(--ink-2); margin-bottom: 5px; }
  #legend .l-row { display: flex; align-items: center; gap: 0; }
  #legend .l-cell { width: 30px; height: 10px; }
  #legend .l-labels { display: flex; font-size: 10px; color: var(--muted); margin-top: 1px; }
  #legend .l-labels span { width: 30px; text-align: left; }
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
  <h1>PRF County Base Value ($/acre)</h1>
  <div class="sub">County Base Value scales PRF protection
  (acres &times; productivity factor &times; coverage level &times; CBV). Darker = higher $/acre.
  Generated __GENERATED__.</div>
</header>
<div class="filters">
  <label>Intended use <select id="fUse"></select></label>
  <label>Irrigation <select id="fPractice"></select></label>
  <label>Organic <select id="fOrganic"></select></label>
  <label id="yearWrap" style="display:none">Year <select id="fYear"></select></label>
  <span id="countLine" style="color:var(--muted);font-size:12px;margin-left:auto"></span>
</div>
<div class="rangebar" id="rangebar">
  <label>County Base Value range</label>
  <div class="dual">
    <div class="track"></div>
    <div class="fill" id="rFill"></div>
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
<footer>County Base Value is county-grain RMA data (rainfall index / rates are grid-grain).
Counties with no CBV for the current use / practice / organic / year selection are shown neutral.</footer>

<script>__D3__</script>
<script>__TOPOJSON__</script>
<script>
var US_ATLAS = __ATLAS__;
var DATA = __PAYLOAD__;

(function () {
  "use strict";

  var NONE = getComputedStyle(document.documentElement).getPropertyValue("--none").trim() || "#ececea";
  // Sequential single-hue "money" green ramp (light->dark = low->high $/acre).
  var RAMP = ["#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"];

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

  // ---------------- filters
  var fUse = document.getElementById("fUse"),
      fPractice = document.getElementById("fPractice"),
      fOrganic = document.getElementById("fOrganic"),
      fYear = document.getElementById("fYear");

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
  fill(fPractice, DATA.practices, ["Non-Irrigated", "Non Irrigated"]);
  fill(fOrganic, DATA.organics, ["Conventional"]);
  // Years: default to the most recent; only expose the selector when >1 year.
  var yearsDesc = (DATA.years || []).slice().sort(function (a, b) { return b - a; });
  fill(fYear, yearsDesc.map(String), []);
  if (yearsDesc.length > 1) document.getElementById("yearWrap").style.display = "";

  function sel() {
    return {
      use: fUse.value, practice: fPractice.value,
      organic: fOrganic.value, year: fYear.value,
    };
  }

  // Look up the CBV for a county under the current selection (or null).
  function cbvFor(fips, s) {
    var c = DATA.counties[fips];
    if (!c) return null;
    var a = c[s.use]; if (!a) return null;
    var b = a[s.practice]; if (!b) return null;
    var o = b[s.organic]; if (!o) return null;
    var v = o[s.year];
    return (v === undefined || v === null) ? null : v;
  }

  // ---------------- color scale (quantize over the global CBV domain)
  var hasData = DATA.min_cbv !== null && DATA.max_cbv !== null;
  var lo = hasData ? DATA.min_cbv : 0;
  var hi = hasData ? DATA.max_cbv : 1;
  if (hi <= lo) hi = lo + 1;
  var scale = d3.scaleQuantize().domain([lo, hi]).range(RAMP);

  // ---------------- CBV range slider (dual thumb; hides counties outside the $ range,
  // color mapping stays absolute so a given CBV is always the same green).
  var rMin = document.getElementById("rMin"),
      rMax = document.getElementById("rMax"),
      rFill = document.getElementById("rFill"),
      rReadout = document.getElementById("rReadout"),
      rBar = document.getElementById("rangebar");
  var RLO = Math.floor(lo), RHI = Math.ceil(hi);
  if (RHI <= RLO) RHI = RLO + 1;
  [rMin, rMax].forEach(function (r) { r.min = RLO; r.max = RHI; r.step = 1; });
  rMin.value = RLO; rMax.value = RHI;
  if (!hasData) rBar.style.display = "none";
  function rangeLo() { return Math.min(+rMin.value, +rMax.value); }
  function rangeHi() { return Math.max(+rMin.value, +rMax.value); }
  function isFullRange() { return rangeLo() <= RLO && rangeHi() >= RHI; }
  function updateRange() {
    var span = (RHI - RLO) || 1;
    var a = (rangeLo() - RLO) / span, b = (rangeHi() - RLO) / span;
    rFill.style.left = (a * 100) + "%";
    rFill.style.width = ((b - a) * 100) + "%";
    rReadout.textContent = usdShort(rangeLo()) + " – " + usdShort(rangeHi()) + "/ac";
  }

  function usd(v) {
    if (v === null || v === undefined) return "no value";
    return "$" + (Math.round(v * 100) / 100).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "/ac";
  }
  function usdShort(v) {
    return "$" + Math.round(v).toLocaleString();
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
    var labels = '<span>' + usdShort(lo) + '</span>' +
      thr.map(function (t) { return '<span>' + usdShort(t) + '</span>'; }).join("");
    el.innerHTML =
      '<div class="l-title">County Base Value ($/acre)</div>' +
      '<div class="l-row">' + cells + '</div>' +
      '<div class="l-labels">' + labels + '</div>' +
      '<div class="l-none"><span class="sw"></span>no value for this selection</div>';
  }

  // ---------------- hover / tooltip
  var tip = document.getElementById("tooltip");
  function nameFor(d) {
    return DATA.county_names[d.id] || (d.properties && d.properties.name) || "County";
  }
  function hover(ev, d) {
    d3.select(this).classed("hovered", true);
    var v = cbvFor(d.id, sel());
    tip.style.display = "block";
    tip.innerHTML = '<div class="t-name">' + esc(nameFor(d)) + " County</div>" +
        '<div class="t-val">' + usd(v) + "</div>";
    var wrap = document.getElementById("mapWrap").getBoundingClientRect();
    var x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 10;
    if (x > wrap.width - 240) x -= 260;
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
    var s = sel();
    var rlo = rangeLo(), rhi = rangeHi();
    var shaded = 0;
    countySel.attr("fill", function (d) {
      var v = cbvFor(d.id, s);
      if (v === null || v < rlo || v > rhi) return NONE;   // outside selected $ range -> neutral
      shaded++;
      return scale(v);
    });
    var line = document.getElementById("countLine");
    if (!hasData) {
      line.textContent = "";
    } else {
      var forSel = s.use + " / " + s.practice + " / " + s.organic +
        (yearsDesc.length > 1 ? " / " + s.year : "");
      line.textContent = isFullRange()
        ? shaded + " counties with a CBV for " + forSel
        : shaded + " counties with CBV " + usdShort(rlo) + "–" + usdShort(rhi) +
          " for " + forSel;
    }
    var note = document.getElementById("note");
    if (!hasData) {
      note.style.display = "block";
      note.textContent = "PRF data not loaded yet — run the prf_adm connector to populate County Base Values.";
    } else if (shaded === 0) {
      note.style.display = "block";
      note.textContent = "No County Base Values for this use / practice / organic" +
        (yearsDesc.length > 1 ? " / year" : "") + " combination.";
    } else {
      note.style.display = "none";
    }
    drawLegend();
  }

  [fUse, fPractice, fOrganic, fYear].forEach(function (el) {
    el.addEventListener("change", refresh);
  });
  [rMin, rMax].forEach(function (r) {
    r.addEventListener("input", function () { updateRange(); refresh(); });
  });
  document.getElementById("rReset").addEventListener("click", function () {
    rMin.value = RLO; rMax.value = RHI; updateRange(); refresh();
  });
  updateRange();
  refresh();
})();
</script>
</body>
</html>
"""
