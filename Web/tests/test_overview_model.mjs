/* OVERVIEW's rules, in plain node (2026-11-13, the views' stage 3): the tile
   order, every empty state, the 30- and 7-day certificate edges, the summary
   sentence, the "nothing is declared" wording, the favourites and the
   sources that open.

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

const SECTIONS = ['states', 'down', 'unacked', 'maintenance', 'certs', 'review',
  'changes', 'sources', 'favin', 'favout'];

test('the sheet has two faces, the watch list first; the tiles are gone', () => {
  assert.deepEqual(M.FACES, ['list', 'chart']);
  assert.equal(M.faceOr(null), 'list');
  assert.equal(M.faceOr('chart'), 'chart');
  assert.equal(M.faceOr('tiles'), 'list', 'a stored name that is not a face opens the first');
  assert.equal(M.faceStep('list', 1), 'chart');
  assert.equal(M.faceStep('chart', 1), 'chart', 'held at the end');
  assert.equal(M.faceStep('chart', -1), 'list');
  assert.equal(M.faceStep('list', -1), 'list');
  for (const k of M.FACES) assert.ok(M.OVERVIEW_TEXT[`ov_face_${k}`], k);
  assert.equal(M.faceOr('doors'), 'list', 'the doors were a face for an hour; a stored pick opens the first');
  // the favourites are the first face's own: stacked, the watch list (which
  // the chart table also carries) gives up rows before they do
  assert.deepEqual(M.cutOrder(true), ['watch', 'doors']);
  assert.deepEqual(M.cutOrder(false), ['doors', 'watch']);
  assert.equal(M.OVERVIEW_TEXT.ov_face_doors, undefined);
  assert.equal(M.TILES, undefined);
  assert.equal(M.tileOrder, undefined);
  // the ranges and the drift left with their words (2026-11-20)
  for (const gone of ['drift', 'ranges']) {
    assert.ok(!Object.keys(M.OVERVIEW_TEXT).some((k) => k.includes(gone)), gone);
  }
  assert.equal(M.fullestRanges, undefined);
  assert.equal(M.driftTile, undefined);
});

const ANSWER = {
  admin: false,
  states: { total: 4, healthy: 2, degraded: 1, down: 1 },
  down: [
    { id: 'dl', name: 'Downloads', state: 'degraded', declared: false, downstream: [] },
    { id: 'gw', name: 'Gateway', state: 'down', declared: true, downstream: [{ id: 'app', name: 'App host' }] },
  ],
  unacked: { count: 0, items: [] },
  maintenance: [],
  certs: [{ name: 'wild', days: 10, place: { id: 'app', name: 'App host' } }, { name: 'edge', days: -2 }],
  review: { unchecked: 0, stale: 3, items: [{ id: 'app', name: 'App host', reviewed_at: null }] },
  changes: { count_7d: 0 },
  sources: { all_ok: true, silent: 0, items: [] },
  favourites: { internal: [], external: [] },
};

test('the watch list: worst first, in the answer\'s order within a tone', () => {
  const rows = M.watchList(ANSWER, M.plainT, NOW);
  assert.deepEqual(rows.map((r) => r.key), ['place:gw', 'cert:edge', 'place:dl', 'cert:wild', 'review']);
  assert.deepEqual(rows.map((r) => r.tone), ['down', 'down', 'warn', 'warn', '']);
  const gw = rows[0];
  assert.equal(gw.word, 'Down');
  assert.equal(gw.detail, 'Depends on it: App host');
  assert.deepEqual(gw.place, { id: 'gw', name: 'Gateway' });
  // a degraded place is never called down
  assert.equal(rows[2].word, 'Degraded');
  assert.equal(rows[1].word, 'lapsed');
  assert.equal(rows[3].word, '10 days');
  assert.deepEqual(rows[3].place, { id: 'app', name: 'App host' });
  assert.equal(rows[4].go, 'nodes');
  assert.equal(rows[4].word, '3');
  assert.equal(M.worstTone(rows), 'down');
  assert.equal(M.worstTone(rows.slice(2)), 'warn');
  assert.equal(M.worstTone([]), '');
});

test('the watch list: events open the ANNALS, a silent source is a row, a missing answer is no rows', () => {
  const rows = M.watchList({
    ...ANSWER, admin: true, down: [], certs: [], review: {},
    unacked: { count: 2, items: [{ id: 7, name: 'Gateway', from: 'healthy', to: 'down', at: daysAgo(1) }] },
    sources: { silent: 1, items: [{ name: 'kuma', ok: false, url: 'http://kuma.example' }, { name: 'prom', ok: true }] },
    changes: { items: [{ summary: 'Moved the gateway', by: 'ada', at: daysAgo(2) }] },
  }, M.plainT, NOW);
  assert.deepEqual(rows.map((r) => r.key), ['source:kuma', 'unacked', 'changes']);
  assert.equal(rows[0].url, 'http://kuma.example');
  assert.equal(rows[1].go, 'annals');
  assert.equal(rows[1].word, '2');
  assert.ok(rows[1].detail.startsWith('2 events are waiting.'));
  assert.equal(rows[2].detail, 'Moved the gateway · ada · 2d ago');
  assert.deepEqual(M.watchList(null), []);
  assert.deepEqual(M.quietLine(null), [], 'could not be read is never drawn as calm');
});

test('the quiet line: one calm sentence for each section with nothing to report', () => {
  assert.deepEqual(M.quietLine(ANSWER, M.plainT, NOW), [
    'Every event has been acknowledged', 'No maintenance in the next 7 days',
    'No place changed this week', 'Every source is answering']);
  const calm = M.quietLine({ states: {}, changes: { items: [] }, admin: true }, M.plainT, NOW);
  assert.deepEqual(calm, ['Nothing is down', 'Every event has been acknowledged',
    'No maintenance in the next 7 days', 'No certificate lapses within 30 days',
    'Every place has been checked in the last 90 days', 'No changes this week',
    'No live source is set up; the map is all there is']);
  // every section is either a row or a calm sentence, never neither
  assert.equal(M.watchList({ states: {}, changes: { items: [] }, admin: true }).length, 0);
});

test('the chart table: a lamp for each place drawn, the rest counted', () => {
  const rows = M.watchList(ANSWER, M.plainT, NOW);
  const { lamps, off } = M.chartLamps([
    { id: 'gw', name: 'Gateway', x: 10, y: 20 },
    { id: 'app', name: 'App host', x: 140, y: -3 },
    { id: 'cam', name: 'Camera', x: 50, y: 50, off: true },
    { id: 'nas', x: 'nowhere', y: 5 },
    { id: 'sw', name: 'Switch', x: 60, y: 60 },
  ], { gw: 'down', sw: 'healthy' }, rows);
  assert.equal(off, 2);
  assert.deepEqual(lamps.map((l) => l.id), ['sw', 'gw', 'app'], 'a named lamp is drawn last');
  assert.deepEqual(lamps.map((l) => l.named), [false, true, true]);
  assert.deepEqual(lamps[2], { id: 'app', name: 'App host', x: 100, y: 0, state: 'unknown', named: true });
  assert.equal(lamps[1].state, 'down');
  assert.deepEqual(M.chartLamps(null), { lamps: [], off: 0 });
});

test('every phrase has a plain fallback, and fill leaves unknown names alone', () => {
  for (const [k, v] of Object.entries(M.OVERVIEW_TEXT)) {
    assert.ok(k.startsWith('ov_'), k);
    assert.equal(typeof v, 'string');
    assert.ok(v.length > 0, k);
  }
  for (const k of SECTIONS) assert.ok(M.OVERVIEW_TEXT[`ov_t_${k}`], `ov_t_${k}`);
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
  // neither has a console the server named: no link is drawn
  assert.deepEqual(s.items.map((x) => x.url), ['', '']);
});

test('sources: one with a console of its own carries where it opens', () => {
  const s = M.sourcesTile({ all_ok: true, silent: 0, items: [
    { name: 'prometheus', ok: true, last_ok: daysAgo(0), url: 'http://10.0.0.5:9090', open_in: 'auto' },
    { name: 'unifi', ok: true, last_ok: daysAgo(0), url: 'https://10.0.0.1', open_in: 'tab' },
    { name: 'checks', ok: true, last_ok: daysAgo(0) },
    { name: 'odd', ok: true, last_ok: daysAgo(0), url: 'javascript:alert(1)' },
  ] }, true, M.plainT, NOW);
  const by = Object.fromEntries(s.items.map((x) => [x.name, [x.url, x.openIn]]));
  assert.deepEqual(by.prometheus, ['http://10.0.0.5:9090', 'auto']);
  assert.deepEqual(by.unifi, ['https://10.0.0.1', 'tab']);
  assert.deepEqual(by.checks, ['', 'auto']);
  assert.deepEqual(by.odd, ['', 'auto'], 'only an http(s) address is ever a link');
  assert.equal(M.webUrl(' https://a.example/x '), 'https://a.example/x');
  for (const bad of ['', null, undefined, 'ftp://a', '//a', 'data:text/html,x', 7]) assert.equal(M.webUrl(bad), '');
});

test('favourites: the marked services, said plainly when there are none', () => {
  const f = M.favTile([
    { label: 'Jellyfin', url: 'https://media.home.example/web/', open_in: 'tab', place: { id: 'media', name: 'MEDIA' } },
    { label: '', url: 'http://10.0.0.9:8989' },
    { label: 'No address', url: '' },
    { label: 'Script', url: 'javascript:alert(1)' },
    null,
  ]);
  assert.deepEqual(f.items, [
    { label: 'Jellyfin', url: 'https://media.home.example/web/', host: 'media.home.example', openIn: 'tab',
      place: { id: 'media', name: 'MEDIA' } },
    { label: '10.0.0.9:8989', url: 'http://10.0.0.9:8989', host: '10.0.0.9:8989', openIn: 'auto', place: null },
  ]);
  assert.equal(f.empty, '');
  assert.equal(f.how, '');
  // none: everyone is told so; only someone who can mark one is told how
  for (const none of [[], undefined, null, [{ label: 'x' }]]) {
    assert.equal(M.favTile(none).empty, 'No favourites yet.');
    assert.equal(M.favTile(none, false).how, '');
    assert.match(M.favTile(none, true).how, /map editor/);
  }
  assert.ok(M.FAV_CAP > 6, 'six favourites fit a tile without "+N more"');
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
