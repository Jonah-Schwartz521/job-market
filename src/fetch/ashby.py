"""Fetch and normalize postings from an Ashby job board.

Same FetchResult contract as the other fetchers. Ashby differences:
  - response is {"jobs": [...], "apiVersion": ...}
  - descriptionPlain is already plain text; descriptionHtml carries the
    <h1>/<h2> headers we need for section bucketing
  - publishedAt is a real ISO timestamp -> posted_at
  - workplaceType gives a real remote_type
  - secondaryLocations is an array -> posting_locations
  - compensation is STRUCTURED: minValue/maxValue/currencyCode/interval.
    This is the only source that gives salary without regex, so these
    postings get salary_source='structured'.

?includeCompensation=true is required or the compensation object is absent.

This module does not touch SQLite.
"""

import time
from datetime import datetime, timezone
from typing import Optional

import requests

from src.fetch.greenhouse import FetchResult, _HEADER_RE, _clean
from src.normalize.sections import bucket_section

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"

TIMEOUT = 20
MAX_ATTEMPTS = 3
MIN_INTERVAL = 1.0

_last_request_at = 0.0

# Ashby interval strings -> our salary_period vocabulary.
INTERVALS = {
    "1 YEAR": "year",
    "1 MONTH": "month",
    "2 WEEKS": "week",
    "1 WEEK": "week",
    "1 DAY": "day",
    "1 HOUR": "hour",
}

REMOTE_TYPES = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def _throttle():
    global _last_request_at
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _posted_at(raw) -> Optional[str]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).isoformat(timespec="seconds")
    except (TypeError, ValueError, AttributeError):
        return None


def split_sections(raw_html: str):
    """Ashby ships real HTML (not escaped), so no pre-unescape here."""
    if not raw_html:
        return []

    chunks, pos, header = [], 0, None
    for m in _HEADER_RE.finditer(raw_html):
        body = _clean(raw_html[pos:m.start()])
        if body:
            chunks.append((bucket_section(header), body))
        header = _clean(m.group("h") or m.group("b") or "")
        if len(header) > 60:
            header = None
        pos = m.end()

    tail = _clean(raw_html[pos:])
    if tail:
        chunks.append((bucket_section(header), tail))
    return chunks


def parse_compensation(comp):
    """Widest band across every Salary component, matching the regex rule.

    Ashby posts one tier per geography, so a role can carry several ranges.
    Equity, bonus and commission components are ignored: this column means
    base salary.
    """
    empty = {
        "salary_min": None, "salary_max": None, "salary_currency": None,
        "salary_period": None, "salary_source": "none",
    }
    if not comp:
        return empty

    components = []
    for tier in comp.get("compensationTiers") or []:
        components.extend(tier.get("components") or [])
    if not components:
        components = comp.get("summaryComponents") or []

    salaries = [
        c for c in components
        if c.get("compensationType") == "Salary"
        and c.get("minValue") is not None
        and INTERVALS.get(c.get("interval"))
    ]
    if not salaries:
        return empty

    # Never mix periods in one figure; trust the most common.
    periods = [INTERVALS[c["interval"]] for c in salaries]
    period = max(set(periods), key=periods.count)
    same = [c for c in salaries if INTERVALS[c["interval"]] == period]

    currencies = [c["currencyCode"] for c in same if c.get("currencyCode")]
    return {
        "salary_min": float(min(c["minValue"] for c in same)),
        "salary_max": float(max(c.get("maxValue") or c["minValue"] for c in same)),
        "salary_currency": currencies[0] if currencies else None,
        "salary_period": period,
        "salary_source": "structured",
    }


def normalize_job(job: dict) -> dict:
    locations = []
    primary = (job.get("location") or "").strip()
    if primary:
        locations.append(primary)
    for sec in job.get("secondaryLocations") or []:
        loc = (sec.get("location") or "").strip()
        if loc and loc not in locations:
            locations.append(loc)

    workplace = (job.get("workplaceType") or "").lower()
    remote_type = REMOTE_TYPES.get(workplace, "unknown")
    if remote_type == "unknown" and job.get("isRemote"):
        remote_type = "remote"

    sections = split_sections(job.get("descriptionHtml") or "")
    if sections:
        description_text = "\n\n".join(t for _, t in sections)
    else:
        description_text = (job.get("descriptionPlain") or "").strip()
        sections = [("other", description_text)] if description_text else []

    row = {
        "ats_job_id": str(job["id"]),
        "title": (job.get("title") or "").strip(),
        "location": " | ".join(locations) if locations else None,
        "locations": locations,
        "remote_type": remote_type,
        "department": (job.get("department") or "").strip() or None,
        "description_text": description_text,
        "sections": sections,
        "apply_url": job.get("jobUrl") or job.get("applyUrl"),
        "posted_at": _posted_at(job.get("publishedAt")),
    }
    row.update(parse_compensation(job.get("compensation")))
    return row


def parse_payload(payload) -> list:
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise ValueError("expected an object with a 'jobs' key")
    jobs = payload["jobs"]
    if not isinstance(jobs, list):
        raise ValueError("'jobs' is not a list")
    # isListed=false means the posting exists but is not on the public board.
    return [normalize_job(j) for j in jobs if j.get("isListed", True)]


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

        if resp.status_code in (401, 404):
            return FetchResult("failed", [], resp.status_code,
                               "board not found (check board_token)")

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

        return FetchResult("success", postings, resp.status_code, None)

    return FetchResult("failed", [], last_status, last_error or "exhausted retries")