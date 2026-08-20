"""Fetch and normalize postings from a Greenhouse job board.

Returns a FetchResult, never a bare list. An empty board and a failed
request both yield zero postings; only `status` distinguishes them, and
the delisting logic depends on that distinction being explicit.

This module does not touch SQLite.
"""

import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

from src.normalize.sections import bucket_section

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

TIMEOUT = 20
MAX_ATTEMPTS = 3
MIN_INTERVAL = 1.0  # seconds between requests to this host

_last_request_at = 0.0


@dataclass
class FetchResult:
    status: str                      # 'success' | 'failed'
    postings: list = field(default_factory=list)
    http_status: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def posting_count(self) -> int:
        return len(self.postings)


def _throttle():
    global _last_request_at
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _clean(s: str) -> str:
    """Strip tags from already-unescaped HTML and normalize whitespace."""
    if not s:
        return ""
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)                # &amp;nbsp; -> &nbsp; -> \xa0
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def html_to_text(raw: str) -> str:
    """Greenhouse double-encodes: the content field is escaped HTML."""
    if not raw:
        return ""
    return _clean(html.unescape(raw))


def _posted_at(raw) -> Optional[str]:
    """Greenhouse first_published is ISO 8601 with a local UTC offset."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError):
        return None


# A header is either a real heading tag, or a paragraph whose entire content
# is bold. Greenhouse boards mix both, sometimes within one company.
_HEADER_RE = re.compile(
    r"<h[1-6][^>]*>(?P<h>.*?)</h[1-6]>"
    r"|<p[^>]*>\s*<strong[^>]*>(?P<b>.*?)</strong>\s*</p>",
    re.S | re.I,
)


def split_sections(raw: str):
    """Split escaped Greenhouse HTML into (bucket, text) chunks."""
    if not raw:
        return []

    doc = html.unescape(raw)
    chunks, pos, header = [], 0, None

    for m in _HEADER_RE.finditer(doc):
        body = _clean(doc[pos:m.start()])
        if body:
            chunks.append((bucket_section(header), body))
        header = _clean(m.group("h") or m.group("b") or "")
        # A "header" longer than a short line is really a bold sentence.
        if len(header) > 60:
            header = None
        pos = m.end()

    tail = _clean(doc[pos:])
    if tail:
        chunks.append((bucket_section(header), tail))

    return chunks


def normalize_job(job: dict) -> dict:
    """Map one Greenhouse job to the shared normalized shape."""
    location = (job.get("location") or {}).get("name")
    location = location.strip() if location else None

    departments = [
        d["name"].strip()
        for d in (job.get("departments") or [])
        if d.get("name") and d["name"].strip().lower() != "no department"
    ]

    sections = split_sections(job.get("content") or "")
    description_text = "\n\n".join(t for _, t in sections)

    return {
        "ats_job_id": str(job["id"]),
        "title": (job.get("title") or "").strip(),
        "location": location,
        # Greenhouse location.name is free text. "SF, NYC, SEA, CHI" and
        # "San Francisco, CA" are indistinguishable, so do not comma-split.
        # posting_locations is derived and can be rebuilt if that changes.
        "locations": [location] if location else [],
        "remote_type": "unknown",           # no such field on Greenhouse
        "department": departments[0] if departments else None,
        "description_text": description_text,
        "sections": sections,
        "apply_url": job.get("absolute_url"),
        "posted_at": _posted_at(job.get("first_published")),
        # Greenhouse exposes no compensation field at all.
        # src/normalize/salary.py fills these from description_text.
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "salary_source": "none",
    }


def parse_payload(payload) -> list:
    """Greenhouse returns {"jobs": [...]}. Anything else is a parse error."""
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise ValueError("expected an object with a 'jobs' key")
    jobs = payload["jobs"]
    if not isinstance(jobs, list):
        raise ValueError("'jobs' is not a list")
    return [normalize_job(j) for j in jobs]


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

        # 404 means the board token is wrong. Permanent, do not retry.
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

        return FetchResult("success", postings, resp.status_code, None)

    return FetchResult("failed", [], last_status, last_error or "exhausted retries")