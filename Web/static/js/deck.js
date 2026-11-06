/* THE DECK — the Atlas without its map: the scene band over one scrolling
   column of the watchings, the Sky's charts and then the Depths'.

   v1.66.0 made it the page on a PHONE, where the map's places were specks and
   every gesture fought the page. v1.67.0 brings it to every screen (owner,
   2026-11-05): on a wide one THE ATLAS puts the map away and brings it back
   (ui.js), and the last choice is remembered in this browser.

   The column holds the SAME #chronicle and #abyss elements, moved out of the
   camera's stage and back again, so chronicle.js draws into them exactly as
   it does on the map and nothing about the charts forks. A comment marks the
   seat each one left, so it goes back to precisely where it was. The look is
   atlas.css "THE DECK"; the rules are deck-model.js.

   Imported straight after scheme.js in atlas.js, so a page that opens on the
   deck has its column before any module looks for the sections. */

import { A, $ } from './config.js';
import {
  PHONE_MEDIA, opensOnDeck, readStored, storedFor, swipeStep, wantsPhone, withView, writeStored,
} from './deck-model.js';

const view = new URLSearchParams(location.search).get('view');
const screenIsPhone = matchMedia(PHONE_MEDIA).matches;
let store = null;
try { store = localStorage; } catch { /* blocked: the choice simply is not remembered */ }

A.PHONE = wantsPhone(view, screenIsPhone);
A.DECK = false;
if (A.PHONE) document.body.classList.add('phone');

const deck = document.createElement('main');
deck.id = 'chart-deck';
deck.setAttribute('aria-label', 'The watchings');

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
  A.setDeck(false, { remember: true });
  A.home?.(true);
});
deck.append(foot);
$('viewport').after(deck);

/* The colophon is the feed's voice (signals.js turns it to an alarm), so on
   the deck it rides at the column's foot instead of floating over a chart. */
const MOVERS = ['chronicle', 'abyss', 'colophon'];
const seats = new Map();

function lift() {
  for (const id of MOVERS) {
    const el = $(id);
    if (!el || seats.has(id)) continue;
    const seat = document.createComment(` ${id} sits here on the map `);
    el.before(seat);
    seats.set(id, seat);
    deck.insertBefore(el, foot);
  }
}
function settle() {
  for (const [id, seat] of seats) seat.replaceWith($(id));
  seats.clear();
}

function paintHome() {
  const home = document.querySelector('[data-scene="atlas"]');
  if (!home) return;
  home.title = A.PHONE ? 'Back to the top'
    : A.DECK ? 'Bring the map back' : 'Centre the map. Once it is centred, put it away: just the charts';
  if (!A.PHONE) home.setAttribute('aria-pressed', String(A.DECK));
}

/** Show the deck (true) or the map (false). `remember` keeps the choice for
    the next visit, which only a wide screen's own toggle should do. */
A.setDeck = function setDeck(on, { remember = false } = {}) {
  on = Boolean(on);
  if (on !== A.DECK) {
    A.DECK = on;
    if (on) lift(); else settle();
    document.body.classList.toggle('deck', on);
    // back on the stage, the sections need their map seats measured again
    if (!on) A.measureWorld?.();
    if (on) deck.scrollTop = 0;
  }
  if (remember && !A.PHONE) writeStored(store, storedFor(on));
  paintHome();
};
A.toggleDeck = (opts) => A.setDeck(!A.DECK, opts);
A.deckTop = () => deck.scrollTo({ top: 0, behavior: 'smooth' });

A.setDeck(opensOnDeck(view, screenIsPhone, readStored(store)));

/* A swipe pages a carousel. On a phone the carousel's ‹ › are hidden (they
   sat on top of the figures), so the swipe presses them instead of reaching
   into chronicle.js's paging. Bound once: the viewers travel with their
   sections, so the listeners do too. */
for (const id of ['chronicle', 'abyss']) {
  const viewer = $(id)?.querySelector('.chron-viewer');
  if (!viewer) continue;
  let x0 = 0, y0 = 0, tracking = false;
  viewer.addEventListener('touchstart', (e) => {
    tracking = A.DECK && e.touches.length === 1;
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
