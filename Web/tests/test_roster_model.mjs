/* THE ROSTER's rules (NODES and the Desk, 2026-11-13), in plain node.

   Run:  node tests/test_roster_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  NO_FILTER, REVIEW_BATCH, SAVED_KEY, SEVERITY, SORT_KEY, armedLabel, batches, certTone, cleanFilter,
  daysSince, filterRows, inBatches, ipv4Number, isEmptyFilter, markedLine, mergeNeeds, readSaved,
  readSort, reviewOps, rowStanding, rowWaiting, sentence, slugFor, sortRows, staleFor, standing,
  twoPress, waiting, withSaved, withoutSaved, writeSaved, writeSort,
} from '../static/js/roster-model.js';
import * as viaDesk from '../static/js/editor/standing.js';

let passed = 0;
const pending = [];
function test(name, fn) {
  const done = (ok, e) => {
    if (ok) { passed++; console.log(`  ok  ${name}`); }
    else { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
  };
  try {
    const r = fn();
    if (r && typeof r.then === 'function') pending.push(r.then(() => done(true), (e) => done(false, e)));
    else done(true);
  } catch (e) { done(false, e); }
}

const DAY = 86400000;
const NOW = Date.parse('2026-11-13T12:00:00Z');
const ago = (days) => new Date(NOW - days * DAY).toISOString();

const SETS = [{ id: 'core', name: 'Core' }, { id: 'edge', name: 'Edge' }];
const ROWS = [
  { id: 'gw', name: 'GATEWAY', state: 'healthy', zone: 'dmz', zone_name: 'Outset', kind: 'network', role: 'switch',
    addresses: ['10.0.0.1'], services: 3, confirmed_by: 'kuma', reviewed: true, reviewed_at: ago(10), unchecked: false,
    maintenance: { now: false, next: null }, cert: { name: 'gw.example', days: 45 }, sets: ['edge'] },
  { id: 'nas', name: 'NAS', state: 'down', zone: 'core', zone_name: 'Infra', kind: 'physical',
    addresses: ['10.0.0.20', '10.0.1.20'], services: 12, confirmed_by: 'prometheus', reviewed: false, unchecked: true,
    maintenance: { now: false, next: '2026-11-15T03:00:00Z' }, cert: { name: 'nas.example', days: 5 }, sets: ['core'] },
  { id: 'vm9', name: 'downloads', state: 'degraded', zone: 'core', zone_name: 'Infra', kind: 'vm',
    addresses: ['10.0.0.9'], services: 0, confirmed_by: null, reviewed: true, reviewed_at: ago(90), unchecked: false,
    maintenance: { now: true, next: null }, cert: null, sets: ['core', 'edge'] },
  { id: 'old', name: 'Kakariko', state: null, zone: 'home', zone_name: 'Home', kind: 'unknown',
    addresses: [], services: 1, confirmed_by: 'kuma', reviewed: true, reviewed_at: ago(89), unchecked: true,
    changed_since_review: true, maintenance: null, cert: { name: 'k.example', days: -2 }, sets: [] },
  { id: 'sl', name: 'Zora', state: 'slumbering', zone: 'home', zone_name: 'Home', kind: 'vm',
    addresses: ['zora.example'], services: 2, reviewed: true, reviewed_at: ago(91), unchecked: false,
    maintenance: { now: false, next: '2026-11-14T03:00:00Z' }, cert: { name: 'z.example', days: 29 }, sets: [] },
  { id: 'mt', name: 'Edge', state: 'maintenance', zone: 'dmz', zone_name: 'Outset', kind: 'vm',
    addresses: ['10.0.0.100'], services: 4, confirmed_by: 'unifi', unchecked: false, sets: [] },
];
const ids = (rows) => rows.map((r) => r.id);

/* ── the Desk's rules, now shared ── */

test('the Desk reads the very same rules through editor/standing.js', () => {
  assert.equal(viaDesk.standing, standing);
  assert.equal(viaDesk.sentence, sentence);
  assert.equal(viaDesk.waiting, waiting);
});

