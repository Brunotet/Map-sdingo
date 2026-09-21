"""
Gets a list of major cities/towns for a country, to power whole-country
scraping — loop city-by-city and aggregate, rather than relying on a
directory's "unfiltered/national" category page. That page turned out
NOT to be a comprehensive national index — a real run returned only 2
results nationally for a niche with far more listings than that; it
behaves like a limited top-listings view, not a full paginated country
index. Looping real cities and running the (already-proven-working)
per-city scrape on each is the actual fix.

Uses countries.dev's free cities API (https://countries.dev/cities-api)
— built on GeoNames data, served keyless: no signup, no API key, no
quota tier. Confirmed live (2026):
    GET https://countries.dev/cities?country=<ISO2>&limit=N
returns that country's biggest cities ranked by population, as JSON.

HONEST CAVEAT: the exact JSON response shape (a bare list vs. a
{"cities": [...]}-style wrapper, and the exact field name for a city's
name) wasn't confirmed with a live sample response at build time — the
docs page shown described the endpoint and gave a curl example, not a
sample JSON body. get_cities() below handles several plausible shapes
defensively, but if it keeps returning nothing for real countries, check
the actual response shape with `curl` and adjust the parsing here first
before assuming something else is broken.
"""

import requests

# Fallback lists for the two countries most tested in this build, used
# only if the API call fails outright (network issue, unexpected response
# shape) — so ZA/GB whole-country runs keep working even if countries.dev
# has an outage or its shape turns out to differ from what's handled here.
FALLBACK_CITIES = {
    "ZA": ["Johannesburg", "Cape Town", "Durban", "Pretoria", "Port Elizabeth",
           "Bloemfontein", "Nelspruit", "Polokwane", "Kimberley", "East London",
           "Pietermaritzburg", "Rustenburg", "George", "Witbank", "Welkom"],
    "GB": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Liverpool",
           "Bristol", "Sheffield", "Edinburgh", "Cardiff", "Newcastle", "Nottingham",
           "Leicester", "Coventry", "Belfast"],
}


def get_cities(country: str, max_cities: int = 15, timeout: int = 10) -> list[str]:
    """Returns up to `max_cities` city names for `country` (ISO-3166
    alpha-2), ranked by population, biggest first."""
    country = (country or "").strip().upper()
    try:
        resp = requests.get(
            "https://countries.dev/cities",
            params={"country": country, "limit": max_cities},
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("cities") or data.get("results") or data.get("data") or []
            else:
                items = []

            names = []
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("city")
                    if name:
                        names.append(name)
                elif isinstance(item, str):
                    names.append(item)
            if names:
                return names[:max_cities]
    except (requests.RequestException, ValueError):
        pass

    return FALLBACK_CITIES.get(country, [])[:max_cities]
