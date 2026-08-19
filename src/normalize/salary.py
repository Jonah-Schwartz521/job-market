"""Extract posted salary ranges from description text.

No ATS in use exposes a reliable compensation field, so every number here
comes from regex over the body. Pay transparency law in CO, CA, NY, WA and
IL is what puts the ranges there in the first place.

WIDEST BAND RULE. A posting may carry several ranges (Stripe posts one for
SF/NYC and another for everywhere else). We store min(all mins) and
max(all maxes) in the single column pair. The stored figure is therefore a
CEILING ON SPREAD, not a point estimate, and must be labelled that way
wherever it is charted.

Rejects market-size figures ("$4.3 trillion healthcare system") and any
value outside a plausible compensation band.
"""

import re

CURRENCIES = {
    "$": "USD", "us$": "USD", "usd": "USD",
    "£": "GBP", "gbp": "GBP",
    "€": "EUR", "eur": "EUR",
    "c$": "CAD", "cad": "CAD",
    "a$": "AUD", "aud": "AUD",
    "sek": "SEK", "kr": "SEK",
    "kes": "KES", "ksh": "KES",
    "₹": "INR", "inr": "INR",
    "r$": "BRL", "brl": "BRL",
}

# Plausible bounds per period. Anything outside is not compensation.
BOUNDS = {
    "year":  (10_000, 2_000_000),
    "month": (1_000, 200_000),
    "week":  (200, 40_000),
    "day":   (50, 10_000),
    "hour":  (10, 1_000),
}

_SYM = r"(?:US\$|C\$|A\$|R\$|\$|£|€|₹|USD|GBP|EUR|CAD|AUD|SEK|KES|KSh|INR|BRL)"
_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
_DASH = r"\s*(?:-|--|\u2013|\u2014|to)\s*"

# $150,000 - $200,000   |   $150K—$200K   |   £85,000 to £95,000
RANGE_RE = re.compile(
    rf"(?P<c1>{_SYM})\s?(?P<n1>{_NUM})\s?(?P<k1>[KkMm])?"
    rf"{_DASH}"
    rf"(?:(?P<c2>{_SYM})\s?)?(?P<n2>{_NUM})\s?(?P<k2>[KkMm])?",
    re.I,
)

# up to $200,000  |  starting at $150K  |  base salary of $180,000
SINGLE_RE = re.compile(
    rf"(?:up to|starting at|from|base salary of|salary of|at least|minimum of)\s*"
    rf"(?P<c1>{_SYM})\s?(?P<n1>{_NUM})\s?(?P<k1>[KkMm])?",
    re.I,
)

# Trailing scale words mean this is a market size, not a paycheck.
SCALE_TRAP_RE = re.compile(r"^\s*(?:trillion|billion|million|bn|tn)\b", re.I)

PERIOD_HINTS = (
    ("hour",  r"per hour|/\s*hour|hourly|an hour|/\s*hr\b|per hr\b"),
    ("day",   r"per day|/\s*day|daily|a day"),
    ("week",  r"per week|/\s*week|weekly|a week"),
    ("month", r"per month|/\s*month|monthly|a month|/\s*mo\b"),
    ("year",  r"per year|/\s*year|annually|annualized|per annum|a year|/\s*yr\b|annual"),
)
PERIOD_RES = [(p, re.compile(r, re.I)) for p, r in PERIOD_HINTS]

WINDOW = 60


def _currency(token):
    if not token:
        return None
    return CURRENCIES.get(token.strip().lower())


def _value(num, suffix):
    v = float(num.replace(",", ""))
    if suffix:
        v *= 1_000 if suffix.lower() == "k" else 1_000_000
    return v


def _period(text, at):
    """Look just after the match for a period hint, then just before."""
    after = text[at:at + WINDOW]
    before = text[max(0, at - WINDOW):at]
    for period, rx in PERIOD_RES:
        if rx.search(after):
            return period
    for period, rx in PERIOD_RES:
        if rx.search(before):
            return period
    return None


def _plausible(lo, hi, period):
    floor, ceil = BOUNDS[period]
    return floor <= lo <= ceil and floor <= hi <= ceil and lo <= hi


def find_all(text):
    """Every plausible (min, max, currency, period) in the text."""
    if not text:
        return []

    hits = []

    for m in RANGE_RE.finditer(text):
        if SCALE_TRAP_RE.match(text[m.end():m.end() + 14]):
            continue
        currency = _currency(m.group("c1")) or _currency(m.group("c2"))
        lo = _value(m.group("n1"), m.group("k1"))
        hi = _value(m.group("n2"), m.group("k2"))

        # "$150K - 200K": the suffix on the first number carries over.
        if m.group("k1") and not m.group("k2") and hi < lo:
            hi = _value(m.group("n2"), m.group("k1"))

        period = _period(text, m.end())
        if period is None:
            period = "hour" if hi <= 1_000 else "year"
        if _plausible(lo, hi, period):
            hits.append((lo, hi, currency, period))

    if not hits:
        for m in SINGLE_RE.finditer(text):
            if SCALE_TRAP_RE.match(text[m.end():m.end() + 14]):
                continue
            v = _value(m.group("n1"), m.group("k1"))
            period = _period(text, m.end()) or ("hour" if v <= 1_000 else "year")
            if _plausible(v, v, period):
                hits.append((v, v, _currency(m.group("c1")), period))

    return hits


def extract(text):
    """Widest band across every range found. Returns a dict of salary fields."""
    empty = {
        "salary_min": None, "salary_max": None, "salary_currency": None,
        "salary_period": None, "salary_source": "none",
    }
    hits = find_all(text)
    if not hits:
        return empty

    # Mixing periods in one posting is rare and ambiguous; trust the most
    # common one and drop the rest rather than averaging incomparable figures.
    periods = [h[3] for h in hits]
    period = max(set(periods), key=periods.count)
    same = [h for h in hits if h[3] == period]

    currencies = [h[2] for h in same if h[2]]
    return {
        "salary_min": min(h[0] for h in same),
        "salary_max": max(h[1] for h in same),
        "salary_currency": currencies[0] if currencies else None,
        "salary_period": period,
        "salary_source": "regex",
    }