/* TOPOLOGY's rules (2026-11-16), in plain node: the graph, its heads and
   layers, the layout, the views, and the questions the canvas asks. The
   shared cases in topology_cases.json are run here and by the server's twin.

   Run:  node --test tests/test_topology_model.mjs        (from Web/) */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ASPECT, CARD_H, CARD_W, EDGE_INSET, FIT_FLOOR, FOLD_LIMIT, GAP_X, GAP_Y, INFRA_STUBS, LANE_GAP, MAX_ZOOM,
  MIN_ZOOM, MONO_ADVANCE, PIECE_GAP, PORT_REACH, ROW, SIDE_INSET, SLOT,
  arrange, boxesMeet, buildGraph, cableGeometry, cableLayout, cablePath, cardBox, carries, centreOn, chipBox,
  clip, clipTo, connections, find, fitView, foldLeaves, groupHolding, heads, infrastructure, layers, linkSeen,
  nearEnd, neighbour, onVlan, pathMarks, pathToHead, pointOn, seen, spreadEnds, stripes, textWidth, viewBox,
  vlanLabel, vlanList, vlanLit, vlanNumber, zoomAt,
} from '../static/js/topology-model.js';

const here = (path) => new URL(path, import.meta.url);
const CASES = JSON.parse(readFileSync(here('./topology_cases.json'), 'utf8')).cases;
const DEMO = JSON.parse(readFileSync(here('../../demo-lab/seed/lab-data.demo.json'), 'utf8'));
const SOURCE = readFileSync(here('../static/js/topology-model.js'), 'utf8');

const clone = (v) => JSON.parse(JSON.stringify(v));
const freeze = (v) => {
  if (v && typeof v === 'object') { Object.values(v).forEach(freeze); Object.freeze(v); }
  return v;
};
const linkOf = (graph, id) => graph.linkById.get(id);
const ups = (graph) => Object.fromEntries([...layers(graph)].map(([id, e]) => [id, e.up ? e.up.id : null]));

/** No two cards in a layout overlap. */
function assertNoOverlap(positions) {
  const cards = Object.entries(positions);
  // sort by x so only near neighbours are compared
  cards.sort((a, b) => a[1].x - b[1].x);
  for (let i = 0; i < cards.length; i++) {
    const [ia, pa] = cards[i];
    for (let j = i + 1; j < cards.length && cards[j][1].x < pa.x + CARD_W; j++) {
      const [ib, pb] = cards[j];
      const apart = pb.x >= pa.x + CARD_W || pa.x >= pb.x + CARD_W || pb.y >= pa.y + CARD_H || pa.y >= pb.y + CARD_H;
      assert.ok(apart, `${ia} and ${ib} overlap at ${JSON.stringify(pa)} / ${JSON.stringify(pb)}`);
    }
  }
}

/** A parent sits within the span of its children. */
function assertParentsCentred(graph, positions) {
  const kids = new Map();
  for (const [id, e] of layers(graph)) {
    if (!e.up) continue;
    if (!kids.has(e.up.id)) kids.set(e.up.id, []);
    kids.get(e.up.id).push(positions[id].x);
  }
  for (const [id, xs] of kids) {
    const x = positions[id].x;
    assert.ok(x >= Math.min(...xs) && x <= Math.max(...xs), `${id} at ${x} is outside its children ${Math.min(...xs)}..${Math.max(...xs)}`);
  }
}

/** A made-up network: a line in, a gateway, `switches` switches, and the rest
    hanging off the switches by cable, a few with routes across. */
function generated(places, switches = 8) {
  const nodes = [{ id: 'gate', name: 'GATE', kind: 'network', ip: '192.0.2.1', zone: 'z1' }];
  const cables = [{ id: 'w', a_stub: 'line', a_port: 'lan', b: 'gate', b_port: 'wan' }];
  const routes = [];
  for (let s = 1; s <= switches; s++) {
    nodes.push({ id: `sw-${s}`, name: `SW ${s}`, kind: 'network', ip: `192.0.2.${s + 1}`, zone: 'z1' });
    cables.push({ id: `up-${s}`, a: 'gate', a_port: `${s}`, b: `sw-${s}`, b_port: '24', vlan: 1, tagged: [10, 20] });
  }
  for (let i = 0; nodes.length < places; i++) {
    const s = (i % switches) + 1;
    const id = `host-${i}`;
    nodes.push({ id, name: `HOST ${i}`, kind: i % 3 ? 'physical' : 'vm', ip: `198.51.100.${i % 250}`, zone: 'z2' });
    cables.push({ id: `c-${i}`, a: `sw-${s}`, a_port: `${Math.floor(i / switches) + 1}`, b: id, b_port: 'eth0', vlan: 10 });
    if (i % 17 === 0 && i > 0) routes.push({ from: id, to: `host-${i - 1}`, kind: 'telemetry' });
  }
  return { nodes, stubs: [{ id: 'line', name: 'LINE IN', kind: 'internet' }], cables, routes };
}

/* ── the shared cases ─────────────────────────────────────────────────────── */

test('the shared cases file has every case the twin needs', () => {
  assert.ok(CASES.length >= 10);
  for (const c of CASES) {
    for (const k of ['name', 'data', 'heads', 'depth', 'up', 'paths', 'connections']) assert.ok(k in c, `${c.name} lacks ${k}`);
  }
});

for (const c of CASES) {
  test(`case: ${c.name}`, () => {
    const data = freeze(clone(c.data));
    const graph = buildGraph(data);
    assert.deepEqual(heads(graph), c.heads, 'heads');
    const info = layers(graph);
    for (const [id, depth] of Object.entries(c.depth)) {
      assert.ok(info.has(id), `${id} is a thing`);
      assert.equal(info.get(id).depth, depth, `depth of ${id}`);
      assert.equal(info.get(id).loose, depth === null, `loose of ${id}`);
    }
    for (const [id, up] of Object.entries(c.up)) {
      assert.equal(info.get(id).up ? info.get(id).up.id : null, up, `up of ${id}`);
    }
    for (const [id, path] of Object.entries(c.paths)) {
      const p = pathToHead(graph, id);
      assert.deepEqual(p.things, path, `path of ${id}`);
      assert.equal(p.links.length, Math.max(0, path.length - 1));
    }
    const rows = connections(graph).map(({ id, to, port, farPort, vlan, poe, path }) => ({ id, to, port, farPort, vlan, poe, path }));
    assert.deepEqual(rows, c.connections, 'connections');
    assert.deepEqual(data, c.data, 'the data is not changed');
  });
}

/* ── buildGraph ───────────────────────────────────────────────────────────── */

test('buildGraph: things carry their facts, places first, then stubs', () => {
  const g = buildGraph({
    nodes: [
      { id: 'gate', name: 'GATE', kind: 'network', ip: '192.0.2.1', zone: 'z', planned: true },
      { id: 'vm', name: 'VM', kind: 'vm', ip: '\u2014', zone: 'z', parent: 'host', unmanaged: true },
      { id: 'host', kind: 'physical', ip: ' 192.0.2.9 ' },
    ],
    stubs: [{ id: 'jack', name: 'Wall jack', kind: 'outlet' }, { id: 'sw', name: 'Desk switch', kind: 'switch' }],
  });
  assert.deepEqual(g.things.map((t) => t.id), ['gate', 'vm', 'host', 'jack', 'sw']);
  assert.deepEqual(g.byId.get('gate'), {
    id: 'gate', type: 'place', name: 'GATE', kind: 'network', sub: '192.0.2.1', ip: '192.0.2.1',
    zone: 'z', parent: null, planned: true, unmanaged: false, infra: true, order: 0,
  });
  const vm = g.byId.get('vm');
  assert.equal(vm.sub, '');
  assert.equal(vm.parent, 'host');
  assert.equal(vm.unmanaged, true);
  assert.equal(vm.infra, false);
  assert.equal(g.byId.get('host').name, 'host', 'a nameless place is called by its id');
  assert.equal(g.byId.get('host').sub, '192.0.2.9');
  assert.equal(g.byId.get('jack').type, 'stub');
  assert.equal(g.byId.get('jack').sub, 'outlet');
  assert.equal(g.byId.get('jack').infra, false);
  assert.equal(g.byId.get('sw').infra, true);
  assert.deepEqual(INFRA_STUBS, ['internet', 'switch', 'patch']);
  // a parent tie: host above vm
  assert.deepEqual(g.links.map((l) => [l.id, l.layer, l.a, l.b]), [['parent:vm', 'parent', 'host', 'vm']]);
});

