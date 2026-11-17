/* NODES (2026-11-13) — one table of every place the viewer may see.

   A view under ATLAS (views.js shows `#view-nodes` in the map's place). The
   rows come from the server (`api/v2/places/roster`), built and redacted
   there, so a hidden place never reaches this file. A row opens the map's own
   card; nothing here draws a form of its own.

   The rules (sorting, filtering, what is waiting for a person, the two-press
   "mark as checked", the batches of 400, what this browser remembers, the
   rail's counts) are roster-model.js, shared with the Desk.

   THE RAIL (2026-11-14): on a wide screen the table has a column down its
   left, in sections that open and shut: COLLECTIONS (named lists of places,
   which were called sets until that day), NETWORKS, KINDS and SAVED FILTERS.
   A row is a name, how many places in it this viewer may see, and a dot when
   something inside is down or degraded; pressing it filters the table to it,
   pressing it again shows everything. An admin makes, renames and removes
   collections there. On a phone there is no rail: the filter row keeps its
   pickers. Every write goes through the
   editor's store (editor/store.js), the same path the Desk's own saves take:
   `/admin/ops` under the dataset's stamp, and `/admin/maintenance` under the
   repairs' stamp. The bulk actions are drawn only where the Desk itself would
   open (`body[data-editable]`), and never on a phone.

   ITS OWN THING (owner, 2026-11-15): NODES no longer stands between the Sky
   and the Depths. Above the table, one line counts the places by state (each
   count is the state filter); below it, the newest state changes of the
   places and services on screen, from the annals (`api/v2/events`, redacted
   for the viewer there).

   WATCHED BY (2026-11-15): the column the roster calls `confirmed_by` names
   the source that gave a place its state (Kuma, Atlas's own checks, UniFi…),
   or "nothing"; a service's line says the same after its name. SHADOW: with
   the map's "Check beside Kuma" on, an admin sees below the changes how often
   Atlas's own checks agreed with Kuma's monitors (`api/v2/admin/shadow`).

   CONTAINERS AND SERVICES (2026-11-15): KINDS in the rail
   also lists Containers and Services. Each shows every one of them on the
   map as a list of its own (roster-model `thingRows`): its state, its name,
   the place it runs on (which opens the card), the container's name, its
   collections, its bell and its ⋯, the same line a place's services draw
   under its row. A container is a service link that names a Docker
   container or says `kind: container`; neither is a place or a marker.

   Every visible word is theme text (`nodes_*`), with the plain fallback in
   NODES_TEXT below. The look is views.css. */

