"""TOPOLOGY's connections sheet: `GET /api/v2/topology/connections.csv` (2026-11-17).

One row per place, and per stub that has a cable, as the TOPOLOGY view's
spreadsheet has them (`topology.connections`, the twin of the client's
`connections`): the device, what it is connected to, its port, the far port,
the cable's VLANs, its PoE in watts, and the names from it up to the head of
the network. Blank where it hangs by no cable: never a guess from a route.

Built from the dataset as `/lab-data` gives it to this viewer (the overlays,
then `redact_for_groups`), so a place the viewer may not see is in no column:
not as a row, not as what a row is connected to, not inside another row's
path. Its cables went with it in the redaction, and the graph is built
afresh from what is left.

A spreadsheet runs a cell that starts with `=`, `+`, `-`, `@`, a tab or a
carriage return as a formula, so such a cell is written with a `'` before it.
UTF-8 with a byte-order mark, so a spreadsheet reads the names right; CRLF
lines; `attachment` with a dated file name; `no-store`, as every per-viewer
answer.

Who may ask: any signed-in viewer, for what that viewer may see. It is the
page's, as the check routes are: an API token is not looked at here (it is
not in `api_tokens.READ_PATHS`), so a request with only a token is refused as
one with no session. A tool reads the same rows from `/lab-data` through
`topology.py`.
"""

import csv
import io
import logging
import re
import time
import unicodedata

from flask import Response, jsonify

import topology
from context import atlas
from redaction import no_store, redact_for_groups

from . import bp

log = logging.getLogger("atlas.api.v2")

CONNECTIONS_PATH = "/topology/connections.csv"

#: The sheet's columns, in order, and the row field each is read from.
COLUMNS = (("Device", "name"), ("Connected to", "to"), ("Port", "port"), ("Far port", "farPort"),
           ("VLAN", "vlan"), ("PoE (W)", "poe"), ("Path to the head", "path"))

#: What a spreadsheet would read as the start of a formula.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """A cell as text, with a `'` before it when a spreadsheet would run it."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def slug(text):
    """A map's title as a file name's first part, as the client's
    topology-export-model.js `slug`: lower-case ASCII letters and digits,
    every other run one hyphen, at most 40, 'atlas' when nothing is left."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].rstrip("-")
    return s or "atlas"


def file_name(title, day=None):
    """'<map>-connections-<YYYY-MM-DD>.csv', the day the server's own."""
    return f"{slug(title)}-connections-{day or time.strftime('%Y-%m-%d', time.localtime())}.csv"


def rows(data):
    """The sheet's rows from a dataset that is already this viewer's."""
    return topology.connections(topology.build_graph(data))


def csv_text(table):
    """The sheet as text: the header, then a line per row (the byte-order mark
    is the encoding's: `utf-8-sig`)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([head for head, _ in COLUMNS])
    for row in table:
        writer.writerow([safe_cell(row.get(field, "")) for _, field in COLUMNS])
    return out.getvalue()


@bp.route(CONNECTIONS_PATH)
def topology_connections_csv():
    ctx = atlas()
    try:
        raw, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 topology connections: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500
    data, _ = ctx.with_overlays(raw)
    data = redact_for_groups(data)[0]
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    resp = Response(csv_text(rows(data)).encode("utf-8-sig"), mimetype="text/csv")
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{file_name(meta.get("title"))}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return no_store(resp)
