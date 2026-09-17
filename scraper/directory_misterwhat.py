"""
MisterWhat is the SAME underlying directory platform running localized
instances across many countries — same URL taxonomy, same "show email"
mechanism — just a different base domain per country:

  GB misterwhat.co.uk   US misterwhat.com      AU misterwhat-au.com
  FR misterwhat.fr      DE misterwhat.de       NL misterwhat.nl
  DK misterwhat.dk      PL misterwhat.pl       PT misterwhat.pt
  BR misterwhat.com.br  AR misterwhat.com.ar   CA ca.misterwhat.com

VERIFIED DIRECTLY against the live site (GB only): category+city browsing
is plain server-rendered HTML, no login needed to browse. Company profile
pages show phone/address/website/description/employee count/owner name
freely. Email sits behind a "show email" control whose link is `#` (a
client-side reveal), NOT a sign-in redirect like Yellosa's — meaning the
email is very likely present in that page's raw HTML/JS already, just
not rendered by default. This module runs the full email_utils extractor
(plain-text regex + Cloudflare-obfuscation decode) against the whole page
to try to catch it either way.

UNVERIFIED for the other 11 domains — same platform, so very likely the
same structure, but not checked directly the way GB was. Rather than
hardcode a guessed URL shape per country (city/region IDs, category slug
conventions) and risk it being subtly wrong for markets I haven't looked
at, this BOOTSTRAPS the real URL structure at runtime instead: search for
the business on that specific country domain, then read the *actual*
category link straight off a real company page found there, rather than
constructing one from assumptions. If a country's structure does differ,
this fails gracefully (finds nothing, main.py's Maps fallback fills in) —
it doesn't break.
"""

import re
import sys
import time
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup

from scraper.email_utils import extract_email_from_html, extract_emails_from_html

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

PROFILE_LINK_RE = re.compile(r'^/company/\d+-[^/?#]+$')
CATEGORY_LINK_RE = re.compile(r'^/[a-z0-9-]+/[a-z0-9-]+/\d+_[a-z0-9-]+/[a-z0-9-]+$')

# Real, confirmed category-listing URLs — checked directly against the
# live site, not discovered via search. Bypasses the DDG bootstrap
# entirely for these exact (domain, niche, location) combos, which
# matters because that bootstrap has been observed returning nothing
# when run from a GitHub Actions runner specifically — DuckDuckGo (like
# most search engines) is known to rate-limit or silently empty-result
# traffic from CI/cloud IP ranges, even when the exact same query works
# fine from an ordinary residential/office connection. Add a confirmed
# URL here any time you verify one by hand, the same way this one was
# found — it sidesteps that CI-IP problem completely for that combo on
# every future run.
VERIFIED_CATEGORY_URLS = {
    ("misterwhat.co.uk", "builders", "london"): "https://www.misterwhat.co.uk/greater-london/london/876_london/builders",
}


def _get(url: str, timeout: int = 12) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp.text if resp.status_code == 200 else None
    except requests.RequestException:
        return None


def _ddg_search(query: str, timeout: int = 10) -> str | None:
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            print(f"      [misterwhat] DDG search returned HTTP {resp.status_code} for: {query}", file=sys.stderr)
            return None
        if len(resp.text) < 500:
            # DDG sometimes returns a short "blocked"/CAPTCHA page rather than
            # a real error status — a suspiciously tiny response body is a
            # tell that this wasn't a normal results page.
            print(f"      [misterwhat] DDG search response looked too short ({len(resp.text)} chars) — possibly rate-limited/blocked for: {query}", file=sys.stderr)
        return resp.text
    except requests.RequestException as e:
        print(f"      [misterwhat] DDG search request failed ({e}) for: {query}", file=sys.stderr)
        return None


