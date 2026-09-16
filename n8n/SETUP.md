# n8n setup + end-to-end test (single workflow)

One file now: **wenlinco-lead-scraper.json**. It has two independent
starting points on the same canvas:

- **Manual Trigger** branch (top) — you run this to kick off a scrape:
  Set Scrape Params → Trigger GitHub Action → Wait For Scrape Result →
  Split Out Leads → Flatten For Sheet → Append Lead
- **Seen Leads Webhook** branch (bottom) — always-on, called by the
  GitHub Action mid-run for the dedup check: Seen Leads Webhook →
  Read All Leads → Filter By Niche + Extract Cids → Respond With Seen Ids

Import just this one file: Workflows → Import from File.

## Source order (changed) — now worldwide (140 countries)

The `country` field you're already sending (it also drives the Ad
Library check) now picks which business directory runs as the
**primary** source before Google Maps kicks in as the **fallback**.

Two networks cover most of the world between them:

- **MisterWhat** — 12 countries (`GB` verified directly; `US`, `AU`,
  `FR`, `DE`, `NL`, `DK`, `PL`, `PT`, `BR`, `AR`, `CA` same platform,
  unverified beyond that). Email is NOT login-gated here — genuinely
  better for email specifically where it applies.
- **"Global Business Directory" network** — confirmed to run ~136
  country-specific sites on identical software (Yellosa for South
  Africa is one of them). 128 countries wired up — everywhere from
  Nigeria and Kenya to India, most of Europe, the Middle East, and
  Latin America. `ZA` and `NG` verified directly; the rest ride on
  "same confirmed platform" confidence. Email IS login-gated here
  (same as Yellosa was) — worse for email specifically, but covers far
  more ground and gives richer per-listing data either way (VAT
  number, employee band, established year).

Full registry (both dicts) lives at the top of `scraper/directory_source.py`.
Any country not in either dict skips the directory step and goes
straight to Maps for that run — nothing breaks, it just doesn't get the
speed/richness boost.

Directory-sourced leads are plain HTTP (no Docker/Playwright for this
part) and don't share Maps' rate limits. Maps only runs for the
shortfall if the directory doesn't reach `max_results` on its own —
check the Action's `[2/7]`/`[3/7]` log lines to see the split each run,
and the `source` column in the Sheet (`yellosa` / `businesslist` /
`misterwhat` / `gmaps` / etc.) to see where each lead actually came from.

**To confirm a currently-unverified country before relying on it
regularly:** fetch a real category page and a real company page on that
country's domain yourself (same way ZA, NG, and GB were checked) — if
the structure matches, it already works as-is.

If a niche has no good directory category match at all, add
`skip_directory: "true"` as a workflow_dispatch input (via the GitHub API
call, or add a `skip_directory` field to `Set Scrape Params` and wire it
into the dispatch payload the same way `depth`/`country` are) to go
straight to Maps for that run.

## One-time config

**Credentials**
- `Trigger GitHub Action` is pre-wired to a credential named
  `Github Global` by name — confirm it resolved to your real credential
  after import (re-select from the dropdown if not). Needs
  `actions:write` + `contents:read` on the `Map-sdingo` repo.
- `Append Lead` and `Read All Leads` both need your Google Sheets OAuth2
  credential.

**Google Sheet**
- Tab named `Leads`, header row (**tailored final list — paste this exact row into row 1**):
  `niche, location, source, name, phone, email, website, address, category, rating,
  review_count, lead_score, website_intent_score, other_intents,
  intent_notes, ad_status, ad_start_date, ad_running_days, dm_order_flow,
  checkout_present, owner_response_ratio, cid, maps_url, scraped_at`
  - `source` — `yellosa` (directory, now the primary source) or `gmaps` (Maps, now the fallback — only used when the directory doesn't reach `max_results` on its own)
  - `ad_status` — `active` / `stopped` / `none_found` / `unknown`
  - `ad_start_date` — when their current campaign began (only set if `ad_status` is `active`)
  - `ad_running_days` — how many days it's been running (only set if `active`)
- Paste that Sheet's ID into `documentId` on **both** `Append Lead` and
  `Read All Leads` (same sheet, same ID, two nodes).
- On `Append Lead`, set **Mapping Column Mode** to **Map Automatically**
  (not "Map Each Column Manually") — it matches incoming fields to your
  header row by name. "Map Each Column Manually" needs every field typed
  in by hand and is where the "At least one value has to be added under
  'Values to Send'" error comes from if it's left on defaults. If you're
  already on manual mapping from an earlier setup, just add `source` as
  one more field there too — same pattern as adding `whatsapp_message`
  earlier.

**GitHub secret** — one only:
- Activate the whole workflow (top-right toggle) so the webhook branch is
  live, then open `Seen Leads Webhook` and copy its production URL.
- In `Map-sdingo` → Settings → Secrets and variables → Actions: set
  `N8N_SEEN_LOOKUP_URL` to that URL.

## Test run, in order

1. Fix `.github/workflows/scrape.yml`'s path first — must live under
   `.github/workflows/`, not a top-level `workflows/` folder.
2. Activate the workflow — this arms the Seen Leads Webhook branch.
3. Edit **Set Scrape Params** to a real test niche/location, click
   **Test workflow**. It'll sit on the Wait node ("Waiting for input") —
   that's expected, it's holding the execution open while the Action runs.
4. Check the `Map-sdingo` repo's **Actions** tab — a run should appear
   within seconds. Watch its logs for the `[1/6]` through `[6/6]`
   progress lines, including the `[2/6]` dedup-check line, which confirms
   the webhook branch is being hit correctly.
5. When the Action finishes, the Wait node should un-pause on its own and
   continue into Split Out Leads → Flatten → Append Lead.
6. Check the Sheet — rows should appear.
7. Run the Manual Trigger again with the **same niche/location** — the
   `[2/6]` count should now be non-zero, and no `cid` should repeat in
   the Sheet.

**If the Wait node never resumes:** check the Action's logs first — it
either failed before the final webhook POST, or the `callback_url` input
didn't come through (check `Trigger GitHub Action`'s output for a
populated `callback_url` field before assuming the Action side is broken).

**If the dedup count stays at 0 forever:** the workflow needs to be
**activated**, not just saved — the Seen Leads Webhook branch only
listens while the workflow is active, same as any other n8n webhook.
