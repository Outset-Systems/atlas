// What the Connections screen says about a token's binding and its read log.
// Run: node --test Web/tests/*.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bindNote, fromWords, readLine, readsHead } from '../static/js/connections-model.js';

test('a binding is said in words', () => {
  assert.equal(fromWords(null), 'from any address');
  assert.equal(fromWords([]), 'from any address');
  assert.equal(fromWords(['lan']), 'local network only');
  assert.equal(fromWords(['192.168.7.0/24', 'lan']), 'only from 192.168.7.0/24, the local network');
});

test('the note names the address the Atlas sees, and says when it is not local', () => {
  assert.match(bindNote({ ip: '192.168.1.20', local: true }), /sees you at 192\.168\.1\.20.*ATLAS_TRUSTED_PROXIES/);
  assert.match(bindNote({ ip: '203.0.113.9', local: false }), /not a local address/);
  assert.doesNotMatch(bindNote(undefined), /sees you/);
});

test('a line of the log: a tool with what it was asked, a route, a refusal', () => {
  assert.equal(
    readLine({ at: '2026-11-12T10:00:00Z', ip: '10.0.0.9', tool: 'atlas_place', method: 'tools/call',
               args: { place: 'nas', limit: 5 }, places: 1, bytes: 2048, status: 200 }),
    '2026-11-12T10:00:00Z · from 10.0.0.9 · atlas_place place=nas limit=5 · 1 place · 2 KB');
  assert.equal(
    readLine({ at: 'T', ip: '10.0.0.9', path: '/api/v2/lab-data', places: 18, bytes: 3 * 1048576, status: 200 }),
    'T · from 10.0.0.9 · /api/v2/lab-data · 18 places · 3.0 MB');
  assert.equal(
    readLine({ at: 'T', ip: '203.0.113.9', path: '/api/v2/maps', refused: 'outside its networks', status: 403 }),
    'T · from 203.0.113.9 · /api/v2/maps · refused: outside its networks');
  assert.equal(readLine({ at: 'T', method: 'tools/list', bytes: 10, status: 200 }),
    'T · from an unknown address · tools/list · 10 B');
});

test('markup in an argument stays text for the page to escape', () => {
  const line = readLine({ at: 'T', ip: 'x', tool: 'atlas_search', args: { query: '<img onerror=1>' }, status: 200 });
  assert.ok(line.includes('query=<img onerror=1>'));
});

test('the head says how many, for how long, and that answers are not kept', () => {
  assert.match(readsHead([], 90, 'harness'), /Nothing has been read with "harness" in the last 90 days/);
  assert.match(readsHead([{}, {}], 30, 'x'), /last 2 requests.*Kept for 30 days.*not stored/);
});

test('a line break in an argument cannot draw a second entry', () => {
  const line = readLine({ at: 'T', ip: 'x', tool: 'atlas_search',
    args: { query: 'a\n2026-01-01 · from 10.0.0.1 · atlas_place' }, status: 200 });
  assert.equal(line.split('\n').length, 1);
  assert.ok(line.includes('query=a 2026-01-01'));
});
