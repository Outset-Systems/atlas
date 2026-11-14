/* THE VIEWS — what stands in the map's place under the band (2026-11-13).

   A view replaces the map area; the band stays. MAP is the map. OVERVIEW is
   the realm's own facts in tiles (overview.js draws them into
   `#overview-body`, inside the tiles' sheet) and, below them, THE DECK (v1.66.0 phone, v1.67.0
   everywhere): one scrolling column of the watchings, the Sky's charts and
   then the Depths'. NODES is one table of every place (nodes.js draws it into
   `#view-nodes`). ALERTS is the rules and destinations that send word out
   when the map changes (alerts.js draws `#view-alerts`), an admin's only:
   its menu item and its strip entry are removed here for anyone else, and
   a stored or addressed `alerts` lands on the map (OVERVIEW on a phone).
   `?place=<id>` (the link an alert carries) opens the map on that place's
   card once the opening shot is over; a place this viewer may not see, or
   one that is gone, gives the map and nothing else. The rules (which view a
   page opens on, what is stored, the old name `charts`, who may open what)
   are views-model.js; this file shows them.

   Each view is a `<main class="atlas-view" data-view="…">` in index.html, and
   exactly one is shown at a time (the others carry `hidden`). While any view
   but MAP is up, `body.deck` says "the map is put away": atlas.css hides the
   stage and everything that only steers it, and camera.js stops taking keys.
   `body.dataset.view` names the view. A change is announced on `window` as
   `atlas:view` with detail {view, prev}; the first one fires here at import,
   before later modules listen, so a reader also takes `A.VIEW` on load.

   OVERVIEW's lower half holds the SAME #chronicle and #abyss elements, moved
   out of the camera's stage into `#overview-charts` and back again, so
   chronicle.js draws into them exactly as it does on the map and nothing
   about the charts forks. A comment marks the seat each one left, so it goes
   back to precisely where it was. `Charts ↓` at the top of OVERVIEW scrolls
   down to them, and `charts` (the Deck's stage 2 name, from `?view=` or a
   stored pick) opens OVERVIEW there.

   Imported straight after scheme.js in atlas.js, so a page that opens on a
   view has it before any module looks for the sections. */

import { A, $, REDUCED, canAdminWrite } from './config.js';
import {
  ADMIN_VIEWS, ALIASES, PHONE_MEDIA, allowedView, namesCharts, openingView, opensAtCharts,
  parsePlace, parseView, readStored, swipeStep, wantsPhone, withView, writeStored,
} from './views-model.js';

const query = new URLSearchParams(location.search);
const param = query.get('view');
const place = parsePlace(query.get('place'));
/* NODES' own gate for its bulk actions (nodes.js `mayWrite`): an admin on an
   instance that writes. The server refuses anyone else regardless; this only
   decides which doors are drawn. */
const ADMIN = canAdminWrite() && document.body.dataset.editable === '1';
const screenIsPhone = matchMedia(PHONE_MEDIA).matches;
let store = null;
try { store = localStorage; } catch { /* blocked: the choice simply is not remembered */ }

A.PHONE = wantsPhone(param, screenIsPhone);
A.MAY_ALERTS = ADMIN;   // alerts.js reads the same answer

/* An admin's views: drawn for an admin, and not there at all for anyone else
   (so the menu's arrow keys never land on a door that is not drawn). */
for (const el of document.querySelectorAll('#view-menu [data-view], .view-strip [data-view]')) {
  if (!ADMIN_VIEWS.includes(el.dataset.view)) continue;
  if (ADMIN) el.removeAttribute('hidden'); else el.remove();
}
A.VIEW = null;     // set by the first setView below
A.DECK = false;    // true while the map is put away (any view but MAP)
if (A.PHONE) document.body.classList.add('phone');

/* OVERVIEW's main and its three parts are in index.html; a page from an older
   template (a template cache that outlived a deploy) gets them made, as the
   Deck always did. */