test('buildGraph: a cable reads both ends, a place or a stub, with its facts', () => {
  const g = buildGraph(DEMO);
  const wan = linkOf(g, 'wan-in');
  assert.equal(wan.layer, 'cable');
  assert.equal(wan.a, 'fibre-line');
  assert.equal(wan.b, 'gateway');
  assert.equal(wan.aPort, 'lan');
  assert.equal(wan.bPort, 'igc0');
  const cam = linkOf(g, 'camera-poe');
  assert.equal(cam.poe, 12);
  assert.equal(cam.vlan, 66);
  assert.deepEqual(cam.tagged, []);
  assert.equal(cam.speed, '1G');
  assert.equal(cam.state, 'confirmed');
  assert.equal(cam.source, 'hand');
  assert.equal(linkOf(g, 'gpu-desk').state, 'assumed');
  assert.equal(linkOf(g, 'hv-uplink').kind, 'dac');
  assert.deepEqual(linkOf(g, 'gw-trunk').tagged, [10, 30, 33, 66, 90]);
  // the demo has 8 cables; every route; the vms that have no route to their host
  assert.equal(g.links.filter((l) => l.layer === 'cable').length, (DEMO.cables || []).length);
  assert.equal(g.links.filter((l) => l.layer === 'route').length, DEMO.routes.length);
});

test('buildGraph: a route a cable already covers is shadowed, a parent tie a link covers is dropped', () => {
  const g = buildGraph({
    nodes: [
      { id: 'gate', kind: 'network' }, { id: 'host', kind: 'physical' },
      { id: 'vm-1', kind: 'vm', parent: 'host' }, { id: 'vm-2', kind: 'vm', parent: 'host' },
      { id: 'vm-3', kind: 'vm', parent: 'host' },
    ],
    cables: [{ id: 'c', a: 'gate', b: 'host' }, { id: 'v3', a: 'host', b: 'vm-3', kind: 'virtual' }],
    routes: [{ from: 'host', to: 'gate', kind: 'vlan' }, { from: 'host', to: 'vm-2' }],
  });
  const route = g.links.find((l) => l.layer === 'route' && l.b === 'gate');
  assert.equal(route.shadowed, true);
  assert.equal(route.id, 'route:host:gate');
  assert.equal(g.links.find((l) => l.layer === 'route' && l.b === 'vm-2').shadowed, false);
  assert.equal(g.links.find((l) => l.layer === 'route' && l.b === 'vm-2').kind, 'vlan', 'a route with no kind is a vlan route');
  assert.deepEqual(g.links.filter((l) => l.layer === 'parent').map((l) => l.id), ['parent:vm-1']);
});

test('buildGraph: lanes number the links of one layer between one pair', () => {
  const g = buildGraph({
    nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
    cables: [{ id: 'x', a: 'a', b: 'b' }, { id: 'y', a: 'b', b: 'a' }, { id: 'z', a: 'a', b: 'c' }],
    routes: [{ from: 'a', to: 'b' }, { from: 'b', to: 'a', kind: 'edge' }, { from: 'a', to: 'b' }],
  });
  const lanes = Object.fromEntries(g.links.map((l) => [l.id, [l.lane, l.lanes]]));
  assert.deepEqual(lanes, {
    x: [0, 2], y: [1, 2], z: [0, 1],
    'route:a:b': [0, 3], 'route:b:a': [1, 3], 'route:a:b:2': [2, 3],
  });
});

test('buildGraph: hand-edited junk in every section is skipped, never thrown on', () => {
  for (const data of [undefined, null, 7, 'text', [], {}, { nodes: 'x', stubs: 3, cables: {}, routes: null, zones: false }]) {
    const g = buildGraph(data);
    assert.deepEqual(g.things, []);
    assert.deepEqual(g.links, []);
    assert.deepEqual(heads(g), []);
    assert.equal(layers(g).size, 0);
    assert.deepEqual(arrange(g), { positions: Object.create(null), width: 0, height: 0, bounds: { x: 0, y: 0, w: 0, h: 0 } });
    assert.deepEqual(connections(g), []);
    assert.deepEqual(vlanList(g, data && data.zones), []);
  }
  const g = buildGraph({
    nodes: [null, 1, 'gate', [], { id: '' }, { id: 5 }, { id: 'gate', kind: 'network', zone: 3, parent: 'gate' },
      { id: 'gate', kind: 'vm' }, { id: 'pc', parent: 'nowhere' }, { id: 'vm', parent: 'jack' }],
    stubs: [{ id: 'gate', kind: 'internet' }, { id: 'jack', kind: 'outlet', name: 42 }, { kind: 'switch' }],
    cables: [
      { a: 'gate', b: 'pc', vlan: 'ten', tagged: 'all', poe_w: -3 },
      { id: 'dup', a: 'gate', b: 'pc', vlan: '\u2014', tagged: [10, '20', 'x', null, 10, 5000], poe_w: '15.4' },
      { id: 'dup', a: 'pc', b_stub: 'jack' },
      { id: 'both', a: 'gone', a_stub: 'jack', b: 'gate', state: 'maybe' },
      { id: 'self', a_stub: 'jack', b_stub: 'jack' },
      { id: 'half', a: 'gate' },
    ],
    routes: [{ from: 'gate', to: 'pc', kind: 7 }, { from: null, to: 'pc' }, 'r'],
  });
  assert.deepEqual(g.things.map((t) => t.id), ['gate', 'pc', 'vm', 'jack']);
  assert.equal(g.byId.get('gate').zone, null);
  assert.equal(g.byId.get('gate').parent, null, 'a place is not its own parent');
  assert.equal(g.byId.get('pc').parent, null, 'a parent that is gone is dropped');
  assert.equal(g.byId.get('vm').parent, null, 'a parent must be a place, not a stub');
  assert.equal(g.byId.get('jack').name, '42');
  const cables = g.links.filter((l) => l.layer === 'cable');
  assert.deepEqual(cables.map((l) => l.id), ['cable:0', 'dup', 'cable:2', 'both']);
  assert.equal(cables[0].vlan, null);
  assert.deepEqual(cables[0].tagged, []);
  assert.equal(cables[0].poe, null);
  assert.equal(cables[1].vlan, null);
  assert.deepEqual(cables[1].tagged, [10, 20]);
  assert.equal(cables[1].poe, 15.4);
  assert.equal(cables[3].a, 'jack', 'a place end that is gone falls back to the stub named');
  assert.equal(cables[3].state, 'confirmed');
  assert.equal(g.links.find((l) => l.layer === 'route').kind, '7');
  assert.doesNotThrow(() => arrange(g, { saved: { gate: 'x', pc: { x: 'a', y: 1 }, nope: { x: 1, y: 1 } } }));
});

test('buildGraph and every reader leave their input as it was', () => {
  const data = freeze(clone(DEMO));
  const g = buildGraph(data);
  heads(g); layers(g); arrange(g, { saved: freeze({ nas: { x: 1, y: 2 } }) });
  infrastructure(g); foldLeaves(g, { limit: 3 }); connections(g); vlanList(g, data.zones);
  find(g, 'nas'); stripes(g.links[0], data.zones);
  assert.deepEqual(data, DEMO);
});

/* ── VLAN notation ────────────────────────────────────────────────────────── */

test('vlanLabel reads a cable in switch notation', () => {
  assert.equal(vlanLabel({ vlan: 10 }), 'U10');
  assert.equal(vlanLabel({ vlan: '10', tagged: [] }), 'U10');
  assert.equal(vlanLabel({ vlan: 1, tagged: [99, '20', 10] }), 'U1 T10,20,99');
  assert.equal(vlanLabel({ tagged: [20, 10, 20] }), 'T10,20');
  assert.equal(vlanLabel({ vlan: 0 }), 'U0');
  assert.equal(vlanLabel({}), '');
  assert.equal(vlanLabel({ vlan: '\u2014', tagged: 'all' }), '');
  assert.equal(vlanLabel(null), '');
  assert.equal(vlanLabel('U10'), '');
});

test('vlanNumber takes numbers and numeric strings, nothing else', () => {
  assert.equal(vlanNumber(33), 33);
  assert.equal(vlanNumber(' 33 '), 33);
  assert.equal(vlanNumber('4095'), 4095);
  for (const v of [4096, -1, 1.5, '', '\u2014', 'ten', null, undefined, [], {}, NaN, '1e2']) assert.equal(vlanNumber(v), null, String(v));
});

/* ── heads and layers ─────────────────────────────────────────────────────── */

test('heads: the demo stands on its line in; without cables, on the gateway', () => {
  const g = buildGraph(DEMO);
  assert.deepEqual(heads(g), ['fibre-line']);
  // every map on first open has routes and no cables: the wan route decides
  const firstOpen = { ...DEMO, cables: [], stubs: [] };
  assert.deepEqual(heads(buildGraph(firstOpen)), ['gateway']);
  // and a wan route written the other way round reads the same
  const flipped = { ...firstOpen, routes: DEMO.routes.map((r) => (r.kind === 'wan' ? { ...r, from: r.to, to: r.from } : r)) };
  assert.deepEqual(heads(buildGraph(flipped)), ['gateway']);
});

