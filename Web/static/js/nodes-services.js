/* NODES, the services (2026-11-15, their own file 2026-11-16): a place's
   services under its row, every container or service as a list of its own,
   and a service's own writes (unmanaged, its collections). Cut out of
   nodes.js. Five of its parts import each other in circles, which is safe
   because none of them calls another while it loads; what they need from
   nodes.js itself they reach through `hooks` (nodes-state.js). */

import { A, esc } from './config.js';
import * as R from './roster-model.js';
import Editor from './editor/store.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import { t } from './nodes-text.js';
import { DOT, S, el, shared, hooks, phone, mayWrite, dim, menuOn } from './nodes-state.js';
import { mayAlert, BELL, alertRules, panelOn } from './nodes-cells.js';
import { drawResults, CARDS, syncSelectAll } from './nodes-table.js';
import {
  tell, drawBulk, ready, busy, applyOps, onDiskCollections, ensureRepairs,
} from './nodes-forms.js';
import { placeMenu, closeMenu } from './nodes-menu.js';

/* ── stage 3b (2026-11-15): a place's services, under its row ─────────────
   The Services count opens the place's services in a row beneath it, built
   only when opened (stage 1: the browser is the wall). Each is known by its
   key (alerts-model serviceKey: a Kuma monitor, or `<place>/<label>`), shows
   its state from the feed, its collections, a bell, and a ⋯ in the one
   shared menu (nodes-menu.js, listed by menu-model.js): Schedule maintenance…, Maintenance mode, Unmanaged,
   Collections…, Alerts. A service in maintenance or unmanaged through a
   collection, or with its place, says so instead of offering a switch. */

const mapNode = (id) => (A.DATA?.nodes || []).find((x) => x && x.id === id) || null;
export const serviceOf = (key) => AM.services(A.DATA).find((s) => s.id === key) || null;
export const linkOf = (svc) => (mapNode(svc?.place)?.links || []).find((l) => l && AM.serviceKey(svc.place, l) === svc.id) || null;
export const holding = (key) => (S.roster?.collections || []).filter((c) => (c.services || []).includes(key));

export function servicesCell(row, admin) {
  const n = typeof row.services === 'number' ? row.services : null;
  if (n === null) return dim;
  if (!admin || phone() || !n) return `<span class="nv-mono">${n}</span>`;
  const open = S.expanded.has(row.id);
  const label = t(open ? 'nodes_svc_close' : 'nodes_svc_open', { name: row.name || row.id });
  return `<button type="button" class="nv-svc-toggle" data-expand="${esc(row.id)}" aria-expanded="${open}" ` +
    `aria-label="${esc(label)}" title="${esc(label)}"><span class="nv-mono">${n}</span> ${open ? '▾' : '▸'}</button>`;
}

/** What a service's state reads as: unmanaged (itself, a collection, its
    place), maintenance (a window on it), else the feed's, else unknown. */
function serviceState(svc, row) {
  const link = linkOf(svc);
  if (row?.unmanaged || link?.unmanaged === true || holding(svc.id).some((c) => c.unmanaged === true)) return 'unmanaged';
  const feed = A.signalsFeed || {};
  if ((feed.maintenance_services || []).includes(svc.id)) return 'maintenance';
  const s = feed.services?.[svc.id]?.state;
  return DOT[s] ? s : 'unknown';
}

/** One service's line: under its place's row, or in the list of every
    container or service, where `flat` (its place and container) follows the
    name (2026-11-15). `s` is the state it reads as; `menu` draws its ⋯ (an
    admin's writes). */
