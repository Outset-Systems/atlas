/* RESOURCES' sums, in plain node (2026-11-20).

   The first two tests pin what the scene said before the sums moved here: a
   lab with one host and one `meta.tribute` must read exactly as it did.

   Run:  node tests/test_tribute_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { CAPACITY_FIELDS, gb, holdsHosts, hostsAt, hostsIn, hostsOf, legacyCapacity, ownCapacity, totalsOf }
  from '../static/js/tribute-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const vm = (id, host, vcpu, ram, demand, state = 'on') => ({ id, host, vcpu, ram_gb: ram, demand_gb: demand, state });

/* the bundled demo lab's guests and its one `meta.tribute`, as they are */
const DEMO = {
  meta: { tribute: { total_gb: 128, host_reserve_gb: 8, cpu_cores: 16, cpu_threads: 32 } },
  nodes: [{ id: 'hypervisor', name: 'HYPERVISOR', kind: 'physical' }],
  vms: [
    vm('dc', 'hypervisor', 2, 4, 1.9), vm('monitor', 'hypervisor', 4, 8, 5.1),
    vm('downloads', 'hypervisor', 2, 4, 2.2), vm('internal-host', 'hypervisor', 4, 8, 4.6),
    vm('media', 'hypervisor', 4, 8, 3.8), vm('edge', 'hypervisor', 2, 2, 0.9),
    vm('app-host', 'hypervisor', 4, 8, 5.4), vm('standby', 'hypervisor', 2, 4, 0, 'off'),
  ],
};

test('one host and one meta.tribute read as they did: the demo lab', () => {
  const hosts = hostsOf(DEMO);
  assert.equal(hosts.length, 1);
  const h = hosts[0];
  assert.equal(h.id, 'hypervisor');
  assert.equal(h.legacy, true);
  assert.deepEqual(h.capacity, { total_gb: 128, reserve_gb: 8, cores: 16, threads: 32 });
  // "42.0 / 128 GB assigned · 23.9 GB in use · 78.0 GB free"
  assert.deepEqual([h.assigned_gb, h.demand_gb, h.free_gb], [42, 23.9, 78]);
  // "22 / 32 vCPU assigned · 16 cores · 32 threads · 10 threads free"
  assert.deepEqual([h.vcpu, h.threads_free, h.over], [22, 10, 0]);
  assert.equal(h.guests.length, 8);
  assert.equal(h.on.length, 7);
  const t = totalsOf(hosts);
  assert.deepEqual([t.assigned_gb, t.total_gb, t.demand_gb, t.free_gb], [42, 128, 23.9, 78]);
  assert.deepEqual([t.vcpu, t.threads, t.cores, t.threads_free, t.over], [22, 32, 16, 10, 0]);
  assert.deepEqual([t.hosts, t.guests, t.guests_on, t.uncounted_gb, t.uncounted_cpu], [1, 8, 7, 0, 0]);
});

test('a 64 GB host with 5 held back and 28 of 32 vCPU: the sums the lab reads', () => {
  const lab = {
    meta: { tribute: { total_gb: 64, host_reserve_gb: 5, cpu_cores: 16, cpu_threads: 32 } },
    nodes: [{ id: 'host', kind: 'physical' }],
    vms: [vm('a', 'host', 8, 16, 9.5), vm('b', 'host', 8, 12, 6), vm('c', 'host', 4, 8.1, 3),
          vm('d', 'host', 4, 8, 2), vm('e', 'host', 4, 6, 1), vm('off', 'host', 2, 8, 0, 'off')],
  };
  const h = hostsOf(lab)[0];
  assert.deepEqual([h.assigned_gb, h.vcpu, h.threads_free], [50.1, 28, 4]);
  assert.equal(h.free_gb, 8.9);          // 64 - 5 - 50.1, to the tenth and never 8.899999
  assert.equal(gb(h.assigned_gb), '50.1');
  assert.equal(gb(42), '42');
});

test('more vCPU than threads is said as over, never as negative headroom', () => {
  const h = hostsOf({ meta: { tribute: { total_gb: 16, cpu_threads: 4 } }, nodes: [{ id: 'h' }],
                      vms: [vm('a', 'h', 4, 8, 1), vm('b', 'h', 4, 12, 1)] })[0];
  assert.deepEqual([h.vcpu, h.threads_free, h.over], [8, 0, 4]);
  assert.equal(h.free_gb, 0);            // 20 assigned of 16: no headroom, not -4
});

