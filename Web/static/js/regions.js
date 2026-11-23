
import { A, REDUCED, $, esc, canAdminWrite, DRAG_END } from './config.js';
import { planFor, regionChanged, premiseBoxes, paintPremiseBoxes, useRegions } from './premises.js';
import * as M from './region-model.js';
import { regionKey, describe } from './keys-model.js';
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
const FADE_MS = REDUCED ? 0 : 200;
const SETTLE_MS = 260;
const LEAVE_ARM_MS = 2200;
const QUIET_MS = 220;
const PAD = 28;

const datasetRegions = () => (Array.isArray(A.DATA?.regions) ? A.DATA.regions : []);
let styleRegions = new Map();
let realmArt = null;
const onOtherStyle = () => {
  const art = chosenStyle();
  return Boolean(art) && art !== realmArt;
};
A.onOtherStyle = onOtherStyle;
let store = null;
try { store = localStorage; } catch {   }
let choices = {};
try { choices = M.parseChoices(store?.getItem(M.SHOWN_KEY)); } catch {   }
const regionArt = () => (onOtherStyle() ? chosenStyle() : '');
const everyRegion = () => (onOtherStyle() ? styleRegions.get(chosenStyle()) || [] : datasetRegions());
let shownFrom = null, shownArt = null, shownList = [];
function shownOf(list) {
  const art = regionArt();
  if (list !== shownFrom || art !== shownArt) {
    shownFrom = list;
    shownArt = art;
    shownList = M.shownRegions(list, choices, art);
  }
  return shownList;
}
let plansFrom = null, plansList = [];
const plans = () => {
  const all = datasetRegions();
  if (all !== plansFrom) { plansFrom = all; plansList = all.filter((r) => r && r.standalone === true); }
  return plansList;
};
let styledFrom = null, styledPlans = null, styledList = [];
const regions = () => {
  if (!onOtherStyle()) return shownOf(datasetRegions());
  const drafted = A.styleDraft?.().regions || {};
  let list = shownOf(styleRegions.get(chosenStyle()) || []);
  if (plans().length) {
    if (styledFrom !== list || styledPlans !== plans()) {
      styledFrom = list; styledPlans = plans(); styledList = [...list, ...styledPlans];
    }
    list = styledList;
  }
  if (!Object.keys(drafted).length) return list;
  return list.map((r) =>
    (drafted[r.id] ? { ...r, places: { ...(r.places || {}), ...drafted[r.id] } } : r));
};

export function zoomMaps() {
  return M.zoomMapRows(everyRegion(), choices, regionArt());
}

export function setZoomMapShown(id, on) {
  const r = everyRegion().find((x) => x.id === id);
  if (!r) return false;
  choices = M.withChoice(choices, r, on, regionArt());
  try {
    if (Object.keys(choices).length) store?.setItem(M.SHOWN_KEY, JSON.stringify(choices));
    else store?.removeItem(M.SHOWN_KEY);
  } catch {   }
  shownFrom = null;
  if (level && !regionById(level.id)) closeLens();
  else A.buildWorld();
  dispatchEvent(new CustomEvent('atlas:zoom-maps'));
  return true;
}
const regionById = (id) => regions().find((r) => r.id === id);
const nodes = () => A.DATA?.nodes || [];
const baseTitle = () => styleName() || String(A.DATA?.meta?.title || 'The map').replace(/ Atlas$/, '');
let MAPS_BY_NAME;
const mapUrl = (name) => {
  const known = MAPS_BY_NAME?.[name];
  return known ? known.url : `static/map/${encodeURIComponent(name)}`;
};

let level = null;
let home = null;
let busy = false;
let leaveArmedAt = 0;
let lastZoomAt = 0;
const disarmed = new Set();

async function loadMaps() {
  try {
    const r = await fetch('api/v2/maps', { cache: 'no-cache' });
    if (!r.ok) return;
    const { maps } = await r.json();
    if (useMaps(maps)) {
      A.onStyleChange();
      followHash();
    } else dispatchEvent(new CustomEvent('atlas:zoom-maps'));
  } catch {   }
}

