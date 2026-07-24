"""Canonical row-crop list + matching.

Federal connectors match by RMA commodity code; private connectors (free text from filings and
brochures) match by keyword. `is_row_crop()` and `match_crops()` are the two entry points.
"""
from __future__ import annotations

import re

# RMA commodity code -> canonical crop name. Row (field) crops only.
ROW_CROP_CODES: dict[str, str] = {
    "0011": "Wheat",
    "0015": "Canola",
    "0016": "Oats",
    "0018": "Rice",
    "0021": "Cotton",
    "0041": "Corn",
    "0047": "Dry Beans",
    "0051": "Grain Sorghum",
    "0067": "Dry Peas",
    "0078": "Sunflowers",
    "0081": "Soybeans",
    "0091": "Barley",
    # Codes below verified against the ADM Commodity table (A00420) + AIB dropdown, RY 2026 —
    # earlier values here were wrong (0094 was mislabeled Flax, 0107 Rye, 0332 Peanuts, 0075
    # Millet). 0107 Alfalfa Seed / 0332 Annual Forage are NOT row crops and are excluded.
    "0094": "Rye",
    "0075": "Peanuts",
    "0017": "Millet",
    "0031": "Flax",
}

# Canonical name -> keyword variants seen in free text (lowercased, matched as whole words).
_KEYWORDS: dict[str, list[str]] = {
    "Corn": ["corn", "field corn", "grain corn"],
    "Soybeans": ["soybean", "soybeans", "beans (soy)"],
    "Wheat": ["wheat", "winter wheat", "spring wheat", "durum"],
    "Grain Sorghum": ["sorghum", "grain sorghum", "milo"],
    "Cotton": ["cotton", "upland cotton"],
    "Rice": ["rice"],
    "Barley": ["barley"],
    "Oats": ["oats", "oat"],
    "Sunflowers": ["sunflower", "sunflowers"],
    "Canola": ["canola", "rapeseed"],
    "Dry Beans": ["dry beans", "dry bean", "edible beans"],
    "Dry Peas": ["dry peas", "dry pea"],
    "Flax": ["flax", "flaxseed"],
    "Rye": ["rye"],
    "Peanuts": ["peanut", "peanuts"],
    "Millet": ["millet"],
    "Sugar Beets": ["sugar beet", "sugarbeets", "sugar beets"],
}

# A blanket phrase like "all row crops" / "field crops" should flag the record as row-crop relevant
# without pinning a specific commodity.
_GENERIC_ROWCROP = re.compile(r"\b(row crop|row crops|field crop|field crops|all crops)\b", re.I)


def _keyword_map(extra: list[str] | None) -> dict[str, list[str]]:
    m = {k: list(v) for k, v in _KEYWORDS.items()}
    for name in extra or []:
        m.setdefault(name.strip().title(), []).append(name.strip().lower())
    return m


def is_row_crop_code(commodity_code: str) -> bool:
    return str(commodity_code).zfill(4) in ROW_CROP_CODES


def crop_for_code(commodity_code: str) -> str | None:
    return ROW_CROP_CODES.get(str(commodity_code).zfill(4))


def match_crops(text: str, extra: list[str] | None = None) -> list[str]:
    """Return canonical row-crop names mentioned in free text (deduped, sorted)."""
    if not text:
        return []
    lowered = text.lower()
    found: set[str] = set()
    for canonical, variants in _keyword_map(extra).items():
        for kw in variants:
            if re.search(rf"\b{re.escape(kw)}\b", lowered):
                found.add(canonical)
                break
    return sorted(found)


def mentions_row_crops(text: str, extra: list[str] | None = None) -> bool:
    """True if text names a specific row crop OR uses a generic row-crop phrase."""
    if not text:
        return False
    return bool(match_crops(text, extra)) or bool(_GENERIC_ROWCROP.search(text))
