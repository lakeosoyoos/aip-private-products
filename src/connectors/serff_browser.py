"""SERFF Filing Access browser-driven extractor (Playwright, headless Chromium).

Phase-B adapter for the `serff` connector: drives the shared NAIC portal at
https://filingaccess.serff.com/sfa/home/<ST> (a JSF/PrimeFaces app that plain requests
cannot search) and extracts filing-level records for the AIP legal entities.

Flow per state:
  open /sfa/home/<ST> -> "Begin Search" -> Accept the public-access user agreement ->
  filingSearch.xhtml -> for each company: Clear Search, Business Type = Property & Casualty,
  Type of Insurance = "02.1 Crop" (checkbox menu; the portal searches at TOI level — the
  Crop-Hail sub-TOIs such as 02.1000/02.1001 are reported per filing and captured verbatim),
  Company Name = <term> with "Contains", Search -> paginate results (rows-per-page bumped to
  100) -> optionally open each filingSummary.xhtml?filingId=<id> for dates + disposition.

Politeness: strictly sequential, small sleeps between searches / page turns / detail fetches.
If the portal ever presents a CAPTCHA/bot challenge we STOP for that state (screenshot to
data/cache/serff/debug/) and report it — no bypass attempts, no fabricated filings. Every
record is parsed verbatim from portal markup (tracking numbers are spot-checkable).

Public API:
    fetch_filings(state, companies, cfg) -> list[dict]

CLI:
    python -m src.connectors.serff_browser --state IA [--companies "A,B"] [--no-details]
prints a JSON summary and writes full results to data/cache/serff/<ST>_filings.json.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://filingaccess.serff.com/sfa"
SEARCH_URL = f"{BASE}/search/filingSearch.xhtml"
RESULTS_URL_PART = "filingSearchResults.xhtml"
SUMMARY_URL = f"{BASE}/search/filingSummary.xhtml?filingId={{fid}}"

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "data" / "cache" / "serff"
DEBUG_DIR = OUT_DIR / "debug"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# TOI checkbox-menu label. The portal offers TOI "02.1 Crop"; Crop-Hail sub-TOIs
# (02.1000 etc.) only appear per filing, so we search the TOI and record sub-TOI verbatim.
DEFAULT_TOI = "02.1 Crop"

# AIP legal entities (catalog aips table) -> distinctive "Contains" search term.
# Contains-match keeps recall high when the writing entity differs slightly.
AIP_COMPANY_TERMS: dict[str, str] = {
    "ACE American Insurance Company": "ACE American",
    "American Agri-Business Insurance Company": "American Agri-Business",
    "American Agricultural Insurance Company": "American Agricultural",
    "Clear Blue Insurance Company": "Clear Blue",
    "Country Mutual Insurance Company": "Country Mutual",
    "Farmers Mutual Hail Insurance Company of Iowa": "Farmers Mutual Hail",
    "Great American Insurance Company": "Great American Insurance Company",
    "Hudson Insurance Company": "Hudson Insurance",
    "NAU Country Insurance Company": "NAU Country",
    "Palomar Specialty Insurance Company": "Palomar",
    "Producers Agriculture Insurance Company": "Producers Agriculture",
    "Rural Community Insurance Company": "Rural Community",
    # Managing-agency name many ACE/Chubb crop filings are filed under.
    "Rain and Hail": "Rain and Hail",
}

# Polite pacing (seconds). Details are the hot path that can trip the portal's bot
# challenge — keep them slow; on any challenge we stop outright (never solve/bypass).
DELAY_BETWEEN_SEARCHES = 4.0
DELAY_BETWEEN_PAGES = 1.5
DELAY_BETWEEN_DETAILS = 3.0

RESULT_COLUMNS = [
    "company_name",
    "naic_company_code",
    "product_name",
    "sub_toi",
    "filing_type",
    "filing_status",
    "serff_tracking_number",
]

# Includes the AWS-WAF-style interstitial the portal serves under load
# ("Let's confirm you are human / Complete the security check before continuing").
CAPTCHA_MARKERS = (
    "captcha",
    "hcaptcha",
    "are you a robot",
    "bot detection",
    "confirm you are human",
    "security check before continuing",
    "verifies that you are not a bot",
    "awswaf",
)


class SerffBlockedError(RuntimeError):
    """Raised when the portal presents a CAPTCHA / bot challenge. Never bypassed."""


# --------------------------------------------------------------------------------------
# Pure parsing helpers (unit-testable, no browser)
# --------------------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    """Collapse an HTML fragment to normalized visible text."""
    text = _TAG_RE.sub(" ", html)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_paginator(html: str) -> tuple[int, int] | None:
    """Return (current_page, total_pages) from a results page, or None if absent."""
    m = re.search(r'ui-paginator-current">\((\d+)\s+of\s+(\d+)\)', html)
    return (int(m.group(1)), int(m.group(2))) if m else None


_ROW_RE = re.compile(r'<tr[^>]*\bdata-rk="(\d+)"[^>]*>(.*?)</tr>', re.DOTALL)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)


def parse_results_rows(html: str) -> list[dict]:
    """Extract filing rows (data-rk id + the 7 result columns) from a results page."""
    rows = []
    for m in _ROW_RE.finditer(html):
        fid, row_html = m.group(1), m.group(2)
        cells = [_strip_tags(c) for c in _CELL_RE.findall(row_html)]
        rec = {"filing_id": fid}
        for col, val in zip(RESULT_COLUMNS, cells):
            rec[col] = val
        rows.append(rec)
    return rows


_SUMMARY_PAIR_RE = re.compile(
    r'<label class="col-sm-5 text-right">([^<]+?):\s*</label>\s*'
    r'<div class="col-sm-7">(.*?)</div>',
    re.DOTALL,
)

_SUMMARY_FIELD_MAP = {
    "Product Name": "product_name",
    "Type Of Insurance": "toi",
    "Sub Type Of Insurance": "sub_toi",
    "Filing Type": "filing_type",
    "SERFF Tracking Number": "serff_tracking_number",
    "Submission Date": "submission_date",
    "Filing Status": "filing_status",
    "SERFF Status": "serff_status",
    "Disposition Date": "disposition_date",
    "Disposition Status": "disposition_status",
}


def parse_filing_summary(html: str) -> dict:
    """Extract the label/value pairs from a filingSummary.xhtml page."""
    out: dict = {}
    for m in _SUMMARY_PAIR_RE.finditer(html):
        label = _strip_tags(m.group(1))
        key = _SUMMARY_FIELD_MAP.get(label)
        if key:
            out[key] = _strip_tags(m.group(2))
    return out


def to_iso_date(raw: str | None) -> str | None:
    """Normalize portal dates ('1/28/16', '02/12/2016') to YYYY-MM-DD; None if unparseable."""
    if not raw:
        return None
    raw = raw.strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$", raw)
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(yr) if len(yr) == 4 else 2000 + int(yr)
    try:
        return datetime(year, mo, dy).date().isoformat()
    except ValueError:
        return None


def looks_blocked(html_text: str) -> bool:
    """True if page text smells like a CAPTCHA / bot challenge."""
    low = html_text.lower()
    return any(marker in low for marker in CAPTCHA_MARKERS)


# --------------------------------------------------------------------------------------
# Browser session
# --------------------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Session:
    """One headless-browser session against one state's portal."""

    def __init__(self, page, state: str, log=print):
        self.page = page
        self.state = state.upper()
        self.log = log

    # -- infrastructure ----------------------------------------------------
    def _shot(self, tag: str) -> str:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DEBUG_DIR / f"{self.state}_{tag}_{ts}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception:
            return ""
        return str(path)

    def _check_blocked(self, stage: str) -> None:
        try:
            body = self.page.inner_text("body", timeout=5000)
        except Exception:
            return
        if looks_blocked(body):
            shot = self._shot(f"BLOCKED_{stage}")
            raise SerffBlockedError(
                f"{self.state}: CAPTCHA/bot challenge at {stage} ({self.page.url}); "
                f"screenshot: {shot}"
            )

    def _settle(self, seconds: float = 0.0) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        if seconds:
            time.sleep(seconds)

    # -- portal flow -------------------------------------------------------
    def open_portal(self) -> None:
        """Home page -> Begin Search -> Accept the public-access user agreement."""
        p = self.page
        p.goto(f"{BASE}/home/{self.state}", timeout=60000)
        self._settle()
        self._check_blocked("home")
        p.click("a:has-text('Begin Search')", timeout=20000)
        self._settle()
        if "userAgreement" in p.url:
            with p.expect_navigation(timeout=30000):
                p.click("button:has-text('Accept')")
            self._settle()
        if "filingSearch" not in p.url:
            shot = self._shot("open_portal")
            raise RuntimeError(
                f"{self.state}: expected filingSearch.xhtml after accept, got {p.url} "
                f"(screenshot: {shot})"
            )

    def _ensure_session(self) -> None:
        """Recover if the JSF session expired (portal bounces to home/sessionExpired)."""
        url = self.page.url
        if "sessionExpired" in url or url.endswith(f"/home/{self.state}") or "userAgreement" in url:
            self.log(f"  [{self.state}] session expired at {url}; re-accepting")
            self.open_portal()

    def goto_search_form(self) -> None:
        self.page.goto(SEARCH_URL, timeout=60000)
        self._settle()
        self._ensure_session()
        if "filingSearch" not in self.page.url:
            self.open_portal()

    def _select_business_type_pc(self) -> None:
        p = self.page
        label = (p.inner_text("#simpleSearch\\:businessType_label", timeout=15000) or "").strip()
        if "Property" in label:
            return
        p.click("#simpleSearch\\:businessType")
        p.wait_for_selector("#simpleSearch\\:businessType_panel", state="visible", timeout=15000)
        p.click("#simpleSearch\\:businessType_panel li[data-label='Property & Casualty']")
        try:
            p.wait_for_selector("#simpleSearch\\:businessType_panel", state="hidden", timeout=15000)
        except Exception:
            p.keyboard.press("Escape")
        # AJAX re-render brings in the TOI checkbox menu; wait for its hidden inputs.
        p.wait_for_selector("input[name='simpleSearch:availableTois']", state="attached",
                            timeout=25000)
        self._settle(0.5)

    def _select_toi(self, toi_label: str) -> None:
        p = self.page
        sel = f"input[name='simpleSearch:availableTois'][value='{toi_label}']"
        p.wait_for_selector(sel, state="attached", timeout=25000)
        if p.eval_on_selector(sel, "e => e.checked"):
            return
        p.click("#simpleSearch\\:availableTois")
        p.wait_for_selector("#simpleSearch\\:availableTois_panel", state="visible", timeout=15000)
        p.click(f"#simpleSearch\\:availableTois_panel li:has-text('{toi_label}')")
        time.sleep(0.6)
        p.keyboard.press("Escape")
        try:
            p.wait_for_selector("#simpleSearch\\:availableTois_panel", state="hidden",
                                timeout=15000)
        except Exception:
            pass
        self._settle(0.5)
        if not p.eval_on_selector(sel, "e => e.checked"):
            raise RuntimeError(f"{self.state}: failed to check TOI '{toi_label}'")

    def run_search(self, company_term: str, toi_label: str) -> None:
        """Fill the search form fresh and submit; lands on filingSearchResults.xhtml."""
        p = self.page
        self.goto_search_form()
        # The form retains prior criteria ("refine" behavior) — always reset first.
        clear = p.query_selector("button:has-text('Clear Search')")
        if clear:
            clear.click()
            self._settle(1.0)
        self._select_business_type_pc()
        self._select_toi(toi_label)
        p.fill("#simpleSearch\\:companyName", company_term)
        if not p.eval_on_selector("#simpleSearch\\:companyNameOptions\\:1", "e => e.checked"):
            p.click("label[for='simpleSearch:companyNameOptions:1']")  # Contains
        with p.expect_navigation(timeout=60000):
            p.click("#simpleSearch\\:saveBtn")
        self._settle(0.5)
        self._check_blocked("search")
        if RESULTS_URL_PART not in p.url:
            shot = self._shot("search_no_results_page")
            raise RuntimeError(
                f"{self.state}/'{company_term}': search did not reach results page "
                f"(at {p.url}; screenshot: {shot})"
            )

    def _bump_page_size(self) -> None:
        """Ask the results datatable for 100 rows/page (fewer round-trips = politer)."""
        p = self.page
        try:
            before = len(p.query_selector_all("tr[data-rk]"))
            pag = parse_paginator(p.content())
            if not pag or pag[1] <= 1:
                return
            p.select_option("select.ui-paginator-rpp-options >> nth=0", "100")
            for _ in range(40):
                time.sleep(0.5)
                if len(p.query_selector_all("tr[data-rk]")) != before:
                    break
                new_pag = parse_paginator(p.content())
                if new_pag and new_pag != pag:
                    break
        except Exception as exc:  # non-fatal: fall back to default page size
            self.log(f"  [{self.state}] rows-per-page bump failed ({exc}); paging at default size")

    def collect_result_rows(self, company_term: str) -> list[dict]:
        """Walk every results page, harvesting row records."""
        p = self.page
        self._bump_page_size()
        rows: list[dict] = []
        seen: set[str] = set()
        for guard in range(200):  # hard stop; no results set is this big
            html = p.content()
            page_rows = parse_results_rows(html)
            for r in page_rows:
                if r["filing_id"] not in seen:
                    seen.add(r["filing_id"])
                    rows.append(r)
            pag = parse_paginator(html)
            if not pag or pag[0] >= pag[1]:
                break
            cur = pag[0]
            p.click("a.ui-paginator-next >> nth=0")
            advanced = False
            for _ in range(40):
                time.sleep(0.5)
                new_pag = parse_paginator(p.content())
                if new_pag and new_pag[0] == cur + 1:
                    advanced = True
                    break
            if not advanced:
                shot = self._shot("pagination_stuck")
                raise RuntimeError(
                    f"{self.state}/'{company_term}': paginator stuck at page {cur} of "
                    f"{pag[1]} (screenshot: {shot})"
                )
            time.sleep(DELAY_BETWEEN_PAGES)
        return rows

    def fetch_detail(self, filing_id: str) -> dict:
        """Open filingSummary.xhtml?filingId=<id> and parse dates/disposition."""
        p = self.page
        url = SUMMARY_URL.format(fid=filing_id)
        p.goto(url, timeout=60000)
        self._settle()
        self._check_blocked(f"detail_{filing_id}")
        self._ensure_session()
        if f"filingId={filing_id}" not in p.url:
            p.goto(url, timeout=60000)
            self._settle()
            self._check_blocked(f"detail_{filing_id}")
        html = p.content()
        detail = parse_filing_summary(html)
        if not detail.get("serff_tracking_number"):
            shot = self._shot(f"detail_{filing_id}")
            raise RuntimeError(
                f"{self.state}: filing summary {filing_id} did not parse "
                f"(at {p.url}; screenshot: {shot})"
            )
        detail["filing_url"] = url
        return detail


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def _cfg_get(cfg, attr: str, default):
    return getattr(cfg, attr, default) if cfg is not None else default


