"""
Shared email-extraction logic used across enrich.py, web_discovery.py, and
run_gmaps_scraper.py — one place for the regex and the Cloudflare decode,
instead of three slightly-different copies.

WHY THE CLOUDFLARE DECODE MATTERS: many sites (business directories
especially) obfuscate mailto emails using Cloudflare's "Email Address
Obfuscation" feature — the visible HTML has no email text at all, just a
<span class="__cf_email__" data-cfemail="HEXSTRING">, decoded client-side
by a tiny JS snippet. A plain regex over the page text will find nothing
on these pages even though the email IS there. Decoding it is a simple
reversible XOR, documented publicly by Cloudflare itself (not a security
bypass — it's obfuscation against basic scraping, not encryption).
"""

import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
CF_EMAIL_RE = re.compile(r'data-cfemail="([a-f0-9]+)"', re.IGNORECASE)

_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".js", ".css", ".webp")


def _decode_cf_email(hex_str: str) -> str | None:
    try:
        data = bytes.fromhex(hex_str)
    except ValueError:
        return None
    if not data:
        return None
    key = data[0]
    decoded = bytes(b ^ key for b in data[1:])
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None


def extract_emails_from_html(html: str) -> list[str]:
    """
    Returns every plausible email found in a page — both plain-text matches
    and Cloudflare-obfuscated ones, decoded. Filters out obvious false
    positives (image/script filenames that happen to match the pattern).
    Order: plain-text matches first, then decoded Cloudflare ones.
    """
    if not html:
        return []

    found = []
    for m in EMAIL_RE.findall(html):
        if not m.lower().endswith(_ASSET_EXTENSIONS):
            found.append(m)

    for hex_str in CF_EMAIL_RE.findall(html):
        decoded = _decode_cf_email(hex_str)
        if decoded and EMAIL_RE.fullmatch(decoded):
            found.append(decoded)

    # de-dupe, preserve order
    seen = set()
    result = []
    for e in found:
        if e.lower() not in seen:
            seen.add(e.lower())
            result.append(e)
    return result


def extract_email_from_html(html: str) -> str | None:
    """Convenience wrapper — first match only, or None."""
    matches = extract_emails_from_html(html)
    return matches[0] if matches else None
