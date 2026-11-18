/* TOPOLOGY, drawing's rules (2026-11-17), in plain node: the ids offered, the
   ports made on the spot, the routes with no cable, the one batch a cable's
   form saves, picking a cable, moving a card, and the saved layout laid over
   the canvas's own. Also: every word the view shows has its plain twin.

   Run:  node --test tests/test_topology_draw_model.mjs        (from Web/) */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { arrange, buildGraph } from '../static/js/topology-model.js';
import { cableGeometry } from '../static/js/topology-geometry.js';
import {
  HIT, ID_MAX, LIMIT, NUDGE,
  cableBody, cableIdFor, cableOps, cablesFromRoutes, changedCards, clampPoint, distanceToCurve,
  freeId, hitCable, newPortOps, nudge, parseTagged, portsOf, routesWithoutCable, slugify,
  stubIdFor, takenIds, withSaved,
} from '../static/js/topology-draw-model.js';

const here = (path) => new URL(path, import.meta.url);
const freeze = (v) => {
  if (v && typeof v === 'object') { Object.values(v).forEach(freeze); Object.freeze(v); }
  return v;
};

const DATA = freeze({
  nodes: [
    { id: 'gw', name: 'Gateway', kind: 'network' },
    { id: 'core', name: 'Core switch', kind: 'network' },
    { id: 'nas', name: 'NAS', kind: 'physical' },
    { id: 'cam', name: 'Camera', kind: 'physical' },
  ],
  stubs: [{ id: 'line-in', name: 'Line in', kind: 'internet' }],
  interfaces: [
    { device: 'core', name: '1' }, { device: 'core', name: '2' }, { device: 'core', name: '1' },
    { device: 'nas', name: 'eth0' }, { device: 'gw', name: ' ' },
  ],
  cables: [{ id: 'gw-to-core', a: 'gw', b: 'core', a_port: 'igc1', b_port: '1' }],
  routes: [
    { from: 'gw', to: 'core', kind: 'edge' },
    { from: 'core', to: 'nas', kind: 'vlan' },
    { from: 'nas', to: 'core', kind: 'vlan' },
    { from: 'core', to: 'cam', kind: 'mesh' },
    { from: 'cam', to: 'gone', kind: 'vlan' },
    { from: 'cam', to: 'cam', kind: 'vlan' },
  ],
});
const place = (id) => ({ id, type: 'place' });
const stub = (id) => ({ id, type: 'stub' });

/* ── ids ── */

test('slugify makes an id the schema takes', () => {
  assert.equal(slugify('Core Switch #2'), 'core-switch-2');
  assert.equal(slugify('  --Café line!  '), 'cafe-line');
  assert.equal(slugify('gw.lan_1'), 'gw.lan_1');
  assert.equal(slugify(''), '');
  assert.equal(slugify(null), '');
  assert.ok(slugify('x'.repeat(200)).length <= ID_MAX);
  for (const s of ['A b', '_x', '1-', 'é']) assert.match(slugify(s) || 'a', /^[a-z0-9][a-z0-9._-]*$/);
});

test('freeId adds -2, -3 until the id is free, and stays within the length', () => {
  assert.equal(freeId('gw-to-core', new Set()), 'gw-to-core');
  assert.equal(freeId('gw-to-core', new Set(['gw-to-core'])), 'gw-to-core-2');
  assert.equal(freeId('gw-to-core', ['gw-to-core', 'gw-to-core-2']), 'gw-to-core-3');
  const long = 'y'.repeat(ID_MAX);
  const id = freeId(long, new Set([long]));
  assert.ok(id.length <= ID_MAX && id.endsWith('-2'));
  assert.equal(freeId('', new Set()), 'item');
});

test('the id offered for a cable is made from its two ends', () => {
  const taken = takenIds(DATA, 'cables');
  assert.deepEqual([...taken], ['gw-to-core']);
  assert.equal(cableIdFor('gw', 'core', taken), 'gw-to-core-2');
  assert.equal(cableIdFor('core', 'nas', taken), 'core-to-nas');
  assert.equal(cableIdFor('line-in', 'gw', taken), 'line-in-to-gw');
});

test("a stub's id is free of every place's and stub's id", () => {
  const taken = new Set([...takenIds(DATA, 'nodes'), ...takenIds(DATA, 'stubs')]);
  assert.equal(stubIdFor('Line in', taken), 'line-in-2');
  assert.equal(stubIdFor('NAS', taken), 'nas-2');
  assert.equal(stubIdFor('Desk switch', taken), 'desk-switch');
  assert.equal(stubIdFor('!!!', taken), 'stub');
});

