"""PRF optimizer sweep: prf_opt_best + prf_grid_county for every grid in a state.

Runs the calibrated src/prfopt.py engine (see its module docstring: coverage 0.90,
subsidy 0.51 at 90%, per-year net, win = net > 0, years 2006-2024) over every PRF
grid that touches a state, and stores the best allocations per grid x intended use
x coverage level in prf_opt_best plus the grid -> county map in prf_grid_county
(schema in src/db.py).

GRID LIST SOURCE: the cached RMA ADM Price member (data/cache/adm/
<year>_A00810_Price_YTD.txt).  Its record-category-03 (plan 13, PRF) rows are
keyed by grid: the "Sub County Code" field IS the PRF grid id, alongside State
Code / County Code / Intended Use Code.  Filtering rc03 rows to a state + use
lists every grid without touching the network; collecting ALL states' rows for
those grids yields the full grid -> county map (a border grid touching e.g.
Idaho and Montana carries rows for both counties).  County / state names come
from the cached A00440 / A00520 code files.

NORMALIZATION (matches the prf_opt_best schema comment): metrics are stored PER
$1 OF ANNUAL PROTECTION -- the simulation runs with protection=1.0 and
round_cents=False, so every per-year net is exactly linear in protection:

    net_{y}($P) = P * net_{y}($1)

Win rate is therefore scale-invariant (signs never change) and dollar values for
a county are avg_net * CBV * coverage * productivity at display time.  NOTE this
deliberately drops the calibrated run's cent-rounding (round_cents=True), which
is a fixed-dollar-vintage nicety and NOT linear in protection; the residual vs a
cent-rounded run is bounded by rounding dust (~1e-2 $/acre at 18.36 protection).
Verified for grid 27663 (Blaine): normalized avg_net * 18.36 reproduces
simulate(protection=18.36, round_cents=False) to < 1e-9 on all 59,536 policies.

Intervals a grid does not offer (no premium rate) DROP the policies that
reference them (sentinel_net=None) instead of the calibrated -10.00 sentinel:
a fixed dollar sentinel is not expressible per $1 of protection, and sentinel
policies are strictly dominated anyway.  n_policies records how many of the
59,536 candidates were actually scored.

Grids with no rates for the use/coverage, or with incomplete index history over
2006-2024, are SKIPPED (recorded with a reason, never fabricated).  Skips are
not persisted, so a re-run retries them -- cheap, because prfdata's JSON file
cache under data/cache/prf/ answers without network.

RESUMABILITY: grids already present in prf_opt_best for the same use + coverage
are skipped unless --force; an interrupted run loses nothing (prfdata caches
every API response on disk before the DB write, and each grid commits alone).

TWO DATA PATHS
--------------
--bulk (preferred, and the only sane way to sweep the country) scores straight
out of the DB after src/prfbulk.py has loaded RMA's published files: ZERO HTTP
requests, grid list taken from prf_grid_county rather than a per-state ADM scan,
and every grid judged against one internally consistent index vintage.  Pair it
with --changed-only to re-score just the grids whose 2006-2024 index window
actually moved since the last run (prfbulk.changed_grids / prf_index_hash) --
that is what turns the monthly job from hours into seconds.

The original per-grid PrfWebApi path is unchanged and remains the fallback for a
single state when the bulk files are unavailable; it is what --bulk was verified
against (96 Idaho grids, see the cross-check in the bulk sweep's git history).

CLI:
    .venv/bin/python -m src.prfsweep --state ID --use Grazing \
        [--coverage 0.90] [--limit N] [--resume] [--force] [--delay 0.5]
    .venv/bin/python -m src.prfsweep --bulk [--state ID] [--changed-only] \
        [--jobs 6] [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, db, http, prfbulk, prfdata, prfopt

ADM_DIR = config.CACHE_DIR / "adm"

# Scoring window: 20 complete years, 2006..2025.
#
# Was 2006..2024, because that is what the grid-27663 calibration WORKBOOK covered. That is a
# reason to trust the arithmetic against 19 years, not a reason to score on 19 forever. 2025
# is now final -- all 11 intervals, non-null -- and is loaded by
# scripts/harvest_prf_index_2025.py from the PRF support-tool API, because RMA's bulk
# Rainfall_Index_HistoricData2026CY.zip still stops at 2024.
#
# A side effect, not the reason: 1/20 makes every win rate a clean multiple of 5%. That is
# cosmetic. Twenty observations still carry roughly a +/-11 point interval on a win rate; the
# argument for the change is the extra year of evidence, not the rounder number.
YEARS = tuple(range(2006, 2026))

TOP_N = 10


class SweepSkip(RuntimeError):
    """A grid that cannot be scored honestly (missing rates / index years)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# ADM parsing (pure, unit-tested, no network)