test('the standing cases the Desk relied on still hold', () => {
  assert.equal(standing({ id: 'old' }), 'unknown');
  assert.equal(standing({ provenance: { reviewed: false } }), 'unchecked');
  assert.equal(standing({ provenance: { reviewed: true, reviewed_at: '2026-11-10T08:00:00Z' } }), 'checked');
  assert.equal(standing({ provenance: { reviewed: true, reviewed_at: '2026-11-10T08:00:00Z', changed_at: '2026-11-11T08:00:00Z' } }), 'changed');
  assert.equal(standing({ provenance: { reviewed: true } }), 'changed');
  assert.equal(standing({ provenance: { reviewed: true, reviewed_at: '2026-11-10T08:00:00Z', changed_since_review: true } }), 'changed');
  assert.equal(standing({ provenance: { reviewed: 'true' } }), 'unknown');
  assert.equal(waiting([{ provenance: { reviewed: false } }, { id: 'x' }]),
    'None of the 2 places here has been checked by a person. 1 came from an import, 1 was charted before the map kept this record.');
});

test('a roster row: the server\'s `unchecked` decides waiting, the flat stamp says why', () => {
  assert.equal(rowStanding(ROWS[0]), 'checked');
  assert.equal(rowStanding(ROWS[1]), 'unchecked');
  assert.equal(rowStanding(ROWS[3]), 'changed');
  assert.equal(rowStanding(ROWS[5]), 'unknown');                       // no stamp at all
  // the server says waiting where the flat fields alone would say checked
  // (a change later than the review, which the row does not carry)
  assert.equal(rowStanding({ reviewed: true, reviewed_at: ago(1), unchecked: true }), 'changed');
  // no `unchecked` given: the rule is worked out from the stamp
  assert.equal(rowStanding({ reviewed: true, reviewed_at: ago(1) }), 'checked');
  assert.equal(rowStanding(null), 'unknown');
  assert.deepEqual(ROWS.filter(rowWaiting).map((r) => r.id), ['nas', 'old']);
  assert.equal(rowWaiting({ reviewed: false }), true);
});

/* ── the writes: batches of 400, two presses ── */

test('batches cut at 400 by default and keep the order', () => {
  const list = Array.from({ length: 1001 }, (_, i) => `p${i}`);
  const parts = batches(list);
  assert.equal(REVIEW_BATCH, 400);
  assert.deepEqual(parts.map((p) => p.length), [400, 400, 201]);
  assert.deepEqual(parts.flat(), list);
  assert.deepEqual(batches(list.slice(0, 400)).map((p) => p.length), [400]);
  assert.deepEqual(batches([]), []);
  assert.deepEqual(batches(['a', 'b', 'c'], 2), [['a', 'b'], ['c']]);
});

test('review ops are one per place, in the Desk\'s shape', () => {
  assert.deepEqual(reviewOps(['gw', 'nas']), [
    { op: 'review', section: 'nodes', id: 'gw' }, { op: 'review', section: 'nodes', id: 'nas' }]);
});

test('inBatches saves each part in turn and stops at a refusal', async () => {
  const seen = [];
  const all = await inBatches(Array.from({ length: 900 }, (_, i) => i), async (part) => { seen.push(part.length); return { ok: true }; });
  assert.deepEqual(seen, [400, 400, 100]);
  assert.deepEqual(all, { done: 900, stopped: false });
  let calls = 0;
  const stopped = await inBatches(Array.from({ length: 900 }, (_, i) => i), async () => (++calls === 2 ? null : {}));
  assert.deepEqual(stopped, { done: 400, stopped: true });
  assert.equal(calls, 2);
});

test('two presses: the first counts and arms, the second writes what was counted', () => {
  const arm = twoPress();
  let shown = ['a', 'b'];
  assert.deepEqual(arm.press(() => shown), { armed: ['a', 'b'] });
  shown = ['a', 'b', 'c'];                                   // the second press does not recount
  assert.deepEqual(arm.press(() => shown), { write: ['a', 'b'] });
  assert.equal(arm.armed, null);
  assert.deepEqual(arm.press(() => []), { none: true });
  arm.press(() => ['x']);
  arm.disarm();
  assert.deepEqual(arm.press(() => ['y']), { armed: ['y'] });
  assert.equal(armedLabel(1), 'Yes, I have checked this one');
  assert.equal(armedLabel(7), 'Yes, I have checked these 7');
  assert.equal(markedLine(1), 'Marked as checked.');
  assert.equal(markedLine(3), '3 marked as checked.');
});

