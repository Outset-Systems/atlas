/* TOPOLOGY, what its parts share (2026-11-17): the view's state (`T`), its
   words, what the parts call back through (`hooks`), and the small stable
   doors later stages use to draw on the canvas, take it out, or light a
   way through it, without touching the parts that are here today.

   As NODES does (nodes-state.js), every part imports these same objects and
   changes them in place; this file imports none of the parts (only the
   drawing's pure rules, topology-draw-model.js, for `withSaved`). topology.js
   (the conductor) fills `hooks` with its own functions as it loads.

   THE DOORS (later stages call these, or `A.topology.*`, never the parts):
     shownGraph()                 the graph on screen (after the view and folding)
     positions()                  its cards' top-left corners, {id: {x, y}}
     svgEl()                      the one <svg class="tp-canvas">
     redraw()                     draw again from the dataset in memory
     lightPath(things, links, failedAt)
                                  light a chain HEAD FIRST: things[0] is the head,
                                  links[i] joins things[i] and things[i + 1]; with
                                  failedAt (an index into things) only as far as
                                  that step, which is drawn in the down colour.
                                  (pathToHead answers bottom first: reverse it.)
     clearLight()                 nothing lit, no VLAN pressed
     focusThing(id)               centre on a card and select it (opening the
                                  folded group or leaving Infrastructure first)
     addTool({id, label, title, onPress})
                                  a button in ARRANGE AND EXPORT; returns a
                                  function that takes it away
     onPointer(fn)                fn(kind, detail) for every press and every
                                  pointer going down on a card or the empty
                                  canvas: kind is 'card-down', 'card-press',
                                  'canvas-down' or 'canvas-press'; detail is
                                  {id, thing, event, world: {x, y}}. A fn that
                                  returns true has handled a press, and the card
                                  does not open. Returns a function that stops.

   THE DRAWING'S DOORS (2026-11-17, topology-draw.js; the conductor is not
   changed for them, so each one sits on an assignment the conductor already
   makes):
     mayDraw()                    an admin on an Atlas that writes, on a wide
                                  screen: the Desk's own gate, and not a phone
     setSaved(cards)              the layout an admin saved ({id: {x, y}}), laid
                                  over every layout the conductor makes from now
                                  on, and over the one on screen now. `T.layout`
                                  is an accessor for it: what the conductor
                                  assigns (arrange(shown)) is kept as it came,
                                  and what is read is that with the saved
                                  corners over it (withSaved, which gives what
                                  arrange(shown, {saved}) gives)
     onLayout(fn)                 fn() after every layout the conductor makes
                                  (a reshow); returns a function that stops
     guardRearrange(fn)           fn() before the panel's Re-arrange does
                                  anything; one that returns false stops it.
                                  `hooks.rearrange` is an accessor for it
     stageEl()                    the element round the svg, where a form sits
   The cleaner seam, for whoever next owns topology.js: reshow() passing
   `{saved: T.saved}` to arrange, and hooks.rearrange calling the guards,
   would make the two accessors plain properties again. */

import { canAdminWrite, themeText } from './config.js';
import { withSaved } from './topology-draw-model.js';

/** Every word the view shows, with its plain fallback (the theme's `tp_*`
    and `view_topology`, Web/themes/plain.json, win). */
