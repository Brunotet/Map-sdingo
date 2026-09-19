"""
Orchestrator. Called from the GitHub Action with niche + location coming
from n8n's workflow_dispatch inputs.

SOURCE ORDER (changed): Yellosa.co.za directory browsing is now the
PRIMARY lead source — lighter (plain HTTP, no Docker/Playwright needed
for this part), richer per-listing data, and doesn't share Maps' rate
limits. Google Maps (via gosom) is now the FALLBACK, only scraped if the
directory doesn't reach --max-results on its own for a given niche/location.

REACHABILITY FILTER (added 2026-09): a lead that has neither an email
nor a WhatsApp-capable mobile number can't actually be contacted through
either of this pipeline's outreach channels — kept in the Sheet, it's
just dead weight. After email discovery runs, every lead's phone gets
classified mobile/landline/unknown (phone_classify.py, via Google's
phonenumbers library) and any lead with no email AND a non-mobile phone
gets dropped. This can bring the final count below --max-results when a
lot of leads turn out unreachable — that's expected, not a bug; the
alternative (keeping unreachable leads just to hit a number) defeats the
point of the list.

Usage:
    python -m scraper.main --niche "hair salons" --location "Nelspruit" \
        --max-results 50 --min-rating 3.5 [--webhook-url URL] [--depth 5]

If --webhook-url is omitted, falls back to the WEBHOOK_URL env var
(set as a GitHub Actions secret so it's not hardcoded / not logged).
Always also writes leads.json as a workflow artifact, so nothing is lost
even if the webhook call fails.
"""

import argparse
import json
import os
import sys

import requests

from scraper.run_gmaps_scraper import scrape
from scraper.directory_source import scrape_directory_leads
from scraper.filters import filter_and_sort
from scraper.enrich import enrich_business
from scraper.dedup import fetch_seen_cids
from scraper.signals import extract_bio_signals, owner_response_ratio
from scraper.intent import score_intent
from scraper.web_discovery import find_social_link
from scraper.phone_classify import classify_phone


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--niche", required=True)
    p.add_argument("--location", required=True)
    p.add_argument("--country", default="ZA", help="2-letter country code for the Ad Library check, directory selection, and phone-number classification")
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--min-rating", type=float, default=3.5)
    p.add_argument("--depth", type=int, default=5, help="Maps scroll depth — raise if too few eligible leads survive filtering (only matters if the directory source can't fill max-results on its own)")
    p.add_argument("--scrape-timeout", type=int, default=2700, help="Seconds to let the gosom Docker scrape run before giving up (separate from the Action's own job timeout)")
    p.add_argument("--webhook-url", default=os.environ.get("WEBHOOK_URL"))
    p.add_argument("--seen-lookup-url", default=os.environ.get("SEEN_LOOKUP_URL"))
    p.add_argument("--skip-ad-library", action="store_true", help="Skip the Playwright ad-library check (faster, no running_ads signal)")
    p.add_argument("--skip-directory", action="store_true", help="Skip Yellosa entirely and go straight to Google Maps (escape hatch if a niche has no good directory category match)")
    p.add_argument("--max-social-searches", type=int, default=50, help="Max FB/IG discovery searches per run, to protect the search API's free-tier monthly budget — raise if you have a larger Tavily plan")
    p.add_argument("--out", default="leads.json")
    return p.parse_args()