/* ── sorting ── */

test('state sorts worst first, unknown last, and reverses with unknown still last', () => {
  assert.deepEqual(SEVERITY, ['down', 'degraded', 'maintenance', 'slumbering', 'healthy']);
  assert.deepEqual(ids(sortRows(ROWS, 'state', 'asc')), ['nas', 'vm9', 'mt', 'sl', 'gw', 'old']);
  assert.deepEqual(ids(sortRows(ROWS, 'state', 'desc')), ['gw', 'sl', 'mt', 'vm9', 'nas', 'old']);
});

test('names sort without regard to case', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'name', 'asc')), ['mt', 'gw', 'old', 'nas', 'vm9', 'sl']);
  assert.deepEqual(ids(sortRows(ROWS, 'name', 'desc')), ['sl', 'vm9', 'nas', 'old', 'gw', 'mt']);
});

test('addresses sort as IPv4 numbers, names after them, none last', () => {
  assert.equal(ipv4Number('10.0.0.9') < ipv4Number('10.0.0.20'), true);
  assert.equal(ipv4Number('10.0.0.256'), null);
  assert.equal(ipv4Number('zora.example'), null);
  assert.equal(ipv4Number('10.0.0.0/24'), ipv4Number('10.0.0.0'));
  // as text 10.0.0.100 < 10.0.0.20 < 10.0.0.9; as numbers it is the other way
  assert.deepEqual(ids(sortRows(ROWS, 'addresses', 'asc')), ['gw', 'vm9', 'nas', 'mt', 'sl', 'old']);
  assert.deepEqual(ids(sortRows(ROWS, 'addresses', 'desc')), ['sl', 'mt', 'nas', 'vm9', 'gw', 'old']);
});

test('the other columns: network, kind, services, confirmed by, sets', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'zone', 'asc')), ['old', 'sl', 'nas', 'vm9', 'mt', 'gw']);
  assert.deepEqual(ids(sortRows(ROWS, 'kind', 'asc')), ['gw', 'nas', 'old', 'mt', 'vm9', 'sl']);   // ties by name
  assert.deepEqual(ids(sortRows(ROWS, 'services', 'asc')), ['vm9', 'old', 'sl', 'gw', 'mt', 'nas']);
  assert.deepEqual(ids(sortRows(ROWS, 'services', 'desc')), ['nas', 'mt', 'gw', 'sl', 'old', 'vm9']);
  assert.deepEqual(ids(sortRows(ROWS, 'confirmed_by', 'asc')), ['gw', 'old', 'nas', 'mt', 'vm9', 'sl']);
  assert.deepEqual(ids(sortRows(ROWS, 'sets', 'asc', SETS)), ['nas', 'vm9', 'gw', 'mt', 'old', 'sl']);
});

test('dates: reviewed by when, never reviewed last either way', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'reviewed', 'asc')), ['sl', 'vm9', 'old', 'gw', 'mt', 'nas']);
  assert.deepEqual(ids(sortRows(ROWS, 'reviewed', 'desc')), ['gw', 'old', 'vm9', 'sl', 'mt', 'nas']);
});

test('maintenance: open now first, then the nearest next start, none last', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'maintenance', 'asc')), ['vm9', 'sl', 'nas', 'mt', 'gw', 'old']);
  assert.deepEqual(ids(sortRows(ROWS, 'maintenance', 'desc')).slice(-3), ['mt', 'gw', 'old']);
});

test('certificates by days left, lapsed first, none last either way', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'cert', 'asc')), ['old', 'nas', 'sl', 'gw', 'mt', 'vm9']);
  assert.deepEqual(ids(sortRows(ROWS, 'cert', 'desc')), ['gw', 'sl', 'nas', 'old', 'mt', 'vm9']);
});

