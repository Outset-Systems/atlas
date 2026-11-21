/* SAYING WHERE A THING STANDS: location-set-model.js (2026-11-20), with no DOM.

   Owner: "add a way to add locations. maybe a button in the node view, or
   hardware view to set/add location for stuff", "maybe you can also add a
   location in the wiring section too", "in map editor a way to draw a box to
   create a zoom map and/or location".

   A location is a name written on a rack or on a place (locations-model.js),
   so "set the location of X" has to find the record that decides where X is:

     a place outside a rack   its own `location`;
     a place in a rack        the RACK's `location`: the rack is what stands
                              somewhere, and everything in it goes with it;
     a guest                  wherever its host is, so the host's record (by
                              one of the two rules above).

   A map that charts no racks has one implied rack (rack-model.js rackList,
   id ''); naming its location writes the rack's first record, which every
   slot that names no rack already belongs to.

   `locationTarget` finds that record, `locationOps` is what to send the
   editing API, and `boxTargets` does it for every place inside a drawn box,
   each record once. Unit-tested by tests/test_location_set_model.mjs. */

import { whereabouts } from './locations-model.js';
import { rackList } from './rack-model.js';

const clean = (name) => String(name ?? '').trim().replace(/\s+/g, ' ');
const listOf = (v) => (Array.isArray(v) ? v : []);

/** The id the implied rack is written under, clear of any rack already there. */
export const IMPLIED_RACK = { id: 'rack-a', name: 'Rack A' };

/** Every location's name, as the map shows them, in its order. */
export function knownLocations(data, fallback = '') {
  return whereabouts(data, fallback).list.map((l) => l.name).filter(Boolean);
}

/** The record that decides where a thing stands.

    `ask` is `{node: id}` or `{rack: id}`. Returns
      kind     'place' | 'rack' | 'none'
      id       the record's id (a rack's may be '': the implied one)
      name     what to call the record
      implied  true for the rack no record charts yet
      current  the location it is at now, as shown (the default one included)
      written  what the record itself says ('' when it says nothing)
      via      'rack' when a place was asked and its rack answers,
               'host' when a guest was asked and its host answers, else ''
      asked    the name of the thing asked about
      iron     for a 'place': it is hardware already (a physical machine, or
               one that says where it stands); a network place that says
               nothing is as often an idea as a box (locations-model.js)
      why      for 'none': 'missing' or 'guest' (a guest with no host) */
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

  // a guest is where its host is: follow it up to iron
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

/** What to send for one target and one name. A blank name clears what the
    record says (it is then at the default location); nothing is sent when
    that changes nothing. */
export function locationOps(data, target, name) {
  if (!target || target.kind === 'none') return [];
  const said = clean(name);
  if (said === target.written) return [];
  if (target.kind === 'place') {
    return [{ op: 'upsert', section: 'nodes', id: target.id, body: { location: said || null } }];
  }
  if (!target.implied) {
    return [{ op: 'upsert', section: 'racks', id: target.id, body: { location: said || null } }];
  }
  if (!said) return [];
  const taken = new Set(listOf(data?.racks).map((r) => r?.id));
  let id = IMPLIED_RACK.id;
  for (let n = 2; taken.has(id); n++) id = `${IMPLIED_RACK.id}-${n}`;
  return [{ op: 'insert', section: 'racks', body: { id, name: target.name || IMPLIED_RACK.name, location: said } }];
}

/** The records that decide where the places `ids` stand, each once, with
    the places that led to it; and the places that have none to write (a
    guest with no host, a network place that is not hardware).
    Returns {targets: [{...target, places: [name]}], skipped: [name]}. */
export function boxTargets(data, fallback, ids) {
  const byKey = new Map();
  const skipped = [];
  for (const id of ids || []) {
    const t = locationTarget(data, fallback, { node: id });
    // a box never turns an idea (the internet, a tunnel) into a machine on a shelf
    if (t.kind === 'none' || (t.kind === 'place' && !t.iron)) { if (t.asked) skipped.push(t.asked); continue; }
    const key = `${t.kind}:${t.id}`;
    if (!byKey.has(key)) byKey.set(key, { ...t, places: [] });
    byKey.get(key).places.push(t.asked);
  }
  return { targets: [...byKey.values()], skipped };
}

/** The ops for a whole box under one name. */
export function boxOps(data, targets, name) {
  return (targets || []).flatMap((t) => locationOps(data, t, name));
}

/** The places whose spot is inside a rectangle: `spots` is {id: {x, y}} and
    `rect` {x, y, w, h}, all in the same map's percent. */
export function placesInside(spots, rect) {
  if (!rect || !spots) return [];
  return Object.keys(spots).filter((id) => {
    const p = spots[id];
    return p && Number.isFinite(p.x) && Number.isFinite(p.y)
      && p.x >= rect.x && p.x <= rect.x + rect.w && p.y >= rect.y && p.y <= rect.y + rect.h;
  });
}

/** A region's id from its name: a slug, clear of the ids already taken. */
export function regionId(name, taken = []) {
  const base = clean(name).toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'zoom-map';
  const used = new Set(taken);
  let id = base;
  for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
  return id;
}

/** A plain line for what a save will touch: "PI, NAS and Rack A (the whole rack)". */
export function touchWords(targets) {
  const names = (targets || []).map((t) => (t.kind === 'rack' ? `${t.name} (the whole rack)` : t.name));
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}
