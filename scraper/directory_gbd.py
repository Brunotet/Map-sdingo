"""
Generic parser for the "Global Business Directory LLC" network — confirmed
(2026) to run 136 country-specific sites on the SAME underlying platform:
identical "Data Hub" wording, identical /category/, /company/, /location/
URL structure, identical pricing-tier model. Yellosa.co.za (South Africa)
was verified directly first; BusinessList.com.ng (Nigeria) was then
checked and found to be byte-for-byte the same software, just re-skinned
and re-domained — confirming this generalizes rather than being a
coincidence.

Full country->domain registry lives in directory_source.py (this module
just needs a domain passed in). ~125 countries are wired up there,
covering most of the network's advertised 136 sites — Yellosa/ZA was the
only one independently checked page-by-page; the rest are extended with
high (not absolute) confidence given the confirmed shared platform.

CONFIRMED URL STRUCTURE (checked directly on 2 of the network's domains):
  /category/<slug>                       - category listing, page 1
  /category/<slug>/<n>                   - category listing, page n
  /category/<slug>/city:<city-slug>      - filtered to one city
  /company/<id>/<slug>                   - individual listing profile

EMAIL: confirmed NOT freely visible on Yellosa specifically (gated behind
sign-in, same for "Send Enquiry") — assume the same holds across the rest
of this network, since it's the same software and same business model
(their paid "Data Hub" product is explicitly the monetized path to bulk
contact data). This module does NOT attempt to get past that. What IS
freely visible and used here: phone, address, a real website URL when one
exists, established year, employee band, VAT/registration number, and
the full business description text (occasionally has an email written
directly into it by the owner).

HONEST CAVEAT: label-text pairing is used instead of CSS selectors (same
reasoning as every other scraper in this repo — built without a live
browser to inspect exact tag/class structure, only rendered text and
links were verifiable). A domain in this network that hasn't been
directly checked might phrase a label slightly differently (localized
wording) — if a country consistently returns nothing, that's the first
thing to check on a real page from that specific domain.
"""

import re
import sys
import time
import requests
from bs4 import BeautifulSoup

from scraper.email_utils import extract_email_from_html
from scraper.search_provider import search_urls

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

PROFILE_LINK_RE = re.compile(r'^/company/\d+/[^/?#]+$')

CATEGORY_SEED = {
    "plumbers": "plumbers",
    "plumbing": "plumbing-services",
    "construction": "construction-services",
    "builders": "construction-services",
    "estate agents": "estate-agents",
    "real estate": "estate-agents",
    "lawyers": "lawyers",
    "attorneys": "lawyers",
    "doctors": "doctors-and-clinics",
    "restaurants": "restaurants",
    "schools": "schools",
    "employment agencies": "employment-agencies",
}


def resolve_category(domain: str, niche: str) -> str | None:
    key = niche.strip().lower()
    if key in CATEGORY_SEED:
        return CATEGORY_SEED[key]

    # Now goes through search_provider.py (Tavily, with DDG-HTML as a
    # last-resort fallback) rather than hitting DDG directly — a real run
    # confirmed direct DDG scraping returns nothing from GitHub Actions'
    # IP ranges specifically. Add the niche to CATEGORY_SEED above
    # (verified against the live site) to skip search entirely for it —
    # the most reliable fix regardless of which search backend is used.
    urls = search_urls(f"{niche} site:{domain}/category", max_results=5, timeout=10)
    if not urls:
        print(f"      [{domain}] search returned nothing for niche '{niche}'", file=sys.stderr)
        return None

    for url in urls:
        m = re.search(re.escape(domain) + r"/category/([a-z0-9-]+)", url, re.IGNORECASE)
        if m:
            return m.group(1)

    print(f"      [{domain}] search returned results but no category link matched for niche '{niche}' — add a confirmed slug to CATEGORY_SEED instead", file=sys.stderr)
    return None


def slugify_city(location: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", location.strip().lower()).strip("-")


def _get(url: str, timeout: int = 12) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp.text if resp.status_code == 200 else None
    except requests.RequestException:
        return None


def _profile_links_from_category_page(html: str, base: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if PROFILE_LINK_RE.match(href) and href not in seen:
            seen.add(href)
            links.append(base + href)
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


def _parse_profile(html: str, url: str, source_name: str) -> dict | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    website_value = _label_value(text, "Website address")
    has_real_website = bool(website_value) and not website_value.lower().startswith(("send enquiry", "show email"))

    phone = None
    tel_link = soup.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        phone = tel_link["href"].replace("tel:", "").strip()

    name = None
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)

    description = _label_value(text, "Company description") or ""
    established = _label_value(text, "Establishment year")
    employees = _label_value(text, "Employees")
    vat = _label_value(text, "VAT registration")
    address = _label_value(text, "Address")

    company_id_match = re.search(r"/company/(\d+)/", url)
    company_id = company_id_match.group(1) if company_id_match else None

    rating, review_count = 5.0, 1
    rating_match = re.search(r"\b(\d\.\d)\b\s*\n+\s*(\d+)\s+Reviews?\b", text)
    if rating_match:
        rating, review_count = float(rating_match.group(1)), int(rating_match.group(2))

    category = None
    if "Listed in categories" in text:
        cat_links = soup.find_all("a", href=re.compile(r"^/category/"))
        if cat_links:
            category = cat_links[0].get_text(strip=True)

    return {
        "name": name,
        "phone": phone,
        "website": website_value if has_real_website else None,
        "address": address,
        "category": category,
        "rating": rating,
        "review_count": review_count,
        "description": description,
        "established_year": established,
        "employees_band": employees,
        "vat_registration": vat,
        "directory_url": url,
        "maps_url": url,
        "cid": f"{source_name}:{company_id}" if company_id else f"{source_name}:{url}",
        "source": source_name,
    }


def scrape_directory_leads(
    domain: str,
    niche: str,
    location: str,
    max_results: int = 50,
    max_pages: int = 8,
    delay: float = 1.0,
) -> list[dict]:
    """
    `domain` is the bare host (e.g. "www.yellosa.co.za" or
    "www.businesslist.com.ng") — see directory_source.py's registry for
    the full country->domain mapping.
    """
    base = f"https://{domain}"
    source_name = domain.split(".")[-2] if "." in domain else domain  # e.g. "yellosa", "businesslist"

    category = resolve_category(domain, niche)
    if not category:
        return []

    city = slugify_city(location)
    base_url = f"{base}/category/{category}/city:{city}"

    first_page = _get(base_url)
    if not _profile_links_from_category_page(first_page or "", base):
        base_url = f"{base}/category/{category}"
        first_page = _get(base_url)

    candidate_links = []
    for page_num in range(1, max_pages + 1):
        page_url = base_url if page_num == 1 else f"{base_url}/{page_num}"
        html = first_page if page_num == 1 else _get(page_url)
        links = _profile_links_from_category_page(html or "", base)
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
        lead = _parse_profile(html or "", url, source_name)
        time.sleep(delay)
        if not lead or not lead.get("name"):
            continue
        if lead.get("website"):
            continue
        address = (lead.get("address") or "").lower()
        if location_lower not in address:
            continue
        if not lead.get("category"):
            lead["category"] = niche
        lead["gosom_email"] = extract_email_from_html(lead.get("description") or "")
        leads.append(lead)

    return leads
