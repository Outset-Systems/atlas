"""THE API REFERENCE — an OpenAPI document for what a token can read.

It covers `api_tokens.READ_PATHS` and the MCP endpoint, and nothing else. The
rest of `/api/v2` is the page's own API: it changes with the page and is not a
contract. `tests/test_openapi.py` holds the two halves together, so a path a
token may call cannot go undocumented and the document cannot advertise a door
a token cannot open.

Written by hand, as a dict, so the Atlas gains no dependency. The dataset's
shape is not written here at all: it is generated from `schema.py`'s catalogue,
which stays the one definition of what the dataset is.

`docs/openapi.json` is this document on disk, for a reader who has no Atlas
running. Rewrite it after a change here:

    python Web/openapi.py
"""

import json
import os

import api_tokens
import mcp_tools
import schema

#: The contract's own version, apart from the app's. It moves when a documented
#: path, parameter or field changes, so the file on disk does not churn with
#: every release.
CONTRACT = "2.5.0"

OPENAPI_PATH = "/api/v2/openapi.json"

#: Catalogue field type -> JSON Schema. Every type the catalogue uses must be
#: here; a test fails on a new one rather than letting it fall through as "any".
_STRING = {"type": "string"}
TYPE_MAP = {
    "text": _STRING, "longtext": _STRING, "slug": _STRING, "ref": _STRING,
    "ip": _STRING, "cidr": _STRING, "color": _STRING, "path": _STRING,
    "url": _STRING, "link": _STRING, "date": _STRING, "datetime": _STRING,
    "select": _STRING,
    "bool": {"type": "boolean"},
    "int": {"type": "integer"},
    "number": {"type": "number"},
    "percent": {"type": "number"},
    "scalar": {"type": ["string", "number", "boolean"]},
    "strings": {"type": "array", "items": {"type": "string"}},
    "json": {},
    "objects": None,     # built from the field's own `of`
    "object": None,
}

#: What `redact_for_groups` takes out for every token, wholesale. Leaving these
#: in the document would describe fields no token is ever sent.
HIDDEN_SECTIONS = frozenset({"stones"})
HIDDEN_FIELDS = {"nodes": frozenset({"accounts"})}

_ANY_OBJECT = {"type": "object", "additionalProperties": True}

_WHEN = {"type": "string", "description": "UTC, as `2026-11-09T21:14:03Z`."}
#: What the server stamps on an entry and no editor form shows (`provenance.py`),
#: so the catalogue does not list it.
STAMPED = {"nodes": {"provenance": {
    "type": "object", "additionalProperties": True,
    "description": ("When this place was charted and whether a person has checked it. "
                    "Written by the server at each change. Absent on a place charted "
                    "before the map kept it: treat that as unknown. The names (who) are "
                    "kept too and are not sent to a token."),
    "properties": {
        "charted_at": _WHEN,
        "source": {"type": "string", "examples": ["hand", "survey", "unifi"],
                   "description": "`hand`, or the import that wrote it."},
        "changed_at": _WHEN,
        "reviewed": {"type": "boolean",
                     "description": "False until a person saves the place by hand."},
        "reviewed_at": _WHEN,
        "changed_since_review": {
            "type": "boolean",
            "description": ("Present and true when the place has changed since a person "
                            "reviewed it, most often because an import added to it. "
                            "`reviewed` stays true; what changed is unconfirmed until the "
                            "next review.")},
    }}}}


def _field(fld):
    kind = fld["type"]
    if kind == "objects":
        out = {"type": "array", "items": _entry(fld.get("of") or [])}
    elif kind == "object":
        out = _entry(fld.get("of") or [])
    else:
        out = dict(TYPE_MAP[kind])
    words = fld.get("help") or ""
    if fld.get("options"):
        # not `enum`: a hand-edited dataset is served even when a value is off
        # the list, and a strict client would then refuse the whole reply
        out["examples"] = [o for o in fld["options"] if o != ""]
    if fld.get("ref"):
        words = (words + f" Names an entry in `{fld['ref']}`.").strip()
    if words:
        out["description"] = words
    return out