function part(parent, id, tag, cls, before = null) {
  let el = $(id);
  if (!el) {
    el = document.createElement(tag);
    el.id = id;
    el.className = cls;
    parent.insertBefore(el, before);
  }
  return el;
}
let deck = $('view-overview');
if (!deck) {
  deck = document.createElement('main');
  deck.className = 'atlas-view';
  deck.id = 'view-overview';
  deck.dataset.view = 'overview';
  deck.hidden = true;
  $('viewport').after(deck);
}
const sheet = part(deck, 'overview-tiles', 'section', 'ov-sheet');
const jump = part(sheet, 'charts-jump', 'a', 'ov-jump', sheet.firstChild);
if (!jump.textContent.trim()) { jump.href = '#overview-charts'; jump.textContent = 'Charts ↓'; }
part(sheet, 'overview-body', 'div', '');
const charts = part(deck, 'overview-charts', 'div', 'ov-charts');

/* The column's foot: the way back to the map. A phone navigates to the map
   view (`?view=map`) because its own layout is not the map's; a wide screen
   just puts the map back, the same as pressing THE ATLAS. */
const foot = document.createElement('a');
foot.className = 'deck-foot';
foot.href = withView(location.search, 'map');
foot.textContent = A.PHONE ? 'Open the full map ›' : 'Back to the map ›';
foot.addEventListener('click', (e) => {
  if (A.PHONE) return;
  e.preventDefault();
  A.setView('map', { remember: true });
  A.home?.(true);
});
deck.append(foot);

/* The colophon is the feed's voice (signals.js turns it to an alarm), so in
   the charts it rides at the column's foot instead of floating over a chart. */
const MOVERS = ['chronicle', 'abyss', 'colophon'];
const seats = new Map();

function lift() {
  for (const id of MOVERS) {
    const el = $(id);
    if (!el || seats.has(id)) continue;
    const seat = document.createComment(` ${id} sits here on the map `);
    el.before(seat);
    seats.set(id, seat);
    charts.append(el);
  }
}
function settle() {
  for (const [id, seat] of seats) seat.replaceWith($(id));
  seats.clear();
}

/** Scroll OVERVIEW down to its charts (`Charts ↓`, and `?view=charts`). The
    charts' own `scroll-margin-top` keeps them clear of the band. */
A.toCharts = function toCharts({ smooth = true } = {}) {
  if (A.VIEW !== 'overview') return;
  charts.scrollIntoView({ block: 'start', behavior: smooth && !REDUCED ? 'smooth' : 'auto' });
};
/* A page that lands on the charts lands before the tiles have their answer;
   overview.js calls this once its first drawing is in, so the charts are
   still where the page opened. Any scroll of the reader's own lets go. */
let holdCharts = false;
A.settleCharts = () => { if (holdCharts) { holdCharts = false; A.toCharts({ smooth: false }); } };
for (const ev of ['wheel', 'touchstart', 'keydown']) {
  deck.addEventListener(ev, () => { holdCharts = false; }, { passive: true });
}
jump.addEventListener('click', (e) => {
  e.preventDefault();
  holdCharts = false;
  A.toCharts();
});

function paintHome() {
  const home = document.querySelector('[data-scene="atlas"]');
  if (home) home.title = A.PHONE ? 'Back to the top' : 'Back to the whole map';
  // the menu and the phone's strip mark the view on screen
  for (const b of document.querySelectorAll('#view-menu [data-view], .view-strip [data-view]')) {
    if (b.dataset.view === A.VIEW) b.setAttribute('aria-current', 'true');
    else b.removeAttribute('aria-current');
  }
}

/** Show one view. `remember` keeps the pick for the next visit, which only a
    wide screen's own pick should do. A phone has no map, so it never shows
    MAP: its way to the map is `?view=map` (the column's foot). `charts` is an
    old name: it shows OVERVIEW at its charts, and is stored as `overview`. */
