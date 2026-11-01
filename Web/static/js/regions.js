/* Atlas — REGIONS (v1.49.0): zoom into a part of the map and
   its own, more detailed map takes over; zoom back out and you are where you
   were. Regions nest.

   The maths is region-model.js (pure, node-tested). This file is the shell:
   the frames drawn on the main map, the detailed view (the "lens") with its
   own pan and zoom, the breadcrumb, the locator, the keyboard, and the wiring
   into the rest of the Atlas through `A`.

   Two layers, two cameras. The MAIN map keeps its own camera (camera.js) and
   is left framing the rectangle you entered, underneath the lens, so leaving
   puts you back where you were. The LENS draws one region map at a time with
   a camera of its own, held on screen by `clampLens`. */

import { A, CFG, REDUCED, $, esc, canAdminWrite, zoneById, FALLBACK_HUE, DRAG_END } from './config.js';
import * as M from './region-model.js';
import { chosenStyle, refreshStyle, styleName } from './table.js';

const stage = $('stage');
const framesEl = $('region-frames');
const lens = $('region-lens');
const lensView = lens.querySelector('.rl-viewport');
const lensStage = lens.querySelector('.rl-stage');
const lensImg = lens.querySelector('.rl-map');
const lensFrames = lens.querySelector('.rl-frames');
const lensMarkers = lens.querySelector('.rl-markers');
const crumbs = lens.querySelector('.rl-crumbs');
const locator = lens.querySelector('.rl-locator');
const locImg = locator.querySelector('img');
const locBox = locator.querySelector('.rl-loc-box');
const hint = lens.querySelector('.rl-hint');
const announce = $('region-announce');

const MOVE_MS = REDUCED ? 0 : 440;
const SETTLE_MS = 260;          // the pause after a zoom before "open it?" is asked
const LEAVE_ARM_MS = 2200;      // a second zoom-out gesture at the floor within this = leave
const QUIET_MS = 220;           // the pause that makes it a second gesture, not inertia
const PAD = 28;                 // breathing room round a fitted map, px
const LABEL_ALL_AT_MOST = 5;    // up to this many places, every name shows at any zoom
const LABEL_ZOOM = 1.6;         // …beyond it, names show once zoomed this far past the fit

/* A region is a rectangle on one picture, so regions follow the art. The
   dataset's fit the realm's own map. Any other style brings its own from its
   sidecar (mapart.py), or has none: the demo's "Server room" drawn across a
   different continent was the bug this answers. */
const datasetRegions = () => (Array.isArray(A.DATA?.regions) ? A.DATA.regions : []);
let styleRegions = new Map();   // art name to its own regions, from the maps list
let realmArt = null;            // the art the dataset's regions were drawn on
const onOtherStyle = () => {
  const art = chosenStyle();
  return Boolean(art) && art !== realmArt;
};
const regions = () => (onOtherStyle() ? styleRegions.get(chosenStyle()) || [] : datasetRegions());
const regionById = (id) => regions().find((r) => r.id === id);
const nodes = () => A.DATA?.nodes || [];
const baseTitle = () => styleName() || String(A.DATA?.meta?.title || 'The map').replace(/ Atlas$/, '');
const mapUrl = (name) => {
  // bundled art lives in static/map, uploads behind /map-art — the maps list
  // says which; until it answers, try bundled first and fall back on error
  const known = A.MAPS_BY_NAME?.[name];
  return known ? known.url : `static/map/${encodeURIComponent(name)}`;
};

/* ── state ──────────────────────────────────────────────────────────────── */
const lensCam = { x: 0, y: 0, k: 1, min: 0.1, max: 6, w: 1, h: 1 };
let level = null;               // the region shown in the lens, or null (main map)
let busy = false;               // a transition is running
let leaveArmedAt = 0;
const disarmed = new Set();     // left recently: no auto-open until it is mostly out of view

/* ── the maps list (bundled vs uploaded) ─────────────────────────────────── */
async function loadMaps() {
  try {
    const r = await fetch('api/v2/maps', { cache: 'no-cache' });
    if (!r.ok) return;
    const { maps } = await r.json();
    A.MAPS_BY_NAME = Object.fromEntries(maps.map((m) => [m.name, m]));
    realmArt = maps.find((m) => m.default)?.name || null;
    styleRegions = new Map(maps.map((m) => [m.name, m.regions || []]));
    // region art is not in the gallery, so the list carries its address here
    for (const art of [...styleRegions.values()].flat()) A.MAPS_BY_NAME[art.map] ??= art;
    if (chosenStyle()) {
      refreshStyle(maps.find((m) => m.name === chosenStyle()));
      A.onStyleChange();
      followHash();              // a link may have asked before this answered
    }
  } catch { /* the bundled guess still works */ }
}