test('heads: with no line and no wan route, the busiest network place; else the busiest thing', () => {
  const g = buildGraph({
    nodes: [{ id: 'a', kind: 'physical' }, { id: 'b', kind: 'physical' }, { id: 'c', kind: 'physical' }, { id: 'lone' }],
    cables: [{ id: '1', a: 'a', b: 'b' }, { id: '2', a: 'b', b: 'c' }],
  });
  assert.deepEqual(heads(g), ['b']);
  assert.equal(layers(g).get('lone').loose, true);
  // a stub can head a piece of things that are not network gear
  const s = buildGraph({ nodes: [{ id: 'pc' }, { id: 'tv' }], stubs: [{ id: 'hub', kind: 'switch' }],
    cables: [{ id: '1', a: 'pc', b_stub: 'hub' }, { id: '2', a: 'tv', b_stub: 'hub' }] });
  assert.deepEqual(heads(s), ['hub']);
});

test('layers: the demo hangs the gateway under the line, and the vms under their host or by route', () => {
  const g = buildGraph(DEMO);
  const info = layers(g);
  assert.equal(info.get('fibre-line').depth, 0);
  assert.equal(info.get('gateway').depth, 1);
  assert.deepEqual(info.get('gateway').up, { id: 'fibre-line', link: 'wan-in', layer: 'cable' });
  assert.equal(info.get('core-switch').depth, 2);
  assert.equal(info.get('workstation').up.id, 'desk-switch');
  assert.equal(info.get('the-wild').up.layer, 'route');
  assert.equal(info.get('the-wild').up.id, 'gateway');
  assert.equal(info.get('offsite').up.id, 'nas');
  assert.equal(info.get('standby').up.layer, 'parent');
  assert.equal(info.get('standby').up.id, 'hypervisor');
  assert.equal(info.get('nas-2').loose, true, 'a planned place with no link is loose');
  for (const [id, e] of info) if (!e.loose) assert.equal(e.head, 'fibre-line', id);
});

test('layers: a ring of cables and a ring of routes both end', () => {
  const ring = (n, layer) => {
    const nodes = Array.from({ length: n }, (_, i) => ({ id: `n${i}`, kind: i ? 'physical' : 'network' }));
    const links = nodes.map((_, i) => [`n${i}`, `n${(i + 1) % n}`]);
    return buildGraph(layer === 'cable'
      ? { nodes, cables: links.map(([a, b], i) => ({ id: `c${i}`, a, b })) }
      : { nodes, routes: links.map(([from, to]) => ({ from, to })) });
  };
  for (const layer of ['cable', 'route']) {
    const info = layers(ring(9, layer));
    assert.deepEqual([...info.values()].map((e) => e.depth), [0, 1, 2, 3, 4, 4, 3, 2, 1], layer);
  }
});

test('layers: cables walk again from a thing a route reached', () => {
  const g = buildGraph({
    nodes: [{ id: 'gate', kind: 'network' }, { id: 'far', kind: 'network' }, { id: 'pc' }],
    cables: [{ id: 'c', a: 'far', b: 'pc' }],
    routes: [{ from: 'gate', to: 'far', kind: 'wan' }],
  });
  assert.deepEqual(heads(g), ['far'], 'far has more links, so it is the inside end');
  const g2 = buildGraph({
    nodes: [{ id: 'gate', kind: 'network' }, { id: 'site', kind: 'network' }, { id: 'pc' }],
    stubs: [{ id: 'line', kind: 'internet' }],
    cables: [{ id: 'w', a_stub: 'line', b: 'gate' }, { id: 'c', a: 'site', b: 'pc' }],
    routes: [{ from: 'gate', to: 'site', kind: 'mesh' }],
  });
  assert.deepEqual(ups(g2), { gate: 'line', site: 'gate', pc: 'site', line: null });
  assert.equal(layers(g2).get('pc').up.layer, 'cable');
  assert.equal(layers(g2).get('pc').depth, 3);
});

/* ── arrange ──────────────────────────────────────────────────────────────── */

test('the size constants fit together', () => {
  assert.equal(SLOT, CARD_W + GAP_X);
  assert.equal(ROW, CARD_H + GAP_Y);
  assert.ok(PIECE_GAP >= GAP_X);
  assert.equal(FOLD_LIMIT, 150);
});

test('arrange: the demo is deterministic, cards never overlap, heads on top, parents over their children', () => {
  const g = buildGraph(DEMO);
  const one = arrange(g);
  const two = arrange(buildGraph(clone(DEMO)));
  assert.deepEqual(one, two);
  assert.deepEqual(arrange(g), one);
  assertNoOverlap(one.positions);
  assertParentsCentred(g, one.positions);
  assert.equal(one.positions['fibre-line'].y, 0);
  assert.equal(one.positions.gateway.y, ROW);
  assert.equal(Object.keys(one.positions).length, g.things.length);
  const info = layers(g);
  const deepest = Math.max(...[...info.values()].filter((e) => !e.loose).map((e) => e.depth));
  assert.ok(one.positions['nas-2'].y > deepest * ROW, 'the loose thing is in a row at the foot');
  for (const p of Object.values(one.positions)) {
    assert.ok(p.x >= 0 && p.y >= 0 && p.x + CARD_W <= one.width && p.y + CARD_H <= one.height);
  }
});

test('arrange: a 300-place network lays out without overlap, parents within their children', () => {
  const g = buildGraph(generated(300));
  assert.equal(g.things.length, 301);
  const out = arrange(g);
  assertNoOverlap(out.positions);
  assertParentsCentred(g, out.positions);
  assert.deepEqual(arrange(buildGraph(generated(300))), out);
  assert.equal(out.positions.line.y, 0);
  for (let s = 1; s <= 8; s++) assert.equal(out.positions[`sw-${s}`].y, 2 * ROW);
});

/** Many hosts with guests by `parent` and no routes: the map that drew as one
    long row. 42 hosts, 258 guests on the first 30, as 72 cards once folded. */
function hosted() {
  const nodes = [];
  for (let h = 0; h < 42; h++) nodes.push({ id: `host-${h}`, name: `HOST ${h}`, kind: 'physical' });
  for (let i = 0; i < 258; i++) nodes.push({ id: `guest-${i}`, kind: 'vm', parent: `host-${i % 30}` });
  return { nodes };
}

const span = (positions, ids) => {
  const ps = ids.map((id) => positions[id]);
  const x0 = Math.min(...ps.map((p) => p.x));
  const y0 = Math.min(...ps.map((p) => p.y));
  return { x0, y0, x1: Math.max(...ps.map((p) => p.x + CARD_W)), y1: Math.max(...ps.map((p) => p.y + CARD_H)) };
};

test('arrange: separate pieces stand apart, loose things make a block at the foot (2026-11-17)', () => {
  const nodes = [{ id: 'a', kind: 'network' }, { id: 'a1' }, { id: 'b', kind: 'network' }, { id: 'b1' }];
  for (let i = 0; i < 20; i++) nodes.push({ id: `loose-${i}` });
  const g = buildGraph({ nodes, cables: [{ id: '1', a: 'a', b: 'a1' }, { id: '2', a: 'b', b: 'b1' }] });
  const { positions } = arrange(g);
  assertNoOverlap(positions);
  assert.deepEqual(positions.a, { x: 0, y: 0 }, 'the first head\'s piece is top left');
  const apart = positions.b.x >= positions.a.x + CARD_W + PIECE_GAP || positions.b.y >= positions.a1.y + CARD_H + PIECE_GAP;
  assert.ok(apart, 'the second piece is a piece gap clear of the first');
  const trees = span(positions, ['a', 'a1', 'b', 'b1']);
  const loose = Array.from({ length: 20 }, (_, i) => `loose-${i}`);
  const block = span(positions, loose);
  assert.ok(block.y0 >= trees.y1 + PIECE_GAP, 'the loose block is under the pieces');
  assert.equal(block.x0, 0);
  // a block: every row but the last full, rows as even as they can be
  const rows = new Map();
  for (const id of loose) rows.set(positions[id].y, (rows.get(positions[id].y) || 0) + 1);
  const counts = [...rows.values()];
  assert.ok(counts.length > 1, 'twenty loose things are not one line');
  const [first] = counts;
  assert.ok(counts.slice(0, -1).every((c) => c === first), `full rows: ${counts}`);
  assert.ok(counts.at(-1) <= first && counts.at(-1) > first - counts.length, `the last row is nearly full: ${counts}`);
  for (let i = 1; i < loose.length; i++) {
    const p = positions[loose[i - 1]];
    const q = positions[loose[i]];
    assert.ok(q.y > p.y || (q.y === p.y && q.x === p.x + SLOT), 'loose things in dataset order, a slot apart');
  }
});

