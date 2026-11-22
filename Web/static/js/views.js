
import { A, $, REDUCED, canAdminWrite } from './config.js';
import {
  ADMIN_VIEWS, ALIASES, PHONE_MEDIA, allowedView, namesCharts, openingView, opensAtCharts,
  parsePlace, parseView, readStored, swipeStep, wantsPhone, withView, writeStored,
} from './views-model.js';

const query = new URLSearchParams(location.search);
const param = query.get('view');
const place = parsePlace(query.get('place'));
const ADMIN = canAdminWrite() && document.body.dataset.editable === '1';
const screenIsPhone = matchMedia(PHONE_MEDIA).matches;
let store = null;
try { store = localStorage; } catch {   }

A.PHONE = wantsPhone(param, screenIsPhone);
A.MAY_ALERTS = ADMIN;

for (const el of document.querySelectorAll('#view-menu [data-view], .view-strip [data-view]')) {
  if (!ADMIN_VIEWS.includes(el.dataset.view)) continue;
  if (ADMIN) el.removeAttribute('hidden'); else el.remove();
}
A.VIEW = null;
A.DECK = false;
if (A.PHONE) document.body.classList.add('phone');

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
part(sheet, 'overview-body', 'div', '');
part(deck, 'overview-charts', 'div', 'ov-charts view-band view-band-depths');
part(deck, 'overview-sky', 'div', 'view-band view-band-sky', sheet);

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

const BANDED = ['overview'];
function frame(view) {
  if (!BANDED.includes(view)) return null;
  const main = document.querySelector(`main.atlas-view[data-view="${view}"]`);
  const up = main?.querySelector(':scope > .view-band-sky');
  const down = main?.querySelector(':scope > .view-band-depths');
  if (!up || !down) return null;
  return { main, up, down, edge: main.querySelector(':scope > .view-edge-up') || up };
}

const MOVERS = {
  overview: [['chronicle', 'up'], ['abyss', 'down'], ['colophon', 'down']],
  nodes: [['colophon', 'foot']],
  topology: [['colophon', 'foot']],
};
const seats = new Map();

function lift(view) {
  const main = document.querySelector(`main.atlas-view[data-view="${view}"]`);
  const movers = MOVERS[view];
  if (!main || !movers) return;
  const parts = {
    up: main.querySelector(':scope > .view-band-sky'),
    down: main.querySelector(':scope > .view-band-depths'),
    foot: main.querySelector(':scope > .view-foot'),
  };
  for (const [id, where] of movers) {
    const el = $(id);
    if (!el || !parts[where] || seats.has(id)) continue;
    const seat = document.createComment(` ${id} sits here on the map `);
    el.before(seat);
    seats.set(id, seat);
    parts[where].append(el);
  }
  (parts.foot || parts.down)?.append(foot);
}
function settle() {
  for (const [id, seat] of seats) seat.replaceWith($(id));
  seats.clear();
  foot.remove();
}

function toMiddle({ smooth = false } = {}) {
  const f = frame(A.VIEW);
  if (!f) return;
  const pad = parseFloat(getComputedStyle(f.main).paddingTop) || 0;
  f.main.scrollTo({ top: Math.max(0, f.edge.offsetTop - pad), behavior: smooth && !REDUCED ? 'smooth' : 'auto' });
}
let holdMiddle = false;
const keepMiddle = typeof ResizeObserver === 'function'
  ? new ResizeObserver(() => { if (holdMiddle) toMiddle(); }) : null;
for (const view of BANDED) {
  const f = frame(view);
  if (!f) continue;
  keepMiddle?.observe(f.up);
  for (const ev of ['wheel', 'touchstart', 'keydown']) {
    f.main.addEventListener(ev, () => { holdMiddle = false; holdCharts = false; }, { passive: true });
  }
}
for (const a of document.querySelectorAll('.view-edge')) {
  a.addEventListener('click', (e) => {
    e.preventDefault();
    holdMiddle = false; holdCharts = false;
    document.getElementById((a.getAttribute('href') || '').slice(1))
      ?.scrollIntoView({ block: 'start', behavior: REDUCED ? 'auto' : 'smooth' });
  });
}

A.toCharts = function toCharts({ smooth = true } = {}) {
  if (A.VIEW !== 'overview') return;
  frame('overview')?.main.scrollTo({ top: 0, behavior: smooth && !REDUCED ? 'smooth' : 'auto' });
};
let holdCharts = false;
A.settleCharts = () => { if (holdCharts) { holdCharts = false; A.toCharts({ smooth: false }); } };

function paintHome() {
  const home = document.querySelector('[data-scene="atlas"]');
  if (home) home.title = A.PHONE ? 'Back to the top' : 'Back to the whole map';
  const editing = Boolean(document.getElementById('map-drawer')?.classList.contains('open'));
  for (const b of document.querySelectorAll('#view-menu [data-view], .view-strip [data-view]')) {
    const on = b.dataset.view === A.VIEW && (b.dataset.view !== 'map' || !b.closest('#view-menu') || editing);
    if (on) b.setAttribute('aria-current', 'true');
    else b.removeAttribute('aria-current');
  }
}
addEventListener('atlas:map-editor-state', paintHome);

A.setView = function setView(name, { remember = false } = {}) {
  const atCharts = namesCharts(name);
  const named = Object.prototype.hasOwnProperty.call(ALIASES, name) ? ALIASES[name] : name;
  const next = allowedView(named, A.PHONE, ADMIN);
  const prev = A.VIEW;
  if (next !== prev) {
    if (prev === 'map' && A.inRegion?.()) A.leaveToMap?.();
    if (prev) A.closeCard?.();
    if (MOVERS[prev]) settle();
    if (MOVERS[next]) lift(next);
    A.VIEW = next;
    A.DECK = next !== 'map';
    document.body.classList.toggle('deck', A.DECK);
    document.body.dataset.view = next;
    let shown = null;
    for (const el of document.querySelectorAll('main.atlas-view')) {
      el.hidden = el.dataset.view !== next;
      if (!el.hidden) shown = el;
    }
    if (next === 'map') A.measureWorld?.();
    else if (BANDED.includes(next)) { holdMiddle = true; toMiddle(); }
    else if (shown) shown.scrollTop = 0;
    paintHome();
    dispatchEvent(new CustomEvent('atlas:view', { detail: { view: next, prev } }));
  }
  if (atCharts && next === 'overview') { holdMiddle = false; holdCharts = true; A.toCharts({ smooth: false }); }
  if (remember && !A.PHONE) writeStored(store, next);
};

A.setDeck = (on, opts) => A.setView(on ? 'overview' : 'map', opts);

A.deckTop = () => {
  if (frame(A.VIEW)) { holdMiddle = false; toMiddle({ smooth: true }); return; }
  document.querySelector('main.atlas-view:not([hidden])')
    ?.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' });
};

{
  const stored = readStored(store);
  const opts = { admin: ADMIN, place };
  A.setView(openingView(param, A.PHONE, stored, opts));
  if (opensAtCharts(param, A.PHONE, stored, opts)) A.setView('charts');
}

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

for (const b of document.querySelectorAll('.view-strip [data-view]')) {
  b.addEventListener('click', () => {
    A.closeAllScenes?.();
    A.setView(b.dataset.view, { remember: true });
  });
}

for (const id of ['chronicle', 'abyss']) {
  const viewer = $(id)?.querySelector('.chron-viewer');
  if (!viewer) continue;
  let x0 = 0, y0 = 0, tracking = false;
  viewer.addEventListener('touchstart', (e) => {
    tracking = BANDED.includes(A.VIEW) && e.touches.length === 1;
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
