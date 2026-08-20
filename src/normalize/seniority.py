"""Derive a seniority level from a job title.

Same class of column as role_category: DERIVED, so it can be recomputed at
any time against any posting including closed ones. Run
`python -m src.normalize.reclassify --apply` after changing anything here.

Order IS precedence, and it runs SENIOR-FIRST on purpose. "Senior Staff
Engineer" must resolve to staff, not senior, so staff is checked first.

Most titles carry no level word at all. Those return 'unspecified' rather
than being guessed into 'mid': a made-up level would quietly distort every
comparison built on this column.
"""

import re

SENIORITY_PATTERNS = {
    # \bintern\b does not match "Internal", so this is safe first.
    'intern':      r'\bintern\b|\binterns\b|\bco-?op\b|\bapprentice',

    'executive':   r'\bchief\b|\bc[teoif]o\b|\bvp\b|vice president|\bsvp\b|\bevp\b|\bpresident\b',
    'director':    r'\bdirector\b|\bhead of\b|\bhead,|\bdept head',
    'principal':   r'\bprincipal\b|\bdistinguished\b|\bfellow\b|\barchitect, principal',
    'staff':       r'\bstaff\b',
    'senior':      r'\bsenior\b|\bsr\.?\b|\blead\b|\bleads\b|\biv\b|\bl[5-6]\b',
    'mid':         r'\bmid-?level\b|\bii+\b|\bl[34]\b|\bintermediate\b',
    'entry':       r'\bjunior\b|\bjr\.?\b|\bentry.level\b|\bassociate\b|\bnew grad|\bgraduate\b|\bearly career\b|\btrainee\b|\bi\b|\bl[12]\b',
}


def classify_seniority(title: str) -> str:
    t = (title or "").lower()
    for level, pattern in SENIORITY_PATTERNS.items():
        if re.search(pattern, t):
            return level
    return 'unspecified'