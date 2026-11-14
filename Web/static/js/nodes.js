/* NODES (2026-11-13) — one table of every place the viewer may see.

   A view under ATLAS (views.js shows `#view-nodes` in the map's place). The
   rows come from the server (`api/v2/places/roster`), built and redacted
   there, so a hidden place never reaches this file. A row opens the map's own
   card; nothing here draws a form of its own.

   The rules (sorting, filtering, what is waiting for a person, the two-press
   "mark as checked", the batches of 400, what this browser remembers) are
   roster-model.js, shared with the Desk. Every write goes through the
   editor's store (editor/store.js), the same path the Desk's own saves take:
   `/admin/ops` under the dataset's stamp, and `/admin/maintenance` under the
   repairs' stamp. The bulk actions are drawn only where the Desk itself would
   open (`body[data-editable]`), and never on a phone.

   Every visible word is theme text (`nodes_*`), with the plain fallback in
   NODES_TEXT below. The look is views.css. */

import { A, $, esc, themeText, canAdminWrite } from './config.js';
import * as R from './roster-model.js';
import { parseSet } from './views-model.js';
import Editor, { EditorError } from './editor/store.js';
import { inputToIso, isoToInput } from './editor/form-model.js';

/** Every visible string, by theme key, with its plain fallback. `{n}` and the
    like are filled in by `t`. */
