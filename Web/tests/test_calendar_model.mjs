/* THE CALENDAR — the model, run with `node tests/test_calendar_model.mjs`.

   calendar-model.js turns rite rows into a UTC day: clocks (the Desk's `at`,
   and the hour read out of the surveyor's own `when` prose), day sets, hourly
   windows, the ever-turning's rhythm, the meetings between lanes, and what
   turns next. Plain node, no framework — the same shape as test_rack_model.mjs.

   The first eight cases predate v1.45.0 and are unchanged: THE FORGE'S DAY
   became one group of THE CALENDAR rather than a different set of rules, and
   `layoutForge` still answers exactly what the card's pointer asks it. The
   cases from "the clock comes from the Desk" down are what merging THE RITES
   into it added. */

import assert from 'node:assert/strict';
import {
  DAY_MIN, parseClock, parseDays, parseWindow, inWindow, toneOf, laneOf,
  clockOf, daysOf, everyOf, meetings, layoutForge, layoutDay,
  nextTurning, fmtClock, dayName,
} from '../static/js/calendar-model.js';

let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log(`  ✓ ${name}`); };

test('clocks: fixed, hourly, tolerant of Z/UTC, refusing nonsense', () => {
  assert.deepEqual(parseClock('13:45'), { hourly: false, minute: 825 });
  assert.deepEqual(parseClock('07:30Z'), { hourly: false, minute: 450 });
  assert.deepEqual(parseClock(' 22:00 UTC '), { hourly: false, minute: 1320 });
  assert.deepEqual(parseClock(':35'), { hourly: true, minute: 35 });
  assert.equal(parseClock('25:00'), null);
  assert.equal(parseClock(':75'), null);
  assert.equal(parseClock('on request'), null);
  assert.equal(parseClock(''), null);
  assert.equal(parseClock(undefined), null);
});

test('days: ranges wrap, lists, words, blank = every day, garbage = every day', () => {
  assert.deepEqual([...parseDays('Mon–Fri')].sort(), [1, 2, 3, 4, 5]);
  assert.deepEqual([...parseDays('mon-fri')].sort(), [1, 2, 3, 4, 5]);
  assert.deepEqual([...parseDays('Fri–Mon')].sort(), [0, 1, 5, 6]);
  assert.deepEqual([...parseDays('Sun')], [0]);
  assert.deepEqual([...parseDays('Sat, Sun')].sort(), [0, 6]);
  assert.deepEqual([...parseDays('weekdays')].sort(), [1, 2, 3, 4, 5]);
  assert.equal(parseDays('').size, 7);
  assert.equal(parseDays('whenever').size, 7, 'an unreadable day list must not hide the rite');
});

test('windows wrap past midnight', () => {
  const w = parseWindow('13:00–01:00');
  assert.deepEqual(w, { from: 780, to: 60 });
  assert.ok(inWindow(w, 13 * 60));
  assert.ok(inWindow(w, 23 * 60 + 35));
  assert.ok(inWindow(w, 35));
  assert.ok(!inWindow(w, 60), 'half-open at the far edge');
  assert.ok(!inWindow(w, 8 * 60));
  assert.ok(inWindow(null, 500), 'no window = all day');
  assert.equal(parseWindow('sometimes'), null);
});

test('tone: the heavy model is the one that never fit the card', () => {
  assert.equal(toneOf('qwen3:14b · 32k'), 'warm');
  assert.equal(toneOf('qwen3:30b-a3b-64k'), 'heavy');
  assert.equal(toneOf(''), 'cold');
  assert.equal(toneOf(undefined), 'cold');
});

test('an hourly lane inside a window draws only the hours it keeps', () => {
  const lane = laneOf({ name: 'scoring', at: ':35', hold: 5, between: '13:00–01:00' });
  assert.ok(lane.hourly);
  assert.equal(lane.blocks.length, 12, '13:35 … 00:35 is twelve ticks');
  const starts = lane.blocks.map((b) => b.start);
  assert.ok(starts.includes(13 * 60 + 35) && starts.includes(35), 'both ends of the window are kept');
  assert.ok(!starts.includes(8 * 60 + 35), '08:35 is outside the window');
  assert.equal(lane.blocks[0].end - lane.blocks[0].start, 5);
});

