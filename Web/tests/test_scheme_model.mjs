/* THE COLOUR SCHEME's choosing rules, in plain node (v1.52.0).

   Run:  node tests/test_scheme_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  SCHEME_KEY, buttonFace, isToggleKey, nextChoice, otherScheme, parseStored, readStored,
  resolveScheme, writeStored,
} from '../static/js/scheme-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const memory = (init = {}) => {
  const m = { ...init };
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); },
           removeItem: (k) => { delete m[k]; }, m };
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

test('the cycle: auto → the scheme the system is not showing → the other → auto', () => {
  // a system that prefers dark: the first click must show light
  assert.equal(nextChoice(null, false), 'light');
  assert.equal(nextChoice('light', false), 'dark');
  assert.equal(nextChoice('dark', false), null);
  // a system that prefers light: the first click must show dark
  assert.equal(nextChoice(null, true), 'dark');
  assert.equal(nextChoice('dark', true), 'light');
  assert.equal(nextChoice('light', true), null);
  // junk counts as auto
  assert.equal(nextChoice('sepia', false), 'light');
});

test('every click in the cycle that leaves auto changes what is drawn', () => {
  for (const sys of [true, false]) {
    let choice = null;
    const seen = [resolveScheme(choice, sys)];
    for (let i = 0; i < 2; i++) { choice = nextChoice(choice, sys); seen.push(resolveScheme(choice, sys)); }
    assert.notEqual(seen[0], seen[1], 'the first click flips the panels');
    assert.notEqual(seen[1], seen[2]);
  }
});

test('the button: ☾ dark, ☀ light, ◐ while following the system, and says what a click does', () => {
  const l = buttonFace('light', false), d = buttonFace('dark', false), a = buttonFace(null, true);
  assert.equal(l.glyph, '☀'); assert.equal(d.glyph, '☾'); assert.equal(a.glyph, '◐');
  assert.equal(l.icon, 'sun'); assert.equal(d.icon, 'moon'); assert.equal(a.icon, 'auto');
  assert.match(l.title, /^Light panels — switch to dark \(T\)$/);
  assert.match(d.title, /^Dark panels — follow your system \(T\)$/);
  assert.match(a.title, /^Light panels, following your system — switch to dark \(T\)$/);
  assert.equal(l.pressed, true); assert.equal(d.pressed, false); assert.equal(a.pressed, true);
});

test('choosing auto forgets the stored pick', () => {
  const s = memory({ [SCHEME_KEY]: 'dark' });
  assert.equal(writeStored(s, null), true);
  assert.equal(SCHEME_KEY in s.m, false);
  assert.equal(readStored(s), null);
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
