/* Atlas — places.js: where each place stands, and moving it.

   A place has its own spot in the dataset. A drag in Settings → Move places is
   kept in this browser until it is saved: over the dataset's spot on the map's
   own art, per style when another map style is on. A region on the stage holds
   its places at their spots there. `applyOverrides` settles all of that onto
   each node before world.js draws, and `dragOnMap` is the one drag the markers
   and the network names share.

   Split out of world.js, which imports it; everything else reaches it through
   `A`, as it always did. */

import { A, DRAG_END, postJSON } from './config.js';
import { unproject } from './project.js';

/* ── Place editor: drag the dots (Settings → Move the dots) ─────────────
   Positions are overridden per-browser in localStorage so the canonical
   dataset is never touched; "copy" exports the moved coords to bake in. */
const POS_KEY = 'atlas-pos-overrides';
function posOverrides() {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch { return {}; }
}
/* On another map style a spot belongs to that picture, so a drag there is kept
   per style ({places, zones, regions: {id: places}}) and Save writes it into
   the style's sidecar (mapart.save_layout), never the dataset. */
const STYLE_POS_KEY = 'atlas-style-pos';
let styleDrafts = (() => {
  try { return JSON.parse(localStorage.getItem(STYLE_POS_KEY) || '{}') || {}; } catch { return {}; }
})();
export const onStyleArt = () => Boolean(A.styleArt) && (A.onOtherStyle?.() ?? true);
A.styleDraft = () => {
  const d = (onStyleArt() && styleDrafts[A.styleArt]) || {};
  return { places: d.places || {}, zones: d.zones || {}, regions: d.regions || {} };
};
A.draftStyleSpot = function draftStyleSpot(kind, id, at, regionId) {
  const d = (styleDrafts[A.styleArt] = A.styleDraft());
  const spot = { x: Math.round(at.x * 10) / 10, y: Math.round(at.y * 10) / 10 };
  if (regionId) (d.regions[regionId] ??= {})[id] = spot;
  else d[kind][id] = spot;
  try { localStorage.setItem(STYLE_POS_KEY, JSON.stringify(styleDrafts)); } catch { /* private mode: the move still draws */ }
};
const draftCount = (d) => Object.keys(d.places).length + Object.keys(d.zones).length +
  Object.values(d.regions).reduce((sum, pins) => sum + Object.keys(pins).length, 0);
function dropStyleDraft() {
  delete styleDrafts[A.styleArt];
  try { localStorage.setItem(STYLE_POS_KEY, JSON.stringify(styleDrafts)); } catch { /* private mode */ }
}
/* Where a place stands: its own spot (`_home`, with any saved drag), unless the
   chosen map style puts it somewhere on that picture, or a region is on the stage
   (`A.levelPlaces`), which holds some places at their spots there and draws no
   others. `_home` and `_realOff` are what let a viewer step back, and neither
   leaves this browser: the editor works from its own read of the dataset. */
