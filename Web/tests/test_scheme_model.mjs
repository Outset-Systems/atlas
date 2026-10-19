/* THE COLOUR SCHEME's choosing rules, in plain node (v1.52.0).

   Run:  node tests/test_scheme_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  SCHEME_KEY, buttonFace, isToggleKey, otherScheme, parseStored, readStored,
  resolveScheme, writeStored,
} from '../static/js/scheme-model.js';

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

test('a stored pick wins over the OS preference', () => {
  assert.equal(resolveScheme('dark', true), 'dark');
  assert.equal(resolveScheme('light', false), 'light');
});

test('no pick: the OS decides, and no signal at all means dark', () => {
  assert.equal(resolveScheme(null, true), 'light');
  assert.equal(resolveScheme(null, false), 'dark');
  assert.equal(resolveScheme(null, undefined), 'dark');
});

test('junk in storage is no pick', () => {
  for (const junk of ['', 'sepia', '1', 'LIGHTS', null, undefined, '{}']) {
    assert.equal(parseStored(junk), null, String(junk));
  }
  assert.equal(parseStored(' Light '), 'light');
});

test('toggling flips between the two names', () => {
  assert.equal(otherScheme('light'), 'dark');
  assert.equal(otherScheme('dark'), 'light');
  assert.equal(otherScheme('anything'), 'light');
});

test('the pick persists under its key and reads back', () => {
  const s = memory();
  assert.equal(readStored(s), null);
  assert.equal(writeStored(s, 'light'), true);
  assert.equal(s.m[SCHEME_KEY], 'light');
  assert.equal(readStored(s), 'light');
  assert.equal(SCHEME_KEY, 'atlas.scheme');
});

test('storage that throws or is absent never breaks the page', () => {
  assert.equal(readStored(throwing), null);
  assert.equal(writeStored(throwing, 'dark'), false);
  assert.equal(readStored(null), null);
  assert.equal(writeStored(undefined, 'dark'), false);
});

test('the button shows the scheme in force and says what a click does', () => {
  const l = buttonFace('light'), d = buttonFace('dark');
  assert.equal(l.glyph, '☀'); assert.equal(d.glyph, '☾');
  assert.match(l.title, /switch to dark \(T\)$/);
  assert.match(d.title, /switch to light \(T\)$/);
  assert.equal(l.pressed, true); assert.equal(d.pressed, false);
});

test('T toggles, but never while typing or with a modifier', () => {
  const el = (tagName, extra = {}) => ({ tagName, ...extra });
  assert.equal(isToggleKey({ key: 't', target: el('BODY') }), true);
  assert.equal(isToggleKey({ key: 'T', target: el('DIV') }), true);
  assert.equal(isToggleKey({ key: 't', target: el('INPUT') }), false);
  assert.equal(isToggleKey({ key: 't', target: el('textarea') }), false);
  assert.equal(isToggleKey({ key: 't', target: el('SELECT') }), false);
  assert.equal(isToggleKey({ key: 't', target: el('DIV', { isContentEditable: true }) }), false);
  assert.equal(isToggleKey({ key: 't', ctrlKey: true, target: el('BODY') }), false);
  assert.equal(isToggleKey({ key: 't', metaKey: true, target: el('BODY') }), false);
  assert.equal(isToggleKey({ key: 'g', target: el('BODY') }), false);
  assert.equal(isToggleKey(null), false);
});

console.log(`\n${passed} passed`);
