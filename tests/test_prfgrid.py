"""Pin the PRF grid lattice.

src/prfgrid.py derives every cell's corners from grid_id alone. Because that derivation was
FITTED rather than read from an RMA shapefile, the important tests here are not the algebraic
ones — they are test_cells_overlap_their_counties and test_extent_is_conus, which re-run the
original validation against the shipped database and atlas. If RMA ever renumbers the grid,
those two fail and the constants in prfgrid.py need refitting.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src import prfgrid as G

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "catalog_app.db"
ATLAS = REPO / "data" / "assets" / "counties-10m.json"


# ── Algebra ──────────────────────────────────────────────────────────────────

def test_bounds_are_quarter_degree_cells():
    for gid in (1, 6196, 26834, 34941):
        w, s, e, n = G.grid_bounds(gid)
        assert e - w == pytest.approx(G.CELL)
        assert n - s == pytest.approx(G.CELL)


def test_point_lookup_round_trips():
    for gid in range(6196, 34941, 617):
        assert G.grid_at(*G.grid_center(gid)) == gid


def test_neighbors_are_edge_adjacent():
    gid = 26834
    w, s, e, n = G.grid_bounds(gid)
    nb = G.neighbors(gid)
    assert G.grid_bounds(nb["east"])[0] == pytest.approx(e)
    assert G.grid_bounds(nb["west"])[2] == pytest.approx(w)
    assert G.grid_bounds(nb["north"])[1] == pytest.approx(n)
    assert G.grid_bounds(nb["south"])[3] == pytest.approx(s)


def test_row_advances_north_not_south():
    """The lattice counts northward — the single fact most likely to be got backwards."""
    assert G.grid_bounds(1 + G.STRIDE)[1] > G.grid_bounds(1)[1]


def test_known_cell_dakota_county_ne():
    """Grid 26834 covers Dakota County, NE (centroid -96.510, 42.421)."""
    w, s, e, n = G.grid_bounds(26834)
    assert (w, s, e, n) == pytest.approx((-96.75, 42.25, -96.50, 42.50))


def test_polygon_ring_is_closed():
    ring = G.grid_polygon(26834)
    assert len(ring) == 5 and ring[0] == ring[-1]


def test_polygon_ring_is_clockwise():
    """Load-bearing: d3-geo reads a counter-clockwise ring as the whole globe minus the
    cell, which made every grid cell flood the map. Shoelace < 0 == clockwise."""
    ring = G.grid_polygon(26834)
    area2 = sum((ring[i + 1][0] - ring[i][0]) * (ring[i + 1][1] + ring[i][1])
                for i in range(len(ring) - 1))
    assert area2 > 0, "ring must be clockwise in (lon, lat) for d3-geo"


def test_feature_is_valid_geojson():
    f = G.grid_feature(26834, metric=1.5)
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Polygon"
    assert f["properties"]["grid_id"] == 26834
    assert f["properties"]["metric"] == 1.5
    assert len(f["geometry"]["coordinates"][0]) == 5


# ── The fit, re-validated against real data ──────────────────────────────────

def _county_bboxes() -> dict[str, tuple[float, float, float, float]]:
    tj = json.loads(ATLAS.read_text())
    arcs, tr = tj["arcs"], tj["transform"]
    sx, sy = tr["scale"]
    tx, ty = tr["translate"]

    def dec(i):
        a = arcs[~i] if i < 0 else arcs[i]
        x = y = 0
        out = []
        for dx, dy in a:
            x += dx
            y += dy
            out.append((x * sx + tx, y * sy + ty))
        return out[::-1] if i < 0 else out

    box = {}
    for g in tj["objects"]["counties"]["geometries"]:
        pts = []
        rings = (g["arcs"] if g["type"] == "Polygon"
                 else [r for p in g["arcs"] for r in p])
        for ring in rings:
            for i in ring:
                pts += dec(i)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        box[g["id"]] = (min(xs), min(ys), max(xs), max(ys))
    return box


@pytest.mark.skipif(not (DB.exists() and ATLAS.exists()), reason="needs app DB + atlas")
def test_cells_overlap_their_counties():
    """THE load-bearing test: each derived cell must overlap the county RMA maps it to."""
    box = _county_bboxes()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ok = bad = 0
    for gid, fips in conn.execute("SELECT grid_id, county_fips FROM prf_grid_county"):
        if fips not in box:
            continue
        w, s, e, n = G.grid_bounds(gid)
        x0, y0, x1, y1 = box[fips]
        if e >= x0 and w <= x1 and n >= y0 and s <= y1:
            ok += 1
        else:
            bad += 1
    conn.close()
    total = ok + bad
    assert total > 30_000, f"only {total} pairs tested — is prf_grid_county populated?"
    # Measured 99.618%; the shortfall is bbox artifacts on coastal/multi-part counties.
    assert ok / total > 0.99, f"only {ok / total:.3%} of cells overlap their county"


@pytest.mark.skipif(not DB.exists(), reason="needs app DB")
def test_extent_is_conus():
    """The union of derived cells must be the CONUS box PRF actually covers."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT grid_id FROM prf_grid_county")]
    conn.close()
    b = [G.grid_bounds(g) for g in ids]
    assert min(x[0] for x in b) == pytest.approx(-124.75)
    assert max(x[2] for x in b) == pytest.approx(-67.00)
    assert min(x[1] for x in b) == pytest.approx(25.00)
    assert max(x[3] for x in b) == pytest.approx(49.25)
