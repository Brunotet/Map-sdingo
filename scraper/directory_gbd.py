"""
Generic parser for the "Global Business Directory LLC" network — confirmed
(2026) to run ~136 country-specific sites on the SAME underlying platform
(Yellosa.co.za for South Africa, BusinessList.com.ng for Nigeria, both
independently verified to be identical software). Full country->domain
registry lives in directory_source.py.

CONFIRMED URL STRUCTURE:
  /category/<slug>                       - category listing, page 1
  /category/<slug>/<n>                   - category listing, page n
  /category/<slug>/city:<city-slug>      - filtered to one city
  /company/<id>/<slug>                   - individual listing profile

WHOLE-COUNTRY MODE (added 2026-09): the unfiltered /category/<slug> page
(no city: filter) looks like it should cover a whole country — it's the
fallback this code already used whenever a city: filter came up empty —
but a real run showed it is NOT a comprehensive national index (only 2
results for a niche with far more listings than that). It behaves like a
limited top-listings view, not a full paginated country index. Real
whole-country coverage means looping real cities (geo_cities.py) and
running the same per-city scrape that's already proven to work well
(e.g. the 50-lead London MisterWhat run), then aggregating and
deduplicating by cid across cities.

EMAIL: confirmed NOT freely visible on this network — Yellosa checked
directly: "Show Email" AND "Send Enquiry" both require sign-in
(/sign-in/... redirect). This module does not attempt to get past that.
What IS freely visible: phone, address, a real website when one exists,
established year, employee band, VAT/registration number, full
description text (occasionally has an email typed directly into it).

Website classification reuses filters.classify_website() so a
Facebook/Instagram link listed as the "website" is correctly treated as
"no real website" (consistent with the rule everywhere else in this
pipeline) rather than wrongly excluding the lead.
"""

import re
import sys
import time
import requests
from bs4 import BeautifulSoup

from scraper.email_utils import extract_email_from_html
from scraper.search_provider import search_urls
from scraper.filters import classify_website

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

    website_text = _label_value(text, "Website address")
    website_class = classify_website(website_text)

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
        "website": website_text if website_class == "social" else None,
        "_website_class": website_class,
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


def _scrape_one_location(
    domain: str,
    niche: str,
    location: str,
    max_results: int,
    max_pages: int,
    delay: float,
    source_name: str,
) -> list[dict]:
    base = f"https://{domain}"
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
        if lead.pop("_website_class", "none") == "real":
            continue
        address = (lead.get("address") or "").lower()
        if location_lower not in address:
            continue
        if not lead.get("category"):
            lead["category"] = niche
        lead["gosom_email"] = extract_email_from_html(lead.get("description") or "")
        lead["scraped_location"] = location  # which city this actually came from — the run-level "location" isn't this in whole-country mode
        leads.append(lead)

    return leads


def scrape_directory_leads(
    domain: str,
    niche: str,
    location: str,
    max_results: int = 50,
    max_pages: int = 8,
    delay: float = 0.4,
    whole_country: bool = False,
    country: str | None = None,
    max_cities: int = 15,
    max_workers: int = 4,
) -> list[dict]:
    """
    `domain` is the bare host (e.g. "www.yellosa.co.za"). See
    directory_source.py's registry for the full country->domain mapping.

    whole_country=True loops real cities (via geo_cities.get_cities) and
    aggregates+dedupes results across them, rather than relying on the
    unfiltered category page's (not actually comprehensive) single view.
    Cities are scraped CONCURRENTLY (max_workers at a time, default 4) —
    each city's scrape is pure network I/O (no shared browser/state, no
    Playwright involved on this network), so threading gives a close-to-
    linear speedup here with no correctness tradeoff. Aggregation/dedup
    happens after all threads complete, so there's no race on shared state
    during the parallel phase itself.
    """
    source_name = domain.split(".")[-2] if "." in domain else domain

    if not whole_country:
        return _scrape_one_location(domain, niche, location, max_results, max_pages, delay, source_name)

    from scraper.geo_cities import get_cities
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cities = get_cities(country or "", max_cities=max_cities)
    if not cities:
        print(f"      [{domain}] no city list available for country '{country}' — falling back to a single unfiltered scrape", file=sys.stderr)
        cities = [location] if location else [""]

    all_leads = []
    seen_cids = set()
    batches = [cities[i:i + max_workers] for i in range(0, len(cities), max_workers)]
    for batch in batches:
        if len(all_leads) >= max_results:
            break
        print(f"      [{domain}] whole-country: scraping '{niche}' in {', '.join(batch)} (parallel, {max_workers} workers)... ({len(all_leads)}/{max_results} so far)", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(_scrape_one_location, domain, niche, city, max_results, max_pages, delay, source_name): city
                for city in batch
            }
            for future in as_completed(futures):
                city = futures[future]
                try:
                    city_leads = future.result()
                except Exception as e:
                    print(f"      [{domain}] city '{city}' scrape failed ({e}) — skipping it, others unaffected", file=sys.stderr)
                    continue
                for lead in city_leads:
                    if lead["cid"] not in seen_cids:
                        seen_cids.add(lead["cid"])
                        all_leads.append(lead)

    return all_leads[:max_results]
