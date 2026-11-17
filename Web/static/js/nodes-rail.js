/* NODES, the rail (2026-11-14, its own file 2026-11-16): the sections down
   the table's left, their rows and bells, and its clicks and keys. Cut out
   of nodes.js.

   A collection's ⋯ (an admin's) opens the one menu a place's and a
   service's ⋯ open (nodes-menu.js; 2026-11-16, before that a row of buttons
   unfolded under the collection). What stays here, under the collection's
   row: the name box Rename turns into, the armed Remove with what removing
   does, the alert rules that watch it and the wait before its second
   press, and the note that it holds services no longer on the map, with
   the way to tidy them. The menu only starts Rename and Remove
   (`startRename`, `armRemove`).

   Five of NODES' parts import each other in circles, which is safe because
   none of them calls another while it loads; what they need from nodes.js
   itself they reach through `hooks` (nodes-state.js). */

import { A, esc } from './config.js';
import * as R from './roster-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import { t } from './nodes-text.js';
import { DOT, store, S, el, hooks, phone, mayWrite, menuOn } from './nodes-state.js';
import { mayAlert, BELL, alertRules, panelOn, pressBell } from './nodes-cells.js';
import { drawResults, CARDS } from './nodes-table.js';
import {
  tell, ready, busy, applyOps, onDiskCollections, repairs, ensureRepairs, collectionLabel, done, collectionsChanged,
} from './nodes-forms.js';
import { thingList } from './nodes-services.js';
import { placeMenu, toggleMenu } from './nodes-menu.js';

/* ── the rail (2026-11-14) ───────────────────────────────────────────────── */

/** The rail's bell on a collection or a network: lit while a rule watches it. */
function railBell(kind, g) {
  if (!mayAlert()) return '';
  const rules = alertRules();
  const watching = rules ? AM.rulesOn(rules, kind, g.id) : [];
  const n = watching.length;
  const lit = watching.some(AM.ruleOn);   // ink while a rule is on, as the place's bell
  const on = panelOn(kind, g.id);
  const label = n ? t('nodes_bell_watched', { name: g.name, n }) : t('nodes_bell_group', { name: g.name });
  return `<button type="button" class="nv-bell nv-rail-bell${lit ? ' nv-bell-lit' : ''}${on ? ' on' : ''}" ` +
    `data-alerts="${kind}" data-id="${esc(g.id)}" aria-pressed="${on}" aria-label="${esc(label)}" title="${esc(label)}">${BELL}</button>`;
}

/** Put the rail's tools away: nothing being named, nothing armed. */
function railReset() {
  S.railMode = '';
  S.railRename = '';
  S.railArm = '';
  S.railArmAt = 0;
  S.railRules = [];
  S.railFocus = '';
}

function railRows(section, list, admin) {
  const field = R.RAIL_FIELDS[section];
  return list.map((g) => {
    const on = S.filter[field] === g.id;
    const trouble = g.worst ? t('nodes_rail_trouble', { n: g.trouble }) : '';
    const dot = g.worst
      ? `<span class="svc-health nv-rail-dot ${DOT[g.worst]}" aria-hidden="true"></span><span class="nv-sr">${esc(trouble)}</span>`
      : '<span class="nv-rail-dot" aria-hidden="true"></span>';
    const title = on ? t('nodes_rail_unshow') : t('nodes_rail_show', { name: g.name });
    const menu = section === 'collections' && admin
      ? `<button type="button" class="nv-rail-more" data-menu="${esc(g.id)}" aria-haspopup="menu" aria-expanded="${menuOn('collection', g.id)}" ` +
        `aria-label="${esc(t('nodes_rail_menu', { name: g.name }))}" title="${esc(t('nodes_rail_menu', { name: g.name }))}">⋯</button>`
      : '';
    const kind = section === 'collections' ? 'collection' : section === 'networks' ? 'network' : '';
    const bell = kind ? railBell(kind, g) : '';
    const row = `<li class="nv-rail-li"><button type="button" class="idx-item nv-rail-row${on ? ' on' : ''}" ` +
      `data-sec="${section}" data-id="${esc(g.id)}" aria-pressed="${on}" title="${esc(title)}${trouble ? ` · ${esc(trouble)}` : ''}">` +
      `${dot}<span class="nv-rail-name">${esc(g.name)}</span><span class="nv-rail-n">${g.count}</span></button>${bell}${menu}</li>`;
    return row + (section === 'collections' && admin ? railTools(g) : '');
  }).join('');
}