/* ── frames on the main map ─────────────────────────────────────────────── */
function frameEl(r, kind) {
  const el = document.createElement('div');
  el.className = 'rg-frame';
  el.dataset.region = r.id;
  el.style.left = r.x + '%';
  el.style.top = r.y + '%';
  el.style.width = r.w + '%';
  el.style.height = r.h + '%';
  el.innerHTML =
    `<button class="rg-tab" type="button" aria-label="Open the detailed map of ${esc(r.name)}">` +
    `<span class="rg-glyph" aria-hidden="true">⤢</span><span class="rg-name">${esc(r.name)}</span></button>`;
  el.querySelector('.rg-tab').addEventListener('click', (e) => {
    e.stopPropagation();
    enter(r.id, { from: kind });
  });
  return el;
}

function buildFrames() {
  framesEl.innerHTML = '';
  for (const r of M.childrenOf(regions(), null)) framesEl.appendChild(frameEl(r, 'main'));
  syncFrames();
}

/* Frames live in the scaled stage, so they follow the map (and the tilt) for
   free; `--rk` lets their tab and border stay a constant size on screen. */
/* Where the fixed chrome ends: the scene bar across the top, the zoom stack
   down the left. A tab is nudged out from under them (in stage units, so the
   nudge follows the zoom) — a region at the map's edge otherwise hides its
   only button under the bar. Measured on load and on resize, not per frame. */
let chromeClear = { top: 72, left: 76 };
function measureChrome() {
  const bar = $('scenes-list')?.getBoundingClientRect();
  const zoom = document.querySelector('.zoom-stack')?.getBoundingClientRect();
  chromeClear = {
    top: bar && bar.height ? bar.bottom + 8 : 72,
    left: zoom && zoom.width ? zoom.right + 10 : 76,
  };
}

/* Size and nudge the frames in `container`, drawn on a map of mapW×mapH
   under camera `cam`: a frame too small on screen shows its glyph alone, and
   a tab slides along its frame's edges until it clears the chrome — never
   past the frame (a tab outside its frame would point at nothing). */
function nudgeFrames(container, cam, mapW, mapH, clear = chromeClear) {
  for (const el of container.children) {
    const r = regionById(el.dataset.region);
    if (!r) continue;
    const box = M.rectOnScreen(r, cam, mapW, mapH);
    el.classList.toggle('rg-small', box.width < 90);
    const dx = Math.min(Math.max(0, clear.left - box.left), Math.max(0, box.width - 60)) / cam.k;
    const dy = Math.min(Math.max(0, clear.top - box.top), Math.max(0, box.height - 30)) / cam.k;
    el.style.setProperty('--tab-dx', dx + 'px');
    el.style.setProperty('--tab-dy', dy + 'px');
    el.classList.toggle('rg-nudged', dx > 0 || dy > 0);
  }
}

function syncFrames() {
  if (!framesEl.children.length) return;
  const cam = A.cam || { x: 0, y: 0, k: 1 };
  stage.style.setProperty('--rk', cam.k);
  nudgeFrames(framesEl, cam, A.MAPW || 1, A.MAPH || 1);
}
addEventListener('resize', () => { measureChrome(); syncFrames(); });
requestAnimationFrame(measureChrome);

/* ── auto-open: zoom in until a region is most of the window, then pause ── */
let prevK = null;
let zoomingIn = false;
let settleTimer = 0;

function viewOfMain() {
  return M.viewRect(A.cam, A.MAPW, A.MAPH, innerWidth, innerHeight);
}

function rearm(view, parentId) {
  for (const id of [...disarmed]) {
    const r = regionById(id);
    if (!r || (r.parent || '') !== (parentId || '') || M.coverage(view, r) < M.REARM_BELOW) disarmed.delete(id);
  }
}

