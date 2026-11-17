/* TOPOLOGY (2026-11-17), the conductor: a view under ATLAS beside MAP,
   OVERVIEW and NODES (views.js shows `#view-topology` in the map's place).
   It replaces THE PATH, the tier scene (path.js), whose rows were one lab's
   own ids: here the heads come from the data and everything hangs below them
   by cable, then route, then parent (topology-model.js), so a map with no
   cables yet is drawn from its routes and hosts, never flat.

   It draws only what the page was given: the dataset already in memory
   (A.DATA, redacted for this viewer by the server) and the feed the page
   already polls (A.signalsFeed, for the state dots and "Watched by"). It
   asks the server for nothing of its own.

   ITS PARTS, split as NODES is (none imports this file; what they call here
   they reach through `hooks` in topology-state.js):
     topology-state.js   the shared state, the words, and the doors later
                         stages use (drawing, export, "where does it break",
                         "Show in topology"); also on `A.topology`
     topology-canvas.js  the one <svg>: cards, cables, the quieter layer
     topology-panel.js   VLANS, VIEW, LABELS, ARRANGE AND EXPORT, LEGEND
     topology-model.js   every rule and every sum, with no DOM

   OPENING IT: the views' menu and the phone's strip; `?view=topology`; and
   `?view=topology&at=<place id>`, which opens it centred on that place with
   its way up to the head lit. `A.openTopology(id)` does the same from the
   page (the place card's Topology button; NODES' "Show in topology").

   THE HANDS: drag (or a finger) pans, the wheel and a pinch zoom, Fit fits.
   The arrow keys pan the canvas; on a card they move to the nearest card that
   way (one card at a time takes Tab: a roving tabindex). Enter or Space on a
   card, or a press, opens the place's own card (a stub shows its name, kind
   and note; a folded group opens; Shift and an arrow pans from a card; + and
   - zoom, 0 fits). Ctrl+F inside the view goes to find, and
   Enter there steps through what it found. Escape lets go of what is lit and
   selected. Nothing here edits: drawing is a later stage of its own. */

import { A, $, esc, REDUCED } from './config.js';
import { parsePlace, parseView } from './views-model.js';
import * as M from './topology-model.js';
import * as S from './topology-state.js';
import { T, t, hooks, stubWords, writePrefs, emitPointer } from './topology-state.js';
import * as C from './topology-canvas.js';
import { buildPanel, drawPanel } from './topology-panel.js';
import './topology-draw.js';
import './topology-export.js';
import './topology-diagnose.js';

const query = new URLSearchParams(location.search);
/** A place to open on, from `?view=topology&at=<id>` or A.openTopology. */
let pendingAt = parseView(query.get('view')) === 'topology' ? parsePlace(query.get('at')) : null;

const el = {};
const W = M.CARD_W;
const H = M.CARD_H;

/* ── the frame: built once ────────────────────────────────────────────────── */

