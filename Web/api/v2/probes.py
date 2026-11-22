import logging
import re

from flask import current_app, jsonify, make_response, request

import atlas_auth
import embeddable
import settings
import whois
from context import atlas
from ingest import _RateLimiter
from redaction import redact_for_groups

from . import bp

log = logging.getLogger("atlas.api.v2")

WHOIS_PER_MINUTE = 20
whois_limiter = _RateLimiter(limit=WHOIS_PER_MINUTE, window=60.0)


@bp.route("/embeddable")
def embeddable_verdict():
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

    frame_list = current_app.extensions.get("atlas_frame_list")
    dropped = frame_list()[1] if frame_list else frozenset()
    if embeddable.origin_of(url) in dropped:
        out = embeddable.unlisted(url)
    else:
        out = embeddable.verdict(url, self_origin=request.host_url.rstrip("/"),
                                 enabled=settings.embed_probe())
    resp = make_response(jsonify(out))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/whois")
def whois_lookup():
    if not settings.whois_enabled():
        return jsonify({"error": "whois is switched off on this Atlas"}), 403
    q = (request.args.get("q") or "").strip().lower().rstrip(".")
    if (not q or len(q) > 253 or q.startswith("-")
            or not re.match(r"^[a-z0-9._:-]+$", q)
            or not re.search(r"[a-z0-9]", q)):
        return jsonify({"error": "ask about a domain or an IP address"}), 400
    if not whois_limiter.hit(atlas_auth.client_ip()):
        resp = jsonify({"error": "too many questions, try again in a minute"})
        resp.headers["Retry-After"] = "60"
        return resp, 429

    servers, texts, dead, error = whois.follow(q)
    if dead:
        if error is None:
            log.warning("whois: cannot follow %s for %r", dead, q)
        else:
            log.warning("whois: %s would not answer for %r: %s", dead, q, error)
        return jsonify({"error": f"{dead} would not answer"}), 502

    resp = make_response(jsonify({
        "query": q,
        "servers": servers,
        "text": "\n\n".join(texts),
    }))
    resp.headers["Cache-Control"] = "no-store"
    return resp