export function applyOverrides() {
  const o = posOverrides();
  const level = A.levelPlaces;
  const drafted = A.styleDraft().places;
  for (const n of A.DATA.nodes) {
    const home = o[n.id] || n._home || n;
    n._home = { x: home.x, y: home.y };
    n._realOff ??= Boolean(n.off_map);
    const at = level ? level[n.id] : drafted[n.id] || A.stylePlaces?.[n.id];
    n.off_map = n._realOff || Boolean(level && !at);
    n._folded = false;
    const to = at || n._home;
    n.x = to.x; n.y = to.y;
  }
  if (level) return;               // a region's own list already left its folded places out
  // the main map: a folded region keeps the places that speak to nobody outside it
  const drawn = {};
  for (const n of A.DATA.nodes) if (!n.off_map) drawn[n.id] = { x: n.x, y: n.y };
  const hidden = A.foldedHere?.(drawn);
  if (!hidden?.size) return;
  for (const n of A.DATA.nodes) {
    if (hidden.has(n.id)) { n.off_map = true; n._folded = true; }
  }
}
/** Where a place stands on the top-level map, whatever is on the stage now. */
A.mainPlace = (n) => A.styleDraft().places[n.id] || A.stylePlaces?.[n.id] || posOverrides()[n.id] || n._home || n;
A.editMode = false;
A.setEditMode = function setEditMode(on) {
  A.editMode = !!on;
  document.body.classList.toggle('editing-map', A.editMode);
  if (A.editMode) { A.closeCard?.(); }
};
A.copyPositions = function copyPositions() {
  if (onStyleArt()) {   // in the sidecar's own shape, ready to paste into it
    const d = A.styleDraft();
    navigator.clipboard?.writeText(JSON.stringify(d, null, 2)).catch(() => {});
    return draftCount(d);
  }
  const o = posOverrides();
  const rounded = Object.fromEntries(Object.entries(o).map(
    ([id, p]) => [id, { x: +p.x.toFixed(1), y: +p.y.toFixed(1) }]));
  const txt = JSON.stringify(rounded, null, 1);
  navigator.clipboard?.writeText(txt).catch(() => {});
  return Object.keys(rounded).length;
};
A.resetPositions = function resetPositions() {
  if (onStyleArt()) dropStyleDraft();
  else localStorage.removeItem(POS_KEY);
  location.reload();
};
/* persist the moved dots server-side — permanent + shared to every viewer */
A.savePositions = async function savePositions() {
  if (onStyleArt()) {
    const d = A.styleDraft();
    if (!draftCount(d)) return { saved: 0 };
    const r = await postJSON(`api/v2/admin/map-art/${encodeURIComponent(A.styleArt)}/layout`, d);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    const res = await r.json();
    dropStyleDraft();   // the sidecar holds them now
    A.useMaps?.(res.maps || []);
    return { ...res, style: A.styleLabel || 'this map style' };
  }
  const o = posOverrides();
  if (!Object.keys(o).length) return { saved: 0 };
  const r = await postJSON('api/v2/positions', o);   // carries the write proof (config.js)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  const res = await r.json();
  localStorage.removeItem(POS_KEY);   // now canonical; drop the local overlay
  return res;
};

/* screen px → dataset percent, undoing the camera transform.

   🔴 Unproject FIRST. This is the edit-mode marker drag, and unlike pan or
   zoom it does not merely look wrong while tilted — it WRITES `n.x`/`n.y` into
   the dataset, so a marker dropped on a tilted table would be persisted at
   coordinates the surveyor never chose, and would look correct again the moment
   the table went flat. Flat, `unproject` is identity and this is the arithmetic
   it always was. (Arc T step two) */
function screenToPct(clientX, clientY) {
  const p = unproject(clientX, clientY);
  return {
    x: ((p.x - A.cam.x) / A.cam.k) / A.MAPW * 100,
    y: ((p.y - A.cam.y) / A.cam.k) / A.MAPH * 100,
  };
}

A.screenToPct = screenToPct;   // regions.js pins with the same reading

/* One drag in edit mode: `place` turns the pointer's percent into the spot,
   `done` keeps it once the drag ends, and only if it really moved. */
export function dragOnMap(e, el, place, done) {
  e.stopPropagation(); e.preventDefault();
  delete el.dataset.dragged;
  el.setPointerCapture(e.pointerId);
  el.classList.add('dragging');
  const move = (ev) => {
    const at = place(screenToPct(ev.clientX, ev.clientY));
    el.style.left = at.x + '%';
    el.style.top = at.y + '%';
    el.dataset.dragged = '1';
  };
  const up = () => {
    el.classList.remove('dragging');
    el.removeEventListener('pointermove', move);
    for (const t of DRAG_END) el.removeEventListener(t, up);
    if (el.dataset.dragged) done();
  };
  el.addEventListener('pointermove', move);
  // a drag can end without a pointerup — the browser cancels it, or the
  // capture is lost — and every ending must clean up (camera.js does the same)
  for (const t of DRAG_END) el.addEventListener(t, up);
}

/** Keep a dragged place's spot in this browser, over the one the dataset gives it. */
export function keepSpot(id, at) {
  const o = posOverrides();
  o[id] = { x: at.x, y: at.y };
  try { localStorage.setItem(POS_KEY, JSON.stringify(o)); } catch { /* private mode: the move still draws */ }
}
