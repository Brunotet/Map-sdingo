"""
Queries Meta's PUBLIC Ad Library website (facebook.com/ads/library) to see
whether a business is CURRENTLY running ads, previously ran and stopped, or
has no ad history found — plus how long a current campaign has been live.
This is Meta's own public ad-transparency tool — no login required,
explicitly designed to be publicly browsable, and legal to query. We use
the website directly instead of the official Ad Library API because, as of
2026, that API only covers non-political ads for EU/UK plus worldwide
political ads — South African commercial ads aren't in scope for the API
at all.

How status + duration are determined: the Ad Library lets you filter by
active_status. Rather than parse a mixed results page and guess which
badge belongs to which card, this runs the active query and the inactive
query separately — presence of results in one vs. the other tells us the
status directly. Each ad card shows "Started running on <date>" (still
true as of 2026's Ad Library UI); we pull the earliest such date from the
active-ads query as the current campaign's start, and compute days running
from that.

HONEST CAVEAT: this scrapes a live Meta-owned page whose DOM/text can
change without notice, and this build couldn't be tested against the real
site (this sandbox has no route to facebook.com). If `checked` keeps
coming back False across a real run, open the Ad Library in a browser for
one test business, view source, and update NO_RESULTS_MARKERS /
START_DATE_PATTERN below to match what's actually there.
"""

import re
from datetime import date, datetime
from urllib.parse import quote

NO_RESULTS_MARKERS = [
    "no ads match your search",
    "0 results",
    "no results found",
]

START_DATE_PATTERN = re.compile(r"started running on\s+([A-Za-z]+ \d{1,2}, \d{4})", re.IGNORECASE)


def _extract_start_dates(body_text: str) -> list[date]:
    dates = []
    for raw in START_DATE_PATTERN.findall(body_text):
        try:
            dates.append(datetime.strptime(raw, "%B %d, %Y").date())
        except ValueError:
            continue
    return dates


def _query(page, business_name: str, country: str, active_status: str, timeout_ms: int):
    url = (
        "https://www.facebook.com/ads/library/"
        f"?active_status={active_status}&ad_type=all&country={country}&q={quote(business_name)}"
    )
    try:
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)  # let the results grid render
        return page.inner_text("body")
    except Exception:
        return None


def check_active_ads(page, business_name: str, country: str = "ZA", timeout_ms: int = 15000) -> dict:
    """
    `page` is a Playwright page from an already-open browser context
    (reuse one browser across all businesses — spinning up a new one per
    check is slow and looks more bot-like to the target site).

    Returns:
      {
        "ad_status": "active" | "stopped" | "none_found" | "unknown",
        "ad_start_date": "YYYY-MM-DD" | None,   # only set when status == "active"
        "ad_running_days": int | None,          # only set when status == "active"
        "checked": bool,
      }

    "stopped" means ads were found under active_status=inactive but none
    under active_status=active — i.e. they've advertised before but aren't
    right now. ad_start_date/ad_running_days are left None for "stopped"
    since a reliable end-date isn't parsed here — treat "stopped" as a
    qualitative signal (worth a re-engagement pitch), not a precise window.
    """
    result = {"ad_status": "unknown", "ad_start_date": None, "ad_running_days": None, "checked": False}

    active_text = _query(page, business_name, country, "active", timeout_ms)
    if active_text is None:
        return result  # network/render failure — leave as unknown, don't guess

    active_lower = active_text.lower()
    if not any(m in active_lower for m in NO_RESULTS_MARKERS):
        active_dates = _extract_start_dates(active_text)
        if active_dates:
            start = min(active_dates)  # earliest = when the current campaign actually began
            result["ad_status"] = "active"
            result["ad_start_date"] = start.isoformat()
            result["ad_running_days"] = (date.today() - start).days
            result["checked"] = True
            return result
        # results grid rendered but our date pattern didn't match anything —
        # something on the page likely changed; don't silently call it "none"
        result["checked"] = False
        return result

    # no active ads — check whether they've run ads before and stopped
    inactive_text = _query(page, business_name, country, "inactive", timeout_ms)
    if inactive_text is None:
        result["checked"] = False
        return result

    inactive_lower = inactive_text.lower()
    if any(m in inactive_lower for m in NO_RESULTS_MARKERS):
        result["ad_status"] = "none_found"
        result["checked"] = True
        return result

    result["ad_status"] = "stopped"
    result["checked"] = True
    return result