import { A, $, esc, themeText, canAdminWrite, ago } from './config.js';
import * as R from './roster-model.js';
import { parseCollection } from './views-model.js';
import Editor, { EditorError } from './editor/store.js';
import { inputToIso, isoToInput } from './editor/form-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import * as Rules from './alert-rules.js';
import { keepFocus } from './alert-forms.js';
import * as W from './window-model.js';

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
  nodes_any_collection: 'Any collection',
  nodes_state_healthy: 'Up',
  nodes_state_degraded: 'Degraded',
  nodes_state_down: 'Down',
  nodes_state_maintenance: 'In maintenance',
  nodes_state_slumbering: 'Asleep',
  nodes_state_unknown: 'Not known',
  nodes_state_unmanaged: 'Unmanaged',
  nodes_summary_label: 'By state; a count shows only those',
  nodes_by_kuma: 'Kuma',
  nodes_by_checks: 'Atlas',
  nodes_by_unifi: 'UniFi',
  nodes_by_prometheus: 'Prometheus',
  nodes_by_relay: 'Relay',
  nodes_by_static: 'A file',
  nodes_by_demo: 'Demo',
  nodes_by_nothing: 'nothing',
  nodes_shadow_title: 'Atlas beside Kuma',
  nodes_shadow_line: '{pct}% agree over {n} answers since {since}',
  nodes_shadow_none: 'No answer compared yet: Atlas asks what Kuma watches, each on its own schedule.',
  nodes_shadow_same: 'Every answer so far agreed.',
  nodes_shadow_row: 'Atlas said {atlas}, Kuma {kuma} \u00b7 {differ} of {total} differ',
  nodes_shadow_failed: 'The comparison could not be read.',
  nodes_shadow_idle: 'The checks source is off (Settings, Sources), so Atlas asks nothing beside Kuma.',
  nodes_kind_container: 'Containers',
  nodes_kind_service: 'Services',
  nodes_things_container: 'containers',
  nodes_things_container_one: 'container',
  nodes_things_service: 'services',
  nodes_things_service_one: 'service',
  nodes_things_count: '{shown} of {total} {what}',
  nodes_things_all: '{total} {what}',
  nodes_things_none: 'None of these match the filter.',
  nodes_things_empty: 'Nothing on the map is one of these yet.',
  nodes_thing_host: 'Open {name}',
  nodes_summary_item: '{n} {state}',
  nodes_recent_title: 'Recent changes',
  nodes_recent_none: 'Nothing listed here has changed state yet.',
  nodes_recent_failed: 'The recent changes could not be read.',
  nodes_recent_to_down: 'went down',
  nodes_recent_to_degraded: 'became degraded',
  nodes_recent_to_healthy: 'came back up',
  nodes_recent_to_maintenance: 'went into maintenance',
  nodes_recent_to_slumbering: 'went to sleep',
  nodes_recent_to_other: 'became {state}',
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
  nodes_col_confirmed: 'Watched by',
  nodes_col_reviewed: 'Reviewed',
  nodes_col_maintenance: 'Maintenance',
  nodes_col_cert: 'Certificate',
  nodes_col_collections: 'Collections',
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
  nodes_maint_mode: 'mode, {n} days',
  nodes_maint_mode_today: 'mode, since today',
  nodes_maint_mode_title: 'Maintenance mode since {when}, until someone turns it off',
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
  nodes_bulk_col_add: 'Add to a collection',
  nodes_bulk_col_out: 'Take out of a collection',
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
  nodes_s_pick: 'Which collection',
  nodes_s_new_opt: 'A new collection…',
  nodes_s_new: 'Name the new collection',
  nodes_s_add_go: 'Add them',
  nodes_s_out_go: 'Take them out',
  nodes_s_added: 'Added to {name}.',
  nodes_s_removed: 'Taken out of {name}.',
  nodes_s_none: 'There are no collections yet.',
  nodes_s_name_needed: 'Name the new collection.',
  nodes_s_unchanged: 'Nothing to change: {name} already says so.',
  nodes_s_gone: 'That collection is not there any more. Pick another.',
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
  nodes_rail_label: 'Collections, networks and kinds',
  nodes_rail_collections: 'Collections',
  nodes_rail_networks: 'Networks',
  nodes_rail_kinds: 'Kinds',
  nodes_rail_saved: 'Saved filters',
  nodes_rail_empty_collections: 'No collection yet.',
  nodes_rail_empty_saved: 'None yet. Filter the table, then save the filter.',
  nodes_rail_show: 'Show only {name}',
  nodes_rail_unshow: 'Show every place again',
  nodes_rail_trouble: '{n} down or degraded',
  nodes_rail_new: 'New collection',
  nodes_rail_new_go: 'Create',
  nodes_rail_created: 'Made the collection {name}.',
  nodes_rail_menu: 'What to do with {name}',
  nodes_rail_rename: 'Rename',
  nodes_rail_rename_go: 'Save the name',
  nodes_rail_renamed: 'Renamed to {name}.',
  nodes_rail_remove: 'Remove',
  nodes_rail_remove_armed: 'Yes, remove {name}',
  nodes_rail_remove_note: 'Removing a collection takes no place off the map.',
  nodes_rail_remove_rules: 'Alert rules that watch it will stop sending: {rules}. With alerts on, they wait in Settings › Alerts, under Rules on something gone, to be removed.',
  nodes_rail_removed: 'Removed the collection {name}.',
  nodes_rail_name_needed: 'Give the collection a name.',
  // alerts inside NODES (2026-11-14): the Alerts column and the rail's bells
  nodes_col_alerts: 'Alerts',
  nodes_bell_place: 'Alerts on {name}: {n} reach it',
  nodes_bell_none: 'Alerts on {name}: none yet',
  nodes_bell_group: 'Alerts on {name}',
  nodes_bell_watched: 'Alerts on {name}: {n} watch it',
  nodes_bell_held: 'Alerts on {name}: none can send (behind an access group)',
  nodes_bell_unmanaged: 'Alerts on {name}: none can send (unmanaged)',
  // stage 3 (2026-11-14): the row menu, the scope bar, maintenance mode, unmanaged
  nodes_menu: 'What to do with {name}',
  nodes_menu_schedule: 'Schedule maintenance…',
  nodes_menu_mode_on: 'Maintenance mode: turn on',
  nodes_menu_mode_off: 'Maintenance mode: turn off',
  nodes_menu_mode_via: 'In maintenance mode through {name}',
  nodes_menu_unmanaged_on: 'Mark unmanaged',
  nodes_menu_unmanaged_off: 'Watch it again',
  nodes_menu_unmanaged_via: 'Unmanaged through {name}',
  nodes_menu_alerts: 'Alerts',
  nodes_menu_edit: 'Edit',
  nodes_menu_remove: 'Remove…',
  nodes_add_place: 'Add a place',
  nodes_n_places: '{n} places',
  // stage 5 (2026-11-15): a phone draws its cards a few hundred at a time
  nodes_more_cards: 'Show {n} more ({left} left)',
  // stage 3b (2026-11-15): a place's services
  nodes_svc_open: 'Show the services of {name}',
  nodes_svc_close: 'Hide the services of {name}',
  nodes_svc_none: 'No service charted on this place.',
  nodes_svc_in: 'in {names}',
  nodes_svc_unmanaged_place: 'Unmanaged with its place',
  nodes_svc_mode_place: 'In maintenance with its place',
  nodes_menu_collections: 'Collections…',
  nodes_scope_col: 'Collections for {name}',
  nodes_sc_label: 'Collection',
  nodes_sc_add: 'Add it to this collection',
  nodes_sc_out: 'Take it out of this collection',
  nodes_sc_done_add: 'Added {name} to {collection}.',
  nodes_sc_done_out: 'Took {name} out of {collection}.',
  nodes_sc_none: 'No collection yet: make one in the rail first.',
  nodes_svc_key: 'Its key: {key}',
  nodes_rail_gone_services: '{n} of its services are no longer on the map (the place went, or the service was renamed).',
  nodes_rail_tidy: 'Take them out',
  nodes_rail_gone_service: 'One of its services is no longer on the map (the place went, or the service was renamed).',
  nodes_rail_tidied_one: 'Took 1 service no longer on the map out of {name}.',
  nodes_rail_tidied: 'Took {n} services no longer on the map out of {name}.',
  nodes_mode_through: 'Still in maintenance mode through {names}: turn it off on the collection.',
  nodes_unmanaged_through: 'Still unmanaged through {names}: watch the collection again.',
  nodes_scope_for: 'Schedule maintenance for {name}',
  nodes_scope_close: 'Close',
  nodes_mode_reason: 'Maintenance mode',
  nodes_mode_on_done: 'In maintenance mode until someone turns it off: {name}.',
  nodes_mode_off_done: 'Out of maintenance mode: {name}.',
  nodes_unmanaged_on_done: 'Unmanaged, not watched: {name}.',
  nodes_unmanaged_off_done: 'Watched again: {name}.',
  nodes_already: 'Nothing to change: it is already so.',
  nodes_bulk_mode: 'Maintenance mode',
  nodes_bulk_unmanaged: 'Unmanaged',
  nodes_bm_label: 'For these places',
  nodes_bm_on: 'Turn maintenance mode on',
  nodes_bm_off: 'Turn maintenance mode off',
  nodes_bu_on: 'Mark them unmanaged',
  nodes_bu_off: 'Watch them again',
  nodes_b_go: 'Apply',
  nodes_mode_note: 'On until someone turns it off. The daily digest names anything left in maintenance mode more than a week.',
  nodes_unmanaged_note: 'Unmanaged: on the map, greyed, takes no state and raises nothing. Like a save in the map editor, this also marks them as checked.',
  nodes_rail_schedule: 'Schedule…',
  nodes_rail_mode_on: 'Maintenance mode on',
  nodes_rail_mode_off: 'Maintenance mode off',
  nodes_rail_unmanaged_on: 'Mark unmanaged',
  nodes_rail_unmanaged_off: 'Watch again',
};

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
function t(key, vars = {}) {
  return themeText(key, NODES_TEXT[key] || '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown', 'unmanaged'];
const DOT = { healthy: 'h-up', degraded: 'h-degraded', down: 'h-down', maintenance: 'h-maint', slumbering: 'h-slumber' };
const REPEATS = ['none', 'daily', 'weekly', 'monthly'];

/** The columns, in order, and the roster-model key each sorts on. */
const COLUMNS = [
  ['state', 'nodes_col_state'], ['name', 'nodes_col_name'], ['zone', 'nodes_col_zone'],
  ['kind', 'nodes_col_kind'], ['addresses', 'nodes_col_addresses'], ['services', 'nodes_col_services'],
  ['confirmed_by', 'nodes_col_confirmed'], ['reviewed', 'nodes_col_reviewed'],
  ['maintenance', 'nodes_col_maintenance'], ['cert', 'nodes_col_cert'],
  ['collections', 'nodes_col_collections'],
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
  form: '',            // which bulk form is open: '', maint, col-add, col-out, hide, needs
  naming: false,       // the "name this filter" box is out
  arm: R.twoPress(),
  busy: false,
  msg: null,           // {kind: info|warn|bad, text, problems?}
  railShut: R.readRail(store),   // the rail's sections this browser shut
  railMenu: '',        // the collection whose tools are out
  railMode: '',        // '', 'new' (naming a new collection) or 'rename'
  railArm: '',         // the collection a first "Remove" press armed
  railRules: [],       // names of the alert rules that watch the armed one
  railFocus: '',       // a selector to focus once a redraw has drawn it
  railArmAt: 0,        // when Remove was armed; the second press waits for the warning
  rowMenu: '',         // the place whose ⋯ menu is out (stage 3, 2026-11-14)
  scope: null,         // {kind: place|collection|service, id, name, form?}: the bar is for this one thing
  svcMenu: '',         // the service (by key) whose ⋯ menu is out (stage 3b)
  expanded: new Set(), // the places whose services are shown under their row
  win: null,           // the drawn window of a long table (stage 5), or null when every row is drawn
  cards: 200,          // a phone draws this many cards, then "Show more" (stage 5)
  events: null,        // the annals' newest events, or null before (or without) a read (2026-11-15)
  shadow: null,        // Atlas beside Kuma, for an admin (api/v2/admin/shadow), or null
  thingsShown: [],     // the keys of the containers or services listed (C2)
  eventsError: false,  // the last read of them failed
};

let root = null;
let el = {};

const phone = () => document.body.classList.contains('phone');
/** The Desk's own gate (editor/index.js): an admin on an instance that writes. */
const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
const dim = '<span class="nv-dim">—</span>';
const blank = (v) => v === null || v === undefined || v === '';

/* ── alerts inside NODES (2026-11-14) ─────────────────────────────────────
   The owner: "i didn't want to add an alerts section i wanted it built into
   the node view." A place's bell in the Alerts column, and a bell on each
   collection and network in the rail, open alert-rules.js's panel above the
   table for that one thing; a second press on the same bell shuts it. The
   count is the rules that reach the place as the server matches them
   (alerts-model `rulesCovering`). An admin's, on a wide screen; the routes
   refuse anyone else regardless. */
const mayAlert = () => Boolean(A.MAY_ALERTS) && !phone();
const BELL = '<svg class="nv-bell-i" viewBox="0 0 16 16" aria-hidden="true" focusable="false">' +
  '<path fill="currentColor" d="M8 1.4c.5 0 .9.4.9.9v.6a4.4 4.4 0 0 1 3.5 4.3v2.6l1.3 1.9H2.3l1.3-1.9V7.2' +
  'a4.4 4.4 0 0 1 3.5-4.3v-.6c0-.5.4-.9.9-.9zM6.2 12.9h3.6a1.8 1.8 0 0 1-3.6 0z"/></svg>';
const alertRules = () => AlertStore.ALERTS.body?.doc?.rules || null;
const panelOn = (kind, id) => { const p = Rules.current(); return Boolean(p && p.kind === kind && p.id === id); };

function alertsCell(row) {
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

/** Open (or, pressed again, shut) the alerts on one thing; the bells redraw. */
function pressBell(kind, id) {
  // the panel's `moved` (opening) and `shut` (a second press) redraw the bells
  Rules.openFor({ kind, id });
}

function focusBell(kind, id) {
  const where = kind === 'place' || kind === 'service' ? el.results : el.rail;
  // a long table draws only a window: bring the bell's row into it first
  if (kind === 'place') showRow(id);
  else if (kind === 'service') showRow(serviceOf(id)?.place);
  where?.querySelector(`[data-alerts="${kind}"][data-id="${CSS.escape(id)}"]`)?.focus();
}

/* ── the data ────────────────────────────────────────────────────────────── */

function normalise(body) {
  const b = body && typeof body === 'object' ? body : {};
  const list = (v) => (Array.isArray(v) ? v : []);
  return {
    stamp: b.stamp || null,
    zones: list(b.zones),
    collections: list(b.collections),
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
    readEvents();      // the changes below the table, read beside it (never waited on)
    readShadow();      // and, for an admin, Atlas beside Kuma
    hookRefresh();   // and again once the read is back: by then atlas.js has run
    const known = new Set((S.roster?.rows || []).map((r) => r.id));
    for (const id of [...S.selected]) if (!known.has(id)) S.selected.delete(id);
    draw();
    // the map moved: which places no rule can reach (`held`, a place hidden
    // or shown) is the alerts' status, read again with it
    if (mayAlert()) AlertStore.read();
  })();
  return inflight;
}

/** The annals' newest events, for the changes below the table. A failed read
    keeps the last list and says so; the table never waits on this. */
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

/** SHADOW (2026-11-15): how often Atlas's own checks agreed with Kuma, for
    an admin. Read beside the roster; nothing waits on it. */
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
  root = $('nodes-sheet');   // the sheet between the Sky and the Depths (index.html)
  if (!root || el.sheet) return Boolean(root);
  // `?collection=<id>`, or `?set=<id>`, its name before 2026-11-14
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
  el = {
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
    addPlace: root.querySelector('.nv-add-place'),
    summary: root.querySelector('.nv-summary'),
    recent: root.querySelector('.nv-recent'),
    recentList: root.querySelector('.nv-recent-list'),
    shadow: root.querySelector('.nv-shadow'),
    shadowList: root.querySelector('.nv-shadow-list'),
  };
  // the panel shuts itself (Close, Escape): the bells redraw and the keyboard
  // goes back to the bell that opened it
  Rules.mount(el.alerts, {
    shut: (was) => { drawResults(); if (was) focusBell(was.kind, was.id); },
    moved: () => keepFocus(el.sheet, drawResults),   // its own doors move it: the bells follow
  });

  el.search.value = S.filter.text;
  el.search.addEventListener('input', () => setFilter({ text: el.search.value }));
  for (const sel of el.picks) sel.addEventListener('change', () => {
    // a phone's kind picker also offers Containers and Services (`thing:<kind>`)
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
  el.addPlace.addEventListener('click', () => A.newPlace?.());
  // a thing's place, in the list of containers or services, opens its card
  el.results.addEventListener('click', (e) => {
    const host = e.target.closest('[data-hostplace]');
    if (host) { e.stopPropagation(); openCard(host.dataset.hostplace); }
  }, true);
  // a count on the line above is the state filter; pressed again, it lets go
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
  // a press anywhere else, or the page scrolling, puts the menu away
  document.addEventListener('pointerdown', (e) => {
    if ((S.rowMenu || S.svcMenu) && !el.menu.contains(e.target)
        && !e.target.closest?.('[data-rowmenu], [data-svcmenu]')) closeRowMenu(false);
  });
  addEventListener('scroll', () => { if (S.rowMenu || S.svcMenu) closeRowMenu(false); }, true);
  // the rail's pending focus is forgotten once the keyboard goes elsewhere: a
  // row arriving later must not pull focus out of the search box
  root.addEventListener('focusin', (e) => { if (!el.rail.contains(e.target)) S.railFocus = ''; });
  return true;
}

/* ── filters, sorts and the saved ones ───────────────────────────────────── */

function setFilter(patch) {
  S.filter = { ...S.filter, ...patch };
  S.msg = null;
  S.cards = CARDS;
  drawResults();
}

/** Put a whole filter on screen: the boxes, then the table. */
function applyFilter(filter, sort) {
  S.filter = { ...R.NO_FILTER, ...R.cleanFilter(filter) };
  // a saved filter on a collection removed since shows everything, not nothing
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
  // before the roster arrives, `?collection=` keeps its place with its id for a name
  const shown = want && !known && !S.roster ? [...options, [want, want]] : options;
  sel.innerHTML = `<option value="">${esc(first)}</option>` +
    shown.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  // a filter naming something that is not here (an old saved filter, a
  // collection the viewer may not see) shows everything rather than nothing
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

/** The saved filters as chips: a press applies one, × forgets it. Drawn in
    the rail's SAVED FILTERS and, for a phone, in a row under the filters. */
const savedChips = () => S.saved.map((s, i) =>
  `<span class="nv-chip-wrap"><button type="button" class="nv-chip" data-saved="${i}">${esc(s.name)}</button>` +
  `<button type="button" class="nv-chip-x" data-forget="${i}" aria-label="${esc(t('nodes_saved_forget', { name: s.name }))}" ` +
  `title="${esc(t('nodes_saved_forget', { name: s.name }))}">×</button></span>`).join('');

/** A press on a saved filter's chip, wherever it is drawn. True when it was one. */
function onSavedPress(e) {
  const use = e.target.closest('[data-saved]');
  const forget = e.target.closest('[data-forget]');
  if (!use && !forget) return false;
  // the redraw replaces the chip that was pressed: the keyboard goes back to
  // the same place in the same row, the rail's or the one under the filters
  // (round 16)
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
    // the next chip, or (none left) the section's own head; the row under
    // the filters hides when empty, so the search box takes it there
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
    drawRail();
  };
  name.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); keep(); }
    if (e.key === 'Escape') { e.stopPropagation(); S.naming = false; drawSaved(); }
  });
  el.save.append(name, button('dsk-btn dsk-btn-sm dsk-btn-go', t('nodes_save_go'), keep),
    button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { S.naming = false; drawSaved(); }));
}

