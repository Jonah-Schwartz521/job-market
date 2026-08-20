"""Persist a FetchResult: postings, locations, skills, closures, audit row.

The delisting rules live here and are the part of this project that cannot
be repaired after the fact. Read the guards before changing anything.

  - A FAILED fetch changes nothing. No inserts, no last_seen, no closures.
  - A SUCCESSFUL fetch returning zero postings never closes anything.
    An empty board and a broken board look identical from here, so a human
    confirms before a mass closure is written.
  - Posting content freezes at first observation. Only last_seen, closed_at,
    posted_at, and NULL-valued salary fields are ever updated.
  - Skills are RE-EXTRACTED every run from fresh text, so a skill added to a
    live posting on day 40 is recorded on day 40. Insert-only, never deleted.
"""

import csv
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.normalize.roles import classify_role
from src.normalize.salary import extract as extract_salary
from src.normalize.seniority import classify_seniority
from src.normalize.skills import load_matcher

REVIEW_QUEUE = Path("data/review_queue.csv")

SALARY_FIELDS = (
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_source",
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def open_postings(conn, company_id):
    """ats_job_id -> posting row id, for every currently-open posting."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT ats_job_id, id FROM postings "
            "WHERE company_id = ? AND closed_at IS NULL",
            (company_id,),
        )
    }


def _insert_posting(conn, company_id, p, now):
    cur = conn.execute(
        """
        INSERT INTO postings (
          company_id, ats_job_id, title, role_category, seniority, location,
          remote_type, department, description_text, salary_min, salary_max,
          salary_currency, salary_period, salary_source, apply_url, posted_at,
          first_seen, last_seen
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            company_id,
            p["ats_job_id"],
            p["title"],
            classify_role(p["title"]),
            classify_seniority(p["title"]),
            p.get("location"),
            p.get("remote_type") or "unknown",
            p.get("department"),
            p.get("description_text"),
            p.get("salary_min"),
            p.get("salary_max"),
            p.get("salary_currency"),
            p.get("salary_period"),
            p.get("salary_source") or "none",
            p.get("apply_url"),
            p.get("posted_at"),
            now,
            now,
        ),
    )
    posting_id = cur.lastrowid

    for ordinal, loc in enumerate(p.get("locations") or []):
        if loc:
            conn.execute(
                "INSERT INTO posting_locations (posting_id, location, ordinal) "
                "VALUES (?,?,?)",
                (posting_id, loc, ordinal),
            )
    return posting_id


def _touch_posting(conn, posting_id, p, now):
    """Move last_seen. Fill NULL fields only. Never overwrite content.

    Returns True if a salary field was filled in.
    """
    conn.execute("UPDATE postings SET last_seen = ? WHERE id = ?", (now, posting_id))

    # posted_at is immutable upstream; NULL -> value only completes a record.
    if p.get("posted_at"):
        conn.execute(
            "UPDATE postings SET posted_at = ? WHERE id = ? AND posted_at IS NULL",
            (p["posted_at"], posting_id),
        )

    row = conn.execute(
        f"SELECT {', '.join(SALARY_FIELDS)} FROM postings WHERE id = ?", (posting_id,)
    ).fetchone()
    current = dict(zip(SALARY_FIELDS, row))

    # salary_source is bookkeeping, not a value; it rides along with the rest.
    if current["salary_min"] is not None or current["salary_max"] is not None:
        return False

    incoming = {f: p.get(f) for f in SALARY_FIELDS}
    if incoming["salary_min"] is None and incoming["salary_max"] is None:
        return False

    conn.execute(
        f"UPDATE postings SET {', '.join(f + ' = ?' for f in SALARY_FIELDS)} "
        "WHERE id = ?",
        tuple(incoming[f] for f in SALARY_FIELDS) + (posting_id,),
    )
    return True


