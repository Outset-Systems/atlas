/* What a live feed adds up to. `node tests/test_signals_model.mjs` */

import assert from 'node:assert/strict';
import { tally, colophonText } from '../static/js/signals-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const FEED = {
  gate: { state: 'down' },
  web: { state: 'down', cause: 'gate' },
  db: { state: 'down', cause: 'gate', via: 'web' },
  nas: { state: 'degraded' },
  cam: { state: 'healthy' },
  lab: { state: 'maintenance' },
  loft: { state: 'slumbering' },
  blank: {},
  offmap: { state: 'down' },
};

test('a place that is down is dark, and one down behind another is caused', () => {
  const got = tally(['gate', 'web', 'db', 'nas', 'cam', 'lab', 'loft', 'blank', 'unwatched'], FEED);
  assert.deepEqual(got, { dark: 1, caused: 2, darkIds: ['gate'] });
});

test('only the places drawn are counted, in the order they are drawn', () => {
  assert.deepEqual(tally(['nas', 'offmap', 'gate'], FEED), { dark: 2, caused: 0, darkIds: ['offmap', 'gate'] });
  assert.deepEqual(tally(['cam', 'nas'], FEED), { dark: 0, caused: 0, darkIds: [] });
});

test('degraded, maintenance and slumbering are not faults to count', () => {
  assert.deepEqual(tally(['nas', 'lab', 'loft'], FEED), { dark: 0, caused: 0, darkIds: [] });
});

test('a cause is only read on a place that is down', () => {
  const feed = { a: { state: 'degraded', cause: 'b' }, b: { state: 'healthy', cause: 'c' } };
  assert.deepEqual(tally(['a', 'b'], feed), { dark: 0, caused: 0, darkIds: [] });
});

test('no feed, or nothing drawn, is all quiet', () => {
  assert.deepEqual(tally(['gate'], undefined), { dark: 0, caused: 0, darkIds: [] });
  assert.deepEqual(tally([], FEED), { dark: 0, caused: 0, darkIds: [] });
  assert.deepEqual(tally(undefined, FEED), { dark: 0, caused: 0, darkIds: [] });
});

test('one dark place is named', () => {
  assert.equal(colophonText(1, 0, 'GATE'), '⚠ GATE has gone dark');
});

test('what lies behind one cause lies behind "it"', () => {
  assert.equal(colophonText(1, 1, 'GATE'), '⚠ GATE has gone dark — 1 place behind it');
  assert.equal(colophonText(1, 6, 'GATE'), '⚠ GATE has gone dark — 6 places behind it');
});

test('several dark places are counted, and what lies behind them lies behind "them"', () => {
  assert.equal(colophonText(3, 0, 'GATE'), '⚠ 3 places are dark');
  assert.equal(colophonText(2, 1, 'GATE'), '⚠ 2 places are dark — 1 place behind them');
  assert.equal(colophonText(2, 9, 'GATE'), '⚠ 2 places are dark — 9 places behind them');
});

test('faults with no cause left standing are still said', () => {
  assert.equal(colophonText(0, 1), '⚠ 1 place still unreachable');
  assert.equal(colophonText(0, 4), '⚠ 4 places still unreachable');
});

test('nothing dark, nothing to say', () => {
  assert.equal(colophonText(0, 0), '');
  assert.equal(colophonText(0, 0, 'GATE'), '');
});

console.log(`\n${passed} passed`);
