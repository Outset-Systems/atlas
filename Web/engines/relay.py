from engines.base import _Adapter, _coerce_feed, log

RELAY_MAX_AGE = 300.0


def _as_utc(dt):
    from datetime import timezone as _tz
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)


def _latest_relay(site_slug):
    from datetime import datetime, timezone as _tz

    from sqlalchemy import select

    from store import session_scope
    from store.models import SignalSnapshot, Site

    with session_scope() as session:
        site = session.scalar(select(Site).where(Site.slug == site_slug))
        if site is None:
            return None, None
        row = session.scalar(
            select(SignalSnapshot)
            .where(SignalSnapshot.site_id == site.id)
            .order_by(SignalSnapshot.received_at.desc(), SignalSnapshot.id.desc())
            .limit(1)
        )
        if row is None:
            return None, None
        age = (datetime.now(_tz.utc) - _as_utc(row.received_at)).total_seconds()
        return row.payload_json, age


def relay_age_seconds(site_slug):
    try:
        _, age = _latest_relay(site_slug)
        return age
    except Exception as e:
        log.warning("relay age unavailable: %s", e)
        return None


class RelayAdapter(_Adapter):

    name = "relay"

    def __init__(self, site_slug):
        self.site_slug = site_slug
        self.max_age = RELAY_MAX_AGE

    def _fetch(self):
        payload, age = _latest_relay(self.site_slug)
        if payload is None or age is None:
            return {}
        if age > self.max_age:
            log.warning("relay feed for %s is %.0fs old (>%.0fs) — treating as silent",
                        self.site_slug, age, self.max_age)
            return {}
        return _coerce_feed(payload)
