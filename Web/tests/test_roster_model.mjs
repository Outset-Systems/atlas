/* THE ROSTER's rules (NODES and the Desk, 2026-11-13), in plain node.

   Run:  node tests/test_roster_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  NO_FILTER, REVIEW_BATCH, SAVED_KEY, SEVERITY, SORT_KEY, armedLabel, batches, certTone, cleanFilter,
  daysSince, filterRows, inBatches, inMode, modeChange, modeVia, ipv4Number, isEmptyFilter, markedLine, mergeNeeds, readSaved,
  RAIL_FIELDS, RAIL_KEY, SUMMARY_ORDER, dropUnknown, recentFor, stateCounts,
  THING_KINDS, filterThings, sortThings, thingGroups, thingKind, thingRows, filterGroups, memberList, railGroups, railPress, readRail, writeRail,
  readSort, reviewOps, rowPress, rowStanding, rowState, rowWaiting, sentence, slugFor, sortRows, staleFor, standing,
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

const COLLECTIONS = [{ id: 'core', name: 'Core' }, { id: 'edge', name: 'Edge' }];
const ROWS = [
  { id: 'gw', name: 'GATEWAY', state: 'healthy', zone: 'dmz', zone_name: 'Outset', kind: 'network', role: 'switch',
    addresses: ['10.0.0.1'], services: 3, confirmed_by: 'kuma', reviewed: true, reviewed_at: ago(10), unchecked: false,
    maintenance: { now: false, next: null }, cert: { name: 'gw.example', days: 45 }, collections: ['edge'] },
  { id: 'nas', name: 'NAS', state: 'down', zone: 'core', zone_name: 'Infra', kind: 'physical',
    addresses: ['10.0.0.20', '10.0.1.20'], services: 12, confirmed_by: 'prometheus', reviewed: false, unchecked: true,
    maintenance: { now: false, next: '2026-11-15T03:00:00Z' }, cert: { name: 'nas.example', days: 5 }, collections: ['core'] },
  { id: 'vm9', name: 'proxy', state: 'degraded', zone: 'core', zone_name: 'Infra', kind: 'vm',
    addresses: ['10.0.0.9'], services: 0, confirmed_by: null, reviewed: true, reviewed_at: ago(90), unchecked: false,
    maintenance: { now: true, next: null }, cert: null, collections: ['core', 'edge'] },
  { id: 'old', name: 'Kakariko', state: null, zone: 'home', zone_name: 'Home', kind: 'unknown',
    addresses: [], services: 1, confirmed_by: 'kuma', reviewed: true, reviewed_at: ago(89), unchecked: true,
    changed_since_review: true, maintenance: null, cert: { name: 'k.example', days: -2 }, collections: [] },
  { id: 'sl', name: 'Zora', state: 'slumbering', zone: 'home', zone_name: 'Home', kind: 'vm',
    addresses: ['zora.example'], services: 2, reviewed: true, reviewed_at: ago(91), unchecked: false,
    maintenance: { now: false, next: '2026-11-14T03:00:00Z' }, cert: { name: 'z.example', days: 29 }, collections: [] },
  { id: 'mt', name: 'Edge', state: 'maintenance', zone: 'dmz', zone_name: 'Outset', kind: 'vm',
    addresses: ['10.0.0.100'], services: 4, confirmed_by: 'unifi', unchecked: false, collections: [] },
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

/* ── a row's press ── */