function onMainMove(userMove) {
  syncFrames();
  if (level || busy || !A.cam) return;
  const k = A.cam.k;
  if (prevK !== null && userMove) {
    if (k > prevK * 1.001) zoomingIn = true;
    else if (k < prevK * 0.999) zoomingIn = false;
  }
  prevK = k;
  const view = viewOfMain();
  rearm(view, null);
  clearTimeout(settleTimer);
  if (!userMove || !zoomingIn) return;
  settleTimer = setTimeout(() => {
    if (level || busy || document.body.classList.contains('scene-open') || A.editMode) return;
    const pick = M.autoCandidate(regions(), null, viewOfMain(), (id) => !disarmed.has(id));
    if (pick) enter(pick.id, { from: 'main', auto: true });
  }, SETTLE_MS);
}

/* ── the lens ───────────────────────────────────────────────────────────── */
function applyLens(animate = false) {
  const c = M.clampLens(lensCam, lensCam.w, lensCam.h, innerWidth, innerHeight);
  lensCam.x = c.x; lensCam.y = c.y;
  lensStage.classList.toggle('rl-gliding', animate && !REDUCED);
  lensStage.style.transform = `translate(${lensCam.x}px, ${lensCam.y}px) scale(${lensCam.k})`;
  lensStage.style.setProperty('--rk', lensCam.k);
  // names on every place only when there is room for them: few places, or
  // zoomed in past the fit. Otherwise they appear on hover, focus and card.
  lens.classList.toggle('rl-labels',
    lensMarkers.children.length <= LABEL_ALL_AT_MOST || lensCam.k >= lensCam.min * LABEL_ZOOM);
  syncLocator();
  syncLensFrames();
}

function fitLens(animate) {
  const f = M.fitContain(lensCam.w, lensCam.h, innerWidth, innerHeight, PAD);
  lensCam.min = f.k;
  lensCam.max = Math.max(f.k * 6, 2);
  Object.assign(lensCam, { k: f.k, x: f.x, y: f.y });
  applyLens(animate);
}

function lensNodes(r) {
  const out = [];
  for (const n of nodes()) {
    if (n.off_map) continue;
    const p = M.placeOn(regions(), r.id, n);
    if (p) out.push({ n, p });
  }
  return out;
}

function mirrorHealth() {
  if (!level) return;
  const main = $('markers');
  for (const mk of lensMarkers.children) {
    const twin = main?.querySelector(`.mk[data-id="${CSS.escape(mk.dataset.id)}"]`);
    if (!twin) continue;
    const keep = mk.classList.contains('active');
    mk.className = twin.className.replace(/\bactive\b/g, '') + ' rl-mk' + (keep ? ' active' : '');
    for (const prop of ['--mk-hue', '--mk-glow']) {
      const v = twin.style.getPropertyValue(prop);
      if (v) mk.style.setProperty(prop, v);
    }
    mk.title = twin.title || '';
  }
}
A.paintRegionLens = mirrorHealth;

function buildLensMarkers(r) {
  lensMarkers.innerHTML = '';
  for (const { n, p } of lensNodes(r)) {
    const mk = document.createElement('div');
    mk.className = 'mk rl-mk';
    mk.dataset.id = n.id;
    mk.dataset.kind = n.kind || 'vm';
    mk.style.left = p.x + '%';
    mk.style.top = p.y + '%';
    const hue = n.hue || zoneById(n.zone)?.hue || FALLBACK_HUE;
    mk.style.setProperty('--mk-hue', hue);
    mk.style.setProperty('--mk-glow', hue + '55');
    mk.innerHTML = `<div class="mk-dot"><div class="mk-ring"></div><div class="mk-core"></div></div>` +
      `<div class="mk-label">${esc(n.name)}</div>`;
    mk.tabIndex = 0;
    mk.setAttribute('role', 'button');
    mk.setAttribute('aria-label', n.name);
    const open = () => {
      for (const m of lensMarkers.children) m.classList.toggle('active', m === mk);
      A.openCard?.(n);
    };
    mk.addEventListener('click', (e) => {
      if (mk.dataset.dragged) { delete mk.dataset.dragged; return; }
      e.stopPropagation(); open();
    });
    mk.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    mk.addEventListener('pointerdown', (e) => pinDrag(e, mk, n));
    lensMarkers.appendChild(mk);
  }
  mirrorHealth();
}

function buildLensFrames(r) {
  lensFrames.innerHTML = '';
  for (const c of M.childrenOf(regions(), r.id)) lensFrames.appendChild(frameEl(c, 'lens'));
}

/* In a region the breadcrumb is chrome too: tabs clear it as well. */
let crumbsBottom = 0;
function syncLensFrames() {
  const clear = { left: chromeClear.left, top: Math.max(chromeClear.top, crumbsBottom + 8) };
  nudgeFrames(lensFrames, lensCam, lensCam.w, lensCam.h, clear);
}

