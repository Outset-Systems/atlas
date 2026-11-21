/* RESOURCES' available compute, by site and by rack, in plain node (2026-11-21).

   Run:  node tests/test_tribute_available.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { availableBy, availableOf, hostsOf, totalsOf } from '../static/js/tribute-model.js';
import { whereabouts } from '../static/js/locations-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const vm = (id, host, vcpu, ram, state = 'on') => ({ id, host, vcpu, ram_gb: ram, demand_gb: 1, state });
const box = (id, ram, threads, more = {}) => ({ id, name: id.toUpperCase(), kind: 'physical',
  ...(ram === null ? {} : { ram_gb: ram }), ...(threads === null ? {} : { cpu_cores: threads / 2, cpu_threads: threads }), ...more });

/* an office with two racks and a Pi on a shelf, a garage with one rack, a machine that
   names no location (it is at the default one, Lab), and a network place with compute */
const LAB = {
  racks: [{ id: 'a', name: 'Rack A', location: 'Office' }, { id: 'b', name: 'Rack B', location: 'Office' },
    { id: 'g', name: 'Garage rack', location: 'Garage' }],
  rack: [{ rack: 'a', u: 'U1', name: 'Hyper', node: 'hyper' }, { rack: 'b', u: 'U1', name: 'Spare', node: 'spare' },
    { rack: 'g', u: 'U1', name: 'Backup', node: 'backup' }],
  nodes: [box('hyper', 64, 16, { ram_reserve_gb: 4 }), box('spare', 32, 8), box('backup', 16, 4),
    box('pi', 8, 4, { location: 'Office' }), box('mystery', null, null),
    { id: 'cloud-host', name: 'CLOUD', kind: 'network', ram_gb: 4, cpu_threads: 2 }],
  vms: [vm('web', 'hyper', 4, 16), vm('db', 'hyper', 4, 8), vm('idle', 'hyper', 2, 8, 'off'),
    vm('vault', 'backup', 6, 4), vm('lost', 'mystery', 2, 2)],
};
const where = whereabouts(LAB, 'Lab');
const hosts = hostsOf(LAB, where.ofNode, where.rackOf);

test('what is available counts a machine that runs no guests, which the bars do not', () => {
  const office = hosts.filter((h) => h.location === 'office');
  const a = availableOf(office);
  // hyper 64 - 4 held back - 24 assigned = 36, spare 32, pi 8
  assert.deepEqual([a.machines, a.total_gb, a.assigned_gb, a.reserve_gb, a.free_gb], [3, 104, 24, 4, 76]);
  assert.deepEqual([a.threads, a.vcpu, a.threads_free, a.over, a.guests_on], [28, 8, 20, 0, 2]);
  // the bars' own sum is the one host that divides its memory
  assert.equal(totalsOf(office).free_gb, 36);
  assert.deepEqual(availableOf([]).machines, 0);
});

test('by location: a row a site, in the map\'s order, then what stands nowhere', () => {
  const rows = availableBy(hosts, where, 'site');
  assert.deepEqual(rows.map((r) => [r.kind, r.name, r.hosts.length]),
    [['place', 'Office', 3], ['place', 'Garage', 1], ['place', 'Lab', 1], ['adrift', 'Not placed', 1]]);
  const garage = rows[1].sum;
  // six vCPU against four threads: over, and no thread free
  assert.deepEqual([garage.free_gb, garage.threads_free, garage.over], [12, 0, 2]);
  // a machine that names no location is at the map's default one; it charts
  // nothing, so it is in the count and in none of the sums
  const lab = rows[2].sum;
  assert.deepEqual([lab.machines, lab.uncharted, lab.total_gb, lab.free_gb, lab.guests_on], [1, 1, 0, 0, 1]);
  // a network place that says its compute stands at no location at all
  const adrift = rows[3].sum;
  assert.deepEqual([adrift.machines, adrift.uncharted, adrift.total_gb, adrift.free_gb], [1, 0, 4, 4]);
});

test('by hardware: a row a rack under its location, then what is in no rack', () => {
  const rows = availableBy(hosts, where, 'rack');
  assert.deepEqual(rows.map((r) => [r.kind, r.name, r.at, r.sum.free_gb]), [
    ['rack', 'Rack A', 'Office', 36], ['rack', 'Rack B', 'Office', 32], ['shelf', 'Not in a rack', 'Office', 8],
    ['rack', 'Garage rack', 'Garage', 12], ['shelf', 'Not in a rack', 'Lab', 0], ['adrift', 'Not placed', '', 4]]);
  assert.deepEqual([rows[0].id, rows[0].key], ['a', 'office']);
  // one location on show: its racks and its shelf, and nothing from elsewhere
  assert.deepEqual(availableBy(hosts, where, 'rack', 'office').map((r) => r.name), ['Rack A', 'Rack B', 'Not in a rack']);
  assert.deepEqual(availableBy(hosts, where, 'rack', 'garage').map((r) => r.name), ['Garage rack']);
});

test('a rack or a site with no machine in it is not a row', () => {
  const empty = { ...LAB, racks: [...LAB.racks, { id: 'z', name: 'Empty rack', location: 'Attic' }] };
  const w = whereabouts(empty, 'Lab');
  const h = hostsOf(empty, w.ofNode, w.rackOf);
  assert.ok(!availableBy(h, w, 'site').some((r) => r.name === 'Attic'));
  assert.ok(!availableBy(h, w, 'rack').some((r) => r.name === 'Empty rack'));
  assert.deepEqual(availableBy([], w, 'site'), []);
  assert.deepEqual(availableBy(h, null, 'site').map((r) => r.kind), ['adrift']);
});

console.log(`\n${passed} passed`);
