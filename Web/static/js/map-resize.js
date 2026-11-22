
import { A, $, esc, canAdminWrite } from './config.js';
import { clampRect, rectOnScreen } from './region-model.js';
import { frameRegions } from './regions.js';

const MIN = 2;
const box = $('med-resize');
const sayEl = $('med-resize-say');
const SAY = sayEl?.textContent || '';

let layer = null;
let raf = 0;
let drawn = '';
let drag = null;
let pending = new Map();

const on = () => Boolean(box?.checked);
const tilted = () => document.body.classList.contains('tilted');
const mayWrite = () => canAdminWrite() && Boolean(A.editorReady?.());

function reason() {
  if (!mayWrite()) return 'Off here: it needs an admin, on an Atlas that takes changes.';
  if (A.onOtherStyle?.()) return 'Off on this map style: its zoom maps are written in the style\'s own file.';
  if (tilted()) return 'Lay the map flat first: turn off Tilt the map, under Map style.';
  return '';
}

function paintDoor() {
  if (!box || !sayEl) return;
  const why = reason();
  box.disabled = Boolean(why);
  if (why && box.checked) { box.checked = false; stop(); }
  sayEl.textContent = why || SAY;
}


function build(list) {
  layer.innerHTML = list.map((r) =>
    `<div class="mrz-box" data-id="${esc(r.id)}" tabindex="-1">` +
      `<span class="mrz-name">${esc(r.name || r.id)}</span>` +
      ['nw', 'ne', 'sw', 'se'].map((c) => `<span class="mrz-h mrz-${c}" data-c="${c}"></span>`).join('') +
    '</div>').join('');
  drawn = list.map((r) => r.id).join('|');
}

function layout() {
  if (!layer || !(A.cam && A.MAPW && A.MAPH)) return;
  const { list } = frameRegions();
  if (list.map((r) => r.id).join('|') !== drawn && !drag) build(list);
  for (const r of list) {
    const el = layer.querySelector(`.mrz-box[data-id="${CSS.escape(r.id)}"]`);
    if (!el) continue;
    const s = rectOnScreen(pending.get(r.id) || r, A.cam, A.MAPW, A.MAPH);
    Object.assign(el.style, { left: `${s.left}px`, top: `${s.top}px`, width: `${s.width}px`, height: `${s.height}px` });
  }
}

function tick() {
  if (!on()) return;
  if (tilted()) { paintDoor(); return; }
  layout();
  raf = requestAnimationFrame(tick);
}

function dragged(e) {
  const k = A.cam.k;
  const dx = ((e.clientX - drag.start.x) / (A.MAPW * k)) * 100;
  const dy = ((e.clientY - drag.start.y) / (A.MAPH * k)) * 100;
  const r = drag.rect;
  let x0 = r.x, y0 = r.y, x1 = r.x + r.w, y1 = r.y + r.h;
  if (!drag.corner) {
    const mx = Math.max(-x0, Math.min(100 - x1, dx));
    const my = Math.max(-y0, Math.min(100 - y1, dy));
    return { x: x0 + mx, y: y0 + my, w: r.w, h: r.h };
  }
  if (drag.corner.includes('w')) x0 = Math.min(x0 + dx, x1 - MIN);
  if (drag.corner.includes('e')) x1 = Math.max(x1 + dx, x0 + MIN);
  if (drag.corner.includes('n')) y0 = Math.min(y0 + dy, y1 - MIN);
  if (drag.corner.includes('s')) y1 = Math.max(y1 + dy, y0 + MIN);
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function onDown(e) {
  const el = e.target.closest?.('.mrz-box');
  if (!el || e.button !== 0) return;
  const r = frameRegions().list.find((x) => x.id === el.dataset.id);
  if (!r) return;
  e.preventDefault();
  e.stopPropagation();
  drag = { id: r.id, name: r.name || r.id, corner: e.target.dataset?.c || '', el,
    start: { x: e.clientX, y: e.clientY }, rect: { x: r.x, y: r.y, w: r.w, h: r.h } };
  el.classList.add('dragging');
  try { el.setPointerCapture(e.pointerId); } catch {   }
}

function onMove(e) {
  if (!drag) return;
  pending.set(drag.id, dragged(e));
  layout();
}

async function onUp(e) {
  if (!drag) return;
  const { id, name, el, rect: was } = drag;
  const rect = clampRect(dragged(e));
  drag = null;
  el.classList.remove('dragging');
  if (!rect || (rect.x === was.x && rect.y === was.y && rect.w === was.w && rect.h === was.h)) {
    pending.delete(id);
    return;
  }
  pending.set(id, rect);
  try {
    const { Editor } = await import('./editor/index.js');
    await Editor.load();
    await Editor.apply([{ op: 'upsert', section: 'regions', id, body: rect }],
      `${name}: its box moved or resized on the map (MAP EDITOR)`);
    A.showToast?.(`${name} is saved.`);
  } catch (err) {
    A.showToast?.(`Not saved: ${err.message || err}`);
  } finally {
    pending.delete(id);
  }
}


function start() {
  if (!layer) {
    layer = document.createElement('div');
    layer.className = 'mrz-layer';
    document.body.append(layer);
    layer.addEventListener('pointerdown', onDown);
    layer.addEventListener('pointermove', onMove);
    layer.addEventListener('pointerup', onUp);
    layer.addEventListener('pointercancel', () => {
      if (!drag) return;
      pending.delete(drag.id);
      drag.el.classList.remove('dragging');
      drag = null;
    });
  }
  drawn = '';
  layer.innerHTML = '';
  layer.classList.add('on');
  cancelAnimationFrame(raf);
  layout();
  raf = requestAnimationFrame(tick);
}

function stop() {
  cancelAnimationFrame(raf);
  drag = null;
  pending = new Map();
  layer?.classList.remove('on');
  if (box) box.checked = false;
}

box?.addEventListener('change', () => {
  paintDoor();
  if (on()) start(); else stop();
});
addEventListener('atlas:map-editor-state', (e) => { if (e.detail?.open) paintDoor(); else stop(); });
addEventListener('atlas:view', (e) => { if (e.detail?.view !== 'map') stop(); });
paintDoor();
