"""Fetch and normalize postings from a Lever job board.

Same FetchResult contract as the Greenhouse fetcher. Lever differences:
  - the response is a BARE ARRAY, not {"jobs": [...]}
  - 200 with [] is an account with no public postings, NOT an error
  - descriptionPlain / descriptionBodyPlain are already plain text
  - categories.allLocations is a real array, so posting_locations gets
    one row per location
  - workplaceType gives a real remote_type
  - `lists` pre-splits the description into sections, but the headers are
    free text, so they are bucketed by keyword in src/normalize/sections.py

This module does not touch SQLite.
"""

import html
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from src.fetch.greenhouse import FetchResult
from src.normalize.sections import bucket_section

API_URL = "https://api.lever.co/v0/postings/{token}?mode=json"

TIMEOUT = 20
MAX_ATTEMPTS = 3
MIN_INTERVAL = 1.0

_last_request_at = 0.0


def _throttle():
    global _last_request_at
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"<li[^>]*>", "\n- ", raw, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def _posted_at(created_ms) -> Optional[str]:
    """Lever createdAt is epoch milliseconds."""
    if not created_ms:
        return None
    try:
        return datetime.fromtimestamp(
            created_ms / 1000, timezone.utc
        ).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def normalize_job(job: dict) -> dict:
    cats = job.get("categories") or {}

    locations = [
        loc.strip() for loc in (cats.get("allLocations") or []) if loc and loc.strip()
    ]
    if not locations and cats.get("location"):
        locations = [cats["location"].strip()]

    workplace = (job.get("workplaceType") or "").lower()
    remote_type = workplace if workplace in ("remote", "hybrid", "onsite") else "unknown"

    sections = []
    opening = (job.get("openingPlain") or "").strip()
    body = (job.get("descriptionBodyPlain") or job.get("descriptionPlain") or "").strip()
    if opening:
        sections.append(("other", opening))
    if body:
        sections.append(("other", body))

    for item in job.get("lists") or []:
        text = strip_html(item.get("content") or "")
        if text:
            sections.append((bucket_section(item.get("text")), text))

    # EEO / accommodation boilerplate. Kept for salary regex, never signal.
    additional = (job.get("additionalPlain") or "").strip()
    if additional:
        sections.append(("other", additional))

    description_text = "\n\n".join(t for _, t in sections)

    return {
        "ats_job_id": str(job["id"]),
        "title": (job.get("text") or "").strip(),
        "location": " | ".join(locations) if locations else None,
        "locations": locations,
        "remote_type": remote_type,
        "department": (cats.get("department") or "").strip() or None,
        "description_text": description_text,
        "sections": sections,
        "apply_url": job.get("hostedUrl") or job.get("applyUrl"),
        "posted_at": _posted_at(job.get("createdAt")),
        # salaryRange is frequently absent. Regex over description_text is primary.
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "salary_source": "none",
    }


def parse_payload(payload) -> list:
    """Lever returns a bare array. An object means we hit the wrong endpoint."""
    if not isinstance(payload, list):
        raise ValueError("expected a bare JSON array")
    return [normalize_job(j) for j in payload]


def fetch(board_token: str, session=None) -> FetchResult:
    url = API_URL.format(token=board_token)
    sess = session or requests
    last_error = None
    last_status = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            resp = sess.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
            continue

        last_status = resp.status_code

        if resp.status_code == 404:
            return FetchResult("failed", [], 404, "board not found (check board_token)")

        if resp.status_code >= 500 or resp.status_code == 429:
            last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
            continue

        if resp.status_code != 200:
            return FetchResult("failed", [], resp.status_code, f"HTTP {resp.status_code}")

        try:
            postings = parse_payload(resp.json())
        except ValueError as e:
            return FetchResult("failed", [], resp.status_code, f"parse error: {e}")

        # 200 with [] is a real answer: this account has no public postings.
        # The writer's empty-board guard decides what that means for closures.
        return FetchResult("success", postings, resp.status_code, None)

    return FetchResult("failed", [], last_status, last_error or "exhausted retries")