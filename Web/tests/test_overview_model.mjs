/* OVERVIEW's rules, in plain node (2026-11-13, the views' stage 3): the tile
   order, every empty state, the 30- and 7-day certificate edges, the summary
   sentence, the "nothing is declared" wording, and the fullest address
   ranges worked out with the Addresses scene's own maths.

   Run:  node tests/test_overview_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import * as M from '../static/js/overview-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const NOW = Date.parse('2026-11-13T12:00:00Z');
const daysAgo = (n) => new Date(NOW - n * 86400000).toISOString();

test('the tiles keep one order; drift only when the server sends it', () => {
  assert.deepEqual(M.TILES, ['states', 'down', 'unacked', 'maintenance', 'certs', 'review',
    'changes', 'sources', 'drift', 'ranges']);
  assert.deepEqual(M.tileOrder({ admin: false }), M.TILES.filter((k) => k !== 'drift'));
  assert.deepEqual(M.tileOrder({ admin: true, drift: { count: 0, items: [] } }), M.TILES);
  // nothing read yet: every tile but drift is still drawn, so the page never jumps
  assert.deepEqual(M.tileOrder(null), M.TILES.filter((k) => k !== 'drift'));
});

test('every phrase has a plain fallback, and fill leaves unknown names alone', () => {
  for (const [k, v] of Object.entries(M.OVERVIEW_TEXT)) {
    assert.ok(k.startsWith('ov_'), k);
    assert.equal(typeof v, 'string');
    assert.ok(v.length > 0, k);
  }
  for (const k of M.TILES) assert.ok(M.OVERVIEW_TEXT[`ov_t_${k}`], `ov_t_${k}`);
  assert.equal(M.fill('{a} and {b}', { a: 1 }), '1 and {b}');
  assert.equal(M.plainT('ov_days', { n: 4 }), '4 days');
});

test('the summary sentence', () => {
  assert.equal(M.stateSummary({ healthy: 18, total: 18 }), 'All 18 places are up.');
  assert.equal(M.stateSummary({ healthy: 16, down: 2, total: 18 }), '2 of 18 places are down.');
  assert.equal(M.stateSummary({ healthy: 17, down: 1, total: 18 }), '1 of 18 places is down.');
  assert.equal(M.stateSummary({ healthy: 15, degraded: 3, total: 18 }), 'No place is down; 3 of 18 are degraded.');
  assert.equal(M.stateSummary({ healthy: 17, degraded: 1, total: 18 }), 'No place is down; 1 of 18 is degraded.');
  assert.equal(M.stateSummary({ healthy: 16, slumbering: 2, total: 18 }), 'No place is down; 16 of 18 are up.');
  assert.equal(M.stateSummary({ unknown: 5, total: 5 }), 'The state of every place is not known yet.');
  assert.equal(M.stateSummary({ healthy: 1, total: 1 }), 'The one place is up.');
  assert.equal(M.stateSummary({ total: 0 }), 'There are no places on the map yet.');
  assert.equal(M.stateSummary(null), 'There are no places on the map yet.');
  // a missing total is the sum of the states
  assert.equal(M.stateSummary({ healthy: 3, down: 1 }), '1 of 4 places is down.');
});

test('the state rows skip the empty states, in the one order', () => {
  assert.deepEqual(M.stateRows({ down: 2, healthy: 16, unknown: 0, total: 18 }),
    [{ state: 'healthy', n: 16 }, { state: 'down', n: 2 }]);
  assert.deepEqual(M.stateRows(undefined), []);
});

test('days in words', () => {
  assert.equal(M.daysPhrase(-3), 'lapsed');
  assert.equal(M.daysPhrase(0), 'today');
  assert.equal(M.daysPhrase(1), '1 day');
  assert.equal(M.daysPhrase(12), '12 days');
  assert.equal(M.daysPhrase(null), '');
});

test('the certificate tone: warn at 30 or fewer, down at 7 or fewer, or lapsed', () => {
  assert.equal(M.certClass(31), '');
  assert.equal(M.certClass(30), 'warn');
  assert.equal(M.certClass(8), 'warn');
  assert.equal(M.certClass(7), 'down');
  assert.equal(M.certClass(0), 'down');
  assert.equal(M.certClass(-1), 'down');
  assert.equal(M.certClass(undefined), '');
  assert.equal(M.certClass(NaN), '');
});

test('certificates: soonest first, empty says so', () => {
  const rows = M.certRows([
    { name: 'b.example', days: 20, place: null },
    { name: 'a.example', days: -2, place: { id: 'x', name: 'X' } },
    { name: 'c.example', days: 5 },
  ]);
  assert.deepEqual(rows.map((r) => [r.name, r.phrase, r.tone]),
    [['a.example', 'lapsed', 'down'], ['c.example', '5 days', 'down'], ['b.example', '20 days', 'warn']]);
  assert.deepEqual(M.certRows(undefined), []);
  assert.equal(M.plainT('ov_certs_none'), 'No certificate lapses within 30 days.');
});

test('down: nothing declared is said once, for the tile', () => {
  const d = M.downTile([
    { id: 'a', name: 'A', state: 'down', cause: '', downstream: [], declared: false },
    { id: 'b', name: 'B', state: 'down', cause: '', downstream: [], declared: false },
  ]);
  assert.equal(d.note, 'Nothing is declared to depend on these.');
  assert.deepEqual(d.items.map((x) => x.line), ['', '']);
  assert.equal(d.empty, '');
});

test('down: what depends on each, or why nothing does', () => {
  const d = M.downTile([
    { id: 'a', name: 'A', downstream: [{ id: 'c', name: 'C' }], declared: true },
    { id: 'b', name: 'B', downstream: [], declared: true },
    { id: 'e', name: 'E', downstream: [], declared: false },
  ]);
  assert.equal(d.note, '');
  assert.equal(d.items[0].takes, 'Depends on it:');
  assert.deepEqual(d.items[0].downstream, [{ id: 'c', name: 'C' }]);
  assert.equal(d.items[1].line, 'Nothing depends on it.');
  assert.equal(d.items[2].line, 'Nothing is declared to depend on it.');
  // a cause that is the place itself says nothing new
  assert.equal(M.downTile([{ id: 'a', cause: 'a', declared: true, downstream: [] }]).items[0].cause, '');
  assert.equal(M.downTile([{ id: 'a', cause: null, declared: true, downstream: [] }]).items[0].cause, '');
  assert.equal(M.downTile([]).empty, 'Nothing is down.');
  assert.equal(M.downTile(undefined).empty, 'Nothing is down.');
});

test('not acknowledged: the count, the rows, and how many more', () => {
  const u = M.unackedTile({ count: 9, items: [
    { id: 4, at: daysAgo(0), kind: 'state', target: 'n1', name: 'N1', from: 'healthy', to: 'down' },
  ] }, M.plainT, NOW);
  assert.equal(u.line, '9 events are waiting.');
  assert.equal(u.items[0].move, 'healthy → down');
  assert.equal(u.items[0].when, 'just now');
  assert.equal(u.more, 8);
  assert.equal(M.unackedTile({ count: 1, items: [{ id: 1 }] }).line, '1 event is waiting.');
  assert.equal(M.unackedTile({ count: 0, items: [] }).empty, 'Every event has been acknowledged.');
  assert.equal(M.unackedTile(undefined).empty, 'Every event has been acknowledged.');
});

test('maintenance: open windows first, then by start; empty says so', () => {
  const m = M.maintenanceTile([
    { window: 'w2', reason: 'Later', starts: '2026-11-15T02:00:00Z', ends: '2026-11-15T04:00:00Z', now: false, places: [] },
    { window: 'w1', reason: 'Patching', starts: '2026-11-13T10:00:00Z', ends: '2026-11-13T14:00:00Z', now: true, places: [{ id: 'a', name: 'A' }] },
  ]);
  assert.deepEqual(m.items.map((w) => w.window), ['w1', 'w2']);
  assert.equal(m.items[0].when, 'now, until 2026-11-13 14:00 UTC');
  assert.equal(m.items[1].when, '2026-11-15 02:00 UTC to 2026-11-15 04:00 UTC');
  assert.equal(M.maintenanceTile([]).empty, 'No maintenance in the next 7 days.');
});

test('not checked: the two counts and the rows, with the 90-day words', () => {
  const r = M.reviewTile({ unchecked: 1, stale: 2, items: [
    { id: 'a', name: 'A', reviewed_at: null },
    { id: 'b', name: 'B', reviewed_at: daysAgo(91) },
    { id: 'c', name: 'C', reviewed_at: daysAgo(90) },
  ] }, M.plainT, NOW);
  assert.deepEqual(r.lines, ['1 place is waiting to be checked.', '2 places have not been checked in 90 days.']);
  assert.deepEqual(r.items.map((x) => x.when), ['never checked', 'checked 91 days ago', 'checked 90 days ago']);
  assert.equal(r.more, 0);
  // the two counts can share places: never added together
  const both = M.reviewTile({ unchecked: 18, stale: 18, items: [{ id: 'a', name: 'A', reviewed_at: null }] });
  assert.equal(both.count, 18);
  assert.equal(both.more, 17);
  assert.equal(M.reviewTile({ unchecked: 0, stale: 0, items: [] }).empty,
    'Every place has been checked in the last 90 days.');
  assert.equal(M.reviewTile({ unchecked: 3, stale: 0, items: [] }).lines[0], '3 places are waiting to be checked.');
});

test('recent changes: an admin sees who; anyone else a count with no names', () => {
  const a = M.changesTile({ items: [{ at: daysAgo(2), by: 'ops', summary: 'edited N1' }] }, M.plainT, NOW);
  assert.equal(a.admin, true);
  assert.deepEqual(a.items[0], { summary: 'edited N1', by: 'ops', when: '2d ago' });
  assert.equal(M.changesTile({ items: [] }).empty, 'No changes this week.');
  const v = M.changesTile({ count_7d: 3 });
  assert.equal(v.admin, false);
  assert.equal(v.line, '3 places changed this week.');
  assert.deepEqual(v.items, []);
  assert.equal(M.changesTile({ count_7d: 1 }).line, '1 place changed this week.');
  assert.equal(M.changesTile({ count_7d: 0 }).line, 'No place changed this week.');
  assert.equal(M.changesTile(undefined).line, 'No place changed this week.');
});

test('sources: everyone gets the sentence, an admin the names', () => {
  assert.equal(M.sourcesTile({ all_ok: true, silent: 0, items: [] }, false).line, 'Every source is answering.');
  assert.equal(M.sourcesTile({ all_ok: false, silent: 1, items: [] }, false).line, '1 source is silent.');
  assert.equal(M.sourcesTile({ all_ok: false, silent: 2, items: [] }, false).line, '2 sources are silent.');
  assert.equal(M.sourcesTile({ all_ok: true, silent: 0, items: [] }, true).line,
    'No live source is set up; the map is all there is.');
  const s = M.sourcesTile({ all_ok: false, silent: 1, items: [
    { name: 'kuma', ok: true, last_ok: daysAgo(0) },
    { name: 'unifi', ok: false, last_ok: null },
  ] }, true, M.plainT, NOW);
  assert.equal(s.tone, 'warn');
  assert.deepEqual(s.items.map((x) => [x.name, x.state, x.when]),
    [['unifi', 'silent', 'has not answered'], ['kuma', 'answering', 'last answered just now']]);
});

test('drift: agreement said plainly, else the count and names', () => {
  assert.equal(M.driftTile({ count: 0, items: [] }).line, 'The map agrees with its sources.');
  const d = M.driftTile({ count: 3, items: ['a', 'b'] });
  assert.equal(d.line, '3 places differ from their sources.');
  assert.equal(d.more, 1);
  assert.equal(M.driftTile({ count: 1, items: ['a'] }).line, '1 place differs from its sources.');
});

/* a small realm: three /24s and one /30, one of them split in two */
const FIXTURE = {
  zones: [
    { id: 'core', name: 'Core', subnet: '10.0.1.0/24' },
    { id: 'edge', name: 'Edge', subnet: '10.0.2.0/30' },
    { id: 'quiet', name: 'Quiet', subnet: '10.0.3.0/24' },
  ],
  prefixes: [
    { id: 'lab', cidr: '10.0.8.0/24', name: 'Lab', role: 'container' },
    { id: 'lab-a', cidr: '10.0.8.0/25', name: 'Lab A' },
    { id: 'lab-b', cidr: '10.0.8.128/25', name: 'Lab B' },
  ],
  nodes: [
    { id: 'a', ip: '10.0.1.10', kind: 'vm' },
    { id: 'b', ip: '10.0.1.11', kind: 'vm' },
    { id: 'c', ip: '10.0.2.1', kind: 'physical' },
    { id: 'd', ip: '10.0.2.2', kind: 'physical' },
    { id: 'e', ip: '10.0.8.5', kind: 'vm' },
    { id: 'f', ip: '—' },
  ],
};

