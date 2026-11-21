/* THE MAP EDITOR's panel (2026-11-20; owner: "on the atlas drop down, lets
   change map to 'map editor', and take all the map editing settings and put
   it there. have it roll out and look kind of like index does").

   `#map-drawer` is the Index's panel mirrored: it hangs under THE ATLAS at the
   band's left end and unfurls downward (atlas.css). ATLAS ▾ MAP EDITOR shows
   the map and opens it; the same item, Escape, THE ATLAS itself, a scene
   and any other view close it (its × became the side arrow, 2026-11-20). It
   does not roll up when the mouse
   leaves, as the Index does: MOVE PLACES is used with the pointer out on the
   map, and Save to map must still be there after the drag.

   What it holds was Settings › THE MAP (the background and tilt, the standard
   words, MOVE PLACES), whose controls keep their ids and are still wired where
   they always were (table.js, words.js, ui.js), plus ZOOM MAPS, which is this
   file's: every region of the picture on screen, each shown or hidden for
   this viewer (regions.js keeps that choice), and the way to add or remove
   one. The Desk adds its own door to every record below (editor/index.js).

   A control that writes to the map is drawn for everyone and is off, with one
   plain line saying why, wherever this viewer may not write: a look-only
   Atlas used to show Save to map live and answer the press with a refusal.

   ui.js asks for the panel with an `atlas:map-editor` event (detail.open:
   true, false, or absent to switch), so nothing imports this file and it can
   be loaded after regions.js, whose list it reads. */

import { A, $, esc, canAdminWrite } from './config.js';
import { setZoomMapShown, zoomMaps } from './regions.js';

const drawer = $('map-drawer');
const zoomList = $('med-zoom');
const WHY = 'Off here: it needs an admin, on an Atlas that takes changes.';

export const mapEditorOpen = () => Boolean(drawer?.classList.contains('open'));

/** Open, close, or (with no word) switch the panel. It only ever stands over
    the map: asked for from another view or a phone, it stays shut. */
export function toggleMapEditor(open) {
  if (!drawer) return false;
  let will = open ?? !mapEditorOpen();
  if (will && (A.PHONE || A.VIEW !== 'map')) will = false;
  if (will === mapEditorOpen()) return will;
  if (will) {
    A.buildCartographer?.();   // the map style list: a cheap fetch, fresh per opening (table.js)
    drawZoomMaps();
    drawNames();
  }
  drawer.classList.toggle('open', will);
  drawer.setAttribute('aria-hidden', String(!will));
  // the zoom column, the region's crumbs and a left-hand card stand clear (atlas.css)
  document.body.classList.toggle('editor-open', will);
  if (will) drawer.querySelector('.sp-sub, input, button')?.focus({ preventScroll: true });
  else if (drawer.contains(document.activeElement)) document.activeElement.blur();
  // the views' menu marks MAP EDITOR only while this is out (views.js)
  dispatchEvent(new CustomEvent('atlas:map-editor-state', { detail: { open: will } }));
  return will;
}

/* ── ZOOM MAPS ───────────────────────────────────────────────────────────── */

function drawZoomMaps() {
  if (!zoomList) return;
  const rows = zoomMaps();
  const had = zoomList.contains(document.activeElement) ? document.activeElement.dataset.zoom : null;
  if (!rows.length) {
    zoomList.innerHTML = '<div class="sp-hint">This map has no zoom maps.</div>';
  } else {
    zoomList.innerHTML = rows.map((r) => `
      <label class="sp-row med-zoom-row${r.reachable ? '' : ' med-zoom-off'}" style="--med-depth:${Math.min(r.depth, 4)}">
        <span class="med-zoom-name">${esc(r.name)}${
          r.byDefault ? '' : ' <span class="med-zoom-tag">hidden to start with</span>'}${
          r.reachable ? '' : ' <span class="med-zoom-tag">inside a hidden one</span>'}</span>
        <input type="checkbox" data-zoom="${esc(r.id)}"${r.on ? ' checked' : ''}
               aria-label="Show ${esc(r.name)}">
      </label>`).join('');
  }
  if (had) zoomList.querySelector(`[data-zoom="${CSS.escape(had)}"]`)?.focus({ preventScroll: true });
  paintZoomDoor();
}

/** Add or remove: the Desk's REGIONS section, for an admin, on the realm's
    own map. A map style's regions are written in its style file, which
    nothing here edits; a look-only Atlas edits nothing at all. */
function paintZoomDoor() {
  const add = $('med-zoom-add');
  const why = $('med-zoom-why');
  if (!add || !why) return;
  let reason = '';
  if (!canAdminWrite() || !A.editorReady?.()) reason = WHY;
  else if (A.onOtherStyle?.()) reason = 'Off on this map style: its zoom maps are written in the style\'s own file.';
  add.disabled = Boolean(reason);
  why.textContent = reason;
  why.hidden = !reason;
}

