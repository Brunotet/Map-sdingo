"""
Eligibility filtering + scoring for scraped Google Maps business leads.

Core rules (from spec):
- Target businesses with NO real website. A Facebook/Instagram link in the
  "website" field does NOT disqualify them — that's still "no website" for
  our purposes, and it's a gift because it tells us exactly where to look
  for an email/DM handle.
- Review count is a proxy for "is this business actually active", not a
  hard minimum. New listings get a pass with very few reviews; older-
  looking listings need more reviews to prove they're still alive.
"""

import re
from urllib.parse import urlparse

SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "instagram.com", "wa.me",
    "whatsapp.com", "linktr.ee", "linktree.com",
)


def classify_website(url: str | None) -> str:
    """Return 'none' | 'social' | 'real' for a business's Maps website field."""
    if not url or not url.strip():
        return "none"
    try:
        host = urlparse(url if "://" in url else f"http://{url}").netloc.lower()
    except ValueError:
        return "none"
    host = host.removeprefix("www.")
    if any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS):
        return "social"
    return "real"


def social_url(url: str | None) -> str | None:
    """If the website field is a social link, return it, else None."""
    return url if url and classify_website(url) == "social" else None


def is_no_website(business: dict) -> bool:
    return classify_website(business.get("website")) in ("none", "social")


def review_activity_score(review_count: int) -> float:
    """
    Higher = more evidence the business is real/active. Deliberately generous
    to new listings (few reviews is fine), stricter as review count implies
    an older listing that SHOULD have accumulated more reviews by now.

    This is a proxy only — Maps doesn't expose a founding date, so we treat
    review_count itself as a rough signal of listing age as well as activity.
    """
    if review_count <= 0:
        return 0.0
    if review_count <= 5:
        return 1.0  # likely new, give full benefit of the doubt
    if review_count <= 15:
        return 0.8
    if review_count <= 40:
        return 0.6
    return 0.4  # old listing, low-to-mid reviews relative to its age = weaker signal


def is_eligible(business: dict, min_rating: float = 3.5) -> bool:
    if not is_no_website(business):
        return False
    reviews = business.get("review_count") or 0
    rating = business.get("rating") or 0
    if reviews == 0:
        # zero reviews AND zero activity signal elsewhere = likely dead/ghost listing
        return False
    if rating and rating < min_rating:
        return False
    return True


def score(business: dict) -> float:
    """Composite ranking score — higher sorts first."""
    reviews = business.get("review_count") or 0
    rating = business.get("rating") or 0
    has_phone = bool(business.get("phone"))
    has_social = bool(social_url(business.get("website")))
    has_email = bool(business.get("email"))

    s = review_activity_score(reviews)
    s += (rating / 5.0) * 0.5
    s += 0.3 if has_phone else 0
    s += 0.3 if has_social else 0
    s += 0.4 if has_email else 0  # email found = best outreach lead, weight it up
    return round(s, 3)


def exclude_seen(businesses: list[dict], seen_cids: set[str]) -> list[dict]:
    """Drop any business whose Google `cid` is already in the seen set.
    cid (Google's own place identifier) is used instead of name/address
    because those shift slightly between scrapes (punctuation, formatting)
    and would let duplicates slip through a string match."""
    if not seen_cids:
        return businesses
    return [b for b in businesses if str(b.get("cid")) not in seen_cids]


def filter_and_sort(
    businesses: list[dict],
    max_results: int = 50,
    min_rating: float = 3.5,
    seen_cids: set[str] | None = None,
) -> list[dict]:
    eligible = [b for b in businesses if is_eligible(b, min_rating=min_rating)]
    eligible = exclude_seen(eligible, seen_cids or set())
    for b in eligible:
        b["lead_score"] = score(b)
    eligible.sort(key=lambda b: b["lead_score"], reverse=True)
    return eligible[:max_results]
