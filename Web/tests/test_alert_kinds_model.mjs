/* The destination form's kinds, from what the server declares (2026-11-16):
   `kinds` in the alerts read, from Web/senders/. Settings › Alerts draws the
   kind picker and each kind's fields from this list, so a kind added on the
   server appears with no change here; told nothing, the page offers the
   three it always has, with the same fields.

   Run:  node tests/test_alert_kinds_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import * as M from '../static/js/alerts-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const url = (placeholder) => ({ name: 'url', type: 'url', required: true, label: 'alerts_f_url', text: 'Address', placeholder });
const SECRET = {
  name: 'secret', type: 'secret-name', required: false, label: 'alerts_f_secret', text: 'Secret\'s name',
  hint: 'alerts_secret_hint', hint_text: 'The server reads ATLAS_ALERT_SECRET_<NAME> or its _FILE; Atlas never stores the secret.',
  placeholder: 'NTFY_LAB',
};
/** What the server sends today (senders.declarations()). */
const SERVER = [
  { kind: 'ntfy', label: 'ntfy', fields: [url('https://ntfy.example/lab-alerts'), SECRET] },
  { kind: 'gotify', label: 'Gotify', fields: [url('https://gotify.example'), SECRET] },
  { kind: 'webhook', label: 'A JSON webhook', fields: [url('https://hooks.example/atlas'), SECRET] },
];
const PAGER = { kind: 'pager', label: 'A pager', fields: [url('https://pager.example/in')] };
/** Discord as senders/discord.py declares it (2026-11-16): its secret required. */
const DISCORD = {
  kind: 'discord', label: 'Discord',
  fields: [url('https://discord.com/api/webhooks/123456789012345678'), { ...SECRET, required: true, placeholder: 'DISCORD_LAB' }],
};

const shape = (kinds) => kinds.map((k) => [k.kind, k.label, k.fields.map((f) => [f.name, f.type, f.label, f.placeholder])]);

test('told nothing, the three kinds the page always offered, with the same fields', () => {
  for (const given of [undefined, null, [], 'x', [{}], [{ kind: 'pager', fields: [] }]]) {
    assert.deepEqual(shape(M.kindList(given)), shape(SERVER), JSON.stringify(given));
  }
  assert.deepEqual(M.kindList().map((k) => k.kind), M.KINDS);
});

test('the server\'s declarations are taken in its order, a fourth kind included', () => {
  assert.deepEqual(shape(M.kindList(SERVER)), shape(SERVER));
  const four = M.kindList([...SERVER, PAGER]);
  assert.deepEqual(four.map((k) => k.kind), ['ntfy', 'gotify', 'webhook', 'pager']);
  assert.equal(four[3].label, 'A pager');
  assert.deepEqual(four[3].fields.map((f) => f.name), ['url']);
});

test('a declaration with no address, or a field of no known type, is left out', () => {
  const odd = { kind: 'odd', label: 'Odd', fields: [{ name: 'server', type: 'text' }] };
  const strange = { kind: 'strange', label: 'S', fields: [url('x'), { name: 'colour', type: 'paint' }] };
  const out = M.kindList([PAGER, odd, strange, null, { label: 'no kind', fields: [url('x')] }]);
  assert.deepEqual(out.map((k) => k.kind), ['pager', 'strange']);
  assert.deepEqual(out[1].fields.map((f) => f.name), ['url']);
});

test('the kind check follows the kinds the server can send to', () => {
  const ok = { name: 'Pager', kind: 'pager', url: 'https://pager.example/in/x' };
  const hosts = ['pager.example:443'];
  assert.deepEqual(M.checkDestination(ok, { hosts }).map((p) => p.field), ['kind'], 'unknown without the list');
  assert.deepEqual(M.checkDestination(ok, { hosts, kinds: ['ntfy', 'pager'] }), []);
  // a kind the server no longer lists is refused, naming the kinds it does
  // list by their declared labels (2026-11-16)
  assert.deepEqual(M.checkDestination({ ...ok, kind: 'gotify', url: 'https://pager.example/message' }, { hosts, kinds: [SERVER[0], PAGER] }),
    [{ field: 'kind', text: 'Pick ntfy or a pager.' }]);
  // told nothing, the three, in the words they always had
  assert.deepEqual(M.checkDestination({ ...ok, kind: 'smtp' }, { hosts }),
    [{ field: 'kind', text: 'Pick ntfy, Gotify or a JSON webhook.' }]);
});

test('the kinds sentence is drawn from the declared labels, so a fifth kind needs no edit', () => {
  const five = [...SERVER, DISCORD, PAGER];
  assert.equal(M.kindWords(five), 'ntfy, Gotify, a JSON webhook, Discord or a pager');
  assert.equal(M.plainT('alerts_need_kind', { kinds: M.kindWords(five) }),
    'Pick ntfy, Gotify, a JSON webhook, Discord or a pager.');
  const bad = M.checkDestination({ name: 'X', kind: 'smtp', url: 'https://discord.com/api/webhooks/1' }, { kinds: five });
  assert.deepEqual(bad, [{ field: 'kind', text: 'Pick ntfy, Gotify, a JSON webhook, Discord or a pager.' }]);
});

test('a kind whose secret is required is asked for it before the page posts', () => {
  const d = { name: 'Lab channel', kind: 'discord', url: 'https://discord.com/api/webhooks/123456789012345678' };
  const hosts = ['discord.com:443'];
  assert.deepEqual(M.checkDestination(d, { hosts, kinds: [DISCORD] }),
    [{ field: 'secret', text: M.ALERTS_TEXT.alerts_need_secret }]);
  assert.deepEqual(M.checkDestination({ ...d, secret: 'discord_lab' }, { hosts, kinds: [DISCORD] }), []);
  // the address in full, token and all, is the server's to refuse; its
  // sentence says "address", so it is put beside the address
  assert.equal(M.fieldOfSentence('A Discord address stops at the webhook\'s id: the token after it goes in a named secret, never in the address.'), 'url');
  assert.equal(M.fieldOfSentence('This kind of destination needs a secret: name it, and the server reads ATLAS_ALERT_SECRET_<name>.'), 'secret');
});

test('what a destination posts is read by the fields its kind declares', () => {
  const box = { url: '  https://ntfy.example/lab  ', secret: ' ntfy_lab ' };
  assert.deepEqual(M.destinationValues(SERVER[0].fields, (n) => box[n]),
    { url: 'https://ntfy.example/lab', secret: 'NTFY_LAB' });
  assert.deepEqual(M.destinationValues(SERVER[0].fields, (n) => ({ url: 'x', secret: '' })[n]),
    { url: 'x', secret: null });
  // a kind that asks for no secret posts none, so an old one is not kept
  assert.deepEqual(M.destinationValues(PAGER.fields, (n) => box[n]), { url: 'https://ntfy.example/lab', secret: null });
});

console.log(`\n${passed} passed`);
