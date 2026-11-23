
import { A, $, esc, themeText, ago, getJSON } from './config.js';
import * as R from './roster-model.js';
import { parseCollection } from './views-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import * as Rules from './alert-rules.js';
import { keepFocus } from './alert-forms.js';
import { NODES_TEXT, t } from './nodes-text.js';
import { STATES, DOT, store, S, el, shared, hooks, mayWrite, blank } from './nodes-state.js';
import { mayAlert } from './nodes-cells.js';
import { serviceIntents } from './names-model.js';
import {
  drawResults, CARDS, showRow, openCard, onResultsClick, onResultsChange,
} from './nodes-table.js';
import { drawRail, onRailClick, onRailKey } from './nodes-rail.js';
import { button } from './nodes-forms.js';
import { serviceOf, thingList } from './nodes-services.js';
import {
  closeMenu, onMenuClick, onMenuKey, onThingKey, onThingContext, onMenuContext,
} from './nodes-menu.js';

let root = null;

function focusBell(kind, id) {
  const where = kind === 'place' || kind === 'service' ? el.results : el.rail;
  if (kind === 'place') showRow(id);
  else if (kind === 'service') showRow(serviceOf(id)?.place);
  where?.querySelector(`[data-alerts="${kind}"][data-id="${CSS.escape(id)}"]`)?.focus();
}


function normalise(body) {
  const b = body && typeof body === 'object' ? body : {};
  const list = (v) => (Array.isArray(v) ? v : []);
  return {
    stamp: b.stamp || null,
    zones: list(b.zones),
    collections: list(b.collections),
    premises: list(b.premises),
    rows: list(b.rows).filter((r) => r && typeof r.id === 'string'),
  };
}

async function fetchRoster() {
  return normalise(await getJSON('api/v2/places/roster'));
}

let inflight = null;
let again = false;
function refresh() {
  hookRefresh();
  if (inflight) { again = true; return inflight; }
  inflight = (async () => {
    do {
      again = false;
      try { S.roster = await fetchRoster(); S.error = ''; } catch (err) { S.error = err.message || String(err); }
    } while (again);
    inflight = null;
    readEvents();
    readNames();
    readShadow();
    hookRefresh();
    const known = new Set((S.roster?.rows || []).map((r) => r.id));
    for (const id of [...S.selected]) if (!known.has(id)) S.selected.delete(id);
    draw();
    if (mayAlert()) AlertStore.read();
  })();
  return inflight;
}

let namesInflight = null;
function readNames() {
  if (namesInflight) return namesInflight;
  namesInflight = (async () => {
    try {
      const intents = serviceIntents(await getJSON('api/v2/names'));
      const changed = intents.size !== S.intents.size
        || [...intents].some(([k, v]) => S.intents.get(k)?.intent !== v.intent || S.intents.get(k)?.name !== v.name);
      S.intents = intents;
      if (changed && el.sheet) draw();
    } catch {   }
    namesInflight = null;
  })();
  return namesInflight;
}

