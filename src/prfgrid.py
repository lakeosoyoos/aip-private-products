"""Geometry for RMA's PRF rainfall-index grids, derived arithmetically from grid_id.

RMA publishes no grid shapefile in any feed this project pulls, and prf_grid_county carries
only grid_id -> county_fips. But the PRF grid is a regular 0.25-degree lattice and grid_id
encodes position in it, so every cell's corners are computable with no new data at all.

THE LATTICE (derived empirically, then checked against all 30,345 grid/county pairs):

    row, col  = divmod(grid_id - 1, 300)
    lon_west  = -130.0 + col * 0.25
    lat_south =   20.0 + row * 0.25

i.e. 300 cells per row, numbered WEST->EAST within a row and SOUTH->NORTH between rows,
from an origin at 130W 20N.

How each constant was established, so this can be re-checked rather than trusted:

* STRIDE = 300. Sorting each county's grid_ids, the gap between consecutive ids is either 1
  (the neighbour to the east) or ~300 (the cell in the next row up). Fitting the origin over
  candidate strides, the implied longitude origin's interquartile spread collapses to 0.44
  degrees at 300 and is 30-45 degrees at 240/280/290/310/320/360 — an unambiguous minimum.
* SOUTH->NORTH. With lat = LAT0 - row*0.25 the implied origin's IQR spread is 16.35 degrees;
  with lat = LAT0 + row*0.25 it is 0.355. The lattice counts northward.
* ORIGIN. The fitted medians are -129.871 and 20.124, each within 0.005 of an exact quarter
  degree once the half-cell centroid offset (0.125) is removed: -130.00 and 20.00 exactly.

VALIDATION: for all 30,345 pairs, the derived cell overlaps that county's bounding box in
99.618% of cases, and the union of derived cells spans lon -124.75..-67.00, lat 25.00..49.25
-- the CONUS bounding box, which is what PRF covers. The 116 non-overlapping pairs (0.382%)
are bounding-box artifacts on coastal and multi-part counties, not a different lattice.

Alaska and Hawaii are NOT covered: they sit outside the fitted extent and RMA administers
them on a separate grid. grid_bounds() will still return a cell for such an id -- callers
that must not render off-lattice ids should check in_conus().
"""
from __future__ import annotations

from typing import Iterator

#: Cells per lattice row.
STRIDE = 300
#: Cell edge length in degrees.
CELL = 0.25
#: Longitude of the lattice's western edge.
LON0 = -130.0
#: Latitude of the lattice's southern edge.
LAT0 = 20.0

#: The fitted extent of grids actually present in prf_grid_county (CONUS).
CONUS_LON = (-124.75, -67.00)
CONUS_LAT = (25.00, 49.25)


def grid_rowcol(grid_id: int) -> tuple[int, int]:
    """(row, col) of a grid in the lattice. Row counts north, col counts east."""
    return divmod(int(grid_id) - 1, STRIDE)


def grid_bounds(grid_id: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) degrees for a grid cell.

    Pure arithmetic — no lookup table, no network, valid for any positive id.
    """
    row, col = grid_rowcol(grid_id)
    west = LON0 + col * CELL
    south = LAT0 + row * CELL
    return (west, south, west + CELL, south + CELL)


def grid_center(grid_id: int) -> tuple[float, float]:
    """(lon, lat) of a grid cell's centre."""
    w, s, e, n = grid_bounds(grid_id)
    return ((w + e) / 2.0, (s + n) / 2.0)


def grid_at(lon: float, lat: float) -> int:
    """The grid_id containing a point. Inverse of grid_bounds()."""
    col = int((lon - LON0) // CELL)
    row = int((lat - LAT0) // CELL)
    return row * STRIDE + col + 1


def in_conus(grid_id: int) -> bool:
    """True if the cell lies inside the extent PRF actually covers."""
    w, s, e, n = grid_bounds(grid_id)
    return (CONUS_LON[0] <= w and e <= CONUS_LON[1]
            and CONUS_LAT[0] <= s and n <= CONUS_LAT[1])


def grid_polygon(grid_id: int) -> list[list[float]]:
    """The cell as a closed linear ring, wound CLOCKWISE in (lon, lat).

    The winding is load-bearing, not cosmetic. d3-geo treats polygons as SPHERICAL and takes
    the interior to be the region to the left of the ring's direction of travel, which is the
    opposite of RFC 7946's counter-clockwise-exterior convention. Hand d3 a counter-clockwise
    ring and it renders the complement — the entire globe minus the cell — which on this map
    appeared as every grid cell painting the whole viewport. Verified in-browser: clockwise
    yields a 4-point quad, counter-clockwise yields the full clip rectangle plus a hole.
    """
    w, s, e, n = grid_bounds(grid_id)
    return [[w, s], [w, n], [e, n], [e, s], [w, s]]


def grid_feature(grid_id: int, **properties) -> dict:
    """The cell as a GeoJSON Feature, for handing straight to D3."""
    return {
        "type": "Feature",
        "id": int(grid_id),
        "geometry": {"type": "Polygon", "coordinates": [grid_polygon(grid_id)]},
        "properties": {"grid_id": int(grid_id), **properties},
    }


def grid_featurecollection(grid_ids: Iterator[int], **shared) -> dict:
    """A FeatureCollection of cells — what the map's grid layer consumes."""
    return {"type": "FeatureCollection",
            "features": [grid_feature(g, **shared) for g in grid_ids]}


def neighbors(grid_id: int) -> dict[str, int]:
    """The four edge-adjacent cells, by compass direction."""
    return {"west": grid_id - 1, "east": grid_id + 1,
            "south": grid_id - STRIDE, "north": grid_id + STRIDE}
