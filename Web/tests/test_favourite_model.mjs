/* A service as a favourite, in plain node (2026-11-21).

   Run:  node tests/test_favourite_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { favouriteOf, favouriteOps, hostOf, tileFor } from '../static/js/favourite-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const MAP = {
  nodes: [
    { id: 'gateway', links: [{ label: 'Console', url: 'https://10.0.0.1' }, { label: 'Status', url: 'https://status.example.com/' }] },
    { id: 'switch', links: [{ label: 'Console', url: 'https://10.0.0.1', desc: 'the same console' }] },
    { id: 'nas', links: [{ label: 'Files', url: 'http://nas.internal:5000', favourite: 'internal' }, { label: 'No address' }] },
    { id: 'bare' },
  ],
};

test('the host of an address', () => {
  assert.equal(hostOf('https://Example.COM:8443/a?b'), 'example.com');
  assert.equal(hostOf('http://user:pw@10.0.0.1/'), '10.0.0.1');
  assert.equal(hostOf('http://[fd00::1]:80/'), 'fd00::1');
  assert.equal(hostOf('nonsense'), '');
});

test('which tile: what only the inside can reach is internal', () => {
  for (const url of ['https://10.77.1.1', 'http://192.168.1.5:8080', 'http://172.20.0.3', 'http://127.0.0.1',
    'http://100.100.5.2', 'http://nas:5000', `https://atlas.home.${'l' + 'an'}/x`, 'http://printer.local', 'http://[fd12::9]/', 'nonsense']) {
    assert.equal(tileFor(url), 'internal', url);
  }
  for (const url of ['https://status.example.com', 'https://8.8.8.8', 'http://172.32.0.1', 'https://atlas.example.com/demo/', 'http://[2001:db8::1]/']) {
    assert.equal(tileFor(url), 'external', url);
  }
});

test('an address is one favourite however many places chart it', () => {
  assert.equal(favouriteOf(MAP, 'http://nas.internal:5000'), 'internal');
  assert.equal(favouriteOf(MAP, ' http://nas.internal:5000 '), 'internal');
  assert.equal(favouriteOf(MAP, 'https://10.0.0.1'), '');
  assert.equal(favouriteOf(MAP, ''), '');
  const marked = { nodes: [...MAP.nodes.slice(0, 1), { id: 'switch', links: [{ label: 'Console', url: 'https://10.0.0.1', favourite: 'external' }] }] };
  assert.equal(favouriteOf(marked, 'https://10.0.0.1'), 'external');
});

test('marking writes the one link pressed, with the place\'s whole list', () => {
  const ops = favouriteOps(MAP, 'switch', { label: 'Console', url: 'https://10.0.0.1' }, true);
  assert.deepEqual(ops, [{ op: 'upsert', section: 'nodes', id: 'switch',
    body: { links: [{ label: 'Console', url: 'https://10.0.0.1', desc: 'the same console', favourite: 'internal' }] } }]);
  const out = favouriteOps(MAP, 'gateway', { label: 'Status', url: 'https://status.example.com/' }, true);
  assert.equal(out[0].body.links[1].favourite, 'external');
  assert.equal('favourite' in out[0].body.links[0], false);
  // a tile said outright wins over the guess
  assert.equal(favouriteOps(MAP, 'gateway', { label: 'Status', url: 'https://status.example.com/' }, true, 'internal')[0].body.links[1].favourite, 'internal');
});

test('nothing is sent when nothing would change, or the service is not there', () => {
  assert.deepEqual(favouriteOps(MAP, 'nas', { label: 'Files', url: 'http://nas.internal:5000' }, true), []);     // already one
  assert.deepEqual(favouriteOps(MAP, 'nas', { label: 'No address' }, true), []);                            // no address
  assert.deepEqual(favouriteOps(MAP, 'nobody', { label: 'Console', url: 'https://10.0.0.1' }, true), []);
  assert.deepEqual(favouriteOps(MAP, 'gateway', { label: 'Renamed', url: 'https://10.0.0.1' }, true), []);
  assert.deepEqual(favouriteOps(MAP, 'gateway', { label: 'Console', url: 'https://10.0.0.1' }, false), []);  // not one
});

test('clearing clears every place that marks the address', () => {
  const both = { nodes: [
    { id: 'gateway', links: [{ label: 'Console', url: 'https://10.0.0.1', favourite: 'internal' }, { label: 'Other', url: 'https://x.example' }] },
    { id: 'switch', links: [{ label: 'Console', url: 'https://10.0.0.1', favourite: 'external', desc: 'd' }] },
    { id: 'nas', links: [{ label: 'Files', url: 'http://nas.internal:5000', favourite: 'internal' }] },
  ] };
  const ops = favouriteOps(both, 'switch', { label: 'Console', url: 'https://10.0.0.1' }, false);
  assert.deepEqual(ops.map((o) => o.id), ['gateway', 'switch']);
  assert.deepEqual(ops[0].body.links, [{ label: 'Console', url: 'https://10.0.0.1' }, { label: 'Other', url: 'https://x.example' }]);
  assert.deepEqual(ops[1].body.links, [{ label: 'Console', url: 'https://10.0.0.1', desc: 'd' }]);
});

console.log(`\n${passed} passed`);
