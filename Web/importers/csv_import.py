"""CSV importer — the "here's my device list" path.

    name,ip,kind,zone,role,url,url_label,notes

Only `name` is required. The whole file is parsed and validated before
anything is written: a typo on row 40 must not leave rows 1-39 imported. Every
problem is reported with its line number, the way a spreadsheet user needs.

Unlike NetBox (an authoritative inventory that can legitimately say a device is
gone), a CSV is usually a partial list, so import is additive by default —
nodes absent from the file are left alone unless `--retire-missing` says the
file is the whole truth.
"""

import csv
import io
import ipaddress
from datetime import datetime, timezone

from sqlalchemy import select

from store.labdata import get_site
from store.layout import auto_layout
from store.models import Node, NodeLink, Site, Zone

from .common import (
    UNKNOWN_ZONE_FIELDS, ensure_uncharted, slugify, subnet_index, zone_for_ip,
)

KNOWN_HEADERS = ("name", "ip", "kind", "zone", "role", "url", "url_label", "notes")
REQUIRED_HEADERS = ("name",)
KINDS = ("physical", "vm", "network", "unknown")
DEFAULT_KIND = "physical"  # a human declaring inventory usually means real gear


class CsvError(RuntimeError):
    pass


def parse_csv(text):
    """Return (rows, errors). `errors` non-empty means nothing should be written."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], ["empty file: expected a header row of " + ",".join(KNOWN_HEADERS)]

    headers = [(h or "").strip().lower() for h in reader.fieldnames]
    errors = []
    unknown = [h for h in headers if h and h not in KNOWN_HEADERS]
    if unknown:
        errors.append(f"line 1: unknown column(s) {unknown} — known: {list(KNOWN_HEADERS)}")
    for h in REQUIRED_HEADERS:
        if h not in headers:
            errors.append(f"line 1: missing required column {h!r}")
    if errors:
        return [], errors

    rows = []
    for raw in reader:
        line = reader.line_num
        row = {h: (str(raw.get(orig) or "").strip())
               for h, orig in zip(headers, reader.fieldnames)}
        if not any(row.values()):
            continue  # blank line

        name = row.get("name", "")
        if not name:
            errors.append(f"line {line}: name is required")
            continue

        ip = row.get("ip", "")
        if ip:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                errors.append(f"line {line}: {ip!r} is not an IP address")

        kind = (row.get("kind", "") or "").lower()
        if kind and kind not in KINDS:
            errors.append(f"line {line}: unknown kind {kind!r} — one of {list(KINDS)}")

        url = row.get("url", "")
        if url and not url.startswith(("http://", "https://")):
            errors.append(f"line {line}: url must start with http:// or https:// (got {url!r})")

        rows.append({
            "line": line, "name": name, "ip": ip or None, "kind": kind or DEFAULT_KIND,
            "zone": row.get("zone", "") or None, "role": row.get("role", "") or None,
            "url": url or None, "url_label": row.get("url_label", "") or None,
            "notes": row.get("notes", "") or None,
        })

    seen = {}
    for r in rows:
        slug = slugify(r["name"])
        if slug in seen:
            errors.append(f"line {r['line']}: duplicate name {r['name']!r} (also line {seen[slug]})")
        seen[slug] = r["line"]

    return rows, errors


def import_rows(session, rows, site_slug, retire_missing=False):
    """Write validated rows into `site_slug`. One transaction; additive unless
    `retire_missing`. Hand-written lore/links/positions are never overwritten."""
    now = datetime.now(timezone.utc)
    stats = {"created": 0, "updated": 0, "zones_created": 0,
             "links_added": 0, "retired": 0, "placed": 0}

    site = get_site(session, site_slug)
    if site is None:
        site = Site(slug=site_slug, name=site_slug)
        session.add(site)
        session.flush()

    zones = list(session.scalars(select(Zone).where(Zone.site_id == site.id)))
    zone_sort = max([z.sort_order for z in zones] + [-1]) + 1
    by_zone_slug = {z.slug: z for z in zones}
    by_zone_name = {(z.name or "").lower(): z for z in zones}

    def resolve_zone(label, ip):
        nonlocal zone_sort
        if label:
            z = by_zone_slug.get(slugify(label)) or by_zone_name.get(label.lower())
            if z is None:
                z = Zone(site_id=site.id, slug=slugify(label), name=label, hue="#8A8069",
                         lore="", sort_order=zone_sort,
                         extra_json=dict(UNKNOWN_ZONE_FIELDS))
                session.add(z)
                session.flush()
                zone_sort += 1
                by_zone_slug[z.slug] = z
                by_zone_name[(z.name or "").lower()] = z
                stats["zones_created"] += 1
            return z.slug
        return zone_for_ip(subnet_index(session, site), ip) or ensure_uncharted(session, site).slug

    nodes = list(session.scalars(select(Node).where(Node.site_id == site.id)))
    by_slug = {n.slug: n for n in nodes}
    node_sort = max([n.sort_order for n in nodes] + [-1]) + 1
    touched = set()

    for r in rows:
        slug = slugify(r["name"])
        touched.add(slug)
        n = by_slug.get(slug)
        zone_slug = resolve_zone(r["zone"], r["ip"])
        if n is None:
            n = Node(site_id=site.id, slug=slug, name=r["name"], kind=r["kind"],
                     zone_slug=zone_slug, role=r["role"] or "", lore=r["notes"] or "",
                     ip=r["ip"], external_source="csv", external_ref=slug,
                     sort_order=node_sort, extra_json={})
            session.add(n)
            node_sort += 1
            by_slug[slug] = n
            stats["created"] += 1
        else:
            n.name, n.kind = r["name"], r["kind"]
            if r["ip"]:
                n.ip = r["ip"]
            if r["role"]:
                n.role = r["role"]
            if r["zone"]:
                n.zone_slug = zone_slug
            if r["notes"] and not (n.lore or "").strip():
                n.lore = r["notes"]  # fill a blank, never overwrite a human's words
            if n.status == "retired":
                n.status = "documented"
            stats["updated"] += 1
        n.last_imported = now
        session.flush()

        if r["url"] and not any((l.url or "") == r["url"] for l in n.links):
            n.links.append(NodeLink(label=r["url_label"] or "Service", url=r["url"],
                                    sort_order=len(n.links), extra_json={}))
            stats["links_added"] += 1

    if retire_missing:
        for n in nodes:
            if n.external_source == "csv" and n.slug not in touched and n.status != "retired":
                n.status = "retired"
                stats["retired"] += 1

    session.flush()
    stats["placed"] = auto_layout(session, site)
    site.data_version = (site.data_version or 0) + 1
    site.updated_at = now
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    return stats


def import_text(session, text, site_slug, retire_missing=False):
    """parse + validate + write. Raises CsvError (no writes) if anything is wrong."""
    rows, errors = parse_csv(text)
    if errors:
        raise CsvError("\n".join(errors))
    return import_rows(session, rows, site_slug, retire_missing=retire_missing)
