/* THE VIEWS' choosing rules, with no DOM (v1.66.0 phone, v1.67.0 the Deck,
   2026-11-13 the views).

   A VIEW is a way of looking at the whole realm that you would leave on screen
   in place of the map: it replaces the map area under the band, it is
   remembered (`atlas.view`) and addressable (`?view=`), it can be what the page
   opens on, and THE ATLAS is the way back from it. MAP is the map itself;
   OVERVIEW is the realm's own facts in tiles, then the Deck below them (the
   Sky's and the Depths' charts in one column, 2026-11-13 stage 3); NODES is
   one table of every place; ALERTS is the rules and destinations that send
   word out when the map changes (stage 4), and is an admin's only.
   views.js does the showing; this file only decides.
   Unit-tested by tests/test_views_model.mjs under plain node.

   CHARTS was the Deck's own view in stage 2. It is now an old name for
   OVERVIEW that lands on the charts: `?view=charts` and a stored `charts`
   still work, and a pick stores `overview` from now on.

   On a PHONE there is no map (v1.66.0), so the phone opens on OVERVIEW, or on
   NODES when that was the last pick, and ignores a stored MAP.

   ALERTS is in ADMIN_VIEWS: a viewer who is not an admin never gets it, from
   the address or from a stored pick, and lands where nothing named a view
   (the map; OVERVIEW on a phone). The callers pass `admin`; this file reads
   no page.

   `?place=<id>` opens the map on that place's card (an alert's link). It
   wins over a stored pick and a phone's default, never over `?view=`.

   The address can overrule all of it: `?view=map` keeps the map on any screen,
   `?view=overview` / `?view=nodes` open on that view, and `?view=phone` asks
   for the phone's own layout on any screen (what a phone looks like, on a
   desk). `phone` is a LAYOUT, not a view: it is never stored and never in
   VIEWS. */

/** Narrow, or a short touch screen (a phone turned sideways). */
export const PHONE_MEDIA = '(max-width: 720px), (max-height: 500px) and (pointer: coarse)';

export const DECK_KEY = 'atlas.view';

/** Every view, in the menu's order. The ONE list: a later stage adds its view
    here and the menu, the address and the stored pick all know it. */
export const VIEWS = ['map', 'overview', 'nodes', 'alerts'];
/** The views only an admin may open (and only an admin sees in the menu). */
export const ADMIN_VIEWS = Object.freeze(['alerts']);
/** Old names that still mean a view: CHARTS (stage 2's Deck) is OVERVIEW,
    landing on its charts. */
export const ALIASES = Object.freeze({ charts: 'overview' });
/** The views a phone can show: everything but the map. */
export const PHONE_VIEWS = VIEWS.filter((v) => v !== 'map');

/** True for a view's name (not `phone`, which is a layout). */
export const isView = (v) => VIEWS.includes(v);

/** True when this viewer may open the view: anyone, except ADMIN_VIEWS. */
export const mayOpen = (v, admin) => isView(v) && (admin === true || !ADMIN_VIEWS.includes(v));

const clean = (raw) => String(raw ?? '').trim().toLowerCase();

/** The `view` query value (or a stored one) as a view's name, an old name
    resolved (`charts` is `overview`), or null when it says nothing usable. */
export function parseView(raw) {
  const v = clean(raw);
  if (Object.prototype.hasOwnProperty.call(ALIASES, v)) return ALIASES[v];
  return isView(v) || v === 'phone' ? v : null;
}

/** True when a value names the charts (the Deck's old name). */
export const namesCharts = (raw) => clean(raw) === 'charts';

/** True when this page takes the phone's layout. */
export function wantsPhone(viewParam, screenIsPhone) {
  const asked = parseView(viewParam);
  if (asked === 'phone') return true;
  if (asked) return false;
  return screenIsPhone === true;
}

/** The view a phone shows when nothing names one it can show. */
const phoneDefault = (stored, admin) => {
  const s = parseView(stored);
  return s && s !== 'map' && s !== 'phone' && mayOpen(s, admin) ? s : 'overview';
};

/** The view this page opens on. The address wins (`phone` meaning the phone's
    own default); then `?place=` opens the map; then a phone opens on its
    default; then the stored pick; anything unknown is the map. A view this
    viewer may not open (ALERTS, for anyone but an admin) is as good as
    unknown: the map, or OVERVIEW on a phone. `opts` is {admin, place}. */
export function openingView(viewParam, isPhone, stored, { admin = false, place = null } = {}) {
  const asked = parseView(viewParam);
  if (asked === 'phone') return phoneDefault(stored, admin);
  if (asked) return mayOpen(asked, admin) ? asked : (isPhone === true ? 'overview' : 'map');
  if (parsePlace(place)) return isPhone === true ? 'overview' : 'map';
  if (isPhone === true) return phoneDefault(stored, admin);
  const s = parseView(stored);
  return s && s !== 'phone' && mayOpen(s, admin) ? s : 'map';
}

/** The view a press asks for, as this viewer gets it: an unknown name or one
    they may not open is the map, and a phone never shows the map. */
export function allowedView(name, isPhone, admin) {
  const next = mayOpen(name, admin) ? name : 'map';
  return isPhone === true && next === 'map' ? 'overview' : next;
}

/** True when the page should open OVERVIEW scrolled down to its charts:
    the address says `charts`, or it names no view and the stored pick that
    the page opens on is the old `charts`. */
export function opensAtCharts(viewParam, isPhone, stored, opts = {}) {
  const asked = parseView(viewParam);
  if (asked && asked !== 'phone') return namesCharts(viewParam);
  if (parsePlace(opts.place)) return false;
  return namesCharts(stored) && openingView(viewParam, isPhone, stored, opts) === 'overview';
}

/** The `set` query value (`?view=nodes&set=<id>`, a saved set of places), or
    null. A set's id is a slug; anything else is ignored, not obeyed. */
export function parseSet(raw) {
  const s = String(raw ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(s) ? s : null;
}

/** The `place` query value (`?place=<id>`, a link in an alert), or null. A
    place's id is a slug; anything else is ignored, not obeyed. */
export function parsePlace(raw) {
  const s = String(raw ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(s) ? s : null;
}

/** A stored value that cannot throw (private windows, blocked storage). */
export function readStored(storage) {
  try { return storage?.getItem(DECK_KEY) ?? null; } catch { return null; }
}
export function writeStored(storage, value) {
  try { storage?.setItem(DECK_KEY, value); return true; } catch { return false; }
}

/** The address of the same page with `view` set, every other query kept. */
export function withView(search, view) {
  const q = new URLSearchParams(search || '');
  q.set('view', view);
  return '?' + q.toString();
}

/** Which way a finished touch moved a carousel: -1 back, 1 on, 0 neither.
    It has to travel far enough and be more sideways than up-and-down, or it
    was the column being scrolled. */
export function swipeStep(dx, dy, min = 48) {
  if (Math.abs(dx) < min || Math.abs(dx) <= Math.abs(dy) * 1.2) return 0;
  return dx < 0 ? 1 : -1;
}
