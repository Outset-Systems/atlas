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

{
  const { placesFor } = await import('../static/js/locations-model.js');
  test('a location\'s topology: what is there, its guests, and what is at no location', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    // every place when no location is asked for
    assert.equal(placesFor(w, null, HOUSE.nodes).length, HOUSE.nodes.length);
    // the garage: its rack's machines, the guests on them, and the placeless
    // (the internet, an unknown thing, a guest whose host is not on the map)
    assert.deepEqual(ids(placesFor(w, locationByKey(w, 'garage'), HOUSE.nodes)),
      ['backup', 'ups', 'internet', 'mystery', 'db', 'nested', 'lost']);
    assert.deepEqual(ids(placesFor(w, locationByKey(w, 'living room'), HOUSE.nodes)),
      ['pi', 'ap', 'internet', 'mystery', 'lost']);
    // nothing of another location leaks in
    const office = ids(placesFor(w, locationByKey(w, 'home office'), HOUSE.nodes));
    for (const other of ['backup', 'ups', 'pi', 'ap', 'desk', 'db']) assert.ok(!office.includes(other), other);
    assert.deepEqual(placesFor(w, null, null), []);
  });

  test('a route\'s next stop elsewhere is drawn with the location, and known as a visitor', async () => {
    const { awayFrom } = await import('../static/js/locations-model.js');
    const w = whereabouts(HOUSE, 'Home lab');
    const routes = [{ from: 'pi', to: 'switch' }, { from: 'backup', to: 'ap' }, { from: 'hyper', to: 'old' },
                    { from: 'internet', to: 'switch' }, null];
    const room = locationByKey(w, 'living room');
    const drawn = placesFor(w, room, HOUSE.nodes, routes);
    // the switch (home office) and the backup box (garage) are each one hop from the room
    assert.deepEqual(ids(drawn), ['switch', 'backup', 'pi', 'ap', 'internet', 'mystery', 'lost']);
    assert.deepEqual([...awayFrom(w, room, drawn)], [['switch', 'home office'], ['backup', 'garage']]);
    // a route wholly inside another location brings nothing in
    assert.ok(!ids(drawn).includes('hyper') && !ids(drawn).includes('old'));
    // every place: nobody is a visitor
    assert.equal(awayFrom(w, null, HOUSE.nodes).size, 0);
  });
}