function useMaps(maps) {
  MAPS_BY_NAME = Object.fromEntries(maps.map((m) => [m.name, m]));
  realmArt = maps.find((m) => m.default)?.name || null;
  styleRegions = new Map(maps.map((m) => [m.name, m.regions || []]));
  for (const art of [...styleRegions.values()].flat()) MAPS_BY_NAME[art.map] ??= art;
  if (!chosenStyle()) return false;
  refreshStyle(maps.find((m) => m.name === chosenStyle()));
  return true;
}
A.useMaps = (maps) => {
  const drawn = useMaps(maps);
  if (drawn) A.buildWorld();
  dispatchEvent(new CustomEvent('atlas:zoom-maps'));
};

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

function paintFolds() {
  const here = level?.id ?? null;
  const live = A.signalsFeed?.nodes || {};
  const sum = foldNote && foldNote.levelId === here
    ? M.foldSummary(regions(), here, foldNote.at, foldNote.hidden,
      Object.fromEntries([...foldNote.hidden].map((id) => [id, live[id]?.state])))
    : {};
  const homes = foldNote && foldNote.levelId === here ? M.homesAt(regions(), here, foldNote.at) : {};
  const RANK = ['down', 'degraded', 'maintenance', 'healthy'];
  for (const el of framesEl.children) {
    const r = regionById(el.dataset.region);
    const tab = el.querySelector('.rg-tab');
    if (!r || !tab) continue;
    const inside = Object.keys(homes).filter((id) => homes[id] === r.id).map((id) => live[id]?.state);
    const state = RANK.find((s) => inside.includes(s));
    if (state) el.dataset.state = state; else delete el.dataset.state;
    for (const old of tab.querySelectorAll('.rg-count, .svc-health')) old.remove();
    const s = sum[r.id];
    const words = M.foldWords(s);
    const open = `Open the detailed map of ${r.name}`;
    if (s?.worst) tab.dataset.worst = s.worst; else delete tab.dataset.worst;
    if (!words) { tab.setAttribute('aria-label', open); continue; }
    const [count, ...ills] = words.split(', ');
    const row = document.createElement('span');
    row.className = 'rg-count';
    row.setAttribute('aria-hidden', 'true');
    row.textContent = words;
    tab.appendChild(row);
    tab.setAttribute('aria-label',
      `${open}. ${count} ${s.count === 1 ? 'waits' : 'wait'} inside${ills.length ? ', ' + ills.join(', ') : ''}.`);
  }
  paintPremiseBoxes(framesEl);
}
A.paintFolds = paintFolds;

function buildFrames() {
  framesEl.innerHTML = '';
  for (const r of M.childrenOf(regions(), level?.id ?? null)) {
    if (r.standalone !== true) framesEl.appendChild(frameEl(r));
  }
  for (const el of premiseBoxes(level?.id ?? null)) framesEl.appendChild(el);
  paintFolds();
  syncFrames();
}

let chromeClear = { top: 72, left: 76 };
function measureChrome() {
  const bar = $('scenes-list')?.getBoundingClientRect();
  const zoom = document.querySelector('.zoom-stack')?.getBoundingClientRect();
  chromeClear = {
    top: bar && bar.height ? bar.bottom + 8 : 72,
    left: zoom && zoom.width ? zoom.right + 10 : 76,
  };
}

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
    const pick = M.autoCandidate(regions().filter((r) => r.standalone !== true), here, viewOfMain(),
      (id) => !disarmed.has(id));
    if (pick) enter(pick.id, { auto: true });
  }, SETTLE_MS);
}

function placesFor(r) {
  const plan = planFor(r.id, r.places || {});
  if (plan) return plan;
  const out = M.standingOn(regions(), r.id, mainSpots());
  for (const id of foldedHere(out, r.id)) delete out[id];
  return out;
}

function mainSpots() {
  const spots = {};
  for (const n of nodes()) {
    if (n._realOff ?? n.off_map) continue;
    const { x, y } = A.mainPlace(n);
    spots[n.id] = { x, y };
  }
  return spots;
}

