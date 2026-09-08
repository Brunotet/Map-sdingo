"""
Best-effort enrichment of leads that have no email yet.

Honesty note (read this before relying on it): Facebook and Instagram gate
most profile data behind a login wall for automated/non-logged-in requests.
This module only reads what's in the public, logged-out HTML/meta tags —
which sometimes includes a bio-line email or phone, and sometimes doesn't.
Treat this as a bonus enrichment pass, not a guaranteed email source. It
will legitimately come back empty for a large chunk of leads, especially
Instagram. When it does, WhatsApp (from the Maps phone number) is the
reliable fallback channel, not email.
"""

import re
import time
import requests
from urllib.parse import urlparse, urlunparse

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
FB_LINK_RE = re.compile(r'https?://(?:www\.|web\.|m\.)?facebook\.com/[^\s"\'<>]+', re.IGNORECASE)
IG_LINK_RE = re.compile(r'https?://(?:www\.)?instagram\.com/[^\s"\'<>]+', re.IGNORECASE)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _extract_email(text: str) -> str | None:
    matches = EMAIL_RE.findall(text)
    # filter out common false positives (image/js asset filenames etc.)
    matches = [m for m in matches if not m.lower().endswith((".png", ".jpg", ".svg", ".js", ".css"))]
    return matches[0] if matches else None


def _to_mobile_facebook_url(fb_url: str) -> str:
    """Rewrite any Facebook host (www.facebook.com, web.facebook.com, bare
    facebook.com, m.facebook.com already, fb.com) to m.facebook.com — the
    mobile version is less aggressively login-gated than desktop.

    BUG FIXED: the previous version did a naive string .replace(), which
    mangled "web.facebook.com" (the host Maps often lists for Business
    Pages that never set a vanity name — shows up as a profile.php?id=...
    URL) into "web.m.facebook.com", a domain that doesn't exist. That
    silently broke email enrichment for every lead whose Facebook link
    used that host, with no error surfaced — enrichment just always came
    back empty for them. Proper URL parsing avoids this category of bug
    for any current or future Facebook subdomain variant.
    """
    parsed = urlparse(fb_url if "://" in fb_url else f"https://{fb_url}")
    if parsed.netloc.endswith("facebook.com"):
        parsed = parsed._replace(netloc="m.facebook.com")
    return urlunparse(parsed)


def enrich_from_facebook(fb_url: str, timeout: int = 10) -> dict:
    """Try the public mobile FB page (m.facebook.com), which is less login-gated
    than the desktop version, and pull an email + raw bio text if visible."""
    result = {"email": None, "bio_text": None}
    try:
        mobile_url = _to_mobile_facebook_url(fb_url)
        resp = requests.get(mobile_url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            result["email"] = _extract_email(resp.text)
            result["bio_text"] = resp.text
    except requests.RequestException:
        pass
    return result


def enrich_from_instagram(ig_url: str, timeout: int = 10) -> dict:
    """Try IG's public page meta description, which occasionally contains a
    bio email/text. Instagram blocks this far more aggressively than
    Facebook — expect a low hit rate on both fronts."""
    result = {"email": None, "bio_text": None}
    try:
        resp = requests.get(ig_url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            result["email"] = _extract_email(resp.text)
            result["bio_text"] = resp.text
    except requests.RequestException:
        pass
    return result


def enrich_business(business: dict, delay: float = 1.5) -> dict:
    """Mutates a copy of `business`, adding 'email' if found via its social
    link, plus an internal '_bio_text' field (raw page text) that the
    intent-signal step reads for DM-to-order / checkout phrasing — that
    field is stripped before the final leads.json is written.

    Checks up to two sources, not just whichever single link Maps happened
    to give us in "website":
    1. Whichever platform (Facebook or Instagram) the Maps "website" field
       actually points to.
    2. If that page's bio links to the *other* platform (many businesses
       cross-link FB<->IG even when only one is registered with Google),
       follow that too — only if we still don't have an email.

    (gosom's own website-email crawl and the Maps "description" text are
    checked earlier, for free, in run_gmaps_scraper.py — this function only
    runs at all for leads still missing an email after those.)

    `delay` is a polite pause between requests so we're not hammering FB/IG.
    """
    b = dict(business)
    social = b.get("website") or ""

    if "instagram.com" in social:
        primary = enrich_from_instagram(social)
        cross_pattern, cross_fetch = FB_LINK_RE, enrich_from_facebook
    elif "facebook.com" in social or "fb.com" in social:
        primary = enrich_from_facebook(social)
        cross_pattern, cross_fetch = IG_LINK_RE, enrich_from_instagram
    else:
        primary = {"email": None, "bio_text": None}
        cross_pattern, cross_fetch = None, None

    if not b.get("email") and primary.get("email"):
        b["email"] = primary["email"]
    if primary.get("bio_text"):
        b["_bio_text"] = primary["bio_text"]

    time.sleep(delay)

    if not b.get("email") and cross_pattern and primary.get("bio_text"):
        m = cross_pattern.search(primary["bio_text"])
        if m:
            secondary = cross_fetch(m.group(0))
            if secondary.get("email"):
                b["email"] = secondary["email"]
            if secondary.get("bio_text") and not b.get("_bio_text"):
                b["_bio_text"] = secondary["bio_text"]
            time.sleep(delay)

    return b
