/* THE COLOUR SCHEME's choosing rules, in plain node (v1.52.0; three picks,
   stage 1, 2026-11-13).

   Run:  node tests/test_scheme_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  RESET_KEY, RESET_MARK, SCHEME_KEY, barScheme, buttonFace, isToggleKey, migrateOnce, nextChoice,
  otherScheme, parsePick, parseStored, pickAttr, readStored, resolveScheme, whereFrom, writeStored,
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
const classes = (...names) => ({ contains: (c) => names.includes(c) });

const PICKS = ['light', 'dark', null];
const PLACES = ['table', 'sky', 'depths', 'other'];

test('a stored pick wins over the OS preference', () => {
  assert.equal(resolveScheme('dark', true), 'dark');
  assert.equal(resolveScheme('light', false), 'light');
});

test('no pick: the OS decides the panels, and no signal at all means dark', () => {
  assert.equal(resolveScheme(null, true), 'light');
  assert.equal(resolveScheme(null, false), 'dark');
  assert.equal(resolveScheme(null, undefined), 'dark');
});

test('junk in storage is no pick (Light/Dark)', () => {
  for (const junk of ['', 'sepia', '1', 'LIGHTS', 'auto', null, undefined, '{}']) {
    assert.equal(parsePick(junk), null, String(junk));
  }
  assert.equal(parsePick(' Light '), 'light');
  assert.equal(parseStored, parsePick);
});

test('the pick as an attribute: auto is Light/Dark', () => {
  assert.equal(pickAttr('light'), 'light');
  assert.equal(pickAttr('dark'), 'dark');
  assert.equal(pickAttr(null), 'auto');
  assert.equal(pickAttr('sepia'), 'auto');
});

test('toggling flips between the two names', () => {
  assert.equal(otherScheme('light'), 'dark');
  assert.equal(otherScheme('dark'), 'light');
  assert.equal(otherScheme('anything'), 'light');
});

// The decided table, written out (not recomputed): pick × OS light? × place.
const BAR = {
  light: { true: { table: 'light', sky: 'light', depths: 'light', other: 'light' },
           false: { table: 'light', sky: 'light', depths: 'light', other: 'light' } },
  dark:  { true: { table: 'dark', sky: 'dark', depths: 'dark', other: 'dark' },
           false: { table: 'dark', sky: 'dark', depths: 'dark', other: 'dark' } },
  auto:  { true: { table: 'light', sky: 'light', depths: 'dark', other: 'light' },
           false: { table: 'dark', sky: 'light', depths: 'dark', other: 'dark' } },
};

test('the bar: all 24 cases of pick × OS × place', () => {
  let n = 0;
  for (const pick of PICKS) for (const os of [true, false]) for (const where of PLACES) {
    assert.equal(barScheme(pick, os, where), BAR[pickAttr(pick)][os][where], `${pick} ${os} ${where}`);
    n++;
  }
  assert.equal(n, 24);
});

test('where the camera is, from body classes', () => {
  assert.equal(whereFrom(classes()), 'table');
  assert.equal(whereFrom(classes('in-sky')), 'sky');
  assert.equal(whereFrom(classes('depths')), 'depths');
  for (const c of ['scene-open', 'deck', 'phone']) {
    assert.equal(whereFrom(classes(c)), 'other', c);
    assert.equal(whereFrom(classes(c, 'in-sky')), 'other', `${c} in the sky`);
    assert.equal(whereFrom(classes(c, 'depths')), 'other', `${c} in the depths`);
  }
  assert.equal(whereFrom(null), 'table');
  assert.equal(whereFrom({ contains() { throw new Error('no'); } }), 'table');
});

test('from Light/Dark a press pins the scheme the bar is not showing, in every place', () => {
  for (const os of [true, false]) for (const where of PLACES) {
    const shown = barScheme(null, os, where);
    const next = nextChoice(null, os, where);
    assert.notEqual(next, shown, `${os} ${where}`);
    assert.equal(barScheme(next, os, where), next);   // and the bar then shows it
  }
  assert.equal(nextChoice(null, true, 'sky'), 'dark');
  assert.equal(nextChoice(null, false, 'depths'), 'light');
});

test('from Light a press goes to Dark and from Dark to Light; never null', () => {
  for (const os of [true, false, undefined]) for (const where of [...PLACES, undefined]) {
    assert.equal(nextChoice('light', os, where), 'dark');
    assert.equal(nextChoice('dark', os, where), 'light');
    for (const pick of [...PICKS, 'sepia']) assert.notEqual(nextChoice(pick, os, where), null);
  }
});

test('with no place, a press is the 11-01 rule: the OS scheme not on screen', () => {
  assert.equal(nextChoice(null, false), 'light');
  assert.equal(nextChoice(null, true), 'dark');
  assert.equal(nextChoice('sepia', false), 'light');   // junk counts as no pick
});

test('the pick persists under its key and reads back', () => {
  const s = memory();
  assert.equal(readStored(s), null);
  assert.equal(writeStored(s, 'light'), true);
  assert.equal(s.m[SCHEME_KEY], 'light');
  assert.equal(readStored(s), 'light');
  assert.equal(SCHEME_KEY, 'atlas.scheme');
});

test('Light/Dark (null) removes the stored key', () => {
  const s = memory({ [SCHEME_KEY]: 'dark' });
  assert.equal(writeStored(s, null), true);
  assert.equal(SCHEME_KEY in s.m, false);
  assert.equal(readStored(s), null);
});

test('storage that throws or is absent never breaks the page', () => {
  assert.equal(readStored(throwing), null);
  assert.equal(writeStored(throwing, 'dark'), false);
  assert.equal(readStored(null), null);
  assert.equal(writeStored(undefined, 'dark'), false);
});

test('the button says the pick and what a press does', () => {
  const a = buttonFace(null, true), l = buttonFace('light', false), d = buttonFace('dark', true);
  assert.equal(a.title, 'Light/Dark: the bar follows the map. A press pins the other one (T)');
  assert.equal(l.title, 'Light: press for Dark (T)');
  assert.equal(d.title, 'Dark: press for Light (T)');
  assert.equal(a.label, 'Light/Dark: the bar follows the map. A press pins the other one');
  assert.equal(l.label, 'Light: press for Dark');
  assert.equal(d.label, 'Dark: press for Light');
  assert.deepEqual(buttonFace(null, false), a);   // the words do not follow the OS
  for (const f of [a, l, d]) {
    assert.deepEqual(Object.keys(f).sort(), ['label', 'title']);   // no pressed, no glyph
  }
});

test('migrateOnce: clears a stored light or dark and writes the mark', () => {
  for (const pick of ['light', 'dark']) {
    const s = memory({ [SCHEME_KEY]: pick });
    assert.equal(migrateOnce(s), true);
    assert.equal(SCHEME_KEY in s.m, false);
    assert.equal(s.m[RESET_KEY], RESET_MARK);
  }
  assert.equal(RESET_KEY, 'atlas.scheme.reset');
  assert.equal(RESET_MARK, '2026-11');
});

test('migrateOnce: a second run leaves a new pick alone', () => {
  const s = memory({ [SCHEME_KEY]: 'light' });
  migrateOnce(s);
  writeStored(s, 'dark');
  assert.equal(migrateOnce(s), false);
  assert.equal(readStored(s), 'dark');
});

test('migrateOnce: storage whose every call throws does not throw', () => {
  const all = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); },
                removeItem() { throw new Error('x'); } };
  assert.doesNotThrow(() => migrateOnce(all));
  assert.equal(migrateOnce(all), false);
  assert.doesNotThrow(() => migrateOnce(throwing));   // no removeItem at all
  assert.equal(migrateOnce(null), false);
});

test('migrateOnce: a failing mark write leaves the pick in place', () => {
  const s = memory({ [SCHEME_KEY]: 'light' });
  s.setItem = () => { throw new Error('quota'); };
  assert.equal(migrateOnce(s), false);
  assert.equal(readStored(s), 'light');
  assert.equal(RESET_KEY in s.m, false);
});

test('migrateOnce: junk in the mark counts as no mark', () => {
  for (const junk of ['', '2026-10', 'true', '2026-11 ']) {
    const s = memory({ [SCHEME_KEY]: 'dark', [RESET_KEY]: junk });
    assert.equal(migrateOnce(s), true, JSON.stringify(junk));
    assert.equal(readStored(s), null);
    assert.equal(s.m[RESET_KEY], RESET_MARK);
  }
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
