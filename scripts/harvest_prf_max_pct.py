#!/usr/bin/env python3
"""harvest_prf_max_pct.py -- the PRF maximum percent of value, per county and interval.

WHY THIS EXISTS
---------------
src/prfopt.py hardcoded MAX_PCT = 60 for the whole country. That number came from
reverse-engineering a ground-truth sweep workbook, and a workbook only tells you what THAT
TOOL did -- it is not RMA. The Rainfall Index Insurance Standards Handbook (18150) says only:

    "There may be a minimum and maximum percent of value that can be allocated to an index
     interval. See the CP and AD for more information about minimum and maximum amounts that
     may be allocated."

AD = Actuarial Documents. So the cap is actuarial, published per offer, and it varies. It is
carried as statement text in A01210_Statement, attached to offers by A01200_DocumentBuilder,
which is keyed by state, county, intended use, irrigation practice and INTERVAL. For RY2026
the caps in force are 40%, 45%, 50%, 60% and 70% -- so a flat 60 is simultaneously

  * TOO HIGH in the 50% states (AL AZ CA FL GA LA MS NC SC and parts of NM TX), where the
    optimizer was free to recommend an allocation no producer can actually bind; and
  * TOO LOW in the 70% states (CT ID ME MA MI MN MT NH NY ND OR RI SD VT WA WI WY), where it
    never searched allocations that are perfectly legal, and so understated what the grid
    could return.

Nine states are not even uniform across their own counties (CO DE KS NE NM ND OK SD TX).

THE CONDITIONAL STATEMENTS
--------------------------
Three statements (26501/26502/26503) carry two caps -- e.g. "40% except for growing seasons
10, 11, and 12 which is 50%". They attach per interval like the others, so the attachment
tells us which intervals they cover, but the TEXT is what states the value. Rather than guess
how "growing season NN" maps to an interval code, those rows are written with both numbers
and `is_conditional = 1`, and the loader takes the CONSERVATIVE (lower) cap. A conservative
cap can only make the optimizer refuse a policy that might have been legal; the other
direction recommends one that cannot be bought.

    .venv/bin/python scripts/harvest_prf_max_pct.py            # harvest RY2026 into the DB
    .venv/bin/python scripts/harvest_prf_max_pct.py --report   # summarise what is stored
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402

ADM_URL = ("https://pubfs-rma.fpac.usda.gov/pub/References/actuarial_data_master/"
           "{year}/{year}_ADM_YTD.zip")
RAINFALL_INDEX_PLAN = "13"

DDL = """
CREATE TABLE IF NOT EXISTS prf_max_pct (
    reinsurance_year INTEGER NOT NULL,
    state_code       TEXT    NOT NULL,
    county_code      TEXT    NOT NULL,
    intended_use     TEXT,
    irrigation       TEXT,
    interval_code    TEXT    NOT NULL,
    max_pct          INTEGER NOT NULL,   -- the cap to enforce (conservative if conditional)
    max_pct_alt      INTEGER,            -- the other cap named by a conditional statement
    is_conditional   INTEGER NOT NULL DEFAULT 0,
    statement_id     TEXT    NOT NULL,
    statement_text   TEXT    NOT NULL,
    source           TEXT,
    fetched_at       TEXT,
    PRIMARY KEY (reinsurance_year, state_code, county_code, intended_use,
                 irrigation, interval_code)
);
CREATE INDEX IF NOT EXISTS ix_prf_max_pct_state ON prf_max_pct(state_code, county_code);
"""

# "maximum percent of value allowed ... is 50%" / "... is 40% except for growing seasons
# 10, 11, and 12 which is 50%."
_PCT = re.compile(r"maximum percent of value allowed[^0-9]*?(\d{1,3})\s*%"
                  r"(?:.*?which is\s*(\d{1,3})\s*%)?", re.I)


def parse_caps(text: str) -> tuple[int, int | None] | None:
    """-> (cap_to_enforce, other_cap_or_None), or None if this is not a cap statement."""
    m = _PCT.search(text)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else None
    if b is None:
        return a, None
    # Conditional: enforce the LOWER of the two. Erring low can only reject a policy that
    # might have been legal; erring high recommends one that cannot be bound.
    return min(a, b), max(a, b)


def _open_remote(year: int):
    import requests

    from src.connectors.rma_adm import RangeZip

    url = ADM_URL.format(year=year)
    s = requests.Session()
    s.headers["User-Agent"] = "aip-products/1.0 (crop-insurance catalog research)"
    size = int(s.head(url, timeout=90, allow_redirects=True).headers["Content-Length"])
    return url, RangeZip(
        size, lambda a, b: s.get(url, headers={"Range": f"bytes={a}-{b}"},
                                 timeout=300).content)


def harvest(conn: sqlite3.Connection, year: int, workdir: pathlib.Path) -> int:
    import datetime as dt

    url, z = _open_remote(year)
    stmt_path = z.extract(z.find("A01210_Statement"), workdir / "statement.txt")
    doc_path = z.extract(z.find("A01200_DocumentBuilder"), workdir / "docbuilder.txt")

    caps: dict[str, tuple[int, int | None, str]] = {}
    for line in stmt_path.read_text(errors="replace").splitlines():
        f = line.split("|")
        if len(f) < 5:
            continue
        got = parse_caps(f[4])
        if got:
            caps[f[3].strip()] = (got[0], got[1], " ".join(f[4].split()))
    if not caps:
        raise SystemExit("no percent-of-value statements found -- has the ADM layout moved?")
    print(f"  {len(caps)} cap statements: "
          + ", ".join(f"{k}={v[0]}%" + (f"/{v[1]}%" if v[1] else "") for k, v in sorted(caps.items())))

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows, seen = [], set()
    with doc_path.open() as fh:
        fh.readline()
        for line in fh:
            f = line.split("|")
            if len(f) < 24 or f[6].strip() != RAINFALL_INDEX_PLAN:
                continue
            sid = f[13].strip()
            hit = caps.get(sid)
            if not hit:
                continue
            key = (year, f[7].strip(), f[8].strip(), f[18].strip(), f[19].strip(), f[22].strip())
            if key in seen:
                continue
            seen.add(key)
            rows.append((*key, hit[0], hit[1], 1 if hit[1] is not None else 0,
                         sid, hit[2], f"ADM {year} A01210+A01200", now))

    conn.executescript(DDL)
    conn.execute("DELETE FROM prf_max_pct WHERE reinsurance_year = ?", (year,))
    conn.executemany(
        "INSERT OR REPLACE INTO prf_max_pct (reinsurance_year, state_code, county_code, "
        "intended_use, irrigation, interval_code, max_pct, max_pct_alt, is_conditional, "
        "statement_id, statement_text, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def report(conn: sqlite3.Connection) -> None:
    q = """SELECT state_code, max_pct, COUNT(DISTINCT county_code)
           FROM prf_max_pct GROUP BY state_code, max_pct ORDER BY state_code, max_pct"""
    by_state: dict[str, list[str]] = collections.defaultdict(list)
    for st, cap, n in conn.execute(q):
        by_state[st].append(f"{cap}% ({n} counties)")
    print(f"  {len(by_state)} states\n")
    for st in sorted(by_state):
        flag = "  <- NOT UNIFORM" if len(by_state[st]) > 1 else ""
        print(f"    {st}: {', '.join(by_state[st])}{flag}")
    tot, cond = conn.execute(
        "SELECT COUNT(*), SUM(is_conditional) FROM prf_max_pct").fetchone()
    print(f"\n  {tot:,} rows, {cond or 0:,} from season-conditional statements "
          f"(stored at the conservative cap)")
    print("  vs the retired hardcoded MAX_PCT = 60:")
    for label, sql in (("counties where 60 was TOO HIGH (unbuyable advice)", "max_pct < 60"),
                       ("counties where 60 was TOO LOW (under-searched)", "max_pct > 60")):
        n = conn.execute("SELECT COUNT(DISTINCT state_code || county_code) "
                         f"FROM prf_max_pct WHERE {sql}").fetchone()[0]
        print(f"    {n:,}  {label}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--report", action="store_true", help="summarise what is stored, no fetch")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        if args.report:
            report(conn)
            return 0
        with tempfile.TemporaryDirectory() as td:
            n = harvest(conn, args.year, pathlib.Path(td))
        print(f"  wrote {n:,} prf_max_pct rows for RY{args.year}\n")
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