def _bootstrap_category_url(domain: str, niche: str, location: str) -> str | None:
    """
    Finds a REAL, working category-listing URL for this domain+niche+
    location by searching, then reading the actual category link off a
    real company page the search turns up — rather than guessing at that
    country's city-ID/region-slug conventions.
    """
    seed_key = (domain, niche.strip().lower(), location.strip().lower())
    if seed_key in VERIFIED_CATEGORY_URLS:
        return VERIFIED_CATEGORY_URLS[seed_key]

    search_html = _ddg_search(f"{niche} {location} site:{domain}")
    if not search_html:
        return None

    company_links = re.findall(r'class="result__a"[^>]*href="([^"]*' + re.escape(domain) + r'/company/\d+-[^"]+)"', search_html)
    if not company_links:
        print(f"      [misterwhat] search returned a page but no company links matched for {domain}/{niche}/{location} — DDG's result markup may have changed, or genuinely no results", file=sys.stderr)
        return None

    profile_html = _get(company_links[0])
    if not profile_html:
        return None

    soup = BeautifulSoup(profile_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if CATEGORY_LINK_RE.match(href):
            location_lower = location.strip().lower()
            if location_lower in href.lower() or location_lower.replace(" ", "-") in href.lower():
                return f"https://{domain}{href}"

    return None


def _profile_links_from_category_page(html: str, domain: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if PROFILE_LINK_RE.match(href) and href not in seen:
            seen.add(href)
            links.append(f"https://{domain}{href}")
    return links


def _label_value(text: str, label: str) -> str | None:
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if line == label:
            for nxt in lines[i + 1:]:
                if nxt:
                    return nxt
            return None
    return None


def _parse_profile(html: str, url: str) -> dict | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    name = None
    h1 = soup.find("h1") or soup.find("h2")
    if h1:
        name = h1.get_text(strip=True)
        name = re.sub(r"^.*? in ", "", name) if " in " in name and len(name) > 40 else name

    website_value = _label_value(text, "Website address") or _label_value(text, "Website")
    # a real <a> pointing off-domain right after "Website" is the strongest signal
    has_real_website = bool(website_value)

    phone = None
    tel_link = soup.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        phone = tel_link["href"].replace("tel:", "").strip()

    address = _label_value(text, "Address") or ""
    postcode = _label_value(text, "Postcode")
    if postcode:
        address = f"{address}, {postcode}"

    description = _label_value(text, "Description") or ""

    company_id_match = re.search(r"/company/(\d+)-", url)
    company_id = company_id_match.group(1) if company_id_match else None

    email = extract_email_from_html(html)  # tries plain-text + Cloudflare-decoded, whole page

    category = None
    cat_links = soup.find_all("a", href=re.compile(r"^/[a-z0-9-]+/[a-z0-9-]+/\d+_[a-z0-9-]+/[a-z0-9-]+$"))
    if cat_links:
        category = cat_links[0].get_text(strip=True)

    return {
        "name": name,
        "phone": phone,
        "website": website_value if has_real_website else None,
        "address": address,
        "category": category,
        "rating": 5.0,
        "review_count": 1,
        "description": description,
        "gosom_email": email,
        "directory_url": url,
        "maps_url": url,
        "cid": f"misterwhat:{company_id}" if company_id else f"misterwhat:{url}",
        "source": "misterwhat",
    }


def scrape_directory_leads(
    domain: str,
    niche: str,
    location: str,
    max_results: int = 50,
    max_pages: int = 8,
    delay: float = 1.0,
) -> list[dict]:
    category_url = _bootstrap_category_url(domain, niche, location)
    if not category_url:
        return []

    candidate_links = []
    for page_num in range(1, max_pages + 1):
        page_url = category_url if page_num == 1 else f"{category_url}/{page_num}"
        html = _get(page_url)
        links = _profile_links_from_category_page(html or "", domain)
        if not links:
            break
        candidate_links.extend(links)
        time.sleep(delay)
        if len(candidate_links) >= max_results * 3:
            break

    location_lower = location.strip().lower()
    leads = []
    for url in candidate_links:
        if len(leads) >= max_results:
            break
        html = _get(url)
        lead = _parse_profile(html or "", url)
        time.sleep(delay)
        if not lead or not lead.get("name"):
            continue
        if lead.get("website"):
            continue  # has a real site — not a target
        address = (lead.get("address") or "").lower()
        if location_lower not in address and location_lower.replace(" ", "-") not in url.lower():
            continue
        if not lead.get("category"):
            lead["category"] = niche
        leads.append(lead)

    return leads
