"""Registry of state SERFF Filing Access portals.

Most states expose filings through the shared NAIC portal at filingaccess.serff.com/sfa/home/<ST>.
A handful run their own portals (or don't publish P&C filings publicly); those are marked custom so
the connector reports them as pending instead of pretending to search them.
"""
from __future__ import annotations

SHARED_BASE = "https://filingaccess.serff.com/sfa/home/{state}"

# States known to run a separate portal / not use the shared NAIC access site. Extend as verified.
CUSTOM_PORTALS: dict[str, str] = {
    "CA": "https://interactive.web.insurance.ca.gov/",   # California DOI runs its own
    "NY": "https://myportal.dfs.ny.gov/",                # NY DFS
}


def portal_url(state: str) -> str:
    state = state.upper()
    if state in CUSTOM_PORTALS:
        return CUSTOM_PORTALS[state]
    return SHARED_BASE.format(state=state)


def is_shared(state: str) -> bool:
    return state.upper() not in CUSTOM_PORTALS
