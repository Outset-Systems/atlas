import base64
import json
import logging

from flask import Response, jsonify, request

import api_tokens
import mcp_tools
import settings
import token_log

from . import bp

log = logging.getLogger("atlas.api.v2.mcp")

MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER = "io.modelcontextprotocol/serverInfo"
MAX_BODY = 64 * 1024

PARSE_ERROR, INVALID_REQUEST, NOT_FOUND, BAD_PARAMS = -32700, -32600, -32601, -32602
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022


def _rpc(msg_id, result=None, error=None, status=200):
    body = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _err(msg_id, code, message, status=200, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return _rpc(msg_id, error=error, status=status)


def _server():
    return {"name": "atlas", "title": settings.APP_BRAND, "version": settings.APP_VERSION}


def _modern(result):
    return {**result, "resultType": "complete", "_meta": {META_SERVER: _server()}}


def _same_host():
    origin = request.headers.get("Origin")
    if not origin:
        return True
    return origin.rstrip("/").split("://", 1)[-1] == request.host


def _decode(value):
    if value and value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    return value


def _mismatch(msg, params, version):
    if request.headers.get("MCP-Protocol-Version") != version:
        return "MCP-Protocol-Version does not match the request body"
    if request.headers.get("Mcp-Method") != msg.get("method"):
        return "Mcp-Method does not match the request body"
    if msg.get("method") == "tools/call" and _decode(request.headers.get("Mcp-Name")) != params.get("name"):
        return "Mcp-Name does not match the request body"
    return None


def _tools_list():
    return {"tools": mcp_tools.TOOLS}


def _tools_call(msg_id, params, wrap):
    name = params.get("name")
    token_log.note(tool=name if isinstance(name, str) else None, args=params.get("arguments"))
    if not mcp_tools.known(name):
        return _err(msg_id, BAD_PARAMS, f"Unknown tool: {name}")
    try:
        text, value = mcp_tools.call(name, params.get("arguments") or {})
    except mcp_tools.ToolError as e:
        return _rpc(msg_id, wrap({"content": [{"type": "text", "text": str(e)}], "isError": True}))
    except Exception as e:
        log.warning("mcp: %s failed: %s: %s", name, e.__class__.__name__, e)
        return _rpc(msg_id, wrap({"content": [{"type": "text", "text": "The map could not be read."}],
                                  "isError": True}))
    result = {"content": [{"type": "text", "text": text}], "isError": False}
    if value is not None:
        result["structuredContent"] = value
    log.info("mcp: %s called %s", api_tokens.current()["name"], name)
    return _rpc(msg_id, wrap(result))


def _discover():
    return {"supportedVersions": list(MODERN + LEGACY), "capabilities": {"tools": {}},
            "instructions": mcp_tools.instructions(), "ttlMs": 300000, "cacheScope": "private"}


def _serve_modern(msg, params, version):
    msg_id, method = msg.get("id"), msg.get("method")
    if version not in MODERN:
        return _err(msg_id, UNSUPPORTED_VERSION, "Unsupported protocol version", status=400,
                    data={"supported": list(MODERN + LEGACY), "requested": version})
    problem = _mismatch(msg, params, version)
    if problem:
        return _err(msg_id, HEADER_MISMATCH, problem, status=400)
    if method == "server/discover":
        return _rpc(msg_id, _modern(_discover()))
    if method == "tools/list":
        return _rpc(msg_id, _modern({**_tools_list(), "ttlMs": 300000, "cacheScope": "private"}))
    if method == "tools/call":
        return _tools_call(msg_id, params, _modern)
    return _err(msg_id, NOT_FOUND, "Method not found", status=404)


def _serve_legacy(msg, params):
    msg_id, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        return _rpc(msg_id, {"protocolVersion": asked if asked in LEGACY else LEGACY[0],
                             "capabilities": {"tools": {}}, "serverInfo": _server(),
                             "instructions": mcp_tools.instructions()})
    header = request.headers.get("MCP-Protocol-Version")
    if header and header not in LEGACY:
        return _err(msg_id, INVALID_REQUEST, "Unsupported protocol version", status=400,
                    data={"supported": list(MODERN + LEGACY), "requested": header})
    if method == "ping":
        return _rpc(msg_id, {})
    if method == "server/discover":
        return _rpc(msg_id, _discover())
    if method == "tools/list":
        return _rpc(msg_id, _tools_list())
    if method == "tools/call":
        return _tools_call(msg_id, params, lambda r: r)
    return _err(msg_id, NOT_FOUND, "Method not found")


@bp.route("/mcp", methods=["POST"])
def mcp_post():
    if not _same_host():
        return _err(None, INVALID_REQUEST, "Origin not allowed", status=403)
    if (request.content_length or 0) > MAX_BODY:
        return _err(None, INVALID_REQUEST, "Request too large", status=413)
    raw = request.stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        return _err(None, INVALID_REQUEST, "Request too large", status=413)
    msg = None
    if request.is_json:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            msg = None
    if not isinstance(msg, dict):
        return _err(None, PARSE_ERROR, "Expected one JSON-RPC message", status=400)
    if "id" not in msg:
        return Response(status=202)
    if not isinstance(msg.get("method"), str):
        return _err(msg.get("id"), INVALID_REQUEST, "No method", status=400)
    token_log.note(method=msg["method"])
    params = msg.get("params")
    params = params if isinstance(params, dict) else {}
    meta = params.get("_meta")
    version = meta.get(META_VERSION) if isinstance(meta, dict) else None
    if version is not None:
        return _serve_modern(msg, params, version)
    return _serve_legacy(msg, params)


@bp.route("/mcp", methods=["GET", "DELETE"])
def mcp_no_stream():
    return Response(status=405, headers={"Allow": "POST"})
