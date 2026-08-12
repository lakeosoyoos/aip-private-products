"""
LRP Savings Signal — Feeder Cattle
====================================
One question: how much am I saving vs buying this protection on CME today?

  LRP producer premium:   $X.XX/cwt   ($XX,XXX total)
  CME equivalent put:     $Y.YY/cwt   ($YY,YYY total)
  You save:               $Z.ZZ/cwt   ($ZZ,ZZZ today)

  Normal day savings:     $N.NN/cwt
  Today vs normal:        Kx richer

The gap = CME put price − LRP producer premium. It has two components:
  1. Federal subsidy (always there — the floor)
  2. Vol discount (variable — when RMA vol < CME vol, gap widens)

When the gap is anomalously wide vs its own history → strong buy signal.

Timing:
  ~2:00 PM CT   CME cattle options settle
  ~3:30 PM CT   RMA posts new LRP prices
  ~4:00 PM CT   Run this script — decision: buy tonight or pass
  8:25 AM CT    Window closes, prices expire
  → ~17-hour window to act. LRP suspended on Cattle on Feed report days.

Usage:
    python lrp_signal.py
    python lrp_signal.py --commodity fed
    python lrp_signal.py --lookback 60
    python lrp_signal.py --head 1000
    python lrp_signal.py --output chart
    python lrp_signal.py --output all

Requirements:
    pip install requests pandas scipy matplotlib seaborn tabulate
"""

import argparse
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors
import seaborn as sns
from scipy.stats import norm
from scipy.optimize import brentq
from tabulate import tabulate

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

BARCHART_API_KEY = os.environ.get("BARCHART_API_KEY", "YOUR_BARCHART_API_KEY")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lrp_cache")
# Immutable record of each day's gap, priced with THAT day's curve.
# Richness reads this file and never re-prices history.
GAP_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "lrp_gap_history.csv")

# Set LRP_HISTORY_READONLY=1 to make every gap-history write a no-op.
#
# WHY THIS EXISTS: the LRP page records a snapshot and backfills history as a SIDE EFFECT of
# rendering. That is correct in the app and wrong everywhere else — a headless render under
# pytest grew this file from 1,954 to 5,515 rows, silently moving the baseline that the BUY
# threshold is calibrated against. A test run must not be able to change a production
# calibration. tests/conftest.py sets this for the whole suite.
#
# It guards the WRITE, not the callers, so a new caller cannot forget it.
def _history_readonly() -> bool:
    return os.environ.get("LRP_HISTORY_READONLY", "").strip().lower() in {"1", "true", "yes"}

TENORS_WEEKS    = [13, 17, 21, 26, 30, 34, 39, 43, 47, 52]
# The twelve levels RMA actually publishes in the daily livestock rate file. Verified
# against lrp_cache/lrp_feeder_2026-07-15.csv, whose distinct coverage_level values are
# exactly this list. 0.70 is NOT offered (LRP's floor is 70% of expected ending value only
# in the sense that 0.75 is the lowest published level), and the fine levels 0.875, 0.925
# and 0.96-0.99 exist but were previously absent, so those cells were never priced.
COVERAGE_LEVELS = [0.75, 0.80, 0.85, 0.875, 0.90, 0.925, 0.95, 0.96, 0.97, 0.98, 0.99, 1.00]

# RMA Livestock Rate/Subsidy table: 95.00-100% -> 35%, 90.00-94.99% -> 40%,
# 85.00-89.99% -> 45%, 80.00-84.99% -> 50%, 70.00-79.99% -> 55%.
# Keys are the INCLUSIVE LOWER bound of each band (get_subsidy_rate walks them descending).
# The previous table was shifted one band high (it paid 0.95 a 40% subsidy and 0.80 a 55%),
# which understated producer premium at every level from 80% to 99%.
SUBSIDY_SCHEDULE = {0.95: 0.35, 0.90: 0.40, 0.85: 0.45,
                    0.80: 0.50, 0.00: 0.55}

CME_MONTH_CODES   = {1:"F",2:"G",3:"H",4:"J",5:"K",6:"M",
                     7:"N",8:"Q",9:"U",10:"V",11:"X",12:"Z"}
CME_EXPIRY_MONTHS = {
    "fed":    [2, 4, 6, 8, 10, 12],
    "feeder": [1, 3, 4, 5, 8, 9, 10, 11],
}
CME_FUTURES_PRODUCT_ID = {"fed": 22, "feeder": 34}

RMA_COMMODITY_CODES = {"fed": "0802", "feeder": "0801"}
RMA_TYPE_CODES = {
    "fed":    ["820"],
    "feeder": ["809", "810", "811", "812"],
}

CWT_PER_HEAD = 13  # default, overridable

# ─────────────────────────────────────────────────────────────────────────────
# Black-76
# ─────────────────────────────────────────────────────────────────────────────

