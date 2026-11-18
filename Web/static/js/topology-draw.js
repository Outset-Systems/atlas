/* TOPOLOGY, drawing on the canvas (2026-11-17): an admin's, on a wide screen,
   where the Desk would open (`mayDraw()`); a phone, a viewer and a look-only
   Atlas get none of it, and the server refuses the writes anyway.

   A part of the view: it reaches the canvas only through the doors in
   topology-state.js and never imports the conductor (topology.js), which
   imports it. What it adds:

   THE LAYOUT. Everyone's canvas lays the cards where an admin put them: the
   layout is read from `GET api/v2/topology/layout` each time the view is
   shown and laid over the canvas's own (`setSaved`). An admin drags a card
   to move it (or, with a card focused, Alt and an arrow; Shift for a longer
   step); the move is saved a moment after the drop, with the stamp read, and
   a 409 reads the layout again and says so. Re-arrange asks once, then
   throws the saved layout away (`guardRearrange`). A card dragged is not
   opened by the same press. Not map data: no revision, no undo.

   THE TOOLS, in ARRANGE AND EXPORT (`addTool`):
     Draw cables          toggles drawing. In it: drag from one card to another
                          (a draft line follows), or press one card and then
                          another (the keyboard's way), and a short form opens
                          beside the canvas: the port at each end (the place's
                          own ports, or Other… to type one; a stub's is typed),
                          the VLANs, PoE, kind, speed, confirmed or assumed,
                          note, and the id offered from the two ends. Labels,
                          options and help are the schema's (`Editor.ctx`).
                          Pressing a cable (or Enter on it: cables take Tab
                          while drawing) opens the same form filled in, with
                          Remove, which asks for a second press.
     Add a stub           name, kind, note; it is a card at once
     Add a place          the Desk's own Add a place form (`A.newPlace`)
     Cables from routes   offered while the map has routes with no cable
                          between their ends: a list, every row ticked, that
                          makes one `assumed` cable per row (source `hand`, no
                          ports) in one save
   Every map write is ONE batch through the editor's store (`Editor.apply`
   to the admin ops route): undo, the change log and the stamp's conflict
   rule come with it. A cable's typed port that is new for its place adds an
   `interfaces` entry in the same batch. What the server refuses is shown in
   the form, which stays open.

   WHAT IT PUTS IN THE SVG, only while drawing (so a picture taken out when
   not drawing holds none of it): `<g class="tp-draw-hits">` (a focusable
   path per cable, before the cards) and, during a drag, `<g
   class="tp-draw-draft">`. Its HTML (the message line and the forms) sits in
   the stage beside the svg, never inside it. Every rule inside the svg is in
   topology-canvas.css (its drawing block); the rest is in topology.css. */

import { A, esc, postJSON, REDUCED, refusalHTML, readJSON } from './config.js';
import * as M from './topology-model.js';
import * as Geo from './topology-geometry.js';
import * as D from './topology-draw-model.js';
import {
  T, t, tools, hooks, addTool, onPointer, svgEl, stageEl, mayDraw, setSaved, onLayout, guardRearrange,
  focusThing,
} from './topology-state.js';
import Editor, { EditorError } from './editor/store.js';

const LAYOUT = 'api/v2/topology/layout';
const SVGNS = 'http://www.w3.org/2000/svg';
/** How far a pointer moves before a press becomes a drag (the conductor's). */
const DRAG_PX = 5;
/** How long after the last move the layout is saved. */
const SAVE_MS = 600;

const S = {
  drawing: false,
  pick: null,       // end A, picked by a press: {id, type, name}
  drag: null,       // {id, thing, pointerId, x0, y0, from, moved, mode}
  swallow: false,   // the press that ends a drag is ours
  stamp: null,      // the layout's stamp, as last read or written
  pending: {},      // moves not yet sent
  timer: 0,
  saving: false,
  armed: false,     // Re-arrange asked once
  armTimer: 0,
  form: null,       // the open form
  back: null,       // where the keyboard goes when it closes
  busy: false,
  wired: null,      // the svg the listeners are on
  frame: 0,
};
const el = { msg: null };
const removers = new Map();

/* ── small things ─────────────────────────────────────────────────────────── */

const thingOf = (id) => T.shown?.byId.get(id) || T.graph?.byId.get(id) || null;
const repaint = () => {
  cancelAnimationFrame(S.frame);
  S.frame = requestAnimationFrame(() => { A.paintTopology?.(); drawHits(); });
};
const cardEl = (id) => svgEl()?.querySelector(`.tp-card[data-id="${CSS.escape(id)}"]`) || null;

/** Give the keyboard to a card once it is drawn, else to the canvas. */
function focusCard(id) {
  requestAnimationFrame(() => {
    const card = id ? cardEl(id) : null;
    (card || svgEl())?.focus({ preventScroll: true });
  });
}