test('a fixed lane is one block, clipped at midnight, defaulting its hold', () => {
  const lane = laneOf({ name: 'brief', at: '13:00', hold: 25 });
  assert.deepEqual(lane.blocks, [{ start: 780, end: 805, hit: false }]);
  const late = laneOf({ name: 'late', at: '23:50', hold: 30 });
  assert.equal(late.blocks[0].end, DAY_MIN);
  const bare = laneOf({ name: 'bare', at: '06:00' });
  assert.equal(bare.blocks[0].end - bare.blocks[0].start, 10, 'a rite with no hold takes ten minutes');
  const none = laneOf({ name: 'boot', hold: 10 });
  assert.equal(none.blocks.length, 0, 'no clock, no block — listed, not drawn');
});

const RITES = [
  { name: 'Scout', asks: 'gpu-box', at: '07:30', hold: 15, model: 'qwen3:14b' },
  { name: 'Brief', asks: 'gpu-box', at: '13:00', hold: 25, model: 'qwen3:14b' },
  { name: 'Chain', asks: 'gpu-box', at: '13:45', hold: 45, days: 'Mon–Fri', model: 'qwen3:14b' },
  { name: 'Scoring', asks: 'gpu-box', at: ':35', hold: 5, between: '13:00–01:00', model: 'qwen3:14b' },
  { name: 'Review', asks: 'gpu-box', at: '22:00', hold: 15, days: 'Sun', model: 'qwen3:14b' },
  { name: 'Benchmarks', asks: 'gpu-box', hold: 10, model: 'qwen3:14b' },
  { name: 'Backups', host: 'APP HOST', at: '02:00' },              // asks nobody — not the forge's
];

test('the layout takes only the rites that ask this place, and lists the clockless', () => {
  const { lanes, unclocked, hits } = layoutForge(RITES, 'gpu-box');
  assert.deepEqual(lanes.map((l) => l.name), ['Scout', 'Brief', 'Chain', 'Review', 'Scoring'],
    'fixed lanes in clock order, the hourly ticks last');
  assert.deepEqual(unclocked.map((l) => l.name), ['Benchmarks']);
  assert.equal(hits.length, 0, 'the 09-04 slot plan has no meetings: chain ends 14:30, scoring is at :35');
  assert.equal(layoutForge(RITES, 'app-host').lanes.length, 0);
});

test('a meeting is two lanes wanting the forge at once, on a day they share', () => {
  const rites = [
    { name: 'A', asks: 'gpu-box', at: '13:00', hold: 30 },
    { name: 'B', asks: 'gpu-box', at: '13:20', hold: 10, days: 'Mon–Fri' },
    { name: 'C', asks: 'gpu-box', at: '13:20', hold: 10, days: 'Sun' },
  ];
  const { lanes, hits } = layoutForge(rites, 'gpu-box');
  assert.equal(hits.length, 2, 'A meets B (weekdays) and A meets C (Sunday); B and C never share a day');
  assert.deepEqual(hits[0].lanes, ['A', 'B']);
  assert.ok(lanes.find((l) => l.name === 'A').blocks[0].hit);
  assert.ok(lanes.find((l) => l.name === 'B').blocks[0].hit);
  const weekend = layoutForge([
    { name: 'B', asks: 'gpu-box', at: '13:20', hold: 10, days: 'Mon–Fri' },
    { name: 'C', asks: 'gpu-box', at: '13:20', hold: 10, days: 'Sun' },
  ], 'gpu-box');
  assert.equal(weekend.hits.length, 0);
});

test('what turns next respects the clock, the day set and the hourly window', () => {
  const { lanes } = layoutForge(RITES, 'gpu-box');
  // Wednesday 2026-09-09 13:10Z: the chain (13:45) is nearer than scoring (13:35)? no — scoring is
  const wed = new Date(Date.UTC(2026, 8, 9, 13, 10));
  const n1 = nextTurning(lanes, wed);
  assert.equal(n1.lane.name, 'Scoring'); assert.equal(fmtClock(n1.start), '13:35'); assert.equal(n1.inMin, 25);
  // Saturday 2026-09-12 01:00Z: scoring's window closed at 01:00; the scout at 07:30 is next
  const sat = new Date(Date.UTC(2026, 8, 12, 1, 0));
  const n2 = nextTurning(lanes, sat);
  assert.equal(n2.lane.name, 'Scout'); assert.equal(n2.dayOffset, 0); assert.equal(n2.inMin, 390);
  // Saturday 23:59Z: Sunday brings the scout at 07:30 (the chain waits for Monday)
  const satNight = new Date(Date.UTC(2026, 8, 12, 23, 59));
  const n3 = nextTurning(lanes, satNight);
  assert.equal(n3.lane.name, 'Scoring'); assert.equal(fmtClock(n3.start), '00:35'); assert.equal(n3.dayOffset, 1);
  // Friday 14:00Z, chain only: next chain is Monday
  const chainOnly = layoutForge([RITES[2]], 'gpu-box').lanes;
  const fri = new Date(Date.UTC(2026, 8, 11, 14, 0));
  const n4 = nextTurning(chainOnly, fri);
  assert.equal(n4.dayOffset, 3); assert.equal(dayName(fri.getUTCDay() + n4.dayOffset), 'Mon');
  assert.equal(nextTurning([], fri), null);
});

