/* THE TABLE'S WINDOW, in plain node (2026-11-15, stage 5 of the NODES plan:
   past a few hundred rows, NODES draws only the rows on screen).

   Run:  node tests/test_window_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { EDGE, GUESS, OVERSCAN, WINDOW_MIN, guess, needsRedraw, rowWindow } from '../static/js/window-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const even = (n, h = 50) => Array.from({ length: n }, () => h);

test('the constants are sane', () => {
  assert.ok(WINDOW_MIN > 2 * OVERSCAN && OVERSCAN > EDGE && GUESS > 0);
});

test('nothing to draw when there are no rows', () => {
  assert.deepEqual(rowWindow({ count: 0 }), { start: 0, end: 0, first: 0, last: -1, before: 0, after: 0, total: 0 });
});

test('fewer rows than a screen: all of them, no spacers', () => {
  const w = rowWindow({ count: 10, heights: even(10), top: 0, viewport: 800 });
  assert.deepEqual([w.start, w.end, w.first, w.last, w.before, w.after], [0, 10, 0, 9, 0, 0]);
});

test('at the top: the screen and the overscan below, a spacer for the rest', () => {
  const w = rowWindow({ count: 1000, heights: even(1000), top: 0, viewport: 500, overscan: 20 });
  assert.deepEqual([w.start, w.end, w.first, w.last], [0, 30, 0, 9]);
  assert.equal(w.before, 0);
  assert.equal(w.after, (1000 - 30) * 50);
  assert.equal(w.total, 50000);
});

test('the table starts below the screen top: the body is not on screen yet', () => {
  const w = rowWindow({ count: 1000, heights: even(1000), top: -300, viewport: 500, overscan: 5 });
  // 200px of body on screen: rows 0..3
  assert.deepEqual([w.start, w.end, w.first, w.last], [0, 9, 0, 3]);
  const off = rowWindow({ count: 1000, heights: even(1000), top: -900, viewport: 500, overscan: 5 });
  assert.deepEqual([off.start, off.first], [0, 0]);
});

test('in the middle: spacers above and below add up to the rest', () => {
  const w = rowWindow({ count: 1000, heights: even(1000), top: 25000, viewport: 500, overscan: 20 });
  assert.deepEqual([w.first, w.last, w.start, w.end], [500, 509, 480, 530]);
  assert.equal(w.before, 480 * 50);
  assert.equal(w.before + (w.end - w.start) * 50 + w.after, w.total);
});

test('scrolled past the end (a filter shrank the list): the end, never empty', () => {
  const w = rowWindow({ count: 30, heights: even(30), top: 99999, viewport: 500, overscan: 5 });
  assert.equal(w.first, 29);
  assert.equal(w.end, 30);
  assert.ok(w.end > w.start);
});

test('measured heights count, an open services row with its place; the rest are guessed at their average', () => {
  const heights = [];
  heights[0] = 50; heights[1] = 250;           // row 1's services are open
  assert.equal(guess(heights), 150);
  assert.equal(guess([]), GUESS);
  assert.equal(guess([0, -3, NaN, 'x', undefined]), GUESS);
  const w = rowWindow({ count: 5, heights, top: 260, viewport: 10, overscan: 0 });
  // 0..50, 50..300 (row 1), so 260 is in row 1
  assert.deepEqual([w.first, w.last], [1, 1]);
  assert.equal(w.before, 50);
  assert.equal(w.after, 3 * 150);
});

test('drawing again: only near a drawn edge that is not the table\'s own', () => {
  const n = 1000;
  const drawn = { start: 480, end: 530 };
  assert.equal(needsRedraw(drawn, { first: 500, last: 509 }, n), false);
  assert.equal(needsRedraw(drawn, { first: 480 + EDGE - 1, last: 495 }, n), true);
  assert.equal(needsRedraw(drawn, { first: 510, last: 530 - EDGE }, n), true);
  assert.equal(needsRedraw({ start: 0, end: 30 }, { first: 0, last: 9 }, n), false);
  assert.equal(needsRedraw({ start: 970, end: 1000 }, { first: 990, last: 999 }, n), false);
  assert.equal(needsRedraw(null, { first: 0, last: 0 }, n), true);
  assert.equal(needsRedraw({ start: 0, end: 40 }, { first: 0, last: 9 }, 20), true);   // the list shrank
});

test('a window that does not change needs no redraw (a scroll the redraw itself made)', () => {
  const heights = even(1000);
  const w = rowWindow({ count: 1000, heights, top: 25000, viewport: 500 });
  assert.equal(needsRedraw(w, rowWindow({ count: 1000, heights, top: 25000, viewport: 500 }), 1000), false);
});

console.log(`\n${passed} passed`);
