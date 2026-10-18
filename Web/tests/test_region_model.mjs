/* REGIONS' maths, in plain node.

   Run:  node tests/test_region_model.mjs        (from Web/)

   Every behaviour a person feels in the region view is a statement about
   numbers here: where a place lands on a detailed map, when zooming in opens
   a region, how the detailed map is framed and held on screen, and when a
   zoom-out means "leave". */

import assert from 'node:assert/strict';
import {
  autoCandidate, chainOf, childrenOf, clampLens, coverage, fitContain, fitRect,
  placeOn, rectOnScreen, shown, toChild, toParent, viewRect, zoomAround,
} from '../static/js/region-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);

const REGIONS = [
  { id: 'west', name: 'West', map: 'w.webp', x: 10, y: 0, w: 30, h: 80 },
  { id: 'north', name: 'North', map: 'n.webp', parent: 'west', x: 20, y: 0, w: 60, h: 40 },
  { id: 'port', name: 'Port', map: 'p.webp', parent: 'west', x: 50, y: 60, w: 10, h: 10,
    places: { ship: { x: 30, y: 70 } } },
  { id: 'east', name: 'East', map: 'e.webp', x: 50, y: 20, w: 40, h: 60, auto: false },
];

/* ── the tree ─────────────────────────────────────────────────────────── */

test('children of the main map and of a region', () => {
  assert.deepEqual(childrenOf(REGIONS, null).map((r) => r.id), ['west', 'east']);
  assert.deepEqual(childrenOf(REGIONS, 'west').map((r) => r.id), ['north', 'port']);
  assert.deepEqual(childrenOf(REGIONS, 'north'), []);
});

test('the chain runs outermost first, and a broken or looping chain is empty', () => {
  assert.deepEqual(chainOf(REGIONS, 'north').map((r) => r.id), ['west', 'north']);
  assert.deepEqual(chainOf(REGIONS, 'nope'), []);
  const loop = [{ id: 'a', parent: 'b' }, { id: 'b', parent: 'a' }];
  assert.deepEqual(chainOf(loop, 'a'), []);
  assert.deepEqual(chainOf([{ id: 'a', parent: 'gone' }], 'a'), []);
});

/* ── where places land ────────────────────────────────────────────────── */

test('a point maps into a region and back', () => {
  const r = REGIONS[0];
  const q = toChild(r, { x: 25, y: 40 });
  near(q.x, 50); near(q.y, 50);
  const p = toParent(r, q);
  near(p.x, 25); near(p.y, 40);
});

test('a place inside the rectangle is carried through it', () => {
  const p = placeOn(REGIONS, 'west', { id: 'a', x: 25, y: 40 });
  near(p.x, 50); near(p.y, 50);
});

test('a place outside the rectangle is not drawn there', () => {
  assert.equal(placeOn(REGIONS, 'west', { id: 'b', x: 60, y: 40 }), null);
});

test('a nested region carries a place through both rectangles', () => {
  // main (25, 8) → west (50, 10) → north ((50-20)/60, 10/40) = (50, 25)
  const p = placeOn(REGIONS, 'north', { id: 'c', x: 25, y: 8 });
  near(p.x, 50); near(p.y, 25);
});

test('a pin wins over the mapped position, even for a place outside', () => {
  const p = placeOn(REGIONS, 'port', { id: 'ship', x: 99, y: 99 });
  assert.deepEqual(p, { x: 30, y: 70 });
});

test('a place with no position, or an unknown region, is not drawn', () => {
  assert.equal(placeOn(REGIONS, 'west', { id: 'd' }), null);
  assert.equal(placeOn(REGIONS, 'nope', { id: 'a', x: 25, y: 40 }), null);
});

/* ── when zooming opens a region ──────────────────────────────────────── */

test('the window as a rectangle of the map', () => {
  // a 1000×500 map at k=2, shifted so the window starts 25% across
  const v = viewRect({ x: -500, y: 0, k: 2 }, 1000, 500, 1000, 500);
  near(v.x, 25); near(v.y, 0); near(v.w, 50); near(v.h, 50);
});