/* ── the cells ───────────────────────────────────────────────────────────── */

const stateOf = (row) => R.rowState(row);   // `unmanaged`, a state, or `unknown`

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

function certCell(row) {
  const c = row.cert;
  if (!c || typeof c.days !== 'number') return dim;
  const name = c.name || '';
  const text = c.days < 0 ? t('nodes_cert_lapsed', { name })
    : c.days === 1 ? t('nodes_cert_1day', { name }) : t('nodes_cert_days', { name, n: c.days });
  const tone = R.certTone(c.days);
  return `<span class="nv-cert${tone ? ` nv-cert-${tone}` : ''}"${c.expires ? ` title="${esc(c.expires)}"` : ''}>${esc(text)}</span>`;
}

function collectionsCell(row) {
  const names = new Map((S.roster?.collections || []).map((s) => [s.id, s.name || s.id]));
  const list = (row.collections || []).map((id) => names.get(id) || id);
  return list.length ? esc(list.join(', ')) : dim;
}

const text = (v) => (blank(v) ? dim : esc(v));

/** Which source gave a place its state, in words; "nothing" for a place no
    source has a word for (an unmanaged one is nobody's to watch: a dash). */
function watchedCell(row) {
  const by = row.confirmed_by;
  if (blank(by)) return row.unmanaged ? dim : `<span class="nv-quiet">${esc(t('nodes_by_nothing'))}</span>`;
  const key = `nodes_by_${by}`;
  return esc(Object.prototype.hasOwnProperty.call(NODES_TEXT, key) ? t(key) : by);
}

/** Who watches one service: Kuma when it names a monitor, else Atlas when a
    check has answered for it, else nothing. */
function serviceWatcher(svc) {
  if (linkOf(svc)?.kuma) return t('nodes_by_kuma');
  return A.signalsFeed?.services?.[svc.id] ? t('nodes_by_checks') : t('nodes_by_nothing');
}
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

/** The line above the table: every place this viewer may see, by state, or
    (while the list of containers or services is up) every one of those, so
    a count and the filter it sets always agree. */
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

/** Every service key on the map the viewer was given, and the place and
    label it belongs to (the first link to name a key keeps it). Worked out
    once per map: a keystroke redraws the changes, and a big map has many
    links. */
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

/** The changes below the table: the newest state changes of what is on screen. */
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
    // only the things listed: their own changes, not their places'
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

