"""Dictionary-based skill matching over job description sections.

Match is case-insensitive on word boundaries against skill_aliases. Short
ambiguous tokens (R, Go, SAS, dbt) carry a guard regex that must also appear
nearby, or a deny regex that kills the match outright.

Presence per section, never counts. Python appearing five times in one
requirements block says something about the writer, not about demand.

Unmatched capitalized tokens are logged with counts for weekly review. That
queue is the discovery mechanism: a static dictionary is structurally blind
to new tools, which are the interesting ones.
"""

import re
from collections import Counter

GUARD_WINDOW = 80

# Sentence-initial capitals and boilerplate proper nouns swamp the review
# queue otherwise. Measured against the real corpus, not guessed.
STOPWORDS = frozenset("""
a an the this that these those there here it its we our you your they their
he she his her i is are was were be been being have has had do does did will
would can could may might must shall should if then else when where while
who whom what which why how all any both each few more most other some such
no nor not only own same so than too very just now also and or but for with
from into during including until against among throughout despite towards
upon about above below over under again further once at by on in to of as
please note prior new senior staff lead principal director manager head
full part time role team job company work working works worked position
experience experienced years year strong excellent proven demonstrated
ability able skills knowledge understanding familiarity plus bonus nice
required preferred minimum qualifications responsibilities requirements
about who what why where when how join build create develop drive own lead
manage support provide serve define identify collaborate partner help
contribute deliver ensure improve maintain design implement product marketing 
legal finance sales operations strategy business development science analytics 
research partnerships accounting managers functional oriented premium affairs english
""".split())

TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9+#.\-]{1,24}\b")
SENTENCE_START_RE = re.compile(r"(?m)(^|[.!?:;]\s+|\n\s*[-*\u2022]?\s*)([A-Z])")


class SkillMatcher:
    """Compiled matcher built once per run from the skills tables."""

    def __init__(self, alias_rows, company_names=()):
        # alias_rows: (alias, skill_id, canonical_name, guard, deny)
        self._entries = []
        for alias, skill_id, canonical, guard, deny in alias_rows:
            self._entries.append((
                re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])",
                           re.I),
                skill_id,
                canonical,
                re.compile(guard, re.I) if guard else None,
                re.compile(deny, re.I) if deny else None,
            ))

        self._known = {a.lower() for a, *_ in alias_rows}
        self._noise = set(STOPWORDS)
        for name in company_names:
            self._noise.add(name.lower())
            self._noise.update(w.lower() for w in name.split())

    def match(self, text):
        """Return the set of skill_ids present in one chunk of text."""
        if not text:
            return set()
        found = set()
        for pattern, skill_id, _canon, guard, deny in self._entries:
            if skill_id in found:
                continue
            for m in pattern.finditer(text):
                lo = max(0, m.start() - GUARD_WINDOW)
                window = text[lo:m.end() + GUARD_WINDOW]
                if deny and deny.search(window):
                    continue
                if guard and not guard.search(window):
                    continue
                found.add(skill_id)
                break
        return found

    def match_sections(self, sections):
        """sections: [(bucket, text)] -> {(skill_id, bucket)}"""
        out = set()
        for bucket, text in sections or []:
            for skill_id in self.match(text):
                out.add((skill_id, bucket))
        return out

    def unmatched_tokens(self, sections):
        """Capitalized tokens that no alias claimed. Input to the review queue."""
        counts = Counter()
        for _bucket, text in sections or []:
            if not text:
                continue
            # Lowercase sentence-initial words so 'Experience' and 'Build'
            # do not drown the queue.
            flat = SENTENCE_START_RE.sub(
                lambda m: m.group(1) + m.group(2).lower(), text
            )
            for tok in TOKEN_RE.findall(flat):
                low = tok.lower()
                if low in self._known or low in self._noise:
                    continue
                if len(tok) < 2 or tok.isdigit():
                    continue
                counts[tok] += 1
        return counts


def load_matcher(conn, include_company_names=True):
    rows = conn.execute(
        """
        SELECT a.alias, s.id, s.canonical_name, s.guard, s.deny
        FROM skill_aliases a JOIN skills s ON s.id = a.skill_id
        """
    ).fetchall()
    names = ()
    if include_company_names:
        names = [r[0] for r in conn.execute("SELECT name FROM companies")]
    return SkillMatcher(rows, names)