# ---------------------------------------------------------------------------

def _adm_file(stem: str, adm_dir: Path | None = None, year: int | None = None) -> Path:
    adm_dir = Path(adm_dir or ADM_DIR)
    if year is not None:
        p = adm_dir / f"{year}_{stem}_YTD.txt"
        if p.exists():
            return p
    hits = sorted(adm_dir.glob(f"*_{stem}_YTD.txt"))
    if not hits:
        raise FileNotFoundError(f"no {stem} member under {adm_dir}")
    return hits[-1]


def state_codes(adm_dir: Path | None = None) -> dict[str, str]:
    """{'ID': '16', ...} from the ADM A00520 State code file."""
    out: dict[str, str] = {}
    path = _adm_file("A00520_State", adm_dir)
    with open(path) as fh:
        next(fh)  # header
        for line in fh:
            f = line.rstrip("\n").split("|")
            if len(f) > 5 and f[0] == "A00520":
                out[f[5].strip()] = f[3].strip()
    return out


def county_names(adm_dir: Path | None = None) -> dict[tuple[str, str], str]:
    """{('16', '013'): 'Blaine', ...} from the ADM A00440 County code file."""
    out: dict[tuple[str, str], str] = {}
    path = _adm_file("A00440_County", adm_dir)
    with open(path) as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("|")
            if len(f) > 5 and f[0] == "A00440":
                out[(f[3].strip(), f[4].strip())] = f[5].strip()
    return out


def _iter_price_rows(use: str, adm_dir: Path | None = None, year: int | None = None):
    """Yield (grid_id, state_code, county_code) from A00810 rc03 rows for one use.

    Record layout (pipe-delimited; ADMLayout): field 2 = record category ('03'
    = the grid-keyed PRF price rows), field 7 = Insurance Plan Code (13 = PRF),
    field 8/9 = State/County Code, field 10 = Sub County Code == PRF GRID ID,
    field 21 = Intended Use Code ('007' Grazing / '030' Haying).  Hawaii's
    'H'-prefixed grid codes (a separate grid system) are skipped -- PRF grid
    ids are integers everywhere this pipeline runs.
    """
    use_code = prfdata.USE_PARAMS[use][0]
    path = _adm_file("A00810_Price", adm_dir, year)
    with open(path) as fh:
        next(fh)
        for line in fh:
            f = line.split("|")
            if (len(f) > 24 and f[0] == "A00810" and f[1] == "03"
                    and f[6] == "13" and f[20] == use_code
                    and f[9].strip().isdigit()):
                yield int(f[9]), f[7].strip(), f[8].strip()


def list_state_grids(state: str, use: str = "Grazing",
                     adm_dir: Path | None = None,
                     year: int | None = None) -> list[int]:
    """Every PRF grid id with rows for `state` (2-letter) x `use` in the ADM."""
    code = state_codes(adm_dir).get(state.upper())
    if code is None:
        raise ValueError(f"unknown state {state!r}")
    return sorted({g for g, sc, _ in _iter_price_rows(use, adm_dir, year)
                   if sc == code})


def grid_county_rows(grid_ids, use: str = "Grazing",
                     adm_dir: Path | None = None,
                     year: int | None = None) -> list[tuple[int, str, str, str]]:
    """[(grid_id, state_abbrev, county_fips, county_name)] for the given grids,
    across ALL states the grids touch (border grids span state lines)."""
    want = set(int(g) for g in grid_ids)
    abbrev = {v: k for k, v in state_codes(adm_dir).items()}
    names = county_names(adm_dir)
    seen: dict[tuple[int, str], tuple[int, str, str, str]] = {}
    for g, sc, cc in _iter_price_rows(use, adm_dir, year):
        if g in want:
            fips = f"{sc}{cc}"
            seen[(g, fips)] = (g, abbrev.get(sc, sc), fips, names.get((sc, cc), ""))
    return sorted(seen.values())


