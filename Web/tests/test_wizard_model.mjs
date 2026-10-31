/* What guided setup reads off a list of addresses. `node tests/test_wizard_model.mjs` */

import assert from 'node:assert/strict';
import { inCidr, suggestNetworks } from '../static/js/editor/wizard-model.js';

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; }
  catch (err) { console.error(`FAIL  ${name}\n      ${err.message}`); process.exitCode = 1; }
};

test('inCidr reads prefixes of any length, and refuses what it cannot parse', () => {
  assert.equal(inCidr('10.0.0.9', '10.0.0.0/24'), true);
  assert.equal(inCidr('10.0.1.9', '10.0.0.0/24'), false);
  assert.equal(inCidr('10.0.1.9', '10.0.0.0/16'), true);
  assert.equal(inCidr('200.0.0.1', '200.0.0.0/8'), true, 'the top bit must not turn it negative');
  assert.equal(inCidr('10.0.0.9', '—'), false);
  assert.equal(inCidr('fe80::1', '10.0.0.0/24'), false);
  assert.equal(inCidr('10.0.0.9', '10.0.0.0/33'), false);
});

test('addresses group by /24, busiest first', () => {
  const nets = suggestNetworks(['10.0.1.2', '192.168.1.5', '192.168.1.6', '10.0.1.3', '192.168.1.7']);
  assert.deepEqual(nets, [
    { id: 'net-192-168-1', name: 'Network 192.168.1.x', subnet: '192.168.1.0/24', count: 3 },
    { id: 'net-10-0-1', name: 'Network 10.0.1.x', subnet: '10.0.1.0/24', count: 2 },
  ]);
});

test('a charted network is not offered again', () => {
  const zones = [{ id: 'main', subnet: '192.168.0.0/16' }, { id: 'none', subnet: '—' }];
  assert.deepEqual(suggestNetworks(['192.168.1.5', '10.0.1.2'], zones).map((n) => n.subnet), ['10.0.1.0/24']);
});

test('nothing usable means nothing to offer', () => {
  assert.deepEqual(suggestNetworks(['', '—', 'fe80::1', null, '999.1.1.1']), []);
  assert.deepEqual(suggestNetworks(undefined), []);
});

console.log(`wizard-model: ${passed} passed`);
