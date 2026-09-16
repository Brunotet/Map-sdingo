"""
South Africa directory source. Yellosa.co.za was the FIRST site in the
"Global Business Directory" network verified directly (category/city
browsing, company profiles, gated email — see directory_gbd.py's
docstring for the full picture, including how Yellosa turned out to be
one of 136 country sites on the same platform, not a standalone build).

This file is now a thin wrapper around directory_gbd.py so
directory_source.py's existing import keeps working unchanged.
"""

from scraper.directory_gbd import scrape_directory_leads as _scrape_gbd

YELLOSA_DOMAIN = "www.yellosa.co.za"


def scrape_directory_leads(niche: str, location: str, max_results: int = 50) -> list[dict]:
    return _scrape_gbd(YELLOSA_DOMAIN, niche, location, max_results=max_results)
