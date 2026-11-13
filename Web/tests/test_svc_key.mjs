/* The key that ties a service dot to its live state. `node tests/test_svc_key.mjs`

   config.js reads the page as it loads, so the two things it asks for are
   stood up first and the module is imported after them. */

import assert from 'node:assert/strict';

globalThis.document = { getElementById: () => null, body: { dataset: {} } };
globalThis.matchMedia = () => ({ matches: false });
const { svcKey } = await import('../static/js/config.js');

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

test('a link that names a monitor is keyed by the monitor, as it always was', () => {
  assert.equal(svcKey({ label: 'Wiki', kuma: 'Wiki monitor' }, 'app-box'), 'Wiki monitor');
});

test('a link with no monitor is keyed by its place and its label', () => {
  assert.equal(svcKey({ label: 'Wiki' }, 'app-box'), 'app-box/Wiki');
  assert.equal(svcKey({ label: 'Wiki', kuma: '' }, 'app-box'), 'app-box/Wiki');
});

test('the same label on two places is two keys', () => {
  assert.notEqual(svcKey({ label: 'Admin' }, 'app-box'), svcKey({ label: 'Admin' }, 'file-box'));
});

test('a link with no label still has a key, the one the server gives it', () => {
  // signals.service_key: f"{node_id}/{label or ''}"
  assert.equal(svcKey({}, 'app-box'), 'app-box/');
  assert.equal(svcKey({ label: null }, 'app-box'), 'app-box/');
});

console.log(`\n${passed} passed`);
