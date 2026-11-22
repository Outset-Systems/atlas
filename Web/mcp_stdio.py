import json
import re
import sys

import api_tokens

META_VERSION = "io.modelcontextprotocol/protocolVersion"
MAX_LINE = 64 * 1024
PARSE_ERROR, INVALID_REQUEST, UNAUTHORIZED = -32700, -32600, -32001
_PLAIN = re.compile(r"^[\x20-\x7e]{1,200}$")


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _headers(msg, token):
    head = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    version = meta.get(META_VERSION)
    plain = lambda v: isinstance(v, str) and bool(_PLAIN.match(v))
    if plain(version):
        head["MCP-Protocol-Version"] = version
        if plain(msg.get("method")):
            head["Mcp-Method"] = msg["method"]
        if msg.get("method") == "tools/call" and plain(params.get("name")):
            head["Mcp-Name"] = params["name"]
    return head


def answer(client, token, line):
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
    except Exception as e:
        print(f"mcp stdio: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None if "id" not in msg else _error(msg.get("id"), INVALID_REQUEST,
                                                    "That message could not be sent on.")
    if "id" not in msg:
        return None
    body = resp.get_json(silent=True)
    if isinstance(body, dict) and body.get("jsonrpc") == "2.0":
        return body
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
            out.write(json.dumps(reply) + "\n")
            out.flush()


def main(token):
    if not _PLAIN.match(token or "") or not token.startswith(api_tokens.PREFIX):
        print("error: pass --token-file with an API token in it (Settings, Connections), "
              "or set ATLAS_TOKEN.", file=sys.stderr)
        return 2
    import app as atlas_app
    serve(atlas_app.app.test_client(), token, sys.stdin, sys.stdout)
    return 0
