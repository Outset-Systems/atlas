/* Atlas — REGIONS (v1.49.0): zoom into a part of the map and
   its own, more detailed map takes over; zoom back out and you are where you
   were. Regions nest.

   The maths is region-model.js (pure, node-tested). This file is the shell: the
   frames drawn on the map, the breadcrumb, the locator, the keyboard, and the
   wiring into the rest of the Atlas through `A`.

   A region IS the map (owner, 2026-11-01). It used to be a lens, a second stage
   over the map with markers of its own, and everything the map can do had to be
   built twice or went missing: no network layer, no split into services. Now the
   region's picture goes on the one stage, the places it holds move to their spots
   on it (world.js reads `A.levelPlaces`), and the rest of the Atlas carries on
   unchanged. `home` keeps the realm's own picture and camera for the way back. */

import { A, REDUCED, $, esc, canAdminWrite, DRAG_END } from './config.js';
import * as M from './region-model.js';
import { chosenStyle, refreshStyle, styleName } from './table.js';

const stage = $('stage');
const framesEl = $('region-frames');
const lens = $('region-lens');
const mapBase = $('map-base');
const crumbs = lens.querySelector('.rl-crumbs');
const locator = lens.querySelector('.rl-locator');
const locImg = locator.querySelector('img');
const locBox = locator.querySelector('.rl-loc-box');
const hint = lens.querySelector('.rl-hint');
const announce = $('region-announce');

const MOVE_MS = REDUCED ? 0 : 440;
const FADE_MS = REDUCED ? 0 : 200;   // the picture changing, each way
const SETTLE_MS = 260;          // the pause after a zoom before "open it?" is asked
const LEAVE_ARM_MS = 2200;      // a second zoom-out gesture at the floor within this = leave
const QUIET_MS = 220;           // the pause that makes it a second gesture, not inertia
const PAD = 28;                 // breathing room round a framed rectangle, px

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
A.onOtherStyle = onOtherStyle;   // world.js: a drag here belongs to the style's sidecar
/* A style's regions wear this browser's unsaved pins too (world.js A.styleDraft). */
const regions = () => {
  if (!onOtherStyle()) return datasetRegions();
  const drafted = A.styleDraft?.().regions || {};
  const list = styleRegions.get(chosenStyle()) || [];
  if (!Object.keys(drafted).length) return list;   // asked on every camera frame
  return list.map((r) =>
    (drafted[r.id] ? { ...r, places: { ...(r.places || {}), ...drafted[r.id] } } : r));
};
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
let level = null;               // the region on the stage, or null (the realm's own map)
let home = null;                // {src, w, h, cam}: what the stage holds when no region is open
let busy = false;               // a transition is running
let leaveArmedAt = 0;
let lastZoomAt = 0;
const disarmed = new Set();     // left recently: no auto-open until it is mostly out of view

/* ── the maps list (bundled vs uploaded) ─────────────────────────────────── */
async function loadMaps() {
  try {
    const r = await fetch('api/v2/maps', { cache: 'no-cache' });
    if (!r.ok) return;
    const { maps } = await r.json();
    if (useMaps(maps)) {
      A.onStyleChange();
      followHash();              // a link may have asked before this answered
    }
  } catch { /* the bundled guess still works */ }
}

/** Take a maps list in; true when a style is on. A layout save hands its
    answer here too, and the region on the stage stays open for it. */
function useMaps(maps) {
  A.MAPS_BY_NAME = Object.fromEntries(maps.map((m) => [m.name, m]));
  realmArt = maps.find((m) => m.default)?.name || null;
  styleRegions = new Map(maps.map((m) => [m.name, m.regions || []]));
  // region art is not in the gallery, so the list carries its address here
  for (const art of [...styleRegions.values()].flat()) A.MAPS_BY_NAME[art.map] ??= art;
  if (!chosenStyle()) return false;
  refreshStyle(maps.find((m) => m.name === chosenStyle()));
  return true;
}
A.useMaps = (maps) => { if (useMaps(maps)) A.buildWorld(); };