/** The message line over the canvas's top corner (its words, or none). */
function say(words, kind = 'info') {
  const stage = stageEl();
  if (!stage) return;
  if (!el.msg || !stage.contains(el.msg)) {
    el.msg = document.createElement('div');
    el.msg.className = 'tp-draw-msg';
    el.msg.setAttribute('role', 'status');
    el.msg.setAttribute('aria-live', 'polite');
    stage.append(el.msg);
  }
  const text = words || (S.drawing ? t(S.pick ? 'tp_draw_pick' : 'tp_draw_on', { name: S.pick?.name || '' }) : '');
  el.msg.textContent = text;
  el.msg.dataset.kind = kind;
  el.msg.hidden = !text;
}

/* ── the layout ───────────────────────────────────────────────────────────── */

let firstLayout = true;

/** Read the layout and lay it over the canvas. `fit` once, the first time
    cards come back, since the first Fit was made without them. */
async function loadLayout() {
  let body = null;
  try {
    const res = await fetch(LAYOUT, { headers: { Accept: 'application/json' } });
    if (!res.ok) return;
    body = await res.json();
  } catch { return; }
  S.stamp = typeof body?.stamp === 'string' ? body.stamp : null;
  const cards = body?.cards && typeof body.cards === 'object' ? body.cards : {};
  const some = Object.keys(cards).length > 0;
  const first = firstLayout;
  firstLayout = false;
  if (!some && !T.saved) return;
  setSaved(some ? { ...cards } : null);
  if (!T.up) return;
  if (first && some) hooks.fit?.();
  else repaint();
}

/** Send what moved, one save at a time, with the stamp last seen. */
async function flush() {
  clearTimeout(S.timer);
  if (S.saving || !Object.keys(S.pending).length) return;
  const cards = S.pending;
  S.pending = {};
  S.saving = true;
  try {
    // keepalive: a move made just before the page goes is still sent
    const res = await postJSON(LAYOUT, { cards, expect: S.stamp }, { keepalive: true });
    const body = await readJSON(res);
    if (res.ok) {
      S.stamp = body?.stamp || S.stamp;
    } else if (res.status === 409) {
      S.pending = {};
      say(t('tp_layout_conflict'), 'warn');
      await loadLayout();
    } else {
      say(t('tp_layout_failed', { why: body?.error || `${res.status}` }), 'bad');
    }
  } catch (err) {
    say(t('tp_layout_failed', { why: err.message || String(err) }), 'bad');
  } finally {
    S.saving = false;
    if (Object.keys(S.pending).length) S.timer = setTimeout(flush, SAVE_MS);
  }
}

/** Keep a card where it was put: on screen now, saved a moment later. */
function keep(id, corner) {
  const p = D.clampPoint(corner);
  setSaved({ ...(T.saved || {}), [id]: p });
  S.pending[id] = p;
  clearTimeout(S.timer);
  S.timer = setTimeout(flush, SAVE_MS);
  repaint();
}

/* Re-arrange: asks once while there is a saved layout, then throws it away. */
guardRearrange(() => {
  if (!mayDraw() || !T.saved || !Object.keys(T.saved).length) return true;
  if (!S.armed) {
    S.armed = true;
    say(t('tp_rearrange_ask'), 'warn');
    clearTimeout(S.armTimer);
    S.armTimer = setTimeout(() => { S.armed = false; say(''); }, 8000);
    return false;
  }
  S.armed = false;
  clearTimeout(S.armTimer);
  clearTimeout(S.timer);
  S.pending = {};
  setSaved(null);
  postJSON(LAYOUT, { cards: {}, replace: true, expect: S.stamp })
    .then(async (res) => {
      const body = await readJSON(res);
      if (res.ok) { S.stamp = body?.stamp || S.stamp; say(t('tp_rearranged')); }
      else if (res.status === 409) { say(t('tp_layout_conflict'), 'warn'); await loadLayout(); }
      else say(t('tp_layout_failed', { why: body?.error || `${res.status}` }), 'bad');
    })
    .catch((err) => say(t('tp_layout_failed', { why: err.message || String(err) }), 'bad'));
  return true;
});

/* ── the pointer ──────────────────────────────────────────────────────────── */

const movable = (th) => th && (th.type === 'place' || th.type === 'stub');

