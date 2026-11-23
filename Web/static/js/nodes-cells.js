
import { A, esc } from './config.js';
import * as R from './roster-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import * as Rules from './alert-rules.js';
import { NODES_TEXT, t } from './nodes-text.js';
import { DOT, S, phone, dim, blank } from './nodes-state.js';

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

export function pressBell(kind, id) {
  Rules.openFor({ kind, id });
}


export const stateOf = (row) => R.rowState(row);

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

export function watchedCell(row) {
  const by = row.confirmed_by;
  if (blank(by)) return row.unmanaged ? dim : `<span class="nv-quiet">${esc(t('nodes_by_nothing'))}</span>`;
  return esc(watcherWords(by));
}

export function watcherWords(by) {
  if (blank(by)) return '';
  const key = `nodes_by_${by}`;
  return Object.prototype.hasOwnProperty.call(NODES_TEXT, key) ? t(key) : String(by);
}

const deviceWord = (row) => (blank(row.device) || String(row.role || '').toLowerCase()
  .includes(String(row.device).replace(/-/g, ' ')) ? '' : String(row.device).replace(/-/g, ' '));
export const kindCell = (row) => (blank(row.kind) && blank(row.role) && blank(row.device) ? dim
  : esc([row.kind, deviceWord(row), row.role].filter((v) => !blank(v)).join(' · ')));
export const addressCell = (row) => ((row.addresses || []).length
  ? `<span class="nv-mono">${esc(row.addresses.join(', '))}</span>` : dim);
export const servicesLine = (n) => (n === 1 ? t('nodes_services_one') : t('nodes_services_many', { n }));
