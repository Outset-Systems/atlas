"""THE SEALS on the server: how many days a certificate has left.

The SEALS scene works this out in the browser (`static/js/seals.js`,
`daysUntil`). The places table, and what reads it later, need the same number
on the server, so this is a port of that rule, not a second opinion. A test
(`tests/test_certs.py`) runs the browser's own function under node on the same
cases, so the two cannot drift apart.

The rule, exactly as the browser has it:

  * `expires` is read as `<expires>T00:00:00Z`, by the strict ISO form of
    JavaScript's `Date.parse`: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, or a six-digit
    signed year. A month runs 01 to 12 and a day 01 to 31 in any month; a day
    past the month's end rolls into the next (`2026-02-30` is 2 March). A value
    that is not text is first turned into text the way the browser does it
    (`2026` is 1 January 2026). Anything else, and a blank, has no date.
  * Days left is `Math.round((expiry - now) / one day)`: measured from this
    instant, not from midnight, and a half rounds up. Negative means lapsed.
"""

import math
import re
from datetime import date, datetime, timezone

DAY_MS = 86400000

_ISO = re.compile(r"^(?:([+-]\d{6})|(\d{4}))(?:-(\d{2})(?:-(\d{2}))?)?$")


def _days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic Gregorian date, any year (Hinnant)."""
    y -= m <= 2
    era = y // 400                         # floor division: Python's // already rounds down
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


#: The furthest a JavaScript date reaches either side of 1970, in milliseconds.
_JS_LIMIT_MS = 8.64e15


def _js_text(value):
    """`${value}` for what JSON can hold, or None where the browser's `!iso`
    stops first (null, false, 0, the empty string)."""
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool):
        return "true"
    if isinstance(value, (int, float)):
        if value == 0 or value != value:           # 0 and NaN are falsy too
            return None
        if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return str(value) if isinstance(value, int) else "x"   # no other number parses
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join("" if v is None else (_js_text(v) or str(v).lower()) for v in value)
    return "[object Object]"


def expiry_ms(value):
    """Milliseconds since the epoch at which `value` lapses, or None. The
    browser's `Date.parse(`${value}T00:00:00Z`)`."""
    value = _js_text(value)
    if value is None:
        return None
    m = _ISO.match(value)
    if not m:
        return None
    signed, plain, month, day = m.groups()
    if signed is not None:
        if signed == "-000000":           # the one spelling the standard forbids
            return None
        year = int(signed)
    else:
        year = int(plain)
    month = int(month) if month else 1
    day = int(day) if day else 1
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    # day 1 of the month, then the days after it: that is how 31 April rolls on
    at = (_days_from_civil(year, month, 1) + day - 1) * DAY_MS
    return at if abs(at) <= _JS_LIMIT_MS else None


def _now_ms(today):
    if today is None:
        today = datetime.now(timezone.utc)
    if isinstance(today, datetime):
        if today.tzinfo is None:
            today = today.replace(tzinfo=timezone.utc)
        delta = today - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    if isinstance(today, date):
        return _days_from_civil(today.year, today.month, today.day) * DAY_MS
    return int(today)                     # already milliseconds


def _js_round(x):
    """`Math.round`: the nearest whole number, a half going up."""
    return int(math.floor(x + 0.5))


def days_left(cert, today=None):
    """Whole days until `cert` lapses, negative once it has, None with no date.

    `today` is the instant to measure from: an aware datetime (a naive one is
    UTC), a date (its midnight, UTC), or milliseconds. Left out, now. Pass a
    datetime to agree with the browser to the day: it measures from now."""
    expires = cert.get("expires") if isinstance(cert, dict) else None
    at = expiry_ms(expires)
    if at is None:
        return None
    return _js_round((at - _now_ms(today)) / DAY_MS)


def nearest_for_place(certs, place_id, today=None):
    """The certificate tied to `place_id` (its `place`) that lapses first, as
    `{"name", "days", "expires"}`, or None when no certificate names it.

    A lapsed one comes first, since it is the most urgent. One with no date
    comes after every dated one, and is still given: the place has a
    certificate, and the table can say its date is not charted. Certificates
    that name the place only in words (`host`) are not guessed at."""
    best = best_key = None
    for cert in certs or []:
        if not isinstance(cert, dict) or not place_id or cert.get("place") != place_id:
            continue
        days = days_left(cert, today)
        key = (days is None, days if days is not None else 0)
        if best is None or key < best_key:
            best, best_key = {"name": cert.get("name"), "days": days,
                              "expires": cert.get("expires")}, key
    return best
