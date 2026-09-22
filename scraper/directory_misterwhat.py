"""
MisterWhat is the SAME underlying directory platform running localized
instances across many countries — same URL taxonomy, same "show email"
mechanism — just a different base domain per country. Full domain
registry lives in directory_source.py.

TWO BUGS FOUND AND FIXED (2026-09) BY ACTUALLY CLICKING THROUGH A REAL
PROFILE PAGE:
1. Website false-negative — MisterWhat shows the website as a plain link
   under "Contacts:" with no text label; fixed with bounded
   "Contacts"->"Established" HTML slicing + filters.classify_website().
2. Email false-negative — "show email" is a genuine no-login client-side
   reveal (confirmed: clicking it just adds a # to the URL, the real
   address appears inline); fixed with a Playwright second pass that
   actually clicks it, only for leads that already passed the (cheap,
   static) eligibility check.

WHOLE-COUNTRY MODE (added 2026-09): MisterWhat's URLs are structured
per-city (e.g. /greater-london/london/876_london/builders), so there's
no single "whole country" browse page the way the GBD network's
unfiltered category page superficially looks like one. Real
whole-country coverage means looping real cities (geo_cities.py) and
running the same per-city scrape+bootstrap for each, aggregating and
deduplicating by cid.
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

PROFILE_LINK_RE = re.compile(r'^/company/\d+-[^/?#]+$')
CATEGORY_LINK_RE = re.compile(r'^/[a-z0-9-]+/[a-z0-9-]+/\d+_[a-z0-9-]+/[a-z0-9-]+$')

VERIFIED_CATEGORY_URLS = {
    ("misterwhat.co.uk", "builders", "london"): "https://www.misterwhat.co.uk/greater-london/london/876_london/builders",
}


def _get(url: str, timeout: int = 12) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp.text if resp.status_code == 200 else None
    except requests.RequestException:
        return None


def _bootstrap_category_url(domain: str, niche: str, location: str) -> str | None:
    seed_key = (domain, niche.strip().lower(), location.strip().lower())
    if seed_key in VERIFIED_CATEGORY_URLS:
        return VERIFIED_CATEGORY_URLS[seed_key]

    urls = search_urls(f"{niche} {location} site:{domain}", max_results=5)
    company_links = [u for u in urls if f"{domain}/company/" in u]
    if not company_links:
        print(f"      [misterwhat] search returned nothing usable for {domain}/{niche}/{location}", file=sys.stderr)
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


def _contacts_section_html(html: str, domain: str) -> str:
    start = html.find("Contacts")
    if start == -1:
        return html
    end = html.find("Established", start)
    return html[start:end] if end != -1 else html[start:start + 4000]


def _find_website_in_section(section_html: str, domain: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(section_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(("http://", "https://")):
            continue
        if domain in href:
            continue
        return href, classify_website(href)
    return None, "none"


def _parse_profile_static(html: str, url: str, domain: str) -> dict | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    name = None
    h1 = soup.find("h1") or soup.find("h2")
    if h1:
        name = h1.get_text(strip=True)
        name = re.sub(r"^.*? in ", "", name) if " in " in name and len(name) > 40 else name

    phone = None
    tel_link = soup.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        phone = tel_link["href"].replace("tel:", "").strip()

    address = _label_value(text, "Address") or ""
    postcode = _label_value(text, "Postcode")
    if postcode:
        address = f"{address}, {postcode}"

    description = _label_value(text, "Description") or ""

    contacts_html = _contacts_section_html(html, domain)
    website_value, website_class = _find_website_in_section(contacts_html, domain)
    email = extract_email_from_html(contacts_html)

    company_id_match = re.search(r"/company/(\d+)-", url)
    company_id = company_id_match.group(1) if company_id_match else None

    category = None
    cat_links = soup.find_all("a", href=CATEGORY_LINK_RE)
    if cat_links:
        category = cat_links[0].get_text(strip=True)

    return {
        "name": name,
        "phone": phone,
        "website": website_value if website_class == "social" else None,
        "_website_class": website_class,
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


def _reveal_email_playwright(page, url: str, domain: str, timeout_ms: int = 15000) -> str | None:
    try:
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    except Exception:
        return None
    try:
        show_email = page.get_by_text("show email", exact=False).first
        if show_email.count() > 0:
            show_email.click(timeout=3000)
            page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        html = page.content()
    except Exception:
        return None
    contacts_html = _contacts_section_html(html, domain)
    return extract_email_from_html(contacts_html)


def _scrape_one_location_static(
    domain: str,
    niche: str,
    location: str,
    max_results: int,
    max_pages: int,
    delay: float,
) -> list[dict]:
    """Crawl + parse only — no Playwright, no email reveal. Safe to run
    from multiple threads concurrently (pure network I/O, no shared
    browser state)."""
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
        lead = _parse_profile_static(html or "", url, domain)
        time.sleep(delay)
        if not lead or not lead.get("name"):
            continue
        if lead.pop("_website_class", "none") == "real":
            continue
        address = (lead.get("address") or "").lower()
        if location_lower not in address and location_lower.replace(" ", "-") not in url.lower():
            continue
        if not lead.get("category"):
            lead["category"] = niche
        lead["scraped_location"] = location
        leads.append(lead)

    return leads


def _reveal_emails_for_leads(leads: list[dict], domain: str) -> None:
    """ONE Playwright browser session, used to reveal emails for however
    many leads (from one city or many combined) still need it. Mutates
    `leads` in place. Consolidating into a single browser launch here
    (rather than one launch per city, as an earlier version did) avoids
    paying real browser-startup overhead repeatedly — meaningful when
    whole-country mode means this could otherwise happen up to
    max_cities times per run."""
    still_missing = [l for l in leads if not l.get("gosom_email")]
    if not still_missing:
        return
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            revealed = 0
            for lead in still_missing:
                email = _reveal_email_playwright(page, lead["directory_url"], domain)
                if email:
                    lead["gosom_email"] = email
                    revealed += 1
            browser.close()
        print(f"      [misterwhat] revealed {revealed}/{len(still_missing)} emails via 'show email' click", file=sys.stderr)
    except ImportError:
        print("      [misterwhat] playwright not installed — skipping email reveal pass", file=sys.stderr)
    except Exception as e:
        print(f"      [misterwhat] email reveal pass failed entirely ({e})", file=sys.stderr)


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
    whole_country=True loops real cities (geo_cities.get_cities),
    scraping them CONCURRENTLY (max_workers at a time — safe, since the
    static crawl+parse has no shared browser state), then runs the
    Playwright email-reveal pass exactly ONCE across the combined,
    deduplicated result set — not once per city.
    """
    if not whole_country:
        leads = _scrape_one_location_static(domain, niche, location, max_results, max_pages, delay)
        _reveal_emails_for_leads(leads, domain)
        return leads

    from scraper.geo_cities import get_cities
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cities = get_cities(country or "", max_cities=max_cities)
    if not cities:
        print(f"      [{domain}] no city list available for country '{country}' — falling back to a single scrape", file=sys.stderr)
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
                executor.submit(_scrape_one_location_static, domain, niche, city, max_results, max_pages, delay): city
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

    all_leads = all_leads[:max_results]
    print(f"      [{domain}] whole-country crawl done ({len(all_leads)} leads across {len(cities)} cities tried) — now revealing emails in one pass...", file=sys.stderr)
    _reveal_emails_for_leads(all_leads, domain)
    return all_leads