/** What an admin sees under one collection's row, when there is any of it:
    its name box while it is being renamed (the menu's Rename), or its armed
    Remove with what removing does (the menu's Remove; the second press is
    here), and the note of services it holds that have gone. The rest of a
    collection's tools are in its ⋯ menu (nodes-menu.js, 2026-11-16). */
function railTools(g) {
  if (S.railMode === 'rename' && S.railRename === g.id) {
    return `<li class="nv-rail-tools"><input class="dsk-input nv-rail-input" data-input="rename" maxlength="80" ` +
      `value="${esc(g.name)}" aria-label="${esc(t('nodes_rail_rename'))}">` +
      `<button type="button" class="dsk-btn dsk-btn-sm dsk-btn-go" data-act="rename-go" data-id="${esc(g.id)}">${esc(t('nodes_rail_rename_go'))}</button>` +
      `<button type="button" class="dsk-btn dsk-btn-sm" data-act="cancel">${esc(t('nodes_cancel'))}</button></li>`;
  }
  const armed = S.railArm === g.id
    ? `<button type="button" class="dsk-btn dsk-btn-sm dsk-btn-go" data-act="remove" data-id="${esc(g.id)}">` +
      `${esc(t('nodes_rail_remove_armed', { name: g.name }))}</button>` +
      `<button type="button" class="dsk-btn dsk-btn-sm" data-act="cancel">${esc(t('nodes_cancel'))}</button>` +
      `<p class="nv-rail-note">${esc(t('nodes_rail_remove_note'))}</p>` +
      (S.railRules.length ? `<p class="nv-rail-note nv-rail-warn">${esc(t('nodes_rail_remove_rules', { rules: S.railRules.join(', ') }))}</p>` : '')
    : '';
  const gone = goneServicesNote(g.id);
  return armed || gone ? `<li class="nv-rail-tools">${armed}${gone}</li>` : '';
}

/** The keys of the services on the map, worked out once per map: every
    collection's row asks on every draw of the rail. */
let knownCache = { data: null, roster: null, keys: new Set() };
function knownServices() {
  if (knownCache.data !== A.DATA || knownCache.roster !== S.roster) {
    knownCache = { data: A.DATA, roster: S.roster, keys: new Set(AM.services(A.DATA).map((x) => x.id)) };
  }
  return knownCache.keys;
}

/** A collection holding service keys no longer on the map (its place went,
    or the service was renamed; stage 3b): said, with the way to tidy it. */
function goneServices(id) {
  const c = (S.roster?.collections || []).find((x) => x.id === id);
  if (!c?.services?.length || !A.DATA) return [];
  const known = knownServices();
  return c.services.filter((k) => !known.has(k));
}