# ---------------------------------------------------------------------------
# Scoring one grid (reuses the prfopt engine; no reimplementation)
# ---------------------------------------------------------------------------

# Keyed by cap: the legal policy universe DEPENDS on the county's maximum percent of value,
# so a single cached list would silently score every grid against one state's rules.
_POLICIES: dict[int, list] = {}


def _policies(max_pct: int = prfopt.MAX_PCT):
    got = _POLICIES.get(max_pct)
    if got is None:
        got = _POLICIES[max_pct] = prfopt.enumerate_policies(max_pct=max_pct)
    return got


def _policy_entry(row) -> dict:
    return {
        "combo": list(ast.literal_eval(row["combinations"])),
        "props": list(ast.literal_eval(row["proportions"])),
        "avg_net": float(row["average_net_return"]),
        "win_rate": float(row["win rate"]),
    }


def rate_sum(combo, props, rates: dict) -> float | None:
    """Allocation-weighted premium rate: SUM(props_i/100 x rates[combo_i]).

    Premium is protection x rate and PRF protection per acre is CBV x coverage x
    productivity, so CBV x coverage x productivity x this number is the gross premium on one
    acre -- which is what the map's agent-commission metric is a percentage of. It is stored
    on the prf_opt_best row (best_win_rate_sum / best_net_rate_sum) because the shipped app
    DB drops prf_grid_rate; see scripts/backfill_rate_sums.py, which computes the identical
    number for rows written before this existed.

    None (never a partial sum) when an interval in the allocation carries no rate.
    """
    if not combo or not props or len(combo) != len(props):
        return None
    total = 0.0
    for interval, pct in zip(combo, props):
        r = rates.get(interval)
        if r is None:
            return None
        total += (float(pct) / 100.0) * float(r)
    return total


# ---------------------------------------------------------------------------
# The actuarial cap
# ---------------------------------------------------------------------------

_CAPS: dict[int, tuple[int, ...]] | None = None
DEFAULT_CAP = prfopt.MAX_PCT


def grid_caps(conn) -> dict[int, tuple[int, ...]]:
    """grid_id -> the distinct maximum-percent-of-value caps its counties are under.

    The cap is published per COUNTY (prf_max_pct, from ADM A01210) but the sweep is per GRID,
    and a grid touches ~2.3 counties. Where those counties disagree the grid has more than one
    legal policy universe and therefore more than one best policy, so it is swept once per
    distinct cap and prf_opt_best carries max_pct in its key.

    In RY2026 that is cheap: 12,845 grids see one cap, 605 see two, 12 see three — 14,091
    (grid, cap) pairs against 13,462 grids, or 1.05x the work.

    Within a county the cap can also vary BY INTERVAL (three statements read like "40% except
    for growing seasons 10, 11 and 12 which is 50%"). prf_max_pct stores the conservative
    value for those, and MIN here keeps that choice: a cap that is too low can only withhold
    an allocation that might have been legal, while one that is too high recommends a policy
    the producer cannot bind.
    """
    global _CAPS
    if _CAPS is not None:
        return _CAPS
    out: dict[int, set[int]] = {}
    try:
        rows = conn.execute("""
            SELECT gc.grid_id, MIN(m.max_pct)
              FROM prf_grid_county gc
              JOIN prf_max_pct m
                ON m.state_code  = substr(printf('%05d', gc.county_fips), 1, 2)
               AND m.county_code = substr(printf('%05d', gc.county_fips), 3, 3)
             GROUP BY gc.grid_id, gc.county_fips""").fetchall()
    except sqlite3.OperationalError:
        rows = []                       # prf_max_pct not harvested yet
    for gid, cap in rows:
        if cap is not None:
            out.setdefault(int(gid), set()).add(int(cap))
    _CAPS = {g: tuple(sorted(v)) for g, v in out.items()}
    return _CAPS


def caps_for(conn, grid_id: int) -> tuple[int, ...]:
    """The caps to sweep this grid under; falls back to the legacy constant if unknown.

    An unknown grid is swept at DEFAULT_CAP rather than skipped, so a missing prf_max_pct
    harvest degrades to the old behaviour instead of emptying the table.
    """
    return grid_caps(conn).get(int(grid_id)) or (DEFAULT_CAP,)