def run_state(
    state: str,
    companies: list[str],
    cfg=None,
    *,
    toi_label: str = DEFAULT_TOI,
    details: bool = True,
    headless: bool = True,
    log=print,
    out_path: Path | None = None,
) -> dict:
    """Extract crop filings for one state across the given companies.

    Returns the full payload: {"state", "generated_at", "toi", "companies": {name:
    {"search_term", "status", "filings": N, "error"?}}, "filings": [record...]}.
    Saves the payload to out_path incrementally after each company (crash-resumable
    output, not resumed input).
    """
    from playwright.sync_api import sync_playwright

    state = state.upper()
    ua = _cfg_get(cfg, "serff_user_agent", DEFAULT_UA)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (OUT_DIR / f"{state}_filings.json")

    payload: dict = {
        "state": state,
        "portal": f"{BASE}/home/{state}",
        "toi": toi_label,
        "generated_at": _now_iso(),
        "companies": {},
        "filings": [],
    }
    # filing_id -> record (a filing found by two search terms is stored once, both terms noted)
    by_id: dict[str, dict] = {}

    def flush():
        payload["filings"] = list(by_id.values())
        payload["generated_at"] = _now_iso()
        out_path.write_text(json.dumps(payload, indent=2))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(user_agent=ua)
        page.set_default_timeout(30000)
        sess = _Session(page, state, log=log)
        try:
            sess.open_portal()
        except SerffBlockedError:
            raise
        except Exception as exc:
            browser.close()
            raise RuntimeError(f"{state}: could not open portal / accept agreement: {exc}") from exc

        for company in companies:
            term = AIP_COMPANY_TERMS.get(company, company)
            entry = {"search_term": term, "status": "ok", "filings": 0}
            payload["companies"][company] = entry
            log(f"[{state}] searching '{term}' (for: {company})")
            try:
                sess.run_search(term, toi_label)
                rows = sess.collect_result_rows(term)
                entry["filings"] = len(rows)
                log(f"[{state}]   {len(rows)} filings")
                for r in rows:
                    rec = by_id.get(r["filing_id"])
                    if rec is None:
                        rec = dict(r)
                        rec["state"] = state
                        rec["search_companies"] = [company]
                        rec["filing_url"] = SUMMARY_URL.format(fid=r["filing_id"])
                        rec["fetched_at"] = _now_iso()
                        by_id[r["filing_id"]] = rec
                    elif company not in rec["search_companies"]:
                        rec["search_companies"].append(company)
            except SerffBlockedError as exc:
                entry["status"] = "blocked"
                entry["error"] = str(exc)
                log(f"[{state}]   BLOCKED: {exc}")
                flush()
                browser.close()
                return payload  # a challenge means stop the whole state — no bypassing
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}: {exc}"
                log(f"[{state}]   ERROR: {exc}")
            flush()
            time.sleep(DELAY_BETWEEN_SEARCHES)

        if details:
            todo = [rec for rec in by_id.values() if "submission_date" not in rec]
            log(f"[{state}] fetching {len(todo)} filing summaries for dates/disposition")
            for i, rec in enumerate(todo, 1):
                try:
                    detail = sess.fetch_detail(rec["filing_id"])
                    # Results-row fields win only if detail lacks them; detail is richer.
                    rec.update({k: v for k, v in detail.items() if v})
                    rec["submission_date_iso"] = to_iso_date(rec.get("submission_date"))
                    rec["disposition_date_iso"] = to_iso_date(rec.get("disposition_date"))
                except SerffBlockedError as exc:
                    rec["detail_error"] = str(exc)
                    payload["details_blocked"] = str(exc)
                    log(f"[{state}]   BLOCKED during details — stopping detail phase: {exc}")
                    break
                except Exception as exc:
                    rec["detail_error"] = f"{type(exc).__name__}: {exc}"
                    log(f"[{state}]   detail {rec['filing_id']} ERROR: {exc}")
                if i % 25 == 0:
                    log(f"[{state}]   details {i}/{len(todo)}")
                    flush()
                time.sleep(DELAY_BETWEEN_DETAILS)
            flush()

        browser.close()

    flush()
    return payload


