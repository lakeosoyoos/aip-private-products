"""PRF (Rainfall Index) interval-allocation optimizer.

Enumerates every admissible PRF interval/allocation policy, simulates each
against historical grid rainfall indices, and ranks the results — reproducing
the user's hand-built grid workbooks (e.g. ``27663_Blaine_grazing.xlsx``).

ENUMERATION RULES (reverse-engineered from the 59,536-row ground-truth
workbooks for grid 27663; verified by exact set-equality — see
tests/test_prfopt.py):

* 11 two-month index intervals: JAN-FEB, FEB-MAR, ..., NOV-DEC (indices 0-10).
* A policy selects between 2 and 5 intervals, with NO two adjacent intervals
  (index difference >= 2, i.e. no overlapping months).  There is no
  wrap-around constraint: NOV-DEC may be combined with JAN-FEB.
  Combo counts: C(10,2)=45, C(9,3)=84, C(8,4)=70, C(7,5)=21 -> 220 combos.
* Each selected interval receives an allocation in 5% steps within
  [10%, 60%]; allocations sum to exactly 100%.
  Allocation counts per combo size: k=2 -> 5, k=3 -> 90, k=4 -> 439,
  k=5 -> 1001.  Total policies: 45*5 + 84*90 + 70*439 + 21*1001 = 59,536.

SIMULATION / CALIBRATION NOTE (parameters verified against the workbooks —
update this block whenever calibration is re-run):

* The workbook metrics are exactly LINEAR in the allocation vector:
  average_net_return = sum_i p_i * v_i with a single per-interval constant
  v_i (verified: max abs residual 4.4e-14 over all 59,536 rows).
  Recovered v_i for grid 27663 (19 evaluated years; 19*v_i are exact
  2-decimal values, i.e. per-year interval net returns are cent-rounded):
      JAN-FEB  1.386315789474   (19v =  26.34)
      FEB-MAR  0.660000000000   (19v =  12.54)
      MAR-APR -0.001578947368   (19v =  -0.03)
      APR-MAY -0.510526315789   (19v =  -9.70)
      MAY-JUN  0.711052631579   (19v =  13.51)
      JUN-JUL  1.875789473684   (19v =  35.64)
      JUL-AUG  2.320000000000   (19v =  44.08)
      AUG-SEP  0.914736842105   (19v =  17.38)
      SEP-OCT -0.851052631579   (19v = -16.17)
      OCT-NOV -0.356842105263   (19v =  -6.78)
      NOV-DEC -0.179473684211   (19v =  -3.41)
* win rate uses a denominator of 19 (19 evaluated historical years).
* VERIFIED METHODOLOGY (fully calibrated against grid 27663).  Sources:
  the user's per-year CSVs ("Ventura 17143 GZ-... 90 percent.csv" 2005-2023,
  "Okanogan 34243 IRR-... 90 percent.csv" 2006-2024) and, decisively, the
  user's own per-grid source workbook ~/Desktop/"27663 Blaine ID GZ.xlsx"
  (one sheet per coverage level 70..90%, per-year Index/Indemnity columns
  plus Guarantee / Gross Prem / Subsidy / Net Prem footer rows):
      years          = 2006..2024 (19 complete years; partial current year
                       excluded — the source sheet lists 2025 with ** marks)
      coverage_level = 0.90, expected index = 100 (percent of normal)
      trigger        = 0.90 * 100 = 90
      protection     = county_base_value * coverage_level * productivity
                     = 13.60 * 0.90 * 1.50 = 18.36 $/acre for grid 27663
                       Grazing ("Guarantee / Acre" == "Liability / Acre"
                       == 18.36 in the source sheet; CBV 13.60 is the
                       RY2026 ADM value in prf_county)
      payout_{i,y}   = max(0, (trigger - index_{i,y}) / trigger)
      indemnity_{i,y}= round(payout_{i,y} * protection, 2)       [$ / acre]
      gross_prem_i   = round(rate_i * protection, 2)     # RY2026 base rates
      subsidy_amt_i  = round(gross_prem_i * subsidy, 2)  # subsidy = 0.51
      net_prem_i     = gross_prem_i - subsidy_amt_i      # TWO-STEP rounding:
                       verified against all 11 footer rows; a single-step
                       round(rate*prot*0.49, 2) fails for MAY-JUN
                       (2.03 vs true 2.02)
      net_{i,y}      = indemnity_{i,y} - net_prem_i      [$ / acre, cents]
  RY2026 base rates for grid 27663 Grazing 90% (ADM A00810->A01130->A01135
  chain and PrfWebApi agree; gross premia reproduce the source sheet
  exactly): JAN-FEB .1800  FEB-MAR .1890  MAR-APR .1978  APR-MAY .1972
  MAY-JUN .2252  JUN-JUL .3102  JUL-AUG .3488  AUG-SEP .3368  SEP-OCT
  .2747  OCT-NOV .2020  NOV-DEC .2201; net premia $/acre: 1.62 1.70 1.78
  1.77 2.02 2.79 3.14 3.03 2.47 1.82 1.98.
  Per-year policy net = sum_i (p_i/100) * net_{i,y}; average_net_return =
  19-year mean; win rate = (# years with net > 0) / 19 (strictly positive).
  Intervals NOT offered for a grid (no premium rate) carry a sentinel net
  of -10.00 in every year in the user's data (see `sentinel_net`).

  REPRODUCTION RESULT (all 59,536 rows, scoring the per-interval per-year
  nets from the user's source sheet):
      max abs error average_net_return = 1.02e-14   (exact)
      win rate exact on 59,510 rows; 26 rows differ by exactly 1/19.
  All 26 residual rows contain a year whose policy net is EXACTLY $0.00
  (weighted indemnity == weighted premium).  107 such tied policy-years
  exist; the user's engine counted 26 of them as wins and 81 as losses —
  floating-point dust in their summation order on mathematically-zero
  values, not reproducible from first principles.  Median/max win-rate
  error over all rows is 0 / 0.0526 (=1/19) with those ties.

  SIMULATING FROM TODAY'S DB (prf_grid_index, fetched 2026-08) instead of
  the user's Nov-2025 source sheet leaves small residuals (max avg-net
  error ~2.5e-3, ~200 win-rate flips): RMA recomputes historical indices
  every year because the climatological base extends (Nov-2025 pull used
  base 1948-2024; an Aug-2026 pull uses 1948-2025) and NOAA revises
  measurements.  Use simulate_from_source_workbook() to score against a
  captured source sheet when exact vintage reproduction matters.

DB INTERFACE (read-only; expected tables in data/catalog.db):
  prf_grid_index(grid_id, interval[/interval_code/interval_name],
                 year, index_value[/index/value])
  prf_grid_rate(grid_id, use[/intended_use], interval..., rate[/premium_rate],
                optional coverage_level)
  prf_subsidy(coverage_level, subsidy[/subsidy_factor/subsidy_pct])
Column-name variants are resolved dynamically so this module tolerates
whichever names the loader chose.

CLI:
    .venv/bin/python -m src.prfopt --grid 27663 --use Grazing \
        --county Blaine --state ID --out out.xlsx [--coverage 0.9]
    .venv/bin/python -m src.prfopt --calibrate workbook.xlsx --grid 27663 ...
"""