let eventsInflight = null;
function readEvents() {
  if (eventsInflight) return eventsInflight;
  eventsInflight = (async () => {
    try {
      const res = await fetch('api/v2/events?limit=200', { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const body = await res.json();
      S.events = Array.isArray(body?.events) ? body.events : [];
      S.eventsError = false;
    } catch {
      S.eventsError = true;
    }
    eventsInflight = null;
    if (el.sheet) drawRecent();
  })();
  return eventsInflight;
}

let shadowInflight = null;
function readShadow() {
  if (!mayWrite()) { S.shadow = null; return null; }
  if (shadowInflight) return shadowInflight;
  shadowInflight = (async () => {
    try {
      const res = await fetch('api/v2/admin/shadow', { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      S.shadow = await res.json();
    } catch {
      S.shadow = { failed: true };
    }
    shadowInflight = null;
    if (el.sheet) drawShadow();
  })();
  return shadowInflight;
}

function drawShadow() {
  const sh = S.shadow;
  if (!el.shadow) return;
  if (!sh || (!sh.failed && !sh.on && !(sh.things || []).length)) { el.shadow.hidden = true; return; }
  el.shadow.hidden = false;
  if (sh.failed) { el.shadowList.innerHTML = `<div class="nv-quiet">${esc(t('nodes_shadow_failed'))}</div>`; return; }
  const n = (sh.agree || 0) + (sh.differ || 0);
  const lines = [];
  if (sh.on && sh.asking === false) lines.push(`<div class="nv-quiet">${esc(t('nodes_shadow_idle'))}</div>`);
  if (!n) lines.push(`<div class="nv-quiet">${esc(t('nodes_shadow_none'))}</div>`);
  else {
    const pct = Math.floor((1000 * (sh.agree || 0)) / n) / 10;
    const day = new Date(Number(sh.since) * 1000);
    const since = Number.isNaN(day.getTime()) ? '' : day.toISOString().slice(0, 10);
    lines.push(`<div class="nv-quiet">${esc(t('nodes_shadow_line', { pct, n, since }))}</div>`);
    if (!sh.differ) lines.push(`<div class="nv-quiet">${esc(t('nodes_shadow_same'))}</div>`);
  }
  const now = Date.now();
  const word = (s) => t(`nodes_state_${DOT[s] ? s : 'unknown'}`).toLowerCase();
  for (const th of (sh.things || []).filter((x) => x.differ > 0).slice(0, 8)) {
    const last = (th.last || [])[0] || {};
    const at = Number(last.at) * 1000;
    const name = th.of ? `${th.name} · ${th.of}` : th.name;
    lines.push(`<div class="nv-recent-row">` +
      `<span class="nv-recent-when">${esc(Number.isFinite(at) ? ago(Math.max(0, now - at)) : '')}</span>` +
      `<span class="svc-health ${DOT[last.atlas] || ''}" aria-hidden="true"></span>` +
      `<button type="button" class="nv-recent-name" data-recentplace="${esc(th.place || '')}">${esc(name || th.key || '')}</button>` +
      `<span class="nv-recent-said">${esc(t('nodes_shadow_row', { atlas: word(last.atlas), kuma: word(last.kuma),
        differ: th.differ, total: th.agree + th.differ }))}</span></div>`);
  }
  el.shadowList.innerHTML = lines.join('');
}

function hookRefresh() {
  const original = A.refreshData;
  if (typeof original !== 'function' || original.nodesHooked) return;
  const wrapped = async function refreshData(...args) {
    const out = await original.apply(this, args);
    if (A.VIEW === 'nodes') { if (S.busy) shared.pendingWhileBusy = true; else refresh(); }
    return out;
  };
  wrapped.nodesHooked = true;
  A.refreshData = wrapped;
}


function build() {
  root = $('nodes-sheet');
  if (!root || el.sheet) return Boolean(root);
  const query = new URLSearchParams(location.search);
  const wanted = parseCollection(query.get('collection') ?? query.get('set'));
  if (wanted) S.filter.collection = wanted;

  root.innerHTML = `
      <header class="nv-head">
        <h2 class="nv-title">${esc(themeText('view_nodes', 'NODES'))}</h2>
        <p class="nv-sub">${esc(t('nodes_sub'))}</p>
        <span class="nv-count" aria-live="polite"></span>
        <button type="button" class="dsk-btn dsk-btn-sm nv-add-place" hidden>${esc(t('nodes_add_place'))}</button>
      </header>
      <div class="nv-summary" role="group" aria-label="${esc(t('nodes_summary_label'))}" hidden></div>
      <div class="nv-body">
        <nav class="nv-rail" aria-label="${esc(t('nodes_rail_label'))}"></nav>
        <div class="nv-main">
          <div class="nv-menu-dim" aria-hidden="true" hidden></div>
          <div class="nv-menu" role="menu" hidden></div>
          <div class="nv-filters" role="search">
            <input class="dsk-input nv-search" type="search" placeholder="${esc(t('nodes_search'))}" aria-label="${esc(t('nodes_search_label'))}">
            <select class="dsk-input nv-pick" data-f="state" aria-label="${esc(t('nodes_col_state'))}"></select>
            <select class="dsk-input nv-pick nv-pick-rail" data-f="zone" aria-label="${esc(t('nodes_col_zone'))}"></select>
            <select class="dsk-input nv-pick nv-pick-rail" data-f="kind" aria-label="${esc(t('nodes_col_kind'))}"></select>
            <select class="dsk-input nv-pick nv-pick-rail" data-f="collection" aria-label="${esc(t('nodes_col_collections'))}"></select>
            <label class="nv-toggle"><input type="checkbox" class="dsk-check" data-f="unchecked"> ${esc(t('nodes_unchecked'))}</label>
            <label class="nv-toggle"><input type="checkbox" class="dsk-check" data-f="stale"> ${esc(t('nodes_stale'))}</label>
            <button type="button" class="dsk-btn dsk-btn-sm nv-clear">${esc(t('nodes_clear'))}</button>
            <span class="nv-save"></span>
          </div>
          <div class="nv-saved nv-saved-row" aria-label="${esc(t('nodes_saved_label'))}"></div>
          <div class="nv-alerts" hidden></div>
          <div class="nv-bulk"></div>
          <div class="nv-msg" aria-live="polite"></div>
          <div class="nv-results"></div>
        </div>
      </div>
      <section class="nv-recent" aria-label="${esc(t('nodes_recent_title'))}" hidden>
        <h3 class="nv-recent-title">${esc(t('nodes_recent_title'))}</h3>
        <div class="nv-recent-list"></div>
      </section>
      <section class="nv-recent nv-shadow" aria-label="${esc(t('nodes_shadow_title'))}" hidden>
        <h3 class="nv-recent-title">${esc(t('nodes_shadow_title'))}</h3>
        <div class="nv-recent-list nv-shadow-list"></div>
      </section>`;
  Object.assign(el, {
    sheet: root,
    count: root.querySelector('.nv-count'),
    search: root.querySelector('.nv-search'),
    picks: [...root.querySelectorAll('.nv-pick')],
    unchecked: root.querySelector('[data-f="unchecked"]'),
    stale: root.querySelector('[data-f="stale"]'),
    clear: root.querySelector('.nv-clear'),
    save: root.querySelector('.nv-save'),
    saved: root.querySelector('.nv-saved-row'),
    rail: root.querySelector('.nv-rail'),
    alerts: root.querySelector('.nv-alerts'),
    bulk: root.querySelector('.nv-bulk'),
    msg: root.querySelector('.nv-msg'),
    results: root.querySelector('.nv-results'),
    menu: root.querySelector('.nv-menu'),
    menuDim: root.querySelector('.nv-menu-dim'),
    addPlace: root.querySelector('.nv-add-place'),
    summary: root.querySelector('.nv-summary'),
    recent: root.querySelector('.nv-recent'),
    recentList: root.querySelector('.nv-recent-list'),
    shadow: root.querySelector('.nv-shadow'),
    shadowList: root.querySelector('.nv-shadow-list'),
  });
  Rules.mount(el.alerts, {
    shut: (was) => { drawResults(); if (was) focusBell(was.kind, was.id); },
    moved: () => keepFocus(el.sheet, drawResults),
  });

  el.search.value = S.filter.text;
  el.search.addEventListener('input', () => setFilter({ text: el.search.value }));
  for (const sel of el.picks) sel.addEventListener('change', () => {
    if (sel.dataset.f === 'kind') {
      const v = sel.value;
      setFilter(v.startsWith('thing:') ? { kind: '', things: v.slice(6) } : { kind: v, things: '' });
      return;
    }
    setFilter({ [sel.dataset.f]: sel.value });
  });
  el.unchecked.addEventListener('change', () => setFilter({ unchecked: el.unchecked.checked }));
  el.stale.addEventListener('change', () => setFilter({ staleDays: el.stale.checked ? 90 : 0 }));
  el.clear.addEventListener('click', () => { applyFilter({ ...R.NO_FILTER }); el.search.focus(); });

  el.results.addEventListener('click', onResultsClick);
  el.results.addEventListener('change', onResultsChange);
  el.rail.addEventListener('click', onRailClick);
  el.rail.addEventListener('keydown', onRailKey);
  el.menu.addEventListener('click', onMenuClick);
  el.menu.addEventListener('keydown', onMenuKey);
  for (const where of [el.results, el.rail]) {
    where.addEventListener('keydown', onThingKey);
    where.addEventListener('contextmenu', onThingContext);
  }
  el.menu.addEventListener('contextmenu', onMenuContext);
  el.menuDim.addEventListener('click', () => closeMenu(true));
  el.addPlace.addEventListener('click', () => A.newPlace?.());
  el.results.addEventListener('click', (e) => {
    const host = e.target.closest('[data-hostplace]');
    if (host) { e.stopPropagation(); openCard(host.dataset.hostplace); }
  }, true);
  el.summary.addEventListener('click', (e) => {
    const b = e.target.closest('[data-sumstate]');
    if (!b) return;
    const s = b.dataset.sumstate;
    setFilter({ state: S.filter.state === s ? '' : s });
    syncFilterBoxes();
    el.summary.querySelector(`[data-sumstate="${CSS.escape(s)}"]`)?.focus();
  });
  for (const list of [el.recentList, el.shadowList]) {
    list.addEventListener('click', (e) => {
      const b = e.target.closest('[data-recentplace]');
      if (b) openCard(b.dataset.recentplace);
    });
  }
  document.addEventListener('pointerdown', (e) => {
    if (S.menu && !el.menu.contains(e.target)
        && !e.target.closest?.('[data-rowmenu], [data-svcmenu], .nv-rail [data-menu], .nv-menu-dim')) closeMenu(false);
  });
  addEventListener('scroll', () => { if (S.menu) closeMenu(false); }, true);
  root.addEventListener('focusin', (e) => { if (!el.rail.contains(e.target)) S.railFocus = ''; });
  return true;
}


function setFilter(patch) {
  S.filter = { ...S.filter, ...patch };
  S.msg = null;
  S.cards = CARDS;
  drawResults();
}

function applyFilter(filter, sort) {
  S.filter = { ...R.NO_FILTER, ...R.cleanFilter(filter) };
  if (S.roster) S.filter = R.dropUnknown(S.filter, R.filterGroups(S.roster));
  if (sort) { S.sort = { ...sort }; R.writeSort(store, S.sort); }
  syncFilterBoxes();
  S.msg = null;
  S.cards = CARDS;
  drawResults();
}

function syncFilterBoxes() {
  if (!el.sheet) return;
  el.search.value = S.filter.text;
  for (const sel of el.picks) {
    sel.value = sel.dataset.f === 'kind' && S.filter.things ? `thing:${S.filter.things}` : (S.filter[sel.dataset.f] || '');
  }
  el.unchecked.checked = S.filter.unchecked;
  el.stale.checked = Number(S.filter.staleDays) > 0;
}

function fillPick(sel, first, options) {
  const want = S.filter[sel.dataset.f] || '';
  const known = options.some(([v]) => v === want);
  const shown = want && !known && !S.roster ? [...options, [want, want]] : options;
  sel.innerHTML = `<option value="">${esc(first)}</option>` +
    shown.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  if (want && !known && S.roster) S.filter[sel.dataset.f] = '';
  sel.value = S.filter[sel.dataset.f] || '';
}

function drawPicks() {
  const r = S.roster || { zones: [], collections: [], rows: [] };
  const kinds = [...new Set(r.rows.map((x) => x.kind).filter((k) => !blank(k)))].sort();
  const options = {
    state: [STATES.map((s) => [s, t(`nodes_state_${s}`)]), 'nodes_any_state'],
    zone: [r.zones.map((z) => [z.id, z.name || z.id]), 'nodes_any_zone'],
    kind: [[...kinds.map((k) => [k, k]),
      ...R.thingGroups(thingList()).map((g) => [`thing:${g.id}`, t(`nodes_kind_${g.id}`)])], 'nodes_any_kind'],
    collection: [r.collections.map((s) => [s.id, s.name || s.id]), 'nodes_any_collection'],
  };
  for (const sel of el.picks) {
    const [opts, any] = options[sel.dataset.f];
    fillPick(sel, t(any), opts);
  }
}

const savedChips = () => S.saved.map((s, i) =>
  `<span class="nv-chip-wrap"><button type="button" class="nv-chip" data-saved="${i}">${esc(s.name)}</button>` +
  `<button type="button" class="nv-chip-x" data-forget="${i}" aria-label="${esc(t('nodes_saved_forget', { name: s.name }))}" ` +
  `title="${esc(t('nodes_saved_forget', { name: s.name }))}">×</button></span>`).join('');

function onSavedPress(e) {
  const use = e.target.closest('[data-saved]');
  const forget = e.target.closest('[data-forget]');
  if (!use && !forget) return false;
  const inRail = e.currentTarget === el.rail;
  const land = (sel) => {
    if (inRail) { S.railFocus = sel; drawRail(); } else el.saved.querySelector(sel)?.focus();
  };
  if (use) {
    const i = Number(use.dataset.saved);
    const s = S.saved[i];
    if (s) { applyFilter(s.filter, s.sort); land(`[data-saved="${i}"]`); }
    return true;
  }
  const i = Number(forget.dataset.forget);
  const s = S.saved[i];
  if (s) {
    S.saved = R.withoutSaved(S.saved, s.name);
    R.writeSaved(store, S.saved);
    drawSaved();
    drawRail();
    if (S.saved.length) land(`[data-saved="${Math.min(i, S.saved.length - 1)}"]`);
    else if (inRail) land('[data-toggle="saved"]');
    else el.search.focus();
  }
  return true;
}

function drawSaved() {
  el.saved.innerHTML = savedChips();
  el.saved.hidden = !S.saved.length;
  el.saved.onclick = onSavedPress;

  el.save.innerHTML = '';
  if (!S.naming) {
    const open = button('dsk-btn dsk-btn-sm', t('nodes_save'), () => { S.naming = true; drawSaved(); el.save.querySelector('input')?.focus(); });
    open.disabled = R.isEmptyFilter(S.filter);
    el.save.append(open);
    return;
  }
  const name = document.createElement('input');
  name.className = 'dsk-input nv-save-name';
  name.placeholder = t('nodes_save_name');
  name.setAttribute('aria-label', t('nodes_save_name'));
  name.maxLength = 60;
  const keep = () => {
    if (!name.value.trim()) { name.focus(); return; }
    S.saved = R.withSaved(S.saved, name.value, S.filter, S.sort);
    R.writeSaved(store, S.saved);
    S.naming = false;
    drawSaved();
    drawRail();
  };
  name.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); keep(); }
    if (e.key === 'Escape') { e.stopPropagation(); S.naming = false; drawSaved(); }
  });
  el.save.append(name, button('dsk-btn dsk-btn-sm dsk-btn-go', t('nodes_save_go'), keep),
    button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { S.naming = false; drawSaved(); }));
}

