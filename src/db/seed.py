"""Load config/companies.yml into the companies table. Indempotent upsert"""

# Imports 
import sqlite3
from datetime import datetime, timezone
from pathlib import Path 
import yaml 

from src.db.paths import db_path

# DB + Config Path 
DB_PATH = db_path()
CONFIG_PATH = Path("config/companies.yml")

REQUIRED = ["name", "ats", "board_token", "industry"]
VALID_ATS = ["greenhouse", "lever", "ashby"]

def load_config(path): 
    with open(path) as f:
        doc = yaml.safe_load(f)

        rows = (doc or {}).get("companies") or []
        if not rows: 
            raise SystemExit(f"No companies found in {path}")

        seen = set()
        for i, row in enumerate(rows):
            missing = [k for k in REQUIRED if not row.get(k)]
            if missing: 
                raise SystemExit(f"entry {i} ({row.get('name', '?')}) missing: {', '.join(missing)}")
            if row["ats"] not in VALID_ATS: 
                raise SystemExit(f"{row['name']}: unknown ats {row['ats']!r}")

            key = row['ats'], row['board_token']
            if key in seen: 
                raise SystemExit(f"duplicate board: {row['ats']}/{row['board_token']}")
            seen.add(key)

        return rows

def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. run: python -m src.db.init")

    rows = load_config(CONFIG_PATH)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    added = updated = unchanged = 0
    for row in rows: 
        active = 1 if row.get("active", True) else 0
        key = row["ats"], row["board_token"]

        before = conn.execute(
            "SELECT name, industry, active FROM companies WHERE ats=? AND board_token=?", key
        ).fetchone()

        conn.execute(
            """
            INSERT INTO companies (name, ats, board_token, industry, active, added_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT (ats, board_token) DO UPDATE SET
            name     = excluded.name,
            industry = excluded.industry,
            active   = excluded.active
            """,
            (row['name'], row['ats'], row['board_token'], row['industry'], active, now),
        )
    

        if before is None:
            added += 1
            print(f"added      {row['name']}  ({row['ats']}/{row['board_token']}, {row['industry']})")
        elif before != (row['name'], row['industry'], active):
            updated += 1
            print(f"updated    {row['name']}  {before} -> {(row['name'], row['industry'], active)}")
        else:
            unchanged += 1

    conn.commit()
    stale = conn.execute(
            "SELECT name, ats, board_token FROM companies WHERE (ats, board_token) NOT IN (%s)"
            % ",".join("(?,?)" for _ in rows),
            [v for r in rows for v in (r["ats"], r["board_token"])],
        ).fetchall()

    conn.close()

    print(f"\n{added} added, {updated} updated, {unchanged} unchanged")
    for name, ats, token in stale:
        print(f"WARNING  in db but not in yml: {name} ({ats}/{token})")


if __name__ == "__main__":
    main()




