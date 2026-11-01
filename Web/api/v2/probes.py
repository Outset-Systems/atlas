"""Outbound probes — `GET /api/v2/embeddable`, `GET /api/v2/whois`.

Both are viewer-gated reads whose bodies carry no dataset content, so nothing
here is modelled. The engines live in their own modules:

* `embeddable.py` — the framing verdict and its cache.
* `whois.py` — THE NAMING DEEP's socket, hop cap and the SSRF vetting every
  referral must pass (moved there whole at the v1 removal, v1.41.0; until then
  it lived inside the v1 route module and was imported through it). It is
  called through the module, not from-imported, so a monkeypatch in the tests
  lands on the call this route makes.
"""

import logging
import re

from flask import jsonify, make_response, request

import atlas_auth
import embeddable
import settings
import whois
from context import atlas
from ingest import _RateLimiter
from redaction import redact_for_groups

from . import bp

log = logging.getLogger("atlas.api.v2")

#: Questions one client may ask a minute. A person reads the answers; anything
#: faster is using this host as a relay. The socket engine stays stdlib only,
#: so the limit lives with the route.
WHOIS_PER_MINUTE = 20
whois_limiter = _RateLimiter(limit=WHOIS_PER_MINUTE, window=60.0)


@bp.route("/embeddable")
def embeddable_verdict():
    """Will this service render inside the map, or must it open in a tab?

    A browser cannot answer this for itself: a page refused by
    `X-Frame-Options` paints nothing and fires no event a cross-origin parent
    can read, so the only honest way to know before you try is to ask the
    service. This does, once, and caches the answer (see `embeddable.py`).

    **The URL must already be in the dataset.** Not a formality: this endpoint
    makes an outbound request from inside the lab on behalf of whoever calls
    it, and without that check it would be an open fetcher wearing the Atlas's
    network position. The dataset is admin-written and the map already links to
    every URL in it, so the answer set is exactly "the buttons that exist" —
    for THIS viewer: a `require_group` place's buttons are not on their map,
    so probing one on their behalf would confirm the address is charted.
    """
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "no url given"}), 400
    ctx = atlas()
    try:
        data, stamp, _ = ctx.dataset()
    except (OSError, ValueError):
        return jsonify({"error": "dataset unreadable"}), 500
    data, group_key = redact_for_groups(data)
    if url not in embeddable.charted(data, (stamp, group_key)):
        log.warning("refused an embeddable probe for an uncharted url: %s", url[:120])
        return jsonify({"error": "that address is not on this map"}), 400

    out = embeddable.verdict(url, self_origin=request.host_url.rstrip("/"),
                             enabled=settings.embed_probe())
    resp = make_response(jsonify(out))
    # The verdict is already cached server-side for its own TTL; letting the
    # browser cache it too would outlive a service turning framing back on.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/whois")
def whois_lookup():
    """Whois for a domain or an address, with the referral chain followed.

    The abyss panel (index.html → static/js/whois.js) asks "who holds this
    name"; a browser cannot speak port 43, so this route speaks it on the
    viewer's behalf. It rides the same auth gate as the map.

    Never partial-fails loudly: if IANA answered and the registry it pointed
    at did not, the caller gets what was learned plus a note, because half a
    whois answer is still an answer. Only a name nobody would speak to at all
    is an error.
    """
    if not settings.whois_enabled():
        return jsonify({"error": "whois is switched off on this Atlas"}), 403
    q = (request.args.get("q") or "").strip().lower().rstrip(".")
    # hostname/IP characters only (":" for IPv6) — this string goes onto a
    # socket to servers we chose, and it should never be able to smuggle a
    # second query line or an option flag
    if (not q or len(q) > 253 or q.startswith("-")
            or not re.match(r"^[a-z0-9._:-]+$", q)
            or not re.search(r"[a-z0-9]", q)):
        return jsonify({"error": "ask about a domain or an IP address"}), 400
    if not whois_limiter.hit(atlas_auth.client_ip()):
        resp = jsonify({"error": "too many questions, try again in a minute"})
        resp.headers["Retry-After"] = "60"
        return resp, 429

    servers, texts = [], []
    server, seen = whois.ROOT, set()
    for _ in range(whois.MAX_HOPS):
        if not server or server in seen:
            break
        seen.add(server)
        # Vetted per hop, the root included: one path, so a mistake here cannot
        # be a mistake that only some hops make.
        targets = whois.endpoint(server)
        if targets is None:
            # Deliberately the SAME sentence for "does not resolve" and
            # "resolves somewhere private". The referral is written by whoever
            # answered the last hop, so telling them apart would answer
            # "does this internal name exist?" for a caller who is not
            # supposed to be able to ask. The engine's log line says which.
            if not texts:
                log.warning("whois: cannot follow %s for %r", server, q)
                return jsonify({"error": f"{server} would not answer"}), 502
            texts.append(f"% {server} is not a public whois server — "
                         "the chain ends here.")
            break
        try:
            answer = whois.ask(targets, q)
        except OSError as e:
            if not texts:
                log.warning("whois: %s would not answer for %r: %s", server, q, e)
                return jsonify({"error": f"{server} would not answer"}), 502
            texts.append(f"% {server} would not answer — the chain ends here.")
            break
        servers.append(server)
        texts.append(f"% ── {server} ──\n{answer.strip()}")
        server = whois.referral(answer)

    resp = make_response(jsonify({
        "query": q,
        "servers": servers,
        "text": "\n\n".join(texts),
    }))
    # registrations change on their own clock; asking again should really ask
    resp.headers["Cache-Control"] = "no-store"
    return resp
