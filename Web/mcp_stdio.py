"""MCP over stdio — `python cli.py mcp`, for a client that cannot send a header.

    docker exec -i atlas python cli.py mcp --token-file /data/agent.token

This is a pipe to the HTTP endpoint and nothing more. Each line on stdin is one
JSON-RPC message; it is posted to `/api/v2/mcp` inside this process, with the
token, and the reply is written back as one line. So there is one MCP server,
not two: the token gate, the viewer's eyes, the rate limit and the log line are
the ones `api_tokens.py` and `api/v2/mcp.py` already apply.

A token is still required. Being able to run a command in the container is not
the same as being allowed to read the map as anyone: the token decides what this
reader sees, and revoking it stops this reader.
"""

import json
import re
import sys

import api_tokens

META_VERSION = "io.modelcontextprotocol/protocolVersion"
MAX_LINE = 64 * 1024
PARSE_ERROR, INVALID_REQUEST, UNAUTHORIZED = -32700, -32600, -32001
#: What may be mirrored into a header: no control characters, nothing long.
_PLAIN = re.compile(r"^[\x20-\x7e]{1,200}$")


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _headers(msg, token):
    """The headers a 2026-07-28 client mirrors from the body, built from the body,
    since a pipe has none of its own."""
    head = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    version = meta.get(META_VERSION)
    plain = lambda v: isinstance(v, str) and bool(_PLAIN.match(v))   # noqa: E731
    if plain(version):
        head["MCP-Protocol-Version"] = version
        if plain(msg.get("method")):
            head["Mcp-Method"] = msg["method"]
        if msg.get("method") == "tools/call" and plain(params.get("name")):
            head["Mcp-Name"] = params["name"]
    return head


def answer(client, token, line):
    """One line in, one reply out (a dict), or None when there is nothing to say."""
    if len(line) > MAX_LINE:
        return _error(None, INVALID_REQUEST, "Request too large")
    try:
        msg = json.loads(line)
    except ValueError:
        return _error(None, PARSE_ERROR, "Expected one JSON-RPC message per line")
    if not isinstance(msg, dict):
        return _error(None, PARSE_ERROR, "Expected one JSON-RPC message per line")
    try:
        resp = client.post(api_tokens.MCP_PATH, data=json.dumps(msg), headers=_headers(msg, token))
    except Exception as e:      # noqa: BLE001 — one bad message must not end the conversation
        print(f"mcp stdio: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None if "id" not in msg else _error(msg.get("id"), INVALID_REQUEST,
                                                    "That message could not be sent on.")
    if "id" not in msg:
        return None
    body = resp.get_json(silent=True)
    if isinstance(body, dict) and body.get("jsonrpc") == "2.0":
        return body
    # the gate's own refusals are plain JSON, not JSON-RPC: say them in the caller's terms
    # (404 is the gate too: agent access is off, and the reason says so)
    reason = (body or {}).get("reason") if isinstance(body, dict) else None
    return _error(msg.get("id"), UNAUTHORIZED if resp.status_code in (401, 403, 404, 429) else INVALID_REQUEST,
                  reason or f"The Atlas answered {resp.status_code}")


def serve(client, token, lines, out):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        reply = answer(client, token, line)
        if reply is not None:
            out.write(json.dumps(reply) + "\n")       # ASCII: whatever the console's encoding
            out.flush()


def main(token):
    if not _PLAIN.match(token or "") or not token.startswith(api_tokens.PREFIX):
        print("error: pass --token-file with an API token in it (Settings, Connections), "
              "or set ATLAS_TOKEN.", file=sys.stderr)
        return 2
    import app as atlas_app
    # stdout is the protocol: nothing else may print there
    serve(atlas_app.app.test_client(), token, sys.stdin, sys.stdout)
    return 0
