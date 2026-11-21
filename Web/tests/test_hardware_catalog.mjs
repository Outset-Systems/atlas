/* What HARDWARE's Add offers and what it sends, in plain node (2026-11-21).

   Run:  node tests/test_hardware_catalog.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DEVICE_GROUPS, SEATS, addBody, addName, typeById } from '../static/js/hardware-catalog.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

test('the groups the owner named, each with what he named in it', () => {
  assert.deepEqual(DEVICE_GROUPS.map((g) => g.label), ['Network', 'Compute', 'Storage', 'Power']);
  const labels = (group) => DEVICE_GROUPS.find((g) => g.label === group).types.map((t) => t.label).join(' | ');
  for (const word of ['12 ports', '24 ports', '48 ports', 'Gateway', 'Patch panel', 'Router']) assert.ok(labels('Network').includes(word), word);
  for (const word of ['Computer', 'Blade', 'Dell PowerEdge', 'Raspberry Pi']) assert.ok(labels('Compute').includes(word), word);
  assert.ok(labels('Storage').includes('NAS'));
  assert.ok(labels('Power').includes('PDU'));
  assert.deepEqual(SEATS.map((s) => s.id), ['front', 'back', 'inside']);
});

test('every type has its own id, a faceplate the map knows, and a height the box offers', () => {
  const schema = readFileSync(new URL('../schema.py', import.meta.url), 'utf8');
  const kinds = JSON.parse(schema.match(/RACK_KINDS = (\[[^\]]*\])/s)[1].replace(/\s+/g, ' '));
  const page = readFileSync(new URL('../templates/index.html', import.meta.url), 'utf8');
  const heights = [...page.match(/<select id="rel-add-size"[^>]*>(.*?)<\/select>/s)[1].matchAll(/value="(\d+)"/g)].map((m) => Number(m[1]));
  const ids = new Set();
  for (const t of DEVICE_GROUPS.flatMap((g) => g.types)) {
    assert.ok(!ids.has(t.id), `two types share the id ${t.id}`);
    ids.add(t.id);
    assert.ok(kinds.includes(t.kind) && t.kind !== 'auto', `${t.id}: ${t.kind}`);
    assert.ok(heights.includes(t.size), `${t.id}: ${t.size}U is not in the Height list`);
    assert.equal(typeById(t.id), t);
  }
  assert.equal(typeById(''), null);
  assert.equal(typeById('toaster'), null);
});

test('the name: a place\'s own, else what was typed, else the type\'s words', () => {
  const type = typeById('switch-24');
  assert.equal(addName({ node: { name: 'CORE SWITCH' }, typed: 'x', type }), 'CORE SWITCH');
  assert.equal(addName({ typed: '  Top   of rack ', type }), 'Top of rack');
  assert.equal(addName({ type }), 'Switch, 24 ports');
  assert.equal(addName({}), '');
});

test('the front is a U slot with its faceplate and height', () => {
  const type = typeById('switch-24');
  assert.deepEqual(addBody({ seat: 'front', name: 'Top of rack', type, size: 1, u: 'U12', rackId: 'rack-b' }),
    { section: 'rack', body: { u: 'U12', name: 'Top of rack', rack: 'rack-b', desc: 'Switch, 24 ports', size: 1, kind: 'switch' } });
  // a place on the map, on a map that charts no racks, with no type said
  assert.deepEqual(addBody({ seat: 'front', name: 'NAS', node: { id: 'nas' }, size: 2, u: 'U3–U4' }),
    { section: 'rack', body: { u: 'U3–U4', name: 'NAS', node: 'nas', size: 2 } });
  // named by its type: the description would only say the name again
  assert.equal('desc' in addBody({ seat: 'front', name: 'Switch, 24 ports', type, u: 'U1' }).body, false);
});

test('the back and the inside are fittings with no U', () => {
  const type = typeById('pdu');
  assert.deepEqual(addBody({ seat: 'back', name: 'Left strip', type, size: 4, u: 'U9', rackId: 'rack-a' }),
    { section: 'rack_rear', body: { name: 'Left strip', rack: 'rack-a', desc: 'PDU' } });
  assert.deepEqual(addBody({ seat: 'inside', name: 'Tray', node: { id: 'pi' }, type: typeById('pi') }),
    { section: 'rack_rear', body: { name: 'Tray', node: 'pi', desc: 'Raspberry Pi', side: 'inside' } });
});

console.log(`\n${passed} passed`);