def _write_skills(conn, posting_id, sections, matcher, today):
    """INSERT OR IGNORE, so new mentions are added and existing ones keep
    their original first_seen."""
    n = 0
    for skill_id, section in matcher.match_sections(sections):
        cur = conn.execute(
            "INSERT OR IGNORE INTO posting_skills "
            "(posting_id, skill_id, section, first_seen) VALUES (?,?,?,?)",
            (posting_id, skill_id, section, today),
        )
        n += cur.rowcount
    return n


def _flush_review_queue(counts):
    """Merge new unmatched-token counts into data/review_queue.csv.

    Sorted by frequency. Never auto-promoted into skill_aliases: a human
    reviews this and edits config/skills.yml.
    """
    if not counts:
        return
    existing = Counter()
    if REVIEW_QUEUE.exists():
        with open(REVIEW_QUEUE, newline="") as f:
            for row in csv.DictReader(f):
                existing[row["token"]] = int(row["count"])
    existing.update(counts)

    REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_QUEUE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token", "count"])
        for tok, n in existing.most_common():
            w.writerow([tok, n])


def write_result(conn, company_id, result, started_at=None, run_date=None,
                 verbose=True, matcher=None):
    """Apply one company's fetch to the database. One transaction, all or nothing.

    Returns a dict summarising what happened.
    """
    now = _now()
    started_at = started_at or now
    run_date = run_date or _today()

    stats = {
        "status": result.status,
        "inserted": 0,
        "seen": 0,
        "closed": 0,
        "salary_filled": 0,
        "skills": 0,
        "skipped_closures": False,
        "error": result.error,
    }

    unmatched = Counter()

    try:
        conn.execute("BEGIN")

        conn.execute(
            """
            INSERT INTO fetch_runs (
              company_id, run_date, started_at, finished_at,
              status, http_status, posting_count, error
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                company_id,
                run_date,
                started_at,
                now,
                result.status,
                result.http_status,
                result.posting_count,
                result.error,
            ),
        )

        # A failed fetch is recorded and nothing else. This is the whole point.
        if not result.ok:
            conn.execute("COMMIT")
            return stats

        existing = open_postings(conn, company_id)
        seen_ids = set()

        if matcher is None:
            matcher = load_matcher(conn)

        for p in result.postings:
            job_id = p["ats_job_id"]
            seen_ids.add(job_id)

            # No ATS gives a usable comp field, so parse the body. Only fills
            # when the fetcher found nothing structured.
            if p.get("salary_min") is None and p.get("salary_max") is None:
                p.update(extract_salary(p.get("description_text")))

            if job_id in existing:
                stats["seen"] += 1
                posting_id = existing[job_id]
                if _touch_posting(conn, posting_id, p, now):
                    stats["salary_filled"] += 1
            else:
                posting_id = _insert_posting(conn, company_id, p, now)
                stats["inserted"] += 1

            # Skills come from the FRESH text every run, even though
            # description_text froze at first observation.
            sections = p.get("sections") or [("other", p.get("description_text") or "")]
            stats["skills"] += _write_skills(conn, posting_id, sections, matcher, run_date)
            # Discovery only looks where tools are actually named. About Us
            # and EEO boilerplate would otherwise dominate the queue.
            unmatched.update(matcher.unmatched_tokens(
                [(b, t) for b, t in sections if b != "other"]
            ))

        # Guard: a successful fetch of an empty board never closes anything.
        # CLAUDE.md is explicit about this and it cannot be undone.
        if not result.postings and existing:
            stats["skipped_closures"] = True
            if verbose:
                print(
                    f"  WARNING company {company_id}: fetch succeeded with 0 postings "
                    f"but {len(existing)} are open. Closures SKIPPED. Verify by hand."
                )
            conn.execute("COMMIT")
            return stats

        vanished = [pid for jid, pid in existing.items() if jid not in seen_ids]
        for posting_id in vanished:
            conn.execute(
                "UPDATE postings SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                (run_date, posting_id),
            )
        stats["closed"] = len(vanished)

        conn.execute("COMMIT")
        _flush_review_queue(unmatched)

    except Exception:
        conn.execute("ROLLBACK")
        raise

    return stats