function drawResults() {
  if (!el.sheet) return;
  // the table on screen, read before anything here writes (stage 5: a read
  // after the rail's redraw would lay the whole page out for it)
  const oldBody = el.results.querySelector('.nv-table tbody');
  // (only a windowed one: a short table has nothing to hold and needs no layout read)
  const pre = oldBody && S.win ? readDrawn(oldBody) : null;
  el.clear.hidden = R.isEmptyFilter(S.filter);
  // the two checks about a place's review say nothing about a container
  for (const box of [el.unchecked, el.stale]) { const l = box.closest('label'); if (l) l.hidden = Boolean(S.filter.things); }
  drawSaved();
  drawRail();
  drawMessage();

  if (!S.roster) {
    S.win = null;
    el.results.innerHTML = S.error
      ? `<div class="dsk-notice dsk-notice-bad">${esc(t('nodes_failed', { why: S.error }))}</div>`
      : `<div class="dsk-notice">${esc(t('nodes_loading'))}</div>`;
    drawCount(0, 0);
    drawBulk();
    return;
  }
  if (S.filter.things) { drawThings(); return; }
  const now = Date.now();
  const all = S.roster.rows;
  const rows = R.sortRows(R.filterRows(all, S.filter, now), S.sort.key, S.sort.dir, S.roster.collections);
  S.shown = rows.map((r) => r.id);
  // a selection only ever holds rows on screen: what a bulk action writes is what you can see
  const onScreen = new Set(S.shown);
  let dropped = false;
  for (const id of [...S.selected]) if (!onScreen.has(id)) { S.selected.delete(id); dropped = true; }
  if (dropped) S.arm.disarm();
  drawCount(rows.length, all.length);

  if (!all.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_empty'))}</div>`;
  else if (!rows.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_none'))}</div>`;
  else if (phone()) el.results.innerHTML = cardsHTML(rows.slice(0, S.cards)) + (rows.length > S.cards
    ? `<button type="button" class="dsk-btn dsk-btn-sm nv-more-cards" data-morecards>${esc(t('nodes_more_cards', { n: Math.min(CARDS, rows.length - S.cards), left: rows.length - S.cards }))}</button>` : '');
  const warn = S.error ? `<div class="dsk-notice dsk-notice-warn">${esc(t('nodes_failed', { why: S.error }))}</div>` : '';
  const windowed = !phone() && rows.length >= W.WINDOW_MIN;
  if (windowed) drawWindowed(rows, now, pre, warn);   // the notice goes in before the row on screen is held still
  else if (rows.length && !phone()) el.results.innerHTML = tableHTML(rows, now);
  if (!windowed) S.win = null;
  placeRowMenu();
  el.addPlace.hidden = !(mayWrite() && !phone() && typeof A.newPlace === 'function');
  if (warn && !windowed) el.results.insertAdjacentHTML('afterbegin', warn);
  syncSelectAll();
  drawBulk();
  drawSummary();
  drawRecent();
}

function tableHTML(rows, now) {
  const p = tableParts(now);
  return tableShell(p, rows.map((row) => p.rowHTML(row)).join(''), 0);
}

function tableShell(p, body, count) {
  // a windowed table says how many rows it has, and each row its place (stage 5)
  // (and can hold the keyboard while the window moves a focused row away)
  return `<div class="nv-scroll"><table class="dsk-table nv-table"${count ? ` aria-rowcount="${count + 1}" tabindex="-1"` : ''}>` +
    `<thead><tr${count ? ' aria-rowindex="1"' : ''}>${p.pickHead}${p.head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** The table's head and a drawer of one row (with its open services row). */
function tableParts(now) {
  const admin = mayWrite();
  const alerting = mayAlert();
  const span = COLUMNS.length + (admin ? 1 : 0) + (alerting ? 1 : 0);   // a services row spans them all
  const head = COLUMNS.map(([key, label]) => {
    const on = S.sort.key === key;
    const sort = on ? (S.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none';
    // the Alerts column stands beside the name, where its bell is seen with
    // the place it belongs to (a column at the far end scrolled out of sight)
    const alertHead = key === 'name' && alerting ? `<th scope="col" class="nv-th-alerts">${esc(t('nodes_col_alerts'))}</th>` : '';
    return `<th scope="col" aria-sort="${sort}" class="nv-th-${key}"><button type="button" class="nv-sort${on ? ' on' : ''}" ` +
      `data-sort="${key}" title="${esc(t('nodes_sort_by', { col: t(label) }))}">${esc(t(label))}</button></th>${alertHead}`;
  }).join('');
  const pickHead = admin
    ? `<th class="dsk-th-pick" scope="col"><input type="checkbox" class="dsk-check nv-all" aria-label="${esc(t('nodes_select_all'))}"></th>` : '';
  const rowHTML = (row, index = 0) => {
    const standing = R.rowStanding(row);
    const pick = admin
      ? `<td class="dsk-td-pick"><input type="checkbox" class="dsk-check nv-pick-row" data-id="${esc(row.id)}" ` +
        `${S.selected.has(row.id) ? 'checked ' : ''}aria-label="${esc(t('nodes_select', { name: row.name || row.id }))}"></td>` : '';
    return `<tr data-id="${esc(row.id)}" data-standing="${standing}"${index ? ` aria-rowindex="${index}"` : ''} class="nv-row${standing === 'checked' ? '' : ` dsk-p-${standing}`}${S.selected.has(row.id) ? ' nv-on' : ''}${row.unmanaged ? ' nv-unmanaged' : ''}">` +
      pick +
      `<td>${stateCell(row)}</td>` +
      `<td><span class="nv-name-cell"><button type="button" class="nv-name" data-open="${esc(row.id)}" title="${esc(t('nodes_open'))}">${esc(row.name || row.id)}</button>` +
      (admin && !phone() ? `<button type="button" class="nv-rail-more nv-row-more" data-rowmenu="${esc(row.id)}" aria-haspopup="menu" ` +
        `aria-expanded="${S.rowMenu === row.id}" aria-label="${esc(t('nodes_menu', { name: row.name || row.id }))}" ` +
        `title="${esc(t('nodes_menu', { name: row.name || row.id }))}">⋯</button>` : '') + '</span></td>' +
      (alerting ? `<td class="nv-td-alerts">${alertsCell(row)}</td>` : '') +
      `<td>${text(row.zone_name || row.zone)}</td>` +
      `<td>${kindCell(row)}</td>` +
      `<td>${addressCell(row)}</td>` +
      `<td class="nv-num">${servicesCell(row, admin)}</td>` +
      `<td>${watchedCell(row)}</td>` +
      `<td>${reviewedCell(row, now)}</td>` +
      `<td>${maintenanceCell(row)}</td>` +
      `<td>${certCell(row)}</td>` +
      `<td>${collectionsCell(row)}</td>` +
      '</tr>' + (S.expanded.has(row.id) ? servicesRow(row, span, index ? index + 1 : 0) : '');
  };
  return { head, pickHead, span, rowHTML };
}

/* ── the window (2026-11-15, stage 5 of the NODES plan) ──────────────────
   Past W.WINDOW_MIN rows the table draws only the rows on screen and a few
   more (window-model.js), with a spacer row above and below standing in for
   the rest. Scrolling `#view-nodes` near a drawn edge draws again, in the
   scroll handler itself (a hidden pane runs animation frames once a second).
   A row that stays drawn stays where it was on screen: the scroll is put
   right for heights that turned out other than guessed. Columns only widen
   while the window moves, so they do not jump. Find-in-page sees only the
   rows drawn; the search box sees them all. Fewer rows: drawn as before. */

const CARDS = 200;                  // a phone's cards, drawn this many at a time
const heights = new Map();          // `<id>|<services open>` → measured px
const hkey = (row) => `${row.id}|${S.expanded.has(row.id) ? 1 : 0}`;
const scroller = () => document.getElementById('view-nodes') || el.sheet?.closest('[id^="view-"]') || null;
let watching = null;

/** `pre`: the table that was on screen, read by drawResults before it wrote
    anything (its rows' heights, where the screen is). */
function drawWindowed(rows, now, pre = null, lead = '') {
  const p = tableParts(now);
  // the same rows drawn again (a save read back, services opened, a bell):
  // the row at the screen's top stays put, as on a scroll. A keystroke that
  // changed the list skips it (and the layout it costs)
  const same = Boolean(S.win && pre?.anchor && S.win.rows.length === rows.length
    && S.win.rows[0]?.id === rows[0]?.id && S.win.rows.at(-1)?.id === rows.at(-1)?.id);
  S.win = { rows, p, start: 0, end: 0, widths: [] };
  // the shell holds one spacer the height of every row before anything is
  // measured, so the page never shrinks under the scroll (which would clamp
  // it to the top) between this redraw and the window's
  const total = W.rowWindow({ count: rows.length, heights: rows.map((r) => heights.get(hkey(r))) }).total;
  // an open services row is a row too, for the count readers hear
  const extra = rows.reduce((k, r) => k + (S.expanded.has(r.id) ? 1 : 0), 0);
  el.results.innerHTML = lead + tableShell(p, `<tr class="nv-gap" data-gap="before" aria-hidden="true"><td colspan="${p.span}"></td></tr>`, rows.length + extra);
  el.results.querySelector('[data-gap="before"] td').style.height = `${total}px`;
  const sc = scroller();
  if (sc && watching !== sc) {
    sc.addEventListener('scroll', () => { if (S.win) paintWindow(false); }, { passive: true });
    // another width wraps rows differently: measure again, and let the
    // columns narrow (the widths they were held to go)
    addEventListener('resize', () => {
      heights.clear();
      if (!S.win) return;
      S.win.widths = [];
      for (const th of el.results.querySelectorAll('.nv-table thead th')) th.style.minWidth = '';
      paintWindow(true);
    });
    watching = sc;
  }
  paintWindow(true, pre, same);
}

/* EVERY READ, THEN EVERY WRITE. A layout read after a write lays the whole
   page out again (about 25 ms at 2,000 places), so a redraw reads what it
   needs while the layout is still clean (in the scroll event, or before a
   keystroke's redraw replaces the table), then writes. A keystroke's redraw
   forces no layout at all; a scroll's forces one, to keep its anchor row
   still. */

/** What is drawn now, read while the layout is clean: each drawn row's
    height (kept, with its services row when open), where the screen is
    against the body, and the first drawn row on screen. */
function readDrawn(tbody) {
  const sc = scroller();
  const scTop = sc ? sc.getBoundingClientRect().top : 0;
  let anchor = null;
  for (const tr of tbody.querySelectorAll('tr[data-id]')) {
    const r = tr.getBoundingClientRect();
    const svc = tr.nextElementSibling?.classList.contains('nv-svc-row') ? tr.nextElementSibling : null;
    heights.set(`${tr.dataset.id}|${svc ? 1 : 0}`, r.height + (svc ? svc.getBoundingClientRect().height : 0));
    if (!anchor && r.bottom > scTop) anchor = { id: tr.dataset.id, at: r.top };
  }
  const view = { top: scTop - tbody.getBoundingClientRect().top, viewport: sc ? sc.clientHeight : innerHeight };
  return { view, anchor };
}

function paintWindow(force, pre = null, hold = false) {
  const w = S.win;
  const tbody = el.results.querySelector('.nv-table tbody');
  if (!w || !tbody) return;
  // reads
  const seen = pre || readDrawn(tbody);
  const cols = pre ? null : [...el.results.querySelectorAll('.nv-table thead th')].map((th) => Math.ceil(th.getBoundingClientRect().width));
  const n = w.rows.length;
  const want = W.rowWindow({ count: n, heights: w.rows.map((r) => heights.get(hkey(r))), ...seen.view });
  const redraw = force || W.needsRedraw(w, want, n);
  const key = redraw ? rowFocusKey() : null;
  // writes
  growColumns(w, cols);
  if (!redraw) return;
  const gap = (where) => `<tr class="nv-gap" data-gap="${where}" aria-hidden="true"><td colspan="${w.p.span}"></td></tr>`;
  // readers' row numbers: the head is 1, and an open services row counts
  let index = 2;
  for (let k = 0; k < want.start; k++) index += S.expanded.has(w.rows[k].id) ? 2 : 1;
  tbody.innerHTML = gap('before') +
    w.rows.slice(want.start, want.end).map((row) => {
      const html = w.p.rowHTML(row, index);
      index += S.expanded.has(row.id) ? 2 : 1;
      return html;
    }).join('') +
    gap('after');
  // heights through the CSSOM (the page's CSP refuses style attributes in markup)
  tbody.querySelector('[data-gap="before"] td').style.height = `${want.before}px`;
  tbody.querySelector('[data-gap="after"] td').style.height = `${want.after}px`;
  w.start = want.start;
  w.end = want.end;
  // a scroll keeps the row that was at the screen's top where it was, though
  // the rows above it turned out taller or shorter than guessed (one layout);
  // so does a redraw of the same rows (`hold`)
  const sc = scroller();
  if ((!force || hold) && sc && seen.anchor) {
    const again = tbody.querySelector(`tr[data-id="${CSS.escape(seen.anchor.id)}"]`);
    const moved = again ? again.getBoundingClientRect().top - seen.anchor.at : 0;
    if (Math.abs(moved) >= 1) sc.scrollTop += moved;
  }
  restoreRowFocus(key);
  placeRowMenu();
  syncSelectAll();
}

/** Columns may widen as other rows come into the window, never narrow:
    `px` are the widths read before any write. */
function growColumns(w, px) {
  if (!px) return;
  const ths = el.results.querySelectorAll('.nv-table thead th');
  px.forEach((v, i) => {
    if (v > (w.widths[i] || 0) && ths[i]) { w.widths[i] = v; ths[i].style.minWidth = `${v}px`; }
  });
}

/** The control the keyboard is on inside a row, as a selector that finds it
    after a redraw; null when the keyboard is not in the table's rows. */
function rowFocusKey() {
  const was = document.activeElement;
  if (!was || !el.results.contains(was) || !was.closest('tbody')) return null;
  for (const attr of ['data-open', 'data-rowmenu', 'data-expand', 'data-svcmenu', 'data-alerts']) {
    const v = was.getAttribute(attr);
    if (v === null) continue;
    const id = was.getAttribute('data-id');
    return `[${attr}="${CSS.escape(v)}"]${id !== null ? `[data-id="${CSS.escape(id)}"]` : ''}`;
  }
  if (was.classList.contains('nv-pick-row')) return `.nv-pick-row[data-id="${CSS.escape(was.dataset.id)}"]`;
  return '.nv-table';   // somewhere else in a row: the table holds it
}

/** The keyboard back where it was; when the window moved its row away (a
    scroll past it), on the table itself, so it does not fall to the page and
    the next Tab goes on in the rows on screen. */
function restoreRowFocus(key) {
  if (!key) return;
  const now = document.activeElement;
  if (now && now !== document.body && el.results.contains(now)) return;
  (el.results.querySelector(key) || el.results.querySelector('.nv-table'))?.focus({ preventScroll: true });
}

/** Bring a row into the window (a save that re-sorted it away; the keyboard
    going back to its ⋯ or bell) before something looks for it. */
function showRow(id) {
  const w = S.win;
  if (!w) return;
  const i = w.rows.findIndex((r) => r.id === id);
  if (i < 0 || (i >= w.start && i < w.end)) return;
  const sc = scroller();
  const tbody = el.results.querySelector('.nv-table tbody');
  if (!sc || !tbody) return;
  const hs = w.rows.map((r) => heights.get(hkey(r)));
  const g = W.guess(hs);
  let y = 0;
  for (let k = 0; k < i; k++) y += hs[k] > 0 ? hs[k] : g;
  const bodyTop = tbody.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop;
  sc.scrollTop = Math.max(0, bodyTop + y - sc.clientHeight / 3);
  paintWindow(true);
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

/** A row's press: its card, or (pressed again while that card is up) no card,
    the way a marker on the map behaves (2026-11-13). */
function openCard(id) {
  if (R.rowPress(A.cardPlace?.(), id) === 'close') { A.closeCard?.(); return; }
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
  if (e.target.closest('[data-morecards]')) {
    // a phone's next cards: the keyboard goes to the first of them
    const from = S.cards;
    S.cards += CARDS;
    drawResults();
    el.results.querySelectorAll(S.filter.things ? '.nv-things .nv-svc-host' : '.nv-card')[from]?.focus();
    return;
  }
  const expand = e.target.closest('[data-expand]');
  if (expand) { toggleServices(expand.dataset.expand); return; }
  const svcMore = e.target.closest('[data-svcmenu]');
  if (svcMore) { toggleSvcMenu(svcMore.dataset.svcmenu); return; }
  const bell = e.target.closest('[data-alerts]');
  if (bell) { pressBell(bell.dataset.alerts, bell.dataset.id); return; }   // the bell opens alerts, not the card
  if (e.target.closest('.nv-svc-row')) return;   // a service's row opens no card (after its bell: review)
  const more = e.target.closest('[data-rowmenu]');
  if (more) { toggleRowMenu(more.dataset.rowmenu); return; }   // the menu, not the card
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
  if (S.scope && S.scope.kind === 'place' && !rowOf(S.scope.id)) S.scope = null;   // it left the table
  if (S.scope) { drawScope(bar); return; }
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
  for (const [form, key] of [['maint', 'nodes_bulk_maint'], ['col-add', 'nodes_bulk_col_add'],
    ['col-out', 'nodes_bulk_col_out'], ['hide', 'nodes_bulk_hide'], ['needs', 'nodes_bulk_needs'],
    ['mode', 'nodes_bulk_mode'], ['unmanaged', 'nodes_bulk_unmanaged']]) {
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
  // Cancel and Escape put the form away, and a scope with it (stage 3)
  bar.append(button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { if (S.scope) closeScope(); else { S.form = ''; drawBulk(); } }), go);
  box.append(bar);
  box.addEventListener('submit', (e) => { e.preventDefault(); if (!S.busy) onGo(); });
  box.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    if (S.scope) closeScope(); else { S.form = ''; drawBulk(); }
  });
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
    () => openWindow(S.scope ? scopeTarget() : { nodes: selectedIds() },
      { reason: reason.value.trim(), start: start.value, end: end.value, repeat: repeat.value }));
  },
  mode() {
    const pick = select([['on', t('nodes_bm_on')], ['off', t('nodes_bm_off')]], 'on');
    return formBox([field(t('nodes_bm_label'), pick)], t('nodes_b_go'),
      () => setMode({ nodes: selectedIds() }, pick.value === 'on', placesLabel(selectedIds())), t('nodes_mode_note'));
  },
  unmanaged() {
    const pick = select([['on', t('nodes_bu_on')], ['off', t('nodes_bu_off')]], 'on');
    return formBox([field(t('nodes_bm_label'), pick)], t('nodes_b_go'),
      () => setUnmanaged('nodes', selectedIds(), pick.value === 'on', placesLabel(selectedIds())), t('nodes_unmanaged_note'));
  },
  'svc-col'() {
    const options = (S.roster?.collections || []).map((c) => [c.id, c.name || c.id]);
    if (!options.length) {
      const box = document.createElement('div');
      box.className = 'nv-form';
      const p = document.createElement('p');
      p.className = 'nv-form-note';
      p.textContent = t('nodes_sc_none');
      box.append(p);
      return box;
    }
    const pick = select(options, options[0][0]);
    const how = select([['add', t('nodes_sc_add')], ['out', t('nodes_sc_out')]], 'add');
    return formBox([field(t('nodes_sc_label'), pick), field('', how)], t('nodes_b_go'),
      () => setServiceCollection(S.scope.id, pick.value, how.value === 'add', S.scope.name));
  },
  'col-add'() { return collectionForm(true); },
  'col-out'() { return collectionForm(false); },
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

function collectionForm(adding) {
  const options = (S.roster?.collections || []).map((s) => [s.id, s.name || s.id]);
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
    () => (adding ? addToCollection(selectedIds(), pick.value, name.value.trim())
      : takeOutOfCollection(selectedIds(), pick.value)));
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
    collectionsChanged();    // another admin may have changed the collections
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
  collectionsChanged();
  try { await Editor.reload(); } catch { /* the next press loads it again */ }
  await refresh();
  tell(err.message, 'warn');
}

