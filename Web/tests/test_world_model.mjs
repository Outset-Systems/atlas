/* The arithmetic behind the map's lines and rings. `node tests/test_world_model.mjs` */

import assert from 'node:assert/strict';
import { convexHull, paddedHull, ringPoints, reachTargets, serviceEntries } from '../static/js/world-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);

/* ── hulls ────────────────────────────────────────────────────────────── */

test('a hull keeps the corners and drops what lies inside or along an edge', () => {
  const pts = [[0, 0], [10, 0], [10, 10], [0, 10], [5, 5], [5, 0]];
  assert.deepEqual(convexHull(pts), [[0, 0], [10, 0], [10, 10], [0, 10]]);
});

test('fewer than three points come back as given, the same array', () => {
  const two = [[3, 4], [1, 2]];
  assert.equal(convexHull(two), two);
  assert.deepEqual(convexHull([]), []);
});

test('a hull does not reorder the points it was handed', () => {
  const pts = [[10, 10], [0, 0], [10, 0]];
  convexHull(pts);
  assert.deepEqual(pts, [[10, 10], [0, 0], [10, 0]]);
});

test('a padded hull pushes each corner away from the centre, in whole pixels', () => {
  const out = paddedHull([[0, 0], [100, 0], [100, 100], [0, 100]], 10);
  assert.equal(out.cx, 50);
  assert.equal(out.cy, 50);
  // each corner moves 10 along its diagonal: 7.07 on each axis, rounded
  assert.equal(out.points, '-7,-7 107,-7 107,107 -7,107');
});

test('the centre is the mean of the hull corners, not of every point, and is not rounded', () => {
  const out = paddedHull([[0, 0], [10, 0], [0, 10], [1, 1], [2, 2]], 0);
  near(out.cx, 10 / 3);
  near(out.cy, 10 / 3);
  assert.equal(out.points, '0,0 10,0 0,10');
});

test('a corner that sits on the centre is left where it is', () => {
  // three points on one spot: the hull is degenerate and nothing is pushed to NaN
  const out = paddedHull([[5, 5], [5, 5], [5, 5]], 10);
  assert.ok(!out.points.includes('NaN'));
});

/* ── the ring ─────────────────────────────────────────────────────────── */

const RING = { radius: 10, twoRing: 8, outer: 1.5, yScale: 1 };

test('the ring starts due north and runs clockwise', () => {
  const pts = ringPoints({ x: 50, y: 50 }, 4, RING);
  assert.equal(pts.length, 4);
  near(pts[0].x, 50); near(pts[0].y, 40);   // north (y grows downward)
  near(pts[1].x, 60); near(pts[1].y, 50);   // east
  near(pts[2].x, 50); near(pts[2].y, 60);   // south
  near(pts[3].x, 40); near(pts[3].y, 50);   // west
});

test('the ring grows by 4.5% for each dot past six', () => {
  near(ringPoints({ x: 0, y: 0 }, 6, RING)[0].y, -10);
  near(ringPoints({ x: 0, y: 0 }, 8, RING)[0].y, -10 * (1 + 2 * 0.045));
});

test('past the two-ring count every other dot stands further out', () => {
  const pts = ringPoints({ x: 0, y: 0 }, 10, RING);
  const r = 10 * (1 + 4 * 0.045);
  const dist = (p) => Math.hypot(p.x, p.y);
  near(dist(pts[0]), r);
  near(dist(pts[1]), r * 1.5);
  near(dist(pts[2]), r);
  // at the count itself there is still one ring
  const eight = ringPoints({ x: 0, y: 0 }, 8, RING);
  near(dist(eight[1]), dist(eight[0]));
});

test('yScale stretches the ring down the map only', () => {
  const pts = ringPoints({ x: 50, y: 50 }, 4, { ...RING, yScale: 2 });
  near(pts[0].y, 30);
  near(pts[1].x, 60);
});

test('no dots, no ring', () => {
  assert.deepEqual(ringPoints({ x: 1, y: 1 }, 0, RING), []);
});

/* ── reach ────────────────────────────────────────────────────────────── */

const ROUTES = [
  { from: 'gate', to: 'web' }, { from: 'db', to: 'web' }, { from: 'gate', to: 'db' },
  { from: 'web', to: 'hidden' },
];

test('a place reaches what it declares and what a road wires it to, either way', () => {
  const got = reachTargets({ id: 'web', reaches: ['nas'] }, ROUTES, () => false);
  assert.deepEqual([...got], ['nas', 'gate', 'db', 'hidden']);
});

test('a place that is not drawn is not reached', () => {
  const got = reachTargets({ id: 'web', reaches: ['nas'] }, ROUTES, (id) => id === 'hidden' || id === 'nas');
  assert.deepEqual([...got], ['gate', 'db']);
});

test('no reaches and no routes is an empty set', () => {
  assert.equal(reachTargets({ id: 'lone' }, undefined, () => false).size, 0);
});

/* ── a place's services ───────────────────────────────────────────────── */

const jelly = { label: 'Jellyfin', connects: ['gate', 'edge'] };
const wiki = { label: 'Wiki' };
const proxy = { label: 'Proxy' };
const NODES = [
  { id: 'media', links: [jelly, wiki] },
  { id: 'gate', links: [proxy] },
  { id: 'edge' },
  { id: 'other', links: [{ label: 'Loop', connects: ['other'] }] },
];

test('a place rings its own links first, then what passes through it', () => {
  const got = serviceEntries(NODES, 'gate');
  assert.equal(got.length, 2);
  assert.deepEqual(got[0], { host: NODES[1], link: proxy, passing: false });
  assert.deepEqual(got[1], { host: NODES[0], link: jelly, passing: true });
  assert.equal(got[1].link, jelly, 'the link itself, not a copy');
});

test('a transit place with no links of its own still has what crosses it', () => {
  const got = serviceEntries(NODES, 'edge');
  assert.deepEqual(got.map((e) => [e.host.id, e.link.label, e.passing]), [['media', 'Jellyfin', true]]);
});

test('a link that names its own place is not counted twice', () => {
  const got = serviceEntries(NODES, 'other');
  assert.deepEqual(got.map((e) => e.passing), [false]);
});

test('an unknown place has nothing to ring', () => {
  assert.deepEqual(serviceEntries(NODES, 'nowhere'), []);
});

console.log(`\n${passed} passed`);