function frame() {
  if (el.sheet) return true;
  let main = $('view-topology');
  if (!main) {
    // a page from an older template (a cache that outlived a deploy)
    main = document.createElement('main');
    main.className = 'atlas-view';
    main.id = 'view-topology';
    main.dataset.view = 'topology';
    main.hidden = A.VIEW !== 'topology';
    ($('view-nodes') || $('viewport'))?.after(main);
  }
  let sheet = $('topology-sheet');
  if (!sheet) {
    sheet = document.createElement('section');
    sheet.className = 'tp-sheet';
    sheet.id = 'topology-sheet';
    main.prepend(sheet);
  }
  sheet.innerHTML =
    '<div class="tp-head">' +
    `<h2 class="tp-title">${esc(t('view_topology'))}</h2>` +
    `<p class="tp-sub">${esc(t('tp_sub'))}</p>` +
    '<div class="tp-find" role="search">' +
    `<input type="search" class="tp-find-input" placeholder="${esc(t('tp_find'))}" aria-label="${esc(t('tp_find'))}" autocomplete="off" spellcheck="false">` +
    '<span class="tp-find-count" aria-live="polite"></span></div>' +
    `<button type="button" class="tp-btn tp-panel-toggle" aria-expanded="false" aria-controls="tp-panel">${esc(t('tp_panel'))}</button>` +
    '</div>' +
    '<div class="tp-body">' +
    `<aside class="tp-panel" id="tp-panel" aria-label="${esc(t('tp_panel'))}"></aside>` +
    '<div class="tp-stage"><p class="tp-empty" hidden></p><div class="tp-note" role="note" hidden></div></div>' +
    '</div>' +
    `<p class="tp-keys">${esc(t('tp_keys'))}</p>`;
  Object.assign(el, {
    main, sheet,
    find: sheet.querySelector('.tp-find-input'), count: sheet.querySelector('.tp-find-count'),
    toggle: sheet.querySelector('.tp-panel-toggle'), panel: sheet.querySelector('.tp-panel'),
    stage: sheet.querySelector('.tp-stage'), empty: sheet.querySelector('.tp-empty'), note: sheet.querySelector('.tp-note'),
  });
  const svg = C.build(el.stage);
  buildPanel(el.panel);
  wire(svg);
  return true;
}

/* ── the data ─────────────────────────────────────────────────────────────── */

/** Read the dataset in memory again; `force` even when it is the same one. */
function load(force = false) {
  const data = A.DATA;
  if (!data || (!force && data === T.data)) return;
  T.data = data;
  T.graph = M.buildGraph(data);
  reshow();
}

/* The shape the pieces are packed toward (2026-11-17): the stage's own, read
   the first time it has a size and then held, so a window resized or a
   redraw does not reshuffle the cards; Re-arrange and a change of view read
   it again. Null while the stage has no size (the default, 16:10, is used). */
let heldRatio = null;
let arrangedFor = null;
function stageRatio() {
  const { w, h } = C.size();
  return w > 0 && h > 0 ? Math.round((w / h) * 100) / 100 : null;
}
function layOut() {
  if (heldRatio === null) heldRatio = stageRatio();
  arrangedFor = heldRatio;
  T.layout = M.arrange(T.shown, heldRatio ? { ratio: heldRatio } : {});
}
/** Before the first fit: a layout made while the stage had no size is made
    again for the stage's shape. */
function layOutForStage() {
  if (T.shown && arrangedFor === null && stageRatio() !== null) layOut();
}

/** The graph on screen, from the whole one: the view, then folding. */
function reshow({ fit = false } = {}) {
  if (!T.graph) return;
  const base = T.mode === 'infra' ? M.infrastructure(T.graph) : T.graph;
  T.shown = M.foldLeaves(base, { open: T.open });
  layOut();
  if (T.selected && !T.shown.byId.has(T.selected)) T.selected = '';
  const cables = T.shown.links.filter((l) => l.layer === 'cable').length;
  const devices = T.shown.things.reduce((n, th) => n + (th.type === 'group' ? th.count : 1), 0);
  T.svg?.setAttribute('aria-label', t('tp_canvas', { n: devices, c: cables }));
  if (el.empty) {
    el.empty.hidden = T.shown.things.length > 0;
    el.empty.textContent = t('tp_empty');
  }
  if (fit || !T.fitted) fitAll(false);
  else C.draw();
  drawPanel();
}

/* ── where the canvas looks ───────────────────────────────────────────────── */

const FIT_PAD = 36;

/** Fit everything on screen, however far out that is (it may be past
    MIN_ZOOM, 2026-11-17). Gliding unless asked not to, or motion is reduced. */
function fitAll(glide = true) {
  if (!T.layout) return;
  if (!T.fitted) layOutForStage();
  const { w, h } = C.size();
  const target = M.fitView(T.layout.bounds, w, h, { pad: FIT_PAD });
  T.fitted = w > 0 && h > 0;
  if (glide) glideTo(target);
  else { T.view = target; C.draw(); }
}

/** How far out the hand may zoom: MIN_ZOOM, or the fit when that is further
    out, so a big map can be zoomed back out to the whole of it. */