/** Run one write with the table held still, then draw it once from the server. */
async function busy(work) {
  if (S.busy) return;
  S.busy = true;
  drawBulk();
  drawRail();
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
  // the map and the editor's copy are read again once, after the last part,
  // not after each (2026-11-15, stage 5: 2,000 places checked was five full
  // reloads and redraws); a run that stops part-way reads them once there
  let sent = 0;
  let behind = false;   // parts saved that the copies have not read yet
  try {
    return await R.inBatches(ops, async (part) => {
      sent += part.length;
      const last = sent >= ops.length;
      try {
        const out = await Editor.apply(part, note, '', { refresh: last });
        behind = !last;
        return out;
      } catch (err) {
        if (err instanceof EditorError && err.status === 409) { await conflict(err); return null; }
        throw err;
      }
    });
  } finally {
    if (behind) {
      // never in place of the run's own answer or error: the next refresh mends it
      try { await Editor.reload(); } catch { /* ready() reads it before the next write */ }
      try { await A.refreshData?.(); } catch (err) { console.warn('the map could not be read again', err); }
    }
  }
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

async function openWindow(target, w) {
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
      reason: w.reason, starts, ends,
      repeat: REPEATS.includes(w.repeat) ? w.repeat : 'none',
      ...(target.nodes?.length ? { nodes: target.nodes } : {}),
      ...(target.collections?.length ? { collections: target.collections } : {}),
      ...(target.services?.length ? { services: target.services } : {}),
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
    S.scope = null;
    const n = (target.nodes?.length || 0) + (target.collections?.length || 0) + (target.services?.length || 0);
    const line = n === 1 ? t('nodes_m_done_one') : t('nodes_m_done_many', { n });
    A.showToast?.(line);
    tell(line);
  });
}

const onDiskCollections = () => (Array.isArray(Editor.data?.collections) ? Editor.data.collections : []);

/* ── stage 3 (2026-11-14): the place menu, the scope bar, the ways out ────
   The owner's Q4: three ways out of the watch, from a place's menu, a
   collection's menu or the bulk bar. SCHEDULE is the window form (the bulk
   bar's, for one place or one collection: the "scope"); MAINTENANCE MODE is
   a window marked `open` (roster-model modeChange); UNMANAGED is a field on
   the place or the collection (`unmanaged`). A place in either through a
   collection says so, and its own switch is not offered. */

const repairs = () => (Editor.repairs ? Editor.entries('maintenance') : []);
const rowOf = (id) => (S.roster?.rows || []).find((r) => r.id === id) || null;
const placesLabel = (ids) => (ids.length === 1 ? (rowOf(ids[0])?.name || ids[0]) : t('nodes_n_places', { n: ids.length }));
const collectionUnmanaged = (id) => onDiskCollections().find((c) => c.id === id)?.unmanaged === true
  || (S.roster?.collections || []).find((c) => c.id === id)?.unmanaged === true;

async function ensureRepairs() {
  if (Editor.repairs) return;
  try { await Editor.loadRepairs(); } catch { /* an admin route: shown as off until it reads */ }
}

/** The collections a place is unmanaged through (marked so themselves). */
function unmanagedVia(row) {
  const marked = new Set((S.roster?.collections || []).filter((c) => c.unmanaged === true).map((c) => c.id));
  return (row?.collections || []).filter((c) => marked.has(c));
}

const scopeTarget = () => (S.scope?.kind === 'collection' ? { collections: [S.scope.id] }
  : S.scope?.kind === 'service' ? { services: [S.scope.id] } : { nodes: [S.scope.id] });

/** Put the scope bar away: its form goes with it (a kept form would come
    back aimed at the ticked rows; stage 3 review), and the keyboard goes
    back to what opened it, the row's ⋯ or the collection's Schedule…. */
function closeScope() {
  const was = S.scope;
  S.scope = null;
  S.form = '';
  formFor = '';
  formEl = null;
  drawBulk();
  if (!was) return;
  // a place's or service's row may have left the window while the bar was
  // up (its form took the keyboard and scrolled to the top): bring it back
  if (was.kind === 'place') focusRowMore(was.id);
  else if (was.kind === 'service') focusSvcMore(was.id);
  else el.rail.querySelector(`[data-act="col-schedule"][data-id="${CSS.escape(was.id)}"]`)?.focus();
}