export const NODES_TEXT = {
  nodes_sub: 'every place you may see, as the map has it now',
  nodes_loading: 'Reading the places…',
  nodes_failed: 'The places could not be read: {why}',
  nodes_count: '{shown} of {total} places',
  nodes_count_all: '{total} places',
  nodes_count_one: '1 place',
  nodes_search: 'Search names, addresses, roles, networks…',
  nodes_search_label: 'Search the places',
  nodes_any_state: 'Any state',
  nodes_any_zone: 'Any network',
  nodes_any_kind: 'Any kind',
  nodes_any_set: 'Any set',
  nodes_state_healthy: 'Up',
  nodes_state_degraded: 'Degraded',
  nodes_state_down: 'Down',
  nodes_state_maintenance: 'In maintenance',
  nodes_state_slumbering: 'Asleep',
  nodes_state_unknown: 'Not known',
  nodes_unchecked: 'Not checked yet',
  nodes_stale: 'Not checked in 90 days',
  nodes_clear: 'Clear the filter',
  nodes_save: 'Save this filter',
  nodes_save_name: 'Name this filter',
  nodes_save_go: 'Save',
  nodes_saved_label: 'Saved filters',
  nodes_saved_forget: 'Forget {name}',
  nodes_col_state: 'State',
  nodes_col_name: 'Name',
  nodes_col_zone: 'Network',
  nodes_col_kind: 'Kind',
  nodes_col_addresses: 'Addresses',
  nodes_col_services: 'Services',
  nodes_col_confirmed: 'Confirmed by',
  nodes_col_reviewed: 'Reviewed',
  nodes_col_maintenance: 'Maintenance',
  nodes_col_cert: 'Certificate',
  nodes_col_sets: 'Sets',
  nodes_sort_by: 'Sort by {col}',
  nodes_none: 'No place matches this filter.',
  nodes_empty: 'There are no places on the map yet.',
  nodes_open: 'Open its card',
  nodes_not_drawn: 'That place is not on the map yet. Try again in a moment.',
  nodes_never: 'never checked',
  nodes_checked_today: 'checked today',
  nodes_checked_1: 'checked yesterday',
  nodes_checked_ago: 'checked {n} days ago',
  nodes_checked_undated: 'checked, date not kept',
  nodes_by: 'by {who}',
  nodes_changed_since: ', changed since',
  nodes_maint_now: 'now',
  nodes_maint_next: 'next {when}',
  nodes_cert_days: '{name} · {n} days',
  nodes_cert_1day: '{name} · 1 day',
  nodes_cert_lapsed: '{name} · lapsed',
  nodes_services_one: '1 service',
  nodes_services_many: '{n} services',
  nodes_select_all: 'Select every place shown',
  nodes_select: 'Select {name}',
  nodes_selected: '{n} selected',
  nodes_clear_sel: 'Clear the selection',
  nodes_bulk_review: 'Mark as checked',
  nodes_armed_one: 'Yes, I have checked this one',
  nodes_armed_many: 'Yes, I have checked these {n}',
  nodes_marked_one: 'Marked as checked.',
  nodes_marked_many: '{n} marked as checked.',
  nodes_bulk_maint: 'Open a maintenance window',
  nodes_bulk_set_add: 'Add to a set',
  nodes_bulk_set_out: 'Take out of a set',
  nodes_bulk_hide: 'Hide from everyone outside…',
  nodes_bulk_needs: 'Set what these need',
  nodes_cancel: 'Cancel',
  nodes_saving: 'Saving…',
  nodes_m_reason: 'What the work is',
  nodes_m_start: 'Opens (UTC)',
  nodes_m_end: 'Closes (UTC)',
  nodes_m_repeat: 'Repeats',
  nodes_r_none: 'Does not repeat',
  nodes_r_daily: 'Every day',
  nodes_r_weekly: 'Every week',
  nodes_r_monthly: 'Every month',
  nodes_m_go: 'Open the window',
  nodes_m_need: 'Say what the work is, and when it opens and closes.',
  nodes_m_order: 'It has to close after it opens.',
  nodes_m_done_one: 'Maintenance window opened for 1 place.',
  nodes_m_done_many: 'Maintenance window opened for {n} places.',
  nodes_s_pick: 'Which set',
  nodes_s_new_opt: 'A new set…',
  nodes_s_new: 'Name the new set',
  nodes_s_add_go: 'Add them',
  nodes_s_out_go: 'Take them out',
  nodes_s_added: 'Added to {set}.',
  nodes_s_removed: 'Taken out of {set}.',
  nodes_s_none: 'There are no sets yet.',
  nodes_s_name_needed: 'Name the new set.',
  nodes_s_unchanged: 'Nothing to change: {set} already says so.',
  nodes_h_label: 'Hide these from everyone outside the access group named',
  nodes_h_placeholder: 'access group name',
  nodes_h_go: 'Hide them',
  nodes_h_done: 'Hidden from everyone outside {group}.',
  nodes_h_needed: 'Name the access group that may still see them.',
  nodes_n_label: 'These places need',
  nodes_n_go: 'Save what they need',
  nodes_n_done_one: 'Saved what 1 place needs.',
  nodes_n_done_many: 'Saved what {n} places need.',
  nodes_n_needed: 'Pick at least one place they need.',
  nodes_n_unchanged: 'Nothing to change: they already say so.',
  nodes_stamps: 'Like a save in the map editor, this also marks them as checked.',
  nodes_stale_table: 'The map changed since this table was drawn. It has been drawn again: check the selection and press again.',
  nodes_readonly: 'This Atlas is read-only. Nothing here will save.',
  nodes_editor_failed: 'The map editor could not be opened: {why}',
  nodes_phone_bulk: 'Bulk actions need a wider screen.',
};

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
function t(key, vars = {}) {
  return themeText(key, NODES_TEXT[key] || '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown'];
const DOT = { healthy: 'h-up', degraded: 'h-degraded', down: 'h-down', maintenance: 'h-maint', slumbering: 'h-slumber' };
const REPEATS = ['none', 'daily', 'weekly', 'monthly'];

/** The columns, in order, and the roster-model key each sorts on. */
const COLUMNS = [
  ['state', 'nodes_col_state'], ['name', 'nodes_col_name'], ['zone', 'nodes_col_zone'],
  ['kind', 'nodes_col_kind'], ['addresses', 'nodes_col_addresses'], ['services', 'nodes_col_services'],
  ['confirmed_by', 'nodes_col_confirmed'], ['reviewed', 'nodes_col_reviewed'],
  ['maintenance', 'nodes_col_maintenance'], ['cert', 'nodes_col_cert'], ['sets', 'nodes_col_sets'],
];

let store = null;
try { store = localStorage; } catch { /* blocked: nothing is remembered */ }

const S = {
  roster: null,        // the last answer, normalised
  error: '',
  filter: { ...R.NO_FILTER },
  sort: R.readSort(store),
  saved: R.readSaved(store),
  selected: new Set(),
  shown: [],           // ids on screen, in order
  form: '',            // which bulk form is open: '', maint, set-add, set-out, hide, needs
  naming: false,       // the "name this filter" box is out
  arm: R.twoPress(),
  busy: false,
  msg: null,           // {kind: info|warn|bad, text, problems?}
};

let root = null;
let el = {};

const phone = () => document.body.classList.contains('phone');
/** The Desk's own gate (editor/index.js): an admin on an instance that writes. */
const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
const dim = '<span class="nv-dim">—</span>';
const blank = (v) => v === null || v === undefined || v === '';

/* ── the data ────────────────────────────────────────────────────────────── */

function normalise(body) {
  const b = body && typeof body === 'object' ? body : {};
  const list = (v) => (Array.isArray(v) ? v : []);
  return {
    stamp: b.stamp || null,
    zones: list(b.zones),
    sets: list(b.sets),
    rows: list(b.rows).filter((r) => r && typeof r.id === 'string'),
  };
}

async function fetchRoster() {
  const res = await fetch('api/v2/places/roster', { cache: 'no-store' });
  let body = null;
  try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
  if (!res.ok) throw new Error(body?.error || `${res.status} ${res.statusText}`);
  return normalise(body);
}

let inflight = null;
let again = false;
/** Read the roster again and redraw. Calls that land while one is reading
    share it, and one more read follows if any did. */
function refresh() {
  hookRefresh();   // a page that opens on NODES shows before atlas.js has assigned it
  if (inflight) { again = true; return inflight; }
  inflight = (async () => {
    do {
      again = false;
      try { S.roster = await fetchRoster(); S.error = ''; } catch (err) { S.error = err.message || String(err); }
    } while (again);
    inflight = null;
    hookRefresh();   // and again once the read is back: by then atlas.js has run
    const known = new Set((S.roster?.rows || []).map((r) => r.id));
    for (const id of [...S.selected]) if (!known.has(id)) S.selected.delete(id);
    draw();
  })();
  return inflight;
}

/** The map's own refresh (atlas.js, after every Desk write) redraws this table
    too while it is up. Wrapped on first show: atlas.js assigns it after every
    module has loaded, so it does not exist yet when this file runs. */
let pendingWhileBusy = false;
function hookRefresh() {
  const original = A.refreshData;
  if (typeof original !== 'function' || original.nodesHooked) return;
  const wrapped = async function refreshData(...args) {
    const out = await original.apply(this, args);
    if (A.VIEW === 'nodes') { if (S.busy) pendingWhileBusy = true; else refresh(); }
    return out;
  };
  wrapped.nodesHooked = true;
  A.refreshData = wrapped;
}

/* ── the frame: built once ───────────────────────────────────────────────── */

function build() {
  root = $('view-nodes');
  if (!root || el.sheet) return Boolean(root);
  const set = parseSet(new URLSearchParams(location.search).get('set'));
  if (set) S.filter.set = set;

  root.innerHTML = `
    <div class="nv-sheet">
      <header class="nv-head">
        <h2 class="nv-title">${esc(themeText('view_nodes', 'NODES'))}</h2>
        <p class="nv-sub">${esc(t('nodes_sub'))}</p>
        <span class="nv-count" aria-live="polite"></span>
      </header>
      <div class="nv-filters" role="search">
        <input class="dsk-input nv-search" type="search" placeholder="${esc(t('nodes_search'))}" aria-label="${esc(t('nodes_search_label'))}">
        <select class="dsk-input nv-pick" data-f="state" aria-label="${esc(t('nodes_col_state'))}"></select>
        <select class="dsk-input nv-pick" data-f="zone" aria-label="${esc(t('nodes_col_zone'))}"></select>
        <select class="dsk-input nv-pick" data-f="kind" aria-label="${esc(t('nodes_col_kind'))}"></select>
        <select class="dsk-input nv-pick" data-f="set" aria-label="${esc(t('nodes_col_sets'))}"></select>
        <label class="nv-toggle"><input type="checkbox" class="dsk-check" data-f="unchecked"> ${esc(t('nodes_unchecked'))}</label>
        <label class="nv-toggle"><input type="checkbox" class="dsk-check" data-f="stale"> ${esc(t('nodes_stale'))}</label>
        <button type="button" class="dsk-btn dsk-btn-sm nv-clear">${esc(t('nodes_clear'))}</button>
        <span class="nv-save"></span>
      </div>
      <div class="nv-saved" aria-label="${esc(t('nodes_saved_label'))}"></div>
      <div class="nv-bulk"></div>
      <div class="nv-msg" aria-live="polite"></div>
      <div class="nv-results"></div>
    </div>`;
  el = {
    sheet: root.querySelector('.nv-sheet'),
    count: root.querySelector('.nv-count'),
    search: root.querySelector('.nv-search'),
    picks: [...root.querySelectorAll('.nv-pick')],
    unchecked: root.querySelector('[data-f="unchecked"]'),
    stale: root.querySelector('[data-f="stale"]'),
    clear: root.querySelector('.nv-clear'),
    save: root.querySelector('.nv-save'),
    saved: root.querySelector('.nv-saved'),
    bulk: root.querySelector('.nv-bulk'),
    msg: root.querySelector('.nv-msg'),
    results: root.querySelector('.nv-results'),
  };

  el.search.value = S.filter.text;
  el.search.addEventListener('input', () => setFilter({ text: el.search.value }));
  for (const sel of el.picks) sel.addEventListener('change', () => setFilter({ [sel.dataset.f]: sel.value }));
  el.unchecked.addEventListener('change', () => setFilter({ unchecked: el.unchecked.checked }));
  el.stale.addEventListener('change', () => setFilter({ staleDays: el.stale.checked ? 90 : 0 }));
  el.clear.addEventListener('click', () => { applyFilter({ ...R.NO_FILTER }); el.search.focus(); });

  el.results.addEventListener('click', onResultsClick);
  el.results.addEventListener('change', onResultsChange);
  return true;
}

/* ── filters, sorts and the saved ones ───────────────────────────────────── */

function setFilter(patch) {
  S.filter = { ...S.filter, ...patch };
  S.msg = null;
  drawResults();
}

/** Put a whole filter on screen: the boxes, then the table. */
function applyFilter(filter, sort) {
  S.filter = { ...R.NO_FILTER, ...R.cleanFilter(filter) };
  if (sort) { S.sort = { ...sort }; R.writeSort(store, S.sort); }
  syncFilterBoxes();
  S.msg = null;
  drawResults();
}

function syncFilterBoxes() {
  if (!el.sheet) return;
  el.search.value = S.filter.text;
  for (const sel of el.picks) sel.value = S.filter[sel.dataset.f] || '';
  el.unchecked.checked = S.filter.unchecked;
  el.stale.checked = Number(S.filter.staleDays) > 0;
}

function fillPick(sel, first, options) {
  const want = S.filter[sel.dataset.f] || '';
  const known = options.some(([v]) => v === want);
  // before the roster arrives, `?set=` keeps its place with its id for a name
  const shown = want && !known && !S.roster ? [...options, [want, want]] : options;
  sel.innerHTML = `<option value="">${esc(first)}</option>` +
    shown.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  // a filter naming something that is not here (an old saved filter, a set
  // the viewer may not see) shows everything rather than nothing, silently
  if (want && !known && S.roster) S.filter[sel.dataset.f] = '';
  sel.value = S.filter[sel.dataset.f] || '';
}

function drawPicks() {
  const r = S.roster || { zones: [], sets: [], rows: [] };
  const kinds = [...new Set(r.rows.map((x) => x.kind).filter((k) => !blank(k)))].sort();
  const options = {
    state: [STATES.map((s) => [s, t(`nodes_state_${s}`)]), 'nodes_any_state'],
    zone: [r.zones.map((z) => [z.id, z.name || z.id]), 'nodes_any_zone'],
    kind: [kinds.map((k) => [k, k]), 'nodes_any_kind'],
    set: [r.sets.map((s) => [s.id, s.name || s.id]), 'nodes_any_set'],
  };
  for (const sel of el.picks) {
    const [opts, any] = options[sel.dataset.f];
    fillPick(sel, t(any), opts);
  }
}

function drawSaved() {
  el.saved.innerHTML = S.saved.map((s, i) =>
    `<span class="nv-chip-wrap"><button type="button" class="nv-chip" data-saved="${i}">${esc(s.name)}</button>` +
    `<button type="button" class="nv-chip-x" data-forget="${i}" aria-label="${esc(t('nodes_saved_forget', { name: s.name }))}" ` +
    `title="${esc(t('nodes_saved_forget', { name: s.name }))}">×</button></span>`).join('');
  el.saved.hidden = !S.saved.length;
  el.saved.onclick = (e) => {
    const use = e.target.closest('[data-saved]');
    const forget = e.target.closest('[data-forget]');
    if (use) { const s = S.saved[Number(use.dataset.saved)]; if (s) applyFilter(s.filter, s.sort); }
    if (forget) {
      const s = S.saved[Number(forget.dataset.forget)];
      if (!s) return;
      S.saved = R.withoutSaved(S.saved, s.name);
      R.writeSaved(store, S.saved);
      drawSaved();
    }
  };

  // Save this filter: one press opens a name box, Enter or Save keeps it
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
  };
  name.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); keep(); }
    if (e.key === 'Escape') { e.stopPropagation(); S.naming = false; drawSaved(); }
  });
  el.save.append(name, button('dsk-btn dsk-btn-sm dsk-btn-go', t('nodes_save_go'), keep),
    button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { S.naming = false; drawSaved(); }));
}

