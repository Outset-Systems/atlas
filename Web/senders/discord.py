"""Discord: an incoming webhook, its token held as the destination's secret
(2026-11-16).

A Discord webhook's address is `https://discord.com/api/webhooks/<id>/<token>`,
and the token is the key: whoever has it can post to the channel. So the
address Atlas keeps stops at the id, and the token is the secret the
destination names (`ATLAS_ALERT_SECRET_<NAME>` or its `_FILE`), put back on
the end of the path only when a message is sent (`secret_path`). The token is
then never in the alerts file, in what a route returns, on the page or in the
delivery log, and it is sent only to the origin it was named for, as every
secret is.

Discord's query options are not taken: the guard refuses any address with a
query string, so neither `?thread_id=` nor `?wait=true` can be saved.

The body is `{"content": ...}`: the title, a blank line, the body, then the
link on its own line, cut to Discord's 2000 characters (counted in UTF-16
units, which is never fewer than Discord counts), the body cut first and
ending in "…" the way the guard cuts. `allowed_mentions` is empty, so an
alert that says @everyone or names a role pings nobody, and `flags` asks
Discord for no embed, so it does not fetch the link to draw a preview.
"""

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

#: The hosts Discord serves its webhooks from. The operator still lists the
#: one used in ATLAS_ALERT_HOSTS, as discord.com:443; this list only narrows.
HOSTS = ("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com")
#: Discord's own limit on a message's content.
CONTENT_MAX = 2000
#: Message flag SUPPRESS_EMBEDS: no preview drawn from the link.
SUPPRESS_EMBEDS = 1 << 2
#: What is sent when a message has no words at all (Discord refuses empty content).
EMPTY = "Atlas alert"

_PATH = re.compile(r"^/api/webhooks/([0-9]{1,25})/?$")
_WITH_TOKEN = re.compile(r"^/api/webhooks/[0-9]{1,25}/[^/]+/?$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def check_address(scheme, host, port, path):
    """A Discord address is https, on one of Discord's hosts, port 443, and
    stops at the webhook's id. Never quotes the address: a sentence here can
    reach the delivery log."""
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
    """The path posted to: the id's path and the token. None when either is
    not the shape Discord gives, so the guard blocks the send."""
    if not (isinstance(path, str) and _PATH.match(path)
            and isinstance(secret, str) and _TOKEN.match(secret)):
        return None
    return f"{path.rstrip('/')}/{secret}"


def _units(text):
    """`text`'s length in UTF-16 units: a character outside the BMP is two."""
    return len(text.encode("utf-16-le")) // 2


def content(title, body, link):
    """The title, a blank line, the body, then the link on its own line; any
    part that is empty is left out with its gap."""
    text = title or ""
    if body:
        text = f"{text}\n\n{body}" if text else body
    if link:
        text = f"{text}\n{link}" if text else link
    return text or EMPTY


def fitted(title, body, link):
    """`(body, link)` so that `content` is at most CONTENT_MAX units: the
    body cut, ending in "…", as the guard cuts; the link left out only when
    even an empty body leaves it no room (a link can be 2000 characters)."""
    if _units(content(title, body, link)) <= CONTENT_MAX:
        return body, link
    if link and _units(content(title, "…", link)) > CONTENT_MAX:
        link = None
        if _units(content(title, body, None)) <= CONTENT_MAX:
            return body, None
    lo, hi = 0, len(body)
    while lo < hi:                       # the longest prefix that fits
        mid = (lo + hi + 1) // 2
        if _units(content(title, body[:mid] + "…", link)) <= CONTENT_MAX:
            lo = mid
        else:
            hi = mid - 1
    return body[:lo] + "…", link


def build(message, secret=None):
    """`(headers, body_bytes)`. The guard cleans the message and fits the
    JSON to its 4 KB; this cuts the content to Discord's 2000 first. The
    secret is not in the body or a header: it is the end of the path."""
    m = guard.prepared(message)
    headers = guard.base_headers("application/json")
    body, link = fitted(m.title, m.body, m.link)

    def doc(text):
        return {"content": content(m.title, text, link),
                "allowed_mentions": {"parse": []}, "flags": SUPPRESS_EMBEDS}
    return headers, guard.json_body(doc, body)
