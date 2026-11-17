"""Gotify: a JSON message posted to the server's /message, the secret in
X-Gotify-Key (2026-11-16)."""

from .common import SECRET_FIELD, add_secret, url_field

kind = "gotify"
label = "Gotify"
fields = (url_field("https://gotify.example"), SECRET_FIELD)
secret_use = {"in": "header", "header": "X-Gotify-Key", "prefix": ""}
#: The address is saved the way it is sent: ending in /message.
rewrites_url = True


def check_path(path):
    """A Gotify address is the server itself, or ends in /message."""
    bare = path.rstrip("/")
    if bare and not bare.endswith("/message"):
        return ["A Gotify address is the server itself or ends in /message."]
    return []


def send_path(path):
    """The path posted to: the address's own /message, else /message."""
    bare = path.rstrip("/")
    return bare if bare.endswith("/message") else "/message"


def build(message, secret=None):
    """`(headers, body_bytes)`. The guard cleans the message and fits the JSON."""
    import alert_send as guard          # at call time: alert_send imports this package
    m = guard.prepared(message)
    headers = guard.base_headers("application/json")
    add_secret(headers, secret_use, secret)

    def doc(text):
        out = {"title": m.title, "message": text, "priority": 8 if m.high else 5}
        if m.link:
            out["extras"] = {"client::notification": {"click": {"url": m.link}}}
        return out
    return headers, guard.json_body(doc, m.body)