/* ── ports ── */

test("a place's ports are its interfaces' names, each once", () => {
  assert.deepEqual(portsOf(DATA, 'core'), ['1', '2']);
  assert.deepEqual(portsOf(DATA, 'gw'), []);
  assert.deepEqual(portsOf(DATA, 'line-in'), []);
  assert.deepEqual(portsOf({}, 'core'), []);
});

test('a typed port new to its place is made on the spot, once; a stub gets none', () => {
  assert.deepEqual(newPortOps(DATA, [place('core'), place('nas')], ['1', 'eth1']),
    [{ op: 'insert', section: 'interfaces', body: { device: 'nas', name: 'eth1' } }]);
  assert.deepEqual(newPortOps(DATA, [place('gw'), stub('line-in')], ['wan', 'lan']),
    [{ op: 'insert', section: 'interfaces', body: { device: 'gw', name: 'wan' } }]);
  // the same place at both ends with the same new port: one interface
  assert.equal(newPortOps(DATA, [place('cam'), place('cam')], ['p1', ' p1 ']).length, 1);
  assert.deepEqual(newPortOps(DATA, [place('core'), place('nas')], ['', '  ']), []);
});

/* ── routes with no cable ── */

test('every pair a route joins and no cable does, once, with its offered id', () => {
  const rows = routesWithoutCable(DATA);
  assert.deepEqual(rows.map((r) => [r.from, r.to, r.kind, r.id]), [
    ['core', 'nas', 'vlan', 'core-to-nas'],
    ['core', 'cam', 'mesh', 'core-to-cam'],
  ]);
  assert.equal(rows[0].fromName, 'Core switch');
  // a mesh says two places talk, not that a cable runs: listed, not ticked
  assert.deepEqual(rows.map((r) => r.wired), [true, false]);
  assert.deepEqual(routesWithoutCable({}), []);
});

test('ids offered for routes are free of each other too', () => {
  const data = { nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
    cables: [{ id: 'a-to-b-2', a: 'a', b: 'c' }],
    routes: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }] };
  const rows = routesWithoutCable(data);
  assert.deepEqual(rows.map((r) => r.id), ['a-to-b', 'b-to-c']);
  const clash = { ...data, cables: [{ id: 'a-to-b', a: 'x', b: 'y' }] };
  assert.deepEqual(routesWithoutCable(clash).map((r) => r.id), ['a-to-b-2', 'b-to-c']);
});

test('cables from routes: one assumed cable each, source hand, no ports, one batch', () => {
  const ops = cablesFromRoutes(routesWithoutCable(DATA).slice(0, 1));
  assert.deepEqual(ops, [{ op: 'insert', section: 'cables',
    body: { id: 'core-to-nas', a: 'core', b: 'nas', state: 'assumed', source: 'hand' } }]);
  assert.deepEqual(cablesFromRoutes([]), []);
});

/* ── a cable's form ── */

test('a new cable leaves out what is blank, reads numbers, and is marked by hand', () => {
  const { body, problems } = cableBody({
    id: 'line-in-to-gw', aPort: 'lan', bPort: ' wan ', kind: 'fibre', state: 'assumed',
    vlan: '10', tagged: '20, 30 40', poe: '12.5', speed: '', note: '  ',
  }, [stub('line-in'), place('gw')]);
  assert.deepEqual(problems, []);
  assert.deepEqual(body, { a_stub: 'line-in', b: 'gw', id: 'line-in-to-gw', a_port: 'lan', b_port: 'wan',
    kind: 'fibre', state: 'assumed', vlan: 10, tagged: [20, 30, 40], poe_w: 12.5, source: 'hand' });
});

test('words where a number belongs go to the server as typed, so it can say what is wrong', () => {
  const { body } = cableBody({ id: 'c', vlan: 'ten', tagged: '10, x', poe: 'lots' }, [place('a'), place('b')]);
  assert.deepEqual([body.vlan, body.tagged, body.poe_w], ['ten', [10, 'x'], 'lots']);
  assert.deepEqual(parseTagged('[10, 20]'), [10, 20]);
  assert.deepEqual(parseTagged(''), []);
});

test('the form says a missing id, a missing end and a cable to itself', () => {
  assert.deepEqual(cableBody({ id: '' }, [place('a'), place('b')]).problems, ['id']);
  assert.deepEqual(cableBody({ id: 'c' }, [place('a')]).problems, ['ends']);
  assert.deepEqual(cableBody({ id: 'c' }, [place('a'), place('a')]).problems, ['same']);
  // a place and a stub may share nothing, but are not the same end
  assert.deepEqual(cableBody({ id: 'c' }, [place('a'), stub('a')]).problems, []);
});

