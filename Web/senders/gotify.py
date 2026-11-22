from . import shape as guard
from .common import SECRET_FIELD, add_secret, url_field

kind = "gotify"
label = "Gotify"
fields = (url_field("https://gotify.example"), SECRET_FIELD)
secret_use = {"in": "header", "header": "X-Gotify-Key", "prefix": ""}
rewrites_url = True


def check_path(path):
    bare = path.rstrip("/")
    if bare and not bare.endswith("/message"):
        return ["A Gotify address is the server itself or ends in /message."]
    return []


def send_path(path):
    bare = path.rstrip("/")
    return bare if bare.endswith("/message") else "/message"


def build(message, secret=None):
    m = guard.prepared(message)
    headers = guard.base_headers("application/json")
    add_secret(headers, secret_use, secret)

    def doc(text):
        out = {"title": m.title, "message": text, "priority": 8 if m.high else 5}
        if m.link:
            out["extras"] = {"client::notification": {"click": {"url": m.link}}}
        return out
    return headers, guard.json_body(doc, m.body)