test('clock formatting wraps and pads', () => {
  assert.equal(fmtClock(825), '13:45');
  assert.equal(fmtClock(0), '00:00');
  assert.equal(fmtClock(DAY_MIN + 5), '00:05');
  assert.equal(dayName(7), 'Sun');
});

/* ── what THE CALENDAR added (v1.45.0) ─────────────────────────────────────── */

test('the clock comes from the Desk first, and the surveyor prose after', () => {
  assert.deepEqual(clockOf({ at: '13:45', when: 'Sun 03:00' }), { hourly: false, minute: 825, from: 'at' });
  assert.deepEqual(clockOf({ when: 'Sun 03:00 UTC' }), { hourly: false, minute: 180, from: 'when' });
  assert.deepEqual(clockOf({ when: 'daily 02:00' }), { hourly: false, minute: 120, from: 'when' });
  assert.deepEqual(clockOf({ when: '04:00 CDT the download host · 08:00 UTC the edge' }),
    { hourly: false, minute: 240, from: 'when' }, 'the FIRST clock in the prose, never a guess between them');
  assert.equal(clockOf({ when: 'on every save' }), null, 'no clock is listed, never invented');
  assert.equal(clockOf({ when: 'every 7 days from the last boot' }), null);
  assert.equal(clockOf({ when: 'at 99:99' }), null, 'nonsense in the prose is not a clock');
  assert.equal(clockOf({}), null);
});

test('a weekly rite takes its day from its prose when the Desk did not say', () => {
  assert.deepEqual([...daysOf({ cadence: 'weekly', when: 'Sun 04:15' })], [0]);
  assert.deepEqual([...daysOf({ cadence: 'weekly', when: 'Mon 13:00 UTC' })], [1]);
  assert.deepEqual([...daysOf({ cadence: 'weekly', days: 'Sat, Sun', when: 'Mon 13:00' })].sort(), [0, 6],
    'the Desk field wins over the prose');
  assert.equal(daysOf({ cadence: 'daily', when: 'Mon 13:00' }).size, 7,
    'only a WEEKLY rite may be pinned to a weekday by its prose');
  assert.equal(daysOf({ cadence: 'weekly', when: 'every 7 days from boot' }).size, 7,
    'prose that names no day must not hide the rite');
});

test('the ever-turning has a rhythm instead of an hour, and only inside a day', () => {
  assert.equal(everyOf({ when: 'every 5 min' }), 5);
  assert.equal(everyOf({ when: 'every 15 min' }), 15);
  assert.equal(everyOf({ when: '~every 60 days' }), 86400);
  assert.equal(everyOf({ when: 'on every save' }), null);
  const pulse = laneOf({ name: 'Pulse', cadence: 'continuous', when: 'every 5 min' });
  assert.equal(pulse.every, 5);
  assert.equal(pulse.blocks.length, 0, 'a rhythm is washed across the track, never drawn as a block');
  const letters = laneOf({ name: 'Letters', cadence: 'continuous', when: '~every 60 days' });
  assert.equal(letters.every, null, 'a rhythm longer than the day would claim it turns today');
  const clocked = laneOf({ name: 'Scoring', cadence: 'continuous', at: ':35', when: 'hourly at :35' });
  assert.equal(clocked.every, null, 'a clock beats a rhythm');
});

test('a monthly rite is a ghost: the hour is charted, the date is its own', () => {
  const vault = laneOf({ name: 'Vault Copy', cadence: 'monthly', when: '1st, 02:00' });
  assert.equal(vault.ghost, true);
  assert.deepEqual(vault.blocks, [{ start: 120, end: 130, hit: false }]);
  assert.equal(laneOf({ name: 'Backups', cadence: 'daily', when: 'daily 02:00' }).ghost, false);
});