function goneServicesNote(id) {
  const gone = goneServices(id);
  if (!gone.length) return '';
  return `<p class="nv-rail-note nv-rail-warn" title="${esc(gone.join(', '))}">${esc(t(gone.length === 1 ? 'nodes_rail_gone_service' : 'nodes_rail_gone_services', { n: gone.length }))}</p>` +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-act="col-tidy" data-id="${esc(id)}">${esc(t('nodes_rail_tidy'))}</button>`;
}

async function tidyCollection(id) {
  const gone = new Set(goneServices(id));
  if (!gone.size) return;
  await busy(async () => {
    if (!(await ready())) return;
    const c = onDiskCollections().find((x) => x.id === id);
    if (!c) { tell(t('nodes_s_gone'), 'warn'); return; }
    const services = (Array.isArray(c.services) ? c.services : []).filter((k) => !gone.has(k));
    const { stopped } = await applyOps([{ op: 'upsert', section: 'collections', id, body: { services } }],
      'took gone services out of a collection');
    if (stopped) return;
    tell(t(gone.size === 1 ? 'nodes_rail_tidied_one' : 'nodes_rail_tidied', { n: gone.size, name: collectionLabel(id) }));
  });
}

function railSection(key, title, body) {
  const shut = S.railShut[key] === true;
  return `<section class="nv-rail-sec" data-sec="${key}">` +
    `<h3 class="nv-rail-h"><button type="button" class="nv-rail-head" data-toggle="${key}" aria-expanded="${!shut}">` +
    `<span class="nv-rail-chev" aria-hidden="true">${shut ? '▸' : '▾'}</span>${esc(title)}</button></h3>` +
    (shut ? '' : `<div class="nv-rail-body">${body}</div>`) + '</section>';
}

export function drawRail() {
  if (!el.rail) return;
  // a name being typed survives a redraw (a tick, a search, a refresh)
  const typing = el.rail.querySelector('.nv-rail-input');
  const kept = typing ? { which: typing.dataset.input, value: typing.value, focus: document.activeElement === typing,
    start: typing.selectionStart, end: typing.selectionEnd } : null;

  const groups = S.roster ? R.railGroups(S.roster) : { collections: [], networks: [], kinds: [] };
  const admin = mayWrite() && !phone();
  const list = (section, items, empty = '') => (items.length
    ? `<ul class="nv-rail-list">${railRows(section, items, admin)}</ul>`
    : (empty ? `<p class="nv-rail-empty">${esc(empty)}</p>` : ''));

  let foot = '';
  if (admin) {
    foot = S.railMode === 'new'
      ? `<div class="nv-rail-foot"><input class="dsk-input nv-rail-input" data-input="new" maxlength="80" ` +
        `placeholder="${esc(t('nodes_s_new'))}" aria-label="${esc(t('nodes_s_new'))}">` +
        `<button type="button" class="dsk-btn dsk-btn-sm dsk-btn-go" data-act="new-go">${esc(t('nodes_rail_new_go'))}</button>` +
        `<button type="button" class="dsk-btn dsk-btn-sm" data-act="cancel">${esc(t('nodes_cancel'))}</button></div>`
      : `<div class="nv-rail-foot"><button type="button" class="dsk-btn dsk-btn-sm" data-act="new">${esc(t('nodes_rail_new'))}</button></div>`;
  }
  el.rail.innerHTML =
    railSection('collections', t('nodes_rail_collections'),
      list('collections', groups.collections, S.roster ? t('nodes_rail_empty_collections') : '') + foot) +
    railSection('networks', t('nodes_rail_networks'), list('networks', groups.networks)) +
    railSection('kinds', t('nodes_rail_kinds'), list('kinds', groups.kinds) +
      list('things', S.roster ? R.thingGroups(thingList()).map((g) => ({ ...g, name: t(`nodes_kind_${g.id}`) })) : [])) +
    railSection('saved', t('nodes_rail_saved'), S.saved.length
      ? `<div class="nv-saved">${hooks.savedChips()}</div>`
      : `<p class="nv-rail-empty">${esc(t('nodes_rail_empty_saved'))}</p>`);
  for (const b of el.rail.querySelectorAll('[data-act]')) b.disabled = S.busy;

  let typingBack = false;
  if (kept) {
    const again = el.rail.querySelector(`.nv-rail-input[data-input="${kept.which}"]`);
    if (again) {
      again.value = kept.value;
      if (kept.focus) {
        again.focus();
        typingBack = true;
        try { again.setSelectionRange(kept.start, kept.end); } catch { /* not a text box */ }
      }
    }
  }
  // a redraw replaced the button that was pressed, or the name box went away:
  // put the keyboard on what comes next (the armed Remove, the ⋯, the new or
  // renamed row), unless someone is still typing in the box
  if (S.railFocus && !typingBack) {
    const next = el.rail.querySelector(S.railFocus);
    // spent only once it has landed: a redraw from an older roster may not
    // have the row yet, and the next one will
    if (next) { next.focus(); if (document.activeElement === next) S.railFocus = ''; }
  }
  // a collection's menu hangs from a ⋯ this draw has just replaced: seat it
  // again, or put it away when the collection has gone
  if (S.menu?.kind === 'collection') placeMenu();
}

/** A selector for the rail element of a collection, safe for any id. */
const railSel = (what, id) => (what === 'row'
  ? `.nv-rail-row[data-sec="collections"][data-id="${CSS.escape(id)}"]`
  : `[data-menu="${CSS.escape(id)}"]`);

function focusRailInput() {
  const box = el.rail.querySelector('.nv-rail-input');
  if (box) { box.focus(); box.select(); }
}

export function onRailClick(e) {
  if (hooks.onSavedPress(e)) return;
  const bell = e.target.closest('[data-alerts]');
  if (bell) { pressBell(bell.dataset.alerts, bell.dataset.id); return; }
  const toggle = e.target.closest('[data-toggle]');
  if (toggle) {
    const key = toggle.dataset.toggle;
    S.railShut = { ...S.railShut, [key]: !S.railShut[key] };
    R.writeRail(store, S.railShut);
    drawRail();
    el.rail.querySelector(`[data-toggle="${key}"]`)?.focus();
    return;
  }
  const row = e.target.closest('.nv-rail-row');
  if (row) {
    const patch = R.railPress(S.filter, row.dataset.sec, row.dataset.id);
    // a place kind and a thing kind are one choice: picking one lets go of the other
    if (patch.things) patch.kind = '';
    if (patch.kind) patch.things = '';
    S.filter = { ...S.filter, ...patch };
    S.cards = CARDS;
    hooks.syncFilterBoxes();
    S.msg = null;
    drawResults();
    el.rail.querySelector(`.nv-rail-row[data-sec="${row.dataset.sec}"][data-id="${CSS.escape(row.dataset.id)}"]`)?.focus();
    return;
  }
  const more = e.target.closest('[data-menu]');
  if (more) {
    // the one ⋯ menu (nodes-menu.js), out for this collection; a name box
    // or an armed Remove left in the rail is put away first
    if (S.railMode || S.railArm) { railReset(); drawRail(); }
    toggleMenu('collection', more.dataset.menu);
    return;
  }
  const act = e.target.closest('[data-act]');
  if (!act || S.busy) return;
  const id = act.dataset.id;
  const value = () => (el.rail.querySelector('.nv-rail-input')?.value || '').trim();
  switch (act.dataset.act) {
    case 'new': railReset(); S.railMode = 'new'; drawRail(); focusRailInput(); break;
    case 'new-go': createCollection(value()); break;
    case 'col-tidy': tidyCollection(id).then(() => { S.railFocus = railSel('menu', id); drawRail(); }); break;
    case 'rename-go': renameCollection(id, value()); break;
    case 'remove':
      // the armed Remove (the menu's Remove armed it). A double click must
      // not remove: the second press counts only once the warning about
      // alert rules is on screen and a moment has passed
      if (S.railArm === id) { if (S.railArmAt && Date.now() - S.railArmAt >= ARM_WAIT_MS) removeCollection(id); }
      else armRemove(id);
      break;
    case 'cancel': railCancel(); break;
    default: break;
  }
}

/** Cancel, or Escape in a name box: the name box or the armed Remove goes
    away, and the keyboard goes back to the collection's ⋯ (to New, for a
    new collection's name box). */
function railCancel() {
  const back = S.railRename || S.railArm;
  railReset();
  S.railFocus = back ? railSel('menu', back) : '[data-act="new"]';
  drawRail();
}

/** The menu's Rename: the collection's row gains its name box. */
export function startRename(id) {
  railReset();
  S.railMode = 'rename';
  S.railRename = id;
  drawRail();
  focusRailInput();
}

export function onRailKey(e) {
  const box = e.target.closest('.nv-rail-input');
  if (!box) return;
  if (e.key === 'Enter') {
    e.preventDefault();
    el.rail.querySelector(box.dataset.input === 'new' ? '[data-act="new-go"]' : '[data-act="rename-go"]')?.click();
  } else if (e.key === 'Escape') {
    e.stopPropagation();
    railCancel();
  }
}

/** The names of the alert rules that watch a collection, for the warning
    before it is removed. Empty when there are none, or ALERTS cannot say. */
/** The collection ids alert rules name, the suspended ones included: a new
    collection must not take one, or a rule the remove note said had stopped
    would quietly watch the new collection. Empty when ALERTS cannot say. */
/** The rules as read fresh from the shared document (alert-store.js), or
    none when ALERTS cannot say (off, refused, or the read failed). */
async function freshRules() {
  await AlertStore.read();
  return AlertStore.ALERTS.error ? [] : (AlertStore.ALERTS.body?.doc?.rules || []);
}

export async function ruleCollectionIds() {
  return [...AM.watchedIds(await freshRules(), 'collection')];
}

async function rulesWatching(id) {
  return AM.rulesOn(await freshRules(), 'collection', id).map((r) => String(r.name || r.id));
}

/** How long an armed Remove ignores presses: longer than a double click. */
const ARM_WAIT_MS = 500;

/** The menu's Remove: the collection's row gains its armed Remove, what
    removing does, and (once read) the alert rules that watch it. */
export async function armRemove(id) {
  S.railMode = '';
  S.railRename = '';
  S.railArm = id;
  S.railArmAt = 0;
  S.railRules = [];
  S.railFocus = `[data-act="remove"][data-id="${CSS.escape(id)}"]`;
  drawRail();
  const rules = await rulesWatching(id);
  if (S.railArm !== id) return;   // put away while it was asking
  S.railRules = rules;
  const onIt = document.activeElement?.closest?.('[data-act="remove"]');
  if (onIt) S.railFocus = `[data-act="remove"][data-id="${CSS.escape(id)}"]`;
  drawRail();
  // the wait runs from when the warning is on screen, not from the first
  // press (a slow ALERTS read must not shorten it; round 14)
  S.railArmAt = Date.now();
}

async function createCollection(name) {
  if (!name) { tell(t('nodes_rail_name_needed'), 'warn'); focusRailInput(); return; }
  await busy(async () => {
    if (!(await ready())) return;
    await ensureRepairs();
    const windowIds = repairs().flatMap((w) => (Array.isArray(w?.collections) ? w.collections : []));
    const taken = [...onDiskCollections().map((s) => s.id), ...(await ruleCollectionIds()), ...windowIds];
    const id = R.slugFor(name, taken, 'collection');
    const { stopped } = await applyOps([{ op: 'insert', section: 'collections', body: { id, name } }],
      'made a collection');
    if (stopped) return;
    railReset();
    S.railFocus = railSel('row', id);
    collectionsChanged();
    done(t('nodes_rail_created', { name }));
  });
}

async function renameCollection(id, name) {
  if (!name) { tell(t('nodes_rail_name_needed'), 'warn'); focusRailInput(); return; }
  await busy(async () => {
    if (!(await ready())) return;
    if (!onDiskCollections().some((s) => s.id === id)) { railReset(); S.railFocus = '[data-act="new"]'; return; }
    const { stopped } = await applyOps([{ op: 'upsert', section: 'collections', id, body: { name } }],
      'renamed a collection');
    if (stopped) return;
    railReset();
    S.railFocus = railSel('row', id);
    collectionsChanged();
    done(t('nodes_rail_renamed', { name }));
  });
}

async function removeCollection(id) {
  const name = collectionLabel(id);
  await busy(async () => {
    if (!(await ready())) return;
    if (!onDiskCollections().some((s) => s.id === id)) { railReset(); S.railFocus = '[data-act="new"]'; return; }
    const { stopped } = await applyOps([{ op: 'delete', section: 'collections', id }], 'removed a collection');
    if (stopped) { railReset(); return; }   // someone saved first: ask again from the start
    railReset();
    S.railFocus = '[data-act="new"]';
    if (S.filter.collection === id) { S.filter = { ...S.filter, collection: '' }; hooks.syncFilterBoxes(); }
    collectionsChanged();
    done(t('nodes_rail_removed', { name }));
  });
}