def compute_grid_best(conn, grid_id: int, use: str = "Grazing",
                      coverage: float = 0.90, years=YEARS,
                      top_n: int = TOP_N, max_pct: int = prfopt.MAX_PCT) -> dict:
    """Score all admissible policies for one grid; return the prf_opt_best row.

    Normalized per $1 protection (protection=1.0, round_cents=False,
    sentinel_net=None -- see module docstring).  Raises SweepSkip when the grid
    lacks rates for the use/coverage or complete index years.
    """
    matrix = prfdata.indices_matrix(grid_id, conn)
    missing = [y for y in years if len(matrix.get(y, {})) < len(prfopt.INTERVALS)]
    if not matrix:
        raise SweepSkip("no index data in prf_grid_index")
    if missing:
        raise SweepSkip(f"incomplete index years: {missing}")

    rates = prfdata.rates_for(grid_id, use, coverage, conn)
    if not rates:
        raise SweepSkip(f"no {use} rates at coverage {coverage:.2f}")

    sched = prfdata.subsidy_schedule(conn)
    subsidy = next((s for c, s in sched.items() if abs(c - coverage) < 1e-6), None)
    if subsidy is None:
        subsidy = prfdata.SUBSIDY_SCHEDULE.get(round(coverage, 2))
    if subsidy is None:
        raise SweepSkip(f"no subsidy factor for coverage {coverage:.2f}")

    # prfdata stores indices as decimal percent-of-normal (1.0 = normal); the
    # engine's trigger is expected_index * coverage on base 100.  Convert
    # explicitly (deterministic -- prfopt.simulate()'s peak<5 heuristic is for
    # unknown loaders; here the semantics are documented).
    idx100: dict[str, dict[int, float]] = {}
    for y in years:
        for iv, v in matrix[y].items():
            idx100.setdefault(iv, {})[y] = v * 100.0

    nets, yrs = prfopt.interval_year_nets(
        idx100, rates, subsidy, coverage_level=coverage, years=list(years),
        protection=1.0, round_cents=False, sentinel_net=None)
    usable = [p for p in _policies(max_pct) if all(iv in nets for iv in p[0])]
    if not usable:
        raise SweepSkip(
            f"only {len(rates)} rated interval(s); no admissible 2-interval policy")
    df = prfopt.score_policies(usable, nets)

    by_win = prfopt.rank_by_win_rate(df, top_n)
    by_net = prfopt.rank_by_avg_net_return(df, top_n)
    w0, n0 = by_win.iloc[0], by_net.iloc[0]
    win_combo = list(ast.literal_eval(w0["combinations"]))
    win_props = list(ast.literal_eval(w0["proportions"]))
    net_combo = list(ast.literal_eval(n0["combinations"]))
    net_props = list(ast.literal_eval(n0["proportions"]))
    return {
        "grid_id": int(grid_id),
        "intended_use": use,
        "coverage_level": float(coverage),
        "max_pct": int(max_pct),
        "year_min": int(min(yrs)),
        "year_max": int(max(yrs)),
        "n_policies": int(len(df)),
        "best_win_rate": float(w0["win rate"]),
        "best_win_combo": json.dumps(win_combo),
        "best_win_props": json.dumps(win_props),
        "best_win_avg_net": float(w0["average_net_return"]),
        "best_net": float(n0["average_net_return"]),
        "best_net_combo": json.dumps(net_combo),
        "best_net_props": json.dumps(net_props),
        "best_net_win_rate": float(n0["win rate"]),
        "median_net": float(df["average_net_return"].median()),
        "pct_positive": float((df["average_net_return"] > 0).mean()),
        # Weighted premium rate for each winner, from the SAME `rates` the scoring used --
        # so the app can turn a stored allocation into premium (and agent commission) per
        # acre without shipping the 2.1M-row prf_grid_rate table.
        "best_win_rate_sum": rate_sum(win_combo, win_props, rates),
        "best_net_rate_sum": rate_sum(net_combo, net_props, rates),
        "top_json": json.dumps({
            "by_win_rate": [_policy_entry(r) for _, r in by_win.iterrows()],
            "by_avg_net": [_policy_entry(r) for _, r in by_net.iterrows()],
        }),
    }