/* two hosts in two places, a machine with no guests, and a host that says nothing */
const HOUSE = {
  meta: { tribute: { total_gb: 999, cpu_threads: 999 } },   // the old single figure: `quiet`'s, as the one silent host
  nodes: [
    { id: 'big', kind: 'physical', ram_gb: 128, ram_reserve_gb: 8, cpu_cores: 16, cpu_threads: 32 },
    { id: 'small', kind: 'physical', ram_gb: 32, cpu_cores: 4, cpu_threads: 8 },
    { id: 'pi', kind: 'physical', ram_gb: 8, cpu_cores: 4, cpu_threads: 4 },
    { id: 'quiet', kind: 'physical' },
    { id: 'guest', kind: 'vm', ram_gb: 4 },
  ],
  vms: [vm('g1', 'big', 4, 16, 8), vm('g2', 'small', 2, 8, 3), vm('g3', 'quiet', 2, 4, 1),
        vm('g4', 'small', 2, 8, 0, 'off'), vm('guest', 'big', 1, 4, 1)],
};
const AT = new Map([['big', 'office'], ['small', 'garage'], ['pi', 'living room'], ['quiet', 'garage']]);

test('hosts come in the guests\' order, then machines that only declare capacity', () => {
  const hosts = hostsOf(HOUSE, AT);
  assert.deepEqual(hosts.map((h) => h.id), ['big', 'small', 'quiet', 'pi']);
  assert.deepEqual(hosts.map((h) => h.location), ['office', 'garage', 'garage', 'living room']);
  // a guest that happens to carry a capacity field is not a machine
  assert.ok(!hosts.some((h) => h.id === 'guest'));
});

test('a place\'s own capacity is its own; a field it does not declare is not zero', () => {
  const [big, small, quiet, pi] = hostsOf(HOUSE, AT);
  assert.deepEqual(big.capacity, { total_gb: 128, reserve_gb: 8, cores: 16, threads: 32 });
  assert.equal(big.legacy, false);
  assert.deepEqual(small.capacity, { total_gb: 32, reserve_gb: null, cores: 4, threads: 8 });
  assert.equal(small.free_gb, 24);                 // nothing held back, one guest on
  assert.deepEqual([pi.guests.length, pi.assigned_gb, pi.free_gb], [0, 0, 8]);
  assert.equal(ownCapacity({ cpu_threads: 8 }).total_gb, null);
  assert.equal(ownCapacity({ ram_gb: '16' }).total_gb, 16);
  for (const none of [null, undefined, {}, { ram_gb: -1 }, { ram_gb: 'lots' }, { hw: '64 GB' }]) {
    assert.equal(ownCapacity(none), null, JSON.stringify(none));
  }
  assert.deepEqual(CAPACITY_FIELDS, ['ram_gb', 'ram_reserve_gb', 'cpu_cores', 'cpu_threads']);
});

test('a host that says nothing is not counted, and says so', () => {
  const [, , quiet] = hostsOf(HOUSE, AT);
  // `quiet` is the one host with guests and no capacity of its own, so the old
  // single `meta.tribute` is its
  assert.equal(quiet.legacy, true);
  assert.equal(quiet.capacity.total_gb, 999);
  // with a second silent host the old numbers are nobody's: both say "not charted"
  const two = { ...HOUSE, nodes: [...HOUSE.nodes, { id: 'mute', kind: 'physical' }],
                vms: [...HOUSE.vms, vm('g5', 'mute', 2, 4, 1)] };
  const hosts = hostsOf(two, AT);
  const silent = hosts.filter((h) => h.capacity === null);
  assert.deepEqual(silent.map((h) => h.id), ['quiet', 'mute']);
  for (const h of silent) {
    assert.deepEqual([h.free_gb, h.threads_free, h.over, h.legacy], [null, null, 0, false]);
    assert.ok(h.assigned_gb > 0, 'its guests are still summed');
  }
  const t = totalsOf(hosts);
  assert.deepEqual([t.hosts, t.uncounted_gb, t.uncounted_cpu], [4, 2, 2]);
  assert.equal(t.total_gb, 160);                   // big + small only
  assert.equal(t.assigned_gb, 16 + 4 + 8 + 4 + 4); // every host's guests that are on
  assert.equal(legacyCapacity({}), null);
  assert.equal(legacyCapacity({ tribute: {} }), null);
  assert.equal(legacyCapacity(null), null);
});

