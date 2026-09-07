"""
Orchestrator. Called from the GitHub Action with niche + location coming
from n8n's workflow_dispatch inputs.

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
from scraper.filters import filter_and_sort
from scraper.enrich import enrich_business
from scraper.dedup import fetch_seen_cids
from scraper.signals import extract_bio_signals, owner_response_ratio
from scraper.intent import score_intent


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--niche", required=True)
    p.add_argument("--location", required=True)
    p.add_argument("--country", default="ZA", help="2-letter country code for the Ad Library check")
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--min-rating", type=float, default=3.5)
    p.add_argument("--depth", type=int, default=5, help="Maps scroll depth — raise if too few eligible leads survive filtering")
    p.add_argument("--webhook-url", default=os.environ.get("WEBHOOK_URL"))
    p.add_argument("--seen-lookup-url", default=os.environ.get("SEEN_LOOKUP_URL"))
    p.add_argument("--skip-ad-library", action="store_true", help="Skip the Playwright ad-library check (faster, no running_ads signal)")
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
) -> list[dict]:
    print(f"[1/6] Scraping Google Maps for '{niche} in {location}' (depth={depth})...", file=sys.stderr)
    raw = scrape(niche, location, depth=depth)
    print(f"      -> {len(raw)} raw listings", file=sys.stderr)

    print("[2/6] Checking which ones you already have in n8n...", file=sys.stderr)
    seen_cids = fetch_seen_cids(seen_lookup_url, niche, location)
    print(f"      -> {len(seen_cids)} already-used business IDs on record for this niche", file=sys.stderr)

    print("[3/6] Filtering (no-website + review activity + not-already-used) and scoring...", file=sys.stderr)
    eligible = filter_and_sort(raw, max_results=max_results, min_rating=min_rating, seen_cids=seen_cids)
    print(f"      -> {len(eligible)} fresh eligible leads (capped at {max_results})", file=sys.stderr)
    if len(eligible) < max_results:
        print(
            f"      NOTE: got fewer than {max_results} — raise --depth on the next run "
            f"for this niche/location, the pool of new (non-duplicate) leads is thinning out.",
            file=sys.stderr,
        )

    print("[4/6] Enriching leads that have a social link but no email...", file=sys.stderr)
    enriched = [enrich_business(b) for b in eligible]
    found = sum(1 for b in enriched if b.get("email"))
    print(f"      -> email found for {found}/{len(enriched)} leads", file=sys.stderr)

    print("[5/6] Pulling business-level intent signals (bio phrasing, reviews, ad activity)...", file=sys.stderr)
    for b in enriched:
        b.update(extract_bio_signals(b.pop("_bio_text", None)))
        b["owner_response_ratio"] = owner_response_ratio(b.pop("_raw", {}))
        b["running_ads"] = None  # filled in below if the ad-library check runs

    if not skip_ad_library:
        _run_ad_library_checks(enriched, country=country)
    else:
        print("      -> --skip-ad-library set, running_ads left as unknown for all leads", file=sys.stderr)

    print("[6/6] Scoring website intent (1-10) + suggesting other service intents...", file=sys.stderr)
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
                b["running_ads"] = result["running_ads"]
                checked += result["checked"]
            browser.close()
        print(f"      -> ad-library check completed for {checked}/{len(businesses)} leads", file=sys.stderr)
    except Exception as e:
        print(f"      WARNING: ad-library check failed entirely ({e}). running_ads left as unknown.", file=sys.stderr)


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
