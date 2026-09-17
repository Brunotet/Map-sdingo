"""
Shared search interface — every function elsewhere that needs "search the
web for X" calls search_urls() here, instead of each module scraping
DuckDuckGo's HTML results page independently (the old approach).

WHY THE SWITCH: a real GitHub Actions run confirmed the DDG-HTML approach
returns empty results specifically from GitHub's runner IP ranges — the
identical query worked fine tested from elsewhere. Search engines commonly
rate-limit or silently empty-result CI/cloud IP ranges; scraping a search
engine's own web UI was never going to be stable for that reason, no
matter how correct the parsing regex was. Tavily is a real, authenticated
API built for AI-agent web search, so it isn't subject to that same
IP-reputation problem — this was verified as of Sept 2026 to still have a
genuinely free, no-card, no-trial-expiry tier.

SETUP REQUIRED: sign up free at tavily.com (email or Google/GitHub OAuth,
no card), copy the API key (starts with "tvly-") from the dashboard, set
it as the TAVILY_API_KEY GitHub Actions secret (Settings -> Secrets and
variables -> Actions -> New repository secret). Without it, every
function in this module returns an empty list (fails soft — whatever
called it just treats that as "nothing found," same as any other missing
signal) rather than crashing the run.

BUDGET: free tier is 1,000 searches/month, 1 credit per basic search,
resets the 1st of each month. Category-resolution searches are low
volume (a handful of distinct niches a month). The per-lead
FB/IG-discovery search in web_discovery.py is the one that could run up
to max_results times in a single scrape — that call site caps itself at
a configurable per-run limit specifically so one run can't burn the
month's whole budget; see MAX_SOCIAL_SEARCHES_PER_RUN there.

DDG-HTML kept as a last-resort fallback below (only used when Tavily
isn't configured or its call fails) — worse odds from CI specifically,
but free and worth trying rather than returning nothing outright.
"""

import os
import re
from urllib.parse import quote
import requests

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _tavily_search(query: str, max_results: int, timeout: int) -> list[str]:
    if not TAVILY_API_KEY:
        return []
    try:
        resp = requests.post(
            TAVILY_URL,
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [r["url"] for r in data.get("results", []) if r.get("url")]
    except (requests.RequestException, ValueError):
        return []


def _ddg_fallback_search(query: str, max_results: int, timeout: int) -> list[str]:
    """Last resort — same DDG-HTML approach as before, kept only as a
    second attempt when Tavily isn't set up or its call failed."""
    try:
        resp = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote(query)}",
            headers=HEADERS, timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text)
        return links[:max_results]
    except requests.RequestException:
        return []


def search_urls(query: str, max_results: int = 5, timeout: int = 10) -> list[str]:
    """
    Returns up to `max_results` result URLs for `query`. Tries Tavily
    first (if TAVILY_API_KEY is set), falls back to DDG-HTML scraping if
    that returns nothing. Returns an empty list — never raises — if both
    fail; every caller already treats "nothing found" as a normal,
    handled outcome.
    """
    urls = _tavily_search(query, max_results, timeout)
    if urls:
        return urls
    return _ddg_fallback_search(query, max_results, timeout)