function handMin() {
  if (!T.layout) return M.MIN_ZOOM;
  const { w, h } = C.size();
  return Math.min(M.MIN_ZOOM, M.fitView(T.layout.bounds, w, h, { pad: FIT_PAD }).k);
}

let glideFrame = 0;
/** Travel to a view over the design notes's medium 400ms; at once under reduced motion. */
function glideTo(target) {
  cancelAnimationFrame(glideFrame);
  if (REDUCED) { T.view = target; C.move(); return; }
  const from = { ...T.view };
  const start = performance.now();
  const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
  const step = (now) => {
    const p = Math.min(1, (now - start) / 400);
    const e = ease(p);
    // zoom in log space, so the speed of a zoom looks even
    const k = Math.exp(Math.log(from.k) + (Math.log(target.k) - Math.log(from.k)) * e);
    T.view = { k, x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e };
    C.move();
    if (p < 1) glideFrame = requestAnimationFrame(step);
  };
  glideFrame = requestAnimationFrame(step);
}

let moveFrame = 0;
const scheduleMove = () => {
  cancelAnimationFrame(moveFrame);
  moveFrame = requestAnimationFrame(() => C.move());
};

function zoomBy(factor) {
  const { w, h } = C.size();
  cancelAnimationFrame(glideFrame);
  T.view = M.zoomAt(T.view, w / 2, h / 2, factor, { min: handMin() });
  C.move();
}

/** Make sure these things are cards on screen: leave Infrastructure for a
    thing that is not gear, open the group a thing is folded into. */
function ensureShown(ids) {
  if (!T.graph) return;
  const want = ids.filter((id) => T.graph.byId.has(id));
  let changed = false;
  if (T.mode === 'infra' && want.some((id) => !T.graph.byId.get(id).infra)) { T.mode = 'all'; changed = true; }
  if (changed) reshow();
  for (let round = 0; round < 2; round++) {
    const groups = new Set(want.filter((id) => !T.shown.byId.has(id)).map((id) => M.groupHolding(T.shown, id)).filter(Boolean));
    if (!groups.size) break;
    for (const g of groups) T.open.add(g);
    reshow();
  }
}

/** Centre on a card and select it. `focus` also gives it the keyboard. */
function focusThing(id, { focus = false } = {}) {
  if (!T.graph?.byId.has(id)) return false;
  ensureShown([id]);
  const p = T.layout?.positions[id];
  if (!p) return false;
  T.selected = id;
  T.focusId = id;
  const { w, h } = C.size();
  const k = Math.max(T.view.k, Math.min(0.9, M.MAX_ZOOM));
  glideTo(M.centreOn({ k }, p.x + W / 2, p.y + H / 2, w, h));
  C.draw();
  if (focus) C.cardEl(id)?.focus({ preventScroll: true });
  return true;
}

/** Give the keyboard to a card, bringing it on screen when it is not. */
function focusCard(id) {
  const p = T.layout?.positions[id];
  if (!p) return;
  const { w, h } = C.size();
  const onScreen = M.seen({ [id]: p }, M.viewBox(T.view, w, h), -8).length > 0;
  if (!onScreen) {
    cancelAnimationFrame(glideFrame);
    T.view = M.centreOn(T.view, p.x + W / 2, p.y + H / 2, w, h);
    C.move();
  }
  C.setTabStop(id);
  C.cardEl(id)?.focus({ preventScroll: true });
}

/** Light a place's way up to its head, head first, and centre on it. */
function showPlace(id) {
  if (!T.graph?.byId.has(id)) return false;
  ensureShown([id]);
  const up = M.pathToHead(T.shown, id);
  ensureShown(up.things);
  S.lightPath([...up.things].reverse(), [...up.links].reverse());
  return focusThing(id);
}

function applyAt() {
  if (!pendingAt || !T.graph || !T.up) return;
  const id = pendingAt;
  pendingAt = null;
  showPlace(id);
}

/* ── a press ──────────────────────────────────────────────────────────────── */

