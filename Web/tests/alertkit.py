"""Shared by the ALERTS suites (2026-11-13): a realm with alerts switched on, a
sender that captures instead of sending, and a tick driven by hand.

No test here sends anything anywhere: `alert_send.send` is replaced by
`Capture`, which records the destination and the message and answers
"delivered". The rest of the sender (the allow-list check, secret binding,
the delivery log) is the real one.
"""

import json

import viewers

HOST = "ntfy.example:443"
DEST = {"id": "pager", "name": "Pager", "kind": "ntfy",
        "url": "https://ntfy.example/atlas", "secret": None}
PUBLIC = "https://atlas.example/"


def switch(tmp_path, monkeypatch, on=True, hosts=HOST, public_url=PUBLIC):
    """The alert settings, pointed into `tmp_path`. Applied by the next fresh_app."""
    monkeypatch.setenv("ATLAS_ALERTS", "1" if on else "")
    monkeypatch.setenv("ATLAS_ALERT_HOSTS", hosts)
    monkeypatch.setenv("ATLAS_PUBLIC_URL", public_url)
    monkeypatch.setenv("ATLAS_ALERTS_FILE", str(tmp_path / "alerts.json"))
    monkeypatch.setenv("ATLAS_ALERTS_STATE", str(tmp_path / "alerts-state.json"))
    monkeypatch.setenv("ATLAS_ALERT_LOG", str(tmp_path / "alert-deliveries.jsonl"))
    monkeypatch.setenv("ATLAS_ANNALS_POLL", "60")


def build(tmp_path, monkeypatch, data, on=True, windows=None, **kw):
    switch(tmp_path, monkeypatch, on=on, **kw)
    return viewers.build(tmp_path, monkeypatch, data, windows)


class Capture:
    """Stands in for `alert_send.send`."""

    def __init__(self, outcome="delivered"):
        self.sent = []
        self.outcome = outcome

    def __call__(self, dest, message, *, resolver=None, transport=None):
        self.sent.append((dict(dest), dict(message)))
        return {"outcome": self.outcome, "status": 200 if self.outcome == "delivered" else None,
                "why": None}

    @property
    def titles(self):
        return [m["title"] for _, m in self.sent]

    def everything(self):
        """Every byte the sender was handed, as one text."""
        return json.dumps([{"dest": d, "message": m} for d, m in self.sent])


def capture(monkeypatch, outcome="delivered"):
    import alert_send
    c = Capture(outcome)
    monkeypatch.setattr(alert_send, "send", c)
    return c


def rule(rid, kind, tid, to=("down",), minutes=0, dest="pager", name="", note="", enabled=True):
    return {"id": rid, "name": name, "note": note, "enabled": enabled,
            "target": {"kind": kind, "id": tid}, "to": list(to),
            "for_minutes": minutes, "destination": dest}


def store(rules=(), digest=None, dests=(DEST,)):
    """Write the alerts document straight to its store (the routes test the save)."""
    import alerts
    doc = {"rules": list(rules), "destinations": [dict(d) for d in dests],
           "digest": {**alerts.DIGEST_DEFAULTS, **(digest or {})}}
    alerts.save(doc)
    return doc


def dataset(handle):
    data, _, _ = handle.app.extensions["atlas"].dataset()
    return data


def feed_for(data, states, under=()):
    """A raw feed as `build_feed` would leave it: maintenance first, then the
    dependency fold."""
    import dependencies
    feed = {"nodes": {k: {"state": v} for k, v in states.items()}}
    for nid in under:
        feed["nodes"][nid] = {**feed["nodes"].get(nid, {}), "state": "maintenance"}
    feed["maintenance"] = sorted(under)
    dependencies.apply_to(data, feed)
    return feed


class Ticker:
    """One poll by hand: record the annals, then tick at `now`."""

    def __init__(self, handle):
        self.handle = handle

    def step(self, states, now, under=(), extra=None):
        import alerts
        import events
        with self.handle.app.app_context():
            data = dataset(self.handle)
            feed = feed_for(data, states, under)
            if extra:
                feed.update(extra)
            names = {n.get("id"): n.get("name") for n in data.get("nodes") or []
                     if isinstance(n, dict)}
            events.record(feed, lambda kind, target: names.get(target) or target)
            return alerts.tick(feed, data, now=now)


def log_lines(tmp_path):
    path = tmp_path / "alert-deliveries.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