test('arrange: pieces are packed toward the ratio asked for, the first one at 0,0 (2026-11-17)', () => {
  const g = foldLeaves(buildGraph(hosted()));
  assert.equal(g.things.length, 72);
  const out = arrange(g);
  assertNoOverlap(out.positions);
  assertParentsCentred(g, out.positions);
  assert.deepEqual(out.positions['host-0'], { x: 0, y: 0 });
  const r = out.width / out.height;
  assert.ok(r > 1.6 / 2 && r < 1.6 * 2, `16:10 asked, ${out.width} x ${out.height} given`);
  // the fit of an 800 x 500 window is at least three times what one long row gave
  assert.ok(fitView(out.bounds, 800, 500, { pad: 36 }).k > 0.25);
  // the same input and ratio, the same picture; another ratio, another shape
  assert.deepEqual(arrange(foldLeaves(buildGraph(hosted()))), out);
  assert.deepEqual(arrange(g, { ratio: 1.6 }), out, 'the default is 16:10');
  const tall = arrange(g, { ratio: 0.5 });
  const wide = arrange(g, { ratio: 4 });
  assertNoOverlap(tall.positions);
  assertNoOverlap(wide.positions);
  assert.ok(tall.width / tall.height < r && wide.width / wide.height > r, 'the ratio steers the shape');
  assert.deepEqual(tall.positions['host-0'], { x: 0, y: 0 });
  for (const bad of [0, -1, NaN, Infinity, 'wide', null]) assert.deepEqual(arrange(g, { ratio: bad }), out, `ratio ${bad} is the default`);
  // each piece stays whole: a guest group is still under its own host
  for (let h = 0; h < 30; h++) {
    const group = g.things.find((t) => t.type === 'group' && t.id.startsWith(`group:host-${h}:`));
    assert.equal(out.positions[group.id].x, out.positions[`host-${h}`].x);
    assert.equal(out.positions[group.id].y, out.positions[`host-${h}`].y + ROW);
  }
});

test('arrange: a saved card still wins after packing; loose-only and empty maps pack too (2026-11-17)', () => {
  const g = foldLeaves(buildGraph(hosted()));
  const plain = arrange(g).positions;
  const out = arrange(g, { saved: { 'host-7': { x: -900, y: 40 } } });
  assert.deepEqual(out.positions['host-7'], { x: -900, y: 40 });
  for (const id of Object.keys(plain)) if (id !== 'host-7') assert.deepEqual(out.positions[id], plain[id], id);
  // 2,000 things with no link at all: one block near the ratio, quickly
  const nodes = Array.from({ length: 2000 }, (_, i) => ({ id: `p${i}` }));
  const t0 = performance.now();
  const loose = arrange(buildGraph({ nodes }));
  assert.ok(performance.now() - t0 < 500);
  assertNoOverlap(loose.positions);
  assert.deepEqual(loose.positions.p0, { x: 0, y: 0 });
  const r = loose.width / loose.height;
  assert.ok(r > 1.2 && r < 2.2, `${loose.width} x ${loose.height}`);
  // 1,000 two-card pieces
  const pairs = { nodes: [], cables: [] };
  for (let i = 0; i < 1000; i++) {
    pairs.nodes.push({ id: `s${i}`, kind: 'network' }, { id: `d${i}` });
    pairs.cables.push({ id: `c${i}`, a: `s${i}`, b: `d${i}` });
  }
  const t1 = performance.now();
  const packed = arrange(buildGraph(pairs));
  assert.ok(performance.now() - t1 < 1000);
  assertNoOverlap(packed.positions);
  assert.ok(packed.width / packed.height > 0.8 && packed.width / packed.height < 3.2, `${packed.width} x ${packed.height}`);
});

test('arrange: siblings are ordered by where their other links go', () => {
  // under the switch: pc-1, pc-2 in that order; pc-1 also talks to the far right thing
  const g = buildGraph({
    nodes: [{ id: 'gate', kind: 'network' }, { id: 'sw', kind: 'network' }, { id: 'pc-1' }, { id: 'pc-2' },
      { id: 'srv-a' }, { id: 'srv-b' }, { id: 'srv-c' }],
    cables: [
      { id: '1', a: 'gate', b: 'sw' }, { id: '2', a: 'gate', b: 'srv-a' }, { id: '3', a: 'gate', b: 'srv-b' },
      { id: '4', a: 'gate', b: 'srv-c' }, { id: '5', a: 'sw', b: 'pc-1' }, { id: '6', a: 'sw', b: 'pc-2' },
    ],
    routes: [{ from: 'pc-1', to: 'srv-c' }],
  });
  const { positions } = arrange(g);
  assert.ok(positions['pc-2'].x < positions['pc-1'].x, 'pc-1 moves toward srv-c');
});

test('arrange: a saved card keeps its place and the rest do not move for it', () => {
  const g = buildGraph(DEMO);
  const plain = arrange(g).positions;
  const out = arrange(g, { saved: { nas: { x: -500, y: 9000 }, gone: { x: 1, y: 1 }, gateway: { x: 'left', y: 0 } } });
  assert.deepEqual(out.positions.nas, { x: -500, y: 9000 });
  assert.deepEqual(out.positions.gateway, plain.gateway, 'a saved value that is not a number is ignored');
  assert.equal(out.positions.gone, undefined);
  for (const id of Object.keys(plain)) if (id !== 'nas') assert.deepEqual(out.positions[id], plain[id], id);
  assert.equal(out.bounds.x, -500);
  assert.equal(out.height, 9000 + CARD_H);
});

test('arrange: 2,000 things build, layer and lay out quickly', () => {
  const data = generated(2000, 40);
  const t0 = performance.now();
  const g = buildGraph(data);
  layers(g);
  const out = arrange(g);
  const ms = performance.now() - t0;
  console.log(`  2,000 things: buildGraph + layers + arrange in ${ms.toFixed(1)} ms`);
  assert.equal(Object.keys(out.positions).length, 2001);
  assert.ok(ms < 1000, `${ms} ms`);
  // and a 2,000-long chain does not overflow the stack
  const nodes = Array.from({ length: 2000 }, (_, i) => ({ id: `n${i}`, kind: i ? 'physical' : 'network' }));
  const chain = buildGraph({ nodes, cables: nodes.slice(1).map((n, i) => ({ id: `c${i}`, a: `n${i}`, b: n.id })) });
  assert.equal(arrange(chain).positions.n1999.y, 1999 * ROW);
});

/* ── views ────────────────────────────────────────────────────────────────── */

test('infrastructure keeps network gear and the links between it', () => {
  const g = buildGraph(DEMO);
  const infra = infrastructure(g);
  assert.deepEqual(infra.things.map((t) => t.id), ['gateway', 'core-switch', 'offsite', 'the-wild', 'fibre-line', 'desk-switch']);
  for (const l of infra.links) assert.ok(infra.byId.has(l.a) && infra.byId.has(l.b));
  assert.deepEqual(infra.links.map((l) => l.id).sort(), ['desk-run', 'gw-trunk', 'route:gateway:core-switch', 'route:gateway:the-wild', 'wan-in']);
  assert.deepEqual(heads(infra), ['fibre-line']);
  assert.equal(g.things.length, DEMO.nodes.length + DEMO.stubs.length, 'the original graph is untouched');
  assertNoOverlap(arrange(infra).positions);
});

test('foldLeaves folds leaves into one group per kind under their parent, past the limit only', () => {
  const at150 = buildGraph(generated(149));
  assert.equal(at150.things.length, 150);
  assert.equal(foldLeaves(at150), at150, 'at the limit, unchanged');
  const at151 = buildGraph(generated(150));
  assert.equal(at151.things.length, 151);
  const folded = foldLeaves(at151);
  assert.notEqual(folded, at151);
  const groups = folded.things.filter((t) => t.type === 'group');
  assert.ok(groups.length > 0);
  const g1 = folded.byId.get('group:sw-1:physical');
  assert.equal(g1.type, 'group');
  assert.equal(g1.kind, 'physical');
  assert.equal(g1.count, g1.members.length);
  assert.ok(g1.members.every((id) => at151.byId.get(id).kind === 'physical'));
  const link = folded.linkById.get('fold:sw-1:physical');
  assert.deepEqual([link.a, link.b, link.layer], ['sw-1', 'group:sw-1:physical', 'cable']);
  // a leaf with a route across is not a leaf; nothing folded keeps a link
  for (const l of folded.links) assert.ok(folded.byId.has(l.a) && folded.byId.has(l.b), l.id);
  const memberCount = groups.reduce((n, t) => n + t.count, 0);
  assert.equal(folded.things.length, at151.things.length - memberCount + groups.length);
  assert.deepEqual(folded.things.map((t) => t.order), folded.things.map((_, i) => i));
  assertNoOverlap(arrange(folded).positions);
  assert.equal(at151.things.length, 151, 'the original graph is untouched');
  assert.ok(at151.things.every((t) => t.type !== 'group'));
});

