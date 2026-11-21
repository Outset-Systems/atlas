/* Saying where a thing stands, in plain node (2026-11-20): the record that
   decides it, what is sent to change it, and a drawn box's worth of them.

   Run:  node tests/test_location_set_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  boxOps, boxTargets, knownLocations, locationOps, locationTarget, placesInside, regionId, touchWords,
} from '../static/js/location-set-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const node = (id, kind = 'physical', more = {}) => ({ id, name: id.toUpperCase(), kind, ...more });

const HOUSE = {
  racks: [{ id: 'a', name: 'Rack A', location: 'Home office' }, { id: 'g', name: 'Garage rack' }],
  rack: [{ rack: 'a', u: 'U4', name: 'Hypervisor', node: 'hyper' }, { rack: 'g', u: 'U1', name: 'Backup', node: 'backup' }],
  nodes: [node('hyper'), node('backup'), node('pi', 'physical', { location: 'Living room' }), node('desk'),
    node('web', 'vm', { parent: 'hyper' }), node('nested', 'vm'), node('orphan', 'vm'), node('cloud', 'network')],
  vms: [{ id: 'web', host: 'hyper' }, { id: 'nested', host: 'web' }],
};
const BARE = { rack: [{ u: 'U1', name: 'Box', node: 'box' }], nodes: [node('box'), node('pi')] };

test('a place outside a rack is decided by its own record', () => {
  const t = locationTarget(HOUSE, 'Lab', { node: 'pi' });
  assert.deepEqual([t.kind, t.id, t.current, t.written, t.via], ['place', 'pi', 'Living room', 'Living room', '']);
  const d = locationTarget(HOUSE, 'Lab', { node: 'desk' });
  assert.deepEqual([d.kind, d.current, d.written], ['place', 'Lab', '']);
});

test('a place in a rack is decided by the rack', () => {
  const t = locationTarget(HOUSE, 'Lab', { node: 'hyper' });
  assert.deepEqual([t.kind, t.id, t.name, t.via, t.asked, t.current], ['rack', 'a', 'Rack A', 'rack', 'HYPER', 'Home office']);
  const g = locationTarget(HOUSE, 'Lab', { node: 'backup' });
  assert.deepEqual([g.kind, g.id, g.current, g.written], ['rack', 'g', 'Lab', '']);
});

test('a guest is decided by its host, followed up through a guest', () => {
  const t = locationTarget(HOUSE, 'Lab', { node: 'web' });
  assert.deepEqual([t.kind, t.id, t.via, t.asked, t.host], ['rack', 'a', 'host', 'WEB', 'HYPER']);
  assert.equal(locationTarget(HOUSE, 'Lab', { node: 'nested' }).id, 'a');
  const o = locationTarget(HOUSE, 'Lab', { node: 'orphan' });
  assert.deepEqual([o.kind, o.why], ['none', 'guest']);
  assert.equal(locationTarget(HOUSE, 'Lab', { node: 'nobody' }).why, 'missing');
});

test('a rack asked for by id, and the implied rack of a map that charts none', () => {
  assert.equal(locationTarget(HOUSE, 'Lab', { rack: 'g' }).name, 'Garage rack');
  const t = locationTarget(BARE, 'Lab', { rack: '' });
  assert.deepEqual([t.kind, t.id, t.implied, t.current], ['rack', '', true, 'Lab']);
  assert.equal(locationTarget(BARE, 'Lab', { node: 'box' }).implied, true);
  assert.equal(locationTarget(HOUSE, 'Lab', { rack: 'nope' }).kind, 'none');
});

test('the ops: a place, a rack, a clearing, and nothing when nothing changes', () => {
  const pi = locationTarget(HOUSE, 'Lab', { node: 'pi' });
  assert.deepEqual(locationOps(HOUSE, pi, '  Garage '), [{ op: 'upsert', section: 'nodes', id: 'pi', body: { location: 'Garage' } }]);
  assert.deepEqual(locationOps(HOUSE, pi, ''), [{ op: 'upsert', section: 'nodes', id: 'pi', body: { location: null } }]);
  assert.deepEqual(locationOps(HOUSE, pi, 'Living room'), []);
  const a = locationTarget(HOUSE, 'Lab', { node: 'hyper' });
  assert.deepEqual(locationOps(HOUSE, a, 'Basement'), [{ op: 'upsert', section: 'racks', id: 'a', body: { location: 'Basement' } }]);
  assert.deepEqual(locationOps(HOUSE, { kind: 'none' }, 'x'), []);
});

test('the implied rack is written as a first record, clear of a taken id', () => {
  const t = locationTarget(BARE, 'Lab', { rack: '' });
  assert.deepEqual(locationOps(BARE, t, 'Closet'), [{ op: 'insert', section: 'racks', body: { id: 'rack-a', name: 'Rack A', location: 'Closet' } }]);
  assert.deepEqual(locationOps(BARE, t, ''), []);
});

test('a box: each record once, the guests through their host, the hostless skipped', () => {
  const { targets, skipped } = boxTargets(HOUSE, 'Lab', ['hyper', 'web', 'pi', 'orphan', 'cloud', 'desk']);
  assert.deepEqual(targets.map((t) => `${t.kind}:${t.id}`), ['rack:a', 'place:pi', 'place:desk']);
  assert.deepEqual(targets[0].places, ['HYPER', 'WEB']);
  assert.deepEqual(skipped, ['ORPHAN', 'CLOUD']);   // a network place that names no location is not iron
  assert.equal(touchWords(targets), 'Rack A (the whole rack), PI and DESK');
  const ops = boxOps(HOUSE, targets, 'Home office');
  assert.deepEqual(ops.map((o) => o.id), ['pi', 'desk']);   // rack a already says it
  assert.equal(locationTarget(HOUSE, 'Lab', { node: 'cloud' }).kind, 'place');   // asked for by name, it may be told
});

test('what is inside a rectangle, a region id, and the names offered', () => {
  const spots = { a: { x: 10, y: 10 }, b: { x: 30, y: 30 }, c: { x: 20, y: 61 }, d: null };
  assert.deepEqual(placesInside(spots, { x: 10, y: 5, w: 20, h: 30 }), ['a', 'b']);
  assert.deepEqual(placesInside(spots, null), []);
  assert.equal(regionId('  Server Room! '), 'server-room');
  assert.equal(regionId('Server room', ['server-room', 'server-room-2']), 'server-room-3');
  assert.equal(regionId('***'), 'zoom-map');
  assert.deepEqual(knownLocations(HOUSE, 'Lab'), ['Home office', 'Lab', 'Living room']);
});

console.log(`\n${passed} passed`);