const hiddenOn = (at, levelId) =>
  M.foldedAt(regions(), levelId, at, A.DATA?.routes);

let foldNote = null;
function foldedHere(at, levelId = level?.id ?? null) {
  const hidden = hiddenOn(at, levelId);
  foldNote = { levelId, at: { ...at }, hidden };
  return hidden;
}
A.foldedHere = (at) => foldedHere(at, null);

A.levelExits = () => {
  const here = A.levelPlaces;
  if (!level || !here) return [];
  const names = Object.fromEntries(nodes().map((n) => [n.id, n.name]));
  return M.exitsFor(regions(), level.id, here, mainSpots(), names, A.DATA?.routes);
};

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

async function loadArt(url) {
  const img = new Image();
  await new Promise((ok, fail) => {
    img.onload = () => ok();
    img.onerror = () => fail(new Error('the detailed map could not be loaded'));
    img.src = url;
  });
  try { await img.decode?.(); } catch {   }
  return { url, w: img.naturalWidth || 2048, h: img.naturalHeight || 2048 };
}

const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

async function crossing(change) {
  document.body.classList.add('rg-crossing');
  stage.classList.add('rg-fading');
  await wait(FADE_MS);
  change();
  stage.classList.remove('rg-fading');
  await wait(FADE_MS);
  document.body.classList.remove('rg-crossing');
}

function wear(r, art) {
  home ??= { src: mapBase.getAttribute('src'), w: A.MAPW, h: A.MAPH, cam: { ...A.cam } };
  level = r;
  A.levelPlaces = placesFor(r);
  A.sizeWorld(art.url, art.w, art.h);
  document.body.classList.add('region-open');
  lens.hidden = false;
  lens.setAttribute('aria-label', `${r.name}, detailed map`);
  writeHash(r.id);
  regionChanged(r.id, null);
  A.buildWorld();
  A.measureWorld();
  buildCrumbs(r);
  buildLocator(r);
  crumbsBottom = crumbs.getBoundingClientRect().bottom || 0;
}

function closeLens() {
  if (!level) return;
  const was = home;
  const left = level.id;
  level = null;
  home = null;
  A.levelPlaces = null;
  A.sizeWorld(was.src, was.w, was.h);
  document.body.classList.remove('region-open');
  lens.hidden = true;
  writeHash(null);
  regionChanged(null, left);
  A.buildWorld();
  A.measureWorld();
}
A.leaveRegion = closeLens;

export function openRegion(id) { return goTo(id || null); }
export const regionOpen = () => level?.id || '';
useRegions({ open: openRegion, current: regionOpen });

async function enter(id, { auto = false } = {}) {
  const r = regionById(id);
  if (!r || busy) return;
  busy = true;
  clearTimeout(settleTimer);
  try {
    const art = await loadArt(mapUrl(r.map));
    A.closeCard?.();
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
  } catch {   }
  return false;
}

