"""Recompute derived columns on every posting: role_category and seniority.

Both are pure functions of the stored title. Unlike closed_at and
first_seen, which are observed once and can never be reconstructed, these
can be rebuilt at any time including against closed postings. Run this
whenever roles.py or seniority.py changes.

  python -m src.normalize.reclassify            # show what would change
  python -m src.normalize.reclassify --apply    # write it
"""

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from src.normalize.roles import classify_role
from src.normalize.seniority import classify_seniority

DB_PATH = Path("data/jobs.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--show", type=int, default=12, help="example titles")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found.")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, title, role_category, seniority FROM postings"
    ).fetchall()

    changes = []
    for pid, title, old_role, old_sen in rows:
        new_role = classify_role(title)
        new_sen = classify_seniority(title)
        if (new_role, new_sen) != (old_role, old_sen):
            changes.append((pid, title, old_role, new_role, old_sen, new_sen))

    if not changes:
        print(f"{len(rows)} postings, nothing to change.")
        return

    role_moves = Counter((o, n) for _, _, o, n, _, _ in changes if o != n)
    sen_moves = Counter((o, n) for _, _, _, _, o, n in changes if o != n)

    print(f"{len(changes)} of {len(rows)} postings would change\n")
    if role_moves:
        print("role_category:")
        for (old, new), n in role_moves.most_common():
            print(f"  {n:>4}  {old:<16} -> {new}")
        print()
    if sen_moves:
        print("seniority:")
        for (old, new), n in sen_moves.most_common():
            print(f"  {n:>4}  {old:<16} -> {new}")
        print()

    print("examples:")
    for _, title, _, nr, _, ns in changes[:args.show]:
        print(f"  {nr:<16} {ns:<12} {title[:46]}")

    print("\nresulting seniority distribution:")
    for lvl, n in Counter(classify_seniority(t) for _, t, _, _ in rows).most_common():
        print(f"  {n:>5}  {lvl}")

    if not args.apply:
        print("\nDRY RUN. re-run with --apply to write.")
        return

    conn.executemany(
        "UPDATE postings SET role_category = ?, seniority = ? WHERE id = ?",
        [(nr, ns, pid) for pid, _, _, nr, _, ns in changes],
    )
    conn.commit()
    conn.close()
    print(f"\napplied to {len(changes)} postings.")


if __name__ == "__main__":
    main()