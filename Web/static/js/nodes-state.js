/* NODES, what its parts share (2026-11-16): the view's state (`S`), the
   elements build() found (`el`), the few values more than one part writes
   (`shared`), what they call back into nodes.js for (`hooks`), and the
   small constants and gates they all read, with `menuOn`, which says
   whether the one ⋯ menu is out for a thing. Cut out of nodes.js. Every part
   imports these same objects and changes them in place; this file imports
   none of the parts. */

import { canAdminWrite, HEALTH_DOT } from './config.js';
import * as R from './roster-model.js';

export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown', 'unmanaged'];
export const DOT = HEALTH_DOT;   // config.js holds the one map
export const REPEATS = ['none', 'daily', 'weekly', 'monthly'];

/** The columns, in order, and the roster-model key each sorts on. */
export const COLUMNS = [
  ['state', 'nodes_col_state'], ['name', 'nodes_col_name'], ['zone', 'nodes_col_zone'],
  ['kind', 'nodes_col_kind'], ['addresses', 'nodes_col_addresses'], ['services', 'nodes_col_services'],
  ['confirmed_by', 'nodes_col_confirmed'], ['reviewed', 'nodes_col_reviewed'],
  ['maintenance', 'nodes_col_maintenance'], ['cert', 'nodes_col_cert'],
  ['collections', 'nodes_col_collections'],
];

export let store = null;
try { store = localStorage; } catch { /* blocked: nothing is remembered */ }

export const S = {
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
  railMode: '',        // '', 'new' (naming a new collection) or 'rename'
  railRename: '',      // the collection being renamed: its name box is under its row
  railArm: '',         // the collection a first "Remove" press armed
  railRules: [],       // names of the alert rules that watch the armed one
  railFocus: '',       // a selector to focus once a redraw has drawn it
  railArmAt: 0,        // when Remove was armed; the second press waits for the warning
  menu: null,          // {kind: place|service|collection, id, back?}: the thing whose ⋯ menu is out (one menu, 2026-11-16), and where Escape puts the keyboard
  scope: null,         // {kind: place|collection|service, id, name, form?, place?}: the bar is for this one thing
  asked: null,         // {kind, id, text, tone, pending, feed?, until?, dx?}: Check now's line in that thing's row (2026-11-17), or "Where does it break?" asking or refused (`dx`)
  dx: null,            // {id, name, answer, focus, land}: where a place breaks, listed under its name until closed (2026-11-17)
  expanded: new Set(), // the places whose services are shown under their row
  win: null,           // the drawn window of a long table (stage 5), or null when every row is drawn
  cards: 200,          // a phone draws this many cards, then "Show more" (stage 5)
  events: null,        // the annals' newest events, or null before (or without) a read (2026-11-15)
  shadow: null,        // Atlas beside Kuma, for an admin (api/v2/admin/shadow), or null
  thingsShown: [],     // the keys of the containers or services listed (C2)
  eventsError: false,  // the last read of them failed
};

/** The elements build() found (nodes.js fills this in place, once). */
export const el = {};

/** What more than one part writes that is not the view's state: the bulk
    bar's open form and what it was built for (kept across redraws, so
    nothing typed into it is lost), and a map refresh that landed while a
    write was running. Properties, because an imported `let` cannot be
    assigned from another file. */
export const shared = { formEl: null, formFor: '', pendingWhileBusy: false };

/** What the parts call back into nodes.js for. nodes.js puts its own
    functions here, under their own names, as it loads. No part imports
    nodes.js: it runs show() as it loads, so it has to load after them all,
    whichever file the page happens to reach first. */
export const hooks = {};

export const phone = () => document.body.classList.contains('phone');
/** The Desk's own gate (editor/index.js): an admin on an instance that writes. */
export const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
/** Is the ⋯ menu out for this thing? By kind and id together: a place, a
    service and a collection may share an id. */
export const menuOn = (kind, id) => S.menu?.kind === kind && S.menu.id === id;
export const dim = '<span class="nv-dim">—</span>';
export const blank = (v) => v === null || v === undefined || v === '';