test('meetings are found on one day, or across every day a pair shares', () => {
  const pair = () => [laneOf({ name: 'A', at: '13:00', hold: 30 }),
                      laneOf({ name: 'B', at: '13:20', hold: 10, days: 'Sun' })];
  assert.equal(meetings(pair(), 0).length, 1, 'on Sunday they meet');
  assert.equal(meetings(pair(), 1).length, 0, 'on Monday B does not turn');
  assert.equal(meetings(pair()).length, 1, 'and the standing answer is: they can');
});

const REALM = [
  ...RITES,
  { name: 'Backups', cadence: 'daily', when: 'daily 02:00', host: 'APP HOST' },
  { name: 'Export', cadence: 'weekly', when: 'Sun 03:00', host: 'HYPERVISOR' },
  { name: 'Vault Copy', cadence: 'monthly', when: '1st, 02:00' },
  { name: 'Pulse', cadence: 'continuous', when: 'every 5 min' },
  { name: 'Scribes', cadence: 'continuous', when: 'on every save' },
];

test('the day groups the forge first, then the turnings, then the clockless', () => {
  const sunday = layoutDay(REALM, { dow: 0 });
  assert.deepEqual(sunday.groups.map((g) => g.key),
    ['forge:gpu-box', 'daily', 'weekly', 'monthly', 'continuous', 'other', 'unclocked']);
  assert.deepEqual(sunday.groups.slice(1).map((g) => g.title),
    ['THE DAILY RITES', 'THE WEEKLY RITES', 'THE MONTHLY RITES',
     'THE EVER-TURNING', 'THE OTHER TURNINGS', 'NOT ON THE CLOCK']);
  assert.deepEqual(sunday.groups.find((g) => g.key === 'other').lanes.map((l) => l.name), ['Backups'],
    'an hour with no turning is grouped, never filed under the clockless');
  assert.equal(sunday.groups[0].title, null, 'the renderer names the forge after the place');
  const forge = sunday.groups[0];
  assert.equal(forge.kind, 'forge');
  assert.equal(forge.place, 'gpu-box');
  assert.deepEqual(forge.lanes.map((l) => l.name),
    ['Scout', 'Brief', 'Chain', 'Review', 'Scoring', 'Benchmarks'],
    'clocked lanes in clock order, the hourly ticks then the clockless last');
  assert.deepEqual(sunday.groups.at(-1).lanes.map((l) => l.name), ['Scribes'],
    'only a rite with neither clock nor rhythm is listed rather than drawn');
});

test('a rite keeps its row on the six days it does not turn', () => {
  const wed = layoutDay(REALM, { dow: 3 });
  const exp = wed.groups.find((g) => g.title === 'THE WEEKLY RITES').lanes.find((l) => l.name === 'Export');
  assert.equal(exp.blocks.length, 1, 'the rite still has its hour');
  assert.equal(exp.today.length, 0, 'it just does not fall on a Wednesday');
  const sun = layoutDay(REALM, { dow: 0 });
  assert.equal(sun.groups.find((g) => g.title === 'THE WEEKLY RITES')
    .lanes.find((l) => l.name === 'Export').today.length, 1);
  assert.ok(sun.drawn.length > wed.drawn.length, 'Sunday is the busy day');
  assert.ok(sun.drawn.some((l) => l.name === 'Pulse'), 'a rhythm counts as drawn on every day');
});

test('the meetings the day reports are the meetings the strip outlines', () => {
  const clash = [
    { name: 'A', asks: 'gpu-box', at: '13:00', hold: 60 },
    { name: 'B', asks: 'gpu-box', at: '13:20', hold: 10, days: 'Mon–Fri' },
  ];
  const mon = layoutDay(clash, { dow: 1 });
  assert.equal(mon.hits.length, 1);
  assert.ok(mon.groups[0].lanes.find((l) => l.name === 'A').today[0].hit,
    'the outlined block is the very block the row draws');
  const sun = layoutDay(clash, { dow: 0 });
  assert.equal(sun.hits.length, 0, 'B does not turn on a Sunday');
  assert.equal(sun.groups[0].standing.length, 1, 'but the standing warning survives the day step');
});

test('layoutForge is unchanged — the card pointer still asks the old question', () => {
  const { lanes, unclocked, hits } = layoutForge(REALM, 'gpu-box');
  assert.deepEqual(lanes.map((l) => l.name), ['Scout', 'Brief', 'Chain', 'Review', 'Scoring']);
  assert.deepEqual(unclocked.map((l) => l.name), ['Benchmarks']);
  assert.equal(hits.length, 0);
});

console.log(`\n${passed} passed`);