test('an edit sends what changed, null for what was cleared, and keeps its ends', () => {
  const before = { id: 'gw-to-core', a: 'gw', b: 'core', a_port: 'igc1', b_port: '1', vlan: 10,
    tagged: [20], note: 'old', source: 'unifi' };
  const { body } = cableBody({ id: 'gw-to-core', aPort: 'igc1', bPort: '2', vlan: '10', tagged: '',
    note: 'old', kind: 'copper', state: 'confirmed' }, [place('gw'), place('core')], before);
  // kind and state the cable leaves out read as the schema's defaults: not rewritten;
  // a person's change to a cable UniFi reported makes it theirs (source: hand)
  assert.deepEqual(body, { b_port: '2', tagged: null, source: 'hand' });
  const fibre = cableBody({ id: 'gw-to-core', aPort: 'igc1', bPort: '1', vlan: '10', tagged: '20', note: 'old',
    kind: 'fibre', state: 'confirmed' }, [place('gw'), place('core')], before);
  assert.deepEqual(fibre.body, { kind: 'fibre', source: 'hand' });
  const renamed = cableBody({ id: 'uplink', aPort: 'igc1', bPort: '1', vlan: '10', tagged: '20', note: 'old' },
    [place('gw'), place('core')], before);
  assert.deepEqual(renamed.body, { id: 'uplink', source: 'hand' });
});

test('ONE batch: the new ports first, then the cable', () => {
  const ends = [place('core'), place('nas')];
  const { ops, problems } = cableOps({ id: 'core-to-nas', aPort: '3', bPort: 'eth0' }, ends, DATA);
  assert.deepEqual(problems, []);
  assert.deepEqual(ops, [
    { op: 'insert', section: 'interfaces', body: { device: 'core', name: '3' } },
    { op: 'insert', section: 'cables', body: { a: 'core', b: 'nas', id: 'core-to-nas', a_port: '3', b_port: 'eth0', source: 'hand' } },
  ]);
  assert.deepEqual(cableOps({ id: '' }, ends, DATA), { ops: [], problems: ['id'] });
});

test('an edit is an upsert of that cable, and nothing at all when nothing changed', () => {
  const before = DATA.cables[0];
  const ends = [place('gw'), place('core')];
  const same = cableOps({ id: 'gw-to-core', aPort: 'igc1', bPort: '1' }, ends, DATA, before);
  assert.deepEqual(same, { ops: [], problems: [] });
  const moved = cableOps({ id: 'gw-to-core', aPort: 'igc1', bPort: '9' }, ends, DATA, before);
  // gw's igc1 is no interface yet, but it was not changed: only the new one is made
  assert.deepEqual(moved.ops, [
    { op: 'insert', section: 'interfaces', body: { device: 'core', name: '9' } },
    { op: 'upsert', section: 'cables', id: 'gw-to-core', body: { b_port: '9' } },
  ]);
});

/* ── picking a cable ── */

test('a press on or near a cable picks it; off it, nothing', () => {
  const g = cableGeometry({ x: 0, y: 0 }, { x: 0, y: 400 });
  assert.ok(distanceToCurve(g, { x: g.x1, y: g.y1 }) < 0.001);
  assert.ok(distanceToCurve(g, { x: g.x1 + 5, y: 200 }) <= 5.5);
  const list = [{ id: 'one', g }, { id: 'far', g: cableGeometry({ x: 1000, y: 0 }, { x: 1000, y: 400 }) }];
  assert.equal(hitCable(list, { x: g.x1 + 4, y: 200 }), 'one');
  assert.equal(hitCable(list, { x: g.x1 + HIT + 20, y: 200 }), null);
  assert.equal(hitCable([], { x: 0, y: 0 }), null);
  assert.equal(distanceToCurve(null, { x: 0, y: 0 }), Infinity);
  // two cables on the same line: the one drawn last, on top, wins
  assert.equal(hitCable([{ id: 'under', g }, { id: 'over', g }], { x: g.x1, y: 150 }), 'over');
});

/* ── moving cards ── */

test('a drag is kept where the server keeps it, to a tenth', () => {
  assert.deepEqual(clampPoint({ x: 12.345, y: -7.06 }), { x: 12.3, y: -7.1 });
  assert.deepEqual(clampPoint({ x: 5e9, y: -5e9 }), { x: LIMIT, y: -LIMIT });
  assert.deepEqual(clampPoint({ x: NaN, y: Infinity }), { x: 0, y: 0 });
  assert.deepEqual(clampPoint(null), { x: 0, y: 0 });
  assert.deepEqual(nudge({ x: 10, y: 10 }, 'left'), { x: 10 - NUDGE, y: 10 });
  assert.deepEqual(nudge({ x: 10, y: 10 }, 'down', 4), { x: 10, y: 14 });
  assert.deepEqual(nudge({ x: 10, y: 10 }, 'sideways'), { x: 10, y: 10 });
});

