
import { inRack, isEmpty, rackList } from './rack-model.js';
import { lineage, premiseIndex, premiseOf, rackPremises } from './premises-model.js';

export const locKey = (name) => String(name ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
const clean = (name) => String(name ?? '').trim().replace(/\s+/g, ' ');

export function whereabouts(data, fallback = '') {
  const d = data && typeof data === 'object' ? data : {};
  const nodes = (Array.isArray(d.nodes) ? d.nodes : []).filter((n) => n && typeof n.id === 'string');
  const base = clean(fallback);
  const list = [];
  const byKey = new Map();
  const ix = premiseIndex(d);
  const inPremise = ix.size ? premiseOf(d, ix) : new Map();
  const rackIn = ix.size ? rackPremises(d, ix) : new Map();
  const atPremise = (pid) => {
    const key = `@${pid}`;
    if (!byKey.has(key)) {
      const line = lineage(ix, pid);
      const entry = { key, name: clean(ix.byId.get(pid)?.name) || pid, racks: [], loose: [], premise: pid,
        path: line.slice(0, -1).map((id) => clean(ix.byId.get(id)?.name) || id) };
      byKey.set(key, entry);
      list.push(entry);
    }
    return byKey.get(key);
  };
  const at = (name) => {
    const shown = clean(name) || base;
    const key = locKey(shown);
    if (!byKey.has(key)) {
      const entry = { key, name: shown, racks: [], loose: [] };
      byKey.set(key, entry);
      list.push(entry);
    }
    return byKey.get(key);
  };

  const racks = rackList(d.racks, base);
  const rackAt = new Map();
  for (const r of racks) {
    const entry = rackIn.has(r.id) ? atPremise(rackIn.get(r.id)) : at(r.location);
    entry.racks.push(r);
    rackAt.set(r.id, entry.key);
  }
  const ofNode = new Map();
  const racked = new Set();
  const rackOf = new Map();
  const fitted = new Map(racks.map((r) => [r.id, 0]));
  for (const section of [d.rack, d.rack_rear]) {
    for (const r of racks) {
      for (const slot of inRack(Array.isArray(section) ? section : [], racks, r.id)) {
        if (!slot) continue;
        if (!isEmpty(slot)) fitted.set(r.id, fitted.get(r.id) + 1);
        if (typeof slot.node !== 'string' || !slot.node || racked.has(slot.node)) continue;
        racked.add(slot.node);
        ofNode.set(slot.node, rackAt.get(r.id));
        rackOf.set(slot.node, r.id);
      }
    }
  }

  const vms = Array.isArray(d.vms) ? d.vms.filter((v) => v && typeof v.id === 'string') : [];
  const guests = new Set(vms.map((v) => v.id));
  for (const n of nodes) if (n.kind === 'vm') guests.add(n.id);

  for (const n of nodes) {
    if (guests.has(n.id) || racked.has(n.id)) continue;
    const said = clean(n.location);
    if (inPremise.has(n.id)) {
      const entry = atPremise(inPremise.get(n.id));
      entry.loose.push(n);
      ofNode.set(n.id, entry.key);
      continue;
    }
    if (n.kind !== 'physical' && !said) continue;
    const entry = at(said);
    entry.loose.push(n);
    ofNode.set(n.id, entry.key);
  }

  const hostOf = new Map(vms.map((v) => [v.id, v.host]));
  for (const n of nodes) if (guests.has(n.id) && !hostOf.get(n.id) && n.parent) hostOf.set(n.id, n.parent);
  for (const id of guests) {
    let host = hostOf.get(id);
    for (let hops = 0; host && guests.has(host) && hops < 8; hops++) host = hostOf.get(host);
    if (host && ofNode.has(host)) ofNode.set(id, ofNode.get(host));
    if (host && rackOf.has(host)) rackOf.set(id, rackOf.get(host));
  }
  return { list, ofNode, racked, guests, rackOf, fitted };
}

export function rackById(where, id) {
  if (id === null || id === undefined) return null;
  for (const l of where.list) {
    const hit = l.racks.find((r) => r.id === id);
    if (hit) return hit;
  }
  return null;
}

export function locationOfRack(where, id) {
  if (id === null || id === undefined) return null;
  return where.list.find((l) => l.racks.some((r) => r.id === id)) || null;
}

export function offered(where, holds, keep = '') {
  return where.list
    .filter((l) => (keep && l.key === keep) || holds(l, null))
    .map((l) => ({ loc: l, racks: l.racks.filter((r) => holds(l, r)) }));
}

export const holdsHardware = (where) => (l, r) => (r
  ? (where.fitted.get(r.id) || 0) > 0
  : l.loose.length > 0 || l.racks.some((x) => (where.fitted.get(x.id) || 0) > 0));

export function holdsPlaces(where) {
  const keys = new Set(where.ofNode.values());
  const racks = new Set(where.rackOf.values());
  return (l, r) => (r ? racks.has(r.id) : keys.has(l.key));
}

export function locationByKey(where, key) {
  if (key === null || key === undefined || key === '') return null;
  const k = String(key).startsWith('@') ? String(key) : locKey(key);
  return where.list.find((l) => l.key === k) || null;
}

export function racksAt(where, loc) {
  return loc ? loc.racks : where.list.flatMap((l) => l.racks);
}

export function looseAt(where, loc) {
  const from = loc ? [loc] : where.list;
  return from.flatMap((l) => l.loose.map((node) => ({ node, location: l })));
}

export function rackable(data, where) {
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && typeof n.id === 'string'
    && !where.guests.has(n.id) && !where.racked.has(n.id));
  return [...nodes.filter((n) => n.kind === 'physical'), ...nodes.filter((n) => n.kind !== 'physical')];
}

export function placesFor(where, loc, nodes, routes = [], rack = null) {
  const list = (Array.isArray(nodes) ? nodes : []).filter((n) => n && typeof n.id === 'string');
  if (!loc && !rack) return list;
  const here = new Set(list.filter((n) => (rack ? where.rackOf.get(n.id) === rack.id
    : where.ofNode.get(n.id) === loc.key)).map((n) => n.id));
  const next = new Set();
  for (const r of Array.isArray(routes) ? routes : []) {
    if (!r) continue;
    if (here.has(r.from) && !here.has(r.to)) next.add(r.to);
    if (here.has(r.to) && !here.has(r.from)) next.add(r.from);
  }
  return list.filter((n) => here.has(n.id) || !where.ofNode.has(n.id) || next.has(n.id));
}

export function awayFrom(where, loc, nodes, rack = null) {
  const away = new Map();
  if (!loc && !rack) return away;
  for (const n of nodes || []) {
    const at = where.ofNode.get(n.id);
    if (at === undefined) continue;
    if (rack ? where.rackOf.get(n.id) !== rack.id : at !== loc.key) away.set(n.id, at);
  }
  return away;
}
