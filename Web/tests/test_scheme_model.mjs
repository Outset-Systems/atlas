/* THE COLOUR SCHEME's choosing rules, in plain node (v1.52.0; three picks,
   stage 1, 2026-11-13).

   Run:  node tests/test_scheme_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  RESET_KEY, RESET_MARK, SCHEME_KEY, barScheme, isToggleKey, migrateOnce, nextChoice,
  otherScheme, panelScheme, parsePick, parseStored, pickAttr, readStored, resolveScheme, whereFrom,
  writeStored,
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
  for (const c of ['deck', 'phone']) {
    assert.equal(whereFrom(classes(c)), 'other', c);
    assert.equal(whereFrom(classes(c, 'in-sky')), 'other', `${c} in the sky`);
    assert.equal(whereFrom(classes(c, 'depths')), 'other', `${c} in the depths`);
    assert.equal(whereFrom(classes(c, 'in-sky', 'scene-open')), 'other', `${c}, a scene, in the sky`);
  }
  // a scene is where it was opened (2026-11-20): only over the table is it 'other'
  assert.equal(whereFrom(classes('scene-open')), 'other');
  assert.equal(whereFrom(classes('scene-open', 'in-sky')), 'sky');
  assert.equal(whereFrom(classes('scene-open', 'depths')), 'depths');
  assert.equal(whereFrom(null), 'table');
  assert.equal(whereFrom({ contains() { throw new Error('no'); } }), 'table');
});

test('the panels: a scene over the Sky is light and over the Depths dark, under Light/Dark only', () => {
  for (const os of [true, false]) {
    const osScheme = os ? 'light' : 'dark';
    // no scene: the OS, wherever the camera is
    for (const c of [[], ['in-sky'], ['depths'], ['deck'], ['phone']]) {
      assert.equal(panelScheme(null, os, classes(...c)), osScheme, `${os} ${c}`);
    }
    assert.equal(panelScheme(null, os, classes('scene-open', 'in-sky')), 'light');
    assert.equal(panelScheme(null, os, classes('scene-open', 'depths')), 'dark');
    assert.equal(panelScheme(null, os, classes('scene-open')), osScheme);
    // the Deck and a phone follow the OS under a scene too
    assert.equal(panelScheme(null, os, classes('scene-open', 'in-sky', 'deck')), osScheme);
    assert.equal(panelScheme(null, os, classes('scene-open', 'depths', 'phone')), osScheme);
    // a pick holds everywhere
    for (const pick of ['light', 'dark']) {
      for (const c of [[], ['scene-open', 'in-sky'], ['scene-open', 'depths']]) {
        assert.equal(panelScheme(pick, os, classes(...c)), pick, `${pick} ${os} ${c}`);
      }
    }
    // the panel and the bar agree under a scene, in every place
    for (const c of [['in-sky'], ['depths'], [], ['deck'], ['phone', 'in-sky']]) {
      const cl = classes('scene-open', ...c);
      assert.equal(panelScheme(null, os, cl), barScheme(null, os, whereFrom(cl)), `${os} ${c}`);
    }
  }
  assert.equal(panelScheme(null, false, null), 'dark');
  assert.equal(panelScheme(null, true, { contains() { throw new Error('no'); } }), 'light');
});

test('T under a scene over the Sky pins the scheme the scene is not showing', () => {
  const sky = classes('scene-open', 'in-sky');
  assert.equal(nextChoice(null, false, whereFrom(sky)), 'dark');
  assert.equal(nextChoice(null, true, whereFrom(classes('scene-open', 'depths'))), 'light');
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
