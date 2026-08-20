"""Recompute role_category on every posting from the current classifier.

role_category is DERIVED: a pure function of the stored title. Unlike
closed_at and first_seen, which are observed once and can never be
reconstructed, this can be rebuilt at any time, including against closed
postings. Run it whenever src/normalize/roles.py changes.

  python -m src.normalize.reclassify            # show what would change
  python -m src.normalize.reclassify --apply    # write it
"""

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from src.normalize.roles import classify_role

DB_PATH = Path("data/jobs.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--show", type=int, default=15, help="example titles per change")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found.")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, title, role_category FROM postings").fetchall()

    changes = []
    for pid, title, old in rows:
        new = classify_role(title)
        if new != old:
            changes.append((pid, title, old, new))

    if not changes:
        print(f"{len(rows)} postings, nothing to change.")
        return

    moves = Counter((o, n) for _, _, o, n in changes)
    print(f"{len(changes)} of {len(rows)} postings would change:\n")
    for (old, new), n in moves.most_common():
        print(f"  {n:>4}  {old:<16} -> {new}")

    print(f"\nexamples:")
    for _, title, old, new in changes[:args.show]:
        print(f"  {old:<16} -> {new:<16} {title[:50]}")

    after = Counter(classify_role(t) for _, t, _ in rows)
    print("\nresulting distribution:")
    for cat, n in after.most_common():
        print(f"  {n:>4}  {cat}")

    if not args.apply:
        print("\nDRY RUN. re-run with --apply to write.")
        return

    conn.executemany(
        "UPDATE postings SET role_category = ? WHERE id = ?",
        [(new, pid) for pid, _, _, new in changes],
    )
    conn.commit()
    conn.close()
    print(f"\napplied to {len(changes)} postings.")


if __name__ == "__main__":
    main()