def _entry(fields, hidden=frozenset()):
    return {"type": "object", "additionalProperties": True,
            "properties": {f["name"]: _field(f) for f in fields if f["name"] not in hidden}}


def dataset_schema():
    """The dataset as a token is sent it, generated from the catalogue."""
    props = {}
    for key in schema.FILE_ORDER:
        if key in HIDDEN_SECTIONS:
            continue
        if key == "signals":
            props[key] = _entry(schema.SIGNAL_FIELDS)
            props[key]["description"] = "Which monitor watches which place. Not the live feed."
            continue
        sec = schema.get(key)
        entry = _entry(sec["fields"], HIDDEN_FIELDS.get(key, frozenset()))
        entry["properties"].update(STAMPED.get(key, {}))
        if sec["kind"] == "object":
            props[key] = entry
        else:
            props[key] = {"type": "array", "items": entry}
        props[key]["description"] = f"The {sec['plural']}."
    return {
        "type": "object", "additionalProperties": True, "properties": props,
        "description": ("The whole map. No field is promised present: a hand-edited "
                        "dataset is served as it is, and keys the catalogue does not "
                        "know are kept. Places a token may not see are removed, with "
                        "everything that names them."),
    }


def _json(ref, description):
    return {"description": description,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}}


def _refusals(*extra):
    out = {"401": {"$ref": "#/components/responses/Unauthorized"},
           "403": {"$ref": "#/components/responses/Off"},
           "429": {"$ref": "#/components/responses/TooMany"}}
    for status in extra:
        out[status] = {"$ref": "#/components/responses/Unreadable"}
    return out


def _get(op_id, summary, description, ok, parameters=None, extra=()):
    op = {"operationId": op_id, "summary": summary, "description": description,
          "responses": {"200": ok, **_refusals(*extra)}}
    if parameters:
        op["parameters"] = parameters
    return {"get": op}


_STATE = {"type": "string",
          "examples": ["healthy", "degraded", "down", "slumbering", "maintenance"]}
_BY_ID = {"type": "object", "additionalProperties": {
    "type": "object", "additionalProperties": True, "properties": {"state": _STATE}}}


def _roster_schema():
    """The places table, one row per place (`api/v2/roster.py`)."""
    text = {"type": ["string", "null"]}
    ids = {"type": "array", "items": {"type": "string"}}
    row = {
        "id": {"type": "string"},
        "name": text,
        "state": {"type": ["string", "null"], "examples": list(_STATE["examples"]),
                  "description": "The live state. Null is unknown, not healthy."},
        "cause": {**text, "description": "The place whose fault explains this one's, when one does."},
        "zone": text,
        "zone_name": text,
        "kind": {**text, "examples": list(schema.NODE_KINDS)},
        "role": text,
        "addresses": {**ids, "description": ("The place's `ip` and `mac`, then `ipv6`, `hostname` "
                                              "and `fqdn` when present. Only those with a value.")},
        "services": {"type": "integer", "description": "How many services the place lists."},
        "confirmed_by": {**text, "description": "The source whose answer gave the place its state."},
        "charted_source": {**text, "description": "`hand`, or the import that wrote the place."},
        "reviewed": {"type": ["boolean", "null"],
                     "description": "Null for a place charted before the map kept provenance."},
        "reviewed_at": {**text, "description": "UTC."},
        "reviewed_by": {**text, "description": "Who reviewed it. Sent to an admin only."},
        "changed_since_review": {"type": "boolean"},
        "unchecked": {"type": "boolean",
                      "description": ("Never reviewed, or reviewed and changed by an import since. "
                                      "False for a place charted before the map kept provenance.")},
        "maintenance": {"type": "object", "properties": {
            "now": {"type": "boolean", "description": "Under repair now."},
            "next": {**text, "description": "When the next window that names it opens, UTC."}}},
        "cert": {"type": ["object", "null"], "description": (
            "The certificate tied to this place (its `place`) that lapses first. `days` is whole "
            "days left, negative once lapsed, null when its date is not charted."),
            "properties": {"name": text, "days": {"type": ["integer", "null"]}, "expires": text}},
        "sets": {**ids, "description": "The sets this place is in."},
        "depends_on": {**ids, "description": "Places this one cannot work without."},
    }
    return {"type": "object", "properties": {
        "stamp": {**text, "description": "The dataset's version, as an editor sends it back."},
        "generated_at": {"type": "string", "description": "When this answer was made, UTC."},
        "zones": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": text}}},
        "sets": {"type": "array", "description": "Named lists of places. Not access.",
                 "items": {"type": "object", "properties": {
                     "id": {"type": "string"}, "name": text, "note": text, "places": ids}}},
        "rows": {"type": "array", "description": "One per place.",
                 "items": {"type": "object", "additionalProperties": True, "properties": row}},
    }}