onPointer((kind, detail) => {
  if (kind === 'canvas-down') {
    S.drag = null;   // a drag whose pointer never came up is over
    return false;
  }
  if (kind === 'card-down') {
    S.swallow = false;
    const ev = detail.event;
    if (!mayDraw() || !movable(detail.thing) || S.form?.contains(document.activeElement)) return false;
    const from = T.layout?.positions?.[detail.id];
    if (!from) return false;
    S.drag = { id: detail.id, thing: detail.thing, pointerId: ev.pointerId, x0: ev.clientX, y0: ev.clientY,
      from: { ...from }, moved: false, mode: S.drawing ? 'cable' : 'move' };
    return false;
  }
  if (kind === 'card-press') {
    if (S.swallow) { S.swallow = false; return true; }
    if (!S.drawing || !mayDraw()) return false;
    pickEnd(detail.thing);
    return true;
  }
  if (kind === 'canvas-press') {
    if (S.swallow) { S.swallow = false; return true; }
    if (!S.drawing || !mayDraw()) return false;
    const hit = D.hitCable(cableGeometries(), detail.world, D.HIT / Math.max(0.3, T.view.k));
    if (hit) { openCable(hit); return true; }
    if (S.pick) { S.pick = null; T.selected = ''; say(''); repaint(); }
    return false;
  }
  return false;
});

/** Drawing's press on a card: end A, then end B. */
function pickEnd(th) {
  if (!th) return;
  if (th.type === 'group') { say(t('tp_draw_group'), 'warn'); return; }
  if (!movable(th)) return;
  if (!S.pick) {
    S.pick = { id: th.id, type: th.type, name: th.name };
    T.selected = th.id;
    say('');
    repaint();
    return;
  }
  if (S.pick.id === th.id && S.pick.type === th.type) {
    S.pick = null;
    T.selected = '';
    say('');
    repaint();
    return;
  }
  const a = S.pick;
  S.pick = null;
  openNewCable([a, { id: th.id, type: th.type, name: th.name }]);
}

/** Where the pointer is on the canvas, in its own units. */
function worldAt(e) {
  const r = svgEl().getBoundingClientRect();
  return { x: (e.clientX - r.left - T.view.x) / T.view.k, y: (e.clientY - r.top - T.view.y) / T.view.k };
}

function wire() {
  const svg = svgEl();
  const stage = stageEl();
  if (!svg || !stage || S.wired === svg) return;
  S.wired = svg;

  // On the stage, before the svg hears it: a drag that started on a card is
  // a move (or, drawing, a cable), never a pan of the canvas.
  stage.addEventListener('pointerdown', (e) => {
    if (S.drag && e.pointerId !== S.drag.pointerId) cancelDrag();   // a second finger: a pinch
  }, true);
  stage.addEventListener('pointermove', (e) => {
    const d = S.drag;
    if (!d || e.pointerId !== d.pointerId) return;
    if (e.pointerType === 'mouse' && e.buttons === 0) { cancelDrag(); return; }   // its button came up elsewhere
    e.stopPropagation();
    const dx = e.clientX - d.x0;
    const dy = e.clientY - d.y0;
    if (!d.moved) {
      if (Math.hypot(dx, dy) < DRAG_PX) return;
      d.moved = true;
      try { svg.setPointerCapture(e.pointerId); } catch { /* the pointer already left */ }
      stage.classList.add(d.mode === 'move' ? 'tp-moving' : 'tp-cabling');
    }
    if (d.mode === 'move') {
      const pos = T.layout?.positions;
      if (pos) pos[d.id] = D.clampPoint({ x: d.from.x + dx / T.view.k, y: d.from.y + dy / T.view.k });
      cancelAnimationFrame(S.frame);
      S.frame = requestAnimationFrame(() => A.paintTopology?.());
    } else {
      drawDraft(d, worldAt(e));
    }
  }, true);
  const end = (e) => {
    const d = S.drag;
    if (!d || e.pointerId !== d.pointerId) return;
    S.drag = null;
    stage.classList.remove('tp-moving', 'tp-cabling');
    clearDraft();
    if (!d.moved) return;
    try { svg.releasePointerCapture(e.pointerId); } catch { /* not held */ }
    if (e.type !== 'pointerup') { restore(d); return; }
    S.swallow = true;   // the conductor's press after this is ours
    if (d.mode === 'move') {
      keep(d.id, T.layout?.positions?.[d.id] || d.from);
      return;
    }
    const target = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.tp-card');
    const th = target ? thingOf(target.dataset.id) : null;
    if (th && th.type === 'group') { say(t('tp_draw_group'), 'warn'); return; }
    if (!movable(th) || th.id === d.id) return;
    openNewCable([{ id: d.id, type: d.thing.type, name: d.thing.name }, { id: th.id, type: th.type, name: th.name }]);
  };
  stage.addEventListener('pointerup', end, true);
  stage.addEventListener('pointercancel', end, true);

  // Alt and an arrow moves the focused card (the conductor leaves Alt alone)
  const ARROWS = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
  svg.addEventListener('keydown', (e) => {
    const dir = ARROWS[e.key];
    if (dir && e.altKey && !e.ctrlKey && !e.metaKey && mayDraw()) {
      const id = e.target.closest?.('.tp-card')?.dataset.id;
      const th = id ? thingOf(id) : null;
      const p = id ? T.layout?.positions?.[id] : null;
      if (!movable(th) || !p) return;
      e.preventDefault();
      keep(id, D.nudge(p, dir, e.shiftKey ? D.NUDGE * 4 : D.NUDGE));
      return;
    }
    const hit = e.target.closest?.('.tp-hit');
    if (hit && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      openCable(hit.dataset.link);
    }
  });
}

