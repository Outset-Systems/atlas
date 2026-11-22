
import { A, $, esc, canAdminWrite } from './config.js';
import { setZoomMapShown, zoomMaps } from './regions.js';

const drawer = $('map-drawer');
const zoomList = $('med-zoom');
const WHY = 'Off here: it needs an admin, on an Atlas that takes changes.';

export const mapEditorOpen = () => Boolean(drawer?.classList.contains('open'));

export function toggleMapEditor(open) {
  if (!drawer) return false;
  let will = open ?? !mapEditorOpen();
  if (will && (A.PHONE || A.VIEW !== 'map')) will = false;
  if (will === mapEditorOpen()) return will;
  if (will) {
    A.buildCartographer?.();
    drawZoomMaps();
    drawNames();
  }
  drawer.classList.toggle('open', will);
  drawer.setAttribute('aria-hidden', String(!will));
  document.body.classList.toggle('editor-open', will);
  if (will) drawer.querySelector('.sp-sub, input, button')?.focus({ preventScroll: true });
  else if (drawer.contains(document.activeElement)) document.activeElement.blur();
  dispatchEvent(new CustomEvent('atlas:map-editor-state', { detail: { open: will } }));
  return will;
}


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
  setZoomMapShown(box.dataset.zoom, box.checked);
});
$('med-zoom-add')?.addEventListener('click', async () => {
  if ($('med-zoom-add').disabled) return;
  const { openDesk } = await import('./editor/panel.js');
  toggleMapEditor(false);
  openDesk('regions');
});
addEventListener('atlas:zoom-maps', () => { if (mapEditorOpen()) drawZoomMaps(); });


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


addEventListener('atlas:map-editor', (e) => toggleMapEditor(e.detail?.open));
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
try { sideRight = localStorage.getItem(SIDE_KEY) === 'right'; } catch {   }
paintSide(sideRight);
sideBtn?.addEventListener('click', () => {
  sideRight = !sideRight;
  try { localStorage.setItem(SIDE_KEY, sideRight ? 'right' : 'left'); } catch {   }
  paintSide(sideRight);
});

const NAMED = [['med-sky', 'upper'], ['med-depths', 'lower']];
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
  } catch {   }
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

addEventListener('atlas:view', (e) => { if (e.detail?.view !== 'map') toggleMapEditor(false); });
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !mapEditorOpen()) return;
  toggleMapEditor(false);
});
