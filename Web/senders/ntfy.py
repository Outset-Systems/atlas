"""ntfy: the message as plain text, its title, priority, tags and link in
headers, the secret as a bearer token (2026-11-16)."""

from .common import SECRET_FIELD, add_secret, url_field

kind = "ntfy"
label = "ntfy"
fields = (url_field("https://ntfy.example/lab-alerts"), SECRET_FIELD)
secret_use = {"in": "header", "header": "Authorization", "prefix": "Bearer "}


def check_path(path):
    """An ntfy address names its topic."""
    if path.strip("/") == "":
        return ["An ntfy address names its topic, as https://ntfy.example/atlas."]
    return []


def build(message, secret=None):
    """`(headers, body_bytes)`. The guard cleans the message and cuts the body."""
    import alert_send as guard          # at call time: alert_send imports this package
    m = guard.prepared(message)
    headers = guard.base_headers("text/plain; charset=utf-8")
    if m.title:
        headers["Title"] = guard.header_text(m.title)
    headers["Priority"] = "5" if m.high else "3"
    if m.tags:
        headers["Tags"] = ",".join(m.tags)
    if m.link:
        headers["Click"] = m.link
    add_secret(headers, secret_use, secret)
    return headers, guard.plain_body(m.body)