function cancelDrag() {
  const d = S.drag;
  S.drag = null;
  stageEl()?.classList.remove('tp-moving', 'tp-cabling');
  clearDraft();
  if (d?.moved) restore(d);
}

/** A drag that did not finish: the card goes back. */
function restore(d) {
  if (d.mode === 'move' && T.layout?.positions?.[d.id]) {
    T.layout.positions[d.id] = { ...d.from };
    repaint();
  }
}

/* ── what drawing puts in the svg ─────────────────────────────────────────── */

function worldEl() { return svgEl()?.querySelector('.tp-world') || null; }

/** Every cable on screen and where it runs: `{id, g}`, in drawing order. */
function cableGeometries() {
  const pos = T.layout?.positions;
  if (!T.shown || !pos) return [];
  // where each cable is DRAWN: the ends of the cables meeting one card are
  // spread along its edge, so the lane alone is not where such a cable runs
  // (a press on a cable beside a busy switch picked nothing, 2026-11-17)
  const drawn = Geo.cableLayout(T.shown, pos);
  const out = [];
  for (const l of T.shown.links) {
    if (l.layer !== 'cable' || !pos[l.a] || !pos[l.b]) continue;
    out.push({ id: l.id, l, g: drawn.get(l.id)?.geom || Geo.cableGeometry(pos[l.a], pos[l.b], l.lane, l.lanes) });
  }
  return out;
}

/** The cables' hit paths, while drawing: they take Tab and Enter (a press
    is picked by `hitCable`, so they never stand in a card's way). */
function drawHits() {
  const world = worldEl();
  let g = world?.querySelector(':scope > .tp-draw-hits');
  if (!S.drawing || !world) { g?.remove(); return; }
  if (!g) {
    g = document.createElementNS(SVGNS, 'g');
    g.setAttribute('class', 'tp-draw-hits');
    world.insertBefore(g, world.querySelector(':scope > .tp-cards'));
  }
  const had = document.activeElement?.closest?.('.tp-hit')?.dataset.link;
  const editing = S.form?.dataset.cable || '';
  g.innerHTML = cableGeometries().map(({ id, l, g: geo }) => {
    const a = thingOf(l.a);
    const b = thingOf(l.b);
    const label = `${t('tp_cable_edit', { id })}: ${t('tp_cable_between', {
      a: [a?.name || l.a, l.aPort].filter(Boolean).join(' '), b: [b?.name || l.b, l.bPort].filter(Boolean).join(' ') })}`;
    return `<path class="tp-hit${id === editing ? ' tp-hit-on' : ''}" d="${Geo.cablePath(geo)}" data-link="${esc(id)}" tabindex="0" role="button" ` +
      `aria-label="${esc(label)}"${id === editing ? ' aria-current="true"' : ''}><title>${esc(label)}</title></path>`;
  }).join('');
  if (had) g.querySelector(`.tp-hit[data-link="${CSS.escape(had)}"]`)?.focus({ preventScroll: true });
}

function drawDraft(d, to) {
  const world = worldEl();
  const p = T.layout?.positions?.[d.id];
  if (!world || !p) return;
  let g = world.querySelector(':scope > .tp-draw-draft');
  if (!g) {
    g = document.createElementNS(SVGNS, 'g');
    g.setAttribute('class', 'tp-draw-draft');
    g.innerHTML = '<path class="tp-draft-line"/><circle class="tp-draft-end" r="4"/>';
    world.append(g);
  }
  const x1 = p.x + M.CARD_W / 2;
  const y1 = p.y + M.CARD_H / 2;
  g.firstChild.setAttribute('d', `M${Math.round(x1)} ${Math.round(y1)}L${Math.round(to.x)} ${Math.round(to.y)}`);
  g.lastChild.setAttribute('cx', Math.round(to.x));
  g.lastChild.setAttribute('cy', Math.round(to.y));
}

function clearDraft() { worldEl()?.querySelector(':scope > .tp-draw-draft')?.remove(); }

/* ── the tools ────────────────────────────────────────────────────────────── */

function setDrawing(on) {
  S.drawing = Boolean(on) && mayDraw();
  S.pick = null;
  if (T.selected && !S.drawing) T.selected = '';
  stageEl()?.classList.toggle('tp-drawing', S.drawing);
  const tool = tools.find((x) => x.id === 'draw');
  if (tool) {
    tool.label = t(S.drawing ? 'tp_draw_stop' : 'tp_draw');
    hooks.toolsChanged?.();
  }
  say('');
  drawHits();
  repaint();
}

