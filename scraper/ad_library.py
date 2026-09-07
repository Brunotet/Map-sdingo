"""
Queries Meta's PUBLIC Ad Library website (facebook.com/ads/library) to see
if a business currently has active ads running. This is Meta's own public
ad-transparency tool — no login required, explicitly designed to be
publicly browsable, and legal to query. We use the website directly
instead of the official Ad Library API because, as of 2026, that API only
covers non-political ads for EU/UK plus worldwide political ads — South
African commercial ads aren't in scope for the API at all.

HONEST CAVEAT: this scrapes a live Meta-owned page whose DOM structure can
change without notice, and this build couldn't be tested against the real
site (this sandbox has no route to facebook.com). If `checked` keeps
coming back False across a real run, open the Ad Library in a browser for
one test business, view source, and update the selectors/text markers
below to match what's actually there.
"""

from urllib.parse import quote

NO_RESULTS_MARKERS = [
    "no ads match your search",
    "0 results",
    "no results found",
]

# Best-guess text marker present in the results header when ads ARE found,
# e.g. "~N results". Verify against a live page and adjust.
RESULTS_MARKER = "result"


def check_active_ads(page, business_name: str, country: str = "ZA", timeout_ms: int = 15000) -> dict:
    """
    `page` is a Playwright page from an already-open browser context
    (reuse one browser across all businesses — don't spin up a new one
    per check, it's slow and looks more bot-like to the target site).

    Returns {"running_ads": bool | None, "checked": bool}.
    running_ads is None when the check couldn't be completed (treat as
    "unknown", not "no ads" — don't let a failed check silently suppress
    a real intent signal).
    """
    url = (
        "https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={country}&q={quote(business_name)}"
    )
    try:
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)  # let the results grid render
        body_text = page.inner_text("body").lower()
    except Exception:
        return {"running_ads": None, "checked": False}

    if any(marker in body_text for marker in NO_RESULTS_MARKERS):
        return {"running_ads": False, "checked": True}
    if RESULTS_MARKER in body_text:
        return {"running_ads": True, "checked": True}

    # Couldn't confidently parse the page — don't guess.
    return {"running_ads": None, "checked": False}