from __future__ import annotations

import argparse
import ast
import itertools
import sqlite3
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

INTERVALS: Tuple[str, ...] = (
    "JAN-FEB", "FEB-MAR", "MAR-APR", "APR-MAY", "MAY-JUN", "JUN-JUL",
    "JUL-AUG", "AUG-SEP", "SEP-OCT", "OCT-NOV", "NOV-DEC",
)
INTERVAL_INDEX: Dict[str, int] = {m: i for i, m in enumerate(INTERVALS)}

MIN_INTERVALS = 2
MAX_INTERVALS = 5
STEP_PCT = 5
MIN_PCT = 10
MAX_PCT = 60


def _compositions(total: int, parts: int, lo: int, hi: int) -> Iterator[Tuple[int, ...]]:
    """All ordered tuples of ``parts`` ints in [lo, hi] summing to ``total``."""
    if parts == 1:
        if lo <= total <= hi:
            yield (total,)
        return
    lo_rest = lo * (parts - 1)
    hi_rest = hi * (parts - 1)
    for first in range(max(lo, total - hi_rest), min(hi, total - lo_rest) + 1):
        for rest in _compositions(total - first, parts - 1, lo, hi):
            yield (first,) + rest


def enumerate_combinations(
    min_intervals: int = MIN_INTERVALS,
    max_intervals: int = MAX_INTERVALS,
    min_gap: int = 2,
) -> List[Tuple[str, ...]]:
    """All month-ordered interval subsets with no two adjacent intervals."""
    combos: List[Tuple[str, ...]] = []
    n = len(INTERVALS)
    for k in range(min_intervals, max_intervals + 1):
        for ii in itertools.combinations(range(n), k):
            if all(b - a >= min_gap for a, b in zip(ii, ii[1:])):
                combos.append(tuple(INTERVALS[i] for i in ii))
    return combos