function offer(id, spec) {
  if (removers.has(id)) return;
  removers.set(id, addTool({ id, ...spec }));
}
function withdraw(id) {
  removers.get(id)?.();
  removers.delete(id);
}

/** The tools this viewer gets now: all of them, or none. */
function syncTools() {
  if (!mayDraw()) {
    for (const id of [...removers.keys()]) withdraw(id);
    if (S.drawing) setDrawing(false);
    closeForm(false);
    el.msg?.remove();
    el.msg = null;
    return;
  }
  wire();
  offer('draw', { label: t(S.drawing ? 'tp_draw_stop' : 'tp_draw'), title: t('tp_draw_title'),
    onPress: () => setDrawing(!S.drawing) });
  offer('add-stub', { label: t('tp_add_stub'), title: t('tp_add_stub_title'), onPress: () => openStub() });
  if (typeof A.newPlace === 'function') offer('add-place', { label: t('tp_add_place'), onPress: () => A.newPlace() });
  const lacking = T.data ? D.routesWithoutCable(T.data).length : 0;
  if (lacking) {
    offer('from-routes', { label: t('tp_from_routes'), title: t('tp_from_routes_title'), onPress: () => openRoutes() });
  } else {
    withdraw('from-routes');
  }
  const keys = stageEl()?.parentElement?.parentElement?.querySelector('.tp-keys');
  if (keys && !keys.dataset.drawKeys) {
    keys.dataset.drawKeys = '1';
    keys.textContent = `${keys.textContent} ${t('tp_draw_keys')}`;
  }
}

/* ── the forms ────────────────────────────────────────────────────────────── */

/** Read the map on disk and the schema; false (and the reason said) when
    nothing can be written. */
async function ready() {
  try {
    if (!Editor.loaded) await Editor.load(); else await Editor.reload();
  } catch (err) {
    say(t('tp_editor_failed', { why: err.message || String(err) }), 'bad');
    return false;
  }
  if (!Editor.writable()) { say(t('tp_readonly'), 'warn'); return false; }
  return true;
}

const fieldsOf = (section) => new Map((Editor.section(section)?.fields || []).map((f) => [f.name, f]));

function node(tag, cls, textContent) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (textContent !== undefined) n.textContent = textContent;
  return n;
}

/** A labelled field in the Desk's own dress, its words from the schema. */
function field(fld, control, wide = false) {
  const row = node('label', `dsk-field tp-form-field${wide ? ' tp-form-wide' : ''}`);
  row.append(node('span', 'dsk-label', fld?.label || ''), control);
  if (fld?.help) row.append(node('span', 'dsk-help', fld.help));
  return row;
}

function textBox(value = '', cls = 'dsk-input') {
  const i = node('input', cls);
  i.type = 'text';
  i.value = value;
  i.autocomplete = 'off';
  i.spellcheck = false;
  return i;
}

function selectBox(options, value) {
  const s = node('select', 'dsk-input');
  s.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  s.value = value;
  return s;
}

/** The port at one end: the place's ports and Other… to type one; a stub's
    (or a place with no ports yet) typed. Returns {el, read}. */
function portControl(fld, end, had) {
  const ports = end.type === 'place' ? D.portsOf(Editor.data, end.id) : [];
  const typed = textBox(had || '', 'dsk-input dsk-mono');
  typed.placeholder = t('tp_port_type');
  if (!ports.length) {
    return { el: field({ ...fld, label: `${fld?.label || ''} (${end.name})` }, typed, true), read: () => typed.value.trim() };
  }
  const OTHER = '\u0000other';
  const known = !had || ports.includes(had);
  const pick = selectBox([['', ''], ...ports.map((p) => [p, p]), [OTHER, t('tp_port_other')]], known ? (had || '') : OTHER);
  pick.classList.add('dsk-mono');
  typed.hidden = known;
  pick.addEventListener('change', () => {
    typed.hidden = pick.value !== OTHER;
    if (!typed.hidden) typed.focus();
  });
  const box = node('span', 'tp-port');
  box.append(pick, typed);
  return {
    el: field({ ...fld, label: `${fld?.label || ''} (${end.name})` }, box, true),
    read: () => (pick.value === OTHER ? typed.value.trim() : pick.value),
  };
}

/** Put the form beside the canvas; Escape and Cancel close it. */
function showForm(form, back) {
  closeForm(false);
  S.back = back;
  S.form = form;
  form.classList.add('tp-form');
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeForm(); }
  });
  stageEl()?.append(form);
  drawHits();
  if (!REDUCED) form.classList.add('tp-form-in');
  form.querySelector('input:not([hidden]), select, button')?.focus();
}

