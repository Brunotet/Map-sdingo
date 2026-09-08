# Wenlinco Maps Lead Scraper

n8n sends a niche + location → this repo scrapes Google Maps, keeps only
businesses with **no real website** (a Facebook/Instagram link still
counts as "no website"), scores them by review activity + how easy they'll
be to reach (phone/social/email found), caps it at the top N (default 50),
best-effort enriches emails from any linked FB/IG page, and posts the
result straight back to an n8n webhook.

Runs entirely on GitHub Actions' free public-repo runners — **keep this
repo public** or you'll burn your 2,000 private-repo minutes instead.

## Intent scoring (new)

Every lead now gets ranked on **buying intent**, using business-level public
signals only — never a personal profile:

- **Is it running Meta ads right now — and for how long?** — checked
  against the *public* Ad Library website (facebook.com/ads/library, no
  login needed), queried separately for active vs. inactive ads so we get
  a clean status: `active` (with a start date + days running, pulled from
  the "Started running on" text on each ad card), `stopped` (ran ads
  before, none currently — a re-engagement angle), or `none_found`. Note:
  the official Ad Library **API** only covers EU/UK commercial ads plus
  worldwide political ads — South African commercial ads aren't in its
  scope as of 2026, so this queries the public site directly instead.
- **Does its bio say "DM/WhatsApp to order"** instead of having a real
  checkout link? Strong signal they're selling informally and outgrowing it.
- **Does it already have some checkout/store link** (Linktree, Shopify,
  "shop now")? Lowers first-website urgency, reframes it as an upgrade lead.
- **Does the owner respond to reviews?** Engagement/professionalism signal.
- Review count + rating, same as before.

Output columns added per lead:
- `website_intent_score` — 1 to 10
- `other_intents` — list of suggested services beyond "just a website" (e.g. ad management, WhatsApp order automation, reputation management, re-engagement)
- `intent_notes` — plain-English reasons behind the score, so you're never guessing why a lead ranked where it did
- `ad_status`, `ad_start_date`, `ad_running_days`, `dm_order_flow`, `checkout_present`, `owner_response_ratio` — the raw signals themselves, in case you want to re-rank with your own weighting later

Run with `--skip-ad-library` for a faster run without the Playwright ad
check (leaves `ad_status` as `unknown` / no ads-based score bump).

**Two honest caveats on this part specifically:**
1. The Ad Library check scrapes a live Meta page whose layout can change —
   this build couldn't be tested against the real site (no route to
   facebook.com from the sandbox it was built in). If `ad_status` comes
   back `unknown` for everything on your first real run, open
   `scraper/ad_library.py` and adjust the text markers/date pattern to
   match what's actually on the page.
2. The owner-response-ratio signal depends on `gosom/google-maps-scraper`'s
   `-extra-reviews` output using a review field name this build guessed at
   (see the comment block in `scraper/signals.py`). Run once, inspect a raw
   entry, and correct the key names there if it's not matching.



Dedup state lives in **your n8n Google Sheet** — nothing is duplicated in
this repo. Before finalizing the 50, the scraper calls a small n8n lookup
webhook and asks "which `cid`s do you already have for this niche?", then
drops those before scoring/capping. `cid` is Google's own stable place ID
(more reliable than matching on name/address, which shifts slightly
between scrapes).

Build this as its own tiny n8n workflow:

```
Webhook (GET, e.g. /seen-leads)
  -> Google Sheets node: read your leads sheet, filter rows where
     niche == query param `niche` (add a location filter too if you
     track leads per-location)
  -> Set/Code node: pull just the `cid` column into an array
  -> Respond to Webhook: { "seen_ids": ["<cid1>", "<cid2>", ...] }
```

If this isn't wired up yet, the scraper just skips dedup for that run
(logs a warning) instead of failing — so you can turn it on whenever
that n8n workflow is ready.

## One-time setup

1. Push this repo to GitHub as **public**.
2. In an n8n workflow, create a **Webhook** node (POST) — copy its URL.
   This is where finished leads get pushed.
3. Build the "seen leads" lookup workflow above — copy its webhook URL too.
4. In the GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret** — add both:
   - `N8N_WEBHOOK_URL` — where results get posted
   - `N8N_SEEN_LOOKUP_URL` — where dedup checks are looked up

## How n8n triggers a scrape

n8n calls the GitHub API to fire `workflow_dispatch`:

```
POST https://api.github.com/repos/<you>/<repo>/actions/workflows/scrape.yml/dispatches
Authorization: Bearer <a GitHub Personal Access Token with 'repo' + 'workflow' scope>
Accept: application/vnd.github+json

{
  "ref": "main",
  "inputs": {
    "niche": "hair salons",
    "location": "Nelspruit",
    "max_results": "50",
    "min_rating": "3.5"
  }
}
```

Use n8n's **HTTP Request** node for this, with the token stored in n8n
credentials (not hardcoded in the workflow).

The Action runs (a few minutes depending on `depth`), then POSTs this
shape to your n8n webhook when done:

```json
{
  "niche": "hair salons",
  "location": "Nelspruit",
  "count": 50,
  "leads": [
    {
      "name": "...",
      "website": "https://facebook.com/... or null",
      "phone": "...",
      "email": "found via FB/IG bio, or null",
      "rating": 4.6,
      "review_count": 12,
      "category": "...",
      "address": "...",
      "maps_url": "...",
      "cid": "google's stable place ID — store this column, dedup depends on it",
      "lead_score": 1.78,
      "website_intent_score": 8,
      "other_intents": ["Google/Meta ads management (already spending on ads, funnel needs a home)"],
      "intent_notes": "running Meta ads for 45 days straight with no landing page — likely leaking paid-traffic conversions; ...",
      "ad_status": "active",
      "ad_start_date": "2026-07-25",
      "ad_running_days": 45,
      "dm_order_flow": true,
      "checkout_present": false,
      "owner_response_ratio": 0.6
    }
  ]
}
```

From there, your n8n workflow's next node just writes `leads` straight
into the Google Sheet.

## Local test (optional, before wiring up n8n)

Needs Docker running locally.

```bash
pip install -r requirements.txt
python -m scraper.main --niche "coffee shops" --location "Cape Town" --max-results 10
```

## Honest limitations

- **Email enrichment is best-effort.** Facebook/Instagram gate most data
  behind a login wall for non-logged-in requests — this pulls whatever's
  visible in the public bio/meta tags, which is often nothing. Expect a
  real hit rate somewhere well under 50%, especially on Instagram. Phone
  (from Maps directly) is far more reliable — plan your outreach sequence
  around that, with email as a bonus when it's there.
- **`depth` controls how many raw Maps results get pulled before
  filtering.** If a niche+location search comes back with fewer than 50
  eligible leads after filtering, raise `depth` on the next run rather
  than loosening `min_rating`/review filters — that keeps lead quality
  consistent.
- Google Maps' DOM/anti-bot behavior can change; if scrapes start
  returning 0 results, check the `gosom/google-maps-scraper` repo for a
  new release/image tag first before assuming this code is broken.