function drawSummary() {
  const counted = !S.roster ? [] : S.filter.things
    ? thingList().filter((x) => x.kind === S.filter.things) : S.roster.rows;
  const counts = R.stateCounts(counted);
  el.summary.hidden = !counts.length;
  el.summary.innerHTML = counts.map(([s, n]) => {
    const on = S.filter.state === s;
    return `<button type="button" class="nv-sum${on ? ' on' : ''}" data-sumstate="${esc(s)}" aria-pressed="${on}">` +
      `<span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>` +
      `${esc(t('nodes_summary_item', { n, state: t(`nodes_state_${s}`) }))}</button>`;
  }).join('');
}

let svcIndex = { data: null, keys: new Map() };
function serviceIndex() {
  if (svcIndex.data === A.DATA) return svcIndex.keys;
  const keys = new Map();
  for (const node of A.DATA?.nodes || []) {
    if (!node || typeof node.id !== 'string') continue;
    for (const link of node.links || []) {
      if (!link || typeof link !== 'object') continue;
      const key = AM.serviceKey(node.id, link);
      if (!keys.has(key)) keys.set(key, { place: node.id, label: typeof link.label === 'string' ? link.label : '' });
    }
  }
  svcIndex = { data: A.DATA, keys };
  return keys;
}

function drawRecent() {
  if (!el.sheet) return;
  if (!S.roster || (S.events === null && !S.eventsError)) { el.recent.hidden = true; return; }
  el.recent.hidden = false;
  if (S.events === null) {
    el.recentList.innerHTML = `<div class="nv-quiet">${esc(t('nodes_recent_failed'))}</div>`;
    return;
  }
  const svcs = serviceIndex();
  const keyPlace = new Map();
  let places = S.shown;
  let events = S.events;
  if (S.filter.things) {
    for (const k of S.thingsShown) if (svcs.has(k)) keyPlace.set(k, svcs.get(k).place);
    places = [...new Set(keyPlace.values())];
    events = S.events.filter((e) => e?.kind === 'service');
  } else {
    for (const e of S.events) if (e?.kind === 'service' && svcs.has(e.target)) keyPlace.set(e.target, svcs.get(e.target).place);
  }
  const list = R.recentFor(events, places, keyPlace, 8);
  const names = new Map(S.roster.rows.map((r) => [r.id, r.name || r.id]));
  const now = Date.now();
  const row = (e) => {
    const at = Date.parse(e.at);
    const when = Number.isNaN(at) ? '' : ago(Math.max(0, now - at));
    const what = e.kind === 'service'
      ? `${names.get(e.place) || e.place} · ${svcs.get(e.target)?.label || e.target}`
      : (names.get(e.place) || e.name || e.place);
    const known = Object.prototype.hasOwnProperty.call(NODES_TEXT, `nodes_recent_to_${e.to}`);
    const said = known ? t(`nodes_recent_to_${e.to}`) : t('nodes_recent_to_other', { state: String(e.to || '') });
    return `<div class="nv-recent-row">` +
      `<span class="nv-recent-when"${e.at ? ` title="${esc(String(e.at))}"` : ''}>${esc(when)}</span>` +
      `<span class="svc-health ${DOT[e.to] || ''}" aria-hidden="true"></span>` +
      `<button type="button" class="nv-recent-name" data-recentplace="${esc(e.place)}">${esc(what)}</button>` +
      `<span class="nv-recent-said">${esc(said)}</span></div>`;
  };
  el.recentList.innerHTML = (S.eventsError ? `<div class="nv-quiet">${esc(t('nodes_recent_failed'))}</div>` : '') +
    (list.length ? list.map(row).join('') : `<div class="nv-quiet">${esc(t('nodes_recent_none'))}</div>`);
}