function buildCrumbs(r) {
  const chain = M.chainOf(regions(), r.id);
  const parts = [`<button type="button" class="rl-crumb" data-to="">${esc(baseTitle())}</button>`];
  chain.forEach((c, i) => {
    parts.push('<span class="rl-sep" aria-hidden="true">›</span>');
    parts.push(i === chain.length - 1
      ? `<span class="rl-crumb rl-here" aria-current="location">${esc(c.name)}</span>`
      : `<button type="button" class="rl-crumb" data-to="${esc(c.id)}">${esc(c.name)}</button>`);
  });
  crumbs.innerHTML = parts.join('');
  crumbsBottom = crumbs.getBoundingClientRect().bottom || 0;
  for (const b of crumbs.querySelectorAll('button.rl-crumb')) {
    b.addEventListener('click', () => leaveTo(b.dataset.to || null));
  }
}

function buildLocator(r) {
  const parent = r.parent ? regionById(r.parent) : null;
  locImg.src = parent ? mapUrl(parent.map) : $('map-base').getAttribute('src');
  locBox.style.left = r.x + '%';
  locBox.style.top = r.y + '%';
  locBox.style.width = r.w + '%';
  locBox.style.height = r.h + '%';
  locator.setAttribute('aria-label', `Back to ${parent ? parent.name : baseTitle()}`);
}

function syncLocator() { /* the box marks the region; it does not track the view */ }

function say(text) { announce.textContent = ''; requestAnimationFrame(() => { announce.textContent = text; }); }

let hintTimer = 0;
function showHint(text, ms = 2600) {
  hint.textContent = text;
  hint.classList.add('on');
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => hint.classList.remove('on'), ms);
}

/* Loaded is not drawable: a large map can finish downloading and still paint
   blank for several frames while it decodes, and the lens would fade in over
   an empty frame. Wait for the decode too (where the browser offers it). */
async function loadImage(url) {
  await new Promise((ok, fail) => {
    lensImg.onload = () => ok();
    lensImg.onerror = () => fail(new Error('the detailed map could not be loaded'));
    lensImg.src = url;
    if (lensImg.complete && lensImg.naturalWidth) ok();
  });
  try { await lensImg.decode?.(); } catch { /* drawn as soon as it can be */ }
}

/* Show region `r` in the lens, grown out of `box` (its frame on screen) when
   one is given. */
async function show(r, box) {
  await loadImage(mapUrl(r.map));
  lensCam.w = lensImg.naturalWidth || 2048;
  lensCam.h = lensImg.naturalHeight || 2048;
  lensStage.style.width = lensCam.w + 'px';
  lensStage.style.height = lensCam.h + 'px';
  level = r;
  writeHash(r.id);
  buildLensMarkers(r);
  buildLensFrames(r);
  buildCrumbs(r);
  buildLocator(r);
  document.body.classList.add('region-open');
  lens.hidden = false;
  lens.setAttribute('aria-label', `${r.name} — detailed map`);
  crumbsBottom = crumbs.getBoundingClientRect().bottom || 0;   // measurable only once shown
  if (box && !REDUCED) {
    // start exactly over the frame, then grow to fill the window
    Object.assign(lensCam, { k: box.width / lensCam.w, x: box.left, y: box.top });
    lensStage.style.transform = `translate(${lensCam.x}px, ${lensCam.y}px) scale(${lensCam.k})`;
    lensStage.style.setProperty('--rk', lensCam.k);
    lens.classList.remove('rl-in');
    void lens.offsetWidth;          // the start pose has to land before the move
    lens.classList.add('rl-in');
    fitLens(true);
  } else {
    lens.classList.add('rl-in');
    fitLens(false);
  }
  await wait(MOVE_MS);
  lensStage.classList.remove('rl-gliding');
}

const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