def _overview_schema():
    """OVERVIEW's tiles (`api/v2/overview.py`, built in `overview.py`)."""
    text = {"type": ["string", "null"]}
    count = {"type": "integer"}
    ref = {"type": "object", "properties": {"id": {"type": "string"}, "name": text}}
    refs = {"type": "array", "items": ref}
    return {"type": "object", "properties": {
        "generated_at": {"type": "string", "description": "When this answer was made, UTC."},
        "admin": {"type": "boolean", "description": "Whether the reader sees everything. Never true for a token."},
        "states": {"type": "object", "description": (
            "The reader's places by live state. `unknown` is a place with no state, not a healthy one."),
            "properties": {k: count for k in ("healthy", "degraded", "down", "slumbering",
                                              "maintenance", "unknown", "total")}},
        "down": {"type": "array", "description": (
            "Places down or degraded on their own account, down first, then by name. A place "
            "whose fault another visible place explains is that place's fallout and is not listed."),
            "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "name": text,
                "state": {"type": "string", "examples": ["down", "degraded"]},
                "cause": {**text, "description": "Always null here: a place with a visible cause is not a root."},
                "downstream": {**refs, "description": (
                    "Every visible place that needs this one, directly or through another, from "
                    "`parent` and `depends_on` only.")},
                "declared": {"type": "boolean", "description": (
                    "Whether any visible place declares that it needs this one. False means nothing "
                    "is declared to depend on it, not that nothing is affected.")}}}},
        "unacked": {"type": "object", "description": "Events nobody has acknowledged, of any gravity.",
                    "properties": {
                        "count": count,
                        "items": {"type": "array", "description": "Newest first, at most 8.",
                                  "items": {"type": "object", "properties": {
                                      "id": {"type": "integer"}, "at": {"type": "string"},
                                      "kind": {"type": "string"}, "target": {"type": "string"},
                                      "name": text, "from": text, "to": text}}}}},
        "maintenance": {"type": "array", "description": (
            "Repair windows open now or opening within 7 days, soonest first, with the reader's "
            "places in each. A window that names only places the reader may not see is not listed."),
            "items": {"type": "object", "properties": {
                "window": text, "reason": text,
                "starts": {**text, "description": "This occurrence's start, UTC."},
                "ends": {**text, "description": "This occurrence's end, UTC. Null when it has none."},
                "now": {"type": "boolean", "description": "Open now."},
                "places": refs}}},
        "certs": {"type": "array", "description": (
            "Certificates with 30 days or fewer left, lapsed ones included, soonest first."),
            "items": {"type": "object", "properties": {
                "name": text, "place": {"type": ["object", "null"], "properties": ref["properties"]},
                "days": {"type": "integer", "description": "Whole days left, negative once lapsed."},
                "expires": text}}},
        "review": {"type": "object", "properties": {
            "unchecked": {**count, "description": "Places an import wrote or changed that no person has checked since."},
            "stale": {**count, "description": "Places with no review, or none in 90 days."},
            "items": {"type": "array", "description": "Never reviewed first, then the oldest review; at most 8.",
                      "items": {"type": "object", "properties": {
                          "id": {"type": "string"}, "name": text, "reviewed_at": text}}}}},
        "changes": {"type": "object", "description": (
            "For an admin, the last 8 entries in the change log. For anyone else, a token "
            "included, how many of their places changed in 7 days, with no names."),
            "properties": {
                "items": {"type": "array", "items": {"type": "object", "properties": {
                    "at": text, "by": text, "summary": text}}},
                "count_7d": count}},
        "sources": {"type": "object", "properties": {
            "all_ok": {"type": "boolean", "description": "No source was silent on the last build."},
            "silent": count,
            "items": {"type": "array", "description": "Each source, for an admin. Empty for anyone else.",
                      "items": {"type": "object", "properties": {
                          "name": {"type": "string"}, "ok": {"type": "boolean"},
                          "last_ok": {**text, "description": "When it last answered, UTC."}}}}}},
        "drift": {"type": "object", "description": "Monitors the map has not charted. Sent to an admin only.",
                  "properties": {"count": count, "items": {"type": "array", "items": {"type": "string"}}}},
    }}


