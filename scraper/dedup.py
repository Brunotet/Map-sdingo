"""
Looks up which businesses have already been captured for a given
niche(+location), so we never hand back a duplicate lead.

State lives in ONE place — your n8n Google Sheet — not duplicated in this
repo. This module just asks n8n for the list right before filtering.

Set this up in n8n as a small "lookup" workflow:
  Webhook (GET, e.g. /seen-leads)
    -> Google Sheets node: read the leads sheet, filter rows where
       niche == query param `niche` (and location if you track that too)
    -> Set/Code node: return just the `cid` column as a JSON array
    -> Respond to Webhook: {"seen_ids": ["<cid1>", "<cid2>", ...]}

Then set SEEN_LOOKUP_URL (env / --seen-lookup-url) to that webhook's URL.
If it's not set, dedup is simply skipped (first run, or n8n isn't wired
up yet) rather than failing the whole scrape.
"""

import sys
import requests


def fetch_seen_cids(lookup_url: str, niche: str, location: str, timeout_s: int = 20) -> set[str]:
    if not lookup_url:
        return set()

    try:
        resp = requests.get(
            lookup_url,
            params={"niche": niche, "location": location},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        # Don't fail the whole run over a dedup lookup hiccup — worst case
        # a duplicate slips through this one run, which is recoverable.
        print(f"[dedup] Warning: seen-leads lookup failed ({e}). Continuing without dedup.", file=sys.stderr)
        return set()

    # Accept either {"seen_ids": [...]} or a bare [...] array
    ids = data.get("seen_ids", data) if isinstance(data, dict) else data
    return {str(i) for i in ids} if isinstance(ids, list) else set()