async function enter(id, { from = 'main', auto = false } = {}) {
  const r = regionById(id);
  if (!r || busy) return;
  busy = true;
  clearTimeout(settleTimer);
  try {
    let box = null;
    if (from === 'main' || !level) {
      // the main camera frames the rectangle (it waits there, under the lens).
      // A nested region opened straight from the main map (a deep link) has
      // its rectangle on its parent's map, not this one: frame the outermost.
      const outer = M.chainOf(regions(), r.id)[0] || r;
      box = M.rectOnScreen(outer, A.cam, A.MAPW, A.MAPH);
      const target = M.fitRect(outer, A.MAPW, A.MAPH, innerWidth, innerHeight, PAD);
      Object.assign(A.cam, target);
      A.apply?.(true);
      A.closeCard?.();
    } else {
      box = M.rectOnScreen(r, lensCam, lensCam.w, lensCam.h);
      A.closeCard?.();
    }
    await show(r, box);
    const back = r.parent ? regionById(r.parent)?.name : baseTitle();
    say(`${r.name}, detailed map. Press Escape or zoom out to return to ${back}.`);
    if (auto || !sessionHinted()) showHint(`Zoom out or press Esc to return to ${back}`);
  } catch (e) {
    console.warn('region:', e);
    A.showToast?.(`The detailed map of ${r.name} could not be loaded.`);
    if (!level) closeLens();
  } finally {
    busy = false;
  }
}

function sessionHinted() {
  try {
    if (sessionStorage.getItem('atlas-region-hinted')) return true;
    sessionStorage.setItem('atlas-region-hinted', '1');
  } catch { /* private mode: hint every time */ }
  return false;
}

function closeLens() {
  lens.classList.remove('rl-in');
  lens.hidden = true;
  document.body.classList.remove('region-open');
  lensMarkers.innerHTML = '';
  lensFrames.innerHTML = '';
  level = null;
  writeHash(null);
}

/* Leave to `targetId` (null = the main map), one level or several. */
async function leaveTo(targetId) {
  if (!level || busy) return;
  busy = true;
  try {
    A.closeCard?.();
    const chain = M.chainOf(regions(), level.id);
    const stop = targetId ? chain.findIndex((c) => c.id === targetId) : -1;
    const leaving = chain[stop + 1] || level;   // the child of the target we are leaving through
    disarmed.add(leaving.id);
    if (!targetId) {
      // back to the main map, framing the rectangle we came from
      const outer = chain[0];
      const target = M.fitRect(outer, A.MAPW, A.MAPH, innerWidth, innerHeight, PAD);
      Object.assign(A.cam, target);
      A.clampCam?.(); A.apply?.(false);
      prevK = A.cam.k;
      zoomingIn = false;
      if (!REDUCED) {
        const box = M.rectOnScreen(outer, A.cam, A.MAPW, A.MAPH);
        lensStage.classList.add('rl-gliding');
        lensStage.style.transform = `translate(${box.left}px, ${box.top}px) scale(${box.width / lensCam.w})`;
        lens.classList.remove('rl-in');
        await wait(MOVE_MS);
      }
      closeLens();
      say(`Back on ${baseTitle()}.`);
      return;
    }
    const target = regionById(targetId);
    lens.classList.remove('rl-in');
    await wait(REDUCED ? 0 : 180);
    await show(target, null);
    // frame the child we left, so you see where you were
    const f = M.fitRect(leaving, lensCam.w, lensCam.h, innerWidth, innerHeight, PAD);
    if (f.k > lensCam.min) { Object.assign(lensCam, f); applyLens(false); }
    say(`Back on ${target.name}.`);
  } finally {
    busy = false;
  }
}

function leaveOne() {
  if (!level) return;
  leaveTo(level.parent || null);
}
/* ── input inside the lens ──────────────────────────────────────────────── */
/* Leaving by zooming out takes TWO gestures: reaching the floor arms it,
   and only a fresh zoom-out after a pause leaves. A trackpad flick sends a
   burst of wheel events with inertia; counting those as "again" threw people
   out of a region they had only meant to see whole. */
let lastZoomAt = 0;

/* A zoom-out gesture met the floor. `fresh` = it is a new gesture, not the
   tail of the one that armed it. Returns true when it left the region. */
function floorReached(fresh) {
  const now = Date.now();
  if (leaveArmedAt && fresh && now - leaveArmedAt < LEAVE_ARM_MS) { leaveArmedAt = 0; leaveOne(); return true; }
  if (!leaveArmedAt || now - leaveArmedAt >= LEAVE_ARM_MS) {
    leaveArmedAt = now;
    const back = level.parent ? regionById(level.parent)?.name : baseTitle();
    showHint(`Zoom out again to return to ${back}`, LEAVE_ARM_MS);
  }
  return false;
}