def enumerate_policies(
    min_intervals: int = MIN_INTERVALS,
    max_intervals: int = MAX_INTERVALS,
    step: int = STEP_PCT,
    min_pct: int = MIN_PCT,
    max_pct: int = MAX_PCT,
    min_gap: int = 2,
) -> List[Tuple[Tuple[str, ...], Tuple[int, ...]]]:
    """Enumerate every admissible (interval-combo, allocation) policy.

    Returns a list of ``(combo, proportions)`` where ``combo`` is a tuple of
    interval names in month order and ``proportions`` a tuple of ints (whole
    percents, multiples of ``step``, each within [min_pct, max_pct], summing
    to 100).  With the defaults this yields exactly the 59,536 policies of
    the ground-truth workbooks.
    """
    assert 100 % step == 0 and min_pct % step == 0 and max_pct % step == 0
    units_total = 100 // step
    lo, hi = min_pct // step, max_pct // step
    policies: List[Tuple[Tuple[str, ...], Tuple[int, ...]]] = []
    combos = enumerate_combinations(min_intervals, max_intervals, min_gap)
    # Allocation patterns depend only on combo size; compute once per size.
    alloc_cache: Dict[int, List[Tuple[int, ...]]] = {}
    for combo in combos:
        k = len(combo)
        if k not in alloc_cache:
            alloc_cache[k] = [
                tuple(u * step for u in comp)
                for comp in _compositions(units_total, k, lo, hi)
            ]
        for alloc in alloc_cache[k]:
            policies.append((combo, alloc))
    return policies


# ---------------------------------------------------------------------------
# DB access (read-only, tolerant to column-name variants)
# ---------------------------------------------------------------------------

def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _pick(cols: Sequence[str], *candidates: str) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def _normalize_interval(val) -> Optional[str]:
    """Map an interval identifier (name or RMA code 625-635) to our names."""
    if val is None:
        return None
    s = str(val).strip().upper()
    if s in INTERVAL_INDEX:
        return s
    try:
        code = int(float(s))
    except ValueError:
        # e.g. "January-February"
        parts = s.replace("_", "-").split("-")
        if len(parts) == 2:
            abbr = f"{parts[0][:3]}-{parts[1][:3]}"
            if abbr in INTERVAL_INDEX:
                return abbr
        return None
    if 625 <= code <= 635:
        return INTERVALS[code - 625]
    if 0 <= code <= 10:
        return INTERVALS[code]
    return None


