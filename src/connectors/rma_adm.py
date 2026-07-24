"""Actuarial Data Master county-availability connector (opt-in, heavy).

Populates `product_counties` — the county-grain availability of the FEDERAL products in
`products` — from RMA's ADM, the authoritative plan x commodity x state x county source.

The full year zip (YYYY_ADM_YTD.zip) is ~2.7 GB, but the one table we need
(A00030 InsuranceOffer, ~54 MB compressed) can be pulled out alone because RMA's pubfs
server supports HTTP Range requests: we read the zip's central directory remotely, locate
the member, and download + inflate just its bytes. Extracted members are cached under
data/cache/adm/. If the server ever stops honoring Range requests we fall back to a full
zip download through the normal url_cache path.

Because even the member download is tens of MB, the populate step stays behind the
explicit opt-in: `refresh --source rma_adm --force`. Without --force the connector only
resolves the source file and reports what it would do.

Grain and mapping:
  InsuranceOffer rows are (plan, commodity, state, county, type, practice, ...); we reduce
  to DISTINCT (plan-group, commodity, state, county). Plan codes map to products via
  products.plan_code (semicolon lists), plus a supplement for products whose seed predates
  their ADM plan codes (PACE 26/27/28, MCO 67/68/69 — both confirmed in the 2026 ADM
  InsurancePlan table). Commodity codes map to canonical row crops via
  ADM_ROW_CROP_CODES (verified against the ADM Commodity table; src/rowcrops.py has
  four wrong codes — see the note on the map);
  non-row-crop commodities are dropped. WFRP (plan 76) is whole-farm: its commodity 0076
  maps to the catalog's 'All crops (whole-farm)' pseudo-crop (Micro Farm, commodity 9110,
  is ignored). Products whose product_crops uses 'Spring Wheat' (MP, MCO) get commodity
  0011 relabeled from 'Wheat' to 'Spring Wheat' so the crop names join product_crops.

Endorsement-type products with no plan code of their own (TA-APH, Downed Rice, Cottonseed,
Malting Barley Revenue, Pulse Crop Revenue, Peanut Revenue, Popcorn Revenue, Specialty
Soybeans) follow their underlying policy's availability and are skipped with a note.
"""
from __future__ import annotations

import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .. import config
from .base import Connector, ConnectorResult, Context

ADM_CACHE_DIR = config.CACHE_DIR / "adm"

# ADM commodity code -> canonical row-crop name, VERIFIED against the 2026 ADM Commodity
# table (A00420). NOTE: src/rowcrops.py ROW_CROP_CODES has four wrong codes (it says
# 0075=Millet, 0094=Flax, 0107=Rye, 0332=Peanuts; ADM says 0075=Peanuts, 0094=Rye,
# 0107=Alfalfa Seed, 0332=Annual Forage; real Millet=0017, real Flax=0031), so this
# connector carries its own verified map rather than importing the buggy one.
ADM_ROW_CROP_CODES: dict[str, str] = {
    "0011": "Wheat",
    "0015": "Canola",
    "0016": "Oats",
    "0017": "Millet",
    "0018": "Rice",
    "0021": "Cotton",
    "0031": "Flax",
    "0041": "Corn",
    "0047": "Dry Beans",
    "0051": "Grain Sorghum",
    "0067": "Dry Peas",
    "0075": "Peanuts",
    "0078": "Sunflowers",
    "0081": "Soybeans",
    "0091": "Barley",
    "0094": "Rye",
}

# Members of the YTD zip we need (matched by substring of the member file name).
OFFER_MEMBER = "A00030_InsuranceOffer"
COUNTY_MEMBER = "A00440_County"
STATE_MEMBER = "A00520_State"

# products.name -> plan codes, for federal products whose seed row has no plan_code but
# whose codes are confirmed in the ADM InsurancePlan table (A00460) for 2026:
#   26/27/28 = PACE-YP / PACE-RP / PACE-RPHPE, 67/68/69 = MCO-YP / MCO-RP / MCO-RPHPE.
SUPPLEMENTAL_PLAN_CODES = {
    "Post-Application Coverage Endorsement (PACE)": "26;27;28",
    "Margin Coverage Option (MCO)": "67;68;69",
}

