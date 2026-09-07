"""
Detects buying-intent phrases in a business's own public bio/page text.
Business-level only — we never touch a personal profile, only what the
business Page itself publishes publicly (bio, link-in-bio).
"""

import re

DM_ORDER_PATTERNS = [
    r"\bdm\b.{0,15}\border\b",
    r"\bwhatsapp\b.{0,15}\border\b",
    r"\bmessage\b.{0,15}\border\b",
    r"\binbox\b.{0,15}\border\b",
    r"\border\b.{0,15}\bvia\b.{0,10}(dm|whatsapp|inbox)",
    r"\bto order\b",  # generic but nearly always precedes "DM/WhatsApp/call us"
]

CHECKOUT_PATTERNS = [
    r"\bshop now\b",
    r"\border online\b",
    r"\bbuy now\b",
    r"\bcheckout\b",
    r"\blinktr\.ee\b",  # link-in-bio tool often fronts an actual store
    r"\bshopify\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def extract_bio_signals(bio_text: str | None) -> dict:
    if not bio_text:
        return {"dm_order_flow": False, "checkout_present": False}
    return {
        "dm_order_flow": _matches_any(bio_text, DM_ORDER_PATTERNS),
        "checkout_present": _matches_any(bio_text, CHECKOUT_PATTERNS),
    }


# --- Review-response signal (best-effort, schema not fully confirmed) ------
#
# HONEST CAVEAT: gosom/google-maps-scraper's `-extra-reviews` flag returns a
# reviews array on each entry, but its exact field name for "owner replied
# to this review" hasn't been verified against a live run in this build
# (this repo was built without network access to google.com to test
# against). The candidate keys below are best guesses from the tool's
# public docs. Run the scraper once with -extra-reviews, inspect one raw
# entry's JSON, and adjust RAW_REVIEWS_KEYS / OWNER_RESPONSE_KEYS below to
# match what you actually see — this function fails safe (returns None,
# not a wrong answer) if it can't find the field.

RAW_REVIEWS_KEYS = ["reviews", "user_reviews", "extra_reviews"]
OWNER_RESPONSE_KEYS = ["owner_response", "response_from_owner_text", "response", "reply"]


def owner_response_ratio(raw_entry: dict) -> float | None:
    reviews = None
    for key in RAW_REVIEWS_KEYS:
        if key in raw_entry and isinstance(raw_entry[key], list):
            reviews = raw_entry[key]
            break
    if not reviews:
        return None

    responded = 0
    for r in reviews:
        if not isinstance(r, dict):
            continue
        if any(r.get(k) for k in OWNER_RESPONSE_KEYS):
            responded += 1
    return round(responded / len(reviews), 2) if reviews else None