test('foldLeaves: a lone leaf of its kind, a pair standing alone, and infra are never folded', () => {
  const g = buildGraph({
    nodes: [{ id: 'sw', kind: 'network' }, { id: 'a', kind: 'vm' }, { id: 'b', kind: 'vm' }, { id: 'p', kind: 'printer' },
      { id: 'ap-1', kind: 'network' }, { id: 'ap-2', kind: 'network' }, { id: 'x' }, { id: 'y' }],
    cables: [{ id: '1', a: 'sw', b: 'a' }, { id: '2', a: 'sw', b: 'b' }, { id: '3', a: 'sw', b: 'p' },
      { id: '4', a: 'sw', b: 'ap-1' }, { id: '5', a: 'sw', b: 'ap-2' }, { id: '6', a: 'x', b: 'y' }],
    routes: [{ from: 'b', to: 'sw' }],
  });
  const f = foldLeaves(g, { limit: 2 });
  assert.deepEqual(f.things.map((t) => t.id), ['sw', 'group:sw:vm', 'p', 'ap-1', 'ap-2', 'x', 'y']);
  assert.deepEqual(f.byId.get('group:sw:vm').members, ['a', 'b'], 'a cable plus a route to the same thing is still a leaf');
});

test('foldLeaves {open}: a group pressed open keeps its leaves as cards (2026-11-17)', () => {
  const g = buildGraph({
    nodes: [{ id: 'sw', kind: 'network' }, { id: 'a', kind: 'vm' }, { id: 'b', kind: 'vm' },
      { id: 'c', kind: 'physical' }, { id: 'd', kind: 'physical' }],
    cables: [{ id: '1', a: 'sw', b: 'a' }, { id: '2', a: 'sw', b: 'b' }, { id: '3', a: 'sw', b: 'c' }, { id: '4', a: 'sw', b: 'd' }],
  });
  const shut = foldLeaves(g, { limit: 2 });
  assert.deepEqual(shut.things.map((t) => t.id), ['sw', 'group:sw:vm', 'group:sw:physical']);
  const open = foldLeaves(g, { limit: 2, open: ['group:sw:vm'] });
  assert.deepEqual(open.things.map((t) => t.id), ['sw', 'a', 'b', 'group:sw:physical']);
  assert.ok(open.linkById.has('1') && open.linkById.has('2'), 'the open group keeps its cables');
  assert.ok(!open.linkById.has('fold:sw:vm'));
  assert.deepEqual(open.things.map((t) => t.order), [0, 1, 2, 3]);
  const all = foldLeaves(g, { limit: 2, open: new Set(['group:sw:vm', 'group:sw:physical']) });
  assert.equal(all, g, 'nothing left to fold: the same graph');
});

test('groupHolding names the group a folded thing is in', () => {
  const g = buildGraph({
    nodes: [{ id: 'sw', kind: 'network' }, { id: 'a', kind: 'vm' }, { id: 'b', kind: 'vm' }, { id: 'p', kind: 'printer' }],
    cables: [{ id: '1', a: 'sw', b: 'a' }, { id: '2', a: 'sw', b: 'b' }, { id: '3', a: 'sw', b: 'p' }],
  });
  const f = foldLeaves(g, { limit: 2 });
  assert.equal(groupHolding(f, 'a'), 'group:sw:vm');
  assert.equal(groupHolding(f, 'p'), null, 'a card of its own');
  assert.equal(groupHolding(f, 'sw'), null);
  assert.equal(groupHolding(g, 'a'), null, 'nothing is folded in an unfolded graph');
});

/* ── questions ────────────────────────────────────────────────────────────── */

test('pathToHead follows up to the head, with the links it hangs by', () => {
  const g = buildGraph(DEMO);
  assert.deepEqual(pathToHead(g, 'gpu-box'), {
    things: ['gpu-box', 'desk-switch', 'core-switch', 'gateway', 'fibre-line'],
    links: ['gpu-desk', 'desk-run', 'gw-trunk', 'wan-in'],
  });
  assert.deepEqual(pathToHead(g, 'fibre-line'), { things: ['fibre-line'], links: [] });
  assert.deepEqual(pathToHead(g, 'nas-2'), { things: [], links: [] });
  assert.deepEqual(pathToHead(g, 'nobody'), { things: [], links: [] });
  assert.deepEqual(pathToHead(g, undefined), { things: [], links: [] });
});

test('vlanList: the demo VLANs, named and hued by their zones, with what carries them', () => {
  const g = buildGraph(DEMO);
  const list = vlanList(g, DEMO.zones);
  assert.deepEqual(list.map((v) => v.vlan), [1, 10, 30, 33, 66, 90]);
  const v66 = list.find((v) => v.vlan === 66);
  assert.equal(v66.name, 'IoT');
  assert.equal(v66.hue, '#C06B62');
  assert.equal(v66.cables, 2, 'the trunk and the camera cable');
  // camera-hub (its zone, and the cable), gateway and core-switch (the trunk's ends)
  assert.equal(v66.things, 3);
  const v10 = list.find((v) => v.vlan === 10);
  assert.equal(v10.cables, 4, 'the trunk, the desk run and two desk cables');
  const extra = vlanList(buildGraph({ nodes: [{ id: 'a' }, { id: 'b' }], cables: [{ id: 'c', a: 'a', b: 'b', vlan: 77 }] }), []);
  assert.deepEqual(extra, [{ vlan: 77, name: null, hue: null, cables: 1, things: 2 }]);
  assert.deepEqual(vlanList(g, [{ id: 'z', name: 'Odd', vlan: '\u2014', hue: '#000' }]).map((v) => v.vlan), [1, 10, 30, 33, 66, 90]);
});

test('carries and onVlan light the cables and things of a VLAN', () => {
  const g = buildGraph(DEMO);
  const trunk = linkOf(g, 'gw-trunk');
  assert.equal(carries(trunk, 1), true);
  assert.equal(carries(trunk, '90'), true);
  assert.equal(carries(trunk, 20), false);
  assert.equal(carries(linkOf(g, 'nas-fibre'), 33), true);
  assert.equal(carries(g.links.find((l) => l.layer === 'route'), 33), false, 'a route carries no VLAN');
  assert.equal(carries(null, 1), false);
  assert.equal(carries(trunk, 'x'), false);
  assert.equal(onVlan(g, 'camera-hub', 66, DEMO.zones), true);
  assert.equal(onVlan(g, 'core-switch', 66, DEMO.zones), true, 'an end of the camera cable');
  assert.equal(onVlan(g, 'dc', 33, DEMO.zones), true, 'by its zone');
  assert.equal(onVlan(g, 'dc', 66, DEMO.zones), false);
  assert.equal(onVlan(g, 'desk-switch', 10, DEMO.zones), true);
  assert.equal(onVlan(g, 'nobody', 10, DEMO.zones), false);
  assert.equal(onVlan(g, 'dc', 33, undefined), false);
});

test('stripes: one hue for an access cable, one per VLAN for a trunk, none without a hue', () => {
  const g = buildGraph(DEMO);
  const hue = Object.fromEntries(DEMO.zones.map((z) => [z.vlan, z.hue]));
  assert.deepEqual(stripes(linkOf(g, 'camera-poe'), DEMO.zones), [hue[66]]);
  assert.deepEqual(stripes(linkOf(g, 'gw-trunk'), DEMO.zones), [hue[1], hue[10], hue[30], hue[33], hue[66], hue[90]]);
  assert.deepEqual(stripes(linkOf(g, 'hv-uplink'), DEMO.zones), [hue[33], hue[30], hue[90]], 'untagged first');
  assert.deepEqual(stripes(linkOf(g, 'wan-in'), DEMO.zones), []);
  assert.deepEqual(stripes({ vlan: 77 }, DEMO.zones), []);
  assert.deepEqual(stripes({ vlan: 10, tagged: [10, 66] }, DEMO.zones), [hue[10], hue[66]]);
  assert.deepEqual(stripes(linkOf(g, 'camera-poe'), null), []);
});

