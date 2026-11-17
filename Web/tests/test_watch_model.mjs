/* THE WATCH in the page (2026-11-15), in plain node.

   Run:  node tests/test_watch_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { checkWhere, seenFor } from '../static/js/watch-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

test('a service with nothing to open says where its check asks', () => {
  const node = { id: 'dc', ip: '192.0.2.9' };
  assert.equal(checkWhere({ check: 'tcp', check_port: 636 }, node), '192.0.2.9:636');
  assert.equal(checkWhere({ check: 'tcp', check_host: 'dc.example', check_port: 389 }, node), 'dc.example:389');
  assert.equal(checkWhere({ check: 'dns', check_host: 'wiki.example' }, node), 'wiki.example');
  assert.equal(checkWhere({ check: 'dns' }, node), '', 'a dns check names what it resolves');
  assert.equal(checkWhere({ check: 'tcp', check_port: 22 }, { id: 'net', ip: '—' }), '');
  assert.equal(checkWhere({ url: 'http://192.0.2.9/' }, node), '', 'a service with an address shows that');
  assert.equal(checkWhere(null, node), '');
});

const DATA = {
  nodes: [
    { id: 'edge', name: 'EDGE', links: [
      { label: 'Feed', url: 'https://feed.example.org/' },
      { label: 'Cloud', url: 'https://cloud.example.org/', kuma: 'Cloud monitor' },
      { label: 'Plain', url: 'http://192.0.2.5/' },
    ] },
    { id: 'core', name: 'CORE', links: [{ label: 'Panel', url: 'https://192.0.2.6:8443/', check_host: 'https://panel.example.net/' }] },
  ],
};
const SERVICES = {
  'edge/Feed': { state: 'healthy', tls: { expires: '2026-12-17', issuer: 'Invented CA', names: ['*.example.org'] } },
  'Cloud monitor': { state: 'healthy', tls: { expires: '2026-12-01', issuer: 'Invented CA', names: ['cloud.example.org'] } },
  'core/Panel': { state: 'healthy', tls: { expires: '2027-02-02', issuer: 'Self', names: [] } },
};

test('a charted certificate meets the soonest one a check saw for it', () => {
  // the wildcard is among the names one presented, and covers the other's host
  const seen = seenFor({ kind: 'tls', name: '*.example.org', expires: '2026-12-17' }, DATA, SERVICES);
  assert.deepEqual(seen, { expires: '2026-12-01', issuer: 'Invented CA', via: 'Cloud on EDGE', differs: true });
  const same = seenFor({ kind: 'tls', name: 'feed.example.org', expires: '2026-12-17' }, DATA,
    { 'edge/Feed': SERVICES['edge/Feed'] });
  assert.deepEqual(same, { expires: '2026-12-17', issuer: 'Invented CA', via: 'Feed on EDGE', differs: false });
});

test('a certificate is met by the name its check asked, and only one label under a wildcard', () => {
  assert.equal(seenFor({ kind: 'tls', name: 'panel.example.net', expires: '2027-02-02' }, DATA, SERVICES).differs, false);
  assert.equal(seenFor({ kind: 'tls', name: '*.example.net', expires: '2027-02-02' }, DATA, SERVICES).via, 'Panel on CORE');
  assert.equal(seenFor({ kind: 'tls', name: '*.net', expires: '2027-02-02' }, DATA, SERVICES), null);
});

test('nothing seen, not TLS, or no date charted', () => {
  assert.equal(seenFor({ kind: 'tls', name: 'nowhere.example' }, DATA, SERVICES), null);
  assert.equal(seenFor({ kind: 'ssh-host', name: '*.example.org' }, DATA, SERVICES), null);
  assert.equal(seenFor({ kind: 'tls', name: '*.example.org' }, DATA, null), null);
  assert.equal(seenFor({ kind: 'tls', name: 'feed.example.org' }, DATA, { 'edge/Feed': SERVICES['edge/Feed'] }).differs,
    true, 'a seal with no charted date disagrees with one seen');
});

console.log(`\n${passed} passed`);
