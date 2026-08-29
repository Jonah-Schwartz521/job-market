"""Rebuild data/review_queue.csv from a single corpus.

The queue is reviewed weekly sorted by frequency, so every count in it must
come from the same database. Mixing a dev copy with a prod snapshot makes
the ordering meaningless. This rebuilds the whole file from one db.

    python -m scripts.rebuild_queue                     # uses JOBS_DB
    python -m scripts.rebuild_queue --db jobs.prod.db
    python -m scripts.rebuild_queue --add-manual "real-world evidence"

Two kinds of row, distinguished by the source column:

  <db filename>  Capitalized single tokens the matcher could not claim.
                 Regenerated from scratch on every rebuild.
  manual         Phrases a human added: multi-word or lowercase terms that
                 TOKEN_RE cannot produce, so no run will ever reproduce them.
                 CARRIED FORWARD across rebuilds and recounted against the
                 same corpus, so their counts stay comparable.

Read-only on the database. Never touches skill_aliases.
"""

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.paths import db_path
from src.normalize.skills import load_matcher

OUT = Path("data/review_queue.csv")
MANUAL = "manual"


def manual_pattern(phrase):
    """Literal phrase, case-insensitive, hyphen and space interchangeable.

    'real-world data' has to also count 'Real World Data'. Trailing plural
    is allowed so 'electronic health records' counts too.
    """
    parts = [re.escape(p) for p in re.split(r"[\s-]+", phrase.strip()) if p]
    return re.compile(r"\b" + r"[\s-]+".join(parts) + r"s?\b", re.I)


def read_manual(path):
    """Existing manual phrases, so a rebuild never silently drops them."""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r["token"] for r in csv.DictReader(f)
                if (r.get("source") or "") == MANUAL]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None, help="database to count against")
    ap.add_argument("--out", default=str(OUT), type=Path)
    ap.add_argument("--add-manual", action="append", default=[], metavar="PHRASE",
                    help="add a manual phrase; repeatable")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, write nothing")
    args = ap.parse_args()

    db = Path(args.db) if args.db else db_path()
    if not db.exists():
        raise SystemExit(f"{db} not found")

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    matcher = load_matcher(conn)
    source = db.name

    phrases = list(dict.fromkeys(read_manual(args.out) + args.add_manual))
    pats = [(p, manual_pattern(p)) for p in phrases]

    auto, man, n = Counter(), Counter(), 0
    for (d,) in conn.execute(
            "SELECT description_text FROM postings WHERE description_text IS NOT NULL"):
        auto.update(matcher.unmatched_tokens([("requirements", d)]))
        for phrase, pat in pats:
            hits = len(pat.findall(d))
            if hits:
                man[phrase] += hits
        n += 1

    rows = [(t, c, source) for t, c in auto.items()] + \
           [(p, man[p], MANUAL) for p in phrases]
    rows.sort(key=lambda r: (-r[1], r[0], r[2]))

    print(f"postings scanned : {n}")
    print(f"corpus tokens    : {len(auto)} ({sum(auto.values())} mentions)")
    print(f"manual phrases   : {len(phrases)} ({sum(man.values())} mentions)")
    print(f"source tag       : {source}")
    if args.dry_run:
        print("\ndry run, nothing written. manual rows would be:")
        for p in sorted(phrases, key=lambda x: -man[x]):
            print(f"  {p:28} {man[p]}")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token", "count", "source"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