function serviceItem(svc, row, s, rules, flat = '', menu = true) {
  const cols = holding(svc.id).map((c) => c.name || c.id);
  let bell = '';
  if (mayAlert() && rules) {
    const on = panelOn('service', svc.id);
    // as the server judges it: unmanaged, behind its own group, or on a
    // place no rule sends for, it is held (stage 3b review)
    const gated = Boolean(linkOf(svc)?.require_group);
    const heldBy = s === 'unmanaged' ? 'nodes_bell_unmanaged'
      : (gated || (AlertStore.ALERTS.body?.status?.held || []).includes(row.id)) ? 'nodes_bell_held' : '';
    if (heldBy) {
      const label = t(heldBy, { name: svc.label });
      bell = `<button type="button" class="nv-bell nv-bell-held${on ? ' on' : ''}" data-alerts="service" ` +
        `data-id="${esc(svc.id)}" aria-pressed="${on}" aria-label="${esc(label)}" title="${esc(label)}">${BELL}` +
        '<span class="nv-bell-n">×</span></button>';
    } else {
      const reaching = AM.rulesReachingService(rules, svc.id, S.roster?.collections || []);
      const n = reaching.length;
      const lit = reaching.some(AM.ruleOn);
      const label = n ? t('nodes_bell_watched', { name: svc.label, n }) : t('nodes_bell_group', { name: svc.label });
      bell = `<button type="button" class="nv-bell${lit ? ' nv-bell-lit' : ''}${on ? ' on' : ''}" data-alerts="service" ` +
        `data-id="${esc(svc.id)}" aria-pressed="${on}" aria-label="${esc(label)}" title="${esc(label)}">${BELL}` +
        `<span class="nv-bell-n">${n || ''}</span></button>`;
    }
  }
  return `<li class="nv-svc${flat ? ' nv-thing' : ''}${s === 'unmanaged' ? ' nv-unmanaged' : ''}">` +
    `<span class="nv-state"><span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>${esc(t(`nodes_state_${s}`))}</span>` +
    `<span class="nv-svc-name" title="${esc(t('nodes_svc_key', { key: svc.id }))}">${esc(svc.label)}` +
    `<span class="nv-svc-by"> · ${esc(serviceWatcher(svc))}</span></span>` +
    flat +
    `<span class="nv-dim nv-svc-cols">${cols.length ? esc(t('nodes_svc_in', { names: cols.join(', ') })) : ''}</span>` +
    bell + (!menu ? '</li>' :
    `<button type="button" class="nv-rail-more" data-svcmenu="${esc(svc.id)}" aria-haspopup="menu" ` +
    `aria-expanded="${menuOn('service', svc.id)}" aria-label="${esc(t('nodes_menu', { name: svc.name }))}" ` +
    `title="${esc(t('nodes_menu', { name: svc.name }))}">⋯</button></li>`);
}

export function servicesRow(row, span, index = 0) {
  const list = AM.services({ nodes: [mapNode(row.id)].filter(Boolean) });
  const rules = alertRules();
  const items = list.map((svc) => serviceItem(svc, row, serviceState(svc, row), rules)).join('');
  return `<tr class="nv-svc-row" data-svc-of="${esc(row.id)}"${index ? ` aria-rowindex="${index}"` : ''}><td colspan="${span}">` +
    (items ? `<ul class="nv-svc-list">${items}</ul>` : `<p class="nv-rail-empty">${esc(t('nodes_svc_none'))}</p>`) +
    '</td></tr>';
}

/** Who watches one service: Kuma when it names a monitor, else Atlas when a
    check has answered for it, else nothing. */
function serviceWatcher(svc) {
  return serviceWatcherWords(svc) || t('nodes_by_nothing');
}

/** The same, '' for nothing: the first line of its ⋯ menu (2026-11-17). */
export function serviceWatcherWords(svc) {
  if (linkOf(svc)?.kuma) return t('nodes_by_kuma');
  return A.signalsFeed?.services?.[svc.id] ? t('nodes_by_checks') : '';
}

/* ── every container, or every service, as a list (2026-11-15, C2) ── */

/** The things on the map, worked out once per map, feed and roster. */
let thingsCache = { data: null, feed: null, roster: null, list: [] };
export function thingList() {
  const feed = A.signalsFeed || null;
  if (thingsCache.data === A.DATA && thingsCache.feed === feed && thingsCache.roster === S.roster) return thingsCache.list;
  const list = R.thingRows(A.DATA, S.roster, feed || {});
  thingsCache = { data: A.DATA, feed, roster: S.roster, list };
  return list;
}