# WFRP is whole-farm, not a row crop: plan 76 + ADM commodity 0076 ("Whole Farm Revenue
# Protection") maps to the catalog's pseudo-crop. Commodity 9110 (Micro Farm) is ignored.
WFRP_PLAN_CODE = "76"
WFRP_COMMODITY_CODE = "0076"
WFRP_CROP_LABEL = "All crops (whole-farm)"


# ---------------------------------------------------------------------------
# Remote-zip plumbing (pure helpers; unit-tested without network)
# ---------------------------------------------------------------------------

@dataclass
class ZipMember:
    name: str
    method: int          # 0 = stored, 8 = deflated
    csize: int
    usize: int
    header_offset: int   # offset of the local file header


def parse_eocd(tail: bytes) -> tuple[int, int, int]:
    """Parse the end-of-central-directory from the last bytes of a zip.

    Returns (n_entries, cd_size, cd_offset), honoring the ZIP64 EOCD when the
    classic record has sentinel values.
    """
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise ValueError("EOCD signature not found (not a zip / tail too small)")
    n_entries, cd_size, cd_offset = struct.unpack("<HHHHIIH", tail[i + 4:i + 22])[3:6]
    if 0xFFFFFFFF in (cd_size, cd_offset) or n_entries == 0xFFFF:
        j = tail.rfind(b"PK\x06\x06")
        if j < 0:
            raise ValueError("ZIP64 EOCD required but not found in tail")
        z = struct.unpack("<QHHIIQQQQ", tail[j + 4:j + 56])
        n_entries, cd_size, cd_offset = z[6], z[7], z[8]
    return n_entries, cd_size, cd_offset