def black76_put(F, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - F, 0.0) * math.exp(-r * T)
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return math.exp(-r * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def black76_put_delta(F, K, T, r, sigma):
    """
    Black-76 put delta with respect to the forward F:

        Δ = -e^(-rT) · N(-d1),   d1 = (ln(F/K) + 0.5σ²T) / (σ√T)

    Per 1 cwt of insured value: ranges from 0 (deep OTM, K << F) to
    -e^(-rT) (deep ITM, K >> F), ≈ -0.5·e^(-rT) at the money. This is the
    instantaneous hedge ratio — how many cwt of long price exposure one
    insured cwt offsets today.
    """
    if T <= 0 or sigma <= 0:
        # Expired/degenerate: delta collapses to the exercise indicator
        if F < K:
            return -math.exp(-r * T)
        if F > K:
            return 0.0
        return -0.5 * math.exp(-r * T)
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    return -math.exp(-r * T) * norm.cdf(-d1)


def implied_vol(price, F, K, T, r):
    if T <= 0 or price is None or price <= 0:
        return None
    intrinsic = math.exp(-r * T) * max(K - F, 0.0)
    if price <= intrinsic + 1e-8:
        return None
    try:
        f = lambda s: black76_put(F, K, T, r, s) - price
        if f(1e-4) * f(5.0) > 0:
            return None
        return brentq(f, 1e-4, 5.0, xtol=1e-7, maxiter=200)
    except (ValueError, RuntimeError):
        return None


def get_subsidy_rate(cov):
    for t in sorted(SUBSIDY_SCHEDULE.keys(), reverse=True):
        if cov >= t:
            return SUBSIDY_SCHEDULE[t]
    return 0.35


# ─────────────────────────────────────────────────────────────────────────────
# RMA Data
# ─────────────────────────────────────────────────────────────────────────────

def sales_today():
    """
    RMA sales date "today" in Central Time. The app may run on a UTC
    server (Streamlit Cloud): naive date.today() there rolls to tomorrow
    at 7 PM CT, making the app fetch a not-yet-published rate file every
    evening — precisely during the open sales window.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        return date.today()


def fetch_lrp_current(commodity, use_cache=True):
    """
    The rates a producer can act on RIGHT NOW, as (df, sales_date).

    RMA posts the sales-effective-date-D file ~3:30 PM CT on day D and it
    is purchasable until 8:25 AM CT on D+1. So before 8:25 AM CT the operative
    file is YESTERDAY'S; today's appears mid-afternoon. Between 9 AM and
    ~3:30 PM there are genuinely no live rates (df comes back empty).
    """
    today = sales_today()
    df = fetch_lrp(commodity, today, use_cache=use_cache)
    if not df.empty:
        return df, today
    try:
        from zoneinfo import ZoneInfo
        now_ct = datetime.now(ZoneInfo("America/Chicago"))
    except Exception:
        now_ct = datetime.now()
    # Before the 8:25 AM CT close the live quotes are still YESTERDAY's posting.
    if now_ct.hour * 60 + now_ct.minute < 505:
        yday = today - timedelta(days=1)
        df = fetch_lrp(commodity, yday, use_cache=use_cache)
        if not df.empty:
            return df, yday
    return pd.DataFrame(), today


def fetch_lrp_reference(commodity, max_back=5, use_cache=True):
    """
    Most recent EXPIRED rate file, as (df, sales_date) — for reference
    display during the dead zone (9 AM–3:30 PM CT) and weekends, when
    fetch_lrp_current comes back empty. Walks back up to max_back days.
    Callers must label these rates as expired and must NOT record them
    into the gap history (their live snapshot already exists).
    """
    d = sales_today() - timedelta(days=1)
    for _ in range(max_back):
        df = fetch_lrp(commodity, d, use_cache=use_cache)
        if not df.empty:
            return df, d
        d -= timedelta(days=1)
    return pd.DataFrame(), None


def fetch_lrp(commodity, d=None, use_cache=True):
    if d is None:
        d = sales_today()
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"lrp_{commodity}_{d.isoformat()}.csv")
    if use_cache and os.path.exists(cache):
        return pd.read_csv(cache)
    df = _fetch_lrp_zip(commodity, d)
    if df.empty:
        df = _fetch_lrp_legacy(commodity, d)
    if not df.empty and use_cache:
        df.to_csv(cache, index=False)
    return df


def _fetch_lrp_zip(commodity, d):
    import zipfile, io
    # RMA files daily rates under the REINSURANCE year, which rolls July 1
    # (e.g. 2026-07-16 rates live in /2027/). The calendar-year folder keeps
    # publishing a daily zip after the roll, but without the LrpRate file —
    # so try the reinsurance year first, then the calendar year.
    reins_year = d.year + 1 if d.month >= 7 else d.year
    for year in dict.fromkeys([reins_year, d.year]):
        url = (f"https://pubfs-rma.fpac.usda.gov/pub/References/"
               f"adm_livestock/{year}/"
               f"{year}_ADMLivestockLrp_Daily_{d.strftime('%Y%m%d')}.zip")
        try:
            resp = requests.get(url, timeout=30,
                                headers={"User-Agent": "LRP-Signal/1.0"})
            resp.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            rate_file = next((n for n in z.namelist()
                              if "A00630" in n and "LrpRate" in n), None)
            if not rate_file:
                continue
            with z.open(rate_file) as f:
                content = f.read().decode("utf-8")
            df = _parse_rate_file(content, commodity)
            if not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _fetch_lrp_legacy(commodity, d):
    codes = {"fed": "0070", "feeder": "0050"}
    url = (f"https://pubfs-rma.fpac.usda.gov/pub/References/"
           f"livestock_lrp_lgm/LRP_{codes[commodity]}_{d.strftime('%Y%m%d')}.txt")
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": "LRP-Signal/1.0"})
        resp.raise_for_status()
        return _parse_legacy(resp.text)
    except Exception:
        return pd.DataFrame()


def _parse_rate_file(text, commodity):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return pd.DataFrame()
    header = [h.strip().lower().replace(" ", "_") for h in lines[0].split("|")]
    type_codes = RMA_TYPE_CODES.get(commodity, [])
    commodity_code = RMA_COMMODITY_CODES.get(commodity, "")
    rows, seen = [], set()
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < len(header):
            continue
        rec = dict(zip(header, [p.strip() for p in parts]))
        if commodity_code and rec.get("commodity_code") != commodity_code:
            continue
        if type_codes and rec.get("type_code") not in type_codes:
            continue
        if rec.get("deleted_date", "").strip():
            continue
        try:
            weeks = int(rec["endorsement_length_count"])
            cov_level = float(rec["livestock_coverage_level_percent"])
            cov_price = float(rec["coverage_price"])
            rate = float(rec["livestock_rate"])
            cost_cwt = float(rec["cost_per_cwt_amount"])
            expected = float(rec["expected_ending_value_amount"])
            key = (weeks, round(cov_level, 4))
            if key in seen:
                continue
            seen.add(key)
            # cost_per_cwt_amount is the TOTAL (actuarial) premium per cwt -- RMA's own
            # worked example runs $56,250 insured value x .013990 rate = $787 total, from
            # which a 35% subsidy of $275 leaves the producer $512. Treating cost_cwt as
            # the producer's share (as this parser used to) overstated what the producer
            # actually pays by 1/(1-subsidy). livestock_rate x coverage_price reproduces
            # cost_cwt to rounding, so cost_cwt is used directly as the authoritative value.
            rows.append({"weeks": weeks, "coverage_level": cov_level,
                         "coverage_price": cov_price,
                         "actuarial_prem": cost_cwt,
                         "producer_prem": cost_cwt * (1 - get_subsidy_rate(cov_level)),
                         "expected_value": expected})
        except (ValueError, TypeError, KeyError):
            continue
    return pd.DataFrame(rows)


def _parse_legacy(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return pd.DataFrame()
    delim = "|" if "|" in lines[0] else "\t"
    header, rows = None, []
    for line in lines:
        parts = line.split(delim)
        if header is None:
            header = [p.strip().lower().replace(" ", "_") for p in parts]
            continue
        if len(parts) < len(header):
            continue
        rec = dict(zip(header, [p.strip() for p in parts]))
        try:
            rows.append({"weeks": int(rec["endorsement_length"]),
                         "coverage_level": float(rec["coverage_level"]) / 100,
                         "coverage_price": float(rec["coverage_price"]),
                         "producer_prem": float(rec["producer_premium_per_cwt"]),
                         "actuarial_prem": float(rec["total_premium_per_cwt"]),
                         "expected_value": float(rec["expected_ending_value"])})
        except (ValueError, TypeError, KeyError):
            continue
    return pd.DataFrame(rows)


def fetch_lrp_history(commodity, lookback_days):
    history = {}
    d = sales_today() - timedelta(days=1)
    checked = 0
    print(f"  Loading {lookback_days}-day history...", end="", flush=True)
    while len(history) < lookback_days and checked < lookback_days * 2:
        checked += 1
        if d.weekday() >= 5:
            d -= timedelta(days=1)
            continue
        df = fetch_lrp("feeder", d, use_cache=True)
        if not df.empty:
            history[d] = df
            if len(history) % 10 == 0:
                print(f"{len(history)}..", end="", flush=True)
        d -= timedelta(days=1)
        time.sleep(0.05)
    print(f" {len(history)} days.")
    return history


# ─────────────────────────────────────────────────────────────────────────────
# CME Futures Curve (free, no key)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cme_futures_curve(commodity, trade_date=None):
    """
    Fetch feeder/fed cattle futures curve.
    Priority: CME settlement API → Yahoo Finance fallback.
    """
    pid = CME_FUTURES_PRODUCT_ID.get(commodity)

    # Try CME first
    if pid is not None:
        if trade_date is None:
            for offset in range(5):
                d = date.today() - timedelta(days=offset)
                if d.weekday() >= 5:
                    continue
                curve = _cme_settle(pid, d)
                if curve:
                    return curve
        else:
            curve = _cme_settle(pid, trade_date)
            if curve:
                return curve

    # Fallback: Yahoo Finance
    curve = _yahoo_futures_curve(commodity)
    if curve:
        return curve
    return {}


def _cme_settle(pid, d):
    url = (f"https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/"
           f"Settlements/{pid}/FUT?tradeDate={d.strftime('%m/%d/%Y')}")
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/json"
        }, timeout=15)
        resp.raise_for_status()
        curve = {}
        for row in resp.json().get("settlements", []):
            month = row.get("month", "").strip()
            settle = row.get("settle", "").strip()
            if not month or not settle or settle == "-":
                continue
            try:
                curve[month] = float(settle.replace(",", ""))
            except ValueError:
                continue
        return curve
    except Exception:
        return {}


# Yahoo Finance symbol mapping for feeder/fed cattle futures
# Feeder: GF + month code + 2-digit year + .CME
# Fed (Live Cattle): LE + month code + 2-digit year + .CME
_YAHOO_ROOT = {"fed": "LE", "feeder": "GF"}
_YAHOO_MONTHS = {
    "fed":    {2: "G", 4: "J", 6: "M", 8: "Q", 10: "V", 12: "Z"},
    "feeder": {1: "F", 3: "H", 4: "J", 5: "K", 8: "Q", 9: "U", 10: "V", 11: "X"},
}
_MONTH_ABBR = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",
               7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}


def _yahoo_futures_curve(commodity):
    """
    Fetch futures curve from Yahoo Finance (free, no key).
    Returns {month_str: price} in same format as CME settle.
    """
    root = _YAHOO_ROOT.get(commodity)
    months = _YAHOO_MONTHS.get(commodity)
    if not root or not months:
        return {}

    today = date.today()
    curve = {}
    # Scan next 18 months of contract months
    for offset_months in range(0, 19):
        m = today.month + offset_months
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        if m not in months:
            continue
        code = months[m]
        yr2 = str(y)[-2:]
        sym = f"{root}{code}{yr2}.CME"
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                   f"?range=1d&interval=1d")
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue
            price = result[0].get("meta", {}).get("regularMarketPrice")
            if price and price > 0:
                month_str = f"{_MONTH_ABBR[m]} {yr2}"
                curve[month_str] = float(price)
        except Exception:
            continue
        time.sleep(0.05)  # gentle rate limit

    if curve:
        print(f"[Yahoo] {len(curve)} contract months loaded")
    return curve


def cme_month_to_date(month_str):
    try:
        parts = month_str.strip().split()
        month_map = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
                     "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
        m = month_map[parts[0].upper()]
        y = 2000 + int(parts[1]) if len(parts[1]) == 2 else int(parts[1])
        return date(y, m, 15)
    except (KeyError, ValueError, IndexError):
        return None


def interpolate_forward(curve, target_date):
    if not curve:
        return None
    points = sorted([(cme_month_to_date(m), p) for m, p in curve.items()
                     if cme_month_to_date(m)], key=lambda x: x[0])
    if not points:
        return None
    if target_date <= points[0][0]:
        return points[0][1]
    if target_date >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        d0, p0 = points[i]
        d1, p1 = points[i + 1]
        if d0 <= target_date <= d1:
            frac = (target_date - d0).days / max((d1 - d0).days, 1)
            return p0 + frac * (p1 - p0)
    return points[-1][1]


# ─────────────────────────────────────────────────────────────────────────────
# CME Options (Barchart or Black-76 fallback)
# ─────────────────────────────────────────────────────────────────────────────

def get_cme_source_label(futures_curve):
    """Label for what CME data source we're using."""
    if BARCHART_API_KEY != "YOUR_BARCHART_API_KEY":
        return "Barchart"
    return "Yahoo curve + B76" if futures_curve else "B76 synthetic"


# ─────────────────────────────────────────────────────────────────────────────
# Core: build the savings grid
# ─────────────────────────────────────────────────────────────────────────────

def _cell_sigma(F, K, T, base_vol):
    """
    The vol used for a grid cell — base vol with a mild term structure
    plus a put skew (OTM puts, K < F, trade at higher vol). Factored out
    so price (cme_put_price) and delta (black76_put_delta) always use the
    SAME sigma for the same cell.
    """
    moneyness = math.log(K / F)
    # Skew: OTM puts (K < F, negative moneyness) get higher vol
    return base_vol * (1 + 0.002 * (T * 52)) + max(0.0, -moneyness * 0.15)


def cme_put_price(F, K, T, r, base_vol):
    """
    Price a CME-equivalent put using Black-76.
    Same strike K and forward F as the LRP policy — apples to apples.
    """
    if T <= 0 or K <= 0 or F <= 0:
        return max(K - F, 0.0)
    return black76_put(F, K, T, r, _cell_sigma(F, K, T, base_vol))


def build_grid(lrp_df, futures_curve, r, base_vol, asof=None):
    """
    For every (tenor, coverage) cell:
      - K = RMA's actual coverage_price (the policy strike)
      - F = CME futures interpolated to endorsement end date
      - CME put = Black-76(F, K, T, r, sigma)  ← same K, same F as LRP
      - gap = CME put − LRP producer premium    (total savings $/cwt)
      - gap_pct = gap / coverage_price           (normalized to underlying)

    asof: sales date the grid is priced for (default today, Central Time).
    Pass the historical date when reconstructing past days so tenor end
    dates line up with that day's curve.
    """
    today = asof if asof is not None else sales_today()
    rows = []

    # Get RMA's expected value as reference for estimating when no live data
    rma_expected = None
    if not lrp_df.empty and "expected_value" in lrp_df.columns:
        rma_expected = float(lrp_df["expected_value"].iloc[0])

    for weeks in TENORS_WEEKS:
        T = weeks / 52.0
        target = today + timedelta(weeks=weeks)

        # Forward: CME futures curve interpolated to endorsement end
        F = interpolate_forward(futures_curve, target) if futures_curve else None
        if F is None and not lrp_df.empty:
            # Per-tenor fallback: RMA's expected ending value for THIS tenor
            # (derived from CME settlements per RMA methodology)
            ev_w = lrp_df.loc[lrp_df["weeks"] == weeks, "expected_value"]
            if not ev_w.empty:
                F = float(ev_w.mean())
        if F is None and rma_expected:
            F = rma_expected  # fallback: use RMA's own expected value
        if F is None:
            F = 350.0  # last resort

        for cov in COVERAGE_LEVELS:
            subsidy_rate = get_subsidy_rate(cov)

            # ── LRP side: use actual RMA data ──
            if not lrp_df.empty:
                # Exact-level match. RMA publishes levels as close together as 0.01 apart
                # (0.95/0.96/0.97/0.98/0.99), so the old +/-0.025 window straddled up to
                # five of them and iloc[0] silently priced whichever sorted first.
                mask = ((lrp_df["weeks"] == weeks) &
                        ((lrp_df["coverage_level"] - cov).abs() < 0.0025))
                matched = lrp_df[mask]
            else:
                matched = pd.DataFrame()

            if not matched.empty:
                prod_prem = float(matched.iloc[0]["producer_prem"])
                cov_price = float(matched.iloc[0]["coverage_price"])
                # Both premiums come straight from RMA now: actuarial_prem is the published
                # cost_per_cwt_amount and producer_prem is that net of subsidy. The old
                # code grossed prod_prem UP by 1/(1-subsidy) on the belief that RMA's
                # published figure was already net -- it is not, so that compounded the
                # error rather than correcting it.
                act_prem = float(matched.iloc[0]["actuarial_prem"])
                live = True
            else:
                # Estimate: use RMA expected value × coverage as strike
                est_base = rma_expected if rma_expected else F
                cov_price = est_base * cov
                m = math.log(cov_price / F) if F > 0 else 0
                sigma_est = base_vol * (1 + 0.002 * weeks) + max(0.0, -m * 0.08)
                raw_put = black76_put(F, cov_price, T, r, sigma_est)
                load = 1.09 + 0.03 * (1 - cov)
                act_prem = raw_put * load
                prod_prem = act_prem * (1 - subsidy_rate)
                live = False

            # ── CME side: price put with SAME strike (coverage_price) and
            #    SAME forward (F) — the only difference is the vol/premium ──
            cme_px = cme_put_price(F, cov_price, T, r, base_vol)

            # ── Delta: hedge ratio of the LRP put per insured cwt.
            #    Same sigma as the CME put so price and delta agree. ──
            if T > 0 and cov_price > 0 and F > 0:
                sigma_cell = _cell_sigma(F, cov_price, T, base_vol)
            else:
                sigma_cell = 0.0
            put_delta = black76_put_delta(F, cov_price, T, r, sigma_cell)
            # cwt to insure for 1 cwt-equivalent of short delta = 1/|Δ|.
            # Deep OTM cells have |Δ| ≈ 0 → effectively unhedgeable.
            if abs(put_delta) >= 1e-4:
                hedge_cwt_per_delta = round(1.0 / abs(put_delta), 2)
            else:
                hedge_cwt_per_delta = None

            # ── The signal ──
            gap = cme_px - prod_prem
            subsidy_gap = act_prem - prod_prem     # always positive (subsidy)
            vol_gap = cme_px - act_prem             # positive = RMA vol cheap

            # Normalize to underlying so 70% and 100% are comparable
            gap_pct = gap / cov_price if cov_price > 0 else 0

            # ── RETURN PER PRODUCER DOLLAR ──
            #
            # Everything above is a COST comparison: "LRP is $X/cwt cheaper than the CME put".
            # That only speaks to someone who already wanted the hedge. These two say what a
            # dollar of the producer's own money buys, which is the question the rest of this
            # project asks of every product (PRF per $1 protection, DRP per $1 liability).
            #
            #   ret_sub  RMA's own valuation. act_prem is the unsubsidised premium, i.e. what
            #            RMA reckons the protection is worth, so this is 1/(1-subsidy) and is
            #            always > 1. It is what the subsidy alone hands you IF RMA prices fair.
            #
            #   ret_mkt  the market's valuation. cme_put is what the equivalent protection
            #            actually costs, so this is the honest one — and it can be BELOW 1,
            #            because RMA's rate can exceed the market's and the subsidy does not
            #            always cover the difference.
            #
            # The two disagreeing IS the vol_gap above, expressed as a multiple instead of a
            # difference. Neither is a forecast: measured LRP experience nationally is 0.66x
            # (Summary of Business, plan 81), which is below both.
            ret_sub = (act_prem / prod_prem) if prod_prem > 0 else None
            ret_mkt = (cme_px / prod_prem) if prod_prem > 0 else None

            rows.append({
                "weeks": weeks,
                "coverage_level": cov,
                "coverage_pct": f"{int(cov * 100)}%",
                "coverage_price": round(cov_price, 2),
                "F": round(F, 2),
                "producer_prem": round(prod_prem, 4),
                "actuarial_prem": round(act_prem, 4),
                "cme_put": round(cme_px, 4),
                "gap": round(gap, 4),
                "gap_pct": round(gap_pct * 100, 3),  # as percentage
                "subsidy_gap": round(subsidy_gap, 4),
                "vol_gap": round(vol_gap, 4),
                "ret_sub": None if ret_sub is None else round(ret_sub, 4),
                "ret_mkt": None if ret_mkt is None else round(ret_mkt, 4),
                "put_delta": round(put_delta, 4),
                "hedge_cwt_per_delta": hedge_cwt_per_delta,
                "live": live,
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Short-delta hedge sizing
# ─────────────────────────────────────────────────────────────────────────────

def size_delta_hedge(grid, head, ratio):
    """
    Size an LRP purchase to hit a target short-delta ratio.

    A producer with `head` cattle is LONG exposure_cwt = head × CWT_PER_HEAD
    cwt of price (+1 delta per cwt). Each insured cwt of LRP adds put_delta
    (negative) of delta. To offset a fraction `ratio` of the herd's delta:

        insured_cwt = ratio × exposure_cwt / |Δ|

    Because |Δ| < 1, you always insure MORE cwt than you are hedging in
    delta terms — and RMA will not insure more than you own, so a cell is
    feasible only when insured_cwt ≤ exposure_cwt, i.e. |Δ| ≥ ratio.

    RMA endorsements are whole-head, so sizing rounds UP to the next head
    and re-derives cwt/premium from that.

    Returns one row per grid cell: weeks, coverage_pct, coverage_price,
    put_delta, insured_cwt, insured_head, pct_of_herd, premium_cost,
    feasible, achievable_ratio (= |Δ|, the max short-delta ratio the cell
    can deliver insuring 100% of the herd — uncapped).
    """
    exposure_cwt = head * CWT_PER_HEAD
    target_delta_cwt = ratio * exposure_cwt
    rows = []
    for _, row in grid.iterrows():
        delta = row["put_delta"]
        abs_d = abs(float(delta)) if pd.notna(delta) else 0.0
        if abs_d >= 1e-4:
            raw_cwt = target_delta_cwt / abs_d
            insured_head = int(math.ceil(raw_cwt / CWT_PER_HEAD))
            insured_cwt = insured_head * CWT_PER_HEAD
            pct_of_herd = insured_cwt / exposure_cwt
            premium_cost = insured_cwt * float(row["producer_prem"])
            feasible = insured_head <= head
        else:
            # Delta ≈ 0: no finite amount of this cell moves the needle
            insured_cwt = None
            insured_head = None
            pct_of_herd = None
            premium_cost = None
            feasible = False
        rows.append({
            "weeks": row["weeks"],
            "coverage_pct": row["coverage_pct"],
            "coverage_price": row["coverage_price"],
            "put_delta": delta,
            "insured_cwt": round(insured_cwt, 1)
                if insured_cwt is not None else None,
            "insured_head": insured_head,
            "pct_of_herd": round(pct_of_herd * 100, 1)
                if pct_of_herd is not None else None,
            "premium_cost": round(premium_cost, 0)
                if premium_cost is not None else None,
            "feasible": feasible,
            "achievable_ratio": round(abs_d, 4),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Gap history — immutable daily snapshots (each day priced with its own curve)
# ─────────────────────────────────────────────────────────────────────────────

def record_gap_snapshot(grid, commodity, snap_date, source="live"):
    """
    Append one row per LIVE cell to lrp_gap_history.csv. Re-running the same
    day replaces that day's rows. This file is the richness baseline — it is
    never re-priced.
    """
    if _history_readonly():
        return 0
    live = grid[grid["live"]] if "live" in grid.columns else grid
    if live.empty:
        return 0
    cols = ["weeks", "coverage_level", "coverage_price", "F",
            "producer_prem", "cme_put", "gap", "gap_pct"]
    snap = live[cols].copy()
    snap.insert(0, "date", snap_date.isoformat())
    snap.insert(1, "commodity", commodity)
    snap["source"] = source
    if os.path.exists(GAP_HISTORY_FILE):
        old = pd.read_csv(GAP_HISTORY_FILE, dtype={"date": str})
        old = old[~((old["date"] == snap_date.isoformat()) &
                    (old["commodity"] == commodity))]
        snap = pd.concat([old, snap], ignore_index=True)
    snap.sort_values(["commodity", "date", "weeks", "coverage_level"],
                     inplace=True)
    snap.to_csv(GAP_HISTORY_FILE, index=False)
    return len(live)


def load_gap_history(commodity):
    if not os.path.exists(GAP_HISTORY_FILE):
        return pd.DataFrame()
    df = pd.read_csv(GAP_HISTORY_FILE, dtype={"date": str})
    return df[df["commodity"] == commodity]


def _yahoo_contract_history(symbol, range_="2y"):
    """Daily closes for one futures contract → {date: close}."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={range_}&interval=1d")
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                            timeout=15)
        if resp.status_code != 200:
            return {}
        result = resp.json().get("chart", {}).get("result", [])
        if not result:
            return {}
        ts = result[0].get("timestamp", [])
        closes = result[0].get("indicators", {}).get("quote", [{}])[0] \
                          .get("close", [])
        out = {}
        for t, c in zip(ts, closes):
            if c is not None and c > 0:
                out[date.fromtimestamp(t)] = float(c)
        return out
    except Exception:
        return {}


def _yahoo_curve_asof(commodity, asof, hist_cache):
    """
    Reconstruct the futures curve as of a past date from Yahoo daily closes.
    hist_cache caches per-contract history across calls. Uses the last close
    on or before asof (max 7 days stale).
    """
    root = _YAHOO_ROOT.get(commodity)
    months = _YAHOO_MONTHS.get(commodity)
    if not root or not months:
        return {}
    curve = {}
    for offset_months in range(0, 19):
        m = asof.month + offset_months
        y = asof.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        if m not in months:
            continue
        yr2 = str(y)[-2:]
        sym = f"{root}{months[m]}{yr2}.CME"
        if sym not in hist_cache:
            hist_cache[sym] = _yahoo_contract_history(sym)
            time.sleep(0.05)
        h = hist_cache[sym]
        best = None
        for dd in sorted(h):
            if dd <= asof:
                best = dd
            else:
                break
        if best and (asof - best).days <= 7:
            curve[f"{_MONTH_ABBR[m]} {yr2}"] = h[best]
    return curve


def ensure_gap_history(commodity, lookback, r, base_vol, verbose=True):
    """
    Make sure the snapshot file covers the trailing `lookback` trading days.
    Missing days are reconstructed from that day's RMA rates (lrp_cache /
    RMA archive) priced against THAT day's Yahoo curve; if the curve can't
    be rebuilt, that day's RMA expected ending value stands in as the
    forward (tagged in the source column). Days RMA never published
    (holidays, suspensions) are skipped.
    """
    have = set(load_gap_history(commodity)["date"]) \
        if os.path.exists(GAP_HISTORY_FILE) else set()
    d = sales_today() - timedelta(days=1)
    days_ok, checked, added = 0, 0, 0
    hist_cache = {}
    while days_ok < lookback and checked < lookback * 2:
        if d.weekday() >= 5:
            d -= timedelta(days=1)
            continue
        checked += 1
        iso = d.isoformat()
        if iso in have:
            days_ok += 1
        else:
            lrp_df = fetch_lrp(commodity, d, use_cache=True)
            if not lrp_df.empty:
                curve = _yahoo_curve_asof(commodity, d, hist_cache)
                if len(curve) >= 2:
                    source = "backfill_yahoo"
                else:
                    curve, source = {}, "backfill_rma_ev"
                g = build_grid(lrp_df, curve, r, base_vol, asof=d)
                record_gap_snapshot(g, commodity, d, source=source)
                days_ok += 1
                added += 1
                if verbose and added % 5 == 0:
                    print(f"{added}..", end="", flush=True)
        d -= timedelta(days=1)
    if verbose and added:
        print(f" backfilled {added} day(s) into gap history.")
    return days_ok


MIN_BASELINE_GAP_PCT = 0.05
"""Smallest baseline gap_pct, IN PERCENT, that may be used as a richness denominator.

Observed baselines run 0.06 to 1.37 percent, so 0.05 excludes only cells whose normal gap
is indistinguishable from zero -- exactly the cells where a ratio is meaningless. Those are
reported as "no richness" rather than as a large multiple.
"""

MIN_RICHNESS_BUY = 1.25
"""Richness a cell must reach before BUY is allowed.

This was hardcoded at 3.0, which is UNREACHABLE. Backtested over the corrected gap
history (1,533 evaluable cell-days, 2026-06-22..2026-08-06) the highest richness any
cell ever attained was 2.1, and the 3.0 gate fired exactly zero times — the signal
could never fire regardless of how good the opportunity was.

The gate is unreachable because richness is a RATIO of today's gap to that cell's own
baseline, and correcting the producer-premium bug ADDS the subsidy to both sides rather
than scaling them, which compresses every ratio toward 1.0 (median richness moved
0.77 -> 0.90). A multiple that made sense against small contaminated gaps cannot survive
against correctly-sized ones.

Calibration at min_buy_delta=0.25, share of evaluable cell-days firing:
    1.15 -> 9.7%   1.25 -> 4.3%   1.35 -> 2.5%   1.50 -> 1.1%   2.00 -> 0.1%
1.25 is chosen to make BUY occasional (5 of 26 days) rather than never.

CAVEAT: 26 evaluable days is a thin base. Re-run scripts/rebuild_gap_history.py's
backtest once a full season has accumulated and re-tune.
"""


# Recorded days a (tenor x coverage) cell needs before its average is shown at all. Three
# observations is not a baseline, and an average of three printed beside averages of thirty
# invites reading them as equally solid. Cells below this are left BLANK, and the chart says
# so — see build_chart_figure's Average Savings panel.
MIN_HIST_DAYS = 5


def add_history_from_snapshots(grid, commodity, lookback, today_date=None,
                               min_days=MIN_HIST_DAYS, low_base_floor=0.10,
                               min_buy_delta=0.25,
                               min_richness=MIN_RICHNESS_BUY):
    """
    Richness from RECORDED snapshots only — history is never re-priced, so
    market moves between then and now cannot distort the baseline.
    Guards:
      - a cell needs >= min_days recorded days, else no richness
      - baseline avg gap < low_base_floor $/cwt → no richness (a tiny
        denominator turns noise into a huge multiple)
      - BUY additionally requires today's gap >= baseline + min_buy_delta
    Adds: hist_avg_gap, hist_avg_gap_pct, richness, buy_ok, n_hist.
    """
    if today_date is None:
        today_date = sales_today()
    grid = grid.copy()
    hist = load_gap_history(commodity)
    if not hist.empty:
        hist = hist[hist["date"] < today_date.isoformat()]
        dates = sorted(hist["date"].unique())[-lookback:]
        hist = hist[hist["date"].isin(dates)]
    if hist.empty:
        grid["hist_avg_gap"] = None
        grid["hist_avg_gap_pct"] = None
        grid["richness"] = None
        grid["buy_ok"] = False
        grid["n_hist"] = 0
        return grid

    agg = hist.groupby(["weeks", hist["coverage_level"].round(4)]).agg(
        avg_gap=("gap", "mean"), avg_pct=("gap_pct", "mean"),
        n=("gap", "size"))

    avg_gaps, avg_pcts, richness, buy_ok, n_hist = [], [], [], [], []
    for _, row in grid.iterrows():
        key = (row["weeks"], round(row["coverage_level"], 4))
        if key not in agg.index or agg.loc[key, "n"] < min_days:
            avg_gaps.append(None); avg_pcts.append(None)
            richness.append(None); buy_ok.append(False); n_hist.append(0)
            continue
        a = agg.loc[key]
        avg_gaps.append(round(float(a["avg_gap"]), 4))
        avg_pcts.append(round(float(a["avg_pct"]), 3))
        n_hist.append(int(a["n"]))
        rx = None
        # UNITS. gap_pct is stored as a PERCENT (gap / coverage_price * 100), so a floor of
        # 0.001 meant one thousandth of one percent -- no floor at all. Richness divides by
        # this number, so a near-zero baseline produced absurd multiples: observed max was
        # 228x on real data, against a BUY gate of 1.25. low_base_floor guards avg_gap in
        # DOLLARS, which is a different quantity from the ratio's denominator and cannot
        # substitute for it.
        if (float(a["avg_gap"]) >= low_base_floor
                and abs(a["avg_pct"]) >= MIN_BASELINE_GAP_PCT):
            rx = round(float(row["gap_pct"]) / float(a["avg_pct"]), 1)
        richness.append(rx)
        buy_ok.append(bool(rx is not None and rx >= min_richness
                           and (row["gap"] - float(a["avg_gap"]))
                           >= min_buy_delta))

    grid["hist_avg_gap"] = avg_gaps
    grid["hist_avg_gap_pct"] = avg_pcts
    grid["richness"] = richness
    grid["buy_ok"] = buy_ok
    grid["n_hist"] = n_hist
    return grid


# ─────────────────────────────────────────────────────────────────────────────
# Terminal output
# ─────────────────────────────────────────────────────────────────────────────

G  = "\033[32m"
BG = "\033[92m"
Y  = "\033[33m"
R  = "\033[91m"
GR = "\033[90m"
B  = "\033[1m"
RS = "\033[0m"


def check_window():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    ct = datetime.now(ZoneInfo("America/Chicago"))
    dow = ct.weekday()
    hm = ct.hour * 60 + ct.minute
    print(f"  {ct.strftime('%A %Y-%m-%d %I:%M %p')} CT")
    # LRP sales close at 8:25 AM CT (= 505 min past midnight), not 9:00. Endorsements may
    # be written from RMA's ~3:30 PM CT posting through 8:25 the next morning.
    if hm >= 930:
        left = (24 * 60 - hm) + 505
        print(f"  LRP window: {BG}OPEN{RS} — {left // 60}h {left % 60}m to close")
    elif hm < 505:
        left = 505 - hm
        print(f"  LRP window: {BG}OPEN{RS} — {left // 60}h {left % 60}m to close")
    else:
        print(f"  LRP window: {GR}CLOSED{RS} — opens ~3:30 PM CT")
    if dow >= 5:
        print(f"  {GR}Weekend — no settlement or RMA posting.{RS}")


def print_signal(grid, commodity, spot, cme_source, head, futures_curve):
    label = "Fed Cattle" if commodity == "fed" else "Feeder Cattle"
    cwt = head * CWT_PER_HEAD

    print(f"\n{'═' * 78}")
    print(f"  LRP SAVINGS SIGNAL — {label}  |  {sales_today()}")
    print(f"  Spot ${spot:.2f}/cwt  |  CME: {cme_source}  |  {head:,} head")
    print(f"{'═' * 78}")
    check_window()

    if futures_curve:
        months = sorted(futures_curve.items(),
                        key=lambda x: cme_month_to_date(x[0]) or date.max)
        if months:
            print(f"  CME curve: {months[0][0]} ${months[0][1]:.2f}"
                  f" → {months[-1][0]} ${months[-1][1]:.2f}")

    live_count = grid["live"].sum()
    if live_count == 0:
        print(f"\n  {R}NO RMA DATA — LRP suspended today (report day?){RS}")
        print(f"  All numbers below are estimates. Do not trade.\n")

    valid = grid[grid["gap"] > 0]
    if valid.empty:
        print(f"\n  {Y}No cells where LRP is cheaper than CME today.{RS}\n")
        return

    # Best cell by normalized gap (% of coverage price)
    best = valid.loc[valid["gap_pct"].idxmax()]
    print(f"\n  {B}BEST CELL: {best['coverage_pct']} / "
          f"{int(best['weeks'])}w{RS}  (K=${best['coverage_price']:.2f}  "
          f"F=${best['F']:.2f})")
    prod, cme_p, gap = best["producer_prem"], best["cme_put"], best["gap"]
    print(f"    LRP premium:   ${prod:.2f}/cwt  (${prod * cwt:>10,.0f})")
    print(f"    CME put:       ${cme_p:.2f}/cwt  (${cme_p * cwt:>10,.0f})")
    print(f"    {G}You save:      ${gap:.2f}/cwt  (${gap * cwt:>10,.0f})"
          f"  [{best['gap_pct']:.2f}% of strike]{RS}")
    if best.get("hist_avg_gap") is not None and best["hist_avg_gap"] > 0:
        rx = best.get("richness")
        if rx:
            print(f"    30d avg:       ${best['hist_avg_gap']:.2f}/cwt"
                  f"  →  {BG}{rx:.1f}x normal{RS}")

    # Every cell — grouped by tenor
    print(f"\n{'─' * 95}")
    print(f"  {'Tenor':<7} {'Cov':>5} {'K':>8} {'F':>8} {'LRP':>7} {'CME':>7} "
          f"{'Gap':>7} {'Gap%':>6} {'Sub':>6} {'Vol':>7} {'30dAvg':>7} {'vs30d':>6}")
    print(f"{'─' * 95}")

    for weeks in TENORS_WEEKS:
        chunk = grid[grid["weeks"] == weeks].copy()
        chunk = chunk.sort_values("coverage_level", ascending=False)
        if chunk.empty:
            continue
        for _, row in chunk.iterrows():
            rx = row.get("richness")
            avg = row.get("hist_avg_gap")
            gap = row["gap"]
            gap_pct = row["gap_pct"]

            # Color the richness (bright green only for gated BUYs). buy_ok already
            # encodes the richness gate, so don't re-test a second hardcoded multiple.
            if rx is not None and row.get("buy_ok", False):
                tag = f"{BG}{rx:>4.1f}x BUY{RS}"
            elif rx is not None and rx >= MIN_RICHNESS_BUY:
                tag = f"{G}{rx:>4.1f}x{RS}"
            elif rx is not None and rx < 0.8:
                tag = f"{Y}{rx:>4.1f}x{RS}"
            elif rx is not None:
                tag = f"{rx:>4.1f}x"
            else:
                tag = f"{'—':>5}"

            avg_s = f"${avg:.2f}" if avg is not None else "—"
            vol_s = row["vol_gap"]
            vol_col = G if vol_s >= 0 else Y
            gap_col = G if gap > 0 else (Y if gap < 0 else RS)

            print(f"  {weeks:>3}w    {row['coverage_pct']:>5} "
                  f"${row['coverage_price']:>7.2f} ${row['F']:>7.2f} "
                  f"${row['producer_prem']:>6.2f} ${row['cme_put']:>6.2f} "
                  f"{gap_col}${gap:>6.2f}{RS} "
                  f"{gap_col}{gap_pct:>5.2f}%{RS} "
                  f"${row['subsidy_gap']:>5.2f} "
                  f"{vol_col}${vol_s:>6.2f}{RS} "
                  f"{avg_s:>7} {tag}")

    print(f"{'═' * 95}\n")


def print_table(grid, head):
    cwt = head * CWT_PER_HEAD
    d = grid[grid["gap"].notna()].copy()
    d = d.sort_values("gap", ascending=False)

    def f_usd(x): return f"${x:.2f}" if pd.notna(x) else "—"
    def f_gap(x): return f"${x:.2f}" if pd.notna(x) else "—"
    def f_tot(x): return f"${x * cwt:,.0f}" if pd.notna(x) else "—"
    def f_rx(x):  return f"{x:.1f}x" if pd.notna(x) else "—"

    tbl = pd.DataFrame({
        "Weeks": d["weeks"],
        "Cov": d["coverage_pct"],
        "LRP/cwt": d["producer_prem"].apply(f_usd),
        "CME/cwt": d["cme_put"].apply(f_usd),
        "Gap/cwt": d["gap"].apply(f_gap),
        f"Gap/{head:,}hd": d["gap"].apply(f_tot),
        "Subsidy": d["subsidy_gap"].apply(f_usd),
        "Vol disc": d["vol_gap"].apply(f_usd),
        "Normal": d["hist_avg_gap"].apply(f_gap) if "hist_avg_gap" in d else "—",
        "vs Hist": d["richness"].apply(f_rx) if "richness" in d else "—",
    })

    print(f"\n{'═' * 90}")
    print(f"  FULL GRID — sorted by savings (best first)  |  "
          f"{sales_today()}  |  {head:,} head")
    print(f"{'═' * 90}")
    print(tabulate(tbl, headers="keys", tablefmt="simple", showindex=False))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Chart — two panel: today's gap + today vs normal
# ─────────────────────────────────────────────────────────────────────────────

def build_chart_figure(grid, commodity, spot, cme_source, head, banner=None):
    """
    Build the 4-panel dashboard figure and return it (no file I/O).
    banner: optional warning text baked onto the figure (e.g. an EXPIRED
    notice); ignored when the grid is estimate-mode (which has its own).
    """
    label = "Fed Cattle" if commodity == "fed" else "Feeder Cattle"
    cwt = head * CWT_PER_HEAD
    cov_order = [f"{int(c * 100)}%" for c in sorted(COVERAGE_LEVELS, reverse=True)]

    def pivot(col):
        p = grid.pivot(index="coverage_pct", columns="weeks", values=col)
        return p.reindex([c for c in cov_order if c in p.index])

    estimated = "live" in grid.columns and not bool(grid["live"].any())
    # Estimate mode: no real RMA quotes — timing panels would be meaningless
    has_history = (not estimated and "richness" in grid.columns
                   and grid["richness"].notna().any())
    tick_labels = [f"{w}w" for w in TENORS_WEEKS]
    # TYPE SIZES ARE SET FOR THE SIZE THIS IS *VIEWED* AT, not the size it is drawn at.
    # st.pyplot renders the figure ~1460 px wide and the browser fits it to the container at
    # ~809 px — every glyph lands on screen at 55% of its drawn size, so matplotlib's defaults
    # (10pt ticks) arrive as ~5pt and the axis becomes unreadable. Raising dpi does NOT help:
    # it scales the whole image equally and the browser scales it right back down. The only
    # lever is point size relative to figure size.
    # ANNOT_FS is set by the DENSEST panel, not the roomiest. The decomposition panel puts
    # two labelled figures in every cell ("sub $3.36" over "vol $5.09"), ~9 characters a line
    # against a 0.78in cell — at 11pt those run into their neighbours. 9pt clears it, and the
    # single-value panels lose nothing they needed.
    TICK_FS, LABEL_FS, TITLE_FS, ANNOT_FS = 15, 15, 15, 9
    hm_kw = dict(linewidths=0.8, linecolor="white",
                 annot_kws={"size": ANNOT_FS, "fontweight": "bold"})
    cbar_kw = dict(shrink=0.6, aspect=15)

    # STACKED FULL WIDTH, not 2x2 — and NARROWER than the old grid, which is the part that
    # actually matters. Streamlit fits the image to the container, so the on-screen scale is
    # (container px) / (figure inches): 809/18 = 45 px per inch before, 809/13 = 62 now. Two
    # gains compound. Each panel gets the whole width instead of half, so a cell goes from
    # ~0.8in to ~1.7in; and every point of type renders 1.4x larger because the figure is
    # narrower. Together a cell's on-screen width roughly doubles, which is the room the
    # two-line annotations ("$23.74 / $308,656") needed and never had.
    #
    # The cost is a tall image. That is the right trade for a reference table someone reads
    # a row at a time: scrolling is cheap, squinting is not.
    n_panels = 4 if has_history else 2
    # PANEL GEOMETRY IS SET FROM THE GRID SHAPE, not picked by eye. Each panel draws 10
    # tenor columns x 12 coverage rows. At 13 x 5.6 the plotting area came out 9.4 x 4.1in,
    # making every cell 2.78x wider than tall — which is what reads as "stretched": the
    # heatmap stops looking like a grid of values and starts looking like a bar chart.
    #
    # Target is ~1.7, wide enough for the two-line annotations ("$23.74" over "$308,656")
    # and no wider. Narrowing the figure as well as heightening the panel does double duty:
    # it lifts the aspect AND raises on-screen type, since Streamlit fits to the container
    # so px-per-inch is 809/width.
    fig, axes = plt.subplots(n_panels, 1, figsize=(11, 7.0 * n_panels))

    # ── Panel 1 (top-left): Total gap $/cwt ──
    p_gap = pivot("gap")
    annot_gap = p_gap.copy().astype(object)
    for ri in annot_gap.index:
        for ci in annot_gap.columns:
            v = p_gap.loc[ri, ci]
            if pd.notna(v):
                annot_gap.loc[ri, ci] = f"${v:.2f}\n${v * cwt:,.0f}"
            else:
                annot_gap.loc[ri, ci] = ""
    sns.heatmap(p_gap, ax=axes[0], cmap="RdYlGn", center=0,
                annot=annot_gap, fmt="",
                cbar_kws={**cbar_kw, "label": "$/cwt"}, **hm_kw)
    axes[0].set_title(f"Total Savings (CME Put − LRP Premium)\n"
                         f"$/cwt + total on {head:,} head", fontsize=TITLE_FS)
    axes[0].set_xlabel("Tenor (weeks)", fontsize=LABEL_FS)
    axes[0].set_ylabel("Coverage Level", fontsize=LABEL_FS)
    axes[0].set_xticklabels(tick_labels, fontsize=TICK_FS)

    # ── Panel 2 (top-right): Subsidy vs Vol decomposition ──
    p_sub = pivot("subsidy_gap")
    p_vol = pivot("vol_gap")
    # Color by vol_gap (the variable piece — subsidy is structural)
    annot_decomp = p_vol.copy().astype(object)
    for ri in annot_decomp.index:
        for ci in annot_decomp.columns:
            s = p_sub.loc[ri, ci] if pd.notna(p_sub.loc[ri, ci]) else 0
            v = p_vol.loc[ri, ci] if pd.notna(p_vol.loc[ri, ci]) else 0
            if pd.notna(p_sub.loc[ri, ci]):
                annot_decomp.loc[ri, ci] = (f"sub ${s:.2f}\nvol ${v:.2f}")
            else:
                annot_decomp.loc[ri, ci] = ""
    sns.heatmap(p_vol, ax=axes[1], cmap="RdYlGn", center=0,
                annot=annot_decomp, fmt="",
                cbar_kws={**cbar_kw, "label": "vol gap $/cwt"}, **hm_kw)
    axes[1].set_title("Gap Decomposition: Subsidy vs Vol Discount\n"
                         "sub = federal subsidy | vol = RMA cheaper than CME",
                         fontsize=TITLE_FS)
    axes[1].set_xlabel("Tenor (weeks)", fontsize=LABEL_FS)
    axes[1].set_ylabel("Coverage Level", fontsize=LABEL_FS)
    axes[1].set_xticklabels(tick_labels, fontsize=TICK_FS)

    if has_history:
        # ── Panel 3 (bottom-left): 30-day average gap ──
        p_avg = pivot("hist_avg_gap")
        annot_avg = p_avg.copy().astype(object)
        for ri in annot_avg.index:
            for ci in annot_avg.columns:
                v = p_avg.loc[ri, ci]
                if pd.notna(v):
                    annot_avg.loc[ri, ci] = f"${v:.2f}"
                else:
                    annot_avg.loc[ri, ci] = ""
        sns.heatmap(p_avg, ax=axes[2], cmap="RdYlGn", center=0,
                    annot=annot_avg, fmt="",
                    cbar_kws={**cbar_kw, "label": "$/cwt"}, **hm_kw)
        n_days = int(grid["n_hist"].max()) if "n_hist" in grid.columns else 0
        # n_days is the MAXIMUM across cells, not a figure every cell shares — coverage
        # levels added to the offer later have their own, shorter history. Saying so beside
        # the number, and saying what a blank row means, is the difference between "this
        # chart is broken" and "that level is too new to average".
        thin = int((grid["n_hist"] < MIN_HIST_DAYS).sum()) if "n_hist" in grid.columns else 0
        axes[2].set_title(
            f"Average Savings — up to {n_days} recorded day(s)\n"
            "each day priced with its own curve (never re-priced); blank = fewer than "
            f"{MIN_HIST_DAYS} recorded days"
            + (f" ({thin} cells)" if thin else ""), fontsize=TITLE_FS)
        axes[2].set_xlabel("Tenor (weeks)", fontsize=LABEL_FS)
        axes[2].set_ylabel("Coverage Level", fontsize=LABEL_FS)
        axes[2].set_xticklabels(tick_labels, fontsize=TICK_FS)

        # ── Panel 4 (bottom-right): Richness ──
        p_rich = pivot("richness")
        p_buy = pivot("buy_ok") if "buy_ok" in grid.columns else None
        annot_rich = p_rich.copy().astype(object)
        for ri in annot_rich.index:
            for ci in annot_rich.columns:
                v = p_rich.loc[ri, ci]
                ok = (p_buy is not None and pd.notna(p_buy.loc[ri, ci])
                      and bool(p_buy.loc[ri, ci]))
                if pd.notna(v):
                    if ok:
                        annot_rich.loc[ri, ci] = f"{v:.1f}x\nBUY"
                    elif v >= MIN_RICHNESS_BUY:
                        annot_rich.loc[ri, ci] = f"{v:.1f}x"
                    elif v < 0.8:
                        annot_rich.loc[ri, ci] = f"{v:.1f}x\nwait"
                    else:
                        annot_rich.loc[ri, ci] = f"{v:.1f}x"
                else:
                    annot_rich.loc[ri, ci] = ""
        # vmax was 5, but observed richness tops out near 2.1 once producer premium is
        # correct — a 0..5 scale pinned every real cell into the same washed-out band.
        sns.heatmap(p_rich, ax=axes[3], cmap="RdYlGn", center=1.0,
                    vmin=0, vmax=2.5, annot=annot_rich, fmt="",
                    cbar_kws={**cbar_kw, "label": "x normal"}, **hm_kw)
        axes[3].set_title("Today vs Recorded Avg (x multiple)\n"
                             f"BUY needs ≥{MIN_RICHNESS_BUY:g}x AND +$0.25/cwt vs normal; "
                             "blank = baseline too small to trust", fontsize=TITLE_FS)
        axes[3].set_xlabel("Tenor (weeks)", fontsize=LABEL_FS)
        axes[3].set_ylabel("Coverage Level", fontsize=LABEL_FS)
        axes[3].set_xticklabels(tick_labels, fontsize=TICK_FS)
    # No else-branch hiding empty panels any more: the 2x2 grid always created four axes and
    # had to blank two of them, leaving a large hole in the figure. Stacked, n_panels is 2 or
    # 4 up front, so the history panels are simply never created and the image is shorter
    # instead of half empty.

    # Sweep every axis rather than styling each panel: the Y tick labels (coverage levels)
    # and the colour bars are created by seaborn and never touched above, so setting sizes
    # panel-by-panel left exactly those two unreadable. Doing it in one pass also means a
    # future fifth panel inherits the sizes instead of quietly reverting to the 10pt default.
    for ax in axes.flat:
        ax.tick_params(axis="both", labelsize=TICK_FS)
        for lbl in ax.get_yticklabels():
            lbl.set_rotation(0)          # coverage levels read horizontally
        cb = getattr(ax.collections[0], "colorbar", None) if ax.collections else None
        if cb is not None:
            cb.ax.tick_params(labelsize=TICK_FS - 2)
            if cb.ax.get_ylabel():
                cb.ax.set_ylabel(cb.ax.get_ylabel(), fontsize=LABEL_FS - 1)

    fig.suptitle(
        f"LRP Savings Signal  —  {label}  —  Spot ${spot:.2f}/cwt  —  "
        f"{sales_today()}  —  CME: {cme_source}",
        fontsize=18, fontweight="bold")
    note = None
    if estimated:
        note = ("ESTIMATED — NO RMA DATA TODAY — premiums are model "
                "estimates, DO NOT TRADE", "#C62828")
    elif banner:
        note = (banner, "#E65100")
    if note:
        fig.text(0.5, 0.945, note[0],
                 ha="center", fontsize=13, fontweight="bold", color="white",
                 bbox=dict(boxstyle="round,pad=0.4", facecolor=note[1],
                           edgecolor="none"))
        plt.tight_layout(rect=[0, 0, 1, 0.92])
    else:
        plt.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def render_chart(grid, commodity, spot, cme_source, head):
    fig = build_chart_figure(grid, commodity, spot, cme_source, head)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"lrp_signal_{commodity}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Chart saved: {out}")
    # Only open a window when run interactively — plt.show() blocks forever
    # in scripted/background runs (the chart is already saved above)
    if sys.stdout.isatty():
        plt.show()
    else:
        plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LRP Savings Signal")
    parser.add_argument("--commodity", choices=["fed", "feeder"], default="feeder")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--spot", type=float, default=None)
    parser.add_argument("--vol", type=float, default=14.0,
                        help="Base vol %% for B76 fallback (default 14)")
    parser.add_argument("--rate", type=float, default=5.0,
                        help="Risk-free rate %% (default 5.0)")
    parser.add_argument("--head", type=int, default=1000,
                        help="Head count for dollar totals (default 1000)")
    parser.add_argument("--lookback", type=int, default=30,
                        help="Trading days of history for 30-day avg (default 30)")
    parser.add_argument("--output", choices=["signal", "table", "chart", "all"],
                        default="chart")
    args = parser.parse_args()

    r = args.rate / 100.0
    base_vol = args.vol / 100.0

    sales_date = None
    if args.date:
        try:
            sales_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid date: {args.date}")
            sys.exit(1)

    # CME futures curve
    print(f"  Fetching CME settlement curve...", end=" ")
    futures_curve = fetch_cme_futures_curve(args.commodity)
    if futures_curve:
        front = next(iter(futures_curve.items()))
        print(f"{front[0]} @ ${front[1]:.2f}/cwt")
    else:
        print("unavailable")

    # RMA LRP data — overnight window serves yesterday's still-live rates
    print(f"  Fetching RMA LRP data...", end=" ")
    if sales_date is None:
        today_lrp, eff_date = fetch_lrp_current(args.commodity)
    else:
        today_lrp, eff_date = fetch_lrp(args.commodity, sales_date), sales_date
    if today_lrp.empty:
        print(f"{R}no data (suspended?){RS}")
    else:
        print(f"{len(today_lrp)} rows")

    # Spot — for display only now; grid uses RMA coverage_price + CME forwards
    if args.spot:
        spot = args.spot
    elif not today_lrp.empty:
        spot = float(today_lrp["expected_value"].iloc[0])
    elif futures_curve:
        spot = next(iter(futures_curve.values()))
    else:
        spot = 350.0 if args.commodity == "feeder" else 230.0

    cme_source = get_cme_source_label(futures_curve)

    # Build grid — CME puts priced inline using same K and F as LRP
    run_date = eff_date
    grid = build_grid(today_lrp, futures_curve, r, base_vol, asof=run_date)

    # Record the gap as an immutable snapshot (live RMA data only —
    # estimate-mode grids are never written into the baseline; historical
    # --date runs are excluded because the curve is today's)
    if grid["live"].any() and sales_date is None:
        record_gap_snapshot(grid, args.commodity, run_date, source="live")

    # Richness baseline: recorded snapshots, each day priced with its own
    # curve. Backfill any missing trailing days first.
    print(f"  Checking {args.lookback}-day gap history...", end=" ", flush=True)
    n_days = ensure_gap_history(args.commodity, args.lookback, r, base_vol)
    print(f"{n_days} day(s) available.")
    grid = add_history_from_snapshots(grid, args.commodity, args.lookback,
                                      today_date=run_date)

    # Output
    if args.output in ("signal", "all"):
        print_signal(grid, args.commodity, spot, cme_source, args.head,
                     futures_curve)
    if args.output in ("table", "all"):
        print_table(grid, args.head)
    if args.output in ("chart", "all"):
        render_chart(grid, args.commodity, spot, cme_source, args.head)

    # Always print signal summary with chart
    if args.output == "chart":
        print_signal(grid, args.commodity, spot, cme_source, args.head,
                     futures_curve)

    # Save
    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"lrp_signal_{args.commodity}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    grid.to_csv(csv_path, index=False)
    print(f"  Grid saved: {csv_path}")


if __name__ == "__main__":
    main()