def _schemas():
    return {
        "Dataset": dataset_schema(),
        "Maps": {"type": "object", "properties": {"maps": {"type": "array", "items": {
            "type": "object", "additionalProperties": True, "properties": {
                "name": {"type": "string", "description": "The image's file name."},
                "label": {"type": "string"},
                "url": {"type": "string", "description": "Where the image is served."},
                "default": {"type": "boolean", "description": "The map's own picture."},
                "zoom": {"type": "boolean", "description": "Art a region zooms into, not a backdrop."},
                "bright": {"type": "boolean"},
                "theme": {"type": ["object", "null"], "additionalProperties": True},
                "regions": {"type": "array", "items": _ANY_OBJECT},
                "places": {**_ANY_OBJECT, "description": "Where this picture seats each place, by id."},
                "zones": _ANY_OBJECT,
                "logos": _ANY_OBJECT,
                "words": _ANY_OBJECT,
                "tripwire": {"type": "string"},
            }}}}},
        "Signals": {
            "type": "object", "additionalProperties": True,
            "description": ("Live health, merged from every source this Atlas is pointed "
                            "at. A place or service with no entry is unknown, not healthy."),
            "properties": {
                "generated": {"type": "number", "description": "When the feed was built, epoch seconds."},
                "cached": {"type": "boolean", "description": "Served from the 30 second cache."},
                "sources": {"type": "object", "additionalProperties": {"type": "string"},
                            "description": "Each source by name: `ok`, or `silent` when it did not answer."},
                "sources_at": {"type": "object", "additionalProperties": {"type": ["string", "null"]},
                               "description": ("Each source by name: when it last answered, UTC, or null "
                                               "if it has not since the server started.")},
                "nodes": {**_BY_ID, "description": "Places by id."},
                "services": {**_BY_ID, "description": "Services by monitor name."},
                "rites": {**_BY_ID, "description": "Scheduled jobs that are late, missed or failed, by key."},
                "causes": {**_ANY_OBJECT, "description": "For a place that is down because another is: which one."},
                "confirmed_by": {"type": "object", "additionalProperties": {"type": "string"},
                                 "description": ("Places by id: the source whose answer gave the place "
                                                 "its state in this feed. Absent for a place under "
                                                 "repair, whose state comes from the window.")},
                "maintenance": {"type": "array", "items": _ANY_OBJECT},
                "repairs": _ANY_OBJECT,
                "metrics": _ANY_OBJECT,
                "drift": _ANY_OBJECT,
            }},
        "Rites": {"type": "object", "properties": {"rites": {"type": "array", "items": {
            "type": "object", "additionalProperties": True,
            "description": "A scheduled job as charted, with what actually happened to it.",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "host": {"type": "string"},
                "cadence": {"type": "string", "examples": list(schema.RITE_CADENCES)},
                "when": {"type": "string"},
                "verdict": {"type": "string",
                            "examples": ["kept", "late", "missed", "failed", "awaited", "unwatched"],
                            "description": ("`awaited`: watched, never reported. "
                                            "`unwatched`: no interval is expected of it.")},
                "expect_every": {"type": ["number", "null"], "description": "Seconds."},
                "grace": {"type": ["number", "null"], "description": "Seconds."},
                "age_s": {"type": "number", "description": "Seconds since it last reported."},
                "last": {**_ANY_OBJECT, "description": ("The last report: `at`, `status`, `duration_s`. What the job "
                                                        "wrote about its run and the address it posted "
                                                        "from are not sent to a token.")},
                "runs": {"type": "array", "items": _ANY_OBJECT},
            }}}}},
        "Events": {"type": "object", "properties": {
            "events": {"type": "array", "description": "Newest first.", "items": {
                "type": "object", "additionalProperties": True, "properties": {
                    "id": {"type": "integer"},
                    "at": {"type": "string", "description": "When it was first observed, UTC."},
                    "kind": {"type": "string", "description": "What changed state: a place, a service, a job."},
                    "target": {"type": "string"},
                    "name": {"type": "string"},
                    "from": {"type": ["string", "null"]},
                    "to": {"type": "string"},
                    "gravity": {"type": "string",
                                "examples": ["grave", "warn", "planned", "clear", "consequence"]},
                    "cause": {"type": "string", "description": "Present when another fault explains this one."},
                    "outlived": {"type": "boolean", "description": (
                        "Present and true on a place still down after the fault that "
                        "explained it has cleared: its own outage starts here, so `from` "
                        "and `to` are both `down`. It names no cause.")},
                    "ack": {"type": ["object", "null"], "additionalProperties": True,
                            "description": ("`at`: when it was acknowledged; null if it was not. "
                                            "Who, and what they wrote, are for admins.")},
                }}},
            "counts": {"type": "object", "properties": {
                "total": {"type": "integer"}, "unacked": {"type": "integer"},
                "last_24h": {"type": "integer"}}},
        }},
        "Roster": _roster_schema(),
        "Overview": _overview_schema(),
        "Refusal": {"type": "object", "properties": {
            "error": {"type": "string"}, "reason": {"type": "string"}}},
        "Unreadable": {"type": "object", "properties": {"error": {"type": "string"}}},
        "RpcRequest": {"type": "object", "required": ["jsonrpc", "method"], "properties": {
            "jsonrpc": {"const": "2.0"},
            "id": {"type": ["string", "integer"]},
            "method": {"type": "string",
                       "examples": ["initialize", "ping", "tools/list", "tools/call"]},
            "params": _ANY_OBJECT}},
        "RpcReply": {"type": "object", "properties": {
            "jsonrpc": {"const": "2.0"},
            "id": {"type": ["string", "integer", "null"]},
            "result": _ANY_OBJECT,
            "error": {"type": "object", "properties": {
                "code": {"type": "integer"}, "message": {"type": "string"}}}}},
    }


