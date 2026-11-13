/* TOPOLOGY's model, in plain node.

   path-model.js decides which tier a place stands on, where the diagram puts
   it, which edges join the places, and which charted service roads cross a
   hop. path.js only draws the answer.

   Run:  node tests/test_path_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  chainPairs, edgesOf, layout, servicesCrossing, tierOf,
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
