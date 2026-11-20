/* WHERE THE HARDWARE STANDS: locations-model.js (2026-11-20), with no DOM.

   HARDWARE (reliquary.js) and RESOURCES (tribute.js) both show the lab by
   location (owner: "it should show a drop down of locations, like home office
   or wherever there's compute"), so both ask this one file where a thing is.

   A location is a NAME, written in one of two places on the map:
     a rack's `location`   everything in that rack, front or rear, is there;
     a place's `location`  for what stands outside a rack (a Raspberry Pi on a
                           shelf, an access point, a desk machine).
   A rack that names none, and a machine in no rack that names none, are at the
   map's default location (the theme's `rack_location`), so a lab that has
   written nothing has one location and loses nothing. Two spellings of one
   name ("Home office", "home  Office") are one location: `locKey` folds case
   and spaces, and the first spelling met is the one shown.

   What counts as hardware outside a rack: a `physical` place always; any
   other place that is not a guest only when it says where it stands. A
   `network` place is as often an idea as a box (the internet, a tunnel, a
   DNS provider), and listing those on a shelf would be the map inventing
   iron. A guest (a `vm`, or anything listed in `vms`) is never hardware; it
   is where its host is.

   A RACK is one step finer than a location (owner, 2026-11-20: "you should
   be able to see the resources of a specific device, (Rack a or rack B) that
   is associated with a specific location"): `rackOf` says which rack a
   machine sits in, and a guest is in its host's rack. And a scene only
   offers a location, or a rack, that has something for it to draw (owner,
   the same day: "if there isn't any equipment/hardware at a location that
   location shouldn't be displayed in the drop down"): `offered` is that list.

   Unit-tested by tests/test_locations_model.mjs under plain node. */

import { inRack, isEmpty, rackList } from './rack-model.js';

/** One name, however it was typed: trimmed, single-spaced, lower case. */
export const locKey = (name) => String(name ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
const clean = (name) => String(name ?? '').trim().replace(/\s+/g, ' ');

/** Where everything is.

    `fallback` is the default location's name (the theme's). Returns
      list     [{key, name, racks: [{id, name, location}], loose: [node]}],
               in the map's order: the racks' locations, then the rest;
      ofNode   Map(place id → location key) for every racked or loose machine
               and every guest whose host has one;
      racked   Set(place id) of what sits in a rack, front or rear;
      guests   Set(place id) of the guests;
      rackOf   Map(place id → rack id) for every racked machine and every
               guest whose host is racked;
      fitted   Map(rack id → how many things sit in it, front and rear,
               whether or not they are places on the map). */
export function whereabouts(data, fallback = '') {
  const d = data && typeof data === 'object' ? data : {};
  const nodes = (Array.isArray(d.nodes) ? d.nodes : []).filter((n) => n && typeof n.id === 'string');
  const base = clean(fallback);
  const list = [];
  const byKey = new Map();
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

  // the racks first: a lab that charted none has the one rack it always had
  const racks = rackList(d.racks, base);
  const rackAt = new Map();
  for (const r of racks) {
    const entry = at(r.location);
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
        // a slot the map calls empty (kept to say how tall the rack is) is not a thing
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

  // what stands outside a rack
  for (const n of nodes) {
    if (guests.has(n.id) || racked.has(n.id)) continue;
    const said = clean(n.location);
    if (n.kind !== 'physical' && !said) continue;
    const entry = at(said);
    entry.loose.push(n);
    ofNode.set(n.id, entry.key);
  }

  // a guest is where its host is (a host that is itself a guest is followed up)
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

/** The rack an id names, or null: `''` is a real id (the one rack of a map
    that charts none), so only null and undefined mean "no rack asked for". */
export function rackById(where, id) {
  if (id === null || id === undefined) return null;
  for (const l of where.list) {
    const hit = l.racks.find((r) => r.id === id);
    if (hit) return hit;
  }
  return null;
}

/** The location a rack stands at, or null. */
export function locationOfRack(where, id) {
  if (id === null || id === undefined) return null;
  return where.list.find((l) => l.racks.some((r) => r.id === id)) || null;
}

/** What a scene offers to choose between: the locations that hold something
    for it, each with the racks there that do.

    `holds(location, rack | null)` is the scene's own answer to "is there
    anything of mine here": for the location as a whole when the rack is
    null, else for that one rack. `keep` is the key of the location on show:
    it is offered whatever it holds, so the thing that emptied it does not
    throw the scene somewhere else. Returns [{loc, racks}]. */
export function offered(where, holds, keep = '') {
  return where.list
    .filter((l) => (keep && l.key === keep) || holds(l, null))
    .map((l) => ({ loc: l, racks: l.racks.filter((r) => holds(l, r)) }));
}

/** `holds` for HARDWARE: anything in the rack, or anything on the shelf. */
export const holdsHardware = (where) => (l, r) => (r
  ? (where.fitted.get(r.id) || 0) > 0
  : l.loose.length > 0 || l.racks.some((x) => (where.fitted.get(x.id) || 0) > 0));

/** `holds` for TOPOLOGY: a place on the map that stands there. */
export function holdsPlaces(where) {
  const keys = new Set(where.ofNode.values());
  const racks = new Set(where.rackOf.values());
  return (l, r) => (r ? racks.has(r.id) : keys.has(l.key));
}

/** The location a key names, or null: `''`, null and an unknown key are
    "everywhere". */
export function locationByKey(where, key) {
  if (key === null || key === undefined || key === '') return null;
  return where.list.find((l) => l.key === locKey(key)) || null;
}

/** The racks to show for a location (every rack when it is null). */
export function racksAt(where, loc) {
  return loc ? loc.racks : where.list.flatMap((l) => l.racks);
}

/** The machines outside a rack for a location (all of them when it is null),
    each with the location it stands at. */
export function looseAt(where, loc) {
  const from = loc ? [loc] : where.list;
  return from.flatMap((l) => l.loose.map((node) => ({ node, location: l })));
}

/** The places that could be put in a rack: everything on the map that is
    not a guest and not in a rack already, the physical machines first. */
export function rackable(data, where) {
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && typeof n.id === 'string'
    && !where.guests.has(n.id) && !where.racked.has(n.id));
  return [...nodes.filter((n) => n.kind === 'physical'), ...nodes.filter((n) => n.kind !== 'physical')];
}

/** The places TOPOLOGY draws for a location (every place when it is null):
    what is at that location, guests with their hosts; whatever is at no
    location at all; and the next stop of each of its routes when that stop
    stands somewhere else. The placeless are the world beyond and the ways in
    (the internet, a tunnel, a DNS provider): they belong to no one site and
    every site's routes run out through them. The next stops are how a room
    with one machine is shown to reach anything: its gateway is in another
    room, and a location drawn without it would be an island with its roads
    cut off at the shore. `awayFrom` says which of them are those visitors. */
export function placesFor(where, loc, nodes, routes = [], rack = null) {
  const list = (Array.isArray(nodes) ? nodes : []).filter((n) => n && typeof n.id === 'string');
  if (!loc && !rack) return list;
  // one rack is the same drawing one step finer: what is in it, and its guests
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

/** Of some places drawn for a location, the ids that stand at ANOTHER one
    (a route's next stop): Map(place id → that location's key). For one rack
    it is every placed thing outside that rack, the same room's included:
    Map(place id → the key of the location it stands at). */
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