test('the fullest ranges use the Addresses maths: leaves only, fullest first', () => {
  const r = M.fullestRanges(FIXTURE, 5);
  assert.deepEqual(r.map((x) => x.cidr), ['10.0.2.0/30', '10.0.8.0/25', '10.0.1.0/24', '10.0.3.0/24', '10.0.8.128/25']);
  assert.deepEqual(r[0], { name: 'Edge', cidr: '10.0.2.0/30', used: 2, size: 2, sizeLabel: '2', usedLabel: '2', pct: 100 });
  // 1 of 126 is fuller than 2 of 254
  assert.equal(r[1].used, 1);
  assert.equal(r[1].size, 126);
  assert.equal(r[2].used, 2);
  assert.equal(r[2].size, 254);
  assert.equal(r[2].pct, 0.78);
  // two empty ranges tie at 0%: the lower address first
  assert.equal(r[3].cidr, '10.0.3.0/24');
  // the container split into halves is counted in its halves, not twice
  assert.ok(!r.some((x) => x.cidr === '10.0.8.0/24'));
  assert.equal(M.fullestRanges(FIXTURE, 2).length, 2);
});

test('the ranges tile: reading, none described, and the tones', () => {
  assert.equal(M.fullestRanges(null), null);
  assert.equal(M.rangesTile(null).empty, 'Reading the map…');
  assert.deepEqual(M.fullestRanges({ nodes: [] }), []);
  assert.equal(M.rangesTile([]).empty, 'No address ranges are described yet.');
  const t = M.rangesTile(M.fullestRanges(FIXTURE));
  assert.equal(t.items[0].tone, 'down');
  assert.equal(t.items[0].line, '2 of 2');
  assert.equal(t.items[1].tone, '');
  assert.equal(M.rangesTile([{ name: 'x', cidr: 'c', used: 80, size: 100, pct: 80 }]).items[0].tone, 'warn');
});

test('a list on a wall is cut short with how many more', () => {
  assert.deepEqual(M.capped([1, 2, 3], 2), { shown: [1, 2], more: 1 });
  assert.deepEqual(M.capped(undefined), { shown: [], more: 0 });
});

test('a stamp in words', () => {
  assert.equal(M.agoPhrase(daysAgo(0), NOW), 'just now');
  assert.equal(M.agoPhrase(new Date(NOW - 5 * 60000).toISOString(), NOW), '5m ago');
  assert.equal(M.agoPhrase('nonsense', NOW), '');
  assert.equal(M.utcPhrase('2026-11-14T02:00:00Z'), '2026-11-14 02:00 UTC');
});

console.log(`\n${passed} passed`);