def _paths():
    paths = {
        "/api/v2/lab-data": _get(
            "getDataset", "The whole map",
            "Places, zones, routes, addresses, racks, certificates and scheduled jobs, in one "
            "document. Send `If-None-Match` with the last `ETag` to get a 304 when nothing changed.",
            {**_json("Dataset", "The dataset."), "headers": {
                "ETag": {"schema": {"type": "string"}},
                "X-Atlas-Data-Problems": {
                    "schema": {"type": "string"},
                    "description": "How many problems the dataset's own check found. Absent when none."}}},
            extra=("500",)),
        "/api/v2/maps": _get(
            "listMaps", "The pictures the map can be drawn on",
            "Each image, with where it seats the places a token may see.",
            _json("Maps", "The pictures.")),
        "/api/v2/signals": _get(
            "getSignals", "Live health",
            "Never fails: a source that does not answer is listed as `silent` and its "
            "places have no entry. Reading it can record a state change in the event history.",
            _json("Signals", "The feed.")),
        "/api/v2/rites": _get(
            "listScheduledJobs", "Scheduled jobs and whether they ran",
            "Every charted job with its verdict.",
            _json("Rites", "The jobs."), extra=("500",)),
        "/api/v2/events": _get(
            "listEvents", "The event history",
            "State changes, newest first. Tripwire events are never sent to a token.",
            _json("Events", "The events."),
            parameters=[
                {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 100},
                 "description": "How many to return. The history keeps 2,000."},
                {"name": "unacked", "in": "query", "schema": {"type": "string", "enum": ["1"]},
                 "description": "`1` returns only events nobody has acknowledged."}]),
        "/api/v2/places/roster": _get(
            "getPlacesTable", "Every place, one row each",
            "The places this reader may see, each with its live state, network, addresses, "
            "review, repair windows, nearest certificate and sets. Made from the map and the "
            "live health, cut the same way as those two.",
            _json("Roster", "The table."), extra=("500",)),
        "/api/v2/overview": _get(
            "getOverview", "The realm at a glance",
            "Places by state, what is down and what depends on it, events nobody has "
            "acknowledged, repair windows in the next 7 days, certificates lapsing within 30, "
            "places unchecked or not reviewed in 90, how many places changed this week and "
            "whether every source answered. Made from the map and the live health, cut the "
            "same way as those two.",
            _json("Overview", "The tiles."), extra=("500",)),
        OPENAPI_PATH: _get(
            "getReference", "This document",
            "The same document as `docs/openapi.json` in the repository.",
            {"description": "OpenAPI 3.1.", "content": {"application/json": {"schema": _ANY_OBJECT}}}),
    }
    paths["/api/v2/lab-data"]["get"]["responses"]["304"] = {"description": "Unchanged since the `ETag` sent."}
    tools = ", ".join(f"`{t['name']}`" for t in mcp_tools.TOOLS)
    paths[api_tokens.MCP_PATH] = {"post": {
        "operationId": "mcp", "summary": "The MCP endpoint",
        "description": ("Model Context Protocol over HTTP: JSON-RPC, tools only, read-only, "
                        "no session and no stream. An MCP client speaks this for you; the "
                        f"tools are {tools}. A token is the only credential it takes."),
        "x-mcp-tools": [t["name"] for t in mcp_tools.TOOLS],
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/RpcRequest"}}}},
        "responses": {"200": _json("RpcReply", "A JSON-RPC reply. A tool's failure is a reply, not a status."),
                      "202": {"description": "A notification was accepted. No body."},
                      "404": {"$ref": "#/components/responses/Off"},
                      **_refusals()},
    }}
    return paths


