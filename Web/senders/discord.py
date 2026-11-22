import re

from . import shape as guard
from .common import SECRET_FIELD, url_field

kind = "discord"
label = "Discord"
fields = (
    {**url_field("https://discord.com/api/webhooks/123456789012345678"),
     "hint": "alerts_discord_url_hint",
     "hint_text": ("The webhook's address up to its id. The operator lists "
                   "discord.com:443 in ATLAS_ALERT_HOSTS first.")},
    {**SECRET_FIELD, "required": True, "placeholder": "DISCORD_LAB",
     "hint": "alerts_discord_secret_hint",
     "hint_text": ("The token, the part of the webhook's address after the id: "
                   "the server reads it from ATLAS_ALERT_SECRET_<NAME> or its _FILE; "
                   "Atlas never stores it.")},
)
secret_use = {"in": "path"}

HOSTS = ("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com")
CONTENT_MAX = 2000
SUPPRESS_EMBEDS = 1 << 2
EMPTY = "Atlas alert"

_PATH = re.compile(r"^/api/webhooks/([0-9]{1,25})/?$")
_WITH_TOKEN = re.compile(r"^/api/webhooks/[0-9]{1,25}/[^/]+/?$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def check_address(scheme, host, port, path):
    problems = []
    if scheme != "https":
        problems.append("A Discord address starts with https://.")
    if host not in HOSTS:
        problems.append("A Discord address is on discord.com, discordapp.com, "
                        "canary.discord.com or ptb.discord.com.")
    elif port != 443:
        problems.append("A Discord address uses port 443.")
    if _WITH_TOKEN.match(path):
        problems.append("A Discord address stops at the webhook's id: the token after "
                        "it goes in a named secret, never in the address.")
    elif not _PATH.match(path):
        problems.append("A Discord address is https://discord.com/api/webhooks/ and "
                        "the webhook's id, in digits.")
    return problems


def secret_path(path, secret):
    if not (isinstance(path, str) and _PATH.match(path)
            and isinstance(secret, str) and _TOKEN.match(secret)):
        return None
    return f"{path.rstrip('/')}/{secret}"


def _units(text):
    return len(text.encode("utf-16-le")) // 2


def content(title, body, link):
    text = title or ""
    if body:
        text = f"{text}\n\n{body}" if text else body
    if link:
        text = f"{text}\n{link}" if text else link
    return text or EMPTY


def fitted(title, body, link):
    if _units(content(title, body, link)) <= CONTENT_MAX:
        return body, link
    if link and _units(content(title, "…", link)) > CONTENT_MAX:
        link = None
        if _units(content(title, body, None)) <= CONTENT_MAX:
            return body, None
    lo, hi = 0, len(body)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _units(content(title, body[:mid] + "…", link)) <= CONTENT_MAX:
            lo = mid
        else:
            hi = mid - 1
    return body[:lo] + "…", link


def build(message, secret=None):
    m = guard.prepared(message)
    headers = guard.base_headers("application/json")
    body, link = fitted(m.title, m.body, m.link)

    def doc(text):
        return {"content": content(m.title, text, link),
                "allowed_mentions": {"parse": []}, "flags": SUPPRESS_EMBEDS}
    return headers, guard.json_body(doc, body)