function lensZoom(sx, sy, factor) {
  const now = Date.now();
  const gap = now - lastZoomAt;
  lastZoomAt = now;
  const { cam, atFloor } = M.zoomAround(lensCam, sx, sy, factor, lensCam.min, lensCam.max);
  Object.assign(lensCam, cam);
  applyLens(false);
  if (atFloor) { floorReached(gap > QUIET_MS); return; }   // a wheel burst is one gesture
  leaveArmedAt = 0;                                     // zoomed back in: no longer on the way out
  if (factor > 1) scheduleLensAuto();
}

let lensSettle = 0;
function scheduleLensAuto() {
  clearTimeout(lensSettle);
  lensSettle = setTimeout(() => {
    if (!level || busy || A.editMode) return;
    const view = M.viewRect(lensCam, lensCam.w, lensCam.h, innerWidth, innerHeight);
    rearm(view, level.id);
    const pick = M.autoCandidate(regions(), level.id, view, (id) => !disarmed.has(id));
    if (pick) enter(pick.id, { from: 'lens', auto: true });
  }, SETTLE_MS);
}

lensView.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (busy) return;
  lensZoom(e.clientX, e.clientY, e.deltaY < 0 ? CFG.ZOOM_WHEEL : 1 / CFG.ZOOM_WHEEL);
}, { passive: false });

/* Pointers: one drags (pan), two pinch (zoom about their midpoint, and pan
   as the midpoint moves). A pinch is ONE gesture from the second finger down
   to the first finger up, so pinching out against the floor arms "leave" once
   per pinch and a second pinch leaves — the wheel's two-gesture rule. The
   browser must not take the fingers for its own page zoom: touch-action is
   also set in atlas.css, and set here so the gesture never depends on it. */
lensView.style.touchAction = 'none';
const pointers = new Map();     // pointerId → {x, y}: every pointer down on the lens
let pinch = null;               // {startK, floorHit} while two are down

function startPinch() {
  lensDrag = null;
  lensView.classList.remove('dragging');
  clearTimeout(lensSettle);
  for (const id of pointers.keys()) { try { lensView.setPointerCapture(id); } catch { /* ok */ } }
  pinch = { startK: lensCam.k, floorHit: false };
}

function pinchMove(id, x, y) {
  const [ida, idb] = [...pointers.keys()];
  const a0 = pointers.get(ida), b0 = pointers.get(idb);
  const a1 = id === ida ? { x, y } : a0;
  const b1 = id === idb ? { x, y } : b0;
  pointers.set(id, { x, y });
  if (busy || !level) return;
  const { cam, atFloor } = M.pinchStep(lensCam, a0, b0, a1, b1, lensCam.min, lensCam.max);
  Object.assign(lensCam, cam);
  applyLens(false);
  if (atFloor) {
    if (!pinch.floorHit) {
      pinch.floorHit = true;
      if (floorReached(true)) { pinch = null; pointers.clear(); }
    }
  } else if (lensCam.k > lensCam.min * 1.02) {
    leaveArmedAt = 0;                                   // pinched back in: no longer on the way out
  }
}

function endPinch() {
  const zoomedIn = pinch && lensCam.k > pinch.startK * 1.02;
  pinch = null;
  lastZoomAt = Date.now();
  if (zoomedIn) scheduleLensAuto();
  // the finger still down carries on as a one-finger pan
  const [rest] = [...pointers.entries()];
  if (rest) {
    lensDrag = { x: rest[1].x, y: rest[1].y, moved: true, id: rest[0] };
    lensView.classList.add('dragging');
  }
}

let lensDrag = null;
lensView.addEventListener('pointerdown', (e) => {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  if (e.isPrimary) pointers.clear();       // a first finger: any pointer left over lost its "up"
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 2 && !pinch) { startPinch(); return; }
  if (pointers.size > 1) return;
  if (e.button !== 0 || e.target.closest('.rl-mk, .rg-tab')) return;
  lensDrag = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId };
});
lensView.addEventListener('pointermove', (e) => {
  if (pinch && pointers.has(e.pointerId)) { pinchMove(e.pointerId, e.clientX, e.clientY); return; }
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (!lensDrag || e.pointerId !== lensDrag.id) return;
  const dx = e.clientX - lensDrag.x, dy = e.clientY - lensDrag.y;
  if (!lensDrag.moved && Math.abs(dx) + Math.abs(dy) > CFG.DRAG_THRESHOLD_PX) {
    lensDrag.moved = true;
    lensView.classList.add('dragging');
    try { lensView.setPointerCapture(lensDrag.id); } catch { /* ok */ }
  }
  if (!lensDrag.moved) return;
  lensDrag.x = e.clientX; lensDrag.y = e.clientY;
  lensCam.x += dx; lensCam.y += dy;
  applyLens(false);
});
const endLensDrag = (e) => {
  pointers.delete(e.pointerId);
  if (pinch && pointers.size < 2) { endPinch(); return; }
  if (pinch || (lensDrag && e.pointerId !== lensDrag.id)) return;
  lensDrag = null;
  lensView.classList.remove('dragging');
};
lensView.addEventListener('pointerup', endLensDrag);
lensView.addEventListener('pointercancel', endLensDrag);
lensView.addEventListener('dblclick', (e) => { if (!e.target.closest('.rl-mk, .rg-tab')) lensZoom(e.clientX, e.clientY, CFG.ZOOM_DBLCLICK); });

