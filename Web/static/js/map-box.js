/* THE MAP EDITOR's DRAW A BOX (2026-11-20; owner: "in map editor a way to
   draw a box to create a zoom map and/or location").

   Press Draw, drag a rectangle over the map, name it, and choose what the
   box is:

     a LOCATION   the hardware standing inside the box is told that name
                  (location-set-model.js boxTargets: a racked machine is
                  answered by its rack, the whole rack; a guest by its host;
                  a network place that is not hardware is left alone). A
                  location has no shape of its own on the map: the box is
                  only how the places are picked.
     a ZOOM MAP   the box becomes a region (regions.js): zoom into it and its
                  detailed map takes over. A region needs a detailed map, so
                  one is picked from the gallery (Every record › Map art is
                  where one is uploaded). Drawn inside a zoom map, the new
                  one sits on that map.
     or both, in one save.

   While a box is being drawn or named a layer lies over the map, under the
   editor's panel, so the map holds still and the box stays where it was
   drawn. The rectangle is read on the flat map: on a tilted table the box
   taken is the one that holds everything the drawn one covers. Escape, or
   Cancel, puts it all away.

   Off, saying why, for anyone who may not write. The zoom map half is off on
   a map style, whose zoom maps are written in the style's own file. */

import { A, CFG, $, esc, canAdminWrite } from './config.js';
import { unproject } from './project.js';
import { clampRect } from './region-model.js';
import { boxContext } from './regions.js';
import { boxOps, boxTargets, knownLocations, placesInside, regionId, touchWords } from './location-set-model.js';

const WHY = 'Off here: it needs an admin, on an Atlas that takes changes.';
const MIN_PX = 14;   // a smaller drag is a slip of the hand, not a box

const fallback = () => CFG.THEME?.text?.rack_location || '';
const mayWrite = () => canAdminWrite() && Boolean(A.editorReady?.());

let layer = null;      // the sheet over the map while a box is drawn or named
let rectEl = null;     // the box on it
let drag = null;       // {x, y} where the pointer went down
let box = null;        // {rect, level, ids, store, targets, skipped, images}

/* ── the layer and the drag ──────────────────────────────────────────────── */

function buildLayer() {
  if (layer) return;
  layer = document.createElement('div');
  layer.className = 'mbx-layer';
  layer.innerHTML = '<div class="mbx-rect" hidden></div><div class="mbx-say" role="status">Drag a box over the map. Esc cancels.</div>';
  rectEl = layer.firstElementChild;
  document.body.append(layer);
  layer.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    drag = { x: e.clientX, y: e.clientY };
    try { layer.setPointerCapture(e.pointerId); } catch { /* the drag still works inside the layer */ }
    hideForm();
    paintRect(e.clientX, e.clientY);
  });
  layer.addEventListener('pointermove', (e) => { if (drag) paintRect(e.clientX, e.clientY); });
  layer.addEventListener('pointerup', (e) => {
    if (!drag) return;
    const from = drag;
    drag = null;
    taken(from, { x: e.clientX, y: e.clientY });
  });
  layer.addEventListener('pointercancel', () => { drag = null; rectEl.hidden = true; });
  // the wheel would zoom the map out from under the box
  layer.addEventListener('wheel', (e) => e.preventDefault(), { passive: false });
}

function paintRect(x, y) {
  const left = Math.min(drag.x, x), top = Math.min(drag.y, y);
  rectEl.hidden = false;
  Object.assign(rectEl.style, { left: `${left}px`, top: `${top}px`,
    width: `${Math.abs(x - drag.x)}px`, height: `${Math.abs(y - drag.y)}px` });
}

/** A screen rectangle as a rectangle on the map on the stage, in its percent. */
function toMap(a, b) {
  if (!(A.cam && A.MAPW && A.MAPH)) return null;
  const corners = [[a.x, a.y], [b.x, a.y], [a.x, b.y], [b.x, b.y]].map(([sx, sy]) => {
    const p = unproject(sx, sy);
    return { x: ((p.x - A.cam.x) / (A.MAPW * A.cam.k)) * 100, y: ((p.y - A.cam.y) / (A.MAPH * A.cam.k)) * 100 };
  });
  const xs = corners.map((c) => c.x), ys = corners.map((c) => c.y);
  const x = Math.min(...xs), y = Math.min(...ys);
  return clampRect({ x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y });
}

async function taken(a, b) {
  if (Math.abs(b.x - a.x) < MIN_PX || Math.abs(b.y - a.y) < MIN_PX) { rectEl.hidden = true; return; }
  const rect = toMap(a, b);
  if (!rect) { rectEl.hidden = true; say('That box is off the map. Draw it over the map.'); return; }
  const ctx = boxContext();
  const ids = placesInside(ctx.spots, rect);
  let store;
  try {
    ({ Editor: store } = await import('./editor/index.js'));
    await store.load();
  } catch (err) {
    say(`The map could not be read: ${err.message || err}`);
    return;
  }
  let images = [];
  try { images = ((await store.mapArt()).images || []).map((i) => i?.name).filter(Boolean); } catch { /* no gallery: the zoom half says so */ }
  const { targets, skipped } = boxTargets(store.data, fallback(), ids);
  box = { rect, level: ctx.level, ids, store, targets, skipped, images };
  hint('Name the box in the panel, or drag again.');
  showForm();
}

/* ── the form, in the panel ──────────────────────────────────────────────── */

const DRAG_HINT = 'Drag a box over the map. Esc cancels.';
const hint = (text) => { const el = layer?.querySelector('.mbx-say'); if (el) el.textContent = text; };
const say = (text) => { const m = $('mbx-msg'); if (m) m.textContent = text; };

