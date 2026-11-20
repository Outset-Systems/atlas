/* THE MAP EDITOR's panel (2026-11-20; owner: "on the atlas drop down, lets
   change map to 'map editor', and take all the map editing settings and put
   it there. have it roll out and look kind of like index does").

   `#map-drawer` is the Index's panel mirrored: it hangs under THE ATLAS at the
   band's left end and unfurls downward (atlas.css). ATLAS ▾ MAP EDITOR shows
   the map and opens it; the same item, its ×, Escape, THE ATLAS itself, a
   scene and any other view close it. It does not roll up when the mouse
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
  }
  drawer.classList.toggle('open', will);
  drawer.setAttribute('aria-hidden', String(!will));
  // the zoom column, the region's crumbs and a left-hand card stand clear (atlas.css)
  document.body.classList.toggle('editor-open', will);
  if (will) drawer.querySelector('.sp-sub, input, button')?.focus({ preventScroll: true });
  else if (drawer.contains(document.activeElement)) document.activeElement.blur();
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
$('med-close')?.addEventListener('click', () => toggleMapEditor(false));
// another view has no map under it
addEventListener('atlas:view', (e) => { if (e.detail?.view !== 'map') toggleMapEditor(false); });
/* Escape closes it. Heard here and not in the map's own Escape (camera.js),
   which is not read while the keyboard is in one of this panel's fields; the
   key is left to travel on, so a card or a scene closes with it as before. */
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !mapEditorOpen()) return;
  toggleMapEditor(false);
});
