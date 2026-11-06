/* THE DECK's choosing rules, in plain node (v1.66.0 phone, v1.67.0 desktop).

   Run:  node tests/test_deck_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  DECK_KEY, PHONE_MEDIA, opensOnDeck, parseView, readStored, storedFor, swipeStep,
  wantsPhone, withView, writeStored,
} from '../static/js/deck-model.js';

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

test('the phone layout follows the screen when the address says nothing', () => {
  assert.equal(wantsPhone(null, true), true);
  assert.equal(wantsPhone(null, false), false);
  assert.equal(wantsPhone(undefined, undefined), false);
});

test('?view=phone asks for the phone layout anywhere; map and charts never do', () => {
  assert.equal(wantsPhone('phone', false), true);
  assert.equal(wantsPhone(' PHONE ', false), true);
  assert.equal(wantsPhone('map', true), false);
  assert.equal(wantsPhone('charts', true), false);
});

test('a phone opens on the deck whatever was stored', () => {
  assert.equal(opensOnDeck(null, true, null), true);
  assert.equal(opensOnDeck(null, true, 'map'), true);
});

test('a wide screen opens on the map unless the viewer last chose the charts', () => {
  assert.equal(opensOnDeck(null, false, null), false);
  assert.equal(opensOnDeck(null, false, 'map'), false);
  assert.equal(opensOnDeck(null, false, 'charts'), true);
  assert.equal(opensOnDeck(null, false, 'nonsense'), false);
});

test('the address overrules the screen and the stored choice', () => {
  assert.equal(opensOnDeck('map', true, 'charts'), false);
  assert.equal(opensOnDeck('charts', false, 'map'), true);
  assert.equal(opensOnDeck('phone', false, null), true);
});

test('an unknown view is ignored, not obeyed', () => {
  assert.equal(parseView('desk'), null);
  assert.equal(opensOnDeck('desk', false, 'charts'), true);
  assert.equal(wantsPhone('desk', true), true);
});

test('a toggle remembers what it left showing', () => {
  assert.equal(storedFor(true), 'charts');
  assert.equal(storedFor(false), 'map');
  const s = memory();
  assert.equal(writeStored(s, storedFor(true)), true);
  assert.equal(s.m[DECK_KEY], 'charts');
  assert.equal(readStored(s), 'charts');
});

test('blocked storage never throws: nothing read, nothing written', () => {
  assert.equal(readStored(throwing), null);
  assert.equal(writeStored(throwing, 'charts'), false);
  assert.equal(readStored(null), null);
});

test('the way back to the map keeps every other query value', () => {
  assert.equal(withView('', 'map'), '?view=map');
  assert.equal(withView('?style=x.webp', 'map'), '?style=x.webp&view=map');
  assert.equal(withView('?view=phone&style=x.webp', 'map'), '?view=map&style=x.webp');
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

console.log(`\n${passed} passed`);