# ---------------------------------------------------------------------------
# DB writes (idempotent upserts; this module owns these two tables)
# ---------------------------------------------------------------------------

def upsert_best(conn, row: dict, source: str = "prfsweep") -> None:
    conn.execute(
        """INSERT INTO prf_opt_best
             (grid_id, intended_use, coverage_level, max_pct, year_min, year_max,
              n_policies, best_win_rate, best_win_combo, best_win_props,
              best_win_avg_net, best_net, best_net_combo, best_net_props,
              best_net_win_rate, median_net, pct_positive,
              best_win_rate_sum, best_net_rate_sum, top_json,
              source, fetched_at)
           VALUES (:grid_id, :intended_use, :coverage_level, :max_pct, :year_min,
                   :year_max, :n_policies, :best_win_rate, :best_win_combo,
                   :best_win_props, :best_win_avg_net, :best_net,
                   :best_net_combo, :best_net_props, :best_net_win_rate,
                   :median_net, :pct_positive,
                   :best_win_rate_sum, :best_net_rate_sum,
                   :top_json, :source, :fetched_at)
           ON CONFLICT(grid_id, intended_use, coverage_level, max_pct) DO UPDATE SET
             year_min=excluded.year_min, year_max=excluded.year_max,
             n_policies=excluded.n_policies,
             best_win_rate=excluded.best_win_rate,
             best_win_combo=excluded.best_win_combo,
             best_win_props=excluded.best_win_props,
             best_win_avg_net=excluded.best_win_avg_net,
             best_net=excluded.best_net,
             best_net_combo=excluded.best_net_combo,
             best_net_props=excluded.best_net_props,
             best_net_win_rate=excluded.best_net_win_rate,
             median_net=excluded.median_net,
             pct_positive=excluded.pct_positive,
             best_win_rate_sum=excluded.best_win_rate_sum,
             best_net_rate_sum=excluded.best_net_rate_sum,
             top_json=excluded.top_json,
             source=excluded.source, fetched_at=excluded.fetched_at""",
        # Rate sums default to None so a row built by an older caller (or a grid whose
        # rates are incomplete) still writes — NULL means "not known", not zero.
        {"best_win_rate_sum": None, "best_net_rate_sum": None,
         **row, "source": source, "fetched_at": _now_iso()})
    conn.commit()


def upsert_grid_counties(conn, rows, source: str) -> int:
    conn.executemany(
        """INSERT INTO prf_grid_county (grid_id, state, county_fips, county_name, source)
           VALUES (?,?,?,?,?)
           ON CONFLICT(grid_id, county_fips) DO UPDATE SET
             state=excluded.state, county_name=excluded.county_name,
             source=excluded.source""",
        [(g, st, fips, name, source) for g, st, fips, name in rows])
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def sweep(conn, state: str = "ID", use: str = "Grazing", coverage: float = 0.90,
          limit: int | None = None, force: bool = False, delay: float = 0.5,
          adm_dir: Path | None = None, cfg: config.Config | None = None,
          client=None, log=print) -> dict:
    """Sweep every PRF grid touching `state` for `use` at `coverage`.

    Fetches missing grid data via prfdata.ensure_grid (throttled, disk-cached),
    scores with the prfopt engine, and upserts prf_opt_best + prf_grid_county.
    Resumable: grids already in prf_opt_best are skipped unless force.
    """
    cfg = cfg or config.load()
    grids = list_state_grids(state, use, adm_dir, cfg.reinsurance_year)
    if limit:
        grids = grids[:limit]
    log(f"{state} {use}: {len(grids)} PRF grids listed from ADM A00810 "
        f"(RY{cfg.reinsurance_year})")

    n_county = upsert_grid_counties(
        conn, grid_county_rows(grids, use, adm_dir, cfg.reinsurance_year),
        source=f"adm_{cfg.reinsurance_year}")
    log(f"prf_grid_county: upserted {n_county} grid-county rows")

    done: set[int] = set()
    if not force:
        done = {r[0] for r in conn.execute(
            "SELECT grid_id FROM prf_opt_best WHERE intended_use = ? "
            "AND ABS(coverage_level - ?) < 1e-9", (use, coverage))}

    swept, resumed = 0, 0
    skipped: dict[int, str] = {}
    t0 = time.monotonic()
    for i, gid in enumerate(grids, 1):
        if gid in done:
            resumed += 1
        else:
            try:
                if client is None:
                    client = http.Client(cfg, conn)
                summary = prfdata.ensure_grid(gid, conn, cfg=cfg, client=client,
                                              use=use, force=False)
                for cap in caps_for(conn, gid):
                    row = compute_grid_best(conn, gid, use, coverage, max_pct=cap)
                    upsert_best(conn, row, source=f"prfsweep_{cfg.reinsurance_year}")
                swept += 1
                if delay and ("index_rows_fetched" in summary
                              or "rate_rows_fetched" in summary):
                    time.sleep(delay)  # modest extra gap between fetched grids
            except SweepSkip as e:
                skipped[gid] = str(e)
                log(f"  grid {gid}: SKIPPED - {e}")
            except Exception as e:  # network/API failure: record, keep going
                skipped[gid] = f"{type(e).__name__}: {e}"
                log(f"  grid {gid}: ERROR - {skipped[gid]}")
        if i % 25 == 0 or i == len(grids):
            el = time.monotonic() - t0
            log(f"[{i}/{len(grids)}] swept={swept} resumed={resumed} "
                f"skipped={len(skipped)} elapsed={el/60:.1f}m")
    return {"state": state, "use": use, "coverage": coverage,
            "grids": len(grids), "swept": swept, "resumed": resumed,
            "skipped": skipped, "grid_county_rows": n_county,
            "elapsed_s": time.monotonic() - t0}