test('coverage = how much of the window the rectangle is; shown = how much of it you see', () => {
  const r = { x: 0, y: 0, w: 50, h: 50 };
  near(coverage({ x: 0, y: 0, w: 100, h: 100 }, r), 0.25);
  near(coverage({ x: 10, y: 10, w: 20, h: 20 }, r), 1);
  near(shown({ x: 10, y: 10, w: 20, h: 20 }, r), 0.16);
});

test('zooming in until the region is most of the window picks it', () => {
  const pick = autoCandidate(REGIONS, null, { x: 12, y: 5, w: 26, h: 60 });
  assert.equal(pick?.id, 'west');
});

test('a region that is only part of the window does not open', () => {
  assert.equal(autoCandidate(REGIONS, null, { x: 0, y: 0, w: 100, h: 100 }), null);
});

test('auto: false never opens by zooming', () => {
  assert.equal(autoCandidate(REGIONS, null, { x: 55, y: 30, w: 20, h: 20 }), null);
});

test('a disarmed region is skipped (the cooldown after leaving it)', () => {
  const view = { x: 12, y: 5, w: 26, h: 60 };
  assert.equal(autoCandidate(REGIONS, null, view, (id) => id !== 'west'), null);
});

test('only the regions drawn on the current map are candidates', () => {
  // inside west: the window is mostly `port`
  assert.equal(autoCandidate(REGIONS, 'west', { x: 51, y: 61, w: 8, h: 8 })?.id, 'port');
  assert.equal(autoCandidate(REGIONS, null, { x: 51, y: 61, w: 8, h: 8 }), null);
});

/* ── framing and holding the detailed map ─────────────────────────────── */

test('a portrait map fits a landscape window by its height, centred', () => {
  const c = fitContain(1000, 2000, 1600, 900, 0);
  near(c.k, 0.45); near(c.y, 0); near(c.x, (1600 - 450) / 2);
});

test('fitRect frames a rectangle centred in the window', () => {
  const c = fitRect({ x: 25, y: 25, w: 50, h: 50 }, 1000, 1000, 1000, 1000, 0);
  near(c.k, 2); near(c.x, 1000 / 2 - 500 * 2); near(c.y, 1000 / 2 - 500 * 2);
});

test('a map smaller than the window stays centred; a bigger one keeps its edges', () => {
  const small = clampLens({ k: 0.5, x: -999, y: 999 }, 1000, 1000, 1000, 1000);
  near(small.x, 250); near(small.y, 250);
  const big = clampLens({ k: 2, x: 400, y: -5000 }, 1000, 1000, 1000, 1000);
  near(big.x, 0); near(big.y, -1000);
});

test('zooming holds the point under the cursor still', () => {
  const { cam } = zoomAround({ k: 1, x: 0, y: 0 }, 100, 50, 2, 0.1, 10);
  near(cam.k, 2); near(cam.x, -100); near(cam.y, -50);
});

test('zooming out at the floor reports it — the cue to leave the region', () => {
  const r1 = zoomAround({ k: 0.5, x: 0, y: 0 }, 0, 0, 0.8, 0.5, 4);
  assert.equal(r1.atFloor, true); near(r1.cam.k, 0.5);
  const r2 = zoomAround({ k: 1, x: 0, y: 0 }, 0, 0, 0.8, 0.5, 4);
  assert.equal(r2.atFloor, false);
  const r3 = zoomAround({ k: 0.5, x: 0, y: 0 }, 0, 0, 1.25, 0.5, 4);
  assert.equal(r3.atFloor, false);
});

test('a rectangle on screen, for the transition out of its frame', () => {
  const box = rectOnScreen({ x: 10, y: 20, w: 30, h: 40 }, { x: 5, y: 7, k: 2 }, 1000, 500);
  assert.deepEqual(box, { left: 205, top: 207, width: 600, height: 400 });
});

console.log(`\nregion-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
