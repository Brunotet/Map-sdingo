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

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
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


def enrich_from_facebook(fb_url: str, timeout: int = 10) -> dict:
    """Try the public mobile FB page (m.facebook.com), which is less login-gated
    than the desktop version, and pull an email + raw bio text if visible."""
    result = {"email": None, "bio_text": None}
    try:
        mobile_url = fb_url.replace("www.facebook.com", "m.facebook.com").replace(
            "facebook.com", "m.facebook.com"
        )
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
    `delay` is a polite pause between requests so we're not hammering FB/IG.
    """
    b = dict(business)
    social = b.get("website") or ""
    bio_text = None

    if "instagram.com" in social:
        r = enrich_from_instagram(social)
    elif "facebook.com" in social or "fb.com" in social:
        r = enrich_from_facebook(social)
    else:
        r = {"email": None, "bio_text": None}

    if not b.get("email") and r.get("email"):
        b["email"] = r["email"]
    bio_text = r.get("bio_text")
    if bio_text:
        b["_bio_text"] = bio_text

    time.sleep(delay)
    return b