def bulk_grids(conn, state: str | None = None) -> list[int]:
    """Grid ids to score in bulk mode, from the already-loaded grid->county map.

    Bulk mode never touches the network: src/prfbulk.py has already populated
    prf_grid_index (the VI_RI national file) and prf_grid_county/prf_grid_rate
    (the ADM chain), so the grid roster comes straight from the DB.
    """
    if state:
        rows = conn.execute(
            "SELECT DISTINCT grid_id FROM prf_grid_county WHERE state = ? "
            "ORDER BY grid_id", (state.upper(),))
    else:
        rows = conn.execute(
            "SELECT DISTINCT grid_id FROM prf_grid_county ORDER BY grid_id")
    return [r[0] for r in rows]


def bulk_grid_states(conn, state: str | None = None) -> dict[int, str]:
    """{grid_id: 'ID'} -- the alphabetically first state each grid touches.

    Only for progress reporting and the per-state tally: a grid straddling a state
    line is scored ONCE (its result is state-independent) and booked to one state.
    """
    sql = "SELECT grid_id, MIN(state) FROM prf_grid_county"
    args: tuple = ()
    if state:
        sql += " WHERE state = ?"
        args = (state.upper(),)
    sql += " GROUP BY grid_id"
    return {g: st for g, st in conn.execute(sql, args)}


# --- worker plumbing for --jobs (spawn-safe: each child opens its own DB) ---

_W: dict = {}


def _worker_init(db_path, use, coverage) -> None:
    # One library thread per worker: the engine is a tight Python loop, so BLAS/OMP
    # threads would only fight the other workers for the same cores.
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    _W["conn"] = db.connect(db_path)
    _W["use"], _W["coverage"] = use, coverage
    _policies()          # warm the default-cap list once per worker


def _score_one(conn, grid_id, use, coverage):
    """(grid_id, row_or_None, error_or_None) -- never raises, so one bad grid
    can neither abort a 13,000-grid run nor kill a worker pool."""
    try:
        rows = [compute_grid_best(conn, grid_id, use, coverage, max_pct=cap)
                for cap in caps_for(conn, grid_id)]
        return grid_id, rows, None
    except SweepSkip as e:
        return grid_id, None, str(e)
    except Exception as e:
        return grid_id, None, f"{type(e).__name__}: {e}"


def _worker_score(grid_id: int):
    return _score_one(_W["conn"], grid_id, _W["use"], _W["coverage"])


