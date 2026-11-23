
import { whereabouts } from './locations-model.js';
import { premiseNamed, premisePaths } from './premises-model.js';
import { rackList } from './rack-model.js';

const clean = (name) => String(name ?? '').trim().replace(/\s+/g, ' ');
const listOf = (v) => (Array.isArray(v) ? v : []);

export const IMPLIED_RACK = { id: 'rack-a', name: 'Rack A' };

export function knownLocations(data, fallback = '', within = '') {
  const named = whereabouts(data, fallback).list.filter((l) => !l.premise).map((l) => l.name).filter(Boolean);
  return [...premisePaths(data, within), ...named];
}

export function locationTarget(data, fallback, ask) {
  const d = data && typeof data === 'object' ? data : {};
  const where = whereabouts(d, fallback);
  const base = clean(fallback);
  const racks = rackList(d.racks, base);
  const shownAt = (key) => where.list.find((l) => l.key === key)?.name || base;

  const rackTarget = (rackId, extra = {}) => {
    const rack = racks.find((r) => r.id === rackId);
    if (!rack) return { kind: 'none', why: 'missing' };
    const record = listOf(d.racks).find((r) => r && r.id === rackId);
    const written = clean(record?.location);
    return { kind: 'rack', id: rack.id, name: rack.name, implied: !record,
      current: written || base, written, via: '', asked: rack.name, ...extra };
  };

  if (ask && Object.hasOwn(ask, 'rack')) return rackTarget(ask.rack ?? '');

  const nodes = listOf(d.nodes).filter((n) => n && typeof n.id === 'string');
  const node = nodes.find((n) => n.id === ask?.node);
  if (!node) return { kind: 'none', why: 'missing' };
  const asked = node.name || node.id;

  let at = node;
  let via = '';
  if (where.guests.has(node.id)) {
    const hostOf = new Map(listOf(d.vms).filter((v) => v && typeof v.id === 'string').map((v) => [v.id, v.host]));
    let host = hostOf.get(node.id) || node.parent;
    for (let hops = 0; host && where.guests.has(host) && hops < 8; hops++) {
      host = hostOf.get(host) || nodes.find((n) => n.id === host)?.parent;
    }
    at = nodes.find((n) => n.id === host && !where.guests.has(n.id));
    if (!at) return { kind: 'none', why: 'guest', asked };
    via = 'host';
  }

  if (where.racked.has(at.id)) {
    return rackTarget(where.rackOf.get(at.id), { via: via || 'rack', asked, host: via ? at.name || at.id : '' });
  }
  const written = clean(at.location);
  return { kind: 'place', id: at.id, name: at.name || at.id, implied: false, iron: at.kind === 'physical' || Boolean(written),
    current: where.ofNode.has(at.id) ? shownAt(where.ofNode.get(at.id)) : written || base,
    written, via, asked, host: via ? at.name || at.id : '' };
}

export function locationOps(data, target, name) {
  if (!target || target.kind === 'none') return [];
  const said = clean(name);
  if (said === target.written) return [];
  const meant = Array.isArray(data?.premises) && data.premises.length ? premiseNamed(data, said) : null;
  const body = meant ? { premise: meant, location: null }
    : { location: said || null, ...(Array.isArray(data?.premises) && data.premises.length ? { premise: null } : {}) };
  if (target.kind === 'place') {
    return [{ op: 'upsert', section: 'nodes', id: target.id, body }];
  }
  if (!target.implied) {
    return [{ op: 'upsert', section: 'racks', id: target.id, body }];
  }
  if (!said) return [];
  const taken = new Set(listOf(data?.racks).map((r) => r?.id));
  let id = IMPLIED_RACK.id;
  for (let n = 2; taken.has(id); n++) id = `${IMPLIED_RACK.id}-${n}`;
  return [{ op: 'insert', section: 'racks', body: { id, name: target.name || IMPLIED_RACK.name, location: said } }];
}

export function boxTargets(data, fallback, ids) {
  const byKey = new Map();
  const skipped = [];
  for (const id of ids || []) {
    const t = locationTarget(data, fallback, { node: id });
    if (t.kind === 'none' || (t.kind === 'place' && !t.iron)) { if (t.asked) skipped.push(t.asked); continue; }
    const key = `${t.kind}:${t.id}`;
    if (!byKey.has(key)) byKey.set(key, { ...t, places: [] });
    byKey.get(key).places.push(t.asked);
  }
  return { targets: [...byKey.values()], skipped };
}

export function boxOps(data, targets, name) {
  return (targets || []).flatMap((t) => locationOps(data, t, name));
}

export function placesInside(spots, rect) {
  if (!rect || !spots) return [];
  return Object.keys(spots).filter((id) => {
    const p = spots[id];
    return p && Number.isFinite(p.x) && Number.isFinite(p.y)
      && p.x >= rect.x && p.x <= rect.x + rect.w && p.y >= rect.y && p.y <= rect.y + rect.h;
  });
}

export function regionId(name, taken = []) {
  const base = clean(name).toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'zoom-map';
  const used = new Set(taken);
  let id = base;
  for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
  return id;
}

export function touchWords(targets) {
  const names = (targets || []).map((t) => (t.kind === 'rack' ? `${t.name} (the whole rack)` : t.name));
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}