test('find looks in names, ids, addresses and ports', () => {
  const g = buildGraph(DEMO);
  assert.deepEqual(find(g, 'nas'), ['nas', 'nas-2']);
  assert.deepEqual(find(g, '  Second '), ['nas-2']);
  assert.deepEqual(find(g, '10.77.1.2'), ['core-switch']);
  assert.deepEqual(find(g, 'igc0'), ['gateway']);
  assert.deepEqual(find(g, 'sfp'), ['core-switch']);
  assert.deepEqual(find(g, 'desk'), ['desk-switch']);
  assert.deepEqual(find(g, ''), []);
  assert.deepEqual(find(g, '   '), []);
  assert.deepEqual(find(g, null), []);
  assert.deepEqual(find(g, '\u2014'), [], 'the no-address placeholder is not an address');
});

test('seen gives the cards that meet the box', () => {
  const positions = { a: { x: 0, y: 0 }, b: { x: 1000, y: 0 }, c: { x: 0, y: 1000 }, d: 'junk' };
  assert.deepEqual(seen(positions, { x: 0, y: 0, w: 500, h: 500 }), ['a']);
  assert.deepEqual(seen(positions, { x: CARD_W + 1, y: 0, w: 500, h: 500 }), []);
  assert.deepEqual(seen(positions, { x: CARD_W + 1, y: 0, w: 500, h: 500 }, 2), ['a']);
  assert.deepEqual(seen(positions, { x: -10, y: -10, w: 2000, h: 2000 }), ['a', 'b', 'c']);
  assert.deepEqual(seen(new Map(Object.entries(positions)), { x: 900, y: 0, w: 200, h: 10 }), ['b']);
  assert.deepEqual(seen(positions, null), []);
  const out = arrange(buildGraph(DEMO));
  assert.equal(seen(out.positions, { x: 0, y: 0, w: out.width, h: out.height }).length, Object.keys(out.positions).length);
});

test('connections: the demo, with blanks where there is no cable', () => {
  const g = buildGraph(DEMO);
  const rows = connections(g);
  const by = Object.fromEntries(rows.map((r) => [r.id, r]));
  assert.equal(rows.length, DEMO.nodes.length + DEMO.stubs.length);
  assert.deepEqual(by['core-switch'], {
    id: 'core-switch', name: 'CORE SWITCH', to: 'GATEWAY', toId: 'gateway', port: '24', farPort: 'igc1',
    vlan: 'U1 T10,30,33,66,90', poe: '', path: 'CORE SWITCH \u203a GATEWAY \u203a Fibre line in',
  });
  assert.equal(by['camera-hub'].vlan, 'U66');
  assert.equal(by['camera-hub'].poe, 12);
  assert.equal(by.hypervisor.vlan, 'U33 T30,90');
  assert.equal(by['gpu-box'].to, 'Desk switch');
  assert.equal(by['gpu-box'].farPort, '3');
  for (const id of ['dc', 'offsite', 'the-wild', 'nas-2', 'fibre-line']) {
    const { to, toId, port, farPort, vlan, poe, path } = by[id];
    assert.deepEqual({ to, toId, port, farPort, vlan, poe, path },
      { to: '', toId: '', port: '', farPort: '', vlan: '', poe: '', path: '' }, id);
  }
  const names = rows.map((r) => r.name.toLowerCase());
  assert.deepEqual(names, [...names].sort());
});

/* ── house rules ──────────────────────────────────────────────────────────── */

test('the model touches no DOM and imports nothing', () => {
  assert.ok(!SOURCE.includes('document.'), 'no document.');
  assert.ok(!SOURCE.includes('window.'), 'no window.');
  assert.ok(!/^\s*import\s/m.test(SOURCE), 'no imports');
  assert.ok(!SOURCE.includes('\u2014'), 'no em dash in its words');
});

/* ── the drawing's own sums (2026-11-17) ──────────────────────────────────── */

test('vlanLit: the things on a VLAN and the cables that carry it, in graph order', () => {
  const g = buildGraph(DEMO);
  const lit = vlanLit(g, 66, DEMO.zones);
  assert.deepEqual(lit.links, ['gw-trunk', 'camera-poe']);
  assert.ok(lit.things.includes('camera-hub') && lit.things.includes('core-switch') && lit.things.includes('gateway'));
  assert.ok(!lit.things.includes('nas'));
  assert.deepEqual(lit.things, g.things.map((t) => t.id).filter((id) => lit.things.includes(id)), 'graph order');
  assert.deepEqual(vlanLit(g, 'nope', DEMO.zones), { things: [], links: [] });
  assert.deepEqual(vlanLit(g, 4000, DEMO.zones), { things: [], links: [] });
});

test('pathMarks: the whole chain, or as far as the failed step', () => {
  const things = ['head', 'switch', 'host', 'guest'];
  const links = ['l0', 'l1', 'l2'];
  assert.deepEqual(pathMarks(things, links, null), { things, links, failedThing: null, failedLink: null });
  assert.deepEqual(pathMarks(things, links, 9), { things, links, failedThing: null, failedLink: null });
  assert.deepEqual(pathMarks(things, links, 2),
    { things: ['head', 'switch', 'host'], links: ['l0', 'l1'], failedThing: 'host', failedLink: 'l1' });
  assert.deepEqual(pathMarks(things, links, 0), { things: ['head'], links: [], failedThing: 'head', failedLink: null });
  assert.deepEqual(pathMarks(undefined, undefined, 0), { things: [], links: [], failedThing: null, failedLink: null });
});

test('the demo path to the head, head first, is what ?at= lights', () => {
  const g = buildGraph(DEMO);
  const up = pathToHead(g, 'camera-hub');
  const marks = pathMarks([...up.things].reverse(), [...up.links].reverse(), null);
  assert.deepEqual(marks.things, ['fibre-line', 'gateway', 'core-switch', 'camera-hub']);
  assert.deepEqual(marks.links, ['wan-in', 'gw-trunk', 'camera-poe']);
});

test('cableGeometry: rows join edge to edge, side by side joins side to side, lanes stand apart', () => {
  const top = { x: 0, y: 0 };
  const below = { x: 0, y: ROW };
  const v = cableGeometry(top, below);
  assert.equal(v.vertical, true);
  assert.deepEqual([v.x1, v.y1, v.x2, v.y2], [CARD_W / 2, CARD_H, CARD_W / 2, ROW]);
  assert.ok(v.c1y > v.y1 && v.c2y < v.y2, 'the curve leaves downward and arrives from above');
  const up = cableGeometry(below, top);
  assert.deepEqual([up.y1, up.y2], [ROW, CARD_H], 'drawn from the lower card it starts at its top edge');
  const h = cableGeometry({ x: 0, y: 0 }, { x: SLOT, y: 0 });
  assert.equal(h.vertical, false);
  assert.deepEqual([h.x1, h.y1, h.x2, h.y2], [CARD_W, CARD_H / 2, SLOT, CARD_H / 2]);
  const back = cableGeometry({ x: SLOT, y: 0 }, { x: 0, y: 0 });
  assert.deepEqual([back.x1, back.x2], [SLOT, CARD_W]);
  const l0 = cableGeometry(top, below, 0, 2);
  const l1 = cableGeometry(top, below, 1, 2);
  assert.equal(l1.x1 - l0.x1, LANE_GAP);
  assert.equal((l0.x1 + l1.x1) / 2, CARD_W / 2, 'two lanes sit either side of the middle');
  assert.equal(cableGeometry(top, below, 1, 3).x1, CARD_W / 2, 'the middle of three is the middle');
});

test('cablePath, pointOn and nearEnd', () => {
  const g = cableGeometry({ x: 0, y: 0 }, { x: 0, y: ROW });
  assert.equal(cablePath(g), 'M88 64C88 112 88 112 88 160');
  assert.deepEqual(pointOn(g, 0), { x: g.x1, y: g.y1 });
  assert.deepEqual(pointOn(g, 1), { x: g.x2, y: g.y2 });
  assert.equal(pointOn(g, 0.5).y, (g.y1 + g.y2) / 2);
  assert.equal(nearEnd(g, 16), 16 / 96);
  assert.equal(nearEnd(g, 1000), 1 / 3, 'never past a third');
  assert.equal(nearEnd({ x1: 0, y1: 0, x2: 0, y2: 0 }, 10), 0.5);
});

test('chipBox and clip size text without measuring it', () => {
  const b = chipBox('sfp1', 100, 50, 9);
  assert.equal(b.w, 4 * 9 * MONO_ADVANCE + 6);
  assert.equal(b.h, 13);
  assert.equal(b.x + b.w / 2, 100);
  assert.equal(b.y + b.h / 2, 50);
  assert.equal(chipBox('', 0, 0).w, 6);
  assert.equal(chipBox(undefined, 0, 0).w, 6);
  assert.equal(clip('core-switch', 20), 'core-switch');
  assert.equal(clip('a very long place name indeed', 10), 'a very lo…');
  assert.equal([...clip('a very long place name indeed', 10)].length, 10);
  assert.equal(clip(null, 3), '');
});

