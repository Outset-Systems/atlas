from . import shape as guard
from .common import SECRET_FIELD, add_secret, url_field

kind = "webhook"
label = "A JSON webhook"
fields = (url_field("https://hooks.example/atlas"), SECRET_FIELD)
secret_use = {"in": "header", "header": "Authorization", "prefix": "Bearer "}


def build(message, secret=None):
    m = guard.prepared(message)
    headers = guard.base_headers("application/json")
    add_secret(headers, secret_use, secret)

    def doc(text):
        return {"title": m.title, "body": text, "priority": "high" if m.high else "default",
                "link": m.link, "tags": m.tags, "source": "atlas"}
    return headers, guard.json_body(doc, m.body)