export const TP_TEXT = {
  view_topology: 'WIRING',
  tp_sub: 'where the wiring is drawn: every card, cable and stub, live',
  tp_canvas: 'Wiring: {n} devices and {c} cables',
  tp_empty: 'Nothing to draw yet. Places, routes and cables appear here as the map gains them.',
  tp_find: 'Find a place, address or port',
  tp_find_count: '{i} of {n}',
  tp_find_none: 'Nothing found',
  tp_panel: 'VLANs and legend',
  tp_vlans: 'VLANs',
  tp_vlans_none: 'No VLAN is named on this map yet.',
  tp_vlan_cables_one: '1 cable',
  tp_vlan_cables: '{n} cables',
  tp_vlan_lit: 'Lit: press again to clear',
  tp_view: 'View',
  tp_view_all: 'Wiring',
  tp_view_infra: 'Infrastructure',
  tp_labels: 'Labels',
  tp_label_address: 'Address',
  tp_label_kind: 'Vendor and kind',
  tp_label_ports: 'Ports',
  tp_arrange: 'Arrange and export',
  tp_fit: 'Fit',
  tp_rearrange: 'Re-arrange',
  tp_legend: 'Legend',
  tp_lg_copper: 'Copper',
  tp_lg_fibre: 'Fibre',
  tp_lg_dac: 'DAC',
  tp_lg_wireless: 'Wireless',
  tp_lg_virtual: 'Virtual',
  tp_lg_assumed: 'Dashed: assumed, not yet checked',
  tp_lg_trunk: 'Striped: a trunk, a stripe per VLAN',
  tp_lg_route: 'Dotted: a route or a host, no cable known',
  tp_lg_up: 'Up',
  tp_lg_warn: 'Degraded',
  tp_lg_down: 'Down',
  tp_lg_maint: 'Maintenance',
  tp_lg_none: 'No word',
  tp_stub_internet: 'Internet line',
  tp_stub_switch: 'Switch, not charted',
  tp_stub_patch: 'Patch panel',
  tp_stub_outlet: 'Wall outlet',
  tp_stub_other: 'Other gear',
  tp_group: '{n} {kind}',
  tp_group_things: 'things',
  tp_group_open: 'Press to open',
  tp_watched: 'Watched by {by}',
  tp_poe: '{w} W',
  tp_note_close: 'Close',
  tp_keys: 'Arrows pan the canvas and step between cards (Shift pans from a card), + and - zoom, 0 fits, Enter opens a card, Ctrl+F finds.',
  // taking it out (2026-11-17, topology-export.js): everyone's
  tp_x_svg: 'SVG',
  tp_x_svg_title: 'Save the whole drawing as an SVG file, as it looks now',
  tp_x_png: 'PNG',
  tp_x_png_title: 'Save the whole drawing as a picture, at twice its size',
  tp_x_csv: 'Connections CSV',
  tp_x_csv_title: 'Save every connection as a spreadsheet',
  tp_x_report: 'Site report',
  tp_x_report_title: 'Print the map, its connections, what is down and the certificates near their end, or save them as a PDF',
  tp_x_title: '{map}: wiring',
  tp_x_date: 'Taken out {date}',
  tp_x_working: 'Making the file…',
  tp_x_busy: 'One file at a time: the last one is still being made.',
  tp_x_saved: 'Saved {file}',
  tp_x_png_reduced: 'Saved {file} at {pct}% of the drawing size, as twice its size is more than a picture can hold.',
  tp_x_png_canvas: 'This browser could not paint a picture that large.',
  tp_x_csv_refused: 'The server refused the sheet ({status}).',
  tp_x_failed: 'The file could not be made: {why}',
  tp_x_external: 'The drawing reached outside itself, so it was not saved.',
  tp_x_empty: 'Nothing to take out yet.',
  tp_x_partial: 'Only {got} of {want} cards could be drawn, so no file was made.',
  tp_x_rp_head: 'Site report',
  tp_x_rp_when: 'Made {when}',
  tp_x_rp_map: 'The map, every device and the cables between them',
  tp_x_rp_conn: 'Connections',
  tp_x_rp_conn_none: 'No place on this map yet.',
  tp_x_rp_down: 'Down now',
  tp_x_rp_down_none: 'Nothing is down.',
  tp_x_rp_down_nofeed: 'No live word has come yet, so nothing can be said to be down.',
  tp_x_rp_certs: 'Certificates near their end',
  tp_x_rp_certs_none: 'No certificate has lapsed or lapses within 14 days.',
  tp_x_col_device: 'Device',
  tp_x_col_to: 'Connected to',
  tp_x_col_port: 'Port',
  tp_x_col_far: 'Far port',
  tp_x_col_vlan: 'VLAN',
  tp_x_col_poe: 'PoE (W)',
  tp_x_col_path: 'Path to the head',
  tp_x_col_name: 'Name',
  tp_x_col_kind: 'Kind',
  tp_x_col_note: 'Note',
  tp_x_col_by: 'Watched by',
  tp_x_col_host: 'Host',
  tp_x_col_expires: 'Expires',
  tp_x_col_days: 'Days left',
  tp_x_col_renews: 'Renews',
  tp_x_down_place: 'Place',
  tp_x_down_service: 'Service',
  tp_x_down_behind: 'Down behind {name}',
  tp_x_down_on: 'On {name}',
  tp_x_days_left: '{n} days left',
  tp_x_day_left: '1 day left',
  tp_x_days_today: 'Lapses today',
  tp_x_day_lapsed: 'Lapsed 1 day ago',
  tp_x_days_lapsed: 'Lapsed {n} days ago',
  tp_x_renews_none: 'Nothing renews this',
  // drawing (2026-11-17, topology-draw.js): an admin's, on a wide screen
  tp_draw_keys: 'Drag a card to move it, or Alt and an arrow. Draw cables: drag from one card to another, or press one and then the other; press a cable, or Enter on it, to change it.',
  tp_draw: 'Draw cables',
  tp_draw_stop: 'Stop drawing',
  tp_draw_title: 'Lay a cable between two cards, or press a cable to change it',
  tp_draw_on: 'Drawing cables. Drag from one card to another, or press one card and then the other. Escape stops.',
  tp_draw_pick: '{name} is end A. Now press the card at the other end, or Escape to let go.',
  tp_draw_group: 'Open the group first: a cable joins two things, not a group.',
  tp_add_stub: 'Add a stub',
  tp_add_stub_title: 'Gear on the wiring that is not a place: the line in, a wall jack, a desk switch',
  tp_add_place: 'Add a place',
  tp_from_routes: 'Cables from routes',
  tp_from_routes_title: 'Make a cable for each route that has none yet',
  tp_cable_new: 'A new cable',
  tp_cable_edit: 'Cable {id}',
  tp_cable_between: '{a} to {b}',
  tp_port_other: 'Other…',
  tp_port_type: 'Type the port',
  tp_save: 'Save',
  tp_cancel: 'Cancel',
  tp_remove: 'Remove',
  tp_remove_sure: 'Remove again to take it out',
  tp_cable_saved: 'Cable {id} saved.',
  tp_cable_saved_ports: 'Cable {id} saved, and {n} new ports added to their places.',
  tp_cable_saved_port: 'Cable {id} saved, and 1 new port added to its place.',
  tp_cable_removed: 'Cable {id} taken out.',
  tp_cable_gone: 'That cable is no longer on the map.',
  tp_need_id: 'Give the cable an id.',
  tp_same_end: 'A cable needs two different ends.',
  tp_nothing_changed: 'Nothing was changed.',
  tp_stub_new: 'A new stub',
  tp_stub_need_name: 'Give the stub a name.',
  tp_stub_saved: '{name} added. It is a card now: draw a cable to it.',
  tp_routes_head: 'Make cables from these routes',
  tp_routes_lead: 'Each route here joins two places with no cable between them yet. Each one ticked becomes a cable marked assumed, with no ports, until someone gives it them.',
  tp_routes_go: 'Make {n} cables',
  tp_routes_go_one: 'Make 1 cable',
  tp_routes_none: 'Every route already has a cable.',
  tp_routes_more: 'The first {n} are listed. Make these, then open this again for the rest.',
  tp_routes_made: '{n} cables made, each marked assumed.',
  tp_routes_made_one: '1 cable made, marked assumed.',
  tp_rearrange_ask: 'Re-arrange throws away where the cards were put. Press Re-arrange again to do it.',
  tp_rearranged: 'Laid out afresh. The saved layout is gone.',
  tp_layout_conflict: 'Someone else moved cards on this map. The layout was read again: move the card again if you still want it there.',
  tp_layout_failed: 'Where the card was put could not be saved: {why}',
  tp_conflict: 'Someone else saved the map first. It was read again: look, then try again.',
  tp_readonly: 'This Atlas is read-only, so nothing here can be saved.',
  tp_editor_failed: 'The map editor could not be opened: {why}',
  tp_busy: 'Saving…',
  // where does it break (2026-11-17, topology-diagnose.js): an admin's;
  // the steps and the summary are NODES' own words (nodes_dx_*)
  tp_dx: 'Where does it break?',
  tp_dx_title: 'Ask the selected place from the head of the network down, and light the way as far as it answers',
  tp_dx_head: 'Where {name} breaks',
  tp_dx_pick: 'Pick a place first.',
  tp_dx_not_place: 'A stub or a folded group has nothing to ask. Pick a place.',
};