function hideForm() {
  const form = $('mbx-form');
  if (form) form.hidden = true;
  box = null;
}

function showForm() {
  const form = $('mbx-form');
  if (!form || !box) return;
  const n = box.ids.length;
  const on = box.level ? ` on ${box.level.name}` : '';
  $('mbx-found').textContent = n === 0 ? `No place stands inside the box${on}.`
    : n === 1 ? `1 place stands inside the box${on}.` : `${n} places stand inside the box${on}.`;
  $('mbx-known').innerHTML = knownLocations(box.store.data, fallback()).map((name) => `<option value="${esc(name)}"></option>`).join('');
  $('mbx-name').value = '';

  // a location: only where the box holds hardware
  const loc = $('mbx-loc');
  loc.disabled = !box.targets.length;
  loc.checked = Boolean(box.targets.length);
  $('mbx-loc-say').textContent = box.targets.length
    ? `Tells ${touchWords(box.targets)} where ${box.targets.length === 1 ? 'it stands' : 'they stand'}.` +
      (box.skipped.length ? ` Left alone: ${box.skipped.join(', ')} (not hardware, or a guest with no host).` : '')
    : 'No hardware stands inside the box, so there is nothing to tell a location.';

  // a zoom map: the realm's own map, with a detailed map to show
  const zoom = $('mbx-zoom');
  const select = $('mbx-map');
  let off = '';
  if (A.onOtherStyle?.()) off = 'Off on this map style: its zoom maps are written in the style\'s own file.';
  else if (!box.images.length) off = 'A zoom map needs a detailed map to show. Upload one under Every record, Map art, then draw the box again.';
  zoom.disabled = Boolean(off);
  zoom.checked = false;
  select.innerHTML = box.images.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
  $('mbx-zoom-say').textContent = off || (box.level
    ? `The box opens into the detailed map you pick. It sits on ${box.level.name}.`
    : 'The box opens into the detailed map you pick when you zoom into it.');
  paintChoice();
  say('');
  form.hidden = false;
  $('mbx-name').focus({ preventScroll: true });
}

function paintChoice() {
  const wrap = $('mbx-map-wrap');
  if (wrap) wrap.hidden = !$('mbx-zoom')?.checked;
}

async function save() {
  if (!box) return;
  const name = $('mbx-name').value.trim().replace(/\s+/g, ' ');
  const asLoc = $('mbx-loc').checked && !$('mbx-loc').disabled;
  const asZoom = $('mbx-zoom').checked && !$('mbx-zoom').disabled;
  if (!asLoc && !asZoom) { say('Choose what the box is: a location, a zoom map, or both.'); return; }
  if (!name) { say('Give it a name first.'); $('mbx-name').focus(); return; }
  const { store, rect, level } = box;
  const ops = asLoc ? boxOps(store.data, box.targets, name) : [];
  if (asZoom) {
    const id = regionId(name, (store.data.regions || []).map((r) => r?.id));
    ops.push({ op: 'insert', section: 'regions', body: {
      id, name, map: $('mbx-map').value, ...(level ? { parent: level.id } : {}),
      x: rect.x, y: rect.y, w: rect.w, h: rect.h, auto: true,
    } });
  }
  if (!ops.length) { say(`Everything in the box is already at ${name}.`); return; }
  const go = $('mbx-save');
  go.disabled = true;
  try {
    const made = [asLoc && 'location', asZoom && 'zoom map'].filter(Boolean).join(' and ');
    await store.apply(ops, `${name}: a ${made} from a box drawn on the map (MAP EDITOR)`);
    stop();
    A.showToast?.(`${name} is on the map as a ${made}.`);
    dispatchEvent(new CustomEvent('atlas:zoom-maps'));   // the list above, if it grew
  } catch (err) {
    say(`Not saved: ${err.message || err}`);
  } finally {
    go.disabled = false;
  }
}

/* ── starting and stopping ───────────────────────────────────────────────── */

const drawing = () => Boolean(layer?.classList.contains('on'));

function start() {
  if (!mayWrite()) return;
  buildLayer();
  hideForm();
  rectEl.hidden = true;
  hint(DRAG_HINT);
  layer.classList.add('on');
  document.body.classList.add('box-drawing');
  $('mbx-draw')?.classList.add('on');
}

function stop() {
  drag = null;
  hideForm();
  if (rectEl) rectEl.hidden = true;
  layer?.classList.remove('on');
  document.body.classList.remove('box-drawing');
  $('mbx-draw')?.classList.remove('on');
}

function paintDoor() {
  const draw = $('mbx-draw');
  const why = $('mbx-why');
  if (!draw || !why) return;
  const off = !mayWrite();
  draw.disabled = off;
  why.textContent = off ? WHY : '';
  why.hidden = !off;
}

$('mbx-draw')?.addEventListener('click', () => { if (drawing()) stop(); else start(); });
$('mbx-save')?.addEventListener('click', save);
$('mbx-again')?.addEventListener('click', () => { hideForm(); if (rectEl) rectEl.hidden = true; hint(DRAG_HINT); });
$('mbx-cancel')?.addEventListener('click', stop);
$('mbx-zoom')?.addEventListener('change', paintChoice);
$('mbx-form')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.id === 'mbx-name') { e.preventDefault(); save(); }
});
/* Escape puts the box away first, and is not let on to the panel, which
   would close with the same press (capture: the panel's own listener is on
   the window too). */
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !drawing()) return;
  e.stopImmediatePropagation();
  stop();
}, true);
// the panel shut, or another view: nothing is left lying over the map
addEventListener('atlas:map-editor-state', (e) => { if (e.detail?.open) paintDoor(); else stop(); });
addEventListener('atlas:view', (e) => { if (e.detail?.view !== 'map') stop(); });
paintDoor();