def fetch_filings(state: str, companies: list[str], cfg=None, **kwargs) -> list[dict]:
    """Public entry point: filing records for one state x companies (see run_state)."""
    return run_state(state, companies, cfg, **kwargs)["filings"]


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _summary(payload: dict) -> dict:
    per_company = {
        name: {"search_term": e["search_term"], "status": e["status"],
               "filings": e["filings"], **({"error": e["error"]} if e.get("error") else {})}
        for name, e in payload["companies"].items()
    }
    return {
        "state": payload["state"],
        "toi": payload["toi"],
        "unique_filings": len(payload["filings"]),
        "companies": per_company,
        "examples": [
            {k: f.get(k) for k in ("serff_tracking_number", "company_name", "product_name",
                                   "filing_type", "filing_status", "submission_date",
                                   "disposition_date")}
            for f in payload["filings"][:3]
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SERFF Filing Access crop-filing extractor")
    ap.add_argument("--state", required=True, help="2-letter state code, e.g. IA")
    ap.add_argument("--companies", default="",
                    help="Comma-separated company names (default: the AIP entity list)")
    ap.add_argument("--toi", default=DEFAULT_TOI, help=f"TOI menu label (default '{DEFAULT_TOI}')")
    ap.add_argument("--no-details", action="store_true",
                    help="Skip per-filing summary pages (no dates/disposition)")
    ap.add_argument("--headed", action="store_true", help="Run a visible browser (debugging)")
    ap.add_argument("--out", default="", help="Output JSON path override")
    args = ap.parse_args(argv)

    companies = [c.strip() for c in args.companies.split(",") if c.strip()] or \
        list(AIP_COMPANY_TERMS.keys())

    cfg = None
    try:  # optional: pick up the project's configured browser UA
        from .. import config as _config
        cfg = _config.load()
    except Exception:
        pass

    out_path = Path(args.out) if args.out else None
    payload = run_state(
        args.state, companies, cfg,
        toi_label=args.toi, details=not args.no_details,
        headless=not args.headed, out_path=out_path,
    )
    print(json.dumps(_summary(payload), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