export function drawThings() {
  const kind = S.filter.things;
  const all = thingList().filter((x) => x.kind === kind);
  const shown = R.sortThings(R.filterThings(all, S.filter));
  // a selection is of places: none here, and nothing for the bulk bar to act on
  S.win = null;
  S.shown = [];
  S.thingsShown = shown.map((x) => x.key);
  if (S.selected.size) { S.selected.clear(); S.arm.disarm(); }
  const what = (n) => t(n === 1 ? `nodes_things_${kind}_one` : `nodes_things_${kind}`);
  el.count.textContent = shown.length === all.length
    ? t('nodes_things_all', { total: all.length, what: what(all.length) })
    : t('nodes_things_count', { shown: shown.length, total: all.length, what: what(all.length) });
  const rows = new Map(S.roster.rows.map((r) => [r.id, r]));
  const rules = alertRules();
  const admin = mayWrite() && !phone();   // the ⋯ is an admin's, as under a place's row
  const cut = shown.slice(0, S.cards);
  const items = cut.map((x) => {
    const svc = { id: x.key, name: `${x.label} on ${x.place_name}`, place: x.place, label: x.label };
    const flat = `<button type="button" class="nv-svc-host" data-hostplace="${esc(x.place)}" ` +
      `title="${esc(t('nodes_thing_host', { name: x.place_name }))}">${esc(x.place_name)}</button>` +
      `<span class="nv-mono nv-dim nv-svc-ctr">${esc(x.container)}</span>`;
    return serviceItem(svc, rows.get(x.place), R.rowState(x), rules, flat, admin);
  }).join('');
  el.results.innerHTML = !all.length ? `<div class="dsk-notice">${esc(t('nodes_things_empty'))}</div>`
    : !shown.length ? `<div class="dsk-notice">${esc(t('nodes_things_none'))}</div>`
      : `<ul class="nv-svc-list nv-things">${items}</ul>` + (shown.length > S.cards
        ? `<button type="button" class="dsk-btn dsk-btn-sm nv-more-cards" data-morecards>${esc(t('nodes_more_cards', { n: Math.min(CARDS, shown.length - S.cards), left: shown.length - S.cards }))}</button>` : '');
  if (S.error) el.results.insertAdjacentHTML('afterbegin', `<div class="dsk-notice dsk-notice-warn">${esc(t('nodes_failed', { why: S.error }))}</div>`);
  placeMenu();
  el.addPlace.hidden = !(mayWrite() && !phone() && typeof A.newPlace === 'function');
  syncSelectAll();
  drawBulk();
  hooks.drawSummary();
  hooks.drawRecent();
}

export function toggleServices(id) {
  if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id);
  closeMenu(false);
  drawResults();
  el.results.querySelector(`[data-expand="${CSS.escape(id)}"]`)?.focus();
  if (!Editor.repairs) ensureRepairs();
}

/** A link's `unmanaged`: the place's whole `links` list is written (a link
    has no id of its own), read fresh under the map's stamp. */
export async function setServiceUnmanaged(svc, on) {
  await busy(async () => {
    if (!(await ready())) return;
    const node = (Editor.data?.nodes || []).find((x) => x.id === svc.place);
    const links = Array.isArray(node?.links) ? node.links : [];
    let hit = false;
    const next = links.map((l) => {
      if (!l || typeof l !== 'object' || AM.serviceKey(svc.place, l) !== svc.id || (l.unmanaged === true) === on) return l;
      hit = true;
      const copy = { ...l };
      if (on) copy.unmanaged = true; else delete copy.unmanaged;
      return copy;
    });
    if (!hit) { tell(t('nodes_already')); return; }
    const { stopped } = await applyOps([{ op: 'upsert', section: 'nodes', id: svc.place, body: { links: next } }],
      on ? 'marked a service unmanaged' : 'watched a service again');
    if (stopped) return;
    const line = t(on ? 'nodes_unmanaged_on_done' : 'nodes_unmanaged_off_done', { name: svc.name });
    A.showToast?.(line);
    tell(line);
  });
}

/** Put a service in a collection, or take it out (`services`, by key). */
export async function setServiceCollection(key, collectionId, add, name) {
  await busy(async () => {
    if (!(await ready())) return;
    const c = onDiskCollections().find((x) => x.id === collectionId);
    if (!c) { tell(t('nodes_s_gone'), 'warn'); return; }
    const now = Array.isArray(c.services) ? c.services.filter((k) => typeof k === 'string') : [];
    if (add === now.includes(key)) { tell(t('nodes_already')); return; }
    const services = add ? [...now, key] : now.filter((k) => k !== key);
    const { stopped } = await applyOps([{ op: 'upsert', section: 'collections', id: collectionId, body: { services } }],
      add ? 'added a service to a collection' : 'took a service out of a collection');
    if (stopped) return;
    S.form = '';
    S.scope = null;
    shared.formEl = null;
    const line = t(add ? 'nodes_sc_done_add' : 'nodes_sc_done_out', { name, collection: c.name || c.id });
    A.showToast?.(line);
    tell(line);
  });
}