/** A word, from the theme or the fallback above, with {name} filled in. */
export function t(key, vars = {}) {
  return themeText(key, TP_TEXT[key] || '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** A stub's kind in words. */
export const stubWords = (kind) => t(`tp_stub_${Object.prototype.hasOwnProperty.call(TP_TEXT, `tp_stub_${kind}`) ? kind : 'other'}`);

export let store = null;
try { store = localStorage; } catch { /* blocked: nothing is remembered */ }
export const STORE_KEY = 'atlas.topology';

/** What this browser remembers: the view and the labels (a convenience). */
export function readPrefs() {
  try {
    const p = JSON.parse(store?.getItem(STORE_KEY) || '{}');
    return {
      mode: p.mode === 'infra' ? 'infra' : 'all',
      labels: {
        address: p.labels?.address !== false,
        kind: p.labels?.kind !== false,
        ports: p.labels?.ports !== false,
      },
    };
  } catch {
    return { mode: 'all', labels: { address: true, kind: true, ports: true } };
  }
}
export function writePrefs() {
  try { store?.setItem(STORE_KEY, JSON.stringify({ mode: T.mode, labels: T.labels })); } catch { /* not remembered */ }
}

const prefs = readPrefs();

export const T = {
  data: null,          // the dataset last drawn (A.DATA, as this viewer was given it)
  graph: null,         // buildGraph(data)
  shown: null,         // the graph on screen: the view, then folding
  layout: null,        // arrange(shown): {positions, width, height, bounds}
  view: { k: 1, x: 0, y: 0 },   // a world point p is drawn at p * k + (x, y)
  fitted: false,       // has the canvas been fitted since the data changed shape
  mode: prefs.mode,    // 'all' (Wiring) or 'infra' (Infrastructure)
  labels: prefs.labels,
  vlan: null,          // the VLAN pressed in the panel, or null
  path: null,          // {things, links, failedAt}, head first (lightPath), or null
  find: '',            // the find box's text
  matches: [],         // what it finds, in graph order
  match: -1,           // which of them is selected
  selected: '',        // the card pressed or found
  focusId: '',         // the card Tab reaches (roving tabindex)
  open: new Set(),     // folded groups pressed open
  svg: null,           // the one <svg class="tp-canvas">
  stage: null,         // the element round it
  drawn: new Set(),    // the ids of the cards drawn now
  up: false,           // is the view on screen
};

/** What the parts call back into topology.js for; filled there as it loads. */
export const hooks = {};

/** The buttons other stages add to ARRANGE AND EXPORT, in the order added. */
export const tools = [];
/** Who hears the pointer on the canvas (onPointer). */
const listeners = new Set();

/* ── the doors ───────────────────────────────────────────────────────────── */

export const shownGraph = () => T.shown;
export const positions = () => T.layout?.positions || null;
export const svgEl = () => T.svg;
export const redraw = () => hooks.redraw?.();

export function lightPath(things, links, failedAt = null) {
  T.vlan = null;
  T.path = {
    things: Array.isArray(things) ? [...things] : [],
    links: Array.isArray(links) ? [...links] : [],
    failedAt: Number.isInteger(failedAt) ? failedAt : null,
  };
  hooks.lit?.();
}

export function clearLight() {
  T.vlan = null;
  T.path = null;
  hooks.lit?.();
}

export const focusThing = (id) => hooks.focusThing?.(id);

export function addTool(spec) {
  if (!spec || typeof spec.onPress !== 'function') return () => {};
  const tool = { id: String(spec.id || `tool-${tools.length}`), label: String(spec.label || ''),
    title: String(spec.title || ''), onPress: spec.onPress };
  tools.push(tool);
  hooks.toolsChanged?.();
  return () => {
    const i = tools.indexOf(tool);
    if (i >= 0) { tools.splice(i, 1); hooks.toolsChanged?.(); }
  };
}

export function onPointer(fn) {
  if (typeof fn !== 'function') return () => {};
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Tell every listener; true when one of them handled it. */
export function emitPointer(kind, detail) {
  let handled = false;
  for (const fn of listeners) {
    try { handled = fn(kind, detail) === true || handled; } catch { /* one listener's fault stays its own */ }
  }
  return handled;
}

/* ── the drawing's doors (2026-11-17) ────────────────────────────────────── */

/** May this viewer draw here? The Desk's gate (an admin on an Atlas that
    writes: `body[data-editable="1"]`), and a wide screen. */
export const mayDraw = () => canAdminWrite() && document.body.dataset.editable === '1' &&
  !document.body.classList.contains('phone');

export const stageEl = () => T.stage;

/* T.layout: what the conductor assigns, kept as it came; what is read, the
   same with the saved corners laid over it. */
let laid = null;        // the layout as the conductor made it
let shownLayout = null; // the same, with the saved corners over it
const layoutListeners = new Set();
T.saved = null;          // {id: {x, y}}, the layout an admin saved, or null
Object.defineProperty(T, 'layout', {
  enumerable: true,
  get: () => shownLayout,
  set: (value) => {
    laid = value;
    // always a copy, so a card dragged on screen never moves the layout the
    // conductor made (which is what is shown again when the saved one goes)
    shownLayout = value ? withSaved(value, T.saved || {}) : value;
    for (const fn of layoutListeners) {
      try { fn(); } catch { /* one listener's fault stays its own */ }
    }
  },
});

/** Lay `cards` over every layout from now on, and over the one on screen. */
export function setSaved(cards) {
  T.saved = cards && typeof cards === 'object' ? cards : null;
  T.layout = laid;
}

export function onLayout(fn) {
  if (typeof fn !== 'function') return () => {};
  layoutListeners.add(fn);
  return () => layoutListeners.delete(fn);
}

/* hooks.rearrange: the conductor's, behind the guards. */
const rearrangeGuards = new Set();
let conductorRearrange = null;
Object.defineProperty(hooks, 'rearrange', {
  enumerable: true,
  configurable: true,
  get: () => (conductorRearrange ? () => {
    for (const fn of rearrangeGuards) {
      try { if (fn() === false) return; } catch { /* a guard's fault never blocks the button */ }
    }
    conductorRearrange();
  } : undefined),
  set: (fn) => { conductorRearrange = typeof fn === 'function' ? fn : null; },
});

export function guardRearrange(fn) {
  if (typeof fn !== 'function') return () => {};
  rearrangeGuards.add(fn);
  return () => rearrangeGuards.delete(fn);
}