/** Take the form away; the keyboard goes where it came from. */
function closeForm(refocus = true) {
  const form = S.form;
  S.form = null;
  if (!form) return;
  form.remove();
  drawHits();
  const back = S.back;
  S.back = null;
  if (refocus) (typeof back === 'function' ? back : () => svgEl()?.focus({ preventScroll: true }))();
}

/** Back to a tool's button, drawn again since (the panel redraws). */
const toTool = (id) => () => {
  const b = document.querySelector(`.tp-panel [data-tool="${CSS.escape(id)}"]`);
  if (b) b.focus(); else svgEl()?.focus({ preventScroll: true });
};

function problemsBox() {
  const box = node('div', 'tp-form-problems');
  box.setAttribute('aria-live', 'polite');
  return box;
}

/** The server's words for what it refused (or ours), inside the form. */
function showProblems(box, err) {
  if (!err) { box.innerHTML = ''; return; }
  box.innerHTML = refusalHTML(err);
}

function formBar(goLabel) {
  const bar = node('div', 'tp-form-bar');
  const go = node('button', 'dsk-btn dsk-btn-sm dsk-btn-go', goLabel);
  go.type = 'submit';
  const cancel = node('button', 'dsk-btn dsk-btn-sm', t('tp_cancel'));
  cancel.type = 'button';
  cancel.addEventListener('click', () => closeForm());
  bar.append(go, cancel);
  return { bar, go };
}

/** Write one batch through the editor's store. 'saved', 'refused' (its words
    are in the form) or 'stopped' (said on the canvas). */
async function write(ops, note, problems, go) {
  if (S.busy) return 'stopped';
  S.busy = true;
  if (go) go.disabled = true;
  try {
    await Editor.apply(ops, note);
    return 'saved';
  } catch (err) {
    if (err instanceof EditorError && err.status === 409) {
      try { await Editor.reload(); } catch { /* the next form reads it */ }
      try { await A.refreshData?.(); } catch { /* the next refresh mends it */ }
      showProblems(problems, t('tp_conflict'));
      return 'refused';
    }
    showProblems(problems, err);
    return 'refused';
  } finally {
    S.busy = false;
    if (go) go.disabled = false;
  }
}

/* a cable */

function endsOf(cable) {
  const one = (side) => {
    const stub = cable[`${side}_stub`];
    const id = typeof cable[side] === 'string' && cable[side] ? cable[side] : stub;
    const type = typeof cable[side] === 'string' && cable[side] ? 'place' : 'stub';
    return { id, type, name: thingOf(id)?.name || id };
  };
  return [one('a'), one('b')];
}

async function openNewCable(ends) {
  T.selected = '';
  say('');
  repaint();
  if (!(await ready())) return;
  cableForm(null, ends);
}

async function openCable(linkId) {
  if (!(await ready())) return;
  const cable = (Array.isArray(Editor.data?.cables) ? Editor.data.cables : []).find((c) => c && c.id === linkId);
  if (!cable) { say(t('tp_cable_gone'), 'warn'); return; }
  cableForm(cable, endsOf(cable));
}