test('sorting never changes the list it was given, and an unknown key sorts by name', () => {
  const before = ids(ROWS);
  sortRows(ROWS, 'cert', 'desc');
  assert.deepEqual(ids(ROWS), before);
  assert.deepEqual(ids(sortRows(ROWS, 'nonsense')), ids(sortRows(ROWS, 'name')));
  assert.deepEqual(sortRows(null), []);
});

/* ── filtering ── */

test('text finds a name, an id, an address, a role or a network, any case', () => {
  assert.deepEqual(ids(filterRows(ROWS, { text: 'nas' }, NOW)), ['nas']);
  assert.deepEqual(ids(filterRows(ROWS, { text: 'VM9' }, NOW)), ['vm9']);
  assert.deepEqual(ids(filterRows(ROWS, { text: '10.0.1.' }, NOW)), ['nas']);
  assert.deepEqual(ids(filterRows(ROWS, { text: 'switch' }, NOW)), ['gw']);
  assert.deepEqual(ids(filterRows(ROWS, { text: 'outset' }, NOW)), ['gw', 'mt']);
  assert.deepEqual(ids(filterRows(ROWS, { text: '  infra   downloads ' }, NOW)), ['vm9']);   // every word must match
  assert.deepEqual(ids(filterRows(ROWS, { text: 'nothing-like-it' }, NOW)), []);
});

test('state, network, kind and set each narrow it; unknown state is its own pick', () => {
  assert.deepEqual(ids(filterRows(ROWS, { state: 'down' }, NOW)), ['nas']);
  assert.deepEqual(ids(filterRows(ROWS, { state: 'unknown' }, NOW)), ['old']);
  assert.deepEqual(ids(filterRows(ROWS, { zone: 'core' }, NOW)), ['nas', 'vm9']);
  assert.deepEqual(ids(filterRows(ROWS, { kind: 'vm' }, NOW)), ['vm9', 'sl', 'mt']);
  assert.deepEqual(ids(filterRows(ROWS, { set: 'edge' }, NOW)), ['gw', 'vm9']);
});

test('unchecked keeps what a person still has to look at', () => {
  assert.deepEqual(ids(filterRows(ROWS, { unchecked: true }, NOW)), ['nas', 'old']);
});

test('not checked in 90 days: exactly 90 days old counts, 89 does not, never always does', () => {
  assert.equal(staleFor({ reviewed: true, reviewed_at: ago(90) }, 90, NOW), true);
  assert.equal(staleFor({ reviewed: true, reviewed_at: new Date(NOW - 90 * DAY + 1).toISOString() }, 90, NOW), false);
  assert.equal(staleFor({ reviewed: true, reviewed_at: ago(89) }, 90, NOW), false);
  assert.equal(staleFor({ reviewed: false }, 90, NOW), true);
  assert.equal(staleFor({ reviewed: true }, 90, NOW), true);             // checked, but cannot say when
  assert.deepEqual(ids(filterRows(ROWS, { staleDays: 90 }, NOW)), ['nas', 'vm9', 'sl', 'mt']);
});

test('the criteria combine, and an empty filter shows everything', () => {
  assert.deepEqual(ids(filterRows(ROWS, { zone: 'core', staleDays: 90, text: '10.0.0' }, NOW)), ['nas', 'vm9']);
  assert.deepEqual(ids(filterRows(ROWS, { zone: 'core', state: 'degraded', set: 'edge' }, NOW)), ['vm9']);
  assert.deepEqual(ids(filterRows(ROWS, { kind: 'vm', unchecked: true }, NOW)), []);
  assert.deepEqual(ids(filterRows(ROWS, {}, NOW)), ids(ROWS));
  assert.equal(isEmptyFilter(NO_FILTER), true);
  assert.equal(isEmptyFilter({ text: '   ' }), true);
  assert.equal(isEmptyFilter({ staleDays: 90 }), false);
});

/* ── what the browser remembers ── */

const memory = (init = {}) => {
  const m = { ...init };
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, m };
};
const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };

