/* THE DECK's choosing rules, with no DOM (v1.66.0 phone, v1.67.0 desktop).

   THE DECK is the Atlas without its map: the scene band over one scrolling
   column of the watchings (the Sky's and the Depths' charts). deck.js does
   the moving; this file only decides. Unit-tested by tests/test_deck_model.mjs
   under plain node.

   On a PHONE the deck is the page: the map is too small to read and too
   fiddly to steer there. On a wider screen the map is the page and THE ATLAS
   puts it away and brings it back (owner, 2026-11-05); the viewer's last
   choice is remembered in this browser.

   The address can overrule both: `?view=map` keeps the map on any screen,
   `?view=charts` opens on the deck, and `?view=phone` asks for the phone's
   own layout on any screen (what a phone looks like, on a desk). */

/** Narrow, or a short touch screen (a phone turned sideways). */
export const PHONE_MEDIA = '(max-width: 720px), (max-height: 500px) and (pointer: coarse)';

export const DECK_KEY = 'atlas.view';
const VIEWS = ['map', 'charts', 'phone'];

/** The `view` query value, or null when it says nothing usable. */
export function parseView(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  return VIEWS.includes(v) ? v : null;
}

/** True when this page takes the phone's layout. */
export function wantsPhone(viewParam, screenIsPhone) {
  const asked = parseView(viewParam);
  if (asked === 'phone') return true;
  if (asked) return false;
  return screenIsPhone === true;
}

/** True when this page opens on the deck rather than the map. */
export function opensOnDeck(viewParam, screenIsPhone, stored) {
  const asked = parseView(viewParam);
  if (asked) return asked !== 'map';
  if (screenIsPhone === true) return true;
  return parseView(stored) === 'charts';
}

/** What to remember after a toggle on a wide screen. */
export const storedFor = (onDeck) => (onDeck ? 'charts' : 'map');

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
