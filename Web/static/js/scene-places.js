/* A scene shown by location (2026-11-20): what HARDWARE (reliquary.js) and
   RESOURCES (tribute.js) share on the page.

   The rules of what a location is are locations-model.js. This file is the
   three things both scenes do with one: read where everything is from the
   map now in the browser, draw the picker of locations inside the scene, and
   say on the band's own button which location the scene is showing.

   That last one is a `data-place` on the band button. The band (ui.js) reads
   it so that a press on the button of a scene that is showing ONE location
   shows everything, and only the next press closes it (owner: "selecting
   'home office' will display just the resources there, but selecting
   'Resources' will display a summary/total of everything"). The hover menu
   under the button (band-menus.js) and that press both ask by event,
   `atlas:scene-place` with detail {scene, place}; '' is everything. */

import { A, esc, themeText } from './config.js';
import { whereabouts } from './locations-model.js';

let read = { data: null, where: null };

/** Where everything is, for the map now in the browser (read once per map). */
export function whereNow() {
  if (!read.where || read.data !== A.DATA) {
    read = { data: A.DATA, where: whereabouts(A.DATA, themeText('rack_location', '')) };
  }
  return read.where;
}

/** A location's name as a control says it; one with no name at all (no theme
    word and nothing written) is still a place. */
export const placeName = (loc) => (loc && loc.name) || 'Here';

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

/** The picker inside a scene: ALL, then each location, as one segmented
    control. Hidden while the map has a single location (there is nothing to
    pick). The hover menu needs a mouse; this is the way for a touch screen,
    a phone and a keyboard. `onPick(key)` gets '' for everything. */
export function drawPlacePicker(el, key, onPick, allLabel = 'All') {
  if (!el) return;
  const list = whereNow().list;
  el.hidden = list.length < 2;
  const seg = (k, label) => `<button type="button" class="rel-seg${k === key ? ' is-on' : ''}" data-place="${esc(k)}"`
    + ` aria-pressed="${k === key}">${esc(label)}</button>`;
  el.innerHTML = seg('', allLabel) + list.map((l) => seg(l.key, placeName(l))).join('');
  el.onclick = (e) => {
    const b = e.target.closest('[data-place]');
    if (!b) return;
    e.stopPropagation();
    onPick(b.dataset.place);
  };
}
