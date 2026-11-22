import math
import re
from datetime import date, datetime, timezone

DAY_MS = 86400000

_ISO = re.compile(r"^(?:([+-]\d{6})|(\d{4}))(?:-(\d{2})(?:-(\d{2}))?)?$")


def _days_from_civil(y, m, d):
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


_JS_LIMIT_MS = 8.64e15


def _js_text(value):
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool):
        return "true"
    if isinstance(value, (int, float)):
        if value == 0 or value != value:
            return None
        if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return str(value) if isinstance(value, int) else "x"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join("" if v is None else (_js_text(v) or str(v).lower()) for v in value)
    return "[object Object]"


def expiry_ms(value):
    value = _js_text(value)
    if value is None:
        return None
    m = _ISO.match(value)
    if not m:
        return None
    signed, plain, month, day = m.groups()
    if signed is not None:
        if signed == "-000000":
            return None
        year = int(signed)
    else:
        year = int(plain)
    month = int(month) if month else 1
    day = int(day) if day else 1
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
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
    return int(today)


def _js_round(x):
    return int(math.floor(x + 0.5))


def days_left(cert, today=None):
    expires = cert.get("expires") if isinstance(cert, dict) else None
    at = expiry_ms(expires)
    if at is None:
        return None
    return _js_round((at - _now_ms(today)) / DAY_MS)


def nearest_for_place(certs, place_id, today=None):
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


def nearest_by_place(certs, today=None):
    groups = {}
    for cert in certs or []:
        if isinstance(cert, dict) and isinstance(cert.get("place"), str) and cert["place"]:
            groups.setdefault(cert["place"], []).append(cert)
    return {place: nearest_for_place(group, place, today) for place, group in groups.items()}
