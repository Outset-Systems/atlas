/* TOPOLOGY's model, in plain node.

   path-model.js decides which tier a place stands on, where the diagram puts
   it, which edges join the places, and which charted service roads cross a
   hop. path.js only draws the answer.

   Run:  node tests/test_path_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  chainPairs, edgePath, edgesOf, layout, servicesCrossing, tierOf,
} from '../static/js/path-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

// the ids the tiers key on are the code's own; every other name here is invented
const NODES = [
  { id: 'the-wild', name: 'OUTSIDE' },
  { id: 'gateway', name: 'GATE' },
  { id: 'traefik', name: 'PROXY' },
  { id: 'host-a', name: 'HOST A' },
  { id: 'host-b', name: 'HOST B' },
  { id: 'switch-1', name: 'SWITCH', kind: 'network' },
  { id: 'vm-1', name: 'VM ONE', parent: 'host-a',
    links: [
      { label: 'Wiki', path: ['host-a', 'gateway', 'the-wild'] },
      { label: 'No road' },
      { label: 'Empty road', path: [] },
    ] },
  { id: 'vm-2', name: 'VM TWO', parent: 'host-a',
    links: [{ label: 'Media', path: ['gateway', 'traefik', null, 'the-wild'] }] },
];

test('tiers: the world, the ways in, the iron, the guests', () => {
  assert.equal(tierOf({ id: 'the-wild' }), 0);
  assert.equal(tierOf({ id: 'cloudflare' }), 0);
  for (const id of ['gateway', 'traefik', 'tailscale', 'pangolin']) assert.equal(tierOf({ id }), 1, id);
  assert.equal(tierOf({ id: 'vm-1', parent: 'host-a' }), 3);
  assert.equal(tierOf({ id: 'host-a' }), 2);
  // a way in stays a way in even when it has a parent
  assert.equal(tierOf({ id: 'traefik', parent: 'host-b' }), 1);
});

test('layout spreads each tier evenly across the width, at its own height', () => {
  const { tiers, pos } = layout(NODES);
  assert.deepEqual(tiers.map((t) => t.map((n) => n.id)),
    [['the-wild'], ['gateway', 'traefik'], ['host-a', 'host-b', 'switch-1'], ['vm-1', 'vm-2']]);
  assert.deepEqual(pos['the-wild'], { x: 50, y: 8 });
  assert.deepEqual(pos.gateway, { x: 100 / 3, y: 30 });
  assert.deepEqual(pos.traefik, { x: 200 / 3, y: 30 });
  assert.deepEqual(pos['host-a'], { x: 25, y: 55 });
  assert.deepEqual(pos['switch-1'], { x: 75, y: 55 });
  assert.deepEqual(pos['vm-2'], { x: 200 / 3, y: 82 });
  assert.deepEqual(layout([]), { tiers: [[], [], [], []], pos: {} });
});

test('narrow: the tiers that hold anything are columns, and a tier stacks down from the top', () => {
  const { tiers, pos, rows, cols } = layout(NODES, true);
  assert.deepEqual(tiers.map((t) => t.map((n) => n.id)), layout(NODES).tiers.map((t) => t.map((n) => n.id)));
  assert.equal(cols, 4);
  assert.equal(rows, 3, 'the busiest tier (the three on tier 2)');
  // one column a tier, left to right in tier order, each centred in its quarter
  assert.equal(pos['the-wild'].x, 12.5);
  assert.equal(pos.gateway.x, 37.5);
  assert.equal(pos['host-a'].x, 62.5);
  assert.equal(pos['vm-1'].x, 87.5);
  // every tier starts on the first row, and the rows are the same for all of them
  for (const id of ['the-wild', 'gateway', 'host-a', 'vm-1']) assert.equal(pos[id].y, 100 * 0.5 / 3);
  assert.equal(pos.traefik.y, 100 * 1.5 / 3);
  assert.equal(pos['switch-1'].y, 100 * 2.5 / 3);
  assert.equal(pos['vm-2'].y, pos.traefik.y);
  // a tier that holds nothing takes no column
  const few = layout([{ id: 'the-wild' }, { id: 'box-a' }, { id: 'box-b' }, { id: 'guest', parent: 'box-a' }], true);
  assert.equal(few.cols, 3);
  assert.equal(few.rows, 2);
  assert.deepEqual([few.pos['the-wild'].x, few.pos['box-a'].x, few.pos.guest.x].map((x) => +x.toFixed(4)), [16.6667, 50, 83.3333]);
  assert.deepEqual(layout([], true), { tiers: [[], [], [], []], pos: {}, rows: 1, cols: 1 });
  // no two places share a point, wide or narrow
  for (const narrow of [false, true]) {
    const points = Object.values(layout(NODES, narrow).pos).map((p) => `${p.x} ${p.y}`);
    assert.equal(new Set(points).size, points.length);
  }
});

test('the curve between two places: down the page when wide, across it when narrow', () => {
  const a = { x: 10, y: 8 }, b = { x: 30, y: 30 };
  assert.equal(edgePath(a, b), 'M 10 8 C 10 19, 30 19, 30 30');
  assert.equal(edgePath(a, b, false, 4), edgePath(a, b));
  assert.equal(edgePath({ x: 12.5, y: 10 }, { x: 37.5, y: 50 }, true, 4), 'M 12.5 10 C 25 10, 25 50, 37.5 50');
});

test('narrow: two places in one column are joined beside it, not through the names between', () => {
  // a later column bows toward the one before it
  const later = edgePath({ x: 62.5, y: 10 }, { x: 62.5, y: 70 }, true, 4);
  assert.equal(later, 'M 62.5 10 C 47 10, 47 70, 62.5 70');
  // the first column has nothing before it and bows the other way
  const first = edgePath({ x: 12.5, y: 10 }, { x: 12.5, y: 70 }, true, 4);
  assert.equal(first, 'M 12.5 10 C 28 10, 28 70, 12.5 70');
  // and never leaves the picture, however few columns there are
  for (const cols of [1, 2, 3, 4]) {
    for (let c = 0; c < cols; c++) {
      const x = (100 * (c + 0.5)) / cols;
      const bx = Number(edgePath({ x, y: 10 }, { x, y: 70 }, true, cols).split(' ')[4]);
      assert.ok(bx !== x, 'it bows');
      // a cubic with both handles at bx reaches three quarters of the way to it
      const peak = x + 0.75 * (bx - x);
      assert.ok(peak >= 0 && peak <= 100, `cols ${cols} col ${c}: peak ${peak}`);
    }
  }
});

test('edges: charted routes whose ends are both drawn, then each guest under its host', () => {
  const { pos } = layout(NODES);
  const routes = [
    { from: 'the-wild', to: 'gateway', kind: 'wan' },
    { from: 'gateway', to: 'host-a' },
    { from: 'gateway', to: 'not-drawn', kind: 'vlan' },
    { from: 'not-drawn', to: 'host-b', kind: 'vlan' },
  ];
  assert.deepEqual(edgesOf(routes, NODES, pos), [
    { a: 'the-wild', b: 'gateway', kind: 'wan' },
    { a: 'gateway', b: 'host-a', kind: 'road' },
    { a: 'host-a', b: 'vm-1', kind: 'vassal' },
    { a: 'host-a', b: 'vm-2', kind: 'vassal' },
  ]);
  assert.deepEqual(edgesOf(undefined, [], {}), []);
  // a guest whose host is not drawn gets no edge
  assert.deepEqual(edgesOf([], [{ id: 'orphan', parent: 'gone' }], { orphan: { x: 50, y: 82 } }), []);
});

test('a road crosses a hop only where it names both ends consecutively, either way round', () => {
  const crossing = (a, b) => servicesCrossing(NODES, a, b).map((c) => c.link.label);
  assert.deepEqual(crossing('host-a', 'gateway'), ['Wiki']);
  assert.deepEqual(crossing('gateway', 'host-a'), ['Wiki'], 'direction is not checked');
  assert.deepEqual(crossing('gateway', 'the-wild'), ['Wiki']);
  assert.deepEqual(crossing('vm-1', 'gateway'), [], 'on the road, but not adjacent on it');
  // the road begins at the service's own host
  assert.deepEqual(crossing('vm-1', 'host-a'), ['Wiki']);
  assert.deepEqual(crossing('vm-2', 'gateway'), ['Media']);
  // an empty stop is dropped before the pairs are read
  assert.deepEqual(crossing('traefik', 'the-wild'), ['Media']);
  assert.deepEqual(crossing('host-b', 'switch-1'), []);
});

test('a crossing carries the host, the link and the whole chain', () => {
  const [hit] = servicesCrossing(NODES, 'host-a', 'gateway');
  assert.equal(hit.host.id, 'vm-1');
  assert.equal(hit.link.label, 'Wiki');
  assert.deepEqual(hit.chain, ['vm-1', 'host-a', 'gateway', 'the-wild']);
  // a road that crosses the same hop twice is still one road
  const loop = [{ id: 'x', links: [{ label: 'Loop', path: ['y', 'x', 'y'] }] }];
  assert.equal(servicesCrossing(loop, 'x', 'y').length, 1);
  assert.deepEqual(servicesCrossing(undefined, 'a', 'b'), []);
});

test('chain pairs: every consecutive pair, both ways, with the asked separator', () => {
  assert.deepEqual([...chainPairs(['a', 'b', 'c'])], ['a b', 'b a', 'b c', 'c b']);
  assert.deepEqual([...chainPairs(['a', 'b'], '\0')], ['a\0b', 'b\0a']);
  assert.equal(chainPairs(['a']).size, 0);
  assert.equal(chainPairs([]).size, 0);
  assert.ok(!chainPairs(['a', 'b', 'c']).has('a c'), 'not adjacent');
});

console.log(`\n${passed} passed`);
