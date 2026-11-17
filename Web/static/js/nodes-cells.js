/* NODES, the cells (2026-11-16): what one row's columns say (state, reviewed,
   maintenance, certificate, collections, watched by, kind, addresses), and
   the bell in the Alerts column with the gate and the press every other bell
   uses. Cut out of nodes.js. Who watches a place, in words, is also what a
   phone's sheet says (nodes-menu.js, 2026-11-16). They return HTML for
   nodes-table.js to place;
   this file imports only the words and the shared state. */

import { A, esc } from './config.js';
import * as R from './roster-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import * as Rules from './alert-rules.js';
import { NODES_TEXT, t } from './nodes-text.js';
import { DOT, S, phone, dim, blank } from './nodes-state.js';

/* ── alerts inside NODES (2026-11-14) ─────────────────────────────────────
   The owner: "i didn't want to add an alerts section i wanted it built into
   the node view." A place's bell in the Alerts column, and a bell on each
   collection and network in the rail, open alert-rules.js's panel above the
   table for that one thing; a second press on the same bell shuts it. The
   count is the rules that reach the place as the server matches them
   (alerts-model `rulesCovering`). An admin's, on a wide screen; the routes
   refuse anyone else regardless. */
export const mayAlert = () => Boolean(A.MAY_ALERTS) && !phone();
export const BELL = '<svg class="nv-bell-i" viewBox="0 0 16 16" aria-hidden="true" focusable="false">' +
  '<path fill="currentColor" d="M8 1.4c.5 0 .9.4.9.9v.6a4.4 4.4 0 0 1 3.5 4.3v2.6l1.3 1.9H2.3l1.3-1.9V7.2' +
  'a4.4 4.4 0 0 1 3.5-4.3v-.6c0-.5.4-.9.9-.9zM6.2 12.9h3.6a1.8 1.8 0 0 1-3.6 0z"/></svg>';
export const alertRules = () => AlertStore.ALERTS.body?.doc?.rules || null;
export const panelOn = (kind, id) => { const p = Rules.current(); return Boolean(p && p.kind === kind && p.id === id); };

export function alertsCell(row) {
  const rules = alertRules();
  if (!rules) return dim;
  const name = row.name || row.id;
  const on = panelOn('place', row.id);
  // behind an access group: the alerts read the map as a viewer with no
  // group, so nothing reaches it, whatever watches its collections or network
  // unmanaged (not ours to watch), or behind an access group: no rule sends
  // for it, whatever watches its collections or network (2026-11-14)
  const heldBy = row.unmanaged ? 'nodes_bell_unmanaged'
    : (AlertStore.ALERTS.body?.status?.held || []).includes(row.id) ? 'nodes_bell_held' : '';
  if (heldBy) {
    const held = t(heldBy, { name });
    return `<button type="button" class="nv-bell nv-bell-held${on ? ' on' : ''}" data-alerts="place" ` +
      `data-id="${esc(row.id)}" aria-pressed="${on}" aria-label="${esc(held)}" title="${esc(held)}">${BELL}` +
      `<span class="nv-bell-n">×</span></button>`;
  }
  const cover = AM.rulesCovering(rules, row);
  const label = cover.count ? t('nodes_bell_place', { name, n: cover.count }) : t('nodes_bell_none', { name });
  return `<button type="button" class="nv-bell${cover.on ? ' nv-bell-lit' : ''}${on ? ' on' : ''}" data-alerts="place" ` +
    `data-id="${esc(row.id)}" aria-pressed="${on}" aria-label="${esc(label)}" title="${esc(label)}">${BELL}` +
    `<span class="nv-bell-n">${cover.count || ''}</span></button>`;
}

/** Open (or, pressed again, shut) the alerts on one thing; the bells redraw. */
export function pressBell(kind, id) {
  // the panel's `moved` (opening) and `shut` (a second press) redraw the bells
  Rules.openFor({ kind, id });
}

/* ── the cells ───────────────────────────────────────────────────────────── */

export const stateOf = (row) => R.rowState(row);   // `unmanaged`, a state, or `unknown`

