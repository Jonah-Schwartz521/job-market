"""Map free-text job-description section headers onto three buckets.

Shared by every fetcher. Headers are never standardized: the same company
ships 'What You'll Do' in one posting and 'What You"ll Do' (straight double
quote, a typo) in the next, and Greenhouse mixes <h3> tags with bold
paragraphs inside a single board. Match on keywords, never exact strings.

Buckets:
  requirements     the signal. skills here are what the job demands.
  responsibilities what the role does. useful, weaker signal.
  other            About Us, benefits, EEO boilerplate, location. noise.
"""

import re

# Order matters: first bucket with a keyword hit wins.
SECTION_KEYWORDS = (
    ("requirements", (
        "who you are", "who we are looking", "requirement", "qualification",
        "you have", "about you", "what you bring", "what we look", "skills",
        "experience", "youll need", "you will need", "were looking for",
        "nice to have", "must have", "minimum", "preferred",
    )),
    ("responsibilities", (
        "what youll do", "what you will do", "what youll be doing",
        "what you will be doing", "responsibilit", "the role", "your impact",
        "day to day", "the job", "in this role", "what the job involves",
    )),
)

_QUOTES = re.compile(r"[\u2018\u2019\u201c\u201d'\"`]")
_NONWORD = re.compile(r"[^a-z0-9]+")


def bucket_section(header: str) -> str:
    h = _QUOTES.sub("", (header or "").lower())
    h = _NONWORD.sub(" ", h).strip()
    if not h:
        return "other"
    for bucket, keywords in SECTION_KEYWORDS:
        if any(k in h for k in keywords):
            return bucket
    return "other"