/* How the finding-glass matches and orders. `node tests/test_palette_model.mjs` */

import assert from 'node:assert/strict';
import { score, rank } from '../static/js/palette-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

test('an empty query scores nothing, and a miss is -1', () => {
  assert.equal(score('anything', ''), 0);
  assert.equal(score('gate', 'x'), -1);
  assert.equal(score('gate', 'ag'), -1);            // the letters are there, in the wrong order
  assert.equal(score('', 'a'), -1);
});

test('letters in a row and letters that start a word are worth more', () => {
  // g: 1 + first-in-a-row 2 + starts the text 3; a: 1 + second-in-a-row 4
  assert.equal(score('gate', 'ga'), 11);
  // g: 6 as above; t is not next to it: 1
  assert.equal(score('gate', 'gt'), 7);
  // m starts the second word: 1 + 3, and no run because it is not where the search began
  assert.equal(score('the mill', 'm'), 4);
  // a letter in the middle of a word, not where the search began: just 1
  assert.equal(score('gate', 't'), 1);
});

test('a run is counted from where the last match ended', () => {
  // a at 1 (not at the start, so no run): 1; t at 2 follows it: 1 + 2
  assert.equal(score('gate', 'at'), 4);
  // every letter of the word, in a row: (1+2+3) + (1+4) + (1+6) + (1+8)
  assert.equal(score('gate', 'gate'), 27);
});

const ITEMS = [
  { label: 'GATEWAY', hay: 'gateway edge 10.0.0.1' },
  { label: 'GATE', hay: 'gate edge 10.0.0.2' },
  { label: 'Grafana', hay: 'grafana gate http://gate:3000' },
  { label: 'MILL', hay: 'mill farm 10.0.1.1' },
  { label: 'Wiki', hay: 'wiki mill http://mill:8080' },
];

test('no query shows everything in the order given, up to the limit', () => {
  assert.deepEqual(rank(ITEMS, '', 8), ITEMS);
  assert.notEqual(rank(ITEMS, '', 8), ITEMS);
  assert.deepEqual(rank(ITEMS, '', 2).map((it) => it.label), ['GATEWAY', 'GATE']);
});

test('matches come best first, and a tie goes to the shorter label', () => {
  // both gates start with the query and score the same; the shorter name wins
  assert.deepEqual(rank(ITEMS, 'gate', 8).map((it) => it.label), ['GATE', 'GATEWAY', 'Grafana']);
  assert.deepEqual(rank(ITEMS, 'mill', 8).map((it) => it.label), ['MILL', 'Wiki']);
});

test('what does not match is left out, and the limit cuts the rest', () => {
  assert.deepEqual(rank(ITEMS, 'zzz', 8), []);
  assert.deepEqual(rank(ITEMS, 'gate', 1).map((it) => it.label), ['GATE']);
  assert.deepEqual(rank([], 'gate', 8), []);
});

test('items that tie on score and length keep the order they were given in', () => {
  const twins = [{ label: 'AB', hay: 'ab one' }, { label: 'CD', hay: 'ab two' }];
  assert.deepEqual(rank(twins, 'ab', 8).map((it) => it.label), ['AB', 'CD']);
});

console.log(`\n${passed} passed`);