function draw() {
  if (!el.sheet) return;
  drewWithoutMap = !A.DATA;
  if (S.roster) S.filter = R.dropUnknown(S.filter, R.filterGroups(S.roster));
  drawPicks();
  syncFilterBoxes();
  drawResults();
  Rules.draw();
}

function show() {
  if (!build()) return;
  hookRefresh();
  draw();
  refresh();
  if (mayAlert()) AlertStore.read();
}

Object.assign(hooks, { refresh, syncFilterBoxes, savedChips, onSavedPress, drawSaved, drawSummary, drawRecent });

AlertStore.listen((changed) => {
  if (changed && A.VIEW === 'nodes' && el.sheet && mayAlert()) keepFocus(el.sheet, drawResults);
});

addEventListener('atlas:view', (e) => { if (e.detail?.view === 'nodes') show(); });
let drewWithoutMap = false;
addEventListener('atlas:premise', (e) => {
  const id = typeof e.detail?.id === 'string' ? e.detail.id : '';
  if ((S.filter.premise || '') !== id) setFilter({ premise: id });
});
addEventListener('atlas:data', () => { if (drewWithoutMap && A.VIEW === 'nodes' && el.sheet) draw(); });
addEventListener('DOMContentLoaded', hookRefresh, { once: true });
if (A.VIEW === 'nodes' || document.body.dataset.view === 'nodes') show();
