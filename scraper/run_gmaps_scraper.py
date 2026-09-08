"""
Thin wrapper around the gosom/google-maps-scraper Docker image.
Docs: https://github.com/gosom/google-maps-scraper

We run it via Docker (preinstalled on GitHub Actions ubuntu-latest runners)
rather than building the Go binary — one less moving part.
"""

import json
import os
import re
import subprocess
import tempfile


ENTRY_FIELD_MAP = {
    "title": "name",
    "web_site": "website",
    "phone": "phone",
    "review_count": "review_count",
    "review_rating": "rating",
    "address": "address",
    "category": "category",
    "link": "maps_url",
    "cid": "cid",  # Google's own stable place ID — use THIS for dedup, never name/address
}

# Reuse the same email pattern as the enrichment module rather than duplicate it.
from scraper.enrich import EMAIL_RE  # noqa: E402


def _candidate_email_from_entry(entry: dict) -> str | None:
    """
    Two email sources that come for free with the Maps scrape itself,
    checked before we ever make a separate FB/IG request:

    1. gosom's own `emails` field (populated by the -email flag) — it
       crawls whatever URL is in the "website" field, which for our
       target businesses is very often their Facebook/Instagram link
       anyway, using gosom's own (Go/goquery-based) extractor.
    2. The Google Business Profile's own `description` text — some
       businesses put an email straight in their Maps description.
    """
    emails = entry.get("emails")
    if isinstance(emails, list) and emails:
        return emails[0]

    description = entry.get("description") or ""
    m = EMAIL_RE.search(description)
    return m.group(0) if m else None


def _normalize(entry: dict) -> dict:
    out = {new: entry.get(old) for old, new in ENTRY_FIELD_MAP.items()}
    out["gosom_email"] = _candidate_email_from_entry(entry)
    out["_raw"] = entry  # kept for internal signal extraction (e.g. review responses), stripped before final output
    return out


def scrape(niche: str, location: str, depth: int = 5, timeout_s: int = 2700) -> list[dict]:
    """
    Runs the scraper for "{niche} in {location}" and returns a list of
    normalized business dicts. Requires Docker to be available on the runner.

    timeout_s default raised from the original 600s (10 min) to 2700s
    (45 min) — that original value was set before `-extra-reviews` and
    `-email` were added. Both make gosom visit each business individually
    (reviews via DOM-scroll when Google's RPC endpoint 403s, which it does
    fairly often; website crawling for -email), so a depth=5 run can
    legitimately take well past 10 minutes now. This is a SEPARATE timeout
    from the GitHub Actions job-level timeout-minutes in scrape.yml — that
    one bounds the whole job, this one bounds just this subprocess call.
    Keep this comfortably under the job timeout (currently 55 min) so a
    real timeout here still lets the job report a clean error instead of
    both firing at once.
    """
    query = f"{niche} in {location}".strip()

    with tempfile.TemporaryDirectory() as tmp:
        queries_path = os.path.join(tmp, "queries.txt")
        results_path = os.path.join(tmp, "results.json")

        with open(queries_path, "w", encoding="utf-8") as f:
            f.write(query + "\n")

        # touch results file so the bind mount target exists
        open(results_path, "w").close()

        cmd = [
            "docker", "run", "--rm",
            "-v", "gmaps-playwright-cache:/opt",
            "-v", f"{queries_path}:/queries.txt:ro",
            "-v", f"{results_path}:/results.json",
            "gosom/google-maps-scraper",
            "-input", "/queries.txt",
            "-results", "/results.json",
            "-json",
            "-depth", str(depth),
            "-extra-reviews",
            "-email",
            "-exit-on-inactivity", "3m",
        ]

        subprocess.run(cmd, check=True, timeout=timeout_s)

        raw = _load_results(results_path)

    return [_normalize(e) for e in raw]


def _load_results(path: str) -> list[dict]:
    """The scraper's -json output has been a single JSON array in some
    versions and newline-delimited JSON in others — handle both."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in content.splitlines() if line.strip()]
