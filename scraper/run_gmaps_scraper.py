"""
Thin wrapper around the gosom/google-maps-scraper Docker image.
Docs: https://github.com/gosom/google-maps-scraper

We run it via Docker (preinstalled on GitHub Actions ubuntu-latest runners)
rather than building the Go binary — one less moving part.
"""

import json
import os
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


def _normalize(entry: dict) -> dict:
    out = {new: entry.get(old) for old, new in ENTRY_FIELD_MAP.items()}
    out["_raw"] = entry  # kept for internal signal extraction (e.g. review responses), stripped before final output
    return out


def scrape(niche: str, location: str, depth: int = 5, timeout_s: int = 600) -> list[dict]:
    """
    Runs the scraper for "{niche} in {location}" and returns a list of
    normalized business dicts. Requires Docker to be available on the runner.
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
