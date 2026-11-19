/* TOPOLOGY's model, in plain node.

   path-model.js decides which tier a place stands on, where the diagram puts
   it, which edges join the places, and which charted service roads cross a
   hop. path.js only draws the answer.

   Run:  node tests/test_path_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  chainPairs, columnWidths, edgePath, edgesOf, layout, servicesCrossing, tierOf,
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

test('columns share the width equally until one needs more', () => {
  const near = (got, want) => assert.deepEqual(got.map((v) => +v.toFixed(6)), want.map((v) => +v.toFixed(6)));
  assert.deepEqual(columnWidths([]), []);
  // nothing asked, or nothing over an equal share: equal, and exactly so
  assert.deepEqual(columnWidths([0, 0, 0, 0]), [25, 25, 25, 25]);
  assert.deepEqual(columnWidths([20, 25, 10, 0]), [25, 25, 25, 25]);
  assert.deepEqual(columnWidths([10, 20, 30]), [100 / 3, 100 / 3, 100 / 3]);
  // one column needs more than a quarter: it takes that, the rest share what is left
  near(columnWidths([20, 19, 28, 24]), [24, 24, 28, 24]);
  // a smaller share can fall under another column's need, so it is asked again
  near(columnWidths([20, 19, 31, 24]), [22.5, 22.5, 31, 24]);
  // every column gets at least what it asked for while the needs fit
  for (const needs of [[20, 19, 28, 25], [5, 40, 40, 5], [33, 33, 33], [0, 99], [26, 26, 26, 21.9]]) {
    const got = columnWidths(needs);
    assert.ok(Math.abs(got.reduce((a, b) => a + b, 0) - 100) < 1e-9, `${needs}: the widths fill the picture`);
    got.forEach((w, i) => assert.ok(w >= needs[i] - 1e-9, `${needs}: column ${i} got ${w}`));
  }
  // when they cannot all fit, the neediest are cut to one width between them, the
  // rest keep all they asked for, and the picture keeps its width
  near(columnWidths([30, 30, 60]), [30, 30, 40]);
  near(columnWidths([50, 50]), [50, 50]);
  near(columnWidths([60, 60]), [50, 50]);
  near(columnWidths([70, 10, 70]), [45, 10, 45]);
  near(columnWidths([22, 20, 31, 28]), [22, 20, 30, 28]);
  near(columnWidths([40, 40, 40, 40]), [25, 25, 25, 25]);
  for (const needs of [[30, 30, 60], [70, 10, 70], [22, 20, 31, 28], [90, 90, 90]]) {
    const got = columnWidths(needs);
    assert.ok(Math.abs(got.reduce((a, b) => a + b, 0) - 100) < 1e-9, `${needs}: the cut widths fill the picture`);
    got.forEach((w, i) => assert.ok(w <= needs[i] + 1e-9, `${needs}: column ${i} got more than it asked`));
  }
  // rubbish asks for nothing
  assert.deepEqual(columnWidths([NaN, undefined, -5, 'x']), [25, 25, 25, 25]);
  // air: room a column would like beside its need. With room to spare it counts as need
  near(columnWidths([20, 19, 26, 22], 2), [24, 24, 28, 24]);
  assert.deepEqual(columnWidths([20, 19, 22, 21], 2), [25, 25, 25, 25]);
  // it gives way before a need does: the needs fit, need and air do not, so
  // every column keeps its need and what is over is shared equally
  near(columnWidths([22, 21, 30, 23], 2), [23, 22, 31, 24]);
  near(columnWidths([25, 25, 25, 24.6], 2), [25.1, 25.1, 25.1, 24.7]);
  // and it is no part of the cut when the needs themselves cannot fit
  near(columnWidths([30, 30, 60], 5), [30, 30, 40]);
  assert.deepEqual(layout(NODES, true, {}, 3).pos, layout(NODES, true).pos);
});

test('narrow: a column is as wide as its neediest place asks', () => {
  // with nothing asked the columns are the equal ones, to the digit
  const plain = layout(NODES, true);
  for (const [id, x] of [['the-wild', 12.5], ['gateway', 37.5], ['host-a', 62.5], ['vm-1', 87.5]]) {
    assert.equal(layout(NODES, true, {}).pos[id].x, x);
    assert.equal(layout(NODES, true, { 'host-a': 25, 'vm-2': 3 }).pos[id].x, x, 'a need within an equal share moves nothing');
  }
  assert.deepEqual(plain.pos['host-b'], { x: 62.5, y: 100 * 1.5 / 3, w: 25, c: 2 });
  // one long name on tier 2: its whole column widens, the others give way equally
  const { pos, cols, rows } = layout(NODES, true, { 'host-b': 28, 'host-a': 12, gateway: 19 });
  assert.equal(cols, 4);
  assert.equal(rows, 3);
  for (const id of ['host-a', 'host-b', 'switch-1']) {
    assert.equal(pos[id].w, 28, id);
    assert.equal(pos[id].c, 2);
    assert.equal(pos[id].x, 24 + 24 + 14);
  }
  assert.deepEqual([pos['the-wild'].x, pos.gateway.x, pos['vm-1'].x], [12, 36, 88]);
  assert.deepEqual([pos['the-wild'].w, pos.traefik.w, pos['vm-2'].w], [24, 24, 24]);
  // the rows do not move with the widths
  assert.equal(pos['host-b'].y, plain.pos['host-b'].y);
  // a place that is not drawn asks for nothing, and the wide picture never listens
  assert.deepEqual(layout(NODES, true, { nobody: 90 }).pos, plain.pos);
  assert.deepEqual(layout(NODES, false, { 'host-b': 90 }), layout(NODES));
});

test('narrow: the curve beside a column is bowed by that column, not by an equal share', () => {
  // a place that carries its column bows by it: 0.62 of a 40-wide column
  const wide = edgePath({ x: 70, y: 10, w: 40, c: 2 }, { x: 70, y: 70, w: 40, c: 2 }, true, 4);
  assert.equal(wide, 'M 70 10 C 45.2 10, 45.2 70, 70 70');
  // the first column is the first by its number, not by where its centre falls:
  // a thin first column beside a wide second one puts the second's centre under its own width
  const second = edgePath({ x: 35, y: 10, w: 50, c: 1 }, { x: 35, y: 70, w: 50, c: 1 }, true, 3);
  assert.equal(second, 'M 35 10 C 4 10, 4 70, 35 70');
  const first = edgePath({ x: 5, y: 10, w: 10, c: 0 }, { x: 5, y: 70, w: 10, c: 0 }, true, 3);
  assert.equal(first, 'M 5 10 C 11.2 10, 11.2 70, 5 70');
  // whatever the widths, the curve stays inside the picture
  for (const needs of [{}, { 'host-b': 28 }, { 'the-wild': 40, 'vm-1': 45 }, { gateway: 70 }]) {
    const { pos } = layout(NODES, true, needs);
    for (const p of Object.values(pos)) {
      const bx = Number(edgePath(p, { ...p, y: p.y + 30 }, true, 4).split(' ')[4]);
      const peak = p.x + 0.75 * (bx - p.x);
      assert.ok(peak >= 0 && peak <= 100, `${JSON.stringify(needs)}: peak ${peak}`);
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