/* ── frames on the main map ─────────────────────────────────────────────── */
function frameEl(r) {
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
    enter(r.id);
  });
  return el;
}

function buildFrames() {
  framesEl.innerHTML = '';
  for (const r of M.childrenOf(regions(), level?.id ?? null)) framesEl.appendChild(frameEl(r));
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
  const clear = level ? { left: chromeClear.left, top: Math.max(chromeClear.top, crumbsBottom + 8) } : chromeClear;
  nudgeFrames(framesEl, cam, A.MAPW || 1, A.MAPH || 1, clear);
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
  if (busy || !A.cam) return;
  const k = A.cam.k;
  if (prevK !== null && userMove) {
    if (k > prevK * 1.001) zoomingIn = true;
    else if (k < prevK * 0.999) zoomingIn = false;
  }
  prevK = k;
  const here = level?.id ?? null;
  const view = viewOfMain();
  rearm(view, here);
  clearTimeout(settleTimer);
  if (!userMove || !zoomingIn) return;
  settleTimer = setTimeout(() => {
    if (busy || document.body.classList.contains('scene-open') || A.editMode) return;
    const pick = M.autoCandidate(regions(), here, viewOfMain(), (id) => !disarmed.has(id));
    if (pick) enter(pick.id, { auto: true });
  }, SETTLE_MS);
}

/* ── a region on the stage ─────────────────────────────────────────────── */
/** Where each place stands on region `r`, from where it stands on the map. */
function placesFor(r) {
  const out = {};
  for (const n of nodes()) {
    if (n._realOff ?? n.off_map) continue;
    const { x, y } = A.mainPlace(n);
    const at = M.placeOn(regions(), r.id, { id: n.id, x, y });
    if (at) out[n.id] = at;
  }
  return out;
}

/* In a region the breadcrumb is chrome too: tabs clear it as well. */
let crumbsBottom = 0;

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
    // the map's own name is the way home: the whole map, centred (owner, 2026-11-11)
    b.addEventListener('click', () => leaveTo(b.dataset.to || null, { home: !b.dataset.to }));
  }
}

function buildLocator(r) {
  const parent = r.parent ? regionById(r.parent) : null;
  locImg.src = parent ? mapUrl(parent.map) : home.src;
  locBox.style.left = r.x + '%';
  locBox.style.top = r.y + '%';
  locBox.style.width = r.w + '%';
  locBox.style.height = r.h + '%';
  locator.setAttribute('aria-label', `Back to ${parent ? parent.name : baseTitle()}`);
}

function say(text) { announce.textContent = ''; requestAnimationFrame(() => { announce.textContent = text; }); }

let hintTimer = 0;
function showHint(text, ms = 2600) {
  hint.textContent = text;
  hint.classList.add('on');
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => hint.classList.remove('on'), ms);
}

/* Loaded is not drawable: a large map can finish downloading and still paint
   blank for several frames while it decodes, and the stage would fade in on an
   empty frame. Wait for the decode too (where the browser offers it). */
async function loadArt(url) {
  const img = new Image();
  await new Promise((ok, fail) => {
    img.onload = () => ok();
    img.onerror = () => fail(new Error('the detailed map could not be loaded'));
    img.src = url;
  });
  try { await img.decode?.(); } catch { /* drawn as soon as it can be */ }
  return { url, w: img.naturalWidth || 2048, h: img.naturalHeight || 2048 };
}

const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

/** The picture changes under a brief fade, over dark, never over the sky. */
async function crossing(change) {
  document.body.classList.add('rg-crossing');
  stage.classList.add('rg-fading');
  await wait(FADE_MS);
  change();
  stage.classList.remove('rg-fading');
  await wait(FADE_MS);
  document.body.classList.remove('rg-crossing');
}

