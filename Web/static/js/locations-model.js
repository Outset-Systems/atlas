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

   Unit-tested by tests/test_locations_model.mjs under plain node. */

import { inRack, rackList } from './rack-model.js';

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
      guests   Set(place id) of the guests. */
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
  for (const section of [d.rack, d.rack_rear]) {
    for (const r of racks) {
      for (const slot of inRack(Array.isArray(section) ? section : [], racks, r.id)) {
        if (!slot || typeof slot.node !== 'string' || !slot.node || racked.has(slot.node)) continue;
        racked.add(slot.node);
        ofNode.set(slot.node, rackAt.get(r.id));
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
  }
  return { list, ofNode, racked, guests };
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
