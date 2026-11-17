"""What the kinds of destination share: the two fields the store keeps, and the
one way a secret is put in a header (2026-11-16).

A kind's `fields` describe what Settings › Alerts asks for after a
destination's name and kind, in order. Each is a dict:

  name         the key the destination is stored under: `url` or `secret`,
               the only two the alerts store keeps (`alerts.normalize`)
  type         `url`, `secret-name`, `text` or `select`
  required     whether the page asks for it before it posts
  label        the theme key of its label; `text` is the plain words, used
               when no theme has the key
  hint, hint_text   an optional line under it, the same way
  placeholder  what the empty box shows
  options      for `select`: [[value, plain words], ...]

`secret_use` says how a kind sends the secret a destination names:
`{"in": "header", "header": ..., "prefix": ...}`, `{"in": "path"}`, or
`{"in": "none"}` for a kind that takes none. A secret is never in a query
string or a user name: the guard refuses an address that carries either.
`"path"` (2026-11-16) is for a service that keeps its key in the path, as
Discord does: the stored address stops before the key, and the kind's
`secret_path(path, secret)` adds it at send time only, so it is never in the
alerts file, a route's answer or the delivery log. Such a kind must have a
secret: the guard blocks a destination that names none.
"""

#: The keys a destination is stored under, besides id, name and kind.
STORED = ("url", "secret")
#: What a field can be.
TYPES = ("url", "secret-name", "text", "select")
#: Where a secret can go.
SECRET_IN = ("header", "path", "none")


def url_field(placeholder):
    """The address, which every kind has: the guard is built around it."""
    return {"name": "url", "type": "url", "required": True,
            "label": "alerts_f_url", "text": "Address", "placeholder": placeholder}


#: The secret's NAME (the server reads ATLAS_ALERT_SECRET_<NAME>), never its value.
SECRET_FIELD = {
    "name": "secret", "type": "secret-name", "required": False,
    "label": "alerts_f_secret", "text": "Secret's name",
    "hint": "alerts_secret_hint",
    "hint_text": ("The server reads ATLAS_ALERT_SECRET_<NAME> or its _FILE; "
                  "Atlas never stores the secret."),
    "placeholder": "NTFY_LAB",
}


def add_secret(headers, use, secret):
    """Put `secret` into `headers` the way `use` says, when there is one."""
    if secret and use.get("in") == "header":
        headers[use["header"]] = f"{use.get('prefix', '')}{secret}"
    return headers