/** Put region `r`'s map on the stage. */
function wear(r, art) {
  home ??= { src: mapBase.getAttribute('src'), w: A.MAPW, h: A.MAPH, cam: { ...A.cam } };
  level = r;
  A.levelPlaces = placesFor(r);
  A.sizeWorld(art.url, art.w, art.h);
  document.body.classList.add('region-open');
  lens.hidden = false;
  lens.setAttribute('aria-label', `${r.name}, detailed map`);
  writeHash(r.id);
  A.buildWorld();
  A.measureWorld();
  buildCrumbs(r);
  buildLocator(r);
  crumbsBottom = crumbs.getBoundingClientRect().bottom || 0;   // measurable only once shown
}

/** Back to the realm's own picture, at once. */
function closeLens() {
  if (!level) return;
  const was = home;
  level = null;
  home = null;
  A.levelPlaces = null;
  A.sizeWorld(was.src, was.w, was.h);
  document.body.classList.remove('region-open');
  lens.hidden = true;
  writeHash(null);
  A.buildWorld();
  A.measureWorld();
}
A.leaveRegion = closeLens;

async function enter(id, { auto = false } = {}) {
  const r = regionById(id);
  if (!r || busy) return;
  busy = true;
  clearTimeout(settleTimer);
  try {
    const art = await loadArt(mapUrl(r.map));
    A.closeCard?.();
    // the camera frames the rectangle first. A nested region opened straight
    // from further out (a deep link) has its rectangle on its parent's map, not
    // this one, so the outermost rectangle on THIS map is the one to frame.
    const chain = M.chainOf(regions(), r.id);
    const on = chain[chain.findIndex((c) => c.id === level?.id) + 1] || r;
    Object.assign(A.cam, M.fitRect(on, A.MAPW, A.MAPH, innerWidth, innerHeight, PAD));
    A.apply?.(true);
    await wait(MOVE_MS);
    await crossing(() => { wear(r, art); A.home(false); prevK = A.cam.k; zoomingIn = false; });
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

/* Leave to `targetId` (null = the main map), one level or several. Zooming out
   or Escape frames the region you left, so you see where you were. `home`
   is for someone who asked for the map itself (its name in the breadcrumb, THE
   ATLAS): they get it whole and centred. */
async function leaveTo(targetId, { home: goHome = false } = {}) {
  if (!level || busy) return;
  busy = true;
  try {
    A.closeCard?.();
    const chain = M.chainOf(regions(), level.id);
    const stop = targetId ? chain.findIndex((c) => c.id === targetId) : -1;
    const leaving = chain[stop + 1] || level;   // the child of the target we are leaving through
    disarmed.add(leaving.id);
    const target = targetId ? regionById(targetId) : null;
    const art = target ? await loadArt(mapUrl(target.map)) : null;
    await crossing(() => {
      if (target) wear(target, art); else closeLens();
      if (goHome && !target) {
        A.home(false);
      } else {
        // frame the child we left, so you see where you were
        Object.assign(A.cam, M.fitRect(leaving, A.MAPW, A.MAPH, innerWidth, innerHeight, PAD));
        A.clampCam?.();
        A.apply?.(false);
      }
      prevK = A.cam.k;
      zoomingIn = false;
    });
    say(`Back on ${target ? target.name : baseTitle()}.`);
  } finally {
    busy = false;
  }
}

function leaveOne() {
  if (!level) return;
  leaveTo(level.parent || null);
}
/* ── leaving by zooming out ─────────────────────────────────────────────── */
/* Leaving by zooming out takes TWO gestures: reaching the floor arms it, and
   only a fresh zoom-out after a pause leaves. A trackpad flick sends a burst of
   wheel events with inertia; counting those as "again" threw people out of a
   region they had only meant to see whole. */
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

/** A zoom-out with nowhere left to go (camera.js asks). */
A.regionFloor = () => {
  const now = Date.now();
  const gap = now - lastZoomAt;
  lastZoomAt = now;
  floorReached(gap > QUIET_MS);
};
A.inRegion = () => Boolean(level);
/** From any depth, back to the main map, whole and centred (THE ATLAS, ui.js). */
A.leaveToMap = () => leaveTo(null, { home: true });

locator.addEventListener('click', () => leaveOne());
locator.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); leaveOne(); } });

