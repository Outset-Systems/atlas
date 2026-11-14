/* ALERTS' words and checks, in plain node (2026-11-13, the views' stage 4):
   the rule's one sentence (0 minutes, several states, each kind of target,
   a target the map no longer shows), what the page checks before it posts,
   how to turn alerts on from each missing piece, a send's outcome, and a
   line of the delivery log. Every phrase has its plain twin in plain.json.

   Run:  node tests/test_alerts_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as M from '../static/js/alerts-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const DATA = {
  nodes: [{ id: 'core', name: 'Core' }, { id: 'nas', name: 'NAS' }],
  sets: [{ id: 'web', name: 'Web', places: ['core'] }],
  zones: [{ id: 'dmz', name: 'DMZ' }],
};
const DESTS = [{ id: 'lab-ntfy', name: 'Lab ntfy', kind: 'ntfy', url: 'https://ntfy.example/lab' }];
const CTX = { data: DATA, destinations: DESTS };
const rule = (over = {}) => ({
  id: 'r1', name: 'Core down', enabled: true, target: { kind: 'place', id: 'core' },
  to: ['down'], for_minutes: 5, destination: 'lab-ntfy', ...over,
});

test('every phrase has a plain fallback, and plain.json says the same', () => {
  const plain = JSON.parse(readFileSync(new URL('../themes/plain.json', import.meta.url), 'utf8')).text;
  for (const [k, v] of Object.entries(M.ALERTS_TEXT)) {
    assert.ok(k.startsWith('alerts_') || k === 'annals_sent', k);
    assert.ok(typeof v === 'string' && v.length > 0, k);
    assert.equal(plain[k], v, `plain.json text.${k}`);
  }
  assert.equal(plain.view_alerts, 'ALERTS');
  assert.equal(M.fill('{a} and {b}', { a: 1 }), '1 and {b}');
});

test('the rule in one sentence, with a wait', () => {
  assert.equal(M.ruleSentence(rule(), CTX),
    'When Core goes down and stays for 5 minutes, send to Lab ntfy.');
  assert.equal(M.ruleSentence(rule({ for_minutes: 1 }), CTX),
    'When Core goes down and stays for 1 minute, send to Lab ntfy.');
  assert.equal(M.ruleSentence(rule({ for_minutes: 60 }), CTX),
    'When Core goes down and stays for an hour, send to Lab ntfy.');
  assert.equal(M.ruleSentence(rule({ for_minutes: 120 }), CTX),
    'When Core goes down and stays for 2 hours, send to Lab ntfy.');
});

test('0 minutes reads "at once", and so does a missing wait', () => {
  assert.equal(M.ruleSentence(rule({ for_minutes: 0 }), CTX), 'When Core goes down, send to Lab ntfy at once.');
  assert.equal(M.ruleSentence(rule({ for_minutes: undefined }), CTX), 'When Core goes down, send to Lab ntfy at once.');
});

test('several states read as a list', () => {
  assert.equal(M.ruleSentence(rule({ to: ['down', 'degraded'], for_minutes: 0 }), CTX),
    'When Core goes down or degraded, send to Lab ntfy at once.');
  assert.equal(M.ruleSentence(rule({ to: ['down', 'degraded', 'maintenance'], for_minutes: 0 }), CTX),
    'When Core goes down, degraded or into maintenance, send to Lab ntfy at once.');
  assert.equal(M.ruleSentence(rule({ to: ['healthy'], for_minutes: 10 }), CTX),
    'When Core goes up and stays for 10 minutes, send to Lab ntfy.');
  assert.equal(M.ruleSentence(rule({ to: [] }), CTX),
    'When Core goes anywhere yet and stays for 5 minutes, send to Lab ntfy.');
});

test('each kind of target', () => {
  assert.equal(M.ruleSentence(rule({ target: { kind: 'set', id: 'web' }, for_minutes: 0 }), CTX),
    'When any place in the set Web goes down, send to Lab ntfy at once.');
  assert.equal(M.ruleSentence(rule({ target: { kind: 'network', id: 'dmz' }, for_minutes: 0 }), CTX),
    'When any place on the network DMZ goes down, send to Lab ntfy at once.');
  assert.equal(M.targetPhrase({ kind: 'place', id: 'nas' }, DATA), 'NAS');
});

test('a target the map no longer shows, an unread map, and no destination', () => {
  assert.equal(M.targetPhrase({ kind: 'place', id: 'gone' }, DATA), 'a place no longer on the map (gone)');
  assert.equal(M.targetPhrase({ kind: 'set', id: 'old' }, DATA), 'a set that no longer exists (old)');
  assert.equal(M.targetPhrase({ kind: 'network', id: 'x' }, DATA), 'a network no longer on the map (x)');
  // the map not read yet: the id, never "gone"
  assert.equal(M.targetPhrase({ kind: 'place', id: 'core' }, null), 'core');
  assert.equal(M.targetPhrase(null, DATA), 'nothing yet');
  assert.equal(M.ruleSentence(rule({ destination: '' , for_minutes: 0 }), CTX),
    'When Core goes down, send to nowhere yet at once.');
  assert.equal(M.ruleSentence(rule({ destination: 'phone', for_minutes: 0 }), CTX),
    'When Core goes down, send to phone at once.');
});

test('the targets to pick from, by name', () => {
  assert.deepEqual(M.targetOptions(DATA, 'place'), [['nas', 'NAS'], ['core', 'Core']].sort((a, b) => a[1].localeCompare(b[1])));
  assert.deepEqual(M.targetOptions(DATA, 'set'), [['web', 'Web']]);
  assert.deepEqual(M.targetOptions(null, 'network'), []);
});

test('a rule is checked before it is posted', () => {
  assert.deepEqual(M.checkRule(rule(), { destinations: DESTS }), []);
  const fields = (r, d = DESTS) => M.checkRule(r, { destinations: d }).map((p) => p.field);
  assert.deepEqual(fields(rule({ name: '  ' })), ['name']);
  assert.deepEqual(fields(rule({ to: [] })), ['to']);
  assert.deepEqual(fields(rule({ destination: '' })), ['destination']);
  assert.deepEqual(fields(rule({ target: { kind: 'place', id: '' } })), ['target']);
  assert.deepEqual(fields(rule({ for_minutes: -1 })), ['for_minutes']);
  assert.deepEqual(fields(rule({ for_minutes: 2.5 })), ['for_minutes']);
  assert.deepEqual(fields(rule({ for_minutes: 0 })), []);
  const none = M.checkRule(rule(), { destinations: [] });
  assert.deepEqual(none, [{ field: 'destination', text: 'Add a destination first.' }]);
  assert.equal(M.checkRule(rule({ name: '' }), CTX)[0].text, 'Name it.');
  assert.equal(M.checkRule(rule({ to: [] }), CTX)[0].text, 'Pick at least one state.');
  assert.equal(M.checkRule(rule({ destination: '' }), CTX)[0].text, 'Pick where to send it.');
});

test('a destination is checked before it is posted', () => {
  const hosts = ['ntfy.example:443', 'gotify.example:8080'];
  const ok = { name: 'Lab ntfy', kind: 'ntfy', url: 'https://ntfy.example/lab', secret: 'NTFY_LAB' };
  assert.deepEqual(M.checkDestination(ok, { hosts }), []);
  const one = (over) => M.checkDestination({ ...ok, ...over }, { hosts }).map((p) => `${p.field}: ${p.text}`);
  assert.deepEqual(one({ name: '' }), ['name: Name it.']);
  assert.deepEqual(one({ url: '' }), ['url: Give the address to send to.']);
  assert.deepEqual(one({ url: 'ftp://ntfy.example/x' }), ['url: The address must start with https:// or http://.']);
  assert.deepEqual(one({ url: 'https://u:p@ntfy.example/x' }), ['url: The address may not carry a user name or password. Name a secret instead.']);
  assert.deepEqual(one({ url: 'https://ntfy.example/x?token=1' }), ['url: The address may not carry a query (?…). Name a secret instead.']);
  assert.deepEqual(one({ url: 'https://elsewhere.example/x' }), ['url: elsewhere.example:443 is not in ATLAS_ALERT_HOSTS, so Atlas will not send there.']);
  assert.deepEqual(one({ kind: 'gotify', url: 'http://gotify.example:8080' }), []);
  assert.deepEqual(one({ kind: 'gotify', url: 'https://gotify.example' }),
    ['url: gotify.example:443 is not in ATLAS_ALERT_HOSTS, so Atlas will not send there.'], 'the port is part of the allowed host');
  assert.deepEqual(one({ secret: 'no spaces' }),
    ['secret: A secret\'s name is capitals, digits and _ only, at most 40 of them, as NTFY_LAB.']);
  assert.deepEqual(one({ secret: 'X'.repeat(41) }).length, 1);
  assert.deepEqual(one({ url: 'https://ntfy.example/' }), ['url: An ntfy address names its topic, as https://ntfy.example/atlas.']);
  assert.deepEqual(one({ url: 'https://ntfy.example/lab#x' }), ['url: The address may not carry a fragment (#…).']);
  assert.deepEqual(one({ kind: 'gotify', url: 'http://gotify.example:8080/' }), []);
  assert.deepEqual(one({ kind: 'gotify', url: 'http://gotify.example:8080/message' }), []);
  assert.deepEqual(one({ kind: 'gotify', url: 'http://gotify.example:8080/other' }),
    ['url: A Gotify address is the server itself, or ends in /message.']);
  // a host listed without its port allows nothing, as on the server
  assert.equal(M.hostAllowed('https://ntfy.example/x', ['ntfy.example']), false);
  assert.equal(M.hostAllowed('https://NTFY.example/x', ['ntfy.example:443']), true);
  assert.deepEqual(one({ secret: '' }), []);
  assert.deepEqual(one({ kind: 'smtp' }), ['kind: Pick ntfy, Gotify or a JSON webhook.']);
  // with no list the server decides
  assert.deepEqual(M.checkDestination({ ...ok, url: 'https://elsewhere.example/x' }, { hosts: [] }), []);
  assert.equal(M.secretName(' ntfy_lab '), 'NTFY_LAB');
  assert.equal(M.secretName(''), null);
});

test('the digest is checked, its destination only when it is sent, and reads as a sentence', () => {
  const g = { enabled: false, hour: 8, destination: null, cert_days: 30, review_days: 90, drift: false, uncharted: false };
  assert.deepEqual(M.checkDigest(g, { destinations: [] }), []);
  assert.deepEqual(M.checkDigest({ ...g, enabled: true, destination: 'lab-ntfy' }, { destinations: DESTS }), []);
  assert.deepEqual(M.checkDigest({ ...g, enabled: true, hour: 24, destination: '' }, { destinations: DESTS }).map((p) => p.field),
    ['hour', 'destination']);
  // the server keeps the days whether it is sent or not: 1 to 365, 1 to 3650
  assert.deepEqual(M.checkDigest({ ...g, cert_days: 0, review_days: 3651 }).map((p) => p.text),
    ['Certificate days are a whole number from 1 to 365.', 'Review days are a whole number from 1 to 3650.']);
  assert.equal(M.digestSentence({ enabled: false }), 'The daily digest is not sent.');
  assert.equal(M.digestSentence({ enabled: true, hour: 8, destination: 'lab-ntfy', cert_days: 30, review_days: 90, drift: true },
    { destinations: DESTS }),
  'Every day at 08:00, send to Lab ntfy: certificates lapsing within 30 days, places not checked in 90 days and monitors the map has not charted.');
  assert.equal(M.digestSentence({ enabled: true, hour: 7, destination: 'lab-ntfy', cert_days: 14, review_days: 30 }, { destinations: DESTS }),
    'Every day at 07:00, send to Lab ntfy: certificates lapsing within 14 days and places not checked in 30 days.');
});

test('the uncharted condition: on only when the server says so', () => {
  assert.deepEqual(M.unchartedSupport({}), { ok: false, why: 'not supported yet' });
  assert.deepEqual(M.unchartedSupport({ supports: { uncharted: true } }), { ok: true, why: '' });
  assert.deepEqual(M.unchartedSupport({ unsupported: { uncharted: 'the discovery read fetches on its own' } }),
    { ok: false, why: 'the discovery read fetches on its own' });
  assert.deepEqual(M.unchartedSupport({ problems: ['digest.uncharted: not offered on this Atlas'] }),
    { ok: false, why: 'digest.uncharted: not offered on this Atlas' });
});

test('off: says which setting is missing, and never claims what it cannot know', () => {
  const both = M.onOff({ enabled: false, hosts: [], poll_seconds: 60, poll_running: true, public_url_set: true });
  assert.equal(both.off, true);
  assert.equal(both.title, 'Alerts are off.');
  assert.match(both.lines[0], /ATLAS_ALERTS=1, and ATLAS_ALERT_HOSTS/);
  assert.match(both.lines[0], /No host is listed yet\./);
  assert.match(both.lines[1], /Restart Atlas/);
  assert.deepEqual(both.notes, []);
  const flag = M.onOff({ enabled: false, hosts: ['ntfy.example:443'], poll_seconds: 60, public_url_set: true });
  assert.equal(flag.off, true);
  assert.match(flag.lines[0], /^The hosts it may send to are listed in ATLAS_ALERT_HOSTS\. Set ATLAS_ALERTS=1/);
  // the flag is set but no host: the server says `on: false`
  const hostless = M.onOff({ enabled: true, on: false, hosts: [], poll_seconds: 60, poll_running: true, public_url_set: true });
  assert.equal(hostless.off, true);
  assert.match(hostless.lines[0], /^ATLAS_ALERTS is set, but ATLAS_ALERT_HOSTS lists no host/);
  // the server's `on` is the whole answer when it gives one
  assert.equal(M.onOff({ enabled: true, on: true, hosts: ['ntfy.example:443'] }).off, false);
  // nothing said at all is off
  assert.equal(M.onOff(null).off, true);
});

test('on: the poll and the public address are notes, not off', () => {
  const on = { enabled: true, hosts: ['ntfy.example:443'], poll_seconds: 60, poll_running: true, public_url_set: true };
  assert.deepEqual(M.onOff(on), { off: false, title: '', lines: [], notes: [] });
  assert.deepEqual(M.onOff({ ...on, poll_seconds: 0 }).notes,
    ['Alerts need the annals\' poll; it is off. Set ATLAS_ANNALS_POLL above 0 and run Atlas under gunicorn, or nothing will be sent.']);
  assert.deepEqual(M.onOff({ ...on, poll_running: false }).notes,
    ['Alerts need the annals\' poll, and it is not running: it runs under gunicorn, never under flask run. Nothing is sent until it does.']);
  assert.deepEqual(M.onOff({ ...on, public_url_set: false }).notes,
    ['ATLAS_PUBLIC_URL is not set, so messages will carry no link to the place.']);
  assert.equal(M.onOff({ ...on, poll_seconds: 0, public_url_set: false }).notes.length, 2);
  assert.equal(M.onOff({ ...on, poll_seconds: 0 }).off, false);
});

test('the status strip', () => {
  const clock = () => '12:03';
  assert.deepEqual(M.statusBits({ hosts: ['ntfy.example:443', 'gotify.example:8080'], poll_seconds: 60, poll_running: true,
    last_tick: '2026-11-13T12:03:00Z' }, clock),
  ['may send to ntfy.example:443, gotify.example:8080', 'looks every 60 s', 'last looked 12:03']);
  assert.deepEqual(M.statusBits({ hosts: [], poll_seconds: 0, last_tick: null }, clock),
    ['no host is allowed', 'the poll is off', 'has not looked yet']);
  assert.equal(M.statusBits({ hosts: [], poll_seconds: 60, poll_running: false }, clock)[1], 'the poll is not running');
  assert.equal(M.toMs(1763035380), 1763035380000);
  assert.equal(M.toMs(1763035380000), 1763035380000);
  assert.equal(M.toMs('nonsense'), null);
});

test('the outcome of a send, in one word, and nothing of the response', () => {
  assert.equal(M.outcomeWord('delivered', 200), 'delivered');
  assert.equal(M.outcomeWord('refused', 403), 'refused (HTTP 403)');
  assert.equal(M.outcomeWord('refused'), 'refused');
  assert.equal(M.outcomeWord('unreachable'), 'unreachable');
  assert.equal(M.outcomeWord('blocked'), 'blocked');
  assert.equal(M.testLine({ outcome: 'delivered', status: 200, why: '' }), 'delivered');
  assert.equal(M.testLine({ outcome: 'blocked', why: 'not an allowed address' }), 'blocked: not an allowed address');
  assert.equal(M.testLine({ outcome: 'refused', status: 401, why: 'the secret was not accepted' }),
    'refused (HTTP 401): the secret was not accepted');
  assert.equal(M.outcomeTone('delivered'), 'up');
  assert.equal(M.outcomeTone('refused'), 'warn');
  assert.equal(M.outcomeTone('unreachable'), 'down');
});

test('a line of the delivery log, and newest first', () => {
  const ctx = { rules: [rule()], destinations: DESTS };
  assert.equal(M.deliveryLine({ rule: 'r1', destination: 'lab-ntfy', events: [4, 5], outcome: 'delivered', status: 200 }, ctx),
    'Rule “Core down”, 2 changes, to Lab ntfy: delivered.');
  assert.equal(M.deliveryLine({ rule: 'r1', destination: 'lab-ntfy', events: [4], outcome: 'refused', status: 500, why: 'the server failed' }, ctx),
    'Rule “Core down”, 1 change, to Lab ntfy: refused (HTTP 500): the server failed.');
  assert.equal(M.deliveryLine({ rule: null, destination: 'lab-ntfy', events: [], outcome: 'unreachable' }, ctx),
    'A test to Lab ntfy: unreachable.');
  assert.equal(M.deliveryLine({ rule: 'digest', destination: 'lab-ntfy', events: 0, outcome: 'delivered' }, ctx),
    'The daily digest to Lab ntfy: delivered.');
  assert.equal(M.deliveryLine({ rule: 'gone-rule', destination: 'gone-dest', events: 3, outcome: 'blocked' }, ctx),
    'Rule “gone-rule”, 3 changes, to gone-dest: blocked.');
  assert.deepEqual(M.newestFirst([{ at: '2026-11-13T10:00:00Z', n: 1 }, { at: '2026-11-13T12:00:00Z', n: 2 }, null])
    .map((r) => r.n), [2, 1]);
});

test('the server\'s sentences are sorted to the item and its field', () => {
  const got = M.sortProblems([
    'rule core-down: it needs one or more states from degraded, down, healthy, maintenance, slumbering',
    'rule core-down: that place cannot be alerted on. It is not on the map, or a viewer with no access groups cannot see it',
    'rule core-down: how long it must stay is a whole number of minutes from 0 to 1440',
    'rule core-down: it sends to a destination that does not exist',
    'rule core-down: its name must be text of at most 80 characters',
    'rule other: its note must be text of at most 300 characters',
    'at most 50 rules',
  ], 'rules[0]', 'rule core-down');
  assert.deepEqual(Object.keys(got.byField).sort(), ['destination', 'for_minutes', 'name', 'target', 'to']);
  assert.equal(got.byField.to[0], 'It needs one or more states from degraded, down, healthy, maintenance, slumbering');
  assert.deepEqual(got.general, ['rule other: its note must be text of at most 300 characters', 'at most 50 rules']);
  const dest = M.sortProblems([
    'destination lab: The address carries a user name or password (user:pass@host). Name a secret instead; Atlas sends it in a header.',
    'destination lab: The address may not carry a query string (?...). A key goes in a named secret, never in the URL.',
    'destination lab: ntfy.example:443 is not in ATLAS_ALERT_HOSTS; only the operator can add a host there.',
    'destination lab: A secret is named in capitals, digits and underscores, at most 40 characters, as NTFY_LAB; Atlas reads ATLAS_ALERT_SECRET_<name>.',
    'destination lab: Give the destination a name.',
    'destination lab: The kind must be ntfy, gotify or webhook.',
  ], 'destinations[0]', 'destination lab');
  assert.equal(dest.byField.url.length, 3, 'an address that mentions a secret is still the address');
  assert.equal(dest.byField.secret.length, 1);
  assert.equal(dest.byField.name.length, 1);
  assert.equal(dest.byField.kind.length, 1);
  const digest = M.sortProblems(['digest: the hour is a whole number from 0 to 23 (the server\'s local time)',
    'digest: the digest cannot list uncharted devices yet: no feed the poll already builds carries them',
    'digest: something new'], 'digest', 'digest');
  assert.deepEqual(Object.keys(digest.byField).sort(), ['hour', 'uncharted']);
  assert.deepEqual(digest.mine, ['Something new']);
});

test('problems from a 422 are sorted to their fields', () => {
  const got = M.sortProblems([
    { field: 'rules[1].destination', message: 'no such destination' },
    { path: 'rules.1.target', problem: 'that place is hidden from a viewer with no groups' },
    { field: 'rules[0].name', message: 'not this one' },
    'the document is too large',
  ], 'rules[1]');
  assert.deepEqual(got.byField, { destination: ['no such destination'], target: ['that place is hidden from a viewer with no groups'] });
  assert.deepEqual(got.general, ['rules[0].name: not this one', 'the document is too large']);
  assert.deepEqual(M.sortProblems(['plain words'], '').general, ['plain words']);
  assert.deepEqual(M.sortProblems(null).general, []);
});

test('suspended rules, from the status list or a rule\'s own flag', () => {
  assert.deepEqual([...M.suspendedIds({ status: { suspended: ['core-down'] } })], ['core-down']);
  assert.deepEqual([...M.suspendedIds({ doc: { rules: [{ id: 'x', suspended: true }, { id: 'y' }] } })], ['x']);
  assert.equal(M.suspendedIds(null).size, 0);
});

test('new ids from names', () => {
  assert.equal(M.slugFor('Lab ntfy', []), 'lab-ntfy');
  assert.equal(M.slugFor('Lab ntfy', ['lab-ntfy']), 'lab-ntfy-2');
  assert.equal(M.slugFor('***', [], 'rule'), 'rule');
});

test('the ANNALS note beside an event that caused a send', () => {
  assert.equal(M.sentNote([{ to: 'Lab ntfy', at: 'x' }]), 'sent to Lab ntfy');
  assert.equal(M.sentNote([{ to: 'Lab ntfy' }, { to: 'Phone' }, { to: 'Lab ntfy' }]), 'sent to Lab ntfy and Phone');
  assert.equal(M.sentNote([]), '');
  assert.equal(M.sentNote(undefined), '');
});

test('the list masks a destination\'s path (a topic or webhook token)', () => {
  assert.equal(M.shownAddress('https://ntfy.example/lab-alerts'), 'https://ntfy.example/…erts');
  assert.equal(M.shownAddress('https://hooks.example:8443/api/webhooks/123/s3cretTOKEN'), 'https://hooks.example:8443/…OKEN');
  assert.equal(M.shownAddress('http://gotify.example:8080/'), 'http://gotify.example:8080');
  assert.equal(M.shownAddress('not a url'), '');
  assert.equal(M.shownAddress(undefined), '');
});

console.log(`\n${passed} passed`);