test('one location, and everything', () => {
  const hosts = hostsOf(HOUSE, AT);
  assert.deepEqual(hostsAt(hosts, 'garage').map((h) => h.id), ['small', 'quiet']);
  assert.deepEqual(hostsAt(hosts, 'living room').map((h) => h.id), ['pi']);
  assert.deepEqual(hostsAt(hosts, 'the moon'), []);
  for (const all of [null, undefined, '']) assert.equal(hostsAt(hosts, all).length, 4);
  const office = totalsOf(hostsAt(hosts, 'office'));
  assert.deepEqual([office.total_gb, office.reserve_gb, office.assigned_gb, office.free_gb], [128, 8, 20, 100]);
  assert.deepEqual([office.vcpu, office.threads, office.threads_free], [5, 32, 27]);
  // a location with only a machine that runs no guests: nothing is divided there,
  // and the compute that stands there is still counted
  const room = totalsOf(hostsAt(hosts, 'living room'));
  assert.deepEqual([room.hosts, room.total_gb, room.assigned_gb, room.vcpu], [0, 0, 0, 0]);
  assert.deepEqual([room.machines, room.cores_all, room.threads_all, room.ram_all], [1, 4, 4, 8]);
  // everything is the sum of its parts
  const all = totalsOf(hosts);
  const parts = ['office', 'garage', 'living room'].map((k) => totalsOf(hostsAt(hosts, k)));
  for (const key of ['total_gb', 'assigned_gb', 'demand_gb', 'free_gb', 'threads', 'vcpu', 'machines', 'ram_all']) {
    assert.equal(all[key], Math.round(parts.reduce((s, p) => s + p[key], 0) * 10) / 10, key);
  }
});

test('nothing charted is nothing, not a crash', () => {
  for (const junk of [null, undefined, {}, { vms: 'x', nodes: 3 }, { vms: [null, {}, { id: 'a' }] }]) {
    const hosts = hostsOf(junk);
    assert.deepEqual(hosts, [], JSON.stringify(junk));
    assert.equal(totalsOf(hosts).total_gb, 0);
  }
  // a guest whose host is not on the map still has a host row, with no place
  const h = hostsOf({ vms: [vm('a', 'ghost', 2, 4, 1)] })[0];
  assert.deepEqual([h.id, h.node, h.location, h.capacity], ['ghost', null, null, null]);
});

test('one rack: the hosts in it, and a location is the sum of its racks and its shelf', () => {
  // big and quiet share a rack; small has the other; the pi is on a shelf
  const IN = new Map([['big', 'a'], ['quiet', 'a'], ['small', '']]);
  const at = new Map([['big', 'office'], ['quiet', 'office'], ['small', 'office'], ['pi', 'office']]);
  const hosts = hostsOf(HOUSE, at, IN);
  assert.deepEqual(hosts.map((h) => [h.id, h.rack]), [['big', 'a'], ['small', ''], ['quiet', 'a'], ['pi', null]]);
  assert.deepEqual(hostsIn(hosts, 'a').map((h) => h.id), ['big', 'quiet']);
  // the empty string is a real rack id (the one rack of a map that charts none)
  assert.deepEqual(hostsIn(hosts, '').map((h) => h.id), ['small']);
  assert.deepEqual(hostsIn(hosts, 'the moon'), []);
  const a = totalsOf(hostsIn(hosts, 'a'));
  // `quiet` is the one silent host, so the old single figure (999) is its own
  assert.deepEqual([a.total_gb, a.assigned_gb, a.vcpu, a.threads, a.uncounted_gb], [128 + 999, 24, 7, 32 + 999, 0]);
  const parts = [hostsIn(hosts, 'a'), hostsIn(hosts, ''), hosts.filter((h) => h.rack === null)].map(totalsOf);
  const office = totalsOf(hostsAt(hosts, 'office'));
  for (const key of ['total_gb', 'assigned_gb', 'demand_gb', 'threads', 'vcpu', 'machines', 'ram_all']) {
    assert.equal(office[key], Math.round(parts.reduce((s, p) => s + p[key], 0) * 10) / 10, key);
  }
  // with no rack map given, nothing is in a rack
  assert.ok(hostsOf(HOUSE, AT).every((h) => h.rack === null));
});

test('RESOURCES offers a location, or a rack, only where a host stands', () => {
  const hosts = hostsOf(HOUSE, AT, new Map([['big', 'a']]));
  const holds = holdsHosts(hosts);
  const loc = (key) => ({ key });
  assert.deepEqual(['office', 'garage', 'living room', 'attic'].map((k) => holds(loc(k), null)), [true, true, true, false]);
  assert.equal(holds(loc('office'), { id: 'a' }), true);
  assert.equal(holds(loc('office'), { id: 'b' }), false);
  // a rack is asked for by id: one that holds no host is not offered, whatever its location holds
  assert.equal(holds(loc('garage'), { id: '' }), false);
});

console.log(`\ntribute-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