A.setView = function setView(name, { remember = false } = {}) {
  const atCharts = namesCharts(name);
  const named = Object.prototype.hasOwnProperty.call(ALIASES, name) ? ALIASES[name] : name;
  const next = allowedView(named, A.PHONE, ADMIN);
  const prev = A.VIEW;
  if (next !== prev) {
    // a region's crumbs and keys belong to the map: leave it whole
    if (prev === 'map' && A.inRegion?.()) A.leaveToMap?.();
    if (prev) A.closeCard?.();
    if (prev === 'overview') settle();
    if (next === 'overview') lift();
    A.VIEW = next;
    A.DECK = next !== 'map';
    document.body.classList.toggle('deck', A.DECK);
    document.body.dataset.view = next;
    let shown = null;
    for (const el of document.querySelectorAll('main.atlas-view')) {
      el.hidden = el.dataset.view !== next;
      if (!el.hidden) shown = el;
    }
    // back on the stage, the sections need their map seats measured again
    if (next === 'map') A.measureWorld?.();
    else if (shown) shown.scrollTop = 0;
    paintHome();   // before the news goes out, so a listener reads the marks right
    dispatchEvent(new CustomEvent('atlas:view', { detail: { view: next, prev } }));
  }
  if (atCharts && next === 'overview') { holdCharts = true; A.toCharts({ smooth: false }); }
  if (remember && !A.PHONE) writeStored(store, next);
};

/** The Deck's own switch, kept for anything that still says it: on is
    OVERVIEW (the charts are its lower half), off is the map. */
A.setDeck = (on, opts) => A.setView(on ? 'overview' : 'map', opts);

/** The top of whatever view is up (THE ATLAS on a phone). */
A.deckTop = () => document.querySelector('main.atlas-view:not([hidden])')
  ?.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' });

{
  const stored = readStored(store);
  const opts = { admin: ADMIN, place };
  A.setView(openingView(param, A.PHONE, stored, opts));
  if (opensAtCharts(param, A.PHONE, stored, opts)) A.setView('charts');
}

/* `?place=<id>`: the map on that place's card. It waits for the opening shot
   (atlas.js lifts the veil and glides home, which would pull the camera back
   off the place), the way regions.js waits to follow `#region=`: `body.pre`
   stands from the start of the boot until the veil has lifted. Only a place
   in the map this viewer was given is focused; anything else is the map,
   with no word about it. A phone has no map, so it opens the card over its
   column. An address that names another view keeps that view. */
function openPlace() {
  const node = A.DATA?.nodes?.find((n) => n.id === place);
  if (!node) return;
  if (A.PHONE) { A.openCard?.(node); return; }
  if (A.VIEW !== 'map') return;
  A.focusNode?.(place);
}
if (place && [null, 'map'].includes(parseView(param))) {
  addEventListener('DOMContentLoaded', () => {
    if (!document.body.classList.contains('pre')) { openPlace(); return; }
    const watch = new MutationObserver(() => {
      if (document.body.classList.contains('pre')) return;
      watch.disconnect();
      openPlace();
    });
    watch.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }, { once: true });
}

/* The phone's strip: the view names at the top of its column (no MAP; the
   column's foot is the way to the map there). */
for (const b of document.querySelectorAll('.view-strip [data-view]')) {
  b.addEventListener('click', () => {
    A.closeAllScenes?.();
    A.setView(b.dataset.view, { remember: true });
  });
}

/* A swipe pages a carousel. On a phone the carousel's ‹ › are hidden (they
   sat on top of the figures), so the swipe presses them instead of reaching
   into chronicle.js's paging. Bound once: the viewers travel with their
   sections, so the listeners do too. */
for (const id of ['chronicle', 'abyss']) {
  const viewer = $(id)?.querySelector('.chron-viewer');
  if (!viewer) continue;
  let x0 = 0, y0 = 0, tracking = false;
  viewer.addEventListener('touchstart', (e) => {
    tracking = A.VIEW === 'overview' && e.touches.length === 1;
    if (tracking) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }
  }, { passive: true });
  viewer.addEventListener('touchend', (e) => {
    if (!tracking) return;
    tracking = false;
    const t = e.changedTouches[0];
    const step = swipeStep(t.clientX - x0, t.clientY - y0);
    if (step) viewer.querySelector(step > 0 ? '.chron-next' : '.chron-prev')?.click();
  }, { passive: true });
}