test('fitView fits the box, never closer than max, and always shows everything (2026-11-17)', () => {
  const v = fitView({ x: 0, y: 0, w: 1000, h: 500 }, 540, 290, { pad: 20 });
  assert.equal(v.k, 0.5);
  assert.deepEqual([v.x, v.y], [20, 20]);
  const small = fitView({ x: 100, y: 100, w: 10, h: 10 }, 800, 600);
  assert.equal(small.k, 1.25, 'a small map is not blown up');
  assert.equal(small.x + (100 + 5) * small.k, 400, 'and is centred');
  assert.deepEqual(fitView(null, 800, 600), { k: 1, x: 0, y: 0 });
  assert.deepEqual(fitView({ x: 0, y: 0, w: 5, h: 5 }, 0, 600), { k: 1, x: 0, y: 0 }, 'a hidden window');
  // far below the hand's limit, everything is still inside the window
  const shows = (b, w, h, pad) => {
    const f = fitView(b, w, h, { pad });
    assert.ok(f.k > 0, 'a zoom is never 0');
    const [x0, y0] = [b.x * f.k + f.x, b.y * f.k + f.y];
    const [x1, y1] = [(b.x + b.w) * f.k + f.x, (b.y + b.h) * f.k + f.y];
    assert.ok(x0 >= -1e-6 && y0 >= -1e-6 && x1 <= w + 1e-6 && y1 <= h + 1e-6, `${JSON.stringify(b)} in ${w} x ${h}: ${x0},${y0} to ${x1},${y1}`);
    return f;
  };
  assert.ok(shows({ x: 0, y: 0, w: 8064, h: 480 }, 800, 500, 36).k < MIN_ZOOM, 'one long row fits below MIN_ZOOM');
  assert.ok(shows({ x: -500, y: 200, w: 1e5, h: 3e4 }, 800, 500, 36).k < MIN_ZOOM);
  shows({ x: 0, y: 0, w: 2672, h: 864 }, 29, 400, 36);   // the sliver a narrow window gave the canvas
  shows({ x: 0, y: 0, w: 2672, h: 864 }, 10, 10, 36);
  assert.equal(fitView({ x: 0, y: 0, w: 1e9, h: 1e9 }, 800, 600).k, FIT_FLOOR, 'only a floor keeps it above 0');
});

test('zoomAt keeps the point under the pointer, centreOn and viewBox agree', () => {
  const v = { k: 1, x: 10, y: 20 };
  const z = zoomAt(v, 110, 120, 2);
  assert.equal(z.k, 2);
  assert.deepEqual([(110 - z.x) / z.k, (120 - z.y) / z.k], [100, 100], 'world point 100,100 stays under it');
  assert.equal(zoomAt(v, 0, 0, 1000).k, MAX_ZOOM);
  assert.equal(zoomAt(v, 0, 0, 1e-6).k, MIN_ZOOM);
  // a Fit below the hand's limit (2026-11-17): zooming out holds, zooming in moves
  const far = { k: 0.05, x: 0, y: 0 };
  assert.equal(zoomAt(far, 0, 0, 0.8).k, 0.05, 'no jump inward on the first wheel tick out');
  assert.ok(Math.abs(zoomAt(far, 0, 0, 1.25).k - 0.0625) < 1e-12, 'zooming in moves from where it is');
  assert.equal(zoomAt({ k: 0.12, x: 0, y: 0 }, 0, 0, 0.1, { min: 0.05 }).k, 0.05, 'the conductor may lower the floor to the fit');
  const c = centreOn({ k: 2, x: 0, y: 0 }, 50, 60, 400, 300);
  assert.deepEqual(c, { k: 2, x: 100, y: 30 });
  const box = viewBox(c, 400, 300);
  assert.deepEqual(box, { x: -50, y: -15, w: 200, h: 150 });
  assert.equal(box.x + box.w / 2, 50);
  assert.equal(box.y + box.h / 2, 60);
});

test('linkSeen: a cable crossing the window is drawn though both ends are off it', () => {
  const box = { x: 0, y: 0, w: 100, h: 100 };
  assert.equal(linkSeen({ x: -500, y: 20 }, { x: 500, y: 20 }, box), true);
  assert.equal(linkSeen({ x: 300, y: 300 }, { x: 600, y: 600 }, box), false);
  assert.equal(linkSeen({ x: 50, y: 50 }, { x: 900, y: 900 }, box), true);
  assert.equal(linkSeen(null, { x: 0, y: 0 }, box), false);
});

test('neighbour: the nearest card the arrow points to', () => {
  const pos = { a: { x: 0, y: 0 }, b: { x: SLOT, y: 0 }, c: { x: 2 * SLOT, y: 0 }, d: { x: SLOT, y: ROW }, e: { x: 0, y: ROW } };
  assert.equal(neighbour(pos, 'a', 'right'), 'b');
  assert.equal(neighbour(pos, 'c', 'left'), 'b');
  assert.equal(neighbour(pos, 'b', 'down'), 'd');
  assert.equal(neighbour(pos, 'd', 'up'), 'b');
  assert.equal(neighbour(pos, 'a', 'down'), 'e', 'straight down beats down and across');
  assert.equal(neighbour(pos, 'a', 'left'), null);
  assert.equal(neighbour(pos, 'a', 'sideways'), null);
  assert.equal(neighbour(pos, 'nobody', 'right'), null);
  assert.equal(neighbour(new Map(Object.entries(pos)), 'a', 'right'), 'b', 'a Map works too');
});

/* ── the polish pass (2026-11-17): cables spread, chips clear, text sized ─── */

/** No chip in a cableLayout meets another chip or any card. */
function assertChipsClear(graph, positions, layout) {
  const boxes = [];
  for (const [id, c] of layout) for (const k of ['a', 'b', 'mid']) if (c[k]) boxes.push([`${id}.${k}`, c[k].box]);
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      assert.ok(!boxesMeet(boxes[i][1], boxes[j][1]), `${boxes[i][0]} meets ${boxes[j][0]}`);
    }
    for (const t of graph.things) {
      const p = positions instanceof Map ? positions.get(t.id) : positions[t.id];
      if (p) assert.ok(!boxesMeet(boxes[i][1], cardBox(t, p)), `${boxes[i][0]} is on the card ${t.id}`);
    }
  }
  return boxes.length;
}

/** A switch under a gateway with `n` cables down to hosts, as a real rack has. */
function switchOf(n) {
  const nodes = [{ id: 'gw', kind: 'network' }, { id: 'sw', kind: 'network' }];
  const cables = [{ id: 'up', a: 'gw', a_port: 'igc1', b: 'sw', b_port: 'sfp+1', vlan: 1, tagged: [10, 20] }];
  for (let i = 0; i < n; i++) {
    nodes.push({ id: `h${i}` });
    cables.push({ id: `c${i}`, a: 'sw', a_port: i % 3 ? `${i + 1}` : `sfp${i}`, b: `h${i}`, b_port: 'eth0', vlan: 10, poe_w: i % 2 ? 15 : null });
  }
  return buildGraph({ nodes, cables });
}

/** A small seeded random number source, so a failure can be run again. */
function seeded(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; };
}

test('the shape arrange packs toward by default is 16:10', () => {
  assert.equal(ASPECT, 16 / 10);
});

test('spreadEnds: N cables on one edge leave from N points inside it, in far-end order', () => {
  for (const n of [1, 2, 3, 8, 24, 40]) {
    const nodes = [{ id: 'hub', kind: 'network' }];
    const cables = [];
    const positions = { hub: { x: 0, y: 0 } };
    for (let i = 0; i < n; i++) {
      nodes.push({ id: `f${i}` });
      // listed both ways round, the far cards in a scrambled order over three rows
      cables.push(i % 2 ? { id: `c${i}`, a: 'hub', b: `f${i}` } : { id: `c${i}`, a: `f${i}`, b: 'hub' });
      positions[`f${i}`] = { x: (((i * 7) % n) - n / 2) * SLOT, y: ROW * (1 + (i % 3)) };
    }
    const g = buildGraph({ nodes, cables });
    const ends = spreadEnds(g, positions);
    assert.equal(ends.size, n);
    const out = g.links.map((l) => {
      const hubIsA = l.a === 'hub';
      const geom = cableGeometry(positions[l.a], positions[l.b], l.lane, l.lanes, ends.get(l.id));
      return {
        off: hubIsA ? ends.get(l.id).a : ends.get(l.id).b,
        x: hubIsA ? geom.x1 : geom.x2, y: hubIsA ? geom.y1 : geom.y2,
        far: positions[hubIsA ? l.b : l.a].x,
      };
    });
    assert.equal(new Set(out.map((e) => e.x)).size, n, `${n} distinct points`);
    for (const e of out) {
      assert.equal(e.y, CARD_H, 'on the bottom edge');
      assert.ok(e.x >= EDGE_INSET - 1e-9 && e.x <= CARD_W - EDGE_INSET + 1e-9, `inside the edge: ${e.x}`);
      assert.ok(Math.abs(e.x - (CARD_W / 2 + e.off)) < 1e-9);
    }
    const byPoint = [...out].sort((p, q) => p.x - q.x).map((e) => e.far);
    assert.deepEqual(byPoint, [...byPoint].sort((p, q) => p - q), 'left to right as their far cards are');
    if (n === 1) assert.equal(out[0].off, 0, 'one cable leaves from the middle');
    if (n <= 12 && n > 1) {
      const xs = out.map((e) => e.x).sort((p, q) => p - q);
      assert.ok(Math.abs(xs[1] - xs[0] - LANE_GAP) < 1e-9, 'a few stand LANE_GAP apart');
    }
  }
});

