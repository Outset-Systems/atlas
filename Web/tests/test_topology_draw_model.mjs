/* TOPOLOGY, drawing's rules (2026-11-17), in plain node: the ids offered, the
   ports made on the spot, the routes with no cable, the one batch a cable's
   form saves, picking a cable, moving a card, the saved layout laid over
   the canvas's own, and the order the layout's saves and reads are kept in.
   Also: every word the view shows has its plain twin.

   Run:  node --test tests/test_topology_draw_model.mjs        (from Web/) */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { arrange, buildGraph } from '../static/js/topology-model.js';
import { cableGeometry } from '../static/js/topology-geometry.js';
import {
  HIT, ID_MAX, LIMIT, NUDGE,
  cableBody, cableIdFor, cableOps, cablesFromRoutes, changedCards, clampPoint, distanceToCurve,
  freeId, hitCable, layoutQueue, newPortOps, nudge, parseTagged, portsOf, routesWithoutCable, slugify,
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

test('digits too many to be a number stay words: never Infinity, which is sent as null', () => {
  const ends = [place('a'), place('b')];
  const huge = '9'.repeat(400);
  for (const typed of [huge, `${huge}.5`, 'NaN', 'Infinity', '-Infinity', '1e999']) {
    const fresh = cableBody({ id: 'c', poe: typed, vlan: typed, tagged: typed }, ends).body;
    assert.deepEqual([fresh.poe_w, fresh.vlan, fresh.tagged], [typed, typed, [typed]], typed.slice(0, 12));
    // what is sent is what was made: nothing in it turns to null on the way
    assert.deepEqual(JSON.parse(JSON.stringify(fresh)), fresh);
    // an edit sends the words for the server to refuse, and never clears the field
    const edit = cableBody({ id: 'c', poe: typed }, ends, { id: 'c', a: 'a', b: 'b', poe_w: 15 }).body;
    assert.deepEqual(edit, { poe_w: typed });
  }
  // every number the form makes is a finite one
  const seen = [];
  JSON.stringify(cableBody({ id: 'c', poe: '15.4', vlan: '4094', tagged: '1 2' }, ends).body,
    (k, v) => { if (typeof v === 'number') seen.push(v); return v; });
  assert.deepEqual(seen.sort((a, b) => a - b), [1, 2, 15.4, 4094]);
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

/* ── the layout's saves and reads, in order ── */

const at = (x, y = 0) => ({ x, y });

test('one save is out at a time, and what is moved meanwhile goes when it comes back', () => {
  const q = layoutQueue();
  assert.equal(q.take(), null, 'nothing waits');
  assert.equal(q.move('a', at(1)), true);
  assert.equal(q.waiting, true);
  assert.deepEqual(q.take(), { cards: { a: at(1) }, expect: null });
  assert.equal(q.busy, true);
  // moved while that save is out: noted, not sent
  q.move('b', at(2));
  assert.equal(q.take(), null, 'a second save never goes while the first is out');
  assert.equal(q.done('saved', 's1'), true, 'moves made meanwhile wait: they may go at once');
  assert.equal(q.stamp, 's1');
  assert.deepEqual(q.take(), { cards: { b: at(2) }, expect: 's1' });
  assert.equal(q.done('saved', 's2'), false, 'nothing more waits');
  assert.equal(q.busy, false);
  assert.equal(q.waiting, false);
  // an answer with no stamp keeps the one it had; an answer to nothing is nothing
  q.move('a', at(3));
  q.take();
  q.done('saved', undefined);
  assert.equal(q.stamp, 's2');
  assert.equal(q.done('saved', 'zz'), false);
  assert.equal(q.stamp, 's2');
});

test('a card moved again while its save is out is sent once more, where it was put last', () => {
  const q = layoutQueue();
  q.move('a', at(1));
  q.move('a', at(2));
  assert.deepEqual(q.take().cards, { a: at(2) }, 'moved twice before it went: once, the last place');
  q.move('a', at(3));
  q.move('b', at(9));
  q.move('a', at(4));
  q.done('saved', 's1');
  // the older places (1, 2, 3) are never sent after the newer one
  assert.deepEqual(q.take(), { cards: { a: at(4), b: at(9) }, expect: 's1' });
  // what was handed over is not changed by a later move
  q.done('saved', 's2');
  q.move('a', at(5));
  const batch = q.take();
  q.move('a', at(6));
  assert.deepEqual(batch.cards, { a: at(5) });
});

test('a move that is not a place on the canvas is not kept', () => {
  const q = layoutQueue();
  for (const bad of [at(NaN), at(1, Infinity), { x: '1', y: 2 }, null, undefined, 'x', [1, 2]]) {
    assert.equal(q.move('a', bad), false);
  }
  assert.equal(q.move('', at(1)), false);
  assert.equal(q.move(7, at(1)), false);
  assert.equal(q.waiting, false);
  assert.equal(q.take(), null);
});

test('a save refused as stale drops its own batch and keeps what was moved meanwhile', () => {
  const q = layoutQueue();
  q.land(q.read(), { cards: { a: at(0), z: at(50) }, stamp: 's0' });
  q.move('a', at(1));
  assert.deepEqual(q.take(), { cards: { a: at(1) }, expect: 's0' });
  q.move('b', at(2));                       // while the save is out
  assert.equal(q.done('stale'), false, 'nothing goes until the layout is read again');
  assert.equal(q.busy, true);
  assert.equal(q.waiting, true, 'the move made meanwhile is still there');
  assert.equal(q.take(), null);
  // the layout read again: someone else moved a and z; our later move lies over it
  const ticket = q.read();
  q.move('c', at(3));                       // and one made during the read
  const got = q.land(ticket, { cards: { a: at(70), z: at(80) }, stamp: 's9' });
  assert.deepEqual(got, { cards: { a: at(70), z: at(80), b: at(2), c: at(3) } });
  assert.equal(q.busy, false);
  // and goes with the stamp just read; the refused move of a does not
  assert.deepEqual(q.take(), { cards: { b: at(2), c: at(3) }, expect: 's9' });
});

test('after a stale refusal a read that fails changes no stamp and sends nothing', () => {
  const q = layoutQueue();
  q.land(q.read(), { cards: {}, stamp: 's0' });
  q.move('a', at(1));
  q.take();
  q.move('b', at(2));
  q.done('stale');
  assert.equal(q.land(q.read(), null), null);
  assert.equal(q.stamp, 's0', 'a read that failed changes no stamp');
  assert.equal(q.busy, true, 'held until a read lands (2026-11-18: it once let the save go, to be refused and read again without end)');
  assert.equal(q.take(), null);
});

test('a save that got no answer goes back under what was moved meanwhile; a refused one is dropped', () => {
  const q = layoutQueue();
  q.move('a', at(1));
  q.move('b', at(1));
  q.take();
  assert.equal(q.done('failed'), false, 'it is never sent again by itself');
  assert.equal(q.waiting, true);
  q.move('a', at(2));
  assert.deepEqual(q.take().cards, { a: at(2), b: at(1) }, 'with the next save, the newer place over it');
  q.move('c', at(3));                       // while that one is out
  assert.equal(q.done('failed'), true, 'the move made meanwhile may go');
  assert.deepEqual(q.take().cards, { a: at(2), b: at(1), c: at(3) });
  q.move('d', at(4));
  assert.equal(q.done('refused'), true);
  assert.deepEqual(q.take().cards, { d: at(4) }, 'a refused batch is not sent again');
  assert.equal(q.done('refused'), false);
  assert.equal(q.waiting, false);
});

test('Re-arrange waits its turn, and nothing older is sent after it', () => {
  const q = layoutQueue();
  q.land(q.read(), { cards: { a: at(0) }, stamp: 's0' });
  q.move('a', at(1));
  q.take();
  q.move('b', at(2));                       // moved while the save is out ...
  q.clear();                                // ... then Re-arrange: that move goes with the rest
  assert.equal(q.take(), null, 'not while a save is out');
  assert.equal(q.done('saved', 's1'), true);
  assert.deepEqual(q.take(), { cards: {}, replace: true, expect: 's1' });
  assert.equal(q.done('saved', 's2'), false);
  // a card moved after Re-arrange and before it is sent goes in the same save
  q.clear();
  q.move('c', at(3));
  assert.deepEqual(q.take(), { cards: { c: at(3) }, replace: true, expect: 's2' });
  // that save gets no answer: it is sent again whole, still a Re-arrange
  q.move('d', at(4));
  q.done('failed');
  assert.deepEqual(q.take(), { cards: { c: at(3), d: at(4) }, replace: true, expect: 's2' });
  // a save with no answer, and Re-arrange pressed meanwhile: its cards are not brought back
  q.done('saved', 's3');
  q.move('e', at(5));
  q.take();
  q.clear();
  assert.equal(q.done('failed'), true);
  assert.deepEqual(q.take(), { cards: {}, replace: true, expect: 's3' });
});

test('a read that comes back after a move lays the move over what it read', () => {
  const q = layoutQueue();
  const ticket = q.read();
  q.move('a', at(5));                       // dragged before the first read came back
  const got = q.land(ticket, { cards: { a: at(1), b: at(2) }, stamp: 's1' });
  assert.deepEqual(got, { cards: { a: at(5), b: at(2) } }, 'the newer place is not overwritten');
  assert.equal(q.stamp, 's1');
  assert.equal(q.owed, false);
  assert.deepEqual(q.take(), { cards: { a: at(5) }, expect: 's1' });
  // after Re-arrange and before it is sent, what the server still holds is not laid
  q.done('saved', 's2');
  q.clear();
  q.move('c', at(3));
  assert.deepEqual(q.land(q.read(), { cards: { a: at(5), b: at(2) }, stamp: 's2' }), { cards: { c: at(3) } });
  // a read with no cards and no stamp reads as it did
  const bare = layoutQueue();
  assert.deepEqual(bare.land(bare.read(), {}), { cards: {} });
  assert.equal(bare.stamp, null);
});

test('a read that crossed a save is not laid, and is owed again once nothing is out', () => {
  // the save went out and came back while the read was on its way
  let q = layoutQueue();
  q.land(q.read(), { cards: { a: at(0) }, stamp: 's0' });
  let ticket = q.read();                    // reads the layout as it was
  q.move('a', at(1));
  q.take();
  q.done('saved', 's1');                    // the newer place is saved
  assert.equal(q.land(ticket, { cards: { a: at(0) }, stamp: 's0' }), null);
  assert.equal(q.stamp, 's1', 'the older stamp is not taken either');
  assert.equal(q.owed, true);
  assert.deepEqual(q.land(q.read(), { cards: { a: at(1) }, stamp: 's1' }), { cards: { a: at(1) } });
  assert.equal(q.owed, false);

  // the save was out when the read began (sent on leaving the view) and is back before it
  q = layoutQueue();
  q.move('a', at(1));
  q.take();
  ticket = q.read();
  q.done('saved', 's1');
  assert.equal(q.land(ticket, { cards: {}, stamp: 's0' }), null);
  assert.equal(q.stamp, 's1');
  assert.equal(q.owed, true);

  // the save is still out when the read comes back: owed only once it is answered
  q = layoutQueue();
  ticket = q.read();
  q.move('a', at(1));
  q.take();
  assert.equal(q.land(ticket, { cards: {}, stamp: 's0' }), null);
  assert.equal(q.stamp, null);
  assert.equal(q.owed, false, 'not while the save is out');
  q.done('saved', 's1');
  assert.equal(q.owed, true);
  // starting the read again is what settles it
  q.read();
  assert.equal(q.owed, false);
});

test('of two reads on their way, only the one started last is laid', () => {
  const q = layoutQueue();
  const first = q.read();
  const second = q.read();
  assert.deepEqual(q.land(second, { cards: { a: at(2) }, stamp: 's2' }), { cards: { a: at(2) } });
  assert.equal(q.land(first, { cards: { a: at(1) }, stamp: 's1' }), null, 'the older answer came last');
  assert.equal(q.stamp, 's2');
  assert.equal(q.owed, false, 'nothing to read again: the later read answered');
  // the other way round: the older one first
  const third = q.read();
  const fourth = q.read();
  assert.equal(q.land(third, { cards: {}, stamp: 's3' }), null);
  assert.deepEqual(q.land(fourth, { cards: { a: at(4) }, stamp: 's4' }), { cards: { a: at(4) } });
  assert.equal(q.stamp, 's4');
  // a ticket that is not one, and a read that failed
  assert.equal(q.land(null, { cards: {}, stamp: 'x' }), null);
  assert.equal(q.land(q.read(), null), null);
  assert.equal(q.stamp, 's4');
});

test('the drawing sends the layout from one place, in the order the queue keeps', () => {
  const code = readFileSync(here('../static/js/topology-draw.js'), 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
  assert.equal(code.match(/postJSON\(/g).length, 1, 'one save, so one at a time');
  assert.match(code, /const batch = Q\.take\(\);\n\s*if \(!batch\) return;/);
  assert.match(code, /await postJSON\(LAYOUT, batch, \{ keepalive: true \}\)/);
  assert.equal(code.match(/\bfetch\(/g).length, 1, 'one read');
  assert.match(code, /const ticket = Q\.read\(\);[\s\S]*?const got = Q\.land\(ticket, body\);/);
  // nothing keeps a stamp or a list of moves of its own beside the queue
  for (const word of ['S.pending', 'S.stamp', 'S.saving']) assert.ok(!code.includes(word), word);
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

test('layoutQueue: a stale save whose re-read fails stays held, so nothing loops on the old stamp', () => {
  const q = layoutQueue();
  q.land(q.read(), { cards: {}, stamp: 's0' });
  q.move('a', { x: 10, y: 10 });
  assert.equal(q.take().expect, 's0');
  q.move('b', { x: 20, y: 20 });          // moved while the save was out
  assert.equal(q.done('stale'), false, 'nothing more goes until a read lands');
  assert.equal(q.stale, true);
  assert.equal(q.land(q.read(), null), null, 'the re-read failed');
  assert.equal(q.stale, true, 'still held');
  assert.equal(q.take(), null, 'and nothing is sent on the old stamp');
  assert.equal(q.waiting, true, 'the later move still waits');
  const got = q.land(q.read(), { cards: { c: { x: 1, y: 1 } }, stamp: 's1' });
  assert.deepEqual(got.cards, { c: { x: 1, y: 1 }, b: { x: 20, y: 20 } });
  assert.equal(q.stale, false);
  assert.deepEqual(q.take(), { cards: { b: { x: 20, y: 20 } }, expect: 's1' });
});
