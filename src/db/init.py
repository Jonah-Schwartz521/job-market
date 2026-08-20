"""Create the SQLite schema at data/jobs.db. Idempotent."""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/jobs.db")

PRAGMAS = [
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
]

TABLES = [
    ("companies", """
        CREATE TABLE IF NOT EXISTS companies (
          id          INTEGER PRIMARY KEY,
          name        TEXT NOT NULL,
          ats         TEXT NOT NULL CHECK (ats IN ('greenhouse','lever','ashby')),
          board_token TEXT NOT NULL,
          industry    TEXT NOT NULL,
          active      INTEGER NOT NULL DEFAULT 1,
          added_at    TEXT NOT NULL,
          UNIQUE (ats, board_token)
        )
    """),
    ("postings", """
        CREATE TABLE IF NOT EXISTS postings (
          id               INTEGER PRIMARY KEY,
          company_id       INTEGER NOT NULL REFERENCES companies(id),
          ats_job_id       TEXT NOT NULL,
          title            TEXT NOT NULL,
          role_category    TEXT NOT NULL DEFAULT 'other',
          seniority        TEXT NOT NULL DEFAULT 'unspecified',
          location         TEXT,
          remote_type      TEXT CHECK (remote_type IN ('remote','hybrid','onsite','unknown')),
          department       TEXT,
          description_text TEXT,
          salary_min       REAL,
          salary_max       REAL,
          salary_currency  TEXT,
          salary_period    TEXT CHECK (salary_period IN ('year','month','week','day','hour')),
          salary_source    TEXT NOT NULL DEFAULT 'none'
                             CHECK (salary_source IN ('structured','regex','none')),
          apply_url        TEXT,
          posted_at        TEXT,
          first_seen       TEXT NOT NULL,
          last_seen        TEXT NOT NULL,
          closed_at        TEXT
        )
    """),
    ("posting_locations", """
        CREATE TABLE IF NOT EXISTS posting_locations (
          posting_id INTEGER NOT NULL REFERENCES postings(id),
          location   TEXT NOT NULL,
          ordinal    INTEGER NOT NULL,
          PRIMARY KEY (posting_id, ordinal)
        ) WITHOUT ROWID
    """),


    ("fetch_runs", """
        CREATE TABLE IF NOT EXISTS fetch_runs (
          id            INTEGER PRIMARY KEY,
          company_id    INTEGER NOT NULL REFERENCES companies(id),
          run_date      TEXT NOT NULL,
          started_at    TEXT NOT NULL,
          finished_at   TEXT,
          status        TEXT NOT NULL CHECK (status IN ('success','failed')),
          http_status   INTEGER,
          posting_count INTEGER,
          error         TEXT
        )
    """),
    ("skills", """
        CREATE TABLE IF NOT EXISTS skills (
          id              INTEGER PRIMARY KEY,
          canonical_name  TEXT NOT NULL UNIQUE,
          category        TEXT,
          guard           TEXT,
          deny            TEXT,
          first_seen_date TEXT
        )
    """),
    ("skill_aliases", """
        CREATE TABLE IF NOT EXISTS skill_aliases (
          alias    TEXT PRIMARY KEY,
          skill_id INTEGER NOT NULL REFERENCES skills(id)
        )
    """),
    ("posting_skills", """
        CREATE TABLE IF NOT EXISTS posting_skills (
          posting_id INTEGER NOT NULL REFERENCES postings(id),
          skill_id   INTEGER NOT NULL REFERENCES skills(id),
          section    TEXT NOT NULL
                       CHECK (section IN ('requirements','responsibilities','other')),
          first_seen TEXT NOT NULL,
          PRIMARY KEY (posting_id, skill_id, section)
        ) WITHOUT ROWID
    """),
    ("daily_counts", """
        CREATE TABLE IF NOT EXISTS daily_counts (
          snapshot_date TEXT NOT NULL,
          industry      TEXT NOT NULL,
          skill_id      INTEGER NOT NULL REFERENCES skills(id),
          posting_count INTEGER NOT NULL,
          PRIMARY KEY (snapshot_date, industry, skill_id)
        ) WITHOUT ROWID
    """),
]

INDEXES = [
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_postings_open
         ON postings (company_id, ats_job_id) WHERE closed_at IS NULL""",
    "CREATE INDEX IF NOT EXISTS ix_postings_company_open ON postings (company_id, closed_at)",
    "CREATE INDEX IF NOT EXISTS ix_postings_role ON postings (role_category)",
    "CREATE INDEX IF NOT EXISTS ix_postings_first_seen ON postings (first_seen)",
    "CREATE INDEX IF NOT EXISTS ix_fetch_runs_company_date ON fetch_runs (company_id, run_date)",
    "CREATE INDEX IF NOT EXISTS ix_skill_aliases_skill ON skill_aliases (skill_id)",
    "CREATE INDEX IF NOT EXISTS ix_posting_skills_skill ON posting_skills (skill_id)",
    "CREATE INDEX IF NOT EXISTS ix_posting_locations_loc ON posting_locations (location)",
]

def table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None

def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    for pragma in PRAGMAS: 
        conn.execute(pragma)

    for name, ddl in TABLES: 
        existed = table_exists(conn, name)
        conn.execute(ddl)
        print(f"{'exists ' if existed else 'created'}  {name}")

    for ddl in INDEXES:
        conn.execute(ddl)
    print(f"indexes: {len(INDEXES)} ensured")

    conn.commit()
    conn.close()
    print(f"\nSchema Ready at {DB_PATH}")

if __name__ == "__main__":
    main()