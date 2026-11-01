/* TRIPWIRES' reading rules, in plain node (v1.52.0).

   Run:  node tests/test_tripwire_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  ago, byFamily, expiryNote, familyOf, legacySources, listening, roster, tripLine, watchByNode,
} from '../static/js/tripwire-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const NOW = Date.parse('2026-10-19T12:00:00Z');

test('family: the row says so, else honeypot-* kinds are honeypots', () => {
  assert.equal(familyOf({ family: 'token', kind: 'honeypot-ssh' }), 'token');
  assert.equal(familyOf({ kind: 'honeypot-smb' }), 'honeypot');
  assert.equal(familyOf({ kind: 'doc-msword' }), 'token');
  assert.equal(familyOf({}), 'token');
});

test('listening: nothing configured is "unset", not "all quiet"', () => {
  assert.equal(listening({ decoys: { contact: 'off' }, webhook: { contact: 'off' } }).verdict, 'unset');
  assert.equal(listening(undefined).verdict, 'unset');
});

test('listening: a webhook nothing has reached is waiting, never all quiet', () => {
  const alone = listening({ decoys: { contact: 'off' }, webhook: { contact: 'waiting' } });
  assert.equal(alone.verdict, 'waiting');
  const beside = listening({ decoys: { contact: 'ok' }, webhook: { contact: 'waiting' } });
  assert.equal(beside.verdict, 'ok');
  assert.equal(beside.waiting, true);
});

test('listening: one lost source makes the verdict lost and names it', () => {
  const l = listening({ decoys: { contact: 'lost' }, webhook: { contact: 'ok' } });
  assert.equal(l.verdict, 'lost'); assert.deepEqual(l.lost, ['decoys']); assert.deepEqual(l.on, ['webhook']);
  assert.equal(listening({ decoys: { contact: 'ok' }, webhook: { contact: 'off' } }).verdict, 'ok');
  assert.equal(listening({ decoys: { contact: 'off' }, webhook: { contact: 'ok' } }).verdict, 'ok');
});

test('legacy sources: the feed-only reading in the same shape', () => {
  assert.equal(listening(legacySources(null)).verdict, 'unset');
  assert.equal(listening(legacySources({ kuma: 'ok' })).verdict, 'unset');
  assert.equal(listening(legacySources({ deception: 'ok' })).verdict, 'ok');
  assert.equal(listening(legacySources({ deception: 'error' })).verdict, 'lost');
});

test('roster from the overview: states become voices, loudest first', () => {
  const rows = roster({ overview: { tripwires: [
    { id: 'b', name: 'Bravo', state: 'quiet' },
    { id: 'a', name: 'Alpha', state: 'stirred' },
    { id: 'c', name: 'Charlie', state: 'lit' },
  ] } });
  assert.deepEqual(rows.map((r) => [r.id, r.voice]), [['c', 'speaking'], ['a', 'stirred'], ['b', 'silent']]);
});

test('roster with the overview still lists stones only the decoy feed knows', () => {
  // the engine is the authority on what is planted: a deployment that charts
  // no stones at all must still see the feed's (v1.52.0 regression, 10-20)
  const rows = roster({
    overview: { tripwires: [{ id: 'charted', name: 'Charted', state: 'quiet' }] },
    live: { 'charted': { state: 'speaking' }, 'feed-only': { state: 'speaking' }, 'quiet-one': { state: 'silent' } },
  });
  assert.equal(rows[0].id, 'feed-only', 'a speaking stone sorts first, charted or not');
  const ids = rows.map((r) => r.id);
  assert.ok(ids.includes('feed-only') && ids.includes('quiet-one'), 'feed-only stones are listed');
  assert.equal(rows.filter((r) => r.id === 'charted').length, 1, 'a charted stone is not listed twice');
  assert.equal(rows.find((r) => r.id === 'charted').voice, 'silent', 'the overview\'s state wins for a charted stone');
  assert.equal(rows.find((r) => r.id === 'feed-only').uncharted, true);
  // an empty overview (no stones charted) shows every feed stone
  const only = roster({ overview: { tripwires: [] }, live: { a: { state: 'silent' }, b: { state: 'stirred' } } });
  assert.deepEqual(only.map((r) => r.id).sort(), ['a', 'b']);
});

test('roster without the overview: chart merged with the feed, feed wins', () => {
  const rows = roster({
    charted: [{ id: 'x', name: 'X', host: 'h1' }, { id: 'y', name: 'Y' }],
    live: { y: { state: 'speaking' }, z: { state: 'silent', name: 'Z' } },
  });
  assert.deepEqual(rows.map((r) => [r.id, r.voice]), [['y', 'speaking'], ['x', 'unheard'], ['z', 'silent']]);
});

test('byFamily splits honeypots from tokens', () => {
  const f = byFamily([{ id: 1, kind: 'honeypot-host' }, { id: 2, kind: 'dns' }, { id: 3, family: 'honeypot' }]);
  assert.deepEqual(f.honeypot.map((r) => r.id), [1, 3]);
  assert.deepEqual(f.token.map((r) => r.id), [2]);
});

test('a trip reads as one plain line, every part optional', () => {
  assert.equal(tripLine({ signal: 'ssh login', src: '198.51.100.7', port: 22, source: 'opencanary',
                          count: 3, last_at: '2026-10-19T11:57:00Z' }, NOW),
               'ssh login · from 198.51.100.7:22 · via OpenCanary · ×3 · 3m ago');
  assert.equal(tripLine({ source: 'generic' }, NOW), 'tripped · via webhook');
  assert.equal(tripLine({ port: 445, source: 'decoys', signal: 'speaking' }, NOW),
               'speaking · on port 445 · via the decoy feed');
  assert.equal(tripLine(null), '');
});

test('the line is text: markup in a field stays in the string for esc() to handle', () => {
  const line = tripLine({ signal: '<img src=x onerror=alert(1)>', source: 'generic' }, NOW);
  assert.ok(line.startsWith('<img'), 'tripLine does not pretend to sanitise; the scene escapes');
});

test('ago: seconds, minutes, hours, days; junk is null', () => {
  assert.equal(ago('2026-10-19T11:59:30Z', NOW), '30s ago');
  assert.equal(ago('2026-10-19T09:00:00Z', NOW), '3h ago');
  assert.equal(ago('2026-10-16T12:00:00Z', NOW), '3d ago');
  assert.equal(ago('nope', NOW), null);
  assert.equal(ago(null, NOW), null);
});

test('expiry: expired, soon, later, none', () => {
  assert.deepEqual(expiryNote({ expires_in_days: -2 }), { level: 'expired', text: 'expired 2d ago' });
  assert.equal(expiryNote({ expires_in_days: 5 }).level, 'soon');
  assert.equal(expiryNote({ expires_in_days: 90, expires: '2027-01-17' }).text, 'expires 2027-01-17');
  assert.equal(expiryNote({}), null);
});

test('map layer: loudest voice per place, retired leave, unplaced still count', () => {
  const rows = [
    { id: 1, host: 'nas', voice: 'silent' },
    { id: 2, host: 'nas', voice: 'speaking' },
    { id: 3, host: 'web', voice: 'stirred' },
    { id: 4, voice: 'silent' },
    { id: 5, host: 'web', voice: 'speaking', retired: true },
  ];
  const w = watchByNode(rows, false);
  assert.deepEqual(w.nodes.get('nas'), { voice: 'speaking', count: 2 });
  assert.deepEqual(w.nodes.get('web'), { voice: 'stirred', count: 1 });
  assert.equal(w.unplaced, 1); assert.equal(w.speaking, 1); assert.equal(w.total, 4);
});

test('map layer: a lost watch draws every eye unheard', () => {
  const w = watchByNode([{ id: 1, host: 'nas', voice: 'speaking' }], true);
  assert.equal(w.nodes.get('nas').voice, 'unheard'); assert.equal(w.speaking, 0);
});

console.log(`\n${passed} passed`);
