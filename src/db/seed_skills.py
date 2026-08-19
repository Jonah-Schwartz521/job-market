"""Load config/skills.yml into skills + skill_aliases. Idempotent upsert.

Never adds aliases on its own. This file is the only path into the alias
table, and config/skills.yml is the only input, so every alias is a git diff
you approved.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

DB_PATH = Path("data/jobs.db")
CONFIG_PATH = Path("config/skills.yml")

VALID_CATEGORIES = {
    "language", "cloud", "data", "ml", "devops", "database", "bi", "web", "practice",
}


def load_config(path):
    with open(path) as f:
        doc = yaml.safe_load(f)

    rows = (doc or {}).get("skills") or []
    if not rows:
        raise SystemExit(f"no skills found in {path}")

    seen_canon, seen_alias = set(), {}
    for i, row in enumerate(rows):
        canon = (row.get("canonical") or "").strip()
        if not canon:
            raise SystemExit(f"entry {i} has no canonical name")
        if row.get("category") not in VALID_CATEGORIES:
            raise SystemExit(f"{canon}: bad category {row.get('category')!r}")

        key = canon.lower()
        if key in seen_canon:
            raise SystemExit(f"duplicate canonical: {canon}")
        seen_canon.add(key)

        # A bad regex should fail here, not halfway through a nightly run.
        for field in ("guard", "deny"):
            pat = row.get(field)
            if pat:
                try:
                    re.compile(pat)
                except re.error as e:
                    raise SystemExit(f"{canon}: bad {field} regex: {e}")

        for alias in row.get("aliases") or []:
            a = alias.strip().lower()
            if not a:
                raise SystemExit(f"{canon}: empty alias")
            if a in seen_alias and seen_alias[a] != canon:
                raise SystemExit(f"alias {a!r} claimed by both {seen_alias[a]} and {canon}")
            seen_alias[a] = canon

    # An alias colliding with another skill's canonical name is a silent
    # misattribution, so it fails loudly here instead.
    for alias, owner in seen_alias.items():
        if alias in seen_canon and alias != owner.lower():
            raise SystemExit(f"alias {alias!r} on {owner} collides with a canonical name")

    return rows


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. run: python -m src.db.init")

    rows = load_config(CONFIG_PATH)
    today = datetime.now(timezone.utc).date().isoformat()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    added = updated = unchanged = 0

    for row in rows:
        canon = row["canonical"].strip()
        category = row["category"]
        guard = row.get("guard")
        deny = row.get("deny")

        before = conn.execute(
            "SELECT id, category, guard, deny FROM skills WHERE canonical_name = ?",
            (canon,),
        ).fetchone()

        conn.execute(
            """
            INSERT INTO skills (canonical_name, category, guard, deny, first_seen_date)
            VALUES (?,?,?,?,?)
            ON CONFLICT (canonical_name) DO UPDATE SET
              category = excluded.category,
              guard    = excluded.guard,
              deny     = excluded.deny
            """,
            (canon, category, guard, deny, today),
        )

        skill_id = conn.execute(
            "SELECT id FROM skills WHERE canonical_name = ?", (canon,)
        ).fetchone()[0]

        if before is None:
            added += 1
            print(f"added      {canon}  ({category})")
        elif (before[1], before[2], before[3]) != (category, guard, deny):
            updated += 1
            print(f"updated    {canon}")
        else:
            unchanged += 1

        # The canonical name is always a matchable surface, not just aliases.
        surfaces = {canon.lower()} | {a.strip().lower() for a in (row.get("aliases") or [])}
        for alias in surfaces:
            conn.execute(
                "INSERT INTO skill_aliases (alias, skill_id) VALUES (?,?) "
                "ON CONFLICT (alias) DO UPDATE SET skill_id = excluded.skill_id",
                (alias, skill_id),
            )

    conn.commit()

    orphans = conn.execute(
        "SELECT canonical_name FROM skills WHERE canonical_name NOT IN (%s)"
        % ",".join("?" for _ in rows),
        [r["canonical"].strip() for r in rows],
    ).fetchall()

    total_aliases = conn.execute("SELECT COUNT(*) FROM skill_aliases").fetchone()[0]
    conn.close()

    print(f"\n{added} added, {updated} updated, {unchanged} unchanged")
    print(f"{len(rows)} skills, {total_aliases} alias surfaces")
    for (name,) in orphans:
        print(f"WARNING  in db but not in yml: {name}")


if __name__ == "__main__":
    main()