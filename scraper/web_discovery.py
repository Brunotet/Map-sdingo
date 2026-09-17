"""
For leads where Google Maps has NO website/social link at all (empty
"website" field — common, as real data has shown: most small local
businesses simply never registered one with their Business Profile), this
does a web search for their Facebook or Instagram page, so the
enrichment pipeline (enrich.py) has somewhere to look. Without this, those
leads have zero path to an email no matter how good the FB/IG scraping is
— there's nothing to scrape.

Search itself now goes through search_provider.py (Tavily API, free
tier, with a DDG-HTML last-resort fallback) instead of hitting
DuckDuckGo's HTML page directly — a real run confirmed that direct
approach silently returns nothing from GitHub Actions' IP ranges. See
search_provider.py's docstring for the full story and setup steps.

HONEST CAVEAT: even with a real search API behind it, this is still
"find their social page via search," not guaranteed — a business with no
FB/IG presence anywhere just won't have anything to find here, same as
before.
"""

import re
import time
import requests
from scraper.email_utils import extract_email_from_html
from scraper.search_provider import search_urls

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

FB_RESULT_RE = re.compile(r'https?://(?:www\.|web\.|m\.)?facebook\.com/', re.IGNORECASE)
IG_RESULT_RE = re.compile(r'https?://(?:www\.)?instagram\.com/', re.IGNORECASE)

# South African business directories confirmed (2026) to be active and to
# collect an email per listing. Kept short and deliberately checked-not-
# guessed — add more here once you've confirmed a directory actually
# publishes emails rather than gating them behind a paid unlock.
SA_DIRECTORY_SITES = ["yellosa.co.za", "thebusinessdirectory.co.za"]


def find_social_link(business_name: str, location: str, timeout: int = 10) -> str | None:
    """
    Searches "<business name> <location> facebook OR instagram" and
    returns the first Facebook or Instagram URL found in the results, or
    None. Facebook is preferred over Instagram when both appear, since
    Facebook Pages tend to have more bio text (and thus a better shot at
    an email) than Instagram profiles.
    """
    query = f"{business_name} {location} facebook OR instagram"
    urls = search_urls(query, max_results=5, timeout=timeout)

    fb = next((u for u in urls if FB_RESULT_RE.match(u)), None)
    if fb:
        return fb
    ig = next((u for u in urls if IG_RESULT_RE.match(u)), None)
    if ig:
        return ig
    return None


def find_directory_email(business_name: str, location: str, timeout: int = 10, delay: float = 1.5) -> str | None:
    """
    NOT CURRENTLY CALLED ANYWHERE IN THE PIPELINE — kept for reference,
    not wired into main.py.

    Both directories originally listed here were checked directly against
    their live sites and found not to work for this purpose:
      - Yellosa.co.za: emails ARE collected per listing, but confirmed
        gated behind a required sign-in ("Show Email" links to
        /sign-in/email:<id>) — not freely scrapable. (Yellosa is now used
        differently — as the PRIMARY lead source in directory_source.py,
        for its freely-visible fields: phone, address, website, business
        description, etc. — just not for the email specifically.)
      - thebusinessdirectory.co.za: has active bot detection that blocks
        automated page fetches outright.

    Left in place in case a genuinely open SA directory turns up later —
    add it to SA_DIRECTORY_SITES and this function should work as
    written, but verify against the live site first (view a real listing
    page yourself) rather than assuming it behaves like these two did.
    """
    for site in SA_DIRECTORY_SITES:
        query = f"{business_name} {location} site:{site}"
        urls = search_urls(query, max_results=5, timeout=timeout)
        links = [u for u in urls if site in u]
        if not links:
            time.sleep(delay)
            continue

        try:
            resp = requests.get(links[0], headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                email = extract_email_from_html(resp.text)
                if email:
                    return email
        except requests.RequestException:
            pass

        time.sleep(delay)

    return None
