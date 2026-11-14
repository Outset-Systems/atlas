/* THE VIEWS' choosing rules, in plain node (v1.66.0 phone, v1.67.0 the Deck,
   2026-11-13 the views: MAP, OVERVIEW, NODES and an admin's ALERTS; CHARTS is
   OVERVIEW's old name, landing on its charts; `?place=` opens the map).

   Run:  node tests/test_views_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  ADMIN_VIEWS, ALIASES, DECK_KEY, PHONE_MEDIA, PHONE_VIEWS, VIEWS, allowedView, isView, mayOpen,
  namesCharts, openingView, opensAtCharts, parsePlace, parseSet, parseView, readStored, swipeStep, wantsPhone, withView, writeStored,
} from '../static/js/views-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const memory = (init = {}) => {
  const m = { ...init };
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, m };
};
const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };

test('the views are one list, and phone is a layout, not a view', () => {
  assert.deepEqual(VIEWS, ['map', 'overview', 'nodes', 'alerts']);
  assert.deepEqual(PHONE_VIEWS, ['overview', 'nodes', 'alerts']);
  assert.deepEqual([...ADMIN_VIEWS], ['alerts']);
  assert.equal(isView('phone'), false);
  assert.equal(isView('charts'), false, 'charts is an old name, not a view of its own');
  assert.deepEqual(ALIASES, { charts: 'overview' });
  assert.equal(isView('nodes'), true);
  assert.equal(DECK_KEY, 'atlas.view');
});

test('the phone layout follows the screen when the address says nothing', () => {
  assert.equal(wantsPhone(null, true), true);
  assert.equal(wantsPhone(null, false), false);
  assert.equal(wantsPhone(undefined, undefined), false);
});

test('?view=phone asks for the phone layout anywhere; a view never does', () => {
  assert.equal(wantsPhone('phone', false), true);
  assert.equal(wantsPhone(' PHONE ', false), true);
  assert.equal(wantsPhone('map', true), false);
  assert.equal(wantsPhone('charts', true), false);
  assert.equal(wantsPhone('nodes', true), false);
});

test('a phone opens on OVERVIEW whatever was stored, unless it was NODES', () => {
  assert.equal(openingView(null, true, null), 'overview');
  assert.equal(openingView(null, true, 'overview'), 'overview');
  assert.equal(openingView(null, true, 'charts'), 'overview');
  assert.equal(openingView(null, true, 'nodes'), 'nodes');
  assert.equal(opensAtCharts(null, true, null), false, 'a phone opens at the top, on the facts');
});

test('a phone ignores a stored map', () => {
  assert.equal(openingView(null, true, 'map'), 'overview');
  assert.equal(openingView('phone', false, 'map'), 'overview');
});

test('a wide screen opens on the stored view, else the map', () => {
  assert.equal(openingView(null, false, null), 'map');
  assert.equal(openingView(null, false, 'map'), 'map');
  assert.equal(openingView(null, false, 'overview'), 'overview');
  assert.equal(openingView(null, false, 'nodes'), 'nodes');
});

test('OVERVIEW opens, at its top', () => {
  assert.equal(parseView('overview'), 'overview');
  assert.equal(openingView('overview', false, null), 'overview');
  assert.equal(openingView(' OVERVIEW ', true, 'nodes'), 'overview');
  assert.equal(opensAtCharts('overview', false, 'charts'), false, 'the address names the top');
  assert.equal(opensAtCharts(null, false, 'overview'), false);
});

test('a stored charts is OVERVIEW at the charts, until a pick stores overview', () => {
  assert.equal(openingView(null, false, 'charts'), 'overview');
  assert.equal(opensAtCharts(null, false, 'charts'), true);
  assert.equal(opensAtCharts(null, true, 'charts'), true);
  assert.equal(opensAtCharts('phone', false, 'charts'), true);
  // the address wins over the stored pick
  assert.equal(opensAtCharts('map', false, 'charts'), false);
  assert.equal(opensAtCharts('nodes', false, 'charts'), false);
});

test('an unknown stored value is the map', () => {
  assert.equal(openingView(null, false, 'nonsense'), 'map');
  assert.equal(openingView(null, false, 'phone'), 'map');
  assert.equal(openingView(null, false, ''), 'map');
});

test('the address overrules the screen and the stored choice', () => {
  assert.equal(openingView('map', true, 'charts'), 'map');
  assert.equal(openingView('charts', false, 'map'), 'overview');
  assert.equal(openingView('nodes', false, 'charts'), 'nodes');
  assert.equal(openingView('phone', false, null), 'overview');
  assert.equal(openingView('phone', false, 'nodes'), 'nodes');
});

test('?view=charts still lands on the charts: OVERVIEW, scrolled to them', () => {
  assert.equal(parseView('charts'), 'overview');
  assert.equal(namesCharts(' Charts '), true);
  assert.equal(namesCharts('overview'), false);
  assert.equal(openingView('charts', false, null), 'overview');
  assert.equal(opensAtCharts('charts', false, null), true);
  assert.equal(openingView(' Charts ', true, 'nodes'), 'overview');
  assert.equal(opensAtCharts(' Charts ', true, 'nodes'), true);
  assert.equal(wantsPhone('charts', true), false);
});

test('an old name never reaches the prototype', () => {
  assert.equal(parseView('constructor'), null);
  assert.equal(parseView('__proto__'), null);
  assert.equal(parseView('toString'), null);
});

test('an unknown view is ignored, not obeyed', () => {
  assert.equal(parseView('desk'), null);
  assert.equal(openingView('desk', false, 'charts'), 'overview');
  assert.equal(opensAtCharts('desk', false, 'charts'), true);
  assert.equal(openingView('desk', false, null), 'map');
  assert.equal(wantsPhone('desk', true), true);
});

test('a pick is remembered by its name', () => {
  const s = memory();
  assert.equal(writeStored(s, 'nodes'), true);
  assert.equal(s.m[DECK_KEY], 'nodes');
  assert.equal(readStored(s), 'nodes');
  assert.equal(openingView(null, false, readStored(s)), 'nodes');
});

test('blocked storage never throws: nothing read, nothing written', () => {
  assert.equal(readStored(throwing), null);
  assert.equal(writeStored(throwing, 'charts'), false);
  assert.equal(readStored(null), null);
});

test('?set= is a slug or nothing', () => {
  assert.equal(parseSet('edge-boxes'), 'edge-boxes');
  assert.equal(parseSet(' core_1 '), 'core_1');
  assert.equal(parseSet(null), null);
  assert.equal(parseSet(''), null);
  assert.equal(parseSet('-lead'), null);
  assert.equal(parseSet('a b'), null);
  assert.equal(parseSet('<x>'), null);
  assert.equal(parseSet('x'.repeat(81)), null);
  assert.equal(parseSet(new URLSearchParams('?view=nodes&set=dmz').get('set')), 'dmz');
});

test('the way back to the map keeps every other query value', () => {
  assert.equal(withView('', 'map'), '?view=map');
  assert.equal(withView('?style=x.webp', 'map'), '?style=x.webp&view=map');
  assert.equal(withView('?view=phone&style=x.webp', 'map'), '?view=map&style=x.webp');
  assert.equal(withView('?view=nodes&set=dmz', 'map'), '?view=map&set=dmz');
});

test('the media query covers narrow screens and a phone on its side', () => {
  assert.match(PHONE_MEDIA, /max-width: 720px/);
  assert.match(PHONE_MEDIA, /max-height: 500px\) and \(pointer: coarse\)/);
});

test('a sideways swipe pages, a scroll does not', () => {
  assert.equal(swipeStep(-120, 10), 1);
  assert.equal(swipeStep(120, 10), -1);
  assert.equal(swipeStep(-30, 0), 0);
  assert.equal(swipeStep(-80, 90), 0);
  assert.equal(swipeStep(-80, 60), 1);
});

test('ALERTS is an admin\'s: anyone else lands where nothing named a view', () => {
  assert.equal(mayOpen('alerts', true), true);
  assert.equal(mayOpen('alerts', false), false);
  assert.equal(mayOpen('alerts', undefined), false);
  assert.equal(mayOpen('nodes', false), true);
  assert.equal(mayOpen('charts', true), false, 'an old name is not a view');
  // an admin
  assert.equal(openingView('alerts', false, null, { admin: true }), 'alerts');
  assert.equal(openingView(null, false, 'alerts', { admin: true }), 'alerts');
  assert.equal(openingView(null, true, 'alerts', { admin: true }), 'alerts');
  assert.equal(openingView('phone', false, 'alerts', { admin: true }), 'alerts');
  // anyone else: the map on a desk, OVERVIEW on a phone
  assert.equal(openingView('alerts', false, null), 'map');
  assert.equal(openingView('alerts', false, 'nodes', { admin: false }), 'map');
  assert.equal(openingView('alerts', true, null, { admin: false }), 'overview');
  assert.equal(openingView(null, false, 'alerts', { admin: false }), 'map');
  assert.equal(openingView(null, true, 'alerts', { admin: false }), 'overview');
  assert.equal(openingView('phone', false, 'alerts', { admin: false }), 'overview');
});

test('a press asks for a view; what this viewer gets', () => {
  assert.equal(allowedView('alerts', false, true), 'alerts');
  assert.equal(allowedView('alerts', false, false), 'map');
  assert.equal(allowedView('alerts', true, false), 'overview');
  assert.equal(allowedView('map', true, true), 'overview', 'a phone never shows the map');
  assert.equal(allowedView('nonsense', false, true), 'map');
  assert.equal(allowedView('nodes', false, false), 'nodes');
});

test('?place= is a place\'s id, or nothing', () => {
  assert.equal(parsePlace('core'), 'core');
  assert.equal(parsePlace(' core-switch.2 '), 'core-switch.2');
  assert.equal(parsePlace(new URLSearchParams('?place=nas_1&view=map').get('place')), 'nas_1');
  assert.equal(parsePlace(null), null);
  assert.equal(parsePlace(''), null);
  assert.equal(parsePlace('-lead'), null);
  assert.equal(parsePlace('a b'), null);
  assert.equal(parsePlace('<script>'), null);
  assert.equal(parsePlace('../x'), null);
  assert.equal(parsePlace('x'.repeat(121)), null);
});

test('?place= opens the map over a stored pick, never over ?view=', () => {
  assert.equal(openingView(null, false, 'nodes', { place: 'core' }), 'map');
  assert.equal(openingView(null, false, 'charts', { place: 'core' }), 'map');
  assert.equal(opensAtCharts(null, false, 'charts', { place: 'core' }), false);
  assert.equal(openingView(null, false, 'alerts', { admin: true, place: 'core' }), 'map');
  // a phone has no map: its default
  assert.equal(openingView(null, true, 'nodes', { place: 'core' }), 'overview');
  // the address names a view: it wins
  assert.equal(openingView('nodes', false, null, { place: 'core' }), 'nodes');
  // a place that is not an id says nothing
  assert.equal(openingView(null, false, 'nodes', { place: 'a b' }), 'nodes');
});

console.log(`\n${passed} passed`);