def sweep_bulk(conn, state: str | None = None, use: str = "Grazing",
               coverage: float = 0.90, limit: int | None = None,
               force: bool = False, changed_only: bool = False, jobs: int = 1,
               keep_hashes: bool = False,
               db_path=None, cfg: config.Config | None = None, log=print) -> dict:
    """Score grids straight from the DB — zero network calls.

    The nationwide path.  Requires src/prfbulk.py to have loaded the national
    index/rate/county tables first.  Resumable (grids already in prf_opt_best
    are skipped unless force); `changed_only` narrows to grids whose 2006-2024
    index window actually moved since the last run (the monthly case, where
    RMA's release usually touches only the current year and nothing needs
    re-scoring).

    Scoring is pure CPU (~0.7 s/grid), so `jobs > 1` fans the grids out over
    worker processes that each open their own read connection; the parent stays
    the only writer, committing per grid, so the run remains resumable.

    Successfully scored grids get their index-window fingerprint written to
    prf_index_hash, which is what makes the NEXT --changed-only run cheap.
    """
    cfg = cfg or config.load()
    # The parent commits once per grid. Under the default rollback journal with
    # synchronous=FULL that is a full fsync against a >1 GB file EVERY grid, and the
    # cost climbs as prf_opt_best grows -- measured 47 -> 80 min per 13,462-grid combo
    # over the first five. WAL (set on the file) plus NORMAL here keeps commits cheap
    # and flat. NORMAL only risks the last commits on an OS crash/power loss, never on
    # a process kill, and the sweep is resumable either way.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    grids = bulk_grids(conn, state)
    scope = state or "CONUS"
    state_of = bulk_grid_states(conn, state)
    listed = len(grids)

    if changed_only:
        changed = set(prfbulk.changed_grids(conn, grids))
        grids = [g for g in grids if g in changed]
        log(f"{scope} {use}: {len(grids)} of {listed} grids have a changed "
            f"(or never hashed) 2006-2024 window")
    else:
        log(f"{scope} {use}: {listed} PRF grids from prf_grid_county")
    if limit:
        grids = grids[:limit]

    done: set[int] = set()
    if not force:
        done = {r[0] for r in conn.execute(
            "SELECT grid_id FROM prf_opt_best WHERE intended_use = ? "
            "AND ABS(coverage_level - ?) < 1e-9", (use, coverage))}
    todo = [g for g in grids if g not in done]
    resumed = len(grids) - len(todo)

    per_state: dict[str, dict] = {}
    for g in grids:
        st = state_of.get(g, "??")
        per_state.setdefault(st, {"grids": 0, "swept": 0, "skipped": 0})
        per_state[st]["grids"] += 1

    log(f"{len(todo)} to score, {resumed} already in prf_opt_best; "
        f"estimated {len(todo) * 0.7 / 60:.0f} min at 0.7 s/grid "
        f"(~{len(todo) * 0.7 / 60 / max(jobs, 1):.0f} min with jobs={jobs})")

    swept = 0
    scored: list[int] = []
    skipped: dict[int, str] = {}
    t0 = time.monotonic()

    def _record(gid, rows, err):
        # `rows` is a LIST: one prf_opt_best row per distinct actuarial cap the grid's
        # counties are under. Usually length 1; 617 grids straddle a cap boundary and get two
        # or three. The grid still counts as swept ONCE — the counter tracks grids, not rows.
        nonlocal swept
        st = state_of.get(gid, "??")
        if err is not None:
            skipped[gid] = err
            per_state[st]["skipped"] += 1
            return
        for row in rows:
            upsert_best(conn, row, source=f"prfbulk_{cfg.reinsurance_year}")
        scored.append(gid)
        per_state[st]["swept"] += 1
        swept += 1

    def _progress(i):
        el = time.monotonic() - t0
        rate = i / el if el else 0
        eta = (len(todo) - i) / rate / 60 if rate else 0
        by_st = " ".join(f"{s}:{d['swept']}" for s, d in sorted(per_state.items())
                         if d["swept"] or d["skipped"])
        log(f"[{i}/{len(todo)}] swept={swept} skipped={len(skipped)} "
            f"elapsed={el/60:.1f}m eta={eta:.1f}m | {by_st}")

    if jobs and jobs > 1 and todo:
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        with ctx.Pool(jobs, initializer=_worker_init,
                      initargs=(str(db_path or config.DB_PATH), use, coverage)) as pool:
            for i, (gid, row, err) in enumerate(
                    pool.imap_unordered(_worker_score, todo, chunksize=8), 1):
                _record(gid, row, err)
                if i % 250 == 0 or i == len(todo):
                    _progress(i)
    else:
        for i, gid in enumerate(todo, 1):
            _record(*_score_one(conn, gid, use, coverage))
            if i % 250 == 0 or i == len(todo):
                _progress(i)

    # Hashes are keyed by GRID ONLY (no use/coverage), so writing them here would tell
    # the NEXT combo in a multi-combo run that nothing changed — silently skipping 14 of
    # the 15 use x coverage combos while looking successful. keep_hashes lets a caller
    # sweep every combo off one changed-grid list, then stamp the hashes once at the end
    # (`python -m src.prfbulk --hashes`). See scripts/monthly_update.sh step 3.
    if scored and not keep_hashes:
        prfbulk.update_hashes(conn, scored)

    return {"state": scope, "use": use, "coverage": coverage,
            "grids": len(grids), "swept": swept, "resumed": resumed,
            "skipped": skipped, "per_state": per_state, "grid_county_rows": 0,
            "elapsed_s": time.monotonic() - t0}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sweep the PRF optimizer over PRF grids (bulk or per-state).")
    ap.add_argument("--state", default=None,
                    help="2-letter state, e.g. ID (required unless --bulk)")
    ap.add_argument("--use", default="Grazing",
                    choices=sorted(prfdata.USE_PARAMS))
    ap.add_argument("--coverage", type=float, default=0.90)
    ap.add_argument("--bulk", action="store_true",
                    help="score from the loaded national tables; NO network "
                         "calls (run `python -m src.prfbulk` first). Omit "
                         "--state to sweep all of CONUS.")
    ap.add_argument("--keep-hashes", action="store_true",
                    help="bulk mode: do NOT stamp prf_index_hash after scoring. Use when "
                         "sweeping several use x coverage combos off one changed-grid "
                         "list; stamp once at the end with `python -m src.prfbulk --hashes`.")
    ap.add_argument("--changed-only", action="store_true",
                    help="bulk mode: only grids whose 2006-2024 index window "
                         "changed since the last run (the monthly path)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="bulk mode: worker processes (scoring is CPU-bound; "
                         "the parent stays the only DB writer)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N grids (testing)")
    ap.add_argument("--resume", action="store_true",
                    help="skip grids already in prf_opt_best (the default; "
                         "flag kept for explicitness)")
    ap.add_argument("--force", action="store_true",
                    help="recompute grids already in prf_opt_best")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="extra seconds between grids that hit the network "
                         "(prfdata's per-host throttle also applies)")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    if not args.bulk and not args.state:
        ap.error("--state is required unless --bulk is given")

    # Progress must be readable while an hour-long run is still going, so flush every
    # line: nohup/launchd redirect stdout to a file, where Python would otherwise
    # block-buffer and show nothing until the run ends.
    def say(msg):
        print(msg, flush=True)

    conn = db.connect(args.db)
    db.init_db(conn)
    try:
        if args.bulk:
            res = sweep_bulk(conn, state=args.state, use=args.use,
                             coverage=args.coverage, limit=args.limit,
                             force=args.force, changed_only=args.changed_only,
                             keep_hashes=args.keep_hashes,
                             jobs=args.jobs, db_path=args.db, log=say)
        else:
            res = sweep(conn, state=args.state, use=args.use,
                        coverage=args.coverage, limit=args.limit,
                        force=args.force, delay=args.delay, log=say)
    finally:
        conn.close()

    print(f"\ndone in {res['elapsed_s']/60:.1f} min: {res['grids']} grids, "
          f"{res['swept']} swept, {res['resumed']} already done, "
          f"{len(res['skipped'])} skipped")
    if res["skipped"]:
        reasons: dict[str, int] = {}
        for why in res["skipped"].values():
            key = why.split(":")[0][:60]
            reasons[key] = reasons.get(key, 0) + 1
        print("skip reasons:")
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {why}")
    if res.get("per_state"):
        print("per state (grids / swept / skipped):")
        for st, d in sorted(res["per_state"].items()):
            print(f"  {st}  {d['grids']:5d} {d['swept']:5d} {d['skipped']:5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