def parse_central_directory(cd: bytes) -> dict[str, ZipMember]:
    """Parse central-directory bytes into {member name: ZipMember} (ZIP64-aware)."""
    members: dict[str, ZipMember] = {}
    pos = 0
    while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        (_, _, _flags, method, _, _, _crc, csize, usize,
         nlen, elen, clen, _, _, _, lho) = struct.unpack("<HHHHHHIIIHHHHHII",
                                                         cd[pos + 4:pos + 46])
        name = cd[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        extra = cd[pos + 46 + nlen:pos + 46 + nlen + elen]
        e = 0
        while e + 4 <= len(extra):
            hid, hsz = struct.unpack("<HH", extra[e:e + 4])
            if hid == 0x0001:  # ZIP64 extended info: fields present only when 0xFFFFFFFF
                off = e + 4
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack("<Q", extra[off:off + 8])[0]; off += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack("<Q", extra[off:off + 8])[0]; off += 8
                if lho == 0xFFFFFFFF:
                    lho = struct.unpack("<Q", extra[off:off + 8])[0]; off += 8
            e += 4 + hsz
        members[name] = ZipMember(name, method, csize, usize, lho)
        pos += 46 + nlen + elen + clen
    return members


class RangeZip:
    """Read individual members out of a (possibly remote) zip via ranged reads.

    `read(start, end)` returns bytes for the inclusive range; `stream(start, end)`
    yields chunks for the same range (a single HTTP request in the network impl).
    """

    def __init__(self, size: int, read: Callable[[int, int], bytes],
                 stream: Callable[[int, int], Iterable[bytes]] | None = None):
        self.size = size
        self._read = read
        self._stream = stream or (lambda s, e: iter([read(s, e)]))
        self._members: dict[str, ZipMember] | None = None

    def members(self) -> dict[str, ZipMember]:
        if self._members is None:
            tail = self._read(max(0, self.size - 65536), self.size - 1)
            _, cd_size, cd_offset = parse_eocd(tail)
            cd = self._read(cd_offset, cd_offset + cd_size - 1)
            self._members = parse_central_directory(cd)
        return self._members

    def find(self, name_substring: str) -> ZipMember:
        for name, m in self.members().items():
            if name_substring in name:
                return m
        raise KeyError(f"no zip member matching {name_substring!r}")

    def extract(self, member: ZipMember, dest: Path) -> Path:
        """Extract one member to dest (inflating if deflated)."""
        # Local header: 30 fixed bytes; its name/extra lengths can differ from the
        # central directory's, so read them from the local header itself.
        lh = self._read(member.header_offset, member.header_offset + 29)
        if lh[:4] != b"PK\x03\x04":
            raise ValueError(f"bad local header for {member.name}")
        l_nlen, l_elen = struct.unpack("<HH", lh[26:30])
        start = member.header_offset + 30 + l_nlen + l_elen
        end = start + member.csize - 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        if member.method == 8:
            d = zlib.decompressobj(-15)
            with open(tmp, "wb") as fh:
                for chunk in self._stream(start, end):
                    fh.write(d.decompress(chunk))
                fh.write(d.flush())
        elif member.method == 0:
            with open(tmp, "wb") as fh:
                for chunk in self._stream(start, end):
                    fh.write(chunk)
        else:
            raise ValueError(f"unsupported compression method {member.method}")
        got = tmp.stat().st_size
        if got != member.usize:
            tmp.unlink(missing_ok=True)
            raise ValueError(
                f"{member.name}: extracted {got} bytes, expected {member.usize}")
        tmp.replace(dest)
        return dest


def http_range_zip(session, url: str, timeout: int) -> RangeZip:
    """RangeZip over HTTP; raises if the server does not honor Range requests."""
    probe = session.get(url, headers={"Range": "bytes=0-0"}, timeout=timeout)
    probe.raise_for_status()
    if probe.status_code != 206 or "Content-Range" not in probe.headers:
        raise RuntimeError("server does not support HTTP Range requests")
    size = int(probe.headers["Content-Range"].rsplit("/", 1)[1])

    def read(start: int, end: int) -> bytes:
        r = session.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=timeout)
        r.raise_for_status()
        return r.content

    def stream(start: int, end: int) -> Iterator[bytes]:
        r = session.get(url, headers={"Range": f"bytes={start}-{end}"},
                        timeout=timeout, stream=True)
        r.raise_for_status()
        return r.iter_content(chunk_size=1 << 16)

    return RangeZip(size, read, stream)


# ---------------------------------------------------------------------------
# ADM table parsing + mapping (pure helpers; unit-tested)
# ---------------------------------------------------------------------------