zoomList?.addEventListener('change', (e) => {
  const box = e.target;
  if (!(box instanceof HTMLInputElement) || !box.dataset.zoom) return;
  setZoomMapShown(box.dataset.zoom, box.checked);   // redraws the map, and this list through its event
});
$('med-zoom-add')?.addEventListener('click', async () => {
  if ($('med-zoom-add').disabled) return;
  const { openDesk } = await import('./editor/panel.js');
  toggleMapEditor(false);
  openDesk('regions');
});
addEventListener('atlas:zoom-maps', () => { if (mapEditorOpen()) drawZoomMaps(); });

/* ── what may not be written here says so ─────────────────────────────── */

function paintWrites() {
  const save = $('sp-save');
  const why = $('sp-save-why');
  if (!save || !why) return;
  const off = !canAdminWrite();
  save.disabled = off;
  why.textContent = off ? `Save to map is off here: it needs an admin, on an Atlas that takes changes. Your moves still stay in this browser.` : '';
  why.hidden = !off;
}
paintWrites();

/* ── opening and closing ─────────────────────────────────────────────────── */

addEventListener('atlas:map-editor', (e) => toggleMapEditor(e.detail?.open));
/* ── which side it hangs on (2026-11-20; owner: "change the X in the top
   right of the map editor menu to be an arrow, so you can slide it to the left
   or right side. if on the right side, and index is selected it will go over
   the top of it"). The arrow points where the panel will go; the side is kept
   in this browser. On the right it hangs where THE INDEX does, and the Index,
   opened, lies over it (atlas.css). */
const SIDE_KEY = 'atlas-editor-side';
const sideBtn = $('med-side');
function paintSide(right) {
  document.body.classList.toggle('editor-right', right);
  if (!sideBtn) return;
  const words = right ? 'Move to the left side' : 'Move to the right side';
  sideBtn.title = words;
  sideBtn.setAttribute('aria-label', words);
}
let sideRight = false;
try { sideRight = localStorage.getItem(SIDE_KEY) === 'right'; } catch { /* the left, as it was */ }
paintSide(sideRight);
sideBtn?.addEventListener('click', () => {
  sideRight = !sideRight;
  try { localStorage.setItem(SIDE_KEY, sideRight ? 'right' : 'left'); } catch { /* this visit only */ }
  paintSide(sideRight);
});

/* ── the sky's and the depths' names (2026-11-20; owner: "a way to change the
   name for the sky island/depths") ─────────────────────────────────────────
   The place above the map and the place below it are the networks `sky` and
   `depths`: their headings, the map's labels and the Index say those
   networks' names (ui.js nameRegionHeads). So the two boxes here rename the
   two networks, with the editing API's own upsert, and everything that says
   the name follows from the map's refresh. A map with no such network has
   that box off. */
const NAMED = [['med-sky', 'sky'], ['med-depths', 'depths']];
const NAMES_SAY = $('med-names-say')?.textContent || '';
async function drawNames() {
  const wrap = $('med-names');
  if (!wrap) return;
  const can = canAdminWrite() && Boolean(A.editorReady?.());
  wrap.hidden = !can;
  if (!can) return;
  $('med-names-say').textContent = NAMES_SAY;
  try {
    const { Editor } = await import('./editor/index.js');
    await Editor.load();
    const zones = Array.isArray(Editor.data?.zones) ? Editor.data.zones : [];
    for (const [id, zone] of NAMED) {
      const z = zones.find((x) => x && x.id === zone);
      $(id).value = z ? String(z.name || '') : '';
      $(id).disabled = !z;
      $(id).placeholder = z ? '' : `This map has no network with the id ${zone}`;
    }
  } catch { /* the boxes stay as they were; Save says what went wrong */ }
}
$('med-names-save')?.addEventListener('click', async () => {
  const go = $('med-names-save');
  const say = $('med-names-say');
  go.disabled = true;
  try {
    const { Editor } = await import('./editor/index.js');
    await Editor.load();
    const zones = Array.isArray(Editor.data?.zones) ? Editor.data.zones : [];
    const ops = [];
    for (const [id, zone] of NAMED) {
      const z = zones.find((x) => x && x.id === zone);
      const name = $(id).value.trim().replace(/\s+/g, ' ');
      if (!z || $(id).disabled) continue;
      if (!name) { say.textContent = 'A name cannot be blank.'; $(id).focus(); return; }
      if (name !== z.name) ops.push({ op: 'upsert', section: 'zones', id: zone, body: { name } });
    }
    if (!ops.length) { say.textContent = 'Nothing changed.'; return; }
    await Editor.apply(ops, 'the names of the sky and the depths (MAP EDITOR)');
    say.textContent = NAMES_SAY;
    A.showToast?.('The names are saved.');
    drawNames();
  } catch (err) {
    say.textContent = `Not saved: ${err.message || err}`;
  } finally {
    go.disabled = false;
  }
});

// another view has no map under it
addEventListener('atlas:view', (e) => { if (e.detail?.view !== 'map') toggleMapEditor(false); });
/* Escape closes it. Heard here and not in the map's own Escape (camera.js),
   which is not read while the keyboard is in one of this panel's fields; the
   key is left to travel on, so a card or a scene closes with it as before. */
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !mapEditorOpen()) return;
  toggleMapEditor(false);
});