export function stateCell(row) {
  const s = stateOf(row);
  const word = t(`nodes_state_${s}`);
  const cause = row.cause ? ` title="${esc(row.cause)}"` : '';
  return `<span class="nv-state"${cause}><span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>${esc(word)}</span>`;
}

export function reviewedCell(row, now) {
  if (!row.reviewed) return `<span class="nv-quiet">${esc(t('nodes_never'))}</span>`;
  const d = R.daysSince(row.reviewed_at, now);
  let text = d === null ? t('nodes_checked_undated')
    : d <= 0 ? t('nodes_checked_today') : d === 1 ? t('nodes_checked_1') : t('nodes_checked_ago', { n: d });
  if (row.reviewed_by) text += ` ${t('nodes_by', { who: row.reviewed_by })}`;
  if (row.changed_since_review) text += t('nodes_changed_since');
  return `<span${row.reviewed_at ? ` title="${esc(row.reviewed_at)}"` : ''}>${esc(text)}</span>`;
}

const utc = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
};

export function maintenanceCell(row) {
  const m = row.maintenance || {};
  if (m.now && !blank(m.mode_since)) {
    // maintenance mode has no end: how long it has been on, amber past a
    // week (the digest's guard, which runs only with alerts on)
    const days = Math.max(0, Math.floor((Date.now() - Date.parse(m.mode_since)) / 86400000));
    const long = days > 7;
    return `<span class="nv-now${long ? ' nv-mode-long' : ''}" title="${esc(t('nodes_maint_mode_title', { when: utc(m.mode_since) }))}">` +
      `${esc(days === 0 ? t('nodes_maint_mode_today') : t('nodes_maint_mode', { n: days }))}</span>`;
  }
  if (m.now) {
    const why = typeof m.now === 'string' ? ` title="${esc(m.now)}"` : '';
    return `<span class="nv-now"${why}>${esc(t('nodes_maint_now'))}</span>`;
  }
  if (!blank(m.next)) return `<span class="nv-mono nv-maint">${esc(t('nodes_maint_next', { when: utc(m.next) }))}</span>`;
  return dim;
}

export function certCell(row) {
  const c = row.cert;
  if (!c || typeof c.days !== 'number') return dim;
  const name = c.name || '';
  const text = c.days < 0 ? t('nodes_cert_lapsed', { name })
    : c.days === 1 ? t('nodes_cert_1day', { name }) : t('nodes_cert_days', { name, n: c.days });
  const tone = R.certTone(c.days);
  return `<span class="nv-cert${tone ? ` nv-cert-${tone}` : ''}"${c.expires ? ` title="${esc(c.expires)}"` : ''}>${esc(text)}</span>`;
}

export function collectionsCell(row) {
  const names = new Map((S.roster?.collections || []).map((s) => [s.id, s.name || s.id]));
  const list = (row.collections || []).map((id) => names.get(id) || id);
  return list.length ? esc(list.join(', ')) : dim;
}

export const text = (v) => (blank(v) ? dim : esc(v));

/** Which source gave a place its state, in words; "nothing" for a place no
    source has a word for (an unmanaged one is nobody's to watch: a dash). */
export function watchedCell(row) {
  const by = row.confirmed_by;
  if (blank(by)) return row.unmanaged ? dim : `<span class="nv-quiet">${esc(t('nodes_by_nothing'))}</span>`;
  return esc(watcherWords(by));
}

/** Who watches a place, in words (a source the words know, else its own
    name); '' when nothing does. The column's, and a phone's sheet's
    (2026-11-16). */
export function watcherWords(by) {
  if (blank(by)) return '';
  const key = `nodes_by_${by}`;
  return Object.prototype.hasOwnProperty.call(NODES_TEXT, key) ? t(key) : String(by);
}

export const kindCell = (row) => (blank(row.kind) && blank(row.role) ? dim
  : esc([row.kind, row.role].filter((v) => !blank(v)).join(' · ')));
export const addressCell = (row) => ((row.addresses || []).length
  ? `<span class="nv-mono">${esc(row.addresses.join(', '))}</span>` : dim);
export const servicesLine = (n) => (n === 1 ? t('nodes_services_one') : t('nodes_services_many', { n }));