def run(
    niche: str,
    location: str,
    max_results: int,
    min_rating: float,
    depth: int,
    seen_lookup_url: str | None = None,
    country: str = "ZA",
    skip_ad_library: bool = False,
    scrape_timeout: int = 2700,
    skip_directory: bool = False,
    max_social_searches: int = 50,
) -> list[dict]:
    print("[1/8] Checking which ones you already have in n8n...", file=sys.stderr)
    seen_cids = fetch_seen_cids(seen_lookup_url, niche, location)
    print(f"      -> {len(seen_cids)} already-used business IDs on record for this niche", file=sys.stderr)

    eligible = []

    if not skip_directory:
        print(f"[2/8] Scraping the directory for '{niche} in {location}' (country={country}, primary source)...", file=sys.stderr)
        directory_raw = scrape_directory_leads(niche, location, max_results=max_results, country=country)
        print(f"      -> {len(directory_raw)} no-website candidates found on the directory", file=sys.stderr)
        eligible = filter_and_sort(directory_raw, max_results=max_results, min_rating=min_rating, seen_cids=seen_cids)
        print(f"      -> {len(eligible)} fresh eligible leads from the directory (capped at {max_results})", file=sys.stderr)
    else:
        print("[2/8] --skip-directory set, going straight to Google Maps", file=sys.stderr)

    shortfall = max_results - len(eligible)
    if shortfall > 0:
        print(f"[3/8] Directory came up {shortfall} short of {max_results} — falling back to Google Maps for the rest (depth={depth}, timeout={scrape_timeout}s)...", file=sys.stderr)
        maps_raw = scrape(niche, location, depth=depth, timeout_s=scrape_timeout)
        print(f"      -> {len(maps_raw)} raw Maps listings", file=sys.stderr)
        for entry in maps_raw:
            entry.setdefault("source", "gmaps")
        already_picked = seen_cids | {b["cid"] for b in eligible if b.get("cid")}
        maps_eligible = filter_and_sort(maps_raw, max_results=shortfall, min_rating=min_rating, seen_cids=already_picked)
        print(f"      -> {len(maps_eligible)} fresh eligible leads from Maps to fill the shortfall", file=sys.stderr)
        eligible.extend(maps_eligible)
    else:
        print("[3/8] Directory alone reached max-results — skipping Google Maps entirely this run", file=sys.stderr)

    if len(eligible) < max_results:
        print(
            f"      NOTE: still short of {max_results} overall — try a broader location, raise --depth for "
            f"the Maps fallback, or double-check --niche resolves to a sensible directory category.",
            file=sys.stderr,
        )

    print(f"[4/8] For leads with nothing at all linked, searching the web for a social page (capped at {max_social_searches}/run to protect the search API's free-tier budget)...", file=sys.stderr)
    discovered = 0
    searched = 0
    needed = 0
    for b in eligible:
        if not b.get("gosom_email") and not (b.get("website") or "").strip():
            needed += 1
            if searched >= max_social_searches:
                continue
            searched += 1
            found = find_social_link(b["name"], location)
            if found:
                b["website"] = found
                discovered += 1
    print(f"      -> found a Facebook/Instagram page for {discovered}/{searched} searched ({needed} leads actually had nothing linked, {max(0, needed - searched)} skipped past the cap)", file=sys.stderr)

    print("[5/8] Emails: checking gosom/directory-description first, then FB/Instagram for the rest...", file=sys.stderr)
    enriched = []
    from_free = 0
    for b in eligible:
        gosom_email = b.pop("gosom_email", None)
        if gosom_email:
            b["email"] = gosom_email
            b["_bio_text"] = None
            from_free += 1
            enriched.append(b)
        else:
            enriched.append(enrich_business(b))
    found = sum(1 for b in enriched if b.get("email"))
    print(f"      -> email found for {found}/{len(enriched)} leads ({from_free} from gosom/description, {found - from_free} from FB/IG)", file=sys.stderr)

    print("[6/8] Checking reachability (email, or a WhatsApp-capable mobile number)...", file=sys.stderr)
    reachable = []
    dropped = 0
    for b in enriched:
        phone_type = classify_phone(b.get("phone"), country)
        b["phone_type"] = phone_type
        if b.get("email") or phone_type == "mobile":
            reachable.append(b)
        else:
            dropped += 1
    print(f"      -> {dropped} lead(s) dropped: no email and no mobile/WhatsApp-capable number (landline or unknown only)", file=sys.stderr)
    enriched = reachable

    print("[7/8] Pulling business-level intent signals (bio phrasing, reviews, ad activity)...", file=sys.stderr)
    for b in enriched:
        b.update(extract_bio_signals(b.pop("_bio_text", None)))
        b["owner_response_ratio"] = owner_response_ratio(b.pop("_raw", {}))
        website = b.get("website") or ""
        if "wa.me" in website or "whatsapp.com" in website:
            # their ONLY listed "website" is a WhatsApp chat link — that's an
            # even more direct DM-order signal than finding the phrase in a bio
            b["dm_order_flow"] = True
        b["ad_status"] = "unknown"  # filled in below if the ad-library check runs
        b["ad_start_date"] = None
        b["ad_running_days"] = None

    if not skip_ad_library:
        _run_ad_library_checks(enriched, country=country)
    else:
        print("      -> --skip-ad-library set, ad_status left as unknown for all leads", file=sys.stderr)

    print("[8/8] Scoring website intent (1-10) + suggesting other service intents...", file=sys.stderr)
    for b in enriched:
        b.update(score_intent(b))

    return enriched


def _run_ad_library_checks(businesses: list[dict], country: str):
    try:
        from playwright.sync_api import sync_playwright
        from scraper.ad_library import check_active_ads
    except ImportError:
        print("      WARNING: playwright not installed — skipping ad-library check.", file=sys.stderr)
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            checked = 0
            for b in businesses:
                result = check_active_ads(page, b["name"], country=country)
                b["ad_status"] = result["ad_status"]
                b["ad_start_date"] = result["ad_start_date"]
                b["ad_running_days"] = result["ad_running_days"]
                checked += result["checked"]
            browser.close()
        print(f"      -> ad-library check completed for {checked}/{len(businesses)} leads", file=sys.stderr)
    except Exception as e:
        print(f"      WARNING: ad-library check failed entirely ({e}). ad_status left as unknown.", file=sys.stderr)


def send_webhook(url: str, niche: str, location: str, leads: list[dict]):
    payload = {"niche": niche, "location": location, "count": len(leads), "leads": leads}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    print(f"Posted {len(leads)} leads to n8n webhook (status {resp.status_code})", file=sys.stderr)


def main():
    args = parse_args()
    leads = run(
        args.niche,
        args.location,
        args.max_results,
        args.min_rating,
        args.depth,
        args.seen_lookup_url,
        args.country,
        args.skip_ad_library,
        args.scrape_timeout,
        args.skip_directory,
        args.max_social_searches,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"niche": args.niche, "location": args.location, "count": len(leads), "leads": leads}, f, indent=2)
    print(f"Wrote {len(leads)} leads to {args.out}", file=sys.stderr)

    if args.webhook_url:
        send_webhook(args.webhook_url, args.niche, args.location, leads)
    else:
        print("No webhook URL set — skipping n8n push, results are only in the artifact.", file=sys.stderr)


if __name__ == "__main__":
    main()
