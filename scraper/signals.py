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


# --- Review-response signal ------------------------------------------------
#
# CONFIRMED (2026) against gosom/google-maps-scraper's actual Go struct
# (gmaps package, pkg.go.dev): Entry.UserReviewsExtended is what
# `-extra-reviews` populates (json key "user_reviews_extended"; the
# smaller default set is "user_reviews"), and each Review's owner-reply
# text is Review.ReplyText (json key "reply_text", omitempty — absent
# entirely when the owner never replied, not present-but-empty). Earlier
# guesses ("owner_response", "response", "reply", etc.) never matched
# that field, which is why every business was coming back with a
# 0.0 ratio instead of a genuine mix — a 0.0 wasn't "nobody replies",
# it was "the code was checking the wrong key on every review."

RAW_REVIEWS_KEYS = ["user_reviews_extended", "user_reviews"]
OWNER_RESPONSE_KEYS = ["reply_text", "reply_text_original"]


def owner_response_ratio(raw_entry: dict) -> float | None:
    reviews = None
    for key in RAW_REVIEWS_KEYS:
        if key in raw_entry and isinstance(raw_entry[key], list) and raw_entry[key]:
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
