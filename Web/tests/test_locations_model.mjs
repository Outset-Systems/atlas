/* Where the hardware stands, in plain node (2026-11-20): the one notion of a
   location that HARDWARE and RESOURCES share.

   Run:  node tests/test_locations_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { locKey, locationByKey, looseAt, racksAt, whereabouts } from '../static/js/locations-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const node = (id, kind = 'physical', more = {}) => ({ id, name: id.toUpperCase(), kind, ...more });
const ids = (list) => list.map((n) => n.id);

/* a house: two racks in the office, one in the garage, and things on shelves */
const HOUSE = {
  racks: [
    { id: 'a', name: 'Rack A', location: 'Home office' },
    { id: 'b', name: 'Rack B', location: 'home  Office ' },
    { id: 'g', name: 'Garage rack', location: 'Garage' },
  ],
  rack: [
    { rack: 'a', u: 'U4', name: 'Hypervisor', node: 'hyper' },
    { u: 'U3', name: 'Switch', node: 'switch' },             // no rack named: the first
    { rack: 'gone', u: 'U2', name: 'Old box', node: 'old' }, // an unknown rack: the first
    { rack: 'b', u: 'U1', name: 'Patch panel' },             // nothing on the map
    { rack: 'g', u: 'U1', name: 'Backup box', node: 'backup' },
  ],
  rack_rear: [{ rack: 'g', name: 'UPS', node: 'ups' }, { name: 'PDU' }],
  nodes: [
    node('hyper'), node('switch', 'network'), node('old'), node('backup'), node('ups', 'network'),
    node('pi', 'physical', { location: 'Living room' }),
    node('desk'),                                            // physical, says nothing
    node('ap', 'network', { location: 'living ROOM' }),
    node('internet', 'network'),                             // an idea, not a box
    node('mystery', 'unknown'),
    node('web', 'vm', { parent: 'hyper' }),
    node('db', 'vm'),
    node('nested', 'vm'),
    node('lost', 'vm'),
  ],
  vms: [{ id: 'db', host: 'backup' }, { id: 'nested', host: 'db' }, { id: 'lost', host: 'nowhere' }],
};

test('one name however it is typed', () => {
  assert.equal(locKey('  Home   Office '), 'home office');
  assert.equal(locKey('HOME OFFICE'), locKey('home office'));
  for (const none of ['', '   ', null, undefined]) assert.equal(locKey(none), '');
});

test('the locations, in the map\'s order, each spelt as first met', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  assert.deepEqual(w.list.map((l) => [l.key, l.name]), [
    ['home office', 'Home office'], ['garage', 'Garage'], ['living room', 'Living room'], ['home lab', 'Home lab'],
  ]);
  assert.deepEqual(w.list.map((l) => ids(l.racks)), [['a', 'b'], ['g'], [], []]);
});

test('what is in a rack, front or rear, is where the rack is', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  for (const id of ['hyper', 'switch', 'old']) assert.equal(w.ofNode.get(id), 'home office', id);
  for (const id of ['backup', 'ups']) assert.equal(w.ofNode.get(id), 'garage', id);
  assert.deepEqual([...w.racked].sort(), ['backup', 'hyper', 'old', 'switch', 'ups']);
});

test('outside a rack: a physical machine always, anything else only when it says where', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  const loose = Object.fromEntries(w.list.map((l) => [l.key, ids(l.loose)]));
  assert.deepEqual(loose, { 'home office': [], garage: [], 'living room': ['pi', 'ap'], 'home lab': ['desk'] });
  // the internet and an unknown thing that says nothing are nowhere, not on a shelf
  for (const id of ['internet', 'mystery']) assert.equal(w.ofNode.has(id), false, id);
});

test('a guest is never hardware, and is where its host is', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  assert.deepEqual([...w.guests].sort(), ['db', 'lost', 'nested', 'web']);
  assert.equal(w.ofNode.get('web'), 'home office');     // by its parent
  assert.equal(w.ofNode.get('db'), 'garage');           // by vms.host
  assert.equal(w.ofNode.get('nested'), 'garage');       // a guest's guest: followed up
  assert.equal(w.ofNode.has('lost'), false);            // its host is not on the map
  for (const l of w.list) for (const n of l.loose) assert.ok(!w.guests.has(n.id), n.id);
});

test('every machine is listed exactly once', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  const seen = [...w.racked, ...w.list.flatMap((l) => ids(l.loose))];
  assert.equal(new Set(seen).size, seen.length);
  assert.deepEqual(seen.sort(), ['ap', 'backup', 'desk', 'hyper', 'old', 'pi', 'switch', 'ups']);
});

test('a lab that wrote nothing has one location and the one rack it always had', () => {
  const w = whereabouts({ nodes: [node('box'), node('guest', 'vm', { parent: 'box' })],
                          rack: [{ u: 'U1', name: 'Box', node: 'box' }] }, 'Home lab');
  assert.deepEqual(w.list.map((l) => [l.key, l.name, ids(l.racks), ids(l.loose)]),
    [['home lab', 'Home lab', [''], []]]);
  assert.equal(w.ofNode.get('box'), 'home lab');
  assert.equal(w.ofNode.get('guest'), 'home lab');
  // no theme word either: still one location, with an empty name
  const bare = whereabouts({ nodes: [node('box')] });
  assert.deepEqual(bare.list.map((l) => [l.key, l.name, ids(l.loose)]), [['', '', ['box']]]);
  for (const junk of [null, undefined, 7, 'x', {}, { nodes: 'no', rack: {}, vms: 3 }]) {
    assert.equal(whereabouts(junk, 'Home lab').list.length, 1, String(junk));
  }
});

test('one location, or everywhere', () => {
  const w = whereabouts(HOUSE, 'Home lab');
  assert.equal(locationByKey(w, 'GARAGE ').key, 'garage');
  for (const all of ['', null, undefined, 'the moon']) assert.equal(locationByKey(w, all), null);
  assert.deepEqual(ids(racksAt(w, locationByKey(w, 'home office'))), ['a', 'b']);
  assert.deepEqual(ids(racksAt(w, null)), ['a', 'b', 'g']);
  assert.deepEqual(looseAt(w, locationByKey(w, 'living room')).map((x) => x.node.id), ['pi', 'ap']);
  assert.deepEqual(looseAt(w, null).map((x) => [x.node.id, x.location.key]),
    [['pi', 'living room'], ['ap', 'living room'], ['desk', 'home lab']]);
});

{
  const { rackable } = await import('../static/js/locations-model.js');
  test('what could be put in a rack: not a guest, not racked already, machines first', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    assert.deepEqual(ids(rackable(HOUSE, w)), ['pi', 'desk', 'ap', 'internet', 'mystery']);
    assert.deepEqual(rackable(null, whereabouts(null)), []);
  });
}

console.log(`\nlocations-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