/* The keyboard: while a region is open, its keys come here first. */
addEventListener('keydown', (e) => {
  if (!level) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
  let handled = true;
  switch (e.key) {
    case 'Escape':
      if (A.glassOpen?.()) { handled = false; break; }
      if (A.cardOpen?.()) { A.closeCard?.(); break; }
      leaveOne(); break;
    case 'Home': case 'h': leaveTo(null); break;
    case 'd': case 's': break;   // the sky and the Depths belong to the main map
    default: handled = false;
  }
  if (handled) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

/* − at the floor of a region is the same gesture as the wheel's. */
const mainZoomAt = A.zoomAt;
A.zoomAt = (sx, sy, factor) => {
  if (level && factor < 1 && A.cam.k <= A.fitScale() * 1.001) { A.regionFloor(); return; }
  mainZoomAt?.(sx, sy, factor);
};

/* A place that is not on this region is on the map: go there to show it. */
const mainFocus = A.focusNode;
A.focusNode = async (id, ...rest) => {
  if (level && !A.levelPlaces?.[id]) await leaveTo(null);
  mainFocus(id, ...rest);
};

/* ── pinning a place on a region map (edit mode, admins) ─────────────────── */
A.pinDrag = function pinDrag(e, mk, n) {
  if (!A.editMode || !level) return;
  // on another style the pin is drafted for its sidecar; on the realm's it is the dataset's
  const styled = onOtherStyle();
  if (!styled && !canAdminWrite()) return;
  e.stopPropagation(); e.preventDefault();
  mk.setPointerCapture(e.pointerId);
  mk.classList.add('dragging');
  // world.js's reading of the pointer, which also sees through a tilted table
  const toPct = (ev) => A.screenToPct(ev.clientX, ev.clientY);
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
    if (styled) {
      A.draftStyleSpot('places', n.id, pin, r.id);
      A.levelPlaces[n.id] = pin;
      n.x = pin.x; n.y = pin.y;
      A.redrawLines?.();
      return;
    }
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
};

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
    if (target.parent === level.id) { await enter(id); return; }
    await leaveTo(null);                                             // elsewhere: out, then in
  }
  A.closeCard?.();
  await enter(id);
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
   and a region opened under the veil would frame a rectangle that then moves. */
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
   the main map), carried through the rectangles in between when the two maps
   differ. The figure is the flat view: a tilted table is read as if it were
   laid flat. */
A.regionViewFor = (parentId) => {
  if (!(A.cam && A.MAPW && A.MAPH)) return null;
  const raw = M.viewRect(A.cam, A.MAPW, A.MAPH, innerWidth, innerHeight);
  const carried = M.carryRect(regions(), level?.id ?? null, parentId || null, raw);
  return {
    rect: carried ? M.clampRect(carried) : null,
    from: level ? level.name : baseTitle(),           // the map the window is showing
    fromLens: Boolean(level),
    direct: (level?.id ?? '') === (parentId || ''),
  };
};

/* ── wiring into the rest of the Atlas ──────────────────────────────────── */
const prevMove = A.onCameraMove;
A.onCameraMove = (userMove) => { prevMove?.(userMove); onMainMove(userMove); };

const prevBuild = A.buildWorld;
A.buildWorld = function buildWorldWithRegions() {
  if (level) {
    const still = regionById(level.id);
    if (!still) { closeLens(); return; }
    level = still;
    A.levelPlaces = placesFor(still);
  }
  prevBuild();
  buildFrames();
  armDeepLinks();
  if (level) { buildCrumbs(level); buildLocator(level); }
};

/* The viewer changed the picture without a reload: another picture, other regions. */
A.onStyleChange = () => {
  if (level) closeLens();
  buildFrames();
};

loadMaps();
