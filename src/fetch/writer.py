"""Persist a FetchResult: postings, locations, closures, and the audit row.

The delisting rules live here and are the part of this project that cannot
be repaired after the fact. Read the guards before changing anything.

  - A FAILED fetch changes nothing. No inserts, no last_seen, no closures.
  - A SUCCESSFUL fetch returning zero postings never closes anything.
    An empty board and a broken board look identical from here, so a human
    confirms before a mass closure is written.
  - Posting content freezes at first observation. Only last_seen, closed_at,
    and NULL-valued salary fields are ever updated on an existing row.
"""
"""Persist a FetchResult: postings, locations, closures, and the audit row.

The delisting rules live here and are the part of this project that cannot
be repaired after the fact. Read the guards before changing anything.

  - A FAILED fetch changes nothing. No inserts, no last_seen, no closures.
  - A SUCCESSFUL fetch returning zero postings never closes anything.
    An empty board and a broken board look identical from here, so a human
    confirms before a mass closure is written.
  - Posting content freezes at first observation. Only last_seen, closed_at,
    and NULL-valued salary fields are ever updated on an existing row.
"""

import sqlite3
from datetime import datetime, timezone

from src.normalize.roles import classify_role

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
          company_id, ats_job_id, title, role_category, location, remote_type,
          department, description_text, salary_min, salary_max, salary_currency,
          salary_period, salary_source, apply_url, first_seen, last_seen
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            company_id,
            p["ats_job_id"],
            p["title"],
            classify_role(p["title"]),
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
    """Move last_seen. Fill NULL salary fields only. Never overwrite content.

    Returns True if a salary field was filled in.
    """
    conn.execute("UPDATE postings SET last_seen = ? WHERE id = ?", (now, posting_id))

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


def write_result(conn, company_id, result, started_at=None, run_date=None, verbose=True):
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
        "skipped_closures": False,
        "error": result.error,
    }

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

        for p in result.postings:
            job_id = p["ats_job_id"]
            seen_ids.add(job_id)
            if job_id in existing:
                stats["seen"] += 1
                if _touch_posting(conn, existing[job_id], p, now):
                    stats["salary_filled"] += 1
            else:
                _insert_posting(conn, company_id, p, now)
                stats["inserted"] += 1

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

    except Exception:
        conn.execute("ROLLBACK")
        raise

    return stats
import sqlite3
from datetime import datetime, timezone

from src.normalize.roles import classify_role

SALARY_FIELDS = ("salary_min", "salary_max", "salary_currency", "salary_period", "salary_source")

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