test('a row press closes the card already up on that place, and opens any other', () => {
  assert.equal(rowPress('place-a', 'place-a'), 'close');
  assert.equal(rowPress('place-a', 'place-b'), 'open');
  assert.equal(rowPress(null, 'place-a'), 'open');
  assert.equal(rowPress(undefined, 'place-a'), 'open');
  assert.equal(rowPress('', ''), 'open');
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

test('the other columns: network, kind, services, confirmed by, collections', () => {
  assert.deepEqual(ids(sortRows(ROWS, 'zone', 'asc')), ['old', 'sl', 'nas', 'vm9', 'mt', 'gw']);
  assert.deepEqual(ids(sortRows(ROWS, 'kind', 'asc')), ['gw', 'nas', 'old', 'mt', 'vm9', 'sl']);   // ties by name
  assert.deepEqual(ids(sortRows(ROWS, 'services', 'asc')), ['vm9', 'old', 'sl', 'gw', 'mt', 'nas']);
  assert.deepEqual(ids(sortRows(ROWS, 'services', 'desc')), ['nas', 'mt', 'gw', 'sl', 'old', 'vm9']);
  assert.deepEqual(ids(sortRows(ROWS, 'confirmed_by', 'asc')), ['gw', 'old', 'nas', 'mt', 'vm9', 'sl']);
  assert.deepEqual(ids(sortRows(ROWS, 'collections', 'asc', COLLECTIONS)), ['nas', 'vm9', 'gw', 'mt', 'old', 'sl']);
  // the name it had before 2026-11-14 sorts the same
  assert.deepEqual(ids(sortRows(ROWS, 'sets', 'asc', COLLECTIONS)), ['nas', 'vm9', 'gw', 'mt', 'old', 'sl']);
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
  assert.deepEqual(ids(filterRows(ROWS, { text: '  infra   proxy ' }, NOW)), ['vm9']);   // every word must match
  assert.deepEqual(ids(filterRows(ROWS, { text: 'nothing-like-it' }, NOW)), []);
});

test('state, network, kind and collection each narrow it; unknown state is its own pick', () => {
  assert.deepEqual(ids(filterRows(ROWS, { state: 'down' }, NOW)), ['nas']);
  assert.deepEqual(ids(filterRows(ROWS, { state: 'unknown' }, NOW)), ['old']);
  assert.deepEqual(ids(filterRows(ROWS, { zone: 'core' }, NOW)), ['nas', 'vm9']);
  assert.deepEqual(ids(filterRows(ROWS, { kind: 'vm' }, NOW)), ['vm9', 'sl', 'mt']);
  assert.deepEqual(ids(filterRows(ROWS, { collection: 'edge' }, NOW)), ['gw', 'vm9']);
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
  assert.deepEqual(ids(filterRows(ROWS, { zone: 'core', state: 'degraded', collection: 'edge' }, NOW)), ['vm9']);
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
  assert.equal(slugFor('!!!', []), 'collection');
  assert.equal(slugFor('!!!', [], 'window'), 'window');
  assert.match(slugFor('Été à Kakariko', []), /^[a-z0-9][a-z0-9._-]*$/);
  assert.deepEqual(mergeNeeds('vm9', ['gw'], ['nas', 'gw', 'vm9']), ['gw', 'nas']);   // never itself, never twice
  assert.deepEqual(mergeNeeds('vm9', undefined, ['vm9']), []);
});

/* ── the rail (2026-11-14) ── */

const ROSTER = {
  zones: [{ id: 'core', name: 'Core net' }, { id: 'dmz', name: 'Outset' }, { id: 'empty', name: 'Nothing here' }],
  collections: [{ id: 'edge', name: 'Edge' }, { id: 'core', name: 'Core' }, { id: 'none', name: 'Nobody yet' }],
  rows: ROWS,
};

test('the rail counts what this viewer can see, and dots only trouble', () => {
  const g = railGroups(ROSTER);
  // collections keep the map's order; an empty one is still listed
  assert.deepEqual(g.collections.map((c) => [c.id, c.count, c.worst, c.trouble]),
    [['edge', 2, 'degraded', 1], ['core', 2, 'down', 2], ['none', 0, '', 0]]);
  // networks keep the map's order and list only those with a place in them
  assert.deepEqual(g.networks.map((n) => n.id), ['core', 'dmz']);
  assert.equal(g.networks.find((n) => n.id === 'core').name, 'Core net');
  // kinds in name order, each counted
  assert.deepEqual(g.kinds.map((k) => [k.id, k.count]), [['network', 1], ['physical', 1], ['unknown', 1], ['vm', 3]]);
  // a down place outranks a degraded one
  const worse = railGroups({ ...ROSTER, rows: ROWS.map((r) => (r.id === 'gw' ? { ...r, state: 'down' } : r)) });
  assert.equal(worse.collections[0].worst, 'down');
  assert.equal(worse.collections[0].trouble, 2);
  // junk in, nothing thrown
  assert.deepEqual(railGroups(null), { collections: [], networks: [], kinds: [] });
  assert.deepEqual(railGroups({ collections: [null, { name: 'no id' }], zones: 'x', rows: [null] }).collections, []);
});

test('a rail row filters to itself, and a second press shows everything', () => {
  assert.deepEqual(railPress({}, 'collections', 'edge'), { collection: 'edge' });
  assert.deepEqual(railPress({ collection: 'edge' }, 'collections', 'edge'), { collection: '' });
  assert.deepEqual(railPress({ collection: 'edge' }, 'collections', 'core'), { collection: 'core' });
  assert.deepEqual(railPress({}, 'networks', 'dmz'), { zone: 'dmz' });
  assert.deepEqual(railPress({ kind: 'vm' }, 'kinds', 'vm'), { kind: '' });
  assert.deepEqual(railPress({}, 'saved', 'x'), {});
  assert.deepEqual(RAIL_FIELDS, { collections: 'collection', networks: 'zone', kinds: 'kind', things: 'things' });
});

test('a phone keeps a filter on an empty network; members read as one id or a list', () => {
  const g = filterGroups(ROSTER);
  assert.deepEqual(g.networks.map((n) => n.id), ['core', 'dmz', 'empty']);
  assert.deepEqual(dropUnknown({ zone: 'empty' }, g), { zone: 'empty' });
  assert.deepEqual(dropUnknown({ zone: 'gone' }, g), { zone: '' });
  assert.deepEqual(memberList('beta'), ['beta']);
  assert.deepEqual(memberList(['a', 'b']), ['a', 'b']);
  assert.deepEqual(memberList(''), []);
  assert.deepEqual(memberList(null), []);
});

test('a rail filter naming nothing here shows everything, not nothing', () => {
  const g = railGroups(ROSTER);
  assert.deepEqual(dropUnknown({ text: 'x', collection: 'gone', zone: 'empty', kind: 'vm' }, g),
    { text: 'x', collection: '', zone: '', kind: 'vm' });
  assert.deepEqual(dropUnknown({ collection: 'edge' }, g), { collection: 'edge' });
});

test('a filter or sort kept before collections were named still works', () => {
  assert.equal(cleanFilter({ set: 'edge' }).collection, 'edge');
  assert.equal(cleanFilter({ set: 'old', collection: 'new' }).collection, 'new');
  assert.equal('set' in cleanFilter({ set: 'edge' }), false);
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  storage.setItem(SORT_KEY, JSON.stringify({ key: 'sets', dir: 'desc' }));
  assert.deepEqual(readSort(storage), { key: 'collections', dir: 'desc' });
  storage.setItem(SAVED_KEY, JSON.stringify([{ name: 'Edges', filter: { set: 'edge' }, sort: { key: 'sets', dir: 'asc' } }]));
  assert.deepEqual(readSaved(storage), [{ name: 'Edges', filter: { ...cleanFilter({}), collection: 'edge' },
    sort: { key: 'collections', dir: 'asc' } }]);
});

test('the rail remembers which sections were shut, and nothing else', () => {
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.deepEqual(readRail(storage), {});
  writeRail(storage, { kinds: true, networks: false, bogus: true });
  assert.equal(mem.get(RAIL_KEY), JSON.stringify({ kinds: true }));
  assert.deepEqual(readRail(storage), { kinds: true });
  mem.set(RAIL_KEY, '{not json');
  assert.deepEqual(readRail(storage), {});
  const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.deepEqual(readRail(broken), {});
  assert.equal(writeRail(broken, { kinds: true }), false);
});

test("NODES' words: every one has its plain twin in plain.json", () => {
  const src = readFileSync(new URL('../static/js/nodes.js', import.meta.url), 'utf8');
  const body = src.match(/export const NODES_TEXT = \{([\s\S]*?)\n\};/)[1];
  const words = Function(`return {${body}}`)();
  const plain = JSON.parse(readFileSync(new URL('../themes/plain.json', import.meta.url), 'utf8')).text;
  const plainNodes = Object.fromEntries(Object.entries(plain).filter(([k]) => k.startsWith('nodes_')));
  assert.deepEqual(plainNodes, words);
  // nothing still calls a collection a set ("Set what these need" is the verb)
  for (const [k, v] of Object.entries(words)) {
    assert.doesNotMatch(k, /_sets?(_|$)/, k);
    assert.doesNotMatch(v, /\bsets\b|\b(a|the|new|any) set\b|\{set\}/i, k);
  }
});

test('maintenance mode: on writes one open window for what is not already in mode', () => {
  const sched = { id: 'patch', reason: 'Patch', nodes: ['a'], starts: '2026-01-01T00:00:00Z', ends: '2026-01-02T00:00:00Z' };
  const now = '2026-11-14T12:00:00Z';
  const on = modeChange([sched], { nodes: ['a', 'b'] }, true, { now });
  assert.equal(on.length, 2);
  assert.deepEqual(on[1], { id: 'maintenance-mode', reason: 'Maintenance mode', open: true, starts: now, repeat: 'none', nodes: ['a', 'b'] });
  assert.ok(inMode(on, 'place', 'b') && !inMode([sched], 'place', 'a'), 'a scheduled window is not mode');
  // already in mode: nothing to write
  assert.equal(modeChange(on, { nodes: ['b'] }, true, { now }), null);
  // a collection, and a second window gets its own id
  const col = modeChange(on, { collections: ['web'] }, true, { now });
  assert.equal(col[2].id, 'maintenance-mode-2');
  assert.deepEqual(col[2].collections, ['web']);
  assert.ok(inMode(col, 'collection', 'web'));
  assert.deepEqual(modeVia(col, ['web', 'db']), ['web']);
});

test('maintenance mode: off takes them out of every open window, and an empty one goes', () => {
  const sched = { id: 'patch', reason: 'Patch', nodes: ['a'], ends: 'x' };
  const w1 = { id: 'm1', open: true, nodes: ['a', 'b'] };
  const w2 = { id: 'm2', open: true, nodes: ['a'], collections: ['web'] };
  const off = modeChange([sched, w1, w2], { nodes: ['a'] }, false, {});
  assert.deepEqual(off, [sched, { id: 'm1', open: true, nodes: ['b'] }, { id: 'm2', open: true, collections: ['web'] }]);
  assert.deepEqual(modeChange(off, { nodes: ['b'], collections: ['web'] }, false, {}), [sched]);
  assert.equal(modeChange([sched], { nodes: ['a'] }, false, {}), null, 'a schedule is never turned off here');
  assert.equal(modeChange(undefined, { nodes: ['a'] }, false, {}), null);
});

test('maintenance mode on a service: its own window field, on and off (stage 3b)', () => {
  const on = modeChange([], { services: ['core/SSH'] }, true, { now: 'x' });
  assert.deepEqual(on[0].services, ['core/SSH']);
  assert.ok(inMode(on, 'service', 'core/SSH') && !inMode(on, 'place', 'core/SSH'));
  assert.deepEqual(modeChange(on, { services: ['core/SSH'] }, false, {}), []);
  const mixed = [{ id: 'm', open: true, nodes: ['a'], services: ['k'] }];
  assert.deepEqual(modeChange(mixed, { services: ['k'] }, false, {}), [{ id: 'm', open: true, nodes: ['a'] }]);
});

test('the summary line counts each state as the table reads it, worst first (2026-11-15)', () => {
  const rows = [
    { id: 'a', state: 'healthy' }, { id: 'b', state: 'down' }, { id: 'c', state: 'healthy' },
    { id: 'd' }, { id: 'e', state: 'down', unmanaged: true }, { id: 'f', state: 'bogus' }, null,
  ];
  assert.deepEqual(stateCounts(rows), [['down', 1], ['healthy', 2], ['unknown', 2], ['unmanaged', 1]]);
  assert.deepEqual(stateCounts([]), []);
  assert.deepEqual(stateCounts(undefined), []);
  // every count is a state the filter can take, so pressing one shows exactly those rows
  for (const [s, n] of stateCounts(rows)) assert.equal(filterRows(rows.filter(Boolean), { state: s }).length, n);
  assert.deepEqual([...SUMMARY_ORDER].sort(), [...SEVERITY, 'unknown', 'unmanaged'].sort());
});

test('recent changes: only the things on screen, newest first, capped (2026-11-15)', () => {
  const ev = [
    { id: 1, kind: 'node', target: 'a', to: 'down' },
    { id: 4, kind: 'service', target: 'Web UI', to: 'healthy' },
    { id: 3, kind: 'node', target: 'gone', to: 'down' },
    { id: 2, kind: 'rite', target: 'backup', to: 'down' },
    { id: 5, kind: 'service', target: 'b/SSH', to: 'down' },
    { id: 6, kind: 'node', target: 'a', to: 'healthy' },
    { kind: 'node' }, null, 'x',
  ];
  const keys = new Map([['Web UI', 'a'], ['b/SSH', 'b'], ['c/x', 'c']]);
  ev.push({ id: 9, kind: 'service', target: 'c/x', to: 'down' });   // its place is not on screen
  const got = recentFor(ev, ['a', 'b'], keys);
  assert.deepEqual(got.map((e) => [e.id, e.place]), [[6, 'a'], [5, 'b'], [4, 'a'], [1, 'a']]);
  assert.equal(recentFor(ev, ['a', 'b'], keys, 2).length, 2);
  assert.deepEqual(recentFor(ev, [], new Map()), [], 'nothing on screen, nothing listed');
  assert.deepEqual(recentFor(null, ['a'], null), []);
  assert.ok(!('place' in ev[0]), 'the events read are left as they were');
});

test('a container is a link that says so, or names one; anything else is a service (C2)', () => {
  assert.equal(thingKind({ container: 'scout' }), 'container');
  assert.equal(thingKind({ container: '  ' }), 'service');
  assert.equal(thingKind({ container: 'scout', kind: 'service' }), 'service', 'its own word wins');
  assert.equal(thingKind({ kind: 'container' }), 'container');
  assert.equal(thingKind({ kind: 'vm' }), 'service', 'an unknown word is not a kind');
  assert.equal(thingKind(null), 'service');
  assert.deepEqual(THING_KINDS, ['container', 'service']);
});

const THINGS_DATA = {
  nodes: [
    { id: 'host', name: 'HOST', links: [
      { label: 'Scout', container: 'scout', kuma: 'Scout monitor' },
      { label: 'SSH' },
      { label: 'Dup', kuma: 'Scout monitor' },          // a second link naming one monitor: the first keeps it
      { label: 'Quiet', container: 'q', unmanaged: true },
      'junk',
    ] },
    { id: 'hidden', name: 'HIDDEN', links: [{ label: 'Secret', container: 'secret' }] },   // not in the roster
    { id: 'off', name: 'OFF', links: [{ label: 'Web' }] },
  ],
};
const THINGS_ROSTER = {
  rows: [
    { id: 'host', name: 'HOST', zone: 'core', collections: ['racks'] },
    { id: 'off', name: 'OFF', zone: 'edge', unmanaged: true, collections: [] },
  ],
  collections: [{ id: 'racks', places: ['host'], services: [] }, { id: 'web', services: ['host/SSH'] }],
};
const THINGS_FEED = { services: { 'Scout monitor': { state: 'down' }, 'host/SSH': { state: 'healthy' } },
               maintenance_services: ['host/SSH'] };

test('thingRows: every service link of a place the viewer was given, with the card\'s state rule (C2)', () => {
  const rows = thingRows(THINGS_DATA, THINGS_ROSTER, THINGS_FEED);
  assert.deepEqual(rows.map((x) => [x.key, x.kind, x.place]),
    [['Scout monitor', 'container', 'host'], ['host/SSH', 'service', 'host'], ['host/Quiet', 'container', 'host'], ['off/Web', 'service', 'off']]);
  const by = Object.fromEntries(rows.map((x) => [x.key, x]));
  assert.equal(by['Scout monitor'].state, 'down');
  assert.equal(by['Scout monitor'].container, 'scout');
  assert.equal(by['host/SSH'].state, 'maintenance', 'a window naming it outranks the feed');
  assert.deepEqual(by['host/SSH'].collections, ['web']);
  assert.deepEqual(by['host/SSH'].place_collections, ['racks']);
  assert.equal(by['host/Quiet'].unmanaged, true);
  assert.equal(by['off/Web'].unmanaged, true, 'an unmanaged place takes its services with it');
  assert.ok(!rows.some((x) => x.place === 'hidden'), 'a place the roster does not list gives no row');
  assert.deepEqual(thingRows(null, null, null), []);
  assert.deepEqual(thingRows(THINGS_DATA, { rows: [] }, {}), []);
});

test('filterThings and sortThings: the table\'s filter, read for a thing; worst first (C2)', () => {
  const rows = thingRows(THINGS_DATA, THINGS_ROSTER, THINGS_FEED);
  const keys = (list) => list.map((x) => x.key);
  assert.deepEqual(keys(filterThings(rows, { things: 'container' })), ['Scout monitor', 'host/Quiet']);
  assert.deepEqual(keys(filterThings(rows, { things: 'service', text: 'host' })), ['host/SSH']);
  assert.deepEqual(keys(filterThings(rows, { text: 'scout' })), ['Scout monitor'], 'the container name is found');
  assert.deepEqual(keys(filterThings(rows, { state: 'unmanaged' })), ['host/Quiet', 'off/Web']);
  assert.deepEqual(keys(filterThings(rows, { zone: 'edge' })), ['off/Web']);
  assert.deepEqual(keys(filterThings(rows, { collection: 'web' })), ['host/SSH'], 'its own collection');
  assert.deepEqual(keys(filterThings(rows, { collection: 'racks' })).length, 3, 'or its place\'s');
  assert.deepEqual(keys(filterThings(rows, { unchecked: true, staleDays: 90 })).length, 4, 'a place\'s review is not a thing\'s');
  assert.deepEqual(keys(sortThings(rows)), ['Scout monitor', 'host/SSH', 'host/Quiet', 'off/Web']);
});

test('thingGroups: the rail\'s Containers and Services, counted, with the worst trouble (C2)', () => {
  const g = thingGroups(thingRows(THINGS_DATA, THINGS_ROSTER, THINGS_FEED));
  assert.deepEqual(g.map((x) => [x.id, x.count, x.worst]), [['container', 2, 'down'], ['service', 2, '']]);
  assert.deepEqual(thingGroups([]), [], 'a kind with none is not listed');
});

test('a thing filter is a filter: kept, cleaned, and never dropped as unknown (C2)', () => {
  assert.equal(cleanFilter({ things: 'container' }).things, 'container');
  assert.equal(cleanFilter({ things: 'vm' }).things, '');
  assert.equal(isEmptyFilter({ things: 'service' }), false);
  assert.equal(dropUnknown({ things: 'container' }, { collections: [], networks: [], kinds: [] }).things, 'container');
  assert.equal(dropUnknown({ things: 'nope' }, {}).things, '');
});

await Promise.all(pending);
console.log(`\n${passed} passed`);
