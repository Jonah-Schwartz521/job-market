"""Daily collection: fetch every active company and persist the result.

One company's failure never stops the run. Each company gets its own
transaction and its own fetch_runs row, so a partial run is still a
truthful record of what was and wasn't collected.

  python -m src.fetch.run
  python -m src.fetch.run --company stripe
  python -m src.fetch.run --dry-run
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.fetch import greenhouse, lever
from src.fetch.greenhouse import FetchResult
from src.fetch.writer import write_result
from src.normalize.skills import load_matcher
from src.fetch import ashby, greenhouse, lever

DB_PATH = Path("data/jobs.db")

FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active_companies(conn, only=None):
    sql = "SELECT id, name, ats, board_token FROM companies WHERE active = 1"
    params = []
    if only:
        sql += " AND board_token = ?"
        params.append(only)
    return conn.execute(sql + " ORDER BY name", params).fetchall()


def run_one(conn, company, run_date=None, dry_run=False, matcher=None):
    company_id, name, ats, token = company
    started_at = _now()

    fetcher = FETCHERS.get(ats)
    if fetcher is None:
        result = FetchResult("failed", [], None, f"no fetcher for ats '{ats}'")
    else:
        try:
            result = fetcher(token)
        except Exception as e:
            # An unexpected fetcher bug is a failed fetch, not a crash.
            # Recording it as 'failed' means nothing gets closed.
            result = FetchResult("failed", [], None, f"{type(e).__name__}: {e}")

    if dry_run:
        return {
            "status": result.status,
            "inserted": 0,
            "seen": 0,
            "closed": 0,
            "salary_filled": 0,
            "skills": 0,
            "skipped_closures": False,
            "error": result.error,
            "fetched": result.posting_count,
        }

    stats = write_result(
        conn, company_id, result, started_at=started_at, run_date=run_date,
        matcher=matcher,
    )
    stats["fetched"] = result.posting_count
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", help="board_token, to run a single company")
    ap.add_argument("--run-date", help="YYYY-MM-DD, defaults to today UTC")
    ap.add_argument("--dry-run", action="store_true", help="fetch but write nothing")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. run: python -m src.db.init")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    companies = active_companies(conn, args.company)
    if not companies:
        raise SystemExit("no active companies matched")

    # Compiled once for the whole run, not once per company.
    matcher = None if args.dry_run else load_matcher(conn)

    print(f"{'company':<18} {'status':<8} {'got':>5} {'new':>5} {'seen':>5} "
          f"{'closed':>7} {'skills':>7}  notes")
    print("-" * 90)

    failures = 0
    totals = {"inserted": 0, "seen": 0, "closed": 0, "salary_filled": 0, "skills": 0}

    for company in companies:
        name = company[1]
        try:
            s = run_one(conn, company, run_date=args.run_date,
                        dry_run=args.dry_run, matcher=matcher)
        except Exception as e:
            # Writer-level failure. The transaction rolled back; keep going.
            failures += 1
            print(f"{name:<18} {'ERROR':<8} {'':>5} {'':>5} {'':>5} {'':>7} {'':>7}  "
                  f"{type(e).__name__}: {e}")
            continue

        notes = []
        if s["error"]:
            notes.append(s["error"])
        if s["skipped_closures"]:
            notes.append("CLOSURES SKIPPED")
        if s["salary_filled"]:
            notes.append(f"{s['salary_filled']} salary filled")

        if s["status"] != "success":
            failures += 1

        for k in totals:
            totals[k] += s[k]

        print(
            f"{name:<18} {s['status']:<8} {s['fetched']:>5} {s['inserted']:>5} "
            f"{s['seen']:>5} {s['closed']:>7} {s['skills']:>7}  {'; '.join(notes)}"
        )

    conn.close()

    print("-" * 90)
    print(
        f"{len(companies)} companies, {failures} failed. "
        f"{totals['inserted']} new, {totals['seen']} seen, {totals['closed']} closed, "
        f"{totals['skills']} skill mentions."
    )
    if args.dry_run:
        print("DRY RUN: nothing was written.")

    # Non-zero exit if every company failed, so cron surfaces a total outage.
    if failures == len(companies):
        sys.exit(1)


if __name__ == "__main__":
    main()