function hideNote() {
  if (el.note) { el.note.hidden = true; el.note.innerHTML = ''; }
}

/** A stub has no card of its own: its name, kind and note, in a small note. */
function showNote(th) {
  const stub = (Array.isArray(T.data?.stubs) ? T.data.stubs : []).find((s) => s && s.id === th.id);
  const note = stub && typeof stub.note === 'string' ? stub.note.trim() : '';
  el.note.innerHTML = '<div class="tp-note-head">' +
    `<p class="tp-note-name">${esc(th.name)}</p>` +
    `<button type="button" class="tp-btn" data-close>${esc(t('tp_note_close'))}</button></div>` +
    `<p class="tp-note-kind">${esc(stubWords(th.kind))}</p>` +
    (note ? `<p class="tp-note-text">${esc(note)}</p>` : '');
  el.note.setAttribute('aria-label', th.name);
  el.note.hidden = false;
}

/** Open a thing: a place's own card, a stub's note, a folded group's leaves. */
function openThing(th) {
  T.selected = th.id;
  C.setTabStop(th.id);
  if (th.type === 'group') {
    T.open.add(th.id);
    hideNote();
    reshow();
    return;
  }
  if (th.type === 'stub') { showNote(th); C.draw(); return; }
  hideNote();
  C.draw();
  const node = A.DATA?.nodes?.find((n) => n && n.id === th.id);
  if (node && typeof A.openCard === 'function') A.openCard(node);
}

function pointerDetail(e, id) {
  const r = T.svg.getBoundingClientRect();
  return {
    id, thing: id ? T.shown?.byId.get(id) || null : null, event: e,
    world: { x: (e.clientX - r.left - T.view.x) / T.view.k, y: (e.clientY - r.top - T.view.y) / T.view.k },
  };
}

function press(id, e) {
  const thing = id ? T.shown?.byId.get(id) : null;
  if (emitPointer(thing ? 'card-press' : 'canvas-press', pointerDetail(e, thing ? id : ''))) return;
  if (thing) openThing(thing);
  else hideNote();
}

/* ── the hands ────────────────────────────────────────────────────────────── */

function wire(svg) {
  const pointers = new Map();
  let gesture = null;
  const at = (e) => ({ x: e.clientX, y: e.clientY });
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y) || 1;
  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

  svg.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    cancelAnimationFrame(glideFrame);
    pointers.set(e.pointerId, at(e));
    const id = e.target.closest?.('.tp-card')?.dataset.id || '';
    if (pointers.size === 1) {
      gesture = { start: at(e), view: { ...T.view }, id, moved: false };
      emitPointer(id ? 'card-down' : 'canvas-down', pointerDetail(e, id));
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      gesture = { pinch: true, d0: dist(a, b), mid0: mid(a, b), view: { ...T.view }, moved: true, min: handMin() };
    }
  });
  svg.addEventListener('pointermove', (e) => {
    if (!gesture || !pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, at(e));
    const r = svg.getBoundingClientRect();
    if (gesture.pinch) {
      if (pointers.size < 2) return;
      const [a, b] = [...pointers.values()];
      const m = mid(a, b);
      const v = M.zoomAt(gesture.view, gesture.mid0.x - r.left, gesture.mid0.y - r.top, dist(a, b) / gesture.d0, { min: gesture.min });
      T.view = { k: v.k, x: v.x + (m.x - gesture.mid0.x), y: v.y + (m.y - gesture.mid0.y) };
      scheduleMove();
      return;
    }
    const dx = e.clientX - gesture.start.x;
    const dy = e.clientY - gesture.start.y;
    if (!gesture.moved) {
      if (Math.hypot(dx, dy) < 5) return;   // a press, so far: a card's click is not eaten
      gesture.moved = true;
      try { svg.setPointerCapture(e.pointerId); } catch { /* the pointer already left */ }
      el.stage.classList.add('tp-dragging');
    }
    T.view = { ...gesture.view, x: gesture.view.x + dx, y: gesture.view.y + dy };
    scheduleMove();
  });
  const end = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (!pointers.size) el.stage.classList.remove('tp-dragging');
    if (!gesture) return;
    if (gesture.pinch) {
      // one finger left: it carries on panning from where the pinch left off
      const rest = [...pointers.values()][0];
      gesture = rest ? { start: rest, view: { ...T.view }, id: '', moved: true } : null;
      return;
    }
    if (e.type === 'pointerup' && !gesture.moved) press(gesture.id, e);
    gesture = null;
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    cancelAnimationFrame(glideFrame);
    const r = svg.getBoundingClientRect();
    const unit = e.deltaMode === 1 ? 0.05 : e.deltaMode === 2 ? 1 : 0.0015;
    T.view = M.zoomAt(T.view, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * unit), { min: handMin() });
    scheduleMove();
  }, { passive: false });

  const ARROWS = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
  svg.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const id = e.target.closest?.('.tp-card')?.dataset.id || '';
    const dir = ARROWS[e.key];
    if (dir) {
      e.preventDefault();
      if (id && !e.shiftKey) {
        const next = M.neighbour(T.layout?.positions || {}, id, dir);
        if (next) focusCard(next);
        return;
      }
      const step = 64;
      cancelAnimationFrame(glideFrame);
      T.view = {
        ...T.view,
        x: T.view.x + (dir === 'left' ? step : dir === 'right' ? -step : 0),
        y: T.view.y + (dir === 'up' ? step : dir === 'down' ? -step : 0),
      };
      C.move();
      return;
    }
    if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomBy(1.25); return; }
    if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomBy(0.8); return; }
    if (e.key === '0') { e.preventDefault(); fitAll(); return; }
    if ((e.key === 'Enter' || e.key === ' ') && id) {
      e.preventDefault();
      const th = T.shown?.byId.get(id);
      if (th && !emitPointer('card-press', { id, thing: th, event: e, world: { ...T.layout.positions[id] } })) openThing(th);
    }
  });
  svg.addEventListener('focusin', (e) => {
    const id = e.target.closest?.('.tp-card')?.dataset.id;
    if (id) T.focusId = id;
  });

  el.note.addEventListener('click', (e) => {
    if (!e.target.closest('[data-close]')) return;
    const id = T.selected;
    hideNote();
    if (id) C.cardEl(id)?.focus({ preventScroll: true });
  });

  el.toggle.addEventListener('click', () => {
    const open = !el.panel.classList.contains('open');
    el.panel.classList.toggle('open', open);
    el.toggle.setAttribute('aria-expanded', String(open));
  });

  el.find.addEventListener('input', () => runFind(0));
  el.find.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (!T.matches.length) return;
    const n = T.matches.length;
    T.match = ((T.match + (e.shiftKey ? -1 : 1)) % n + n) % n;
    showMatch();
  });

  // Escape lets go of what is lit and selected, wherever the keyboard is (a
  // page opened at `?at=` has it on the body): on the window, before
  // camera.js. A card or the glass over the view goes first (camera.js closes
  // those), a find box empties first, and a key nothing here used goes on.
  addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !T.up || A.cardOpen?.() || A.glassOpen?.()) return;
    const a = document.activeElement;
    if (a && a !== document.body && !el.main.contains(a)) return;
    if (e.target === el.find && el.find.value) { el.find.value = ''; runFind(); e.stopPropagation(); return; }
    if (!el.note.hidden) {
      const had = el.note.contains(a) ? T.selected : null;
      hideNote();
      if (had) C.cardEl(had)?.focus({ preventScroll: true });   // not left on <body>
      e.stopPropagation();
      return;
    }
    if (T.vlan !== null || T.path || T.selected || el.panel.classList.contains('open')) {
      e.stopPropagation();
      el.panel.classList.remove('open');
      el.toggle.setAttribute('aria-expanded', 'false');
      T.selected = '';
      S.clearLight();
    }
  }, true);

  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => {
      if (!T.up || !T.layout) return;
      if (!T.fitted) fitAll(false);
      else C.draw();
      applyAt();
    }).observe(el.stage);
  }
}

/* ── find ─────────────────────────────────────────────────────────────────── */

/** Find in the whole map (a thing folded away or outside Infrastructure is
    brought out when it is picked), and go to the `pick`th thing found. */
function runFind(pick = -1) {
  T.find = el.find.value;
  T.matches = T.graph ? M.find(T.graph, T.find) : [];
  T.match = T.matches.length && pick >= 0 ? pick : -1;
  if (T.match >= 0) showMatch();
  else { paintCount(); C.draw(); }
}

function showMatch() {
  focusThing(T.matches[T.match]);
  paintCount();
}

function paintCount() {
  if (!T.find.trim()) { el.count.textContent = ''; return; }
  el.count.textContent = T.matches.length
    ? t('tp_find_count', { i: T.match + 1, n: T.matches.length })
    : t('tp_find_none');
}

/* ── showing ──────────────────────────────────────────────────────────────── */

function show() {
  if (!frame()) return;
  T.up = true;
  load();
  // measure once the view has its size: the first frame after it is shown
  requestAnimationFrame(() => {
    if (!T.up) return;
    if (T.layout) {
      if (!T.fitted) fitAll(false);
      else C.draw();
    }
    applyAt();
  });
}

function hide() {
  T.up = false;
  hideNote();
  cancelAnimationFrame(glideFrame);
}

/* What the parts call back into this file for (topology-state.js `hooks`). */
Object.assign(hooks, {
  redraw: () => load(true),
  focusThing: (id) => focusThing(id),
  lit: () => {
    if (T.path) ensureShown(T.path.things);
    C.draw();
    drawPanel();
  },
  toolsChanged: () => drawPanel(),
  setVlan: (v) => {
    T.vlan = v;
    T.path = null;
    C.draw();
    drawPanel();
  },
  setMode: (mode) => {
    T.mode = mode === 'infra' ? 'infra' : 'all';
    writePrefs();
    heldRatio = null;   // a new view is packed for the stage as it is now
    reshow({ fit: true });
  },
  setLabels: () => {
    writePrefs();
    C.labels();
  },
  fit: () => fitAll(),
  rearrange: () => {
    T.open.clear();
    heldRatio = null;   // packed again for the stage as it is now
    reshow({ fit: true });
  },
});

/* The doors, for anything that cannot import a module (and for NODES' "Show
   in topology"): the same functions topology-state.js exports. */
A.topology = {
  shownGraph: S.shownGraph, positions: S.positions, svgEl: S.svgEl, redraw: S.redraw,
  lightPath: S.lightPath, clearLight: S.clearLight, focusThing: S.focusThing,
  addTool: S.addTool, onPointer: S.onPointer,
};

/** Open TOPOLOGY centred on a place, its way up to the head lit. */
A.openTopology = function openTopology(id) {
  pendingAt = parsePlace(id);
  A.closeAllScenes?.();
  if (A.VIEW === 'topology') { applyAt(); return; }
  A.setView?.('topology', { remember: true });
};

/** The feed was read (signals.js): the dots and "Watched by" follow it. */
A.paintTopology = () => { if (T.up) C.draw(); };

/* Ctrl+F inside the view is find on the canvas; anywhere else the browser's
   own find stands. */
addEventListener('keydown', (e) => {
  if (!T.up || !el.find || e.altKey || !(e.ctrlKey || e.metaKey) || String(e.key).toLowerCase() !== 'f') return;
  const a = document.activeElement;
  if (a && a !== document.body && !el.main.contains(a)) return;
  e.preventDefault();
  el.find.focus();
  el.find.select();
});

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'topology') show();
  else if (e.detail?.prev === 'topology') hide();
});
// the map was read again (a save, a refresh): draw it again while up
addEventListener('atlas:data', () => {
  if (!T.up) return;
  load();
  applyAt();
});
// the first view is chosen at import, before this file listens (views.js)
if (A.VIEW === 'topology' || document.body.dataset.view === 'topology') show();
