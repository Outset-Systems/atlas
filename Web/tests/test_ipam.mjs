/* Address maths for THE LEDGER — run with `node tests/test_ipam.mjs`.

   The Ledger's prefix handling used to be `ip.split('.').slice(0,3)` and a
   fixed 256-cell grid, which is right for a /24 and wrong for everything
   else. This is the arithmetic that replaced it, checked against the answers
   Python's `ipaddress` gives for the same inputs — because two
   implementations of subnet maths that disagree is worse than one.

   Plain node, no framework: the front-end has no test runner and adding one
   to assert twenty numbers would be the larger change. */

import assert from 'node:assert/strict';
import {
  chartedAddresses, countLabel, drawable, formatAddress, isSubnetOf, nextFree,
  occupancy, parseAddress, parseCidr, prefixesOf, rangeAt, usableRange,
} from '../static/js/ipam.js';

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
  } catch (err) {
    console.error(`FAIL  ${name}\n      ${err.message}`);
    process.exitCode = 1;
  }
}

/* ── parsing ─────────────────────────────────────────────────────────── */

test('parses v4', () => {
  // constants from python: int(ipaddress.ip_address(...))
  assert.equal(parseAddress('10.77.33.15').value, 172826895n);
  assert.equal(parseAddress('0.0.0.0').value, 0n);
  assert.equal(parseAddress('255.255.255.255').value, 4294967295n);
});

test('rejects nonsense v4', () => {
  for (const bad of ['10.77.33', '256.0.0.1', '10.77.33.15.1', 'ten.three', '']) {
    assert.equal(parseAddress(bad), null, `${bad} should not parse`);
  }
});

test('parses v6 including ::', () => {
  assert.equal(parseAddress('::').value, 0n);
  assert.equal(parseAddress('::1').value, 1n);
  assert.equal(parseAddress('fd00::1').version, 6);
  assert.equal(parseAddress('2001:db8:0:0:0:0:0:1').value, parseAddress('2001:db8::1').value);
  assert.equal(parseAddress('fd00:lab::'), null, 'hex only');
});

test('formats v6 per RFC 5952 — longest zero run, and only runs of 2+', () => {
  const round = (t) => formatAddress(6, parseAddress(t).value);
  assert.equal(round('fd00:beef::'), 'fd00:beef::');
  assert.equal(round('fd00:beef::1'), 'fd00:beef::1');
  assert.equal(round('::1'), '::1');
  // one lone zero group must NOT be collapsed; the longer run wins
  assert.equal(round('2001:db8:1:0:0:2:0:1'), '2001:db8:1::2:0:1');
});

test('formats v4 round trip', () => {
  for (const ip of ['0.0.0.0', '10.77.33.15', '192.168.1.1', '255.255.255.255']) {
    assert.equal(formatAddress(4, parseAddress(ip).value), ip);
  }
});

/* ── prefixes ────────────────────────────────────────────────────────── */

test('parses prefixes of any length and masks the host bits off', () => {
  const net = parseCidr('10.77.33.77/24');
  assert.equal(formatAddress(4, net.network), '10.77.33.0', 'network address is masked');
  assert.equal(formatAddress(4, net.broadcast), '10.77.33.255');
  assert.equal(net.size, 256n);

  assert.equal(parseCidr('10.0.0.0/8').size, 16777216n);
  assert.equal(parseCidr('10.0.0.0/30').size, 4n);
  assert.equal(parseCidr('fd00::/64').size, 1n << 64n);
  assert.equal(parseCidr('10.0.0.1').prefixlen, 32, 'a bare address is a host route');
  assert.equal(parseCidr('10.0.0.0/33'), null);
});

test('usable range follows RFC 3021 for /31 and /32', () => {
  assert.equal(usableRange(parseCidr('10.0.0.0/24')).count, 254n);
  assert.equal(usableRange(parseCidr('10.0.0.0/30')).count, 2n);
  // the old maths said "254 free" for every prefix; these two would have gone negative
  assert.equal(usableRange(parseCidr('10.0.0.0/31')).count, 2n, 'point-to-point: both ends usable');
  assert.equal(usableRange(parseCidr('10.0.0.1/32')).count, 1n, 'a host route is one address');
  assert.equal(usableRange(parseCidr('fd00::/64')).count, 1n << 64n, 'v6 has no broadcast');
});

test('nesting', () => {
  const big = parseCidr('10.0.0.0/8');
  const small = parseCidr('10.77.33.0/24');
  assert.equal(isSubnetOf(small, big), true);
  assert.equal(isSubnetOf(big, small), false);
  assert.equal(isSubnetOf(big, big), false, 'a prefix does not contain itself');
  assert.equal(isSubnetOf(parseCidr('fd00::/64'), big), false, 'v6 is not inside v4');
});

test('only sane sizes are drawn cell by cell', () => {
  assert.equal(drawable(parseCidr('10.0.0.0/24')), true);
  assert.equal(drawable(parseCidr('10.0.0.0/22')), true);
  assert.equal(drawable(parseCidr('10.0.0.0/21')), false);
  assert.equal(drawable(parseCidr('fd00::/64')), false);
});