/* ── the cells ───────────────────────────────────────────────────────────── */

const stateOf = (row) => (DOT[row.state] ? row.state : 'unknown');

function stateCell(row) {
  const s = stateOf(row);
  const word = t(`nodes_state_${s}`);
  const cause = row.cause ? ` title="${esc(row.cause)}"` : '';
  return `<span class="nv-state"${cause}><span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>${esc(word)}</span>`;
}

function reviewedCell(row, now) {
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

function maintenanceCell(row) {
  const m = row.maintenance || {};
  if (m.now) {
    const why = typeof m.now === 'string' ? ` title="${esc(m.now)}"` : '';
    return `<span class="nv-now"${why}>${esc(t('nodes_maint_now'))}</span>`;
  }
  if (!blank(m.next)) return `<span class="nv-mono nv-maint">${esc(t('nodes_maint_next', { when: utc(m.next) }))}</span>`;
  return dim;
}

function certCell(row) {
  const c = row.cert;
  if (!c || typeof c.days !== 'number') return dim;
  const name = c.name || '';
  const text = c.days < 0 ? t('nodes_cert_lapsed', { name })
    : c.days === 1 ? t('nodes_cert_1day', { name }) : t('nodes_cert_days', { name, n: c.days });
  const tone = R.certTone(c.days);
  return `<span class="nv-cert${tone ? ` nv-cert-${tone}` : ''}"${c.expires ? ` title="${esc(c.expires)}"` : ''}>${esc(text)}</span>`;
}

function setsCell(row) {
  const names = new Map((S.roster?.sets || []).map((s) => [s.id, s.name || s.id]));
  const list = (row.sets || []).map((id) => names.get(id) || id);
  return list.length ? esc(list.join(', ')) : dim;
}

const text = (v) => (blank(v) ? dim : esc(v));
const kindCell = (row) => (blank(row.kind) && blank(row.role) ? dim
  : esc([row.kind, row.role].filter((v) => !blank(v)).join(' · ')));
const addressCell = (row) => ((row.addresses || []).length
  ? `<span class="nv-mono">${esc(row.addresses.join(', '))}</span>` : dim);
const servicesLine = (n) => (n === 1 ? t('nodes_services_one') : t('nodes_services_many', { n }));

/* ── the table, or the phone's cards ─────────────────────────────────────── */

function drawCount(shown, total) {
  el.count.textContent = !S.roster ? ''
    : shown === total ? (total === 1 ? t('nodes_count_one') : t('nodes_count_all', { total }))
      : t('nodes_count', { shown, total });
}

function drawResults() {
  if (!el.sheet) return;
  el.clear.hidden = R.isEmptyFilter(S.filter);
  drawSaved();
  drawMessage();

  if (!S.roster) {
    el.results.innerHTML = S.error
      ? `<div class="dsk-notice dsk-notice-bad">${esc(t('nodes_failed', { why: S.error }))}</div>`
      : `<div class="dsk-notice">${esc(t('nodes_loading'))}</div>`;
    drawCount(0, 0);
    drawBulk();
    return;
  }
  const now = Date.now();
  const all = S.roster.rows;
  const rows = R.sortRows(R.filterRows(all, S.filter, now), S.sort.key, S.sort.dir, S.roster.sets);
  S.shown = rows.map((r) => r.id);
  // a selection only ever holds rows on screen: what a bulk action writes is what you can see
  const onScreen = new Set(S.shown);
  let dropped = false;
  for (const id of [...S.selected]) if (!onScreen.has(id)) { S.selected.delete(id); dropped = true; }
  if (dropped) S.arm.disarm();
  drawCount(rows.length, all.length);

  if (!all.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_empty'))}</div>`;
  else if (!rows.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_none'))}</div>`;
  else if (phone()) el.results.innerHTML = cardsHTML(rows);
  else el.results.innerHTML = tableHTML(rows, now);
  if (S.error) el.results.insertAdjacentHTML('afterbegin',
    `<div class="dsk-notice dsk-notice-warn">${esc(t('nodes_failed', { why: S.error }))}</div>`);
  syncSelectAll();
  drawBulk();
}

function tableHTML(rows, now) {
  const admin = mayWrite();
  const head = COLUMNS.map(([key, label]) => {
    const on = S.sort.key === key;
    const sort = on ? (S.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none';
    return `<th scope="col" aria-sort="${sort}" class="nv-th-${key}"><button type="button" class="nv-sort${on ? ' on' : ''}" ` +
      `data-sort="${key}" title="${esc(t('nodes_sort_by', { col: t(label) }))}">${esc(t(label))}</button></th>`;
  }).join('');
  const pickHead = admin
    ? `<th class="dsk-th-pick" scope="col"><input type="checkbox" class="dsk-check nv-all" aria-label="${esc(t('nodes_select_all'))}"></th>` : '';
  const body = rows.map((row) => {
    const standing = R.rowStanding(row);
    const pick = admin
      ? `<td class="dsk-td-pick"><input type="checkbox" class="dsk-check nv-pick-row" data-id="${esc(row.id)}" ` +
        `${S.selected.has(row.id) ? 'checked ' : ''}aria-label="${esc(t('nodes_select', { name: row.name || row.id }))}"></td>` : '';
    return `<tr data-id="${esc(row.id)}" data-standing="${standing}" class="nv-row${standing === 'checked' ? '' : ` dsk-p-${standing}`}${S.selected.has(row.id) ? ' nv-on' : ''}">` +
      pick +
      `<td>${stateCell(row)}</td>` +
      `<td><button type="button" class="nv-name" data-open="${esc(row.id)}" title="${esc(t('nodes_open'))}">${esc(row.name || row.id)}</button></td>` +
      `<td>${text(row.zone_name || row.zone)}</td>` +
      `<td>${kindCell(row)}</td>` +
      `<td>${addressCell(row)}</td>` +
      `<td class="nv-num">${typeof row.services === 'number' ? `<span class="nv-mono">${row.services}</span>` : dim}</td>` +
      `<td>${text(row.confirmed_by)}</td>` +
      `<td>${reviewedCell(row, now)}</td>` +
      `<td>${maintenanceCell(row)}</td>` +
      `<td>${certCell(row)}</td>` +
      `<td>${setsCell(row)}</td>` +
      '</tr>';
  }).join('');
  return `<div class="nv-scroll"><table class="dsk-table nv-table"><thead><tr>${pickHead}${head}</tr></thead>` +
    `<tbody>${body}</tbody></table></div>`;
}

function cardsHTML(rows) {
  return `<ul class="nv-cards">${rows.map((row) => {
    const s = stateOf(row);
    const first = (row.addresses || [])[0];
    const services = typeof row.services === 'number' ? servicesLine(row.services) : '';
    return `<li><button type="button" class="nv-card" data-open="${esc(row.id)}">` +
      `<span class="nv-card-top"><span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>` +
      `<span class="nv-name-text">${esc(row.name || row.id)}</span>` +
      `<span class="nv-sr">${esc(t(`nodes_state_${s}`))}</span></span>` +
      `<span class="nv-card-line">${esc(row.zone_name || row.zone || '')}` +
      `${first ? ` <span class="nv-mono">${esc(first)}</span>` : ''}` +
      `${services ? ` <span class="nv-dim">${esc(services)}</span>` : ''}</span>` +
      '</button></li>';
  }).join('')}</ul>`;
}

function syncSelectAll() {
  const all = el.results.querySelector('.nv-all');
  if (!all) return;
  const n = S.shown.filter((id) => S.selected.has(id)).length;
  all.checked = n > 0 && n === S.shown.length;
  all.indeterminate = n > 0 && n < S.shown.length;
}

function openCard(id) {
  const node = A.DATA?.nodes?.find((n) => n.id === id);
  if (!node || typeof A.openCard !== 'function') { A.showToast?.(t('nodes_not_drawn')); return; }
  A.openCard(node);
}

function onResultsClick(e) {
  const sort = e.target.closest('[data-sort]');
  if (sort) {
    const key = sort.dataset.sort;
    S.sort = { key, dir: S.sort.key === key && S.sort.dir === 'asc' ? 'desc' : 'asc' };
    R.writeSort(store, S.sort);
    drawResults();
    el.results.querySelector(`[data-sort="${key}"]`)?.focus();
    return;
  }
  if (e.target.closest('input, label, a, .dsk-td-pick')) return;   // a checkbox selects, it does not open
  const open = e.target.closest('[data-open]') || e.target.closest('tr[data-id]');
  if (open) openCard(open.dataset.open || open.dataset.id);
}

function onResultsChange(e) {
  const box = e.target;
  if (box.classList.contains('nv-all')) {
    for (const id of S.shown) { if (box.checked) S.selected.add(id); else S.selected.delete(id); }
  } else if (box.classList.contains('nv-pick-row')) {
    if (box.checked) S.selected.add(box.dataset.id); else S.selected.delete(box.dataset.id);
  } else return;
  S.arm.disarm();
  for (const tr of el.results.querySelectorAll('tr[data-id]')) {
    const on = S.selected.has(tr.dataset.id);
    tr.classList.toggle('nv-on', on);
    const cb = tr.querySelector('.nv-pick-row');
    if (cb) cb.checked = on;
  }
  syncSelectAll();
  drawBulk();
}

/* ── messages ────────────────────────────────────────────────────────────── */

function tell(textOrErr, kind = 'info') {
  if (textOrErr instanceof Error) {
    const problems = (textOrErr.problems || []).filter((p) => p !== textOrErr.message);
    S.msg = { kind: 'bad', text: textOrErr.message || 'That could not be saved.', problems };
  } else {
    S.msg = textOrErr ? { kind, text: textOrErr, problems: [] } : null;
  }
  drawMessage();
}

function drawMessage() {
  if (!el.msg) return;
  const m = S.msg;
  el.msg.innerHTML = !m ? '' : `<div class="dsk-notice dsk-notice-${m.kind}">${esc(m.text)}` +
    (m.problems?.length ? `<ul class="dsk-problems">${m.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
    '</div>';
}

/* ── the bulk actions (an admin, a wide screen) ──────────────────────────── */

function button(cls, label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

function selectedIds() { return S.shown.filter((id) => S.selected.has(id)); }

function drawBulk() {
  const bar = el.bulk;
  bar.innerHTML = '';
  bar.className = 'nv-bulk';
  if (!mayWrite()) { bar.hidden = true; return; }
  if (phone()) {
    bar.hidden = false;
    bar.classList.add('nv-bulk-note');
    bar.textContent = t('nodes_phone_bulk');
    return;
  }
  const ids = selectedIds();
  bar.hidden = !ids.length;
  if (!ids.length) { S.form = ''; formEl = null; formFor = ''; return; }

  const row = document.createElement('div');
  row.className = 'nv-bulk-row';
  const count = document.createElement('span');
  count.className = 'nv-bulk-n';
  count.textContent = t('nodes_selected', { n: ids.length });
  row.append(count);

  const armed = S.arm.armed;
  const review = button(`dsk-btn dsk-btn-sm nv-review${armed ? ' dsk-btn-go' : ''}`,
    armed ? (armed.length === 1 ? t('nodes_armed_one') : t('nodes_armed_many', { n: armed.length })) : t('nodes_bulk_review'),
    () => markChecked());
  row.append(review);
  for (const [form, key] of [['maint', 'nodes_bulk_maint'], ['set-add', 'nodes_bulk_set_add'],
    ['set-out', 'nodes_bulk_set_out'], ['hide', 'nodes_bulk_hide'], ['needs', 'nodes_bulk_needs']]) {
    const b = button(`dsk-btn dsk-btn-sm${S.form === form ? ' on' : ''}`, t(key), () => {
      S.form = S.form === form ? '' : form;
      S.arm.disarm();
      drawBulk();
      bar.querySelector('.nv-form input, .nv-form select')?.focus();
    });
    b.setAttribute('aria-expanded', String(S.form === form));
    row.append(b);
  }
  row.append(button('dsk-btn dsk-btn-sm nv-bulk-clear', t('nodes_clear_sel'), () => {
    S.selected.clear(); S.arm.disarm(); S.form = ''; drawResults();
  }));
  bar.append(row);
  for (const b of bar.querySelectorAll('button')) b.disabled = S.busy;

  // the open form survives a redraw (a tick, a search, a refresh) so nothing
  // typed into it is lost; a new one is built only when another is picked
  if (S.form !== formFor) { formEl = FORMS[S.form]?.(ids) || null; formFor = S.form; }
  if (formEl) {
    for (const b of formEl.querySelectorAll('button')) b.disabled = S.busy;
    bar.append(formEl);
  }
}

let formEl = null;
let formFor = '';

function field(labelText, control) {
  const label = document.createElement('label');
  label.className = 'nv-field';
  const span = document.createElement('span');
  span.className = 'nv-label';
  span.textContent = labelText;
  label.append(span, control);
  return label;
}

function input(type, value = '', cls = 'dsk-input') {
  const i = document.createElement('input');
  i.type = type;
  i.className = cls;
  i.value = value;
  return i;
}

function select(options, value = '') {
  const s = document.createElement('select');
  s.className = 'dsk-input';
  s.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  s.value = value;
  return s;
}

function formBox(fields, goLabel, onGo, note) {
  const box = document.createElement('form');
  box.className = 'nv-form';
  box.append(...fields);
  if (note) {
    const p = document.createElement('p');
    p.className = 'nv-form-note';
    p.textContent = note;
    box.append(p);
  }
  const bar = document.createElement('div');
  bar.className = 'nv-form-bar';
  const go = button('dsk-btn dsk-btn-sm dsk-btn-go', goLabel, () => {});
  go.type = 'submit';
  go.disabled = S.busy;
  bar.append(button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { S.form = ''; drawBulk(); }), go);
  box.append(bar);
  box.addEventListener('submit', (e) => { e.preventDefault(); if (!S.busy) onGo(); });
  box.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); S.form = ''; drawBulk(); } });
  return box;
}

const FORMS = {
  maint() {
    const now = new Date();
    now.setUTCSeconds(0, 0);
    const reason = input('text');
    reason.maxLength = 200;
    const start = input('datetime-local', isoToInput(now.toISOString()));
    const end = input('datetime-local', isoToInput(new Date(now.getTime() + 3600000).toISOString()));
    const repeat = select(REPEATS.map((r) => [r, t(`nodes_r_${r}`)]), 'none');
    return formBox([field(t('nodes_m_reason'), reason), field(t('nodes_m_start'), start),
      field(t('nodes_m_end'), end), field(t('nodes_m_repeat'), repeat)], t('nodes_m_go'),
    () => openWindow(selectedIds(), { reason: reason.value.trim(), start: start.value, end: end.value, repeat: repeat.value }));
  },
  'set-add'() { return setForm(true); },
  'set-out'() { return setForm(false); },
  hide() {
    const group = input('text');
    group.placeholder = t('nodes_h_placeholder');
    group.maxLength = 120;
    return formBox([field(t('nodes_h_label'), group)], t('nodes_h_go'),
      () => hide(selectedIds(), group.value.trim()), t('nodes_stamps'));
  },
  needs(ids) {
    const chosen = new Set(ids);
    const places = R.sortRows(S.roster?.rows || [], 'name', 'asc')
      .filter((r) => !(chosen.size === 1 && chosen.has(r.id)));
    const pick = select(places.map((r) => [r.id, r.name || r.id]));
    pick.multiple = true;
    pick.size = Math.min(8, Math.max(3, places.length));
    return formBox([field(t('nodes_n_label'), pick)], t('nodes_n_go'),
      () => needs(selectedIds(), [...pick.selectedOptions].map((o) => o.value)), t('nodes_stamps'));
  },
};

function setForm(adding) {
  const sets = S.roster?.sets || [];
  const options = sets.map((s) => [s.id, s.name || s.id]);
  if (adding) options.push(['', t('nodes_s_new_opt')]);
  const fields = [];
  if (!options.length) {
    const p = document.createElement('p');
    p.className = 'nv-form-note';
    p.textContent = t('nodes_s_none');
    const box = document.createElement('div');
    box.className = 'nv-form';
    box.append(p);
    return box;
  }
  const pick = select(options, options[0][0]);
  const name = input('text');
  name.maxLength = 80;
  const nameField = field(t('nodes_s_new'), name);
  nameField.hidden = pick.value !== '';
  pick.addEventListener('change', () => { nameField.hidden = pick.value !== ''; if (!nameField.hidden) name.focus(); });
  fields.push(field(t('nodes_s_pick'), pick));
  if (adding) fields.push(nameField);
  return formBox(fields, adding ? t('nodes_s_add_go') : t('nodes_s_out_go'),
    () => (adding ? addToSet(selectedIds(), pick.value, name.value.trim()) : takeOutOfSet(selectedIds(), pick.value)));
}

/* ── the writes ──────────────────────────────────────────────────────────── */

/** Open the editor's store (once), read the dataset fresh, and refuse to
    write over a table drawn from an older map: the roster's `stamp` is the
    dataset's, so a difference means somebody saved since this was drawn. */
async function ready() {
  try {
    if (!Editor.loaded) await Editor.load(); else await Editor.reload();
  } catch (err) {
    tell(t('nodes_editor_failed', { why: err.message || String(err) }), 'bad');
    return false;
  }
  if (!Editor.writable()) { tell(t('nodes_readonly'), 'warn'); return false; }
  if (S.roster?.stamp && Editor.stamp && S.roster.stamp !== Editor.stamp) {
    S.arm.disarm();
    await refresh();
    tell(t('nodes_stale_table'), 'warn');
    return false;
  }
  return true;
}

/** Someone else saved first (409): say so, read everything again, stop.
    The same three steps desk-kit.js `run()` takes, without redrawing the Desk. */
async function conflict(err) {
  A.showToast?.(err.message);
  try { await Editor.reload(); } catch { /* the next press loads it again */ }
  await refresh();
  tell(err.message, 'warn');
}

/** Run one write with the table held still, then draw it once from the server. */
async function busy(work) {
  if (S.busy) return;
  S.busy = true;
  drawBulk();
  try {
    await work();
  } catch (err) {
    if (err instanceof EditorError && err.status === 409) await conflict(err);
    else tell(err);
  } finally {
    S.busy = false;
    if (pendingWhileBusy) pendingWhileBusy = false;
    await refresh();
  }
}

/** Ops through the editor's store in saves of at most 400. A 409 part-way
    stops the run; the parts already saved stay saved. */
async function applyOps(ops, note) {
  return R.inBatches(ops, async (part) => {
    try {
      return await Editor.apply(part, note);
    } catch (err) {
      if (err instanceof EditorError && err.status === 409) { await conflict(err); return null; }
      throw err;
    }
  });
}

async function markChecked() {
  const step = S.arm.press(selectedIds);
  if (step.armed) { drawBulk(); el.bulk.querySelector('.nv-review')?.focus(); return; }
  if (!step.write) return;
  const ids = step.write;
  await busy(async () => {
    if (!(await ready())) return;
    const { done, stopped } = await applyOps(R.reviewOps(ids), 'marked as checked');
    if (stopped) return;
    const line = done === 1 ? t('nodes_marked_one') : t('nodes_marked_many', { n: done });
    A.showToast?.(line);
    tell(line);
  });
}

async function openWindow(ids, w) {
  if (!w.reason || !w.start || !w.end) { tell(t('nodes_m_need'), 'warn'); return; }
  const starts = inputToIso(w.start);
  const ends = inputToIso(w.end);
  if (!(Date.parse(ends) > Date.parse(starts))) { tell(t('nodes_m_order'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    // the repairs have their own stamp: read them now, so the list sent is
    // the list on disk with one window more, and a writer between is a 409
    await Editor.loadRepairs();
    const taken = Editor.entries('maintenance').map((x) => x.id);
    const entry = {
      id: R.slugFor(w.reason, taken, 'window'),
      reason: w.reason, nodes: ids, starts, ends,
      repeat: REPEATS.includes(w.repeat) ? w.repeat : 'none',
    };
    try {
      await Editor.saveEntry('maintenance', null, entry);
    } catch (err) {
      if (err instanceof EditorError && err.status === 409) {
        try { await Editor.loadRepairs(); } catch { /* the next press reads them again */ }
      }
      throw err;
    }
    S.form = '';
    const line = ids.length === 1 ? t('nodes_m_done_one') : t('nodes_m_done_many', { n: ids.length });
    A.showToast?.(line);
    tell(line);
  });
}

function setLabel(id) {
  const s = (S.roster?.sets || []).find((x) => x.id === id) || (Editor.data?.sets || []).find((x) => x.id === id);
  return s?.name || id;
}

async function addToSet(ids, setId, newName) {
  if (!setId && !newName) { tell(t('nodes_s_name_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const sets = Array.isArray(Editor.data?.sets) ? Editor.data.sets : [];
    let op;
    let label;
    if (setId) {
      const entry = sets.find((s) => s.id === setId);
      const before = Array.isArray(entry?.places) ? entry.places : [];
      const places = [...before, ...ids.filter((id) => !before.includes(id))];
      label = setLabel(setId);
      if (places.length === before.length) { tell(t('nodes_s_unchanged', { set: label })); return; }
      op = { op: 'upsert', section: 'sets', id: setId, body: { places } };
    } else {
      const id = R.slugFor(newName, sets.map((s) => s.id), 'set');
      label = newName;
      op = { op: 'insert', section: 'sets', body: { id, name: newName, places: ids } };
    }
    const { stopped } = await applyOps([op], 'added to a set');
    if (stopped) return;
    S.form = '';
    const line = t('nodes_s_added', { set: label });
    A.showToast?.(line);
    tell(line);
  });
}

async function takeOutOfSet(ids, setId) {
  await busy(async () => {
    if (!(await ready())) return;
    const entry = (Editor.data?.sets || []).find((s) => s.id === setId);
    const before = Array.isArray(entry?.places) ? entry.places : [];
    const places = before.filter((id) => !ids.includes(id));
    const label = setLabel(setId);
    if (!entry || places.length === before.length) { tell(t('nodes_s_unchanged', { set: label })); return; }
    const { stopped } = await applyOps([{ op: 'upsert', section: 'sets', id: setId, body: { places } }], 'taken out of a set');
    if (stopped) return;
    S.form = '';
    const line = t('nodes_s_removed', { set: label });
    A.showToast?.(line);
    tell(line);
  });
}

async function hide(ids, group) {
  if (!group) { tell(t('nodes_h_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const ops = ids.map((id) => ({ op: 'upsert', section: 'nodes', id, body: { require_group: group } }));
    const { stopped } = await applyOps(ops, 'hidden from everyone outside an access group');
    if (stopped) return;
    S.form = '';
    const line = t('nodes_h_done', { group });
    A.showToast?.(line);
    tell(line);
  });
}

async function needs(ids, picks) {
  if (!picks.length) { tell(t('nodes_n_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const onDisk = new Map((Editor.data?.nodes || []).map((n) => [n.id, n]));
    const ops = [];
    for (const id of ids) {
      const before = onDisk.get(id)?.depends_on;
      const merged = R.mergeNeeds(id, before, picks);
      const same = Array.isArray(before) && before.length === merged.length && merged.every((v, i) => v === before[i]);
      if (!same && merged.length) ops.push({ op: 'upsert', section: 'nodes', id, body: { depends_on: merged } });
    }
    if (!ops.length) { tell(t('nodes_n_unchanged')); return; }
    const { done, stopped } = await applyOps(ops, 'said what these places need');
    if (stopped) return;
    S.form = '';
    const line = done === 1 ? t('nodes_n_done_one') : t('nodes_n_done_many', { n: done });
    A.showToast?.(line);
    tell(line);
  });
}

/* ── showing ─────────────────────────────────────────────────────────────── */

function draw() {
  if (!el.sheet) return;
  drawPicks();
  syncFilterBoxes();
  drawResults();
}

/** The view came up: draw what is known at once, then read it fresh. */
function show() {
  if (!build()) return;
  hookRefresh();
  draw();
  refresh();
}

addEventListener('atlas:view', (e) => { if (e.detail?.view === 'nodes') show(); });
// atlas.js assigns A.refreshData once every module has run, which is before
// the page's DOMContentLoaded: wrap it then, whichever view the page opened on
addEventListener('DOMContentLoaded', hookRefresh, { once: true });
// the first view is chosen at import, before this file listens (views.js)
if (A.VIEW === 'nodes' || document.body.dataset.view === 'nodes') show();
