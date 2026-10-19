/* REGIONS' maths, in plain node.

   Run:  node tests/test_region_model.mjs        (from Web/)

   Every behaviour a person feels in the region view is a statement about
   numbers here: where a place lands on a detailed map, when zooming in opens
   a region, how the detailed map is framed and held on screen, and when a
   zoom-out means "leave". */

import assert from 'node:assert/strict';
import {
  autoCandidate, carryRect, chainOf, childrenOf, clampLens, clampRect, coverage, fitContain,
  fitRect, hashWithRegion, pinchStep, placeOn, rectFromView, rectOnScreen, rectToChild,
  rectToParent, regionFromHash, shown, toChild, toParent, viewRect, zoomAround,
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

/* ── "use the current view": the window → a rectangle ─────────────────── */

test('the plain fitted view of a map that fills the window is the whole map', () => {
  assert.deepEqual(rectFromView({ x: 0, y: 0, k: 1 }, 1000, 500, 1000, 500), { x: 0, y: 0, w: 100, h: 100 });
});

test('a panned view moves the rectangle and keeps its size', () => {
  // k=1 on a 2000×1000 map in a 1000×500 window, panned 500 px right and 250 down
  assert.deepEqual(rectFromView({ x: -500, y: -250, k: 1 }, 2000, 1000, 1000, 500), { x: 25, y: 25, w: 50, h: 50 });
});

test('a zoomed view is a smaller rectangle, rounded to one decimal', () => {
  // k=3 on a 1000×1000 map in a 1000×1000 window: a third of it, from 1/3 across
  const r = rectFromView({ x: -1000, y: -1000, k: 3 }, 1000, 1000, 1000, 1000);
  assert.deepEqual(r, { x: 33.3, y: 33.3, w: 33.4, h: 33.4 });
  assert.ok(r.x + r.w <= 100.0001);
});

test('a view past the edge is clamped to the map', () => {
  // the window starts 10% left of the map and runs off its bottom
  const r = rectFromView({ x: 100, y: -800, k: 1 }, 1000, 1000, 500, 500);
  assert.deepEqual(r, { x: 0, y: 80, w: 40, h: 20 });
});

test('a letterboxed map (smaller than the window) gives all of it', () => {
  const r = rectFromView({ x: 250, y: 100, k: 0.5 }, 1000, 1000, 1000, 700);
  assert.deepEqual(r, { x: 0, y: 0, w: 100, h: 100 });
});

test('a view that shows none of the map is no rectangle', () => {
  assert.equal(rectFromView({ x: 2000, y: 0, k: 1 }, 1000, 1000, 1000, 1000), null);
  assert.equal(clampRect({ x: 10, y: 10, w: 0.01, h: 5 }), null);
  assert.equal(clampRect({ x: NaN, y: 0, w: 1, h: 1 }), null);
});

test('a rectangle maps into a region and back', () => {
  const r = { x: 10, y: 20, w: 40, h: 50 };
  const c = rectToChild(r, { x: 20, y: 30, w: 20, h: 25 });
  near(c.x, 25); near(c.y, 20); near(c.w, 50); near(c.h, 50);
  const p = rectToParent(r, c);
  near(p.x, 20); near(p.y, 30); near(p.w, 20); near(p.h, 25);
});

test('carrying a view: main → a nested region, lens → its parent, and onto itself', () => {
  // main (16, 0, 6, 32) → west (20, 0, 20, 40) → north (0, 0, 33.3…, 100)
  const n = carryRect(REGIONS, null, 'north', { x: 16, y: 0, w: 6, h: 32 });
  near(n.x, 0); near(n.y, 0); near(n.w, 100 / 3); near(n.h, 100);
  // a lens view on north, put back on west's map
  const w = carryRect(REGIONS, 'north', 'west', { x: 0, y: 0, w: 50, h: 50 });
  near(w.x, 20); near(w.y, 0); near(w.w, 30); near(w.h, 20);
  assert.deepEqual(carryRect(REGIONS, 'west', 'west', { x: 1, y: 2, w: 3, h: 4 }), { x: 1, y: 2, w: 3, h: 4 });
  assert.equal(carryRect(REGIONS, null, 'nope', { x: 0, y: 0, w: 1, h: 1 }), null);
});

test('a carried view outside the target map clamps to nothing', () => {
  // the window shows only the main map's east, far from west
  assert.equal(clampRect(carryRect(REGIONS, null, 'west', { x: 60, y: 0, w: 30, h: 30 })), null);
});

/* ── deep links ────────────────────────────────────────────────────────── */

test('a hash names a region; junk names none', () => {
  assert.equal(regionFromHash('#region=server-room'), 'server-room');
  assert.equal(regionFromHash('region=rack-a'), 'rack-a');
  assert.equal(regionFromHash('#region=rack%20a'), 'rack a');
  for (const junk of ['', '#', '#region', '#region=', '#region=%E0%A4%A', '#regions=x', '#Region=x', null, undefined]) {
    assert.equal(regionFromHash(junk), null, String(junk));
  }
});

test('a region part among others is found, the first one wins', () => {
  assert.equal(regionFromHash('#view=2&region=rack-a&x=1'), 'rack-a');
  assert.equal(regionFromHash('#region=rack-a&region=server-room'), 'rack-a');
});

test('writing the hash encodes the id and keeps every other part in place', () => {
  assert.equal(hashWithRegion('', 'server-room'), 'region=server-room');
  assert.equal(hashWithRegion('#', 'rack a/b'), 'region=rack%20a%2Fb');
  assert.equal(regionFromHash('#' + hashWithRegion('', 'rack a/b&c')), 'rack a/b&c');
  assert.equal(hashWithRegion('#view=2&region=old&x=1', 'rack-a'), 'view=2&region=rack-a&x=1');
  assert.equal(hashWithRegion('#view=2', 'rack-a'), 'view=2&region=rack-a');
  assert.equal(hashWithRegion('#region=a&region=b', 'c'), 'region=c');
});

test('leaving clears the region part and only it', () => {
  assert.equal(hashWithRegion('#region=rack-a', null), '');
  assert.equal(hashWithRegion('#view=2&region=rack-a', null), 'view=2');
  assert.equal(hashWithRegion('', null), '');
});

/* ── pinch ─────────────────────────────────────────────────────────────── */

const P = (x, y) => ({ x, y });

test('two fingers moving together pan without zooming', () => {
  const { cam, factor, atFloor } = pinchStep({ k: 2, x: 0, y: 0 }, P(100, 100), P(200, 100), P(130, 90), P(230, 90), 0.5, 8);
  near(factor, 1); near(cam.k, 2); near(cam.x, 30); near(cam.y, -10);
  assert.equal(atFloor, false);
});

test('spreading the fingers zooms about their midpoint', () => {
  // midpoint (150, 100) stays put; distance 100 → 200 doubles the zoom
  const { cam } = pinchStep({ k: 1, x: 0, y: 0 }, P(100, 100), P(200, 100), P(50, 100), P(250, 100), 0.5, 8);
  near(cam.k, 2); near(cam.x, 150 - 150 * 2); near(cam.y, 100 - 100 * 2);
});

test('a pinch that also moves keeps the map point under the fingers', () => {
  const before = { k: 1.5, x: -40, y: 20 };
  const a0 = P(300, 300), b0 = P(400, 400), a1 = P(320, 260), b1 = P(520, 460);
  const { cam } = pinchStep(before, a0, b0, a1, b1, 0.1, 10);
  const m0 = P(350, 350), m1 = P(420, 360);
  near((m0.x - before.x) / before.k, (m1.x - cam.x) / cam.k);
  near((m0.y - before.y) / before.k, (m1.y - cam.y) / cam.k);
  near(cam.k, 3);
});

test('a pinch holds the zoom between the floor and the ceiling', () => {
  const up = pinchStep({ k: 4, x: 0, y: 0 }, P(0, 0), P(100, 0), P(0, 0), P(400, 0), 1, 6);
  near(up.cam.k, 6); assert.equal(up.atFloor, false);
});

test('pinching out at the floor reports it — the cue to leave, as the wheel does', () => {
  const r = pinchStep({ k: 1, x: 0, y: 0 }, P(0, 0), P(200, 0), P(50, 0), P(150, 0), 1, 6);
  assert.equal(r.atFloor, true); near(r.cam.k, 1);
  const above = pinchStep({ k: 3, x: 0, y: 0 }, P(0, 0), P(200, 0), P(50, 0), P(150, 0), 1, 6);
  assert.equal(above.atFloor, false); near(above.cam.k, 1.5);
});

test('fingers on the same spot do not divide by zero', () => {
  const r = pinchStep({ k: 2, x: 5, y: 5 }, P(10, 10), P(10, 10), P(20, 10), P(20, 10), 1, 6);
  near(r.factor, 1); near(r.cam.k, 2); near(r.cam.x, 15);
});

console.log(`\nregion-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