async function leaveTo(targetId, { home: goHome = false } = {}) {
  if (!level || busy) return;
  busy = true;
  try {
    A.closeCard?.();
    const chain = M.chainOf(regions(), level.id);
    const stop = targetId ? chain.findIndex((c) => c.id === targetId) : -1;
    const leaving = chain[stop + 1] || level;
    disarmed.add(leaving.id);
    const target = targetId ? regionById(targetId) : null;
    const art = target ? await loadArt(mapUrl(target.map)) : null;
    await crossing(() => {
      if (target) wear(target, art); else closeLens();
      if (goHome && !target) {
        A.home(false);
      } else {
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

A.regionFloor = () => {
  const now = Date.now();
  const gap = now - lastZoomAt;
  lastZoomAt = now;
  floorReached(gap > QUIET_MS);
};
A.inRegion = () => Boolean(level);
A.leaveToMap = () => leaveTo(null, { home: true });

locator.addEventListener('click', () => leaveOne());
locator.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); leaveOne(); } });

addEventListener('keydown', (e) => {
  const action = regionKey(describe(e), {
    region: !!level, scene: !!A.sceneOpen, glass: !!A.glassOpen?.(), card: !!A.cardOpen?.(),
  });
  if (!action) return;
  switch (action) {
    case 'close-card': A.closeCard?.(); break;
    case 'leave-region': leaveOne(); break;
    case 'leave-to-map': leaveTo(null); break;
    case 'swallow': break;
  }
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);

const mainZoomAt = A.zoomAt;
A.zoomAt = (sx, sy, factor) => {
  if (level && factor < 1 && A.cam.k <= A.fitScale() * 1.001) { A.regionFloor(); return; }
  mainZoomAt?.(sx, sy, factor);
};

const mainFocus = A.focusNode;
async function reveal(id) {
  const n = nodes().find((x) => x.id === id);
  if (!n || n._realOff) return true;
  for (let step = 0; step < 8; step++) {
    for (let t = 0; busy && t < 40; t++) await wait(120);
    if (busy) return false;
    const drawn = level ? Boolean(A.levelPlaces?.[id]) : !n.off_map;
    if (drawn) return true;
    const { x, y } = A.mainPlace(n);
    const inside = M.childrenOf(regions(), level?.id ?? null)
      .find((c) => c.standalone !== true && M.placeOn(regions(), c.id, { id, x, y }));
    if (inside) await enter(inside.id);
    else if (level) await leaveTo(level.parent || null);
    else return true;
  }
  return true;
}
A.focusNode = async (id, ...rest) => {
  if (await reveal(id) === false) return;
  mainFocus(id, ...rest);
};

A.pinDrag = function pinDrag(e, mk, n) {
  delete mk.dataset.dragged;
  if (!A.editMode || !level) return;
  const styled = onOtherStyle();
  if (!styled && !canAdminWrite()) return;
  e.stopPropagation(); e.preventDefault();
  mk.setPointerCapture(e.pointerId);
  mk.classList.add('dragging');
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
  for (const t of DRAG_END) mk.addEventListener(t, up);
};

function writeHash(id) {
  try {
    const next = M.hashWithRegion(location.hash, id);
    if (next === location.hash.replace(/^#/, '')) return;
    history.replaceState(history.state, '', location.pathname + location.search + (next ? '#' + next : ''));
  } catch {   }
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
    if (here.includes(id)) { await leaveTo(id); return; }
    if (target.parent === level.id) { await enter(id); return; }
    await leaveTo(null);
  }
  A.closeCard?.();
  await enter(id);
}

let linkReady = false;
let followTimer = 0;
function followHash(tries = 0) {
  clearTimeout(followTimer);
  if (!linkReady) return;
  if (busy) {
    if (tries < 40) followTimer = setTimeout(() => followHash(tries + 1), 120);
    return;
  }
  goTo(M.regionFromHash(location.hash));
}
addEventListener('hashchange', () => followHash());

let linkArmed = false;
function armDeepLinks() {
  if (linkArmed) return;
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

A.regionViewFor = (parentId) => {
  if (!(A.cam && A.MAPW && A.MAPH)) return null;
  const raw = M.viewRect(A.cam, A.MAPW, A.MAPH, innerWidth, innerHeight);
  const carried = M.carryRect(regions(), level?.id ?? null, parentId || null, raw);
  return {
    rect: carried ? M.clampRect(carried) : null,
    from: level ? level.name : baseTitle(),
    fromLens: Boolean(level),
    direct: (level?.id ?? '') === (parentId || ''),
  };
};

export const boxContext = () => ({
  level: level ? { id: level.id, name: level.name } : null,
  spots: level ? { ...(A.levelPlaces || {}) } : mainSpots(),
});

export const frameRegions = () => ({
  level: level ? { id: level.id, name: level.name } : null,
  list: regions().filter((r) => (r.parent || null) === (level?.id ?? null)
    && [r.x, r.y, r.w, r.h].every(Number.isFinite)),
});

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

A.onStyleChange = () => {
  if (level) closeLens();
  if (regions().some((r) => r.fold === true)) A.buildWorld();
  else buildFrames();
  dispatchEvent(new CustomEvent('atlas:zoom-maps'));
};

loadMaps();