/* One step finer than a location, and what a scene has to offer (2026-11-20). */
{
  const { awayFrom, holdsHardware, holdsPlaces, locationOfRack, offered, placesFor, rackById }
    = await import('../static/js/locations-model.js');

  test('which rack a machine sits in; a guest is in its host\'s', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    const of = (id) => w.rackOf.get(id);
    assert.deepEqual(['hyper', 'switch', 'old', 'backup', 'ups'].map(of), ['a', 'a', 'a', 'g', 'g']);
    assert.deepEqual(['web', 'db', 'nested'].map(of), ['a', 'g', 'g']);
    // on a shelf, an idea, a guest whose host is nowhere: in no rack
    for (const id of ['pi', 'desk', 'ap', 'internet', 'lost']) assert.equal(of(id), undefined, id);
  });

  test('how much sits in each rack, on the map or not, and a slot called empty is nothing', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    // a: three in front and the PDU behind; b: a patch panel; g: a box and its UPS
    assert.deepEqual([...w.fitted], [['a', 4], ['b', 1], ['g', 2]]);
    const bare = whereabouts({ racks: [{ id: 'x', name: 'X' }], rack: [{ u: 'U1', name: 'Empty' }, { u: 'U2', name: '(empty)' }] });
    assert.deepEqual([...bare.fitted], [['x', 0]]);
  });

  test('a rack by its id, and the location it stands at', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    assert.equal(rackById(w, 'b').name, 'Rack B');
    assert.equal(locationOfRack(w, 'b').key, 'home office');
    assert.equal(locationOfRack(w, 'g').key, 'garage');
    for (const none of [null, undefined, 'the moon']) {
      assert.equal(rackById(w, none), null);
      assert.equal(locationOfRack(w, none), null);
    }
    // a map that charts no racks has one, and its id is the empty string: a real id
    const plain = whereabouts({ rack: [{ u: 'U1', name: 'Box', node: 'n' }], nodes: [node('n')] }, 'Home lab');
    assert.equal(rackById(plain, '').name, 'Rack A');
    assert.equal(locationOfRack(plain, '').key, 'home lab');
    assert.equal(plain.rackOf.get('n'), '');
  });

  /* a house with a rack that stands empty in the basement, and a rack of
     nothing but a patch panel in the attic */
  const SPARE = {
    racks: [{ id: 'a', name: 'Rack A', location: 'Office' }, { id: 'z', name: 'Spare', location: 'Basement' },
            { id: 'p', name: 'Patch', location: 'Attic' }, { id: 'o', name: 'Other', location: 'Office' }],
    rack: [{ rack: 'a', u: 'U1', name: 'Box', node: 'box' }, { rack: 'z', u: 'U1', name: 'Empty' },
           { rack: 'p', u: 'U1', name: 'Patch panel' }],
    nodes: [node('box'), node('pi', 'physical', { location: 'Shed' })],
  };
  const keys = (offer) => offer.map((o) => [o.loc.key, ids(o.racks)]);

  test('HARDWARE offers a location only when something stands there, and a rack only when something is in it', () => {
    const w = whereabouts(SPARE, 'Home lab');
    assert.deepEqual(ids(w.list.map((l) => ({ id: l.key }))), ['office', 'basement', 'attic', 'shed']);
    // the basement's rack is empty; the office's second rack is too
    assert.deepEqual(keys(offered(w, holdsHardware(w))), [['office', ['a']], ['attic', ['p']], ['shed', []]]);
    // what is on show stays offered whatever it holds
    assert.deepEqual(keys(offered(w, holdsHardware(w), 'basement')),
      [['office', ['a']], ['basement', []], ['attic', ['p']], ['shed', []]]);
  });

  test('TOPOLOGY offers a location only when a place on the map stands there', () => {
    const w = whereabouts(SPARE, 'Home lab');
    // a patch panel is hardware and is not a place: the attic has nothing to draw
    assert.deepEqual(keys(offered(w, holdsPlaces(w))), [['office', ['a']], ['shed', []]]);
    const house = whereabouts(HOUSE, 'Home lab');
    assert.deepEqual(keys(offered(house, holdsPlaces(house))),
      [['home office', ['a']], ['garage', ['g']], ['living room', []], ['home lab', []]]);
    assert.deepEqual(offered(whereabouts(null), holdsPlaces(whereabouts(null))), []);
  });

  test('one rack\'s topology: what is in it, its guests, the placeless, and its routes\' next stops', () => {
    const w = whereabouts(HOUSE, 'Home lab');
    const routes = [{ from: 'backup', to: 'switch' }, { from: 'ups', to: 'desk' }, { from: 'pi', to: 'ap' }];
    const g = rackById(w, 'g');
    const drawn = placesFor(w, locationOfRack(w, 'g'), HOUSE.nodes, routes, g);
    assert.deepEqual(ids(drawn), ['switch', 'backup', 'ups', 'desk', 'internet', 'mystery', 'db', 'nested', 'lost']);
    // the two visitors, each known by the location it stands at
    assert.deepEqual([...awayFrom(w, locationOfRack(w, 'g'), drawn, g)], [['switch', 'home office'], ['desk', 'home lab']]);
    // rack a of two in the office: the other rack's room-mates are visitors too, were one drawn
    const a = rackById(w, 'a');
    const office = placesFor(w, locationOfRack(w, 'a'), HOUSE.nodes, [], a);
    assert.deepEqual(ids(office), ['hyper', 'switch', 'old', 'internet', 'mystery', 'web', 'lost']);
    assert.equal(awayFrom(w, locationOfRack(w, 'a'), office, a).size, 0);
  });
}

console.log(`\nlocations-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