def load_grid_inputs(
    conn: sqlite3.Connection,
    grid_id,
    use: str,
    coverage_level: float,
) -> Tuple[Dict[str, Dict[int, float]], Dict[str, float], float]:
    """Read (indices, premium rates, subsidy) for one grid from catalog.db.

    Returns ``(index_by_interval, rate_by_interval, subsidy)`` where
    ``index_by_interval[interval][year] = index value`` (expected base 100),
    ``rate_by_interval[interval] = premium rate`` and ``subsidy`` is the
    federal subsidy fraction for the coverage level.
    """
    # --- indices -----------------------------------------------------------
    cols = _table_columns(conn, "prf_grid_index")
    if not cols:
        raise RuntimeError("prf_grid_index table not found in catalog.db")
    c_grid = _pick(cols, "grid_id", "grid", "grid_code")
    c_int = _pick(cols, "interval", "interval_code", "interval_name", "index_interval")
    c_year = _pick(cols, "year", "crop_year", "yr")
    c_val = _pick(cols, "index_value", "index", "value", "rainfall_index", "final_index")
    if not all([c_grid, c_int, c_year, c_val]):
        raise RuntimeError(f"prf_grid_index columns not recognized: {cols}")
    idx: Dict[str, Dict[int, float]] = {}
    for iv, yr, val in conn.execute(
        f"SELECT {c_int}, {c_year}, {c_val} FROM prf_grid_index WHERE {c_grid}=?",
        (grid_id,),
    ):
        name = _normalize_interval(iv)
        if name is not None and val is not None:
            idx.setdefault(name, {})[int(yr)] = float(val)
    if not idx:
        raise RuntimeError(f"no prf_grid_index rows for grid {grid_id!r}")
    # Indices may be stored as decimal percent-of-normal (1.0 = normal, the
    # prfdata.py convention) or base-100.  Normalize to base-100.
    peak = max(v for d in idx.values() for v in d.values())
    if peak < 5.0:
        idx = {iv: {y: v * 100.0 for y, v in d.items()} for iv, d in idx.items()}

    # --- premium rates -----------------------------------------------------
    cols = _table_columns(conn, "prf_grid_rate")
    if not cols:
        raise RuntimeError("prf_grid_rate table not found in catalog.db")
    c_grid = _pick(cols, "grid_id", "grid", "grid_code")
    c_int = _pick(cols, "interval", "interval_code", "interval_name", "index_interval")
    c_rate = _pick(cols, "rate", "premium_rate", "base_rate")
    c_use = _pick(cols, "use", "intended_use", "use_code")
    c_cov = _pick(cols, "coverage_level", "coverage", "cov_level")
    c_year = _pick(cols, "year", "crop_year", "reinsurance_year")
    if not all([c_grid, c_int, c_rate]):
        raise RuntimeError(f"prf_grid_rate columns not recognized: {cols}")
    order = f" ORDER BY {c_year}" if c_year else ""  # latest year wins
    q = f"SELECT {c_int}, {c_rate} FROM prf_grid_rate WHERE {c_grid}=?"
    params: list = [grid_id]
    if c_use:
        q += f" AND lower({c_use}) LIKE ?"
        params.append(f"%{use.lower()}%")
    if c_cov:
        q += f" AND abs({c_cov} - ?) < 0.001"
        params.append(coverage_level if coverage_level > 1 else coverage_level)
    q += order
    rates: Dict[str, float] = {}
    for iv, rate in conn.execute(q, params):
        name = _normalize_interval(iv)
        if name is not None and rate is not None:
            rates[name] = float(rate)
    if not rates and c_cov:  # retry without coverage filter
        rates = {}
        q2 = f"SELECT {c_int}, {c_rate} FROM prf_grid_rate WHERE {c_grid}=?"
        p2: list = [grid_id]
        if c_use:
            q2 += f" AND lower({c_use}) LIKE ?"
            p2.append(f"%{use.lower()}%")
        q2 += order
        for iv, rate in conn.execute(q2, p2):
            name = _normalize_interval(iv)
            if name is not None and rate is not None:
                rates[name] = float(rate)
    if not rates:
        raise RuntimeError(f"no prf_grid_rate rows for grid {grid_id!r} use {use!r}")

    # --- subsidy -----------------------------------------------------------
    subsidy = 0.51  # PRF federal subsidy at 90% coverage (default)
    cols = _table_columns(conn, "prf_subsidy")
    if cols:
        c_cov = _pick(cols, "coverage_level", "coverage", "cov_level")
        c_sub = _pick(cols, "subsidy", "subsidy_factor", "subsidy_pct", "subsidy_rate")
        if c_cov and c_sub:
            cov_key = coverage_level * 100 if coverage_level <= 1 else coverage_level
            row = conn.execute(
                f"SELECT {c_sub} FROM prf_subsidy WHERE abs({c_cov}-?)<0.001 "
                f"OR abs({c_cov}-?)<0.001",
                (coverage_level, cov_key),
            ).fetchone()
            if row and row[0] is not None:
                subsidy = float(row[0])
                if subsidy > 1:
                    subsidy /= 100.0
    return idx, rates, subsidy


