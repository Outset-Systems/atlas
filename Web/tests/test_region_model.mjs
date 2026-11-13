/* REGIONS' maths, in plain node.

   Run:  node tests/test_region_model.mjs        (from Web/)

   Every behaviour a person feels in the region view is a statement about
   numbers here: where a place lands on a detailed map, when zooming in opens
   a region, how the detailed map is framed and held on screen, and when a
   zoom-out means "leave". */

import assert from 'node:assert/strict';
import { foldedAt, homesAt, foldSummary, foldWords, carryTo, exitPoint, exitLabel, mergeExits,
  standingOn, drawnAbove, exitsFor,
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

test('a tall narrow region opens at the zoom ceiling, and a click on a place inside it does not open it', () => {
  // REGIONS.west is 30 wide. A window 47.6 wide and shorter than the region sees it as 63% of itself:
  // what the ceiling gives a quarter-wide island on a 1280 window
  assert.equal(autoCandidate(REGIONS, null, { x: 1.2, y: 10, w: 47.6, h: 40 })?.id, 'west');
  // at the scale a clicked place is shown at, the same region is about half the window: not yet
  assert.equal(autoCandidate(REGIONS, null, { x: -4, y: 10, w: 58, h: 40 }), null);
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

test('a folded region keeps the places that speak to nobody outside it', () => {
  const regions = [
    { id: 'island', x: 10, y: 10, w: 30, h: 60, fold: true },
    { id: 'north', parent: 'island', x: 20, y: 0, w: 60, h: 40 },
    { id: 'plain', x: 60, y: 10, w: 20, h: 20 },
  ];
  const at = {
    gate: { x: 20, y: 20 }, core: { x: 22, y: 25 }, nas: { x: 15, y: 30 }, vault: { x: 30, y: 15 },
    far: { x: 90, y: 50 }, hut: { x: 65, y: 15 }, shed: { x: 70, y: 20 },
  };
  const routes = [
    { from: 'gate', to: 'core' }, { from: 'core', to: 'nas' },      // inside the island
    { from: 'gate', to: 'far' },                                     // the island speaks to the world
    { from: 'nas', to: 'vault' },                                    // both inside: neither speaks out
    { from: 'hut', to: 'shed' }, { from: 'ghost', to: 'far' },      // an unfolded region; a place not drawn
  ];
  assert.deepEqual([...foldedAt(regions, null, at, routes)].sort(), ['core', 'nas', 'vault']);
  assert.deepEqual(homesAt(regions, null, at),
    { gate: 'island', core: 'island', nas: 'island', vault: 'island', hut: 'plain', shed: 'plain' });
  // a road into ANOTHER region counts as speaking out, from both ends
  assert.deepEqual([...foldedAt(regions, null, at, [{ from: 'nas', to: 'hut' }])].sort(), ['core', 'gate', 'vault']);
  // no fold, no hiding; and the island's own map asks only its own children
  assert.equal(foldedAt(regions.map((r) => ({ ...r, fold: false })), null, at, routes).size, 0);
  assert.equal(foldedAt(regions, 'island', at, routes).size, 0);
  assert.equal(foldedAt(regions, null, at, undefined).size, 4);
});

/* ── a folded region's tab: how many wait inside, and the worst of them ──── */

const FOLD_REGIONS = [
  { id: 'island', name: 'Island', map: 'i.webp', x: 0, y: 0, w: 50, h: 100, fold: true },
  { id: 'plain', name: 'Plain', map: 'p.webp', x: 60, y: 0, w: 40, h: 100 },
  { id: 'reef', name: 'Reef', map: 'r.webp', x: 52, y: 0, w: 6, h: 100, fold: true },
];
const FOLD_AT = {
  gate: { x: 40, y: 50 }, core: { x: 10, y: 10 }, nas: { x: 20, y: 20 }, vault: { x: 30, y: 30 },
  hut: { x: 70, y: 50 }, shed: { x: 80, y: 60 },
};
const FOLD_ROUTES = [{ from: 'gate', to: 'hut' }, { from: 'core', to: 'nas' }];

test('foldSummary counts only what the fold hid, per folded region', () => {
  const hidden = foldedAt(FOLD_REGIONS, null, FOLD_AT, FOLD_ROUTES);
  const sum = foldSummary(FOLD_REGIONS, null, FOLD_AT, hidden, {});
  assert.deepEqual(Object.keys(sum).sort(), ['island', 'reef']);   // the unfolded one is not listed
  assert.equal(sum.island.count, 3);                               // gate is drawn here: not counted
  assert.equal(sum.island.unknown, 3);
  assert.equal(sum.island.worst, null);
  assert.equal(sum.reef.count, 0);
  assert.equal(foldWords(sum.island), '3 places');
  assert.equal(foldWords(sum.reef), '');
  assert.equal(foldWords(undefined), '');
});

test('foldSummary: the worst live state wins, and unknown is never an alarm', () => {
  const hidden = new Set(['core', 'nas', 'vault']);
  const s = (states) => foldSummary(FOLD_REGIONS, null, FOLD_AT, hidden, states).island;
  assert.equal(s({ core: 'healthy', nas: 'healthy', vault: 'healthy' }).worst, null);
  assert.equal(s({ core: 'healthy' }).unknown, 2);                 // no word is unknown, not healthy
  assert.equal(s({ core: 'healthy' }).healthy, 1);
  assert.equal(s({ core: 'maintenance', nas: 'slumbering' }).worst, 'maintenance');
  assert.equal(s({ core: 'maintenance', nas: 'degraded' }).worst, 'degraded');
  assert.equal(s({ core: 'maintenance', nas: 'degraded', vault: 'down' }).worst, 'down');
  assert.equal(s({ core: 'slumbering' }).worst, null);             // asleep on purpose: words, no cue
  assert.equal(s({ core: 'on fire' }).unknown, 3);                 // a word nobody taught it
  assert.equal(s(undefined).unknown, 3);
  // a state for a place that is drawn (gate) or hidden nowhere changes nothing
  assert.equal(s({ gate: 'down', hut: 'down' }).worst, null);
  assert.equal(foldWords(s({ core: 'down', nas: 'degraded', vault: 'degraded' })), '3 places, 1 down, 2 degraded');
  assert.equal(foldWords(s({ core: 'maintenance', nas: 'slumbering' })), '3 places, 1 in maintenance, 1 slumbering');
  const one = foldSummary(FOLD_REGIONS, null, FOLD_AT, new Set(['core']), { core: 'down' }).island;
  assert.equal(foldWords(one), '1 place, 1 down');
});

test('foldSummary on a region map asks that map, and never hands back a name', () => {
  const regions = [
    { id: 'isle', name: 'Isle', map: 'i.webp', x: 0, y: 0, w: 100, h: 100 },
    { id: 'cove', name: 'Cove', map: 'c.webp', parent: 'isle', x: 0, y: 0, w: 50, h: 50, fold: true },
  ];
  const at = { a: { x: 10, y: 10 }, b: { x: 20, y: 20 }, c: { x: 80, y: 80 } };
  const hidden = foldedAt(regions, 'isle', at, [{ from: 'a', to: 'c' }]);
  const sum = foldSummary(regions, 'isle', at, hidden, { b: 'down' });
  assert.deepEqual(sum, { cove: { count: 1, down: 1, degraded: 0, maintenance: 0, slumbering: 0, healthy: 0, unknown: 0, worst: 'down' } });
  assert.deepEqual(foldSummary(regions, null, at, hidden, { b: 'down' }), {});   // the main map has no folded child
});

/* ── exits: roads that leave the level ───────────────────────────────────── */

test('carryTo is placeOn without the edges', () => {
  // wherever placeOn answers, the two agree (pins and nesting included)
  for (const [rid, node] of [
    ['west', { id: 'a', x: 25, y: 40 }], ['north', { id: 'a', x: 25, y: 16 }],
    ['port', { id: 'ship', x: 90, y: 90 }], ['port', { id: 'a', x: 25.9, y: 49.6 }],
  ]) {
    const on = placeOn(REGIONS, rid, node);
    assert.ok(on, `${rid} holds ${node.id}`);
    const c = carryTo(REGIONS, rid, node);
    near(c.x, on.x); near(c.y, on.y);
  }
  // beyond the rectangle placeOn says null and carryTo says which way
  assert.equal(placeOn(REGIONS, 'west', { id: 'b', x: 70, y: 40 }), null);
  const out = carryTo(REGIONS, 'west', { id: 'b', x: 70, y: 40 });
  near(out.x, 200); near(out.y, 50);
  // through two rectangles: west (10,0,30,80) then north (20,0,60,40)
  const deep = carryTo(REGIONS, 'north', { id: 'b', x: 70, y: 40 });
  near(deep.x, 300); near(deep.y, 125);
  // a pin on the parent is where the place IS on the parent, in or out of the child
  const pinned = [...REGIONS.slice(0, 1).map((r) => ({ ...r, places: { b: { x: 90, y: 90 } } })), ...REGIONS.slice(1)];
  const viaPin = carryTo(pinned, 'north', { id: 'b', x: 70, y: 40 });
  near(viaPin.x, (90 - 20) / 60 * 100); near(viaPin.y, 225);
  assert.equal(carryTo(REGIONS, 'nowhere', { id: 'b', x: 1, y: 1 }), null);
  assert.equal(carryTo(REGIONS, 'west', { id: 'b' }), null);
});

test('exitPoint: where the line to a far place crosses the border', () => {
  const p = (from, far) => exitPoint(from, far);
  assert.deepEqual(p({ x: 50, y: 50 }, { x: 150, y: 50 }), { x: 100, y: 50 });    // east
  assert.deepEqual(p({ x: 50, y: 50 }, { x: -50, y: 50 }), { x: 0, y: 50 });      // west
  assert.deepEqual(p({ x: 50, y: 50 }, { x: 50, y: -10 }), { x: 50, y: 0 });      // north
  assert.deepEqual(p({ x: 50, y: 50 }, { x: 50, y: 400 }), { x: 50, y: 100 });    // south
  assert.deepEqual(p({ x: 50, y: 50 }, { x: 150, y: 150 }), { x: 100, y: 100 });  // the corner
  const slant = p({ x: 60, y: 20 }, { x: 140, y: 60 });                           // leaves by the east side
  near(slant.x, 100); near(slant.y, 40);
  const steep = p({ x: 60, y: 80 }, { x: 80, y: 180 });                           // leaves by the south side
  near(steep.x, 64); near(steep.y, 100);
  // a far point on the map is not an exit; nor is nonsense
  assert.equal(p({ x: 50, y: 50 }, { x: 70, y: 70 }), null);
  assert.equal(p({ x: 50, y: 50 }, { x: 100, y: 100 }), null);
  assert.equal(p({ x: 50, y: 50 }, { x: NaN, y: 0 }), null);
  assert.equal(p(null, { x: 150, y: 50 }), null);
  // a place standing on the border, heading out: the exit is where it stands
  assert.deepEqual(p({ x: 100, y: 30 }, { x: 150, y: 90 }), { x: 100, y: 30 });
  // every answer is on the border
  for (const far of [{ x: 117.2, y: 44.3 }, { x: -3, y: 101 }, { x: 250, y: -80 }, { x: 40, y: 100.5 }]) {
    const at = p({ x: 66, y: 22 }, far);
    assert.ok(at.x >= 0 && at.x <= 100 && at.y >= 0 && at.y <= 100);
    assert.ok([0, 100].some((e) => Math.abs(at.x - e) < 1e-9 || Math.abs(at.y - e) < 1e-9), JSON.stringify(at));
  }
});

test('the demo island: the gateway road to the edge host leaves by the east side', () => {
  // the rectangles and spots of hosted/demo-maps/Seven-Squabbling-Kingdoms.style.json
  const regions = [
    { id: 'big-island', name: 'The Big Island', map: 'i.webp', x: 11.5, y: 3.5, w: 25, h: 77, fold: true,
      places: { gateway: { x: 66, y: 22 } } },
    { id: 'cold-bit', name: 'The Cold Bit', map: 'n.webp', parent: 'big-island', x: 20, y: 2, w: 62, h: 37,
      places: { gateway: { x: 68, y: 42 } } },
  ];
  const edge = { id: 'edge', x: 40.8, y: 37.6 };
  assert.equal(placeOn(regions, 'big-island', edge), null);          // not on the island
  const far = carryTo(regions, 'big-island', edge);
  near(far.x, 117.2); near(far.y, (37.6 - 3.5) / 77 * 100);
  const at = exitPoint(carryTo(regions, 'big-island', { id: 'gateway', x: 29, y: 27 }), far);
  near(at.x, 100);
  near(at.y, 22 + (far.y - 22) * (34 / 51.2));
  // one level further in, the same host still lies east and a little south
  const deep = exitPoint({ x: 68, y: 42 }, carryTo(regions, 'cold-bit', edge));
  near(deep.x, 100);
  assert.ok(deep.y > 42 && deep.y < 100);
});

test('mergeExits: one line where several leave a place by the same spot', () => {
  const exits = [
    { from: 'gw', to: 'edge', name: 'EDGE', at: { x: 100, y: 40 }, kind: 'wan' },
    { from: 'gw', to: 'media', name: 'MEDIA', at: { x: 100, y: 42 }, kind: 'lan' },
    { from: 'gw', to: 'app', name: 'APP', at: { x: 100, y: 43.5 }, kind: 'lan' },
    { from: 'gw', to: 'wild', name: 'THE WILD', at: { x: 100, y: 41 }, kind: 'wan' },
    { from: 'gw', to: 'edge', name: 'EDGE', at: { x: 100, y: 40 }, kind: 'mesh' },   // a second road to the same place
    { from: 'gw', to: 'cam', name: 'CAMERAS', at: { x: 100, y: 80 }, kind: 'lan' },   // same side, far along it
    { from: 'nas', to: 'edge', name: 'EDGE', at: { x: 100, y: 40 }, kind: 'lan' },    // another place: its own line
    { from: 'gw', to: 'nope', name: 'NOPE' },                                         // no point, no line
  ];
  const got = mergeExits(exits);
  assert.equal(got.length, 3);
  const [a, b, c] = got;
  assert.deepEqual(a.ids, ['edge', 'media', 'app', 'wild']);
  assert.equal(a.label, 'EDGE, MEDIA +2');
  assert.equal(a.to, 'edge');                       // a click goes to the first
  assert.equal(a.kind, 'wan');                      // and the line is the first road's
  assert.deepEqual(a.at, { x: 100, y: 40 });
  assert.equal(b.label, 'CAMERAS');
  assert.equal(c.from, 'nas'); assert.equal(c.label, 'EDGE');
  // tolerance is a distance, and can be set
  assert.equal(mergeExits(exits.slice(0, 2), 1).length, 2);
  assert.equal(mergeExits([]).length, 0);
  assert.equal(mergeExits(undefined).length, 0);
  assert.equal(exitLabel(['A']), 'A');
  assert.equal(exitLabel(['A', 'B']), 'A, B');
  assert.equal(exitLabel(['A', 'B', 'C']), 'A, B +1');
  assert.equal(exitLabel([]), '');
});

/* ── what stands on a region, what is drawn above it, and the roads out ──── */

/* An island on the main map with a cold corner inside it. The gateway is
   pinned on both; the keep is carried through the rectangles; the edge host and
   the wild lie out on the main map; the cellar is charted and never drawn. */
const ISLAND = [
  { id: 'isle', name: 'Isle', map: 'i.webp', x: 10, y: 10, w: 40, h: 40,
    places: { gateway: { x: 66, y: 22 } } },
  { id: 'cold', name: 'Cold', map: 'c.webp', parent: 'isle', x: 50, y: 0, w: 50, h: 50,
    places: { gateway: { x: 68, y: 42 } } },
];
const SPOTS = {
  gateway: { x: 30, y: 20 }, keep: { x: 42, y: 14 }, mill: { x: 14, y: 46 },
  edge: { x: 70, y: 30 }, wild: { x: 90, y: 90 },
};
const NAMES = { gateway: 'GATEWAY', keep: 'KEEP', mill: 'MILL', edge: 'EDGE', wild: 'THE WILD', cellar: 'CELLAR' };

test('standingOn: every drawn place inside the rectangle, pins first', () => {
  const isle = standingOn(ISLAND, 'isle', SPOTS);
  assert.deepEqual(Object.keys(isle), ['gateway', 'keep', 'mill']);
  assert.deepEqual(isle.gateway, { x: 66, y: 22 });                 // the pin
  near(isle.keep.x, 80); near(isle.keep.y, 10);                     // carried through
  near(isle.mill.x, 10); near(isle.mill.y, 90);
  const cold = standingOn(ISLAND, 'cold', SPOTS);
  assert.deepEqual(Object.keys(cold), ['gateway', 'keep']);         // the mill is not in that corner
  assert.deepEqual(cold.gateway, { x: 68, y: 42 });
  near(cold.keep.x, 60); near(cold.keep.y, 20);
  assert.deepEqual(standingOn(ISLAND, 'nowhere', SPOTS), {});
  assert.deepEqual(standingOn(ISLAND, 'isle', undefined), {});
});

test('drawnAbove: the main map and every region on the way down, less the folded', () => {
  const routes = [{ from: 'gateway', to: 'edge' }];
  // one level in: only the main map is above
  assert.deepEqual([...drawnAbove(ISLAND, 'isle', SPOTS, routes)].sort(), ['edge', 'gateway', 'keep', 'mill', 'wild']);
  // two levels in: the island's own map is above too, and adds nothing new
  assert.deepEqual([...drawnAbove(ISLAND, 'cold', SPOTS, routes)].sort(), ['edge', 'gateway', 'keep', 'mill', 'wild']);
  // a folded island keeps what has no road off it: those are not drawn on the main map
  const folded = [{ ...ISLAND[0], fold: true }, ISLAND[1]];
  assert.deepEqual([...drawnAbove(folded, 'isle', SPOTS, routes)].sort(), ['edge', 'gateway', 'wild']);
  // from the cold corner the island's own map is above, and draws them again
  assert.deepEqual([...drawnAbove(folded, 'cold', SPOTS, routes)].sort(), ['edge', 'gateway', 'keep', 'mill', 'wild']);
});

test('exitsFor: a road to a place out on a map above runs to the border and is named', () => {
  const here = standingOn(ISLAND, 'isle', SPOTS);
  const road = { from: 'gateway', to: 'edge', kind: 'wan' };
  const routes = [
    road,
    { from: 'keep', to: 'gateway', kind: 'lan' },        // both drawn here: no exit
    { from: 'edge', to: 'wild', kind: 'wan' },           // neither drawn here: no exit
    { from: 'cellar', to: 'keep', kind: 'lan' },         // the far place is kept off the map
    { from: 'keep', to: 'ghost', kind: 'lan' },          // the far place is not in the dataset
    { from: 'keep', to: 'toString', kind: 'lan' },       // nor is a name every object answers to
  ];
  const got = exitsFor(ISLAND, 'isle', here, SPOTS, NAMES, routes);
  assert.equal(got.length, 1);
  const [ex] = got;
  assert.equal(ex.from, 'gateway'); assert.equal(ex.to, 'edge');
  assert.equal(ex.name, 'EDGE'); assert.equal(ex.label, 'EDGE');
  assert.deepEqual(ex.ids, ['edge']); assert.deepEqual(ex.names, ['EDGE']);
  assert.equal(ex.kind, 'wan'); assert.equal(ex.road, road);
  // The edge host carries to (150, 50) on the island's map; from the pin at (66, 22) that leaves east
  near(ex.at.x, 100); near(ex.at.y, 22 + 28 * (34 / 84));
});

test('exitsFor: the near end may be either end of the road, and two roads out by one spot merge', () => {
  const here = standingOn(ISLAND, 'isle', SPOTS);
  const spots = { ...SPOTS, post: { x: 70, y: 31 } };
  const routes = [
    { from: 'edge', to: 'gateway', kind: 'wan' },        // written the other way round
    { from: 'gateway', to: 'post', kind: 'lan' },
  ];
  const got = exitsFor(ISLAND, 'isle', here, spots, { ...NAMES, post: 'POST' }, routes);
  assert.equal(got.length, 1);
  assert.equal(got[0].from, 'gateway'); assert.equal(got[0].to, 'edge');
  assert.deepEqual(got[0].ids, ['edge', 'post']);
  assert.equal(got[0].label, 'EDGE, POST');
  assert.equal(got[0].kind, 'wan');
});

test('exitsFor: a far place folded away on a map above gets no line', () => {
  // two islands on the main map. The envoy stands on the eastern one beside the
  // barn, and is pinned onto the first island's own map.
  const east = { id: 'east', name: 'East', map: 'e.webp', x: 60, y: 60, w: 30, h: 30 };
  const isle = { ...ISLAND[0], places: { envoy: { x: 50, y: 50 } } };
  const spots = { keep: { x: 42, y: 14 }, envoy: { x: 75, y: 75 }, barn: { x: 80, y: 80 } };
  const names = { keep: 'KEEP', envoy: 'ENVOY', barn: 'BARN' };
  const routes = [{ from: 'envoy', to: 'barn', kind: 'lan' }];
  const here = standingOn([isle, east], 'isle', spots);
  assert.deepEqual(Object.keys(here), ['keep', 'envoy']);
  // unfolded, the main map draws the barn: the envoy's road to it leaves the island
  assert.deepEqual(exitsFor([isle, east], 'isle', here, spots, names, routes).map((e) => e.to), ['barn']);
  // folded, the barn's only road stays inside its own island, so no map above draws it
  const folded = [isle, { ...east, fold: true }];
  assert.deepEqual(exitsFor(folded, 'isle', here, spots, names, routes), []);
  // a second road, off the eastern island, brings the barn back out and the line with it
  const out = exitsFor(folded, 'isle', here, spots, names, [...routes, { from: 'barn', to: 'keep', kind: 'lan' }]);
  assert.deepEqual(out.map((e) => [e.from, e.to]), [['envoy', 'barn'], ['keep', 'barn']]);
  assert.deepEqual(exitsFor(folded, 'isle', here, spots, names, undefined), []);
});

console.log(`\nregion-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