function cableForm(cable, ends) {
  const f = fieldsOf('cables');
  const form = node('form', '');
  if (cable) form.dataset.cable = cable.id;   // its hit path is marked while it is open
  form.setAttribute('aria-label', cable ? t('tp_cable_edit', { id: cable.id }) : t('tp_cable_new'));
  form.append(node('h3', 'tp-form-title', cable ? t('tp_cable_edit', { id: cable.id }) : t('tp_cable_new')),
    node('p', 'tp-form-sub', t('tp_cable_between', { a: ends[0].name, b: ends[1].name })));
  const a = portControl(f.get('a_port'), ends[0], cable?.a_port);
  const b = portControl(f.get('b_port'), ends[1], cable?.b_port);
  const opt = (name, fallback) => {
    const fld = f.get(name);
    const options = (fld?.options || []).map((o) => [o, o]);
    const had = cable?.[name] ?? fld?.default ?? fallback;
    if (typeof had === 'string' && had && !options.some(([o]) => o === had)) options.unshift([had, had]);
    return selectBox(options, had);
  };
  const vlan = textBox(cable?.vlan ?? '', 'dsk-input dsk-mono');
  vlan.inputMode = 'numeric';
  const tagged = textBox(Array.isArray(cable?.tagged) ? cable.tagged.join(', ') : (cable?.tagged ?? ''), 'dsk-input dsk-mono');
  const poe = node('input', 'dsk-input dsk-mono');
  poe.type = 'number';
  poe.step = 'any';
  if (f.get('poe_w')?.min !== undefined) poe.min = f.get('poe_w').min;
  poe.value = cable?.poe_w ?? '';
  const kind = opt('kind', 'copper');
  const speed = textBox(cable?.speed ?? '');
  const state = opt('state', 'confirmed');
  const note = textBox(cable?.note ?? '');
  const taken = D.takenIds(Editor.data, 'cables');
  const id = textBox(cable ? cable.id : D.cableIdFor(ends[0].id, ends[1].id, taken), 'dsk-input dsk-mono');
  const problems = problemsBox();
  form.append(a.el, b.el, field(f.get('vlan'), vlan), field(f.get('tagged'), tagged), field(f.get('poe_w'), poe),
    field(f.get('kind'), kind), field(f.get('speed'), speed), field(f.get('state'), state),
    field(f.get('note'), note, true), field(f.get('id'), id), problems);
  const { bar, go } = formBar(t('tp_save'));
  form.append(bar);
  let remove = null;
  if (cable) {
    remove = node('button', 'dsk-btn dsk-btn-sm dsk-btn-warn tp-form-remove', t('tp_remove'));
    remove.type = 'button';
    bar.append(remove);
    let armed = false;
    remove.addEventListener('click', async () => {
      if (!armed) { armed = true; remove.textContent = t('tp_remove_sure'); return; }
      showProblems(problems, null);
      if (!(await ready())) return;
      const still = (Editor.data?.cables || []).some((c) => c && c.id === cable.id);
      if (!still) { closeForm(); say(t('tp_cable_gone'), 'warn'); return; }
      const out = await write([{ op: 'delete', section: 'cables', id: cable.id }], 'took a cable out on the topology', problems, go);
      if (out !== 'saved') return;
      closeForm(false);
      say(t('tp_cable_removed', { id: cable.id }));
      focusCard(ends[0].id);
    });
  }
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showProblems(problems, null);
    const values = { id: id.value, aPort: a.read(), bPort: b.read(), vlan: vlan.value, tagged: tagged.value,
      poe: poe.value, kind: kind.value, speed: speed.value, state: state.value, note: note.value };
    if (!(await ready())) return;
    const before = cable ? (Editor.data?.cables || []).find((c) => c && c.id === cable.id) || null : null;
    if (cable && !before) { closeForm(); say(t('tp_cable_gone'), 'warn'); return; }
    const defaults = { kind: f.get('kind')?.default ?? 'copper', state: f.get('state')?.default ?? 'confirmed' };
    const { ops, problems: ours } = D.cableOps(values, ends, Editor.data, before, defaults);
    if (ours.length) {
      showProblems(problems, t(ours.includes('id') ? 'tp_need_id' : 'tp_same_end'));
      (ours.includes('id') ? id : form.querySelector('select, input'))?.focus();
      return;
    }
    if (!ops.length) { closeForm(false); say(t('tp_nothing_changed')); focusCard(ends[0].id); return; }
    const out = await write(ops, cable ? 'changed a cable on the topology' : 'drew a cable on the topology', problems, go);
    if (out !== 'saved') { form.querySelector('input:not([hidden]), select')?.focus(); return; }
    const made = ops.filter((op) => op.section === 'interfaces').length;
    const name = values.id.trim();
    closeForm(false);
    say(made === 0 ? t('tp_cable_saved', { id: name })
      : t(made === 1 ? 'tp_cable_saved_port' : 'tp_cable_saved_ports', { id: name, n: made }));
    focusCard(ends[1].id);
  });
  showForm(form, () => focusCard(ends[0].id));
}

/* a stub */

async function openStub() {
  if (!(await ready())) return;
  const f = fieldsOf('stubs');
  const form = node('form', '');
  form.setAttribute('aria-label', t('tp_stub_new'));
  form.append(node('h3', 'tp-form-title', t('tp_stub_new')));
  const name = textBox('');
  const kindFld = f.get('kind');
  const kind = selectBox((kindFld?.options || []).map((o) => [o, o]), kindFld?.default || 'other');
  const note = textBox('');
  const problems = problemsBox();
  form.append(field(f.get('name'), name, true), field(kindFld, kind), field(f.get('note'), note, true), problems);
  const { bar, go } = formBar(t('tp_save'));
  form.append(bar);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showProblems(problems, null);
    const words = name.value.trim();
    if (!words) { showProblems(problems, t('tp_stub_need_name')); name.focus(); return; }
    if (!(await ready())) return;
    const taken = new Set([...D.takenIds(Editor.data, 'nodes'), ...D.takenIds(Editor.data, 'stubs')]);
    const body = { id: D.stubIdFor(words, taken), name: words, kind: kind.value };
    if (note.value.trim()) body.note = note.value.trim();
    const out = await write([{ op: 'insert', section: 'stubs', body }], 'added a stub on the topology', problems, go);
    if (out !== 'saved') { name.focus(); return; }
    closeForm(false);
    say(t('tp_stub_saved', { name: words }));
    // the map was read again by the store: the stub is a card now
    requestAnimationFrame(() => {
      if (focusThing(body.id) !== false) focusCard(body.id);
    });
  });
  showForm(form, toTool('add-stub'));
}