test('the saved layout laid over the canvas gives what arrange(graph, {saved}) gives', () => {
  const graph = buildGraph(DATA);
  const saved = { nas: { x: -500, y: 900.5 }, gone: { x: 1, y: 1 }, cam: { x: 'x', y: 1 } };
  const want = arrange(graph, { saved });
  const got = withSaved(arrange(graph), saved);
  assert.deepEqual({ ...got.positions }, { ...want.positions });
  assert.deepEqual([got.width, got.height, got.bounds], [want.width, want.height, want.bounds]);
  assert.equal(withSaved(null, saved), null);
  const plain = arrange(graph);
  const copy = JSON.stringify(plain);
  withSaved(plain, saved);
  assert.equal(JSON.stringify(plain), copy, 'the layout it is given is not changed');
});

test('a save sends each card moved or new, and null for each forgotten', () => {
  assert.deepEqual(changedCards({ a: { x: 1, y: 1 }, b: { x: 2, y: 2 } }, { a: { x: 1, y: 1 }, b: { x: 3, y: 2 }, c: { x: 0, y: 0 } }),
    { b: { x: 3, y: 2 }, c: { x: 0, y: 0 } });
  assert.deepEqual(changedCards({ a: { x: 1, y: 1 } }, {}), { a: null });
  assert.deepEqual(changedCards(null, null), {});
});

/* ── words ── */

test("every word the view shows has its plain twin in plain.json, and none is an em dash", () => {
  const src = readFileSync(here('../static/js/topology-state.js'), 'utf8');
  const words = Function(`return {${src.match(/export const TP_TEXT = \{([\s\S]*?)\n\};/)[1]}}`)();
  const plain = JSON.parse(readFileSync(here('../themes/plain.json'), 'utf8')).text;
  assert.ok(Object.keys(words).length > 60);
  for (const [k, v] of Object.entries(words)) {
    assert.ok(k.startsWith('tp_') || k === 'view_topology', k);
    assert.equal(plain[k], v, `plain.json text.${k}`);
    if (k.startsWith('tp_draw') || k.startsWith('tp_cable') || k.startsWith('tp_routes')) {
      assert.ok(!v.includes('—'), `${k} has an em dash`);
    }
  }
});

test('the drawing writes only through the two doors it is allowed', () => {
  const src = readFileSync(here('../static/js/topology-draw-model.js'), 'utf8');
  for (const word of ['postJSON', 'WRITE_HEADERS', 'admin/ops', 'fetch(']) assert.ok(!src.includes(word), word);
});

test('a person who changes a cable a connection reported makes it theirs', () => {
  const ends = [{ id: 'core', type: 'place' }, { id: 'nas', type: 'place' }];
  const before = { id: 'core.8--nas', a: 'core', a_port: '8', b: 'nas', source: 'unifi', vlan: 10 };
  const same = cableBody({ id: 'core.8--nas', aPort: '8', vlan: '10' }, ends, before);
  assert.deepEqual(same.body, {}, 'a save that changes nothing leaves the source alone');
  const moved = cableBody({ id: 'core.8--nas', aPort: '12', vlan: '10' }, ends, before);
  assert.deepEqual(moved.body, { a_port: '12', source: 'hand' });
  const mine = cableBody({ id: 'x', aPort: '12' }, ends, { id: 'x', a: 'core', a_port: '8', b: 'nas', source: 'hand' });
  assert.deepEqual(mine.body, { a_port: '12' }, 'a hand cable needs no mark');
  const bare = cableBody({ id: 'x', aPort: '12' }, ends, { id: 'x', a: 'core', a_port: '8', b: 'nas' });
  assert.deepEqual(bare.body, { a_port: '12' }, 'no source reads as hand already');
});
test('a port typed in another case is the port the place already has', () => {
  const data = { nodes: [{ id: 'sw' }, { id: 'pc' }], interfaces: [{ device: 'sw', name: 'Eth1' }] };
  const ends = [{ id: 'sw', type: 'place' }, { id: 'pc', type: 'place' }];
  assert.deepEqual(newPortOps(data, ends, ['eth1', 'en0']),
    [{ op: 'insert', section: 'interfaces', body: { device: 'pc', name: 'en0' } }]);
});