def document():
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Atlas API",
            "version": CONTRACT,
            "description": (
                "What an API token can read from an Atlas. Tokens are issued in Settings, "
                "Connections, by an admin, once agent access is turned on there. A token is "
                "read-only, sees no more than a signed-in viewer with no groups, and reaches "
                "only the paths in this document. A URL reaches it without `user:pass@` or "
                "its query string. While agent access is off every path here answers 403 to "
                "a token and the MCP endpoint answers 404. A token made for a cloud AI tool "
                "reads a reduced view through the MCP endpoint only, and every other path "
                "here answers it 403. "
                "The rest of `/api/v2` belongs to the page and is not a contract."),
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "servers": [{"url": "/", "description": "This Atlas."}],
        "security": [{"token": []}],
        "paths": _paths(),
        "components": {
            "securitySchemes": {"token": {
                "type": "http", "scheme": "bearer",
                "description": "`Authorization: Bearer atl_...`"}},
            "schemas": _schemas(),
            "responses": {
                "Unauthorized": _json("Refusal", "No token, or one that is not valid or has expired."),
                "Off": _json("Refusal", "Agent access is turned off on this Atlas, the token tried "
                                        "something other than a read, or it is a cloud token "
                                        "asking for a path other than the MCP endpoint."),
                "TooMany": {**_json("Refusal", f"More than {api_tokens.RATE_PER_MINUTE} requests in a "
                                               "minute on this token."),
                            "headers": {"Retry-After": {"schema": {"type": "string"}}}},
                "Unreadable": _json("Unreadable", "The dataset on disk could not be read."),
            },
        },
    }


def dumps():
    return json.dumps(document(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "docs", "openapi.json")
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps())
    print(f"wrote {target}")
