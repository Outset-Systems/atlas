/* FOLDS' rules, in plain node (2026-11-15, stage 4 of the NODES plan: the
   admin pages' sections open and shut, remembered per page, and a shut one
   keeps its loud fact).

   Run:  node tests/test_fold_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  CROWDED, FOLD_KEY, MAX_KEYS, choose, flip, isOpen, opensAtFirst, readFolds, sealsByHand, sealsDue, tripsLoud, writeFolds,
} from '../static/js/fold-model.js';

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

test('each page keeps its own choices', () => {
  const s = memory();
  assert.equal(writeFolds(s, 'accounts', { 'place:a': false }), true);
  writeFolds(s, 'seals', { 'kind:tls': true });
  assert.deepEqual(readFolds(s, 'accounts'), { 'place:a': false });
  assert.deepEqual(readFolds(s, 'seals'), { 'kind:tls': true });
  assert.ok(`${FOLD_KEY}accounts` in s.m);
});

test('anything odd in storage reads as no choice', () => {
  for (const raw of ['not json', '[1,2]', 'null', '7', '"x"']) {
    assert.deepEqual(readFolds(memory({ [`${FOLD_KEY}p`]: raw }), 'p'), {}, raw);
  }
  assert.deepEqual(readFolds(memory({ [`${FOLD_KEY}p`]: '{"a":true,"b":"yes","c":1}' }), 'p'), { a: true });
  assert.deepEqual(readFolds(throwing, 'p'), {});
  assert.deepEqual(readFolds(null, 'p'), {});
  assert.equal(writeFolds(throwing, 'p', { a: true }), false);
});

test('a stored choice wins over the default, either way', () => {
  assert.equal(isOpen({}, 'k', true), true);
  assert.equal(isOpen({}, 'k', false), false);
  assert.equal(isOpen({ k: false }, 'k', true), false);
  assert.equal(isOpen({ k: true }, 'k', false), true);
  assert.equal(isOpen(null, 'k'), true);
});

test('a flip turns it the other way from how it shows', () => {
  assert.deepEqual(flip({}, 'k', true), { k: false });
  assert.deepEqual(flip({}, 'k', false), { k: true });
  assert.deepEqual(flip({ k: false }, 'k', false), { k: true });
});

test('the latest choices are kept, the oldest go first', () => {
  let st = {};
  for (let i = 0; i < MAX_KEYS + 5; i++) st = choose(st, `place:p${i}`, false);
  st = choose(st, 'place:p0', true);           // chosen again: now the latest
  const s = memory();
  writeFolds(s, 'accounts', st);
  const back = readFolds(s, 'accounts');
  assert.equal(Object.keys(back).length, MAX_KEYS);
  assert.equal(back['place:p0'], true);
  assert.ok(!('place:p1' in back) && 'place:p6' in back);
});

test('a page opens whole while short; past that, only what carries its finding', () => {
  assert.equal(opensAtFirst(0, CROWDED), true);
  assert.equal(opensAtFirst(0, CROWDED + 1), false);
  assert.equal(opensAtFirst(1, CROWDED + 50), true);
  assert.equal(opensAtFirst(undefined, undefined), true);
});

test('a shut seals section still says what lapsed and what lapses within a fortnight', () => {
  assert.deepEqual(sealsDue([-3, -1, 0, 14, 15, 60, null, NaN, 'x']), { lapsed: 2, soon: 2 });
  assert.deepEqual(sealsDue([]), { lapsed: 0, soon: 0 });
  assert.deepEqual(sealsDue(null), { lapsed: 0, soon: 0 });
});

test('a shut tripwire family still says what was touched and what waits', () => {
  assert.deepEqual(tripsLoud([{ voice: 'speaking', unacked: 2 }, { voice: 'silent' }, { voice: 'speaking', unacked: '1' },
    { voice: 'stirred', unacked: -4 }]), { tripped: 2, unacked: 3, dead: 0, expiring: 0 });
  assert.deepEqual(tripsLoud(null), { tripped: 0, unacked: 0, dead: 0, expiring: 0 });
});

test('a shut tripwire family says what cannot trip and which tokens run out (review)', () => {
  const rows = [{ planted: false }, { planted: 'the share' }, { expires_in_days: -2 }, { expires_in_days: 14 },
    { expires_in_days: 15 }, { planted: false, expires_in_days: 1, retired: true }];
  assert.deepEqual(tripsLoud(rows), { tripped: 0, unacked: 0, dead: 1, expiring: 2 });
});

test('a shut seals kind says how many nothing renews (review)', () => {
  assert.equal(sealsByHand([{ renews: 'certbot' }, { renews: '' }, {}, null]), 2);
  assert.equal(sealsByHand(null), 0);
});

console.log(`\n${passed} passed`);