def lookup_protection(
    conn: sqlite3.Connection,
    state: str,
    county: str,
    use: str,
    coverage_level: float = 0.90,
    productivity: float = 1.0,
    irrigation: str = "Non-Irrigated",
) -> Optional[float]:
    """Dollar protection per acre from prf_county (newest year available):
    county_base_value * coverage_level * productivity."""
    try:
        row = conn.execute(
            "SELECT county_base_value FROM prf_county "
            "WHERE state=? AND county_name LIKE ? AND lower(intended_use)=? "
            "AND irrigation_practice=? AND county_base_value IS NOT NULL "
            "ORDER BY year DESC LIMIT 1",
            (state, county + "%", use.lower(), irrigation),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or row[0] is None:
        return None
    return float(row[0]) * coverage_level * productivity


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def interval_year_nets(
    index_by_interval: Dict[str, Dict[int, float]],
    rate_by_interval: Dict[str, float],
    subsidy: float,
    coverage_level: float = 0.90,
    expected_index: float = 100.0,
    years: Optional[Sequence[int]] = None,
    protection: float = 1.0,
    round_cents: bool = True,
    sentinel_net: Optional[float] = -10.0,
) -> Tuple[Dict[str, List[float]], List[int]]:
    """Per-interval, per-year net returns w[interval][year-slot] in $/acre.

    Implements the user's verified methodology (see module docstring):
    indemnity = round(max(0,(trigger-index)/trigger) * protection, 2);
    gross premium = round(rate * protection, 2); subsidy amount =
    round(gross * subsidy, 2); net premium = gross - subsidy_amount
    (two-step rounding, verified); per-year net = indemnity - net_premium.
    ``protection`` is the dollar protection per acre (county base value *
    coverage * productivity).  Intervals with no premium rate get
    ``sentinel_net`` (the user's data uses -10.00) in every year, or are
    omitted when ``sentinel_net=None``.
    """
    trigger = coverage_level * expected_index
    if years is None:
        yrs = sorted(set.intersection(*(set(d) for d in index_by_interval.values())))
    else:
        yrs = list(years)
    nets: Dict[str, List[float]] = {}
    for iv, by_year in index_by_interval.items():
        rate = rate_by_interval.get(iv)
        if rate is None:
            if sentinel_net is not None:
                nets[iv] = [sentinel_net] * len(yrs)
            continue
        if round_cents:
            gross = round(rate * protection, 2)
            net_prem = gross - round(gross * subsidy, 2)
        else:
            net_prem = rate * protection * (1.0 - subsidy)
        row: List[float] = []
        for y in yrs:
            index_val = by_year.get(y)
            if index_val is None:
                row.append(float("nan"))
                continue
            payout = max(0.0, (trigger - index_val) / trigger)
            indem = payout * protection
            if round_cents:
                indem = round(indem, 2)
            net = indem - net_prem
            if round_cents:
                net = round(net, 2)
            row.append(net)
        nets[iv] = row
    return nets, yrs


def score_policies(
    policies: Sequence[Tuple[Tuple[str, ...], Tuple[int, ...]]],
    nets: Dict[str, List[float]],
) -> pd.DataFrame:
    """Compute average_net_return and win rate for each policy.

    Policy per-year net = sum_i p_i * w[interval_i][year]; average is the
    mean over years and win rate the fraction of years with net > 0.
    """
    n_years = len(next(iter(nets.values())))
    rows = []
    for combo, props in policies:
        ws = [nets[iv] for iv in combo]
        ps = [p / 100.0 for p in props]
        total = 0.0
        wins = 0
        for yi in range(n_years):
            net_y = sum(p * w[yi] for p, w in zip(ps, ws))
            total += net_y
            if net_y > 0:
                wins += 1
        rows.append(
            {
                "combinations": str(list(combo)),
                "proportions": str(list(props)),
                "average_net_return": total / n_years,
                "win rate": wins / n_years,
            }
        )
    return pd.DataFrame(rows)


def simulate(
    grid_id,
    use: str,
    conn: sqlite3.Connection,
    coverage_level: float = 0.90,
    expected_index: float = 100.0,
    years: Optional[Sequence[int]] = None,
    protection: float = 1.0,
    round_cents: bool = True,
    sentinel_net: Optional[float] = -10.0,
    policies: Optional[Sequence[Tuple[Tuple[str, ...], Tuple[int, ...]]]] = None,
) -> pd.DataFrame:
    """Full-grid simulation: every policy scored against historical indices."""
    idx, rates, subsidy = load_grid_inputs(conn, grid_id, use, coverage_level)
    nets, yrs = interval_year_nets(
        idx, rates, subsidy, coverage_level, expected_index, years,
        protection, round_cents, sentinel_net,
    )
    if policies is None:
        policies = enumerate_policies()
    # Drop policies referencing intervals lacking data.
    usable = [p for p in policies if all(iv in nets for iv in p[0])]
    df = score_policies(usable, nets)
    df.attrs["years"] = yrs
    df.attrs["subsidy"] = subsidy
    return df


def parse_source_workbook(
    path: str,
    coverage_level: float = 0.90,
) -> Tuple[Dict[str, List[float]], List[int]]:
    """Parse a per-grid source workbook (e.g. '27663 Blaine ID GZ.xlsx').

    These are the user's captures of the RMA PRF support tool: one sheet per
    coverage level ('70%'..'90%'), a Year column, per-interval Index /
    Indemnity column pairs, and footer rows including 'Net Prem / Acre'.
    Returns (nets, years) where nets[interval] is the per-complete-year net
    return list (indemnity - net premium, $/acre) — rows whose cells carry
    '**' (partial current year) are excluded.
    """
    sheet = f"{int(round(coverage_level * 100))}%"
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    # locate the 'Year' header row and the interval title row above it
    hdr = None
    for r in range(min(5, len(df))):
        if str(df.iloc[r, 0]).strip().lower() == "year":
            hdr = r
            break
    if hdr is None:
        raise RuntimeError(f"no 'Year' header row in sheet {sheet} of {path}")
    title = df.iloc[hdr - 1] if hdr >= 1 else df.iloc[hdr]
    # map columns: interval title like 'JAN-FEBINT' at the Index column
    col_map: Dict[str, int] = {}
    for c in range(1, df.shape[1]):
        t = str(title.iloc[c]).replace("INT", "").strip().upper()
        if t in INTERVAL_INDEX and str(df.iloc[hdr, c]).strip().lower() == "index":
            col_map[t] = c
    if len(col_map) < 2:
        raise RuntimeError(f"could not locate interval columns in {path}")
    # year rows: consecutive integer years below hdr
    years: List[int] = []
    rows: List[int] = []
    for r in range(hdr + 1, len(df)):
        v = df.iloc[r, 0]
        try:
            y = int(v)
        except (TypeError, ValueError):
            break
        # skip partial years marked '**' in any indemnity cell
        marked = any(
            isinstance(df.iloc[r, c + 1], str) and "**" in df.iloc[r, c + 1]
            or isinstance(df.iloc[r, c], str) and "**" in str(df.iloc[r, c])
            for c in col_map.values()
        )
        if marked:
            continue
        years.append(y)
        rows.append(r)
    # net premium footer row
    npr_row = None
    for r in range(len(df)):
        if str(df.iloc[r, 0]).strip().lower().startswith("net prem"):
            npr_row = r
            break
    if npr_row is None:
        raise RuntimeError(f"no 'Net Prem / Acre' footer row in {path}")

    def _num(v) -> float:
        if isinstance(v, str):
            s = v.replace("$", "").replace("*", "").replace(",", "").strip()
            if s in ("-", ""):
                return 0.0
            return float(s)
        if v is None or (isinstance(v, float) and v != v):  # NaN
            return 0.0
        return float(v)

    nets: Dict[str, List[float]] = {}
    for iv, c in col_map.items():
        npr = _num(df.iloc[npr_row, c])
        nets[iv] = [round(_num(df.iloc[r, c + 1]) - npr, 2) for r in rows]
    return nets, years


def simulate_from_source_workbook(
    path: str,
    coverage_level: float = 0.90,
    policies: Optional[Sequence[Tuple[Tuple[str, ...], Tuple[int, ...]]]] = None,
) -> pd.DataFrame:
    """Score every policy against a captured per-grid source workbook.

    This reproduces the user's combined workbooks exactly (win-rate ties
    aside — see module docstring) because it consumes the same per-year
    indemnity/premium data vintage the user's engine consumed.
    """
    nets, yrs = parse_source_workbook(path, coverage_level)
    if policies is None:
        policies = enumerate_policies()
    usable = [p for p in policies if all(iv in nets for iv in p[0])]
    df = score_policies(usable, nets)
    df.attrs["years"] = yrs
    return df


# ---------------------------------------------------------------------------
# Ranking / export
# ---------------------------------------------------------------------------

def rank_by_win_rate(df: pd.DataFrame, top: Optional[int] = None) -> pd.DataFrame:
    out = df.sort_values(
        ["win rate", "average_net_return"], ascending=False, kind="mergesort"
    ).reset_index(drop=True)
    return out.head(top) if top else out


def rank_by_avg_net_return(df: pd.DataFrame, top: Optional[int] = None) -> pd.DataFrame:
    out = df.sort_values(
        ["average_net_return", "win rate"], ascending=False, kind="mergesort"
    ).reset_index(drop=True)
    return out.head(top) if top else out


def export_workbook(
    df: pd.DataFrame,
    path: str,
    grid_id,
    county: str,
    use: str,
    state: str,
) -> None:
    """Write results in the user's workbook format (xlsx or csv by suffix)."""
    out = df.copy()
    out.insert(0, "grid_county_use", f"{grid_id}_{county}_{use.lower()}")
    out["state"] = state
    cols = ["grid_county_use", "combinations", "proportions",
            "average_net_return", "win rate", "state"]
    out = out[cols]
    if path.lower().endswith(".csv"):
        out.to_csv(path, index=False)
    else:
        out.to_excel(path, index=False)


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------

def load_workbook(path: str) -> pd.DataFrame:
    df = pd.read_excel(path) if not path.lower().endswith(".csv") else pd.read_csv(path)
    df["_combo"] = df["combinations"].map(lambda s: tuple(ast.literal_eval(s)))
    df["_props"] = df["proportions"].map(lambda s: tuple(ast.literal_eval(s)))
    return df


def compare_to_workbook(sim: pd.DataFrame, wb: pd.DataFrame) -> Dict[str, float]:
    """Max abs error of both metrics between a simulation and a workbook."""
    s = sim.copy()
    s["_combo"] = s["combinations"].map(lambda x: tuple(ast.literal_eval(x)))
    s["_props"] = s["proportions"].map(lambda x: tuple(ast.literal_eval(x)))
    m = wb.merge(s, on=["_combo", "_props"], suffixes=("_wb", "_sim"))
    if len(m) != len(wb):
        raise RuntimeError(f"policy sets differ: matched {len(m)} of {len(wb)}")
    return {
        "max_abs_err_avg_net_return": float(
            (m["average_net_return_wb"] - m["average_net_return_sim"]).abs().max()
        ),
        "max_abs_err_win_rate": float(
            (m["win rate_wb"] - m["win rate_sim"]).abs().max()
        ),
        "n": len(m),
    }


def solve_interval_values(wb: pd.DataFrame) -> Dict[str, float]:
    """Recover the per-interval mean net returns v_i from a workbook.

    Uses exact linear algebra on a Gram system built in pure python (the
    metric is linear in allocations, so 11 unknowns fully determine
    average_net_return for every policy).
    """
    n = len(INTERVALS)
    ata = [[0.0] * n for _ in range(n)]
    atb = [0.0] * n
    for combo, props, y in zip(wb["_combo"], wb["_props"], wb["average_net_return"]):
        ii = [INTERVAL_INDEX[m] for m in combo]
        ps = [p / 100.0 for p in props]
        for a, pa in zip(ii, ps):
            atb[a] += pa * y
            for b, pb in zip(ii, ps):
                ata[a][b] += pa * pb
    # Gaussian elimination with partial pivoting.
    aug = [row[:] + [atb[i]] for i, row in enumerate(ata)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        pv = aug[col][col]
        for r in range(n):
            if r != col and aug[r][col] != 0.0:
                f = aug[r][col] / pv
                for c in range(col, n + 1):
                    aug[r][c] -= f * aug[col][c]
    return {INTERVALS[i]: aug[i][n] / aug[i][i] for i in range(n)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="PRF interval-allocation optimizer")
    ap.add_argument("--grid", required=True)
    ap.add_argument("--use", default="Grazing")
    ap.add_argument("--county", default="")
    ap.add_argument("--state", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--coverage", type=float, default=0.90)
    ap.add_argument("--protection", type=float, default=None,
                    help="dollar protection per acre (county base value * "
                         "coverage * productivity); default: look up the "
                         "county base value in prf_county, else 1.0")
    ap.add_argument("--productivity", type=float, default=1.0,
                    help="productivity factor applied when protection is "
                         "looked up from prf_county (0.60..1.50; the "
                         "grid-27663 ground-truth workbooks use 1.50)")
    ap.add_argument("--source", default=None,
                    help="path to a captured per-grid source workbook "
                         "(e.g. '27663 Blaine ID GZ.xlsx'); when given, "
                         "score from its per-year data instead of the DB")
    ap.add_argument("--years", default=None,
                    help="comma-separated year list or FIRST-LAST range")
    ap.add_argument("--db", default="data/catalog.db")
    ap.add_argument("--calibrate", default=None,
                    help="path to a ground-truth workbook to compare against")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--rank", choices=["win_rate", "avg_net_return"],
                    default="avg_net_return")
    args = ap.parse_args(argv)

    years: Optional[List[int]] = None
    if args.years:
        if "-" in args.years and "," not in args.years:
            a, b = args.years.split("-")
            years = list(range(int(a), int(b) + 1))
        else:
            years = [int(y) for y in args.years.split(",")]

    if args.source:
        df = simulate_from_source_workbook(args.source, args.coverage)
    else:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            protection = args.protection
            if protection is None:
                protection = lookup_protection(
                    conn, args.state, args.county, args.use, args.coverage,
                    productivity=args.productivity,
                )
                if protection is not None:
                    print(f"protection from prf_county: {protection:.4f} $/acre")
                else:
                    protection = 1.0
            df = simulate(args.grid, args.use, conn,
                          coverage_level=args.coverage,
                          years=years, protection=protection)
        finally:
            conn.close()

    if args.calibrate:
        wb = load_workbook(args.calibrate)
        res = compare_to_workbook(df, wb)
        print(f"calibration vs {args.calibrate}:")
        for k, v in res.items():
            print(f"  {k}: {v}")

    ranker = rank_by_win_rate if args.rank == "win_rate" else rank_by_avg_net_return
    df = ranker(df, args.top)
    if args.out:
        export_workbook(df, args.out, args.grid, args.county, args.use, args.state)
        print(f"wrote {len(df)} rows -> {args.out}")
    else:
        print(df.head(20).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
