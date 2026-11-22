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

COLUMNS = (("Device", "name"), ("Connected to", "to"), ("Port", "port"), ("Far port", "farPort"),
           ("VLAN", "vlan"), ("PoE (W)", "poe"), ("Path to the head", "path"))

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def slug(text):
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].rstrip("-")
    return s or "atlas"


def file_name(title, day=None):
    return f"{slug(title)}-connections-{day or time.strftime('%Y-%m-%d', time.localtime())}.csv"


def rows(data):
    return topology.connections(topology.build_graph(data))


def csv_text(table):
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