/* cables from routes */

const MAX_OPS = 500;

async function openRoutes() {
  if (!(await ready())) return;
  const all = D.routesWithoutCable(Editor.data);
  const rows = all.slice(0, MAX_OPS);
  const form = node('form', '');
  form.setAttribute('aria-label', t('tp_routes_head'));
  form.append(node('h3', 'tp-form-title', t('tp_routes_head')));
  const problems = problemsBox();
  if (!rows.length) {
    form.append(node('p', 'tp-form-sub', t('tp_routes_none')));
    const { bar } = formBar(t('tp_save'));
    bar.querySelector('[type="submit"]').remove();
    form.append(bar);
    showForm(form, toTool('from-routes'));
    return;
  }
  form.append(node('p', 'tp-form-sub', t('tp_routes_lead')));
  if (all.length > rows.length) form.append(node('p', 'tp-form-sub', t('tp_routes_more', { n: rows.length })));
  const list = node('ul', 'tp-route-list');
  const boxes = rows.map((r) => {
    const li = node('li', '');
    const label = node('label', 'tp-check');
    const box = node('input', '');
    box.type = 'checkbox';
    box.checked = r.wired !== false;       // a mesh or a scrape path is rarely a cable
    label.append(box, node('span', 'tp-route-names', t('tp_cable_between', { a: r.fromName, b: r.toName })),
      node('span', 'tp-route-kind', r.kind));
    li.append(label);
    list.append(li);
    return box;
  });
  form.append(list, problems);
  const { bar, go } = formBar('');
  form.append(bar);
  const count = () => {
    const n = boxes.filter((b) => b.checked).length;
    go.textContent = n === 1 ? t('tp_routes_go_one') : t('tp_routes_go', { n });
    go.disabled = n === 0;
  };
  list.addEventListener('change', count);
  count();
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showProblems(problems, null);
    const picked = rows.filter((_, i) => boxes[i].checked);
    if (!picked.length) return;
    if (!(await ready())) return;
    const ops = D.cablesFromRoutes(picked);
    const out = await write(ops, 'made cables from routes on the topology', problems, go);
    if (out !== 'saved') return;
    closeForm(false);
    say(ops.length === 1 ? t('tp_routes_made_one') : t('tp_routes_made', { n: ops.length }));
    syncTools();
    toTool('from-routes')();
  });
  showForm(form, toTool('from-routes'));
}

/* ── Escape, and when to offer the tools ──────────────────────────────────── */

// on the window, in the capture phase, before the conductor's own Escape
// (which would let go of the selection too): one step back at a time
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !T.up || !mayDraw() || A.cardOpen?.() || A.glassOpen?.()) return;
  // the keyboard elsewhere (the Desk that Add a place opened): not ours
  const a = document.activeElement;
  if (document.getElementById('desk')?.classList.contains('open')) return;
  if (a && a !== document.body && !document.getElementById('view-topology')?.contains(a)) return;
  if (S.form) { e.stopImmediatePropagation(); closeForm(); return; }
  if (S.drag) { e.stopImmediatePropagation(); cancelDrag(); return; }
  if (S.armed) { e.stopImmediatePropagation(); S.armed = false; say(''); return; }
  if (S.pick) {
    e.stopImmediatePropagation();
    const id = S.pick.id;
    S.pick = null;
    T.selected = '';
    say('');
    repaint();
    focusCard(id);
    return;
  }
  if (S.drawing) {
    e.stopImmediatePropagation();
    setDrawing(false);
    toTool('draw')();
  }
}, true);

onLayout(() => {
  if (S.drawing) {
    cancelAnimationFrame(S.frame);
    S.frame = requestAnimationFrame(drawHits);
  }
});

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'topology') {
    loadLayout();
    requestAnimationFrame(syncTools);
  } else if (e.detail?.prev === 'topology') {
    clearTimeout(S.timer);
    flush();
    if (S.drawing) setDrawing(false);
    closeForm(false);
  }
});
addEventListener('atlas:data', () => {
  if (!T.up) return;
  requestAnimationFrame(syncTools);
});
let resizeFrame = 0;
addEventListener('resize', () => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => { if (T.up) syncTools(); });
});
// a move not yet sent goes before the page does
addEventListener('pagehide', () => {
  if (Object.keys(S.pending).length) flush();
});
// the first view is chosen before this file listens (views.js)
if (A.VIEW === 'topology' || document.body.dataset.view === 'topology') {
  loadLayout();
  requestAnimationFrame(syncTools);
}
