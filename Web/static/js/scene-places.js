
import { A, esc, themeText } from './config.js';
import { holdsHardware, holdsPlaces, offered, whereabouts } from './locations-model.js';
import { holdsHosts, hostsOf } from './tribute-model.js';

let read = { data: null, where: null, hosts: null };

export function whereNow() {
  if (!read.where || read.data !== A.DATA) {
    read = { data: A.DATA, where: whereabouts(A.DATA, themeText('rack_location', '')), hosts: null };
  }
  return read.where;
}

export function hostsNow() {
  const where = whereNow();
  if (!read.hosts) read.hosts = hostsOf(A.DATA, where.ofNode, where.rackOf);
  return read.hosts;
}

export function offerFor(scene, keep = '') {
  const where = whereNow();
  const holds = scene === 'tribute' ? holdsHosts(hostsNow())
    : scene === 'path' ? holdsPlaces(where) : holdsHardware(where);
  return offered(where, holds, keep);
}

export const placeName = (loc) => (loc && loc.name) || 'Here';

export function whereLine(loc, rack = null) {
  if (!loc) return '';
  const whole = (name) => String(name).replace(/ /g, '\u00a0');
  return rack ? `${whole(placeName(loc))}\u00a0· ${whole(rack.name)}` : placeName(loc);
}

export function markPlace(scene, key) {
  const btn = document.querySelector(`.scene[data-scene="${scene}"]`);
  if (!btn) return;
  if (key) btn.dataset.place = key; else delete btn.dataset.place;
}

export function askPlace(scene, place) {
  dispatchEvent(new CustomEvent('atlas:scene-place', { detail: { scene, place: place || '' } }));
}

const seg = (on, attrs, label) => `<button type="button" class="rel-seg${on ? ' is-on' : ''}" ${attrs}`
  + ` aria-pressed="${on}">${esc(label)}</button>`;

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

export function racksOffered(scene, key) {
  const where = whereNow();
  const offer = offerFor(scene, key);
  const at = key ? offer.find((o) => o.loc.key === key) : (where.list.length === 1 ? offer[0] : null);
  if (!at) return [];
  if (at.racks.length >= 2) return at.racks;
  const more = at.loc.loose.length > 0 || at.loc.racks.filter((r) => (where.fitted.get(r.id) || 0) > 0).length > 1;
  return at.racks.length === 1 && where.list.length > 1 && more ? at.racks : [];
}

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