test('spreadEnds: parallel cables keep their lanes, sides spread along the side', () => {
  const pos = { a: { x: 0, y: 0 }, b: { x: 0, y: ROW } };
  const g = buildGraph({
    nodes: [{ id: 'a', kind: 'network' }, { id: 'b' }],
    cables: [{ id: '1', a: 'a', b: 'b' }, { id: '2', a: 'b', b: 'a' }],
  });
  const ends = spreadEnds(g, pos);
  for (const l of g.links) {
    const spread = cableGeometry(pos[l.a], pos[l.b], l.lane, l.lanes, ends.get(l.id));
    const lane = cableGeometry(pos[l.a], pos[l.b], l.lane, l.lanes);
    assert.deepEqual([spread.x1, spread.x2], [lane.x1, lane.x2], `${l.id}: two parallel cables alone are drawn as their lanes were`);
  }
  // listed either way round, they do not cross: the one on the left at the top is on the left below
  const xs = g.links.map((l) => {
    const geom = cableGeometry(pos[l.a], pos[l.b], l.lane, l.lanes, ends.get(l.id));
    return l.a === 'a' ? [geom.x1, geom.x2] : [geom.x2, geom.x1];
  });
  assert.equal(Math.sign(xs[0][0] - xs[1][0]), Math.sign(xs[0][1] - xs[1][1]));
  // side by side, along the side, inside it
  const n = 9;
  const nodes = [{ id: 'hub', kind: 'network' }];
  const cables = [];
  const side = { hub: { x: 0, y: 0 } };
  for (let i = 0; i < n; i++) {
    nodes.push({ id: `r${i}` });
    cables.push({ id: `c${i}`, a: 'hub', b: `r${i}` });
    side[`r${i}`] = { x: SLOT * (1 + i), y: (((i * 5) % n) - 4) * 6 };   // all within a card's height
  }
  const spread = spreadEnds(buildGraph({ nodes, cables }), side);
  const ys = [...spread.values()].map((e) => CARD_H / 2 + e.a);
  assert.equal(new Set(ys).size, n);
  for (const y of ys) assert.ok(y >= SIDE_INSET - 1e-9 && y <= CARD_H - SIDE_INSET + 1e-9, `${y}`);
});

test('cableLayout: no chip meets another or a card, up to 30 cables on a switch', () => {
  for (let n = 1; n <= 30; n++) {
    const g = switchOf(n);
    const { positions } = arrange(g);
    const layout = cableLayout(g, positions);
    assert.equal(layout.size, n + 1);
    assertChipsClear(g, positions, layout);
    const down = [...layout].filter(([id]) => id !== 'up');
    const atSwitch = down.filter(([, c]) => c.a).length;
    assert.equal(down.filter(([, c]) => c.b).length, n, 'every host keeps its own port chip');
    assert.equal(down.filter(([, c]) => c.mid).length, n, 'every cable keeps its VLAN and watts');
    if (n <= 12) assert.equal(atSwitch, n, `${n} cables: every chip at the switch`);
    else assert.ok(atSwitch >= 12, `${n} cables: ${atSwitch} chips at the switch`);
    // nearer cables are tried first, so the nearest seven always keep theirs
    const reach = (id) => Math.abs(positions[g.linkById.get(id).b].x - positions.sw.x);
    const nearest = [...down].sort((p, q) => reach(p[0]) - reach(q[0])).slice(0, 7);
    assert.ok(nearest.every(([, c]) => c.a), `${n} cables: the nearest keep their chips`);
  }
});

test('cableLayout: chips stay clear and near their ends wherever the cards were dragged', () => {
  for (let seed = 1; seed <= 25; seed++) {
    const rand = seeded(seed);
    const nodes = [];
    const cables = [];
    const positions = {};
    for (let i = 0; i < 24; i++) {
      nodes.push({ id: `n${i}`, kind: i < 3 ? 'network' : 'physical' });
      positions[`n${i}`] = { x: Math.round(rand() * 1400), y: Math.round(rand() * 900) };
    }
    for (let i = 0; i < 40; i++) {
      const a = Math.floor(rand() * 24);
      const b = (a + 1 + Math.floor(rand() * 23)) % 24;
      cables.push({ id: `c${i}`, a: `n${a}`, a_port: `p${i}`, b: `n${b}`, b_port: rand() < 0.5 ? 'eth0' : `sfp+${i}`, vlan: 10 + (i % 3), poe_w: i % 4 ? null : 30 });
    }
    const g = buildGraph({ nodes, cables });
    const layout = cableLayout(g, positions);
    assertChipsClear(g, positions, layout);
    for (const c of layout.values()) {
      if (c.a) assert.ok(Math.hypot(c.a.x - c.geom.x1, c.a.y - c.geom.y1) <= PORT_REACH + 1, 'a port chip stays near its end');
      if (c.b) assert.ok(Math.hypot(c.b.x - c.geom.x2, c.b.y - c.geom.y2) <= PORT_REACH + 1);
    }
    assert.deepEqual(cableLayout(g, new Map(Object.entries(positions))), layout, 'the same picture every time, from a Map too');
  }
});

test('cableLayout: a label too long for its cable is left off; the demo is clear', () => {
  const g = buildGraph({
    nodes: [{ id: 'a', kind: 'network' }, { id: 'b' }, { id: 'c' }],
    cables: [
      { id: 'short', a: 'a', a_port: 'sfp+1', b: 'b', b_port: 'sfp+2', vlan: 1, tagged: [10, 20, 30, 40], poe_w: 30 },
      { id: 'long', a: 'a', a_port: '7', b: 'c', b_port: 'eth0', vlan: 1, tagged: [10, 20, 30, 40], poe_w: 30 },
    ],
  });
  const positions = { a: { x: 0, y: 0 }, b: { x: SLOT, y: 0 }, c: { x: 0, y: ROW } };
  const layout = cableLayout(g, positions);
  assert.equal(layout.get('short').mid, null, 'the gap between two cards side by side cannot hold it');
  assert.equal(layout.get('long').mid.text, 'U1 T10,20,30,40 · 30 W');
  assertChipsClear(g, positions, layout);
  const own = cableLayout(g, positions, { midText: (l) => `vlan ${l.vlan}` });
  assert.equal(own.get('long').mid.text, 'vlan 1', 'the page gives its own words');
  // the demo: every chip clear, every port shown, every cable with words keeps them
  const demo = buildGraph(DEMO);
  const at = arrange(demo).positions;
  const dl = cableLayout(demo, at);
  assertChipsClear(demo, at, dl);
  for (const [id, c] of dl) {
    const l = demo.linkById.get(id);
    assert.equal(Boolean(c.a), Boolean(l.aPort), `${id} a`);
    assert.equal(Boolean(c.b), Boolean(l.bPort), `${id} b`);
    if (vlanLabel(l) || l.poe) assert.ok(c.mid, `${id} keeps its label`);
  }
  // and 2,000 things lay their chips quickly
  const big = buildGraph(generated(2000, 40));
  const t0 = performance.now();
  cableLayout(big, arrange(big).positions);
  assert.ok(performance.now() - t0 < 1000);
});

test('textWidth and clipTo cut a line to the room it has', () => {
  assert.ok(textWidth('MMMM', 10) > textWidth('iiii', 10));
  assert.ok(textWidth('ab', 13, true) > textWidth('ab', 13));
  assert.equal(textWidth('', 10), 0);
  assert.equal(clipTo('vm', 100, 10.5), 'vm', 'what fits is kept whole');
  for (const room of [20, 40, 63, 90, 122]) {
    const cut = clipTo('physical · the hypervisor under the stairs', room, 10.5);
    assert.ok(textWidth(cut, 10.5) <= room, `${cut} fits ${room}`);
    assert.ok(cut.endsWith('…'));
  }
  assert.equal(clipTo('WWWW', 1, 10), '', 'no room, no text');
  assert.equal(clipTo(null, 50, 10), '');
});
