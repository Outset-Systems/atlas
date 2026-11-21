/* A scene shown by location (2026-11-20): what HARDWARE (reliquary.js),
   RESOURCES (tribute.js) and TOPOLOGY (path.js) share on the page.

   The rules of what a location is are locations-model.js. This file is the
   things all three scenes do with one: read where everything is from the map
   now in the browser, say what each scene has to offer, draw the picker of
   locations (and, one step finer, of the racks at one) inside the scene, and
   say on the band's own button what the scene is showing.

   That last one is a `data-place` on the band button. The band (ui.js)
   reads it so that a press on the button of a scene that is showing ONE
   location shows everything, and only the next press closes it (owner:
   "selecting 'home office' will display just the resources there, but
   selecting 'Resources' will display a summary/total of everything"). The
   hover menu under the button (band-menus.js) and that press both ask by
   event, `atlas:scene-place` with detail {scene, place}; '' is everything.

   A RACK is chosen inside the scene and nowhere else (owner, 2026-11-20:
   "don't put the machines in the drop down, just the location. then when a
   location is selected, you can switch between machines at that location"):
   `drawRackPicker`, beside the locations' own.

   WHAT IS OFFERED (owner, 2026-11-20: "if there isn't any equipment/hardware
   at a location that location shouldn't be displayed in the drop down"). A
   scene offers a location only when it has something of that scene's to
   draw there: hardware for HARDWARE, a machine that runs guests for
   RESOURCES, a place on the map for TOPOLOGY. The racks at a location are
   held to the same rule. The menu and the picker read the one
   list, so they never disagree. */

import { A, esc, themeText } from './config.js';
import { holdsHardware, holdsPlaces, offered, whereabouts } from './locations-model.js';
import { holdsHosts, hostsOf } from './tribute-model.js';

let read = { data: null, where: null, hosts: null };

/** Where everything is, for the map now in the browser (read once per map). */
export function whereNow() {
  if (!read.where || read.data !== A.DATA) {
    read = { data: A.DATA, where: whereabouts(A.DATA, themeText('rack_location', '')), hosts: null };
  }
  return read.where;
}

/** RESOURCES' hosts for the map now in the browser (summed once per map). */
export function hostsNow() {
  const where = whereNow();
  if (!read.hosts) read.hosts = hostsOf(A.DATA, where.ofNode, where.rackOf);
  return read.hosts;
}

/** What a scene offers to choose between: [{loc, racks}], the locations that
    hold something for it and the racks at each that do. `keep` is the key of
    the location on show, offered whatever it holds. */
export function offerFor(scene, keep = '') {
  const where = whereNow();
  const holds = scene === 'tribute' ? holdsHosts(hostsNow())
    : scene === 'path' ? holdsPlaces(where) : holdsHardware(where);
  return offered(where, holds, keep);
}

/** A location's name as a control says it; one with no name at all (no theme
    word and nothing written) is still a place. */
export const placeName = (loc) => (loc && loc.name) || 'Here';

/** What a scene's title line says it is showing: nothing for everything, the
    location, or "Garage · Rack B". Each name holds together (a no-break space
    for each of its own), so a narrow title breaks between the two names and
    never inside one. */
export function whereLine(loc, rack = null) {
  if (!loc) return '';
  const whole = (name) => String(name).replace(/ /g, '\u00a0');
  return rack ? `${whole(placeName(loc))}\u00a0· ${whole(rack.name)}` : placeName(loc);
}

/** Say on a scene's band button which location it shows ('' = everything). */
export function markPlace(scene, key) {
  const btn = document.querySelector(`.scene[data-scene="${scene}"]`);
  if (!btn) return;
  if (key) btn.dataset.place = key; else delete btn.dataset.place;
}

/** Ask a scene to show a location ('' = everything). */
export function askPlace(scene, place) {
  dispatchEvent(new CustomEvent('atlas:scene-place', { detail: { scene, place: place || '' } }));
}

const seg = (on, attrs, label) => `<button type="button" class="rel-seg${on ? ' is-on' : ''}" ${attrs}`
  + ` aria-pressed="${on}">${esc(label)}</button>`;

/** The picker inside a scene: ALL, then each location the scene offers, as
    one segmented control. Hidden while there is a single one and everything
    is on show (there is nothing to pick); with a location on show it is
    drawn whatever the count, since ALL is then the way back. The hover menu
    needs a mouse; this is the way for a touch screen, a phone and a
    keyboard. `onPick(key)` gets '' for everything. */
export function drawPlacePicker(el, scene, key, onPick, allLabel = 'All') {
  if (!el) return;
  const offer = offerFor(scene, key);
  el.hidden = offer.length < 2 && !key;
  el.innerHTML = seg(key === '', 'data-place=""', allLabel)
    + offer.map((o) => seg(o.loc.key === key, `data-place="${esc(o.loc.key)}"`, placeName(o.loc))).join('');
  el.onclick = (e) => {
    const b = e.target.closest('[data-place]');
    if (!b) return;
    e.stopPropagation();
    onPick(b.dataset.place);
  };
}

/** The racks to switch between for what a scene is showing: those at the
    location on show; with no location chosen, those of a map that has only
    one location. Two racks are always a choice. One rack is a choice only
    where the location is more than that rack (something stands outside it,
    or another rack stands there with nothing of this scene's in it), and
    only on a map of several locations: on a map of one, the one rack is the
    lab itself (the lab this was written for) and a switch of one thing is
    noise. */
export function racksOffered(scene, key) {
  const where = whereNow();
  const offer = offerFor(scene, key);
  const at = key ? offer.find((o) => o.loc.key === key) : (where.list.length === 1 ? offer[0] : null);
  if (!at) return [];
  if (at.racks.length >= 2) return at.racks;
  const more = at.loc.loose.length > 0 || at.loc.racks.filter((r) => (where.fitted.get(r.id) || 0) > 0).length > 1;
  return at.racks.length === 1 && where.list.length > 1 && more ? at.racks : [];
}

/** The picker of racks inside a scene, beside the picker of locations: the
    whole location, then each rack `racksOffered` gives. `onPick(id)` gets
    null for the whole location. */
export function drawRackPicker(el, scene, key, rackId, onPick, allLabel = 'All') {
  if (!el) return;
  const racks = racksOffered(scene, key);
  el.hidden = !racks.length;
  el.innerHTML = !racks.length ? '' : seg(rackId === null, 'data-whole="1"', allLabel)
    + racks.map((r) => seg(r.id === rackId, `data-rack="${esc(r.id)}"`, r.name)).join('');
  el.onclick = (e) => {
    const b = e.target.closest('[data-rack], [data-whole]');
    if (!b) return;
    e.stopPropagation();
    onPick(b.dataset.whole ? null : b.dataset.rack);
  };
}