test('saved filters round-trip, replace by name, and are forgotten', () => {
  const store = memory();
  let list = withSaved([], 'Down in core', { zone: 'core', state: 'down', junk: 1 }, { key: 'cert', dir: 'desc' });
  list = withSaved(list, 'old ones', { staleDays: 90 });
  list = withSaved(list, 'DOWN IN CORE', { zone: 'core' });                // same name: replaced in place
  assert.equal(list.length, 2);
  assert.equal(list[0].name, 'DOWN IN CORE');
  assert.equal(writeSaved(store, list), true);
  assert.ok(store.m[SAVED_KEY]);
  const back = readSaved(store);
  assert.deepEqual(back.map((s) => s.name), ['DOWN IN CORE', 'old ones']);
  assert.deepEqual(back[0].filter, { ...NO_FILTER, zone: 'core' });
  assert.equal(back[1].filter.staleDays, 90);
  assert.deepEqual(withoutSaved(back, 'old ones').map((s) => s.name), ['DOWN IN CORE']);
  assert.deepEqual(withSaved(back, '   ', {}), back);                      // no name, no save
});

test('storage that throws, or holds junk, never throws back', () => {
  assert.deepEqual(readSaved(throwing), []);
  assert.equal(writeSaved(throwing, []), false);
  assert.deepEqual(readSort(throwing), { key: 'name', dir: 'asc' });
  assert.equal(writeSort(throwing, { key: 'cert', dir: 'desc' }), false);
  assert.deepEqual(readSaved(null), []);
  assert.deepEqual(readSaved(memory({ [SAVED_KEY]: '{not json' })), []);
  assert.deepEqual(readSaved(memory({ [SAVED_KEY]: '{"a":1}' })), []);
  assert.deepEqual(readSaved(memory({ [SAVED_KEY]: JSON.stringify([null, { name: '' }, { name: 'ok', filter: { state: 5, unchecked: 'yes' } }]) })),
    [{ name: 'ok', filter: { ...NO_FILTER } }]);
});

test('the current sort is remembered, and a bad one falls back to name', () => {
  const store = memory();
  assert.equal(writeSort(store, { key: 'addresses', dir: 'desc' }), true);
  assert.equal(SORT_KEY, 'atlas.nodes.sort');
  assert.deepEqual(readSort(store), { key: 'addresses', dir: 'desc' });
  assert.deepEqual(readSort(memory({ [SORT_KEY]: '{"key":"evil","dir":"asc"}' })), { key: 'name', dir: 'asc' });
  assert.deepEqual(readSort(memory({ [SORT_KEY]: '{"key":"cert","dir":"up"}' })), { key: 'name', dir: 'asc' });
});

test('cleanFilter keeps only what a filter may hold', () => {
  assert.deepEqual(cleanFilter({ text: 'a', staleDays: '90', unchecked: true, extra: 'x' }),
    { ...NO_FILTER, text: 'a', staleDays: 90, unchecked: true });
  assert.deepEqual(cleanFilter('nope'), { ...NO_FILTER });
  assert.equal(cleanFilter({ staleDays: -4 }).staleDays, 0);
});

/* ── cell helpers ── */

test('days since, certificate tone, slugs and needs', () => {
  assert.equal(daysSince(ago(12), NOW), 12);
  assert.equal(daysSince('not a date', NOW), null);
  assert.equal(certTone(45), '');
  assert.equal(certTone(30), 'warn');
  assert.equal(certTone(31), '');
  assert.equal(certTone(8), 'warn');
  assert.equal(certTone(7), 'down');
  assert.equal(certTone(-1), 'down');
  assert.equal(certTone(null), '');
  assert.equal(slugFor('Sunday patching!', []), 'sunday-patching');
  assert.equal(slugFor('Core', ['core', 'core-2']), 'core-3');
  assert.equal(slugFor('!!!', [], 'set'), 'set');
  assert.match(slugFor('Été à Kakariko', []), /^[a-z0-9][a-z0-9._-]*$/);
  assert.deepEqual(mergeNeeds('vm9', ['gw'], ['nas', 'gw', 'vm9']), ['gw', 'nas']);   // never itself, never twice
  assert.deepEqual(mergeNeeds('vm9', undefined, ['vm9']), []);
});

await Promise.all(pending);
console.log(`\n${passed} passed`);