locator.addEventListener('click', () => leaveOne());
locator.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); leaveOne(); } });

/* The keyboard: while a region is open, its keys come here first. */
addEventListener('keydown', (e) => {
  if (!level) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
  const pan = CFG.PAN_KEY_PX;
  const mid = [innerWidth / 2, innerHeight / 2];
  let handled = true;
  switch (e.key) {
    case 'Escape':
      if (A.glassOpen?.()) { handled = false; break; }
      if (A.cardOpen?.()) { A.closeCard?.(); for (const m of lensMarkers.children) m.classList.remove('active'); break; }
      leaveOne(); break;
    case '+': case '=': lensZoom(...mid, CFG.ZOOM_KEY); break;
    case '-': lensZoom(...mid, 1 / CFG.ZOOM_KEY); break;
    case 'ArrowLeft': lensCam.x += pan; applyLens(false); break;
    case 'ArrowRight': lensCam.x -= pan; applyLens(false); break;
    case 'ArrowUp': lensCam.y += pan; applyLens(false); break;
    case 'ArrowDown': lensCam.y -= pan; applyLens(false); break;
    case 'Home': case 'h': leaveTo(null); break;
    case 'd': case 's': case 'n': case 'g': break;   // the main map's travel keys sleep in here
    default: handled = false;
  }
  if (handled) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

/* The + / − buttons call A.zoomAt; inside a region they zoom the lens. */
const mainZoomAt = A.zoomAt;
A.zoomAt = (sx, sy, factor) => (level ? lensZoom(innerWidth / 2, innerHeight / 2, factor) : mainZoomAt?.(sx, sy, factor));

/* ── pinning a place on a region map (edit mode, admins) ─────────────────── */
function pinDrag(e, mk, n) {
  if (!A.editMode || !canAdminWrite() || !level || onOtherStyle()) return;   // not the dataset's region
  e.stopPropagation(); e.preventDefault();
  mk.setPointerCapture(e.pointerId);
  mk.classList.add('dragging');
  const toPct = (ev) => ({
    x: ((ev.clientX - lensCam.x) / lensCam.k / lensCam.w) * 100,
    y: ((ev.clientY - lensCam.y) / lensCam.k / lensCam.h) * 100,
  });
  let last = null;
  const move = (ev) => {
    last = toPct(ev);
    mk.style.left = last.x + '%';
    mk.style.top = last.y + '%';
    mk.dataset.dragged = '1';
  };
  const up = async () => {
    mk.classList.remove('dragging');
    mk.removeEventListener('pointermove', move);
    for (const t of DRAG_END) mk.removeEventListener(t, up);
    if (!last) return;
    const r = level;
    const pin = { x: Math.round(last.x * 10) / 10, y: Math.round(last.y * 10) / 10 };
    try {
      const { Editor } = await import('./editor/store.js');
      if (!Editor.loaded) await Editor.load();
      const current = Editor.entries('regions').find((x) => x.id === r.id);
      if (!current) throw new Error('that region is not in the saved map');
      const places = { ...(current.places && typeof current.places === 'object' ? current.places : {}), [n.id]: pin };
      await Editor.upsert('regions', r.id, { ...current, places });
      A.showToast?.(`${n.name} pinned on ${r.name}.`);
    } catch (err) {
      console.warn('region pin:', err);
      A.showToast?.(`Could not pin ${n.name}: ${err.message || err}`);
    }
  };
  mk.addEventListener('pointermove', move);
  for (const t of DRAG_END) mk.addEventListener(t, up);   // cancel and lost capture end it too
}

/* ── deep links: #region=<id> ─────────────────────────────────────────────
   Opening a region writes its id into the hash, leaving rewrites or clears
   it — with replaceState, so walking in and out of regions never piles up
   history entries. A hash typed, pasted or followed opens that region on
   load and on hashchange; nested ones open straight in, breadcrumb and all.
   An id the map does not know is announced and otherwise ignored. */
function writeHash(id) {
  try {
    const next = M.hashWithRegion(location.hash, id);
    if (next === location.hash.replace(/^#/, '')) return;
    history.replaceState(history.state, '', location.pathname + location.search + (next ? '#' + next : ''));
  } catch { /* a sandboxed frame may refuse; the lens works without the link */ }
}

async function goTo(id) {
  if (!id) { if (level) await leaveTo(null); return; }
  if (level?.id === id) return;
  const target = regionById(id);
  if (!target || !M.chainOf(regions(), id).length) {
    say(`No region called “${id}” on this map.`);
    return;
  }
  if (level) {
    const here = M.chainOf(regions(), level.id).map((c) => c.id);
    if (here.includes(id)) { await leaveTo(id); return; }           // an ancestor: step back out to it
    if (target.parent === level.id) { await enter(id, { from: 'lens' }); return; }
    await leaveTo(null);                                             // elsewhere: out, then in
  }
  A.closeCard?.();
  await enter(id, { from: 'main' });
}

let linkReady = false;
let followTimer = 0;
function followHash(tries = 0) {
  clearTimeout(followTimer);
  if (!linkReady) return;
  if (busy) {                                         // a transition is running: ask again after it
    if (tries < 40) followTimer = setTimeout(() => followHash(tries + 1), 120);
    return;
  }
  goTo(M.regionFromHash(location.hash));
}
addEventListener('hashchange', () => followHash());

/* The first open waits for the veil: the opening shot moves the main camera,
   and a lens opened under the veil would frame a rectangle that then moves. */
let linkArmed = false;
function armDeepLinks() {
  if (linkArmed) return;                              // buildWorld runs again on every Desk save
  linkArmed = true;
  const go = () => { linkReady = true; if (M.regionFromHash(location.hash)) followHash(); };
  if (!document.body.classList.contains('pre')) { go(); return; }
  const watch = new MutationObserver(() => {
    if (document.body.classList.contains('pre')) return;
    watch.disconnect();
    go();
  });
  watch.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

/* ── the Desk's "use the current view" ───────────────────────────────────
   What the window shows now, as a rectangle on the map `parentId` (blank =
   the main map): the lens's view when a region is open, else the main
   camera's — carried through the rectangles in between when the two maps
   differ. The main map's figure is the flat view: a tilted table is read as
   if it were laid flat. */
A.regionViewFor = (parentId) => {
  const onLens = Boolean(level);
  if (!onLens && !(A.cam && A.MAPW && A.MAPH)) return null;
  const raw = onLens
    ? M.viewRect(lensCam, lensCam.w, lensCam.h, innerWidth, innerHeight)
    : M.viewRect(A.cam, A.MAPW, A.MAPH, innerWidth, innerHeight);
  const carried = M.carryRect(regions(), onLens ? level.id : null, parentId || null, raw);
  return {
    rect: carried ? M.clampRect(carried) : null,
    from: onLens ? level.name : baseTitle(),          // the map the window is showing
    fromLens: onLens,
    direct: (onLens ? level.id : '') === (parentId || ''),
  };
};

/* ── wiring into the rest of the Atlas ──────────────────────────────────── */
const prevMove = A.onCameraMove;
A.onCameraMove = (userMove) => { prevMove?.(userMove); onMainMove(userMove); };

const prevBuild = A.buildWorld;
A.buildWorld = function buildWorldWithRegions() {
  prevBuild();
  buildFrames();
  armDeepLinks();
  if (level) {
    const still = regionById(level.id);
    if (!still) { closeLens(); return; }
    level = still;
    buildLensMarkers(still); buildLensFrames(still); buildCrumbs(still); buildLocator(still);
  }
};

/* The viewer changed the picture without a reload: another picture, other regions. */
A.onStyleChange = () => {
  if (level) closeLens();
  buildFrames();
};

addEventListener('resize', () => { if (level) { const k = lensCam.k; fitLens(false); if (k > lensCam.min) { lensCam.k = k; applyLens(false); } } });

loadMaps();