test('huge counts get an exponent, not 1.8e19 digits', () => {
  assert.equal(countLabel(254n), '254');
  assert.match(countLabel(1n << 64n), /^10\^\d+$/);
});

/* ── occupancy ───────────────────────────────────────────────────────── */

const DATA = {
  zones: [
    { id: 'admin', name: 'Admin', vlan: 4, subnet: '10.77.33.0/24' },
    { id: 'dmz', name: 'DMZ', vlan: 90, subnet: '10.77.90.0/24' },
  ],
  prefixes: [
    { id: 'super', cidr: '10.77.0.0/16', role: 'container', name: 'Everything' },
    { id: 'admin4', cidr: '10.77.33.0/24', zone: 'admin', role: 'prefix',
      ranges: [{ start: '10.77.33.100', end: '10.77.33.199', kind: 'dhcp' }] },
  ],
  nodes: [
    { id: 'a', ip: '10.77.33.10' },
    { id: 'b', ip: '10.77.33.11' },
    { id: 'c', ip: '10.77.90.5' },
    { id: 'nowhere', ip: '198.51.100.1' },
    { id: 'none', ip: '—' },
    { id: 'range', ip: '100.64.0.0/10' },
  ],
};

test('zone subnets become prefixes when prefixes[] does not list them', () => {
  const list = prefixesOf(DATA);
  const cidrs = list.map((p) => p.cidr);
  assert.ok(cidrs.includes('10.77.90.0/24'), 'the DMZ zone subnet was synthesised');
  assert.equal(cidrs.filter((c) => c === '10.77.33.0/24').length, 1, 'no duplicate');
  const admin = list.find((p) => p.cidr === '10.77.33.0/24');
  assert.equal(admin.source, 'prefix', 'the explicit prefix wins over the zone');
});

test('children nest under their container', () => {
  const list = prefixesOf(DATA);
  const container = list.find((p) => p.id === 'super');
  assert.equal(container.children.length, 2, 'both /24s are inside the /16');
  assert.equal(container.parent, null);
  assert.equal(list.find((p) => p.id === 'admin4').parent.id, 'super');
});

test('charted addresses skip the unparseable and the em-dash', () => {
  const charted = chartedAddresses(DATA);
  assert.equal(charted.size, 5, 'the em-dash is not an address; a bare prefix is');
  assert.ok(charted.has(parseAddress('10.77.33.10').value));
});

test('a prefix counts its own hosts, and a pool counts as spoken for', () => {
  const list = prefixesOf(DATA);
  const charted = chartedAddresses(DATA);
  const admin = list.find((p) => p.id === 'admin4');
  const stats = occupancy(admin, charted);
  assert.equal(stats.direct.length, 2);
  assert.equal(stats.pool, 100n, 'the dhcp pool is 100 addresses');
  assert.equal(stats.used, 102n);
  assert.equal(stats.free, 254n - 102n);
});

test('a container reports delegation, not loose hosts', () => {
  const list = prefixesOf(DATA);
  const stats = occupancy(list.find((p) => p.id === 'super'), chartedAddresses(DATA));
  assert.equal(stats.container, true);
  assert.equal(stats.delegated, 512n, 'two /24s');
  assert.equal(stats.total, 65536n);
  assert.equal(stats.free, 65024n);
});

test('a host inside a child belongs to the child, not the container', () => {
  const list = prefixesOf(DATA);
  const container = list.find((p) => p.id === 'super');
  const stats = occupancy(container, chartedAddresses(DATA));
  assert.equal(stats.direct.length, 0, 'every 10.77.x host lives in a child prefix');
  assert.equal(stats.hosts.length, 3, '...but they are still inside it');
});

test('next free address skips what is taken and what is pooled', () => {
  const list = prefixesOf(DATA);
  const admin = list.find((p) => p.id === 'admin4');
  const used = new Set(chartedAddresses(DATA).keys());
  assert.equal(nextFree(admin.net, used, admin.ranges), '10.77.33.1');

  // fill .1 to .9 and it should step over the two charted hosts as well
  for (let i = 1; i <= 9; i++) used.add(parseAddress(`10.77.33.${i}`).value);
  assert.equal(nextFree(admin.net, used, admin.ranges), '10.77.33.12');
});

test('next free stays out of the dhcp pool', () => {
  const net = parseCidr('10.0.0.0/24');
  const used = new Set();
  for (let i = 1; i <= 9; i++) used.add(parseAddress(`10.0.0.${i}`).value);
  const ranges = [{ start: '10.0.0.10', end: '10.0.0.250', kind: 'dhcp' }];
  assert.equal(nextFree(net, used, ranges), '10.0.0.251');
});

test('next free terminates on an enormous prefix', () => {
  assert.equal(nextFree(parseCidr('fd00::/64'), new Set(), []), 'fd00::');
});

test('rangeAt identifies pool membership', () => {
  const admin = prefixesOf(DATA).find((p) => p.id === 'admin4');
  assert.equal(rangeAt(admin, parseAddress('10.77.33.150').value).kind, 'dhcp');
  assert.equal(rangeAt(admin, parseAddress('10.77.33.10').value), null);
});

if (!process.exitCode) console.log(`ipam: ${passed} passed`);