/** The bar for one thing: its schedule form (stage 3). */
function openScope(scope) {
  closeRowMenu(false);
  S.scope = scope;
  S.form = scope.form || 'maint';
  formFor = '';
  drawBulk();
  el.bulk.querySelector('.nv-form input, .nv-form select')?.focus();
}

function drawScope(bar) {
  bar.hidden = false;
  const row = document.createElement('div');
  row.className = 'nv-bulk-row';
  const what = document.createElement('span');
  what.className = 'nv-bulk-n';
  what.textContent = t(S.scope.form === 'svc-col' ? 'nodes_scope_col' : 'nodes_scope_for', { name: S.scope.name });
  row.append(what, button('dsk-btn dsk-btn-sm nv-bulk-clear', t('nodes_scope_close'), closeScope));
  bar.append(row);
  // another action cleared the shared form (a mode toggle elsewhere): the
  // scope keeps its own (stage 3b review: FORMS[''] threw on every redraw)
  if (!FORMS[S.form]) S.form = S.scope.form || 'maint';
  const key = `scope:${S.scope.kind}:${S.scope.id}:${S.form}`;
  if (formFor !== key) { formEl = FORMS[S.form]([]); formFor = key; }
  for (const b of [...bar.querySelectorAll('button'), ...formEl.querySelectorAll('button')]) b.disabled = S.busy;
  bar.append(formEl);
}

/** Maintenance mode on or off for {nodes, collections}, one save of the
    repairs (their own stamp: a writer between is a 409). */
async function setMode(targets, on, label) {
  await busy(async () => {
    if (!(await ready())) return;
    await Editor.loadRepairs();
    const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    const next = R.modeChange(repairs(), targets, on, { now, reason: t('nodes_mode_reason') });
    if (!next) { tell(on ? t('nodes_already') : throughLine('nodes_mode_through', targets, (row) => R.modeVia(repairs(), row.collections)), 'warn'); return; }
    try {
      await Editor.saveRepairs(next);
    } catch (err) {
      if (err instanceof EditorError && err.status === 409) {
        try { await Editor.loadRepairs(); } catch { /* the next press reads them again */ }
      }
      throw err;
    }
    S.form = '';
    const line = t(on ? 'nodes_mode_on_done' : 'nodes_mode_off_done', { name: label });
    A.showToast?.(line);
    tell(line);
  });
}

/** Nothing to turn off on the places themselves: say which collections
    hold them (their own switch is there), or that it is already so. */
function throughLine(key, targets, via) {
  const names = [...new Set((targets.nodes || []).flatMap((id) => via(rowOf(id) || {})))].map(collectionLabel);
  return names.length ? t(key, { names: names.join(', ') }) : t('nodes_already');
}

/** Unmanaged on or off: the field on places (`nodes`) or collections. */
async function setUnmanaged(section, ids, on, label) {
  await busy(async () => {
    if (!(await ready())) return;
    const onDisk = new Map((section === 'nodes' ? (Editor.data?.nodes || []) : onDiskCollections()).map((x) => [x.id, x]));
    const ops = ids.filter((id) => onDisk.has(id) && (onDisk.get(id).unmanaged === true) !== on)
      .map((id) => ({ op: 'upsert', section, id, body: { unmanaged: on } }));
    if (!ops.length) {
      tell(on || section !== 'nodes' ? t('nodes_already')
        : throughLine('nodes_unmanaged_through', { nodes: ids }, unmanagedVia), 'warn');
      return;
    }
    const { stopped } = await applyOps(ops, on ? 'marked unmanaged' : 'watched again');
    if (stopped) return;
    S.form = '';
    const line = t(on ? 'nodes_unmanaged_on_done' : 'nodes_unmanaged_off_done', { name: label });
    A.showToast?.(line);
    tell(line);
  });
}

/* the row's ⋯: one menu element for every row, put beside the ⋯ pressed */

function rowMenuItems(row) {
  const items = [['schedule', t('nodes_menu_schedule')]];
  const via = R.modeVia(repairs(), row.collections);
  if (R.inMode(repairs(), 'place', row.id)) items.push(['mode-off', t('nodes_menu_mode_off')]);
  else if (via.length) items.push(['', t('nodes_menu_mode_via', { name: via.map(collectionLabel).join(', ') })]);
  else items.push(['mode-on', t('nodes_menu_mode_on')]);
  const own = (Editor.data?.nodes || []).find((x) => x.id === row.id)?.unmanaged === true
    || (row.unmanaged && !unmanagedVia(row).length);
  const uvia = unmanagedVia(row);
  if (own) items.push(['unmanaged-off', t('nodes_menu_unmanaged_off')]);
  else if (uvia.length) items.push(['', t('nodes_menu_unmanaged_via', { name: uvia.map(collectionLabel).join(', ') })]);
  else items.push(['unmanaged-on', t('nodes_menu_unmanaged_on')]);
  if (mayAlert()) items.push(['alerts', t('nodes_menu_alerts')]);
  if (typeof A.editPlace === 'function') items.push(['edit', t('nodes_menu_edit')]);
  if (typeof A.removePlace === 'function') items.push(['remove', t('nodes_menu_remove')]);
  return items;
}

/** The ⋯ the menu is out for: a place's, or a service's (stage 3b). */
const menuAnchor = () => (S.svcMenu
  ? el.results?.querySelector(`[data-svcmenu="${CSS.escape(S.svcMenu)}"]`)
  : S.rowMenu ? el.results?.querySelector(`[data-rowmenu="${CSS.escape(S.rowMenu)}"]`) : null);

function drawRowMenu() {
  if (S.svcMenu) { drawSvcMenu(); return; }
  const row = rowOf(S.rowMenu);
  if (!row) { closeRowMenu(false); return; }
  el.menu.innerHTML = rowMenuItems(row).map(([act, label]) => (act
    ? `<button type="button" role="menuitem" class="nv-menu-item" data-mact="${act}">${esc(label)}</button>`
    : `<p class="nv-menu-note">${esc(label)}</p>`)).join('');
  for (const b of el.menu.querySelectorAll('button')) b.disabled = S.busy;
  el.menu.setAttribute('aria-label', t('nodes_menu', { name: row.name || row.id }));
  el.menu.hidden = false;
  placeRowMenu();
}

/** Seat the menu under its ⋯ (after every redraw of the table); put it
    away when the row has gone. */
function placeRowMenu() {
  if ((!S.rowMenu && !S.svcMenu) || !el.menu) return;
  const more = menuAnchor();
  if (!more) { closeRowMenu(false); return; }
  more.setAttribute('aria-expanded', 'true');
  const at = more.getBoundingClientRect();
  const box = el.menu.getBoundingClientRect();
  el.menu.style.left = `${Math.max(8, Math.min(at.left, innerWidth - box.width - 8))}px`;
  el.menu.style.top = `${at.bottom + 4 + box.height > innerHeight ? Math.max(8, at.top - box.height - 4) : at.bottom + 4}px`;
}

async function toggleRowMenu(id) {
  if (S.rowMenu === id && !S.svcMenu) { closeRowMenu(true); return; }
  closeRowMenu(false);
  S.rowMenu = id;
  drawRowMenu();
  el.menu.querySelector('button:not(:disabled)')?.focus();
  // its maintenance mode line reads the repairs: read once, then drawn again
  if (!Editor.repairs) {
    await ensureRepairs();
    if (S.rowMenu === id) { const at = focusKeyOfMenu(); drawRowMenu(); refocusMenu(at); }
  }
}

const focusKeyOfMenu = () => document.activeElement?.closest?.('.nv-menu')?.contains(document.activeElement)
  ? [...el.menu.querySelectorAll('button')].indexOf(document.activeElement) : -1;
function refocusMenu(i) {
  const items = [...el.menu.querySelectorAll('button')];
  (items[i] || items[0])?.focus();
}

function closeRowMenu(focusBack = true) {
  const more = menuAnchor();
  const had = S.rowMenu || S.svcMenu;
  S.rowMenu = '';
  S.svcMenu = '';
  if (el.menu) { el.menu.hidden = true; el.menu.innerHTML = ''; }
  if (!had) return;
  more?.setAttribute('aria-expanded', 'false');
  if (focusBack) more?.focus();
}

function onMenuClick(e) {
  const b = e.target.closest('[data-mact]');
  if (!b || b.disabled || S.busy) return;
  if (S.svcMenu) { onSvcMenuAct(b.dataset.mact); return; }
  const id = S.rowMenu;
  const row = rowOf(id);
  if (!row) { closeRowMenu(false); return; }
  const name = row.name || row.id;
  switch (b.dataset.mact) {
    case 'schedule': openScope({ kind: 'place', id, name }); break;
    // the table is drawn again once the save is read back: the keyboard
    // goes back to this row's ⋯ then, not to the page
    case 'mode-on': case 'mode-off':
      closeRowMenu(true);
      setMode({ nodes: [id] }, b.dataset.mact === 'mode-on', name).then(() => focusRowMore(id));
      break;
    case 'unmanaged-on': case 'unmanaged-off':
      closeRowMenu(true);
      setUnmanaged('nodes', [id], b.dataset.mact === 'unmanaged-on', name).then(() => focusRowMore(id));
      break;
    case 'alerts': closeRowMenu(false); pressBell('place', id); break;
    case 'edit': closeRowMenu(false); A.editPlace?.(id); break;
    case 'remove': closeRowMenu(false); A.removePlace?.(id); break;
    default: break;
  }
}

const focusRowMore = (id) => { showRow(id); el.results.querySelector(`[data-rowmenu="${CSS.escape(id)}"]`)?.focus(); };

/* ── stage 3b (2026-11-15): a place's services, under its row ─────────────
   The Services count opens the place's services in a row beneath it, built
   only when opened (stage 1: the browser is the wall). Each is known by its
   key (alerts-model serviceKey: a Kuma monitor, or `<place>/<label>`), shows
   its state from the feed, its collections, a bell, and a ⋯ in the one
   shared menu: Schedule maintenance…, Maintenance mode, Unmanaged,
   Collections…, Alerts. A service in maintenance or unmanaged through a
   collection, or with its place, says so instead of offering a switch. */

