"""
For leads where Google Maps has NO website/social link at all (empty
"website" field — common, as real data has shown: most small local
businesses simply never registered one with their Business Profile), this
does a free web search for their Facebook or Instagram page, so the
enrichment pipeline (enrich.py) has somewhere to look. Without this, those
leads have zero path to an email no matter how good the FB/IG scraping is
— there's nothing to scrape.

Also searches South African business directories directly for a listed
email — several (Yellosa.co.za confirmed as of 2026: 600k+ SA listings,
updated daily, collects "Company email" as a structured listing field)
require an email at signup, unlike Google Business Profile where it's
optional and rarely public. This is a genuinely higher-yield source than
FB/IG bio scraping for businesses that have listed themselves on one of
these — worth trying as its own step, not just a Facebook/Instagram
substitute.

Uses DuckDuckGo's HTML endpoint (html.duckduckgo.com) — not an official
API, no key, no paid tier, and it's the same result set a browser gets,
just as parseable HTML instead of a JS-rendered page. This is the
"free tools only" option; Bing/Google both require paid API keys at any
real volume.

HONEST CAVEAT: this isn't an official, stable API — DuckDuckGo can change
this page's structure or rate-limit automated traffic without notice. If
`find_social_link` or `find_directory_email` start returning None for
everything, check this page manually in a browser first before assuming
the regex needs fixing.
"""

import re
import time
import requests
from urllib.parse import quote
from scraper.email_utils import extract_email_from_html

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

FB_RESULT_RE = re.compile(r'https?://(?:www\.|web\.|m\.)?facebook\.com/[^\s"\'<>&]+', re.IGNORECASE)
IG_RESULT_RE = re.compile(r'https?://(?:www\.)?instagram\.com/[^\s"\'<>&]+', re.IGNORECASE)

# South African business directories confirmed (2026) to be active and to
# collect an email per listing. Kept short and deliberately checked-not-
# guessed — add more here once you've confirmed a directory actually
# publishes emails rather than gating them behind a paid unlock.
SA_DIRECTORY_SITES = ["yellosa.co.za", "thebusinessdirectory.co.za"]


def _ddg_search(query: str, timeout: int = 10) -> str | None:
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp.text if resp.status_code == 200 else None
    except requests.RequestException:
        return None


def _result_links(html: str) -> list[str]:
    """DuckDuckGo's HTML results wrap each link in an <a class="result__a" href="...">."""
    if not html:
        return []
    return re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)


def find_social_link(business_name: str, location: str, timeout: int = 10) -> str | None:
    """
    Searches "<business name> <location> facebook OR instagram" and
    returns the first Facebook or Instagram URL found in the results, or
    None. Facebook is preferred over Instagram when both appear, since
    Facebook Pages tend to have more bio text (and thus a better shot at
    an email) than Instagram profiles.
    """
    query = f"{business_name} {location} facebook OR instagram"
    text = _ddg_search(query, timeout=timeout)
    if not text:
        return None

    fb = FB_RESULT_RE.search(text)
    if fb:
        return fb.group(0)
    ig = IG_RESULT_RE.search(text)
    if ig:
        return ig.group(0)
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
        search_html = _ddg_search(query, timeout=timeout)
        links = [l for l in _result_links(search_html or "") if site in l]
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