def parse_pipe_table(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """Yield dict rows from an ADM pipe-delimited file (first line = header)."""
    it = iter(lines)
    try:
        header = next(it).rstrip("\r\n").split("|")
    except StopIteration:
        return
    for line in it:
        line = line.rstrip("\r\n")
        if not line:
            continue
        yield dict(zip(header, line.split("|")))


def split_plan_codes(plan_code: str | None) -> list[str]:
    """'31;32;33' -> ['31', '32', '33'] (zero-padded to 2, deduped, order kept)."""
    out: list[str] = []
    for tok in (plan_code or "").split(";"):
        tok = tok.strip().zfill(2)
        if tok and tok != "00" and tok not in out:
            out.append(tok)
    return out


def plan_map_for_products(products: list[dict]) -> tuple[dict[str, int], list[str]]:
    """Map plan code -> product_id for federal products; return (map, skipped names).

    `products` rows need keys: product_id, name, plan_code. Products without a plan code
    (after the SUPPLEMENTAL_PLAN_CODES fill-in) are endorsements that follow their
    underlying policy — they land in the skipped list.
    """
    plan_to_pid: dict[str, int] = {}
    skipped: list[str] = []
    for p in products:
        codes = split_plan_codes(p["plan_code"] or SUPPLEMENTAL_PLAN_CODES.get(p["name"]))
        if not codes:
            skipped.append(p["name"])
            continue
        for c in codes:
            plan_to_pid[c] = p["product_id"]
    return plan_to_pid, skipped


def crop_for_offer(product_id: int, plan_code: str, commodity_code: str,
                   product_crop_set: set[tuple[int, str]]) -> str | None:
    """Canonical catalog crop for one offer row, or None to drop it.

    Row-crop gate via ADM_ROW_CROP_CODES; WFRP pseudo-crop; 'Spring Wheat' relabel for products
    (MP, MCO) whose product_crops names spring wheat specifically.
    """
    commodity_code = str(commodity_code).zfill(4)
    if plan_code == WFRP_PLAN_CODE:
        return WFRP_CROP_LABEL if commodity_code == WFRP_COMMODITY_CODE else None
    crop = ADM_ROW_CROP_CODES.get(commodity_code)
    if crop is None:
        return None
    if (crop == "Wheat" and (product_id, "Wheat") not in product_crop_set
            and (product_id, "Spring Wheat") in product_crop_set):
        return "Spring Wheat"
    return crop


def build_county_rows(offer_rows: Iterable[dict[str, str]],
                      plan_to_pid: dict[str, int],
                      product_crop_set: set[tuple[int, str]],
                      state_abbrev: dict[str, str],
                      county_name: dict[str, str],
                      source: str) -> list[tuple]:
    """Reduce InsuranceOffer rows to distinct product_counties tuples.

    Returns tuples (product_id, crop, state, county_fips, county_name, source).
    """
    seen: set[tuple[int, str, str]] = set()
    out: list[tuple] = []
    for row in offer_rows:
        if row.get("Deleted Date"):
            continue
        pid = plan_to_pid.get(str(row["Insurance Plan Code"]).zfill(2))
        if pid is None:
            continue
        crop = crop_for_offer(pid, str(row["Insurance Plan Code"]).zfill(2),
                              row["Commodity Code"], product_crop_set)
        if crop is None:
            continue
        fips = str(row["State Code"]).zfill(2) + str(row["County Code"]).zfill(3)
        key = (pid, crop, fips)
        if key in seen:
            continue
        seen.add(key)
        out.append((pid, crop, state_abbrev.get(fips[:2], fips[:2]), fips,
                    county_name.get(fips), source))
    return out


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class RmaAdm(Connector):
    name = "rma_adm"
    bucket = "508h"

    # -- source resolution -------------------------------------------------
    def _resolve_year(self, ctx: Context, year: int) -> tuple[int, str] | None:
        """Return (year, ytd_zip_url) for the requested year, falling back one year."""
        for y in (year, year - 1):
            base = ctx.cfg.rma_adm_base_url.format(year=y)
            try:
                listing = ctx.client.get(base).text
            except Exception:
                continue
            if re.search(rf'href="\.?/?{y}_ADM_YTD\.zip"', listing):
                return y, base + f"{y}_ADM_YTD.zip"
        return None

    def _member_path(self, year: int, member: ZipMember) -> Path:
        return ADM_CACHE_DIR / member.name if member.name.startswith(str(year)) \
            else ADM_CACHE_DIR / f"{year}_{member.name}"

    def _get_member(self, rz: RangeZip, year: int, name_substring: str) -> Path:
        """Extract (or reuse from data/cache/adm/) one member of the YTD zip."""
        member = rz.find(name_substring)
        dest = self._member_path(year, member)
        if dest.exists() and dest.stat().st_size == member.usize:
            return dest  # already extracted from an identical member
        return rz.extract(member, dest)

    # -- main --------------------------------------------------------------
    def fetch(self, ctx: Context) -> ConnectorResult:
        result = ConnectorResult()
        want_year = ctx.year or ctx.cfg.reinsurance_year

        resolved = self._resolve_year(ctx, want_year)
        if resolved is None:
            result.status = "error"
            result.message = f"no ADM YTD zip found for {want_year} or {want_year - 1}"
            result.coverage.append(f"rma_adm: ERROR — {result.message}")
            return result
        year, zip_url = resolved
        source = f"adm_{year}_ytd"

        if not ctx.force:
            result.status = "skipped"
            result.message = f"resolved {zip_url}; skipped download (use --force)"
            result.coverage.append(
                f"rma_adm: resolved {zip_url} — NOT downloaded. Run "
                f"`refresh --source rma_adm --force` to range-extract InsuranceOffer "
                f"(~55 MB) and populate product_counties."
            )
            return result

        # Range-extract the members we need; fall back to a full download only if the
        # server stops honoring Range requests.
        try:
            rz = http_range_zip(ctx.client.session, zip_url, ctx.cfg.timeout_seconds)
            offer_path = self._get_member(rz, year, OFFER_MEMBER)
            county_path = self._get_member(rz, year, COUNTY_MEMBER)
            state_path = self._get_member(rz, year, STATE_MEMBER)
        except RuntimeError:  # no Range support: heavy full-zip path via url_cache
            local = ctx.client.download(zip_url, force=ctx.force)
            with zipfile.ZipFile(local) as zf:
                def _extract(sub: str) -> Path:
                    name = next(n for n in zf.namelist() if sub in n)
                    dest = ADM_CACHE_DIR / Path(name).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(dest, "wb") as out:
                        while chunk := src.read(1 << 16):
                            out.write(chunk)
                    return dest
                offer_path = _extract(OFFER_MEMBER)
                county_path = _extract(COUNTY_MEMBER)
                state_path = _extract(STATE_MEMBER)

        # Lookups: state code -> abbrev, 5-digit fips -> county name.
        with open(state_path, encoding="utf-8", errors="replace") as fh:
            state_abbrev = {r["State Code"].zfill(2): r["State Abbreviation"]
                            for r in parse_pipe_table(fh)}
        with open(county_path, encoding="utf-8", errors="replace") as fh:
            county_name = {r["State Code"].zfill(2) + r["County Code"].zfill(3):
                           r["County Name"] for r in parse_pipe_table(fh)}

        # Federal products -> plan map (+ endorsements skipped).
        prods = [dict(r) for r in ctx.conn.execute(
            "SELECT product_id, name, plan_code FROM products "
            "WHERE bucket != 'private' ORDER BY product_id")]
        plan_to_pid, skipped = plan_map_for_products(prods)
        pid_name = {p["product_id"]: p["name"] for p in prods}
        product_crop_set = {(r["product_id"], r["crop"]) for r in ctx.conn.execute(
            "SELECT product_id, crop FROM product_crops")}

        with open(offer_path, encoding="utf-8", errors="replace") as fh:
            rows = build_county_rows(parse_pipe_table(fh), plan_to_pid,
                                     product_crop_set, state_abbrev, county_name, source)

        # Idempotent (re)populate: this connector owns product_counties for these
        # products, so clear-and-insert keeps stale counties from lingering.
        pids = sorted({t[0] for t in rows}) or sorted(set(plan_to_pid.values()))
        ctx.conn.executemany(
            "DELETE FROM product_counties WHERE product_id = ?", [(p,) for p in pids])
        ctx.conn.executemany(
            """INSERT INTO product_counties
                   (product_id, crop, state, county_fips, county_name, source)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(product_id, crop, county_fips) DO UPDATE SET
                 state=excluded.state, county_name=excluded.county_name,
                 source=excluded.source""",
            rows)
        ctx.conn.commit()

        # Coverage report: per-product county x crop counts.
        by_pid: dict[int, tuple[set, set]] = {}
        for pid, crop, _, fips, _, _ in rows:
            cs = by_pid.setdefault(pid, (set(), set()))
            cs[0].add(fips)
            cs[1].add(crop)
        for pid in sorted(by_pid):
            counties, crops = by_pid[pid]
            short = re.search(r"\(([^)]+)\)$", pid_name[pid])
            label = short.group(1) if short else pid_name[pid]
            result.coverage.append(
                f"rma_adm: {label} — {len(counties):,} counties x {len(crops)} crops ({year})")
        if skipped:
            result.coverage.append(
                "rma_adm: skipped (endorsements follow underlying policy, no plan code): "
                + ", ".join(skipped))

        result.status = "ok"
        result.message = (f"product_counties: {len(rows):,} rows from {source} "
                          f"({offer_path.name})")
        return result