const mapNode = (id) => (A.DATA?.nodes || []).find((x) => x && x.id === id) || null;
const serviceOf = (key) => AM.services(A.DATA).find((s) => s.id === key) || null;
const linkOf = (svc) => (mapNode(svc?.place)?.links || []).find((l) => l && AM.serviceKey(svc.place, l) === svc.id) || null;
const holding = (key) => (S.roster?.collections || []).filter((c) => (c.services || []).includes(key));

function servicesCell(row, admin) {
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
    `aria-expanded="${S.svcMenu === svc.id}" aria-label="${esc(t('nodes_menu', { name: svc.name }))}" ` +
    `title="${esc(t('nodes_menu', { name: svc.name }))}">⋯</button></li>`);
}

function servicesRow(row, span, index = 0) {
  const list = AM.services({ nodes: [mapNode(row.id)].filter(Boolean) });
  const rules = alertRules();
  const items = list.map((svc) => serviceItem(svc, row, serviceState(svc, row), rules)).join('');
  return `<tr class="nv-svc-row" data-svc-of="${esc(row.id)}"${index ? ` aria-rowindex="${index}"` : ''}><td colspan="${span}">` +
    (items ? `<ul class="nv-svc-list">${items}</ul>` : `<p class="nv-rail-empty">${esc(t('nodes_svc_none'))}</p>`) +
    '</td></tr>';
}

/* ── every container, or every service, as a list (2026-11-15, C2) ── */

/** The things on the map, worked out once per map, feed and roster. */
let thingsCache = { data: null, feed: null, roster: null, list: [] };
function thingList() {
  const feed = A.signalsFeed || null;
  if (thingsCache.data === A.DATA && thingsCache.feed === feed && thingsCache.roster === S.roster) return thingsCache.list;
  const list = R.thingRows(A.DATA, S.roster, feed || {});
  thingsCache = { data: A.DATA, feed, roster: S.roster, list };
  return list;
}

function drawThings() {
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
  placeRowMenu();
  el.addPlace.hidden = !(mayWrite() && !phone() && typeof A.newPlace === 'function');
  syncSelectAll();
  drawBulk();
  drawSummary();
  drawRecent();
}

function toggleServices(id) {
  if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id);
  closeRowMenu(false);
  drawResults();
  el.results.querySelector(`[data-expand="${CSS.escape(id)}"]`)?.focus();
  if (!Editor.repairs) ensureRepairs();
}

function serviceMenuItems(svc) {
  const row = rowOf(svc.place);
  const items = [['svc-schedule', t('nodes_menu_schedule')]];
  const modeVia = holding(svc.id).filter((c) => R.inMode(repairs(), 'collection', c.id));
  if (R.inMode(repairs(), 'service', svc.id)) items.push(['svc-mode-off', t('nodes_menu_mode_off')]);
  else if (modeVia.length) items.push(['', t('nodes_menu_mode_via', { name: modeVia.map((c) => c.name || c.id).join(', ') })]);
  else if (row?.maintenance?.now) items.push(['', t('nodes_svc_mode_place')]);
  else items.push(['svc-mode-on', t('nodes_menu_mode_on')]);
  const uVia = holding(svc.id).filter((c) => c.unmanaged === true);
  if (linkOf(svc)?.unmanaged === true) items.push(['svc-unmanaged-off', t('nodes_menu_unmanaged_off')]);
  else if (row?.unmanaged) items.push(['', t('nodes_svc_unmanaged_place')]);
  else if (uVia.length) items.push(['', t('nodes_menu_unmanaged_via', { name: uVia.map((c) => c.name || c.id).join(', ') })]);
  else items.push(['svc-unmanaged-on', t('nodes_menu_unmanaged_on')]);
  items.push(['svc-cols', t('nodes_menu_collections')]);
  if (mayAlert()) items.push(['svc-alerts', t('nodes_menu_alerts')]);
  return items;
}

function drawSvcMenu() {
  const svc = serviceOf(S.svcMenu);
  if (!svc) { closeRowMenu(false); return; }
  el.menu.innerHTML = serviceMenuItems(svc).map(([act, label]) => (act
    ? `<button type="button" role="menuitem" class="nv-menu-item" data-mact="${act}">${esc(label)}</button>`
    : `<p class="nv-menu-note">${esc(label)}</p>`)).join('');
  for (const b of el.menu.querySelectorAll('button')) b.disabled = S.busy;
  el.menu.setAttribute('aria-label', t('nodes_menu', { name: svc.name }));
  el.menu.hidden = false;
  placeRowMenu();
}

async function toggleSvcMenu(key) {
  if (S.svcMenu === key) { closeRowMenu(true); return; }
  closeRowMenu(false);
  S.svcMenu = key;
  drawSvcMenu();
  el.menu.querySelector('button:not(:disabled)')?.focus();
  if (!Editor.repairs) {
    await ensureRepairs();
    if (S.svcMenu === key) { const at = focusKeyOfMenu(); drawSvcMenu(); refocusMenu(at); }
  }
}

const focusSvcMore = (key) => {
  showRow(serviceOf(key)?.place);
  el.results.querySelector(`[data-svcmenu="${CSS.escape(key)}"]`)?.focus();
};

function onSvcMenuAct(act) {
  const svc = serviceOf(S.svcMenu);
  if (!svc) { closeRowMenu(false); return; }
  switch (act) {
    case 'svc-schedule': openScope({ kind: 'service', id: svc.id, name: svc.name }); break;
    case 'svc-cols': openScope({ kind: 'service', id: svc.id, name: svc.name, form: 'svc-col' }); break;
    case 'svc-mode-on': case 'svc-mode-off':
      closeRowMenu(true);
      setMode({ services: [svc.id] }, act === 'svc-mode-on', svc.name).then(() => focusSvcMore(svc.id));
      break;
    case 'svc-unmanaged-on': case 'svc-unmanaged-off':
      closeRowMenu(true);
      setServiceUnmanaged(svc, act === 'svc-unmanaged-on').then(() => focusSvcMore(svc.id));
      break;
    case 'svc-alerts': closeRowMenu(false); pressBell('service', svc.id); break;
    default: break;
  }
}

/** A link's `unmanaged`: the place's whole `links` list is written (a link
    has no id of its own), read fresh under the map's stamp. */
async function setServiceUnmanaged(svc, on) {
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
async function setServiceCollection(key, collectionId, add, name) {
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
    formEl = null;
    const line = t(add ? 'nodes_sc_done_add' : 'nodes_sc_done_out', { name, collection: c.name || c.id });
    A.showToast?.(line);
    tell(line);
  });
}

function onMenuKey(e) {
  const items = [...el.menu.querySelectorAll('button:not(:disabled)')];
  const i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const step = e.key === 'ArrowDown' ? 1 : -1;
    items[(i + step + items.length) % items.length]?.focus();
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault();
    (e.key === 'Home' ? items[0] : items[items.length - 1])?.focus();
  } else if (e.key === 'Escape') {
    e.stopPropagation();
    closeRowMenu(true);
  } else if (e.key === 'Tab') {
    closeRowMenu(true);
  }
}

function collectionLabel(id) {
  const s = (S.roster?.collections || []).find((x) => x.id === id) || onDiskCollections().find((x) => x.id === id);
  return s?.name || id;
}

/** Say a write worked, in the toast and above the table. */
function done(line) {
  A.showToast?.(line);
  tell(line);
}

async function addToCollection(ids, collectionId, newName) {
  if (!collectionId && !newName) { tell(t('nodes_s_name_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const list = onDiskCollections();
    let op;
    let label;
    if (collectionId) {
      const entry = list.find((s) => s.id === collectionId);
      if (!entry) {
        // removed in the rail since the form was drawn: say so and draw it again
        formFor = '';
        drawBulk();
        tell(t('nodes_s_gone'), 'warn');
        return;
      }
      const before = R.memberList(entry?.places);
      const places = [...before, ...ids.filter((id) => !before.includes(id))];
      label = collectionLabel(collectionId);
      if (places.length === before.length) { tell(t('nodes_s_unchanged', { name: label })); return; }
      op = { op: 'upsert', section: 'collections', id: collectionId, body: { places } };
    } else {
      const id = R.slugFor(newName, [...list.map((s) => s.id), ...(await ruleCollectionIds())], 'collection');
      label = newName;
      op = { op: 'insert', section: 'collections', body: { id, name: newName, places: ids } };
    }
    const { stopped } = await applyOps([op], 'added to a collection');
    if (stopped) return;
    S.form = '';
    done(t('nodes_s_added', { name: label }));
  });
}

async function takeOutOfCollection(ids, collectionId) {
  await busy(async () => {
    if (!(await ready())) return;
    const entry = onDiskCollections().find((s) => s.id === collectionId);
    if (!entry) {
      // removed since the form was drawn (another admin, or the rail)
      formFor = '';
      drawBulk();
      tell(t('nodes_s_gone'), 'warn');
      return;
    }
    const before = R.memberList(entry?.places);
    const places = before.filter((id) => !ids.includes(id));
    const label = collectionLabel(collectionId);
    if (!entry || places.length === before.length) { tell(t('nodes_s_unchanged', { name: label })); return; }
    const { stopped } = await applyOps([{ op: 'upsert', section: 'collections', id: collectionId, body: { places } }],
      'taken out of a collection');
    if (stopped) return;
    S.form = '';
    done(t('nodes_s_removed', { name: label }));
  });
}

/* ── the rail (2026-11-14) ───────────────────────────────────────────────── */

/** Put the rail's tools away: no menu out, nothing being named, nothing armed. */
/** The rail changed the collections: an open bulk form is drawn again, so
    its picker lists what is there now. */
function collectionsChanged() {
  // only the collection forms list collections: a typed maintenance reason,
  // access group or needs pick is never wiped (round 14)
  if (S.form === 'col-add' || S.form === 'col-out') formFor = '';
}

function railReset() {
  S.railMenu = '';
  S.railMode = '';
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
      ? `<button type="button" class="nv-rail-more" data-menu="${esc(g.id)}" aria-expanded="${S.railMenu === g.id}" ` +
        `aria-label="${esc(t('nodes_rail_menu', { name: g.name }))}" title="${esc(t('nodes_rail_menu', { name: g.name }))}">⋯</button>`
      : '';
    const kind = section === 'collections' ? 'collection' : section === 'networks' ? 'network' : '';
    const bell = kind ? railBell(kind, g) : '';
    const row = `<li class="nv-rail-li"><button type="button" class="idx-item nv-rail-row${on ? ' on' : ''}" ` +
      `data-sec="${section}" data-id="${esc(g.id)}" aria-pressed="${on}" title="${esc(title)}${trouble ? ` · ${esc(trouble)}` : ''}">` +
      `${dot}<span class="nv-rail-name">${esc(g.name)}</span><span class="nv-rail-n">${g.count}</span></button>${bell}${menu}</li>`;
    return row + (section === 'collections' && admin && S.railMenu === g.id ? railTools(g) : '');
  }).join('');
}

/** An admin's tools under one collection: rename, or remove in two presses. */
function railTools(g) {
  if (S.railMode === 'rename') {
    return `<li class="nv-rail-tools"><input class="dsk-input nv-rail-input" data-input="rename" maxlength="80" ` +
      `value="${esc(g.name)}" aria-label="${esc(t('nodes_rail_rename'))}">` +
      `<button type="button" class="dsk-btn dsk-btn-sm dsk-btn-go" data-act="rename-go" data-id="${esc(g.id)}">${esc(t('nodes_rail_rename_go'))}</button>` +
      `<button type="button" class="dsk-btn dsk-btn-sm" data-act="cancel">${esc(t('nodes_cancel'))}</button></li>`;
  }
  const armed = S.railArm === g.id;
  const notes = armed
    ? `<p class="nv-rail-note">${esc(t('nodes_rail_remove_note'))}</p>` +
      (S.railRules.length ? `<p class="nv-rail-note nv-rail-warn">${esc(t('nodes_rail_remove_rules', { rules: S.railRules.join(', ') }))}</p>` : '')
    : '';
  return `<li class="nv-rail-tools">` +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-act="col-schedule" data-id="${esc(g.id)}">${esc(t('nodes_rail_schedule'))}</button>` +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-act="col-mode" data-id="${esc(g.id)}">${esc(t(R.inMode(repairs(), 'collection', g.id) ? 'nodes_rail_mode_off' : 'nodes_rail_mode_on'))}</button>` +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-act="col-unmanaged" data-id="${esc(g.id)}">${esc(t(collectionUnmanaged(g.id) ? 'nodes_rail_unmanaged_off' : 'nodes_rail_unmanaged_on'))}</button>` +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-act="rename" data-id="${esc(g.id)}">${esc(t('nodes_rail_rename'))}</button>` +
    `<button type="button" class="dsk-btn dsk-btn-sm${armed ? ' dsk-btn-go' : ''}" data-act="remove" data-id="${esc(g.id)}">` +
    `${esc(armed ? t('nodes_rail_remove_armed', { name: g.name }) : t('nodes_rail_remove'))}</button>` +
    (armed ? `<button type="button" class="dsk-btn dsk-btn-sm" data-act="cancel">${esc(t('nodes_cancel'))}</button>` : '') +
    `${notes}${goneServicesNote(g.id)}</li>`;
}

/** A collection holding service keys no longer on the map (its place went,
    or the service was renamed; stage 3b): said, with the way to tidy it. */
function goneServices(id) {
  const c = (S.roster?.collections || []).find((x) => x.id === id);
  if (!c || !A.DATA) return [];
  const known = new Set(AM.services(A.DATA).map((x) => x.id));
  return (c.services || []).filter((k) => !known.has(k));
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

function drawRail() {
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
      ? `<div class="nv-saved">${savedChips()}</div>`
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
}

/** A selector for the rail element of a collection, safe for any id. */
const railSel = (what, id) => (what === 'row'
  ? `.nv-rail-row[data-sec="collections"][data-id="${CSS.escape(id)}"]`
  : `[data-menu="${CSS.escape(id)}"]`);

function focusRailInput() {
  const box = el.rail.querySelector('.nv-rail-input');
  if (box) { box.focus(); box.select(); }
}

function onRailClick(e) {
  if (onSavedPress(e)) return;
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
    syncFilterBoxes();
    S.msg = null;
    drawResults();
    el.rail.querySelector(`.nv-rail-row[data-sec="${row.dataset.sec}"][data-id="${CSS.escape(row.dataset.id)}"]`)?.focus();
    return;
  }
  const more = e.target.closest('[data-menu]');
  if (more) {
    const id = more.dataset.menu;
    const open = S.railMenu !== id;
    railReset();
    if (open) S.railMenu = id;
    drawRail();
    // its maintenance mode switch reads the repairs: read once, then drawn again
    if (open && !Editor.repairs) ensureRepairs().then(() => { if (S.railMenu === id) keepFocus(el.rail, drawRail); });
    el.rail.querySelector(`[data-menu="${CSS.escape(id)}"]`)?.focus();
    return;
  }
  const act = e.target.closest('[data-act]');
  if (!act || S.busy) return;
  const id = act.dataset.id;
  const value = () => (el.rail.querySelector('.nv-rail-input')?.value || '').trim();
  switch (act.dataset.act) {
    case 'new': railReset(); S.railMode = 'new'; drawRail(); focusRailInput(); break;
    case 'new-go': createCollection(value()); break;
    case 'rename': S.railMode = 'rename'; S.railArm = ''; drawRail(); focusRailInput(); break;
    case 'col-schedule': openScope({ kind: 'collection', id, name: collectionLabel(id) }); break;
    case 'col-tidy': tidyCollection(id).then(() => { S.railFocus = railSel('menu', id); drawRail(); }); break;
    case 'col-mode':
      setMode({ collections: [id] }, !R.inMode(repairs(), 'collection', id), collectionLabel(id))
        .then(() => { S.railFocus = `[data-act="col-mode"][data-id="${CSS.escape(id)}"]`; drawRail(); });
      break;
    case 'col-unmanaged':
      setUnmanaged('collections', [id], !collectionUnmanaged(id), collectionLabel(id))
        .then(() => { S.railFocus = `[data-act="col-unmanaged"][data-id="${CSS.escape(id)}"]`; drawRail(); });
      break;
    case 'rename-go': renameCollection(id, value()); break;
    case 'remove':
      // a double click must not remove: the second press counts only once the
      // warning about alert rules is on screen and a moment has passed
      if (S.railArm === id) { if (S.railArmAt && Date.now() - S.railArmAt >= ARM_WAIT_MS) removeCollection(id); }
      else armRemove(id);
      break;
    case 'cancel': {
      // back to the collection's tools; a new one's name box just goes away
      const back = S.railMenu;
      railReset();
      S.railMenu = back;
      S.railFocus = back ? railSel('menu', back) : '[data-act="new"]';
      drawRail();
      break;
    }
    default: break;
  }
}

function onRailKey(e) {
  const box = e.target.closest('.nv-rail-input');
  if (!box) return;
  if (e.key === 'Enter') {
    e.preventDefault();
    el.rail.querySelector(box.dataset.input === 'new' ? '[data-act="new-go"]' : '[data-act="rename-go"]')?.click();
  } else if (e.key === 'Escape') {
    // the same as Cancel: back to the collection's tools, or New
    e.stopPropagation();
    const back = S.railMenu;
    railReset();
    S.railMenu = back;
    S.railFocus = back ? railSel('menu', back) : '[data-act="new"]';
    drawRail();
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

async function ruleCollectionIds() {
  return [...AM.watchedIds(await freshRules(), 'collection')];
}

async function rulesWatching(id) {
  return AM.rulesOn(await freshRules(), 'collection', id).map((r) => String(r.name || r.id));
}

/** How long an armed Remove ignores presses: longer than a double click. */
const ARM_WAIT_MS = 500;

async function armRemove(id) {
  S.railMode = '';
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
    if (S.filter.collection === id) { S.filter = { ...S.filter, collection: '' }; syncFilterBoxes(); }
    collectionsChanged();
    done(t('nodes_rail_removed', { name }));
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
  drewWithoutMap = !A.DATA;
  if (S.roster) S.filter = R.dropUnknown(S.filter, R.filterGroups(S.roster));
  drawPicks();
  syncFilterBoxes();
  drawResults();
  Rules.draw();   // the map was read again: the panel's names follow it
}

/** The view came up: draw what is known at once, then read it fresh. */
function show() {
  if (!build()) return;
  hookRefresh();
  draw();
  refresh();
  if (mayAlert()) AlertStore.read();   // the bells' counts
}

/* The alerts document was read (here, or a save in Settings › Alerts): the
   bells' counts follow it. */
AlertStore.listen((changed) => {
  // only when something changed, and with the keyboard kept where it was:
  // the remove warning's own read lands while focus is on the armed Remove
  if (changed && A.VIEW === 'nodes' && el.sheet && mayAlert()) keepFocus(el.sheet, drawResults);
});

addEventListener('atlas:view', (e) => { if (e.detail?.view === 'nodes') show(); });
// the containers and services come from the map: a NODES drawn before it
// arrived (the roster answered first) draws again, once (review, 2026-11-15)
let drewWithoutMap = false;
addEventListener('atlas:data', () => { if (drewWithoutMap && A.VIEW === 'nodes' && el.sheet) draw(); });
// atlas.js assigns A.refreshData once every module has run, which is before
// the page's DOMContentLoaded: wrap it then, whichever view the page opened on
addEventListener('DOMContentLoaded', hookRefresh, { once: true });
// the first view is chosen at import, before this file listens (views.js)
if (A.VIEW === 'nodes' || document.body.dataset.view === 'nodes') show();
