/* THE MENU's rules, in plain node (NODES, 2026-11-16): the ⋯ of a place, a
   service and a collection is one list of actions, and what each lists
   comes from a few plain facts about the thing.

   Run:  node tests/test_menu_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ACTIONS, KINDS, STATES, CHECK_FIELDS, CHECK_TYPES, menuItems, menuKeys, agoWords, checkAsk, monitorMap,
  answerLine, refusalLine, checkPatch, patched,
  DIAGNOSE_STEPS, DIAGNOSE_WHYS, diagnoseAsk, diagnoseLines, diagnoseSummary, diagnoseLight, diagnoseRefusal, diagnoseKeys,
  wordsOf,
} from '../static/js/menu-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

/** A menu as its presses and its notes: an act, or the note's key in brackets. */
const acts = (kind, facts) => menuItems(kind, facts).map((i) => i.act || `(${i.key})`);
const keys = (kind, facts) => menuItems(kind, facts).map((i) => i.key);
const ALL = { alerts: true, edit: true, remove: true };

/* ── a place ─────────────────────────────────────────────────────────────── */

test('a place, plain: schedule, both switches on, alerts, edit, remove', () => {
  assert.deepEqual(menuItems('place', ALL), [
    { act: 'schedule', key: 'nodes_menu_schedule' },
    { act: 'mode-on', key: 'nodes_menu_mode_on' },
    { act: 'unmanaged-on', key: 'nodes_menu_unmanaged_on' },
    { act: 'alerts', key: 'nodes_menu_alerts' },
    { act: 'edit', key: 'nodes_menu_edit' },
    { act: 'remove', key: 'nodes_menu_remove' },
  ]);
});

test('a place in maintenance mode offers to turn it off', () => {
  assert.deepEqual(menuItems('place', { ...ALL, mode: { own: true } })[1], { act: 'mode-off', key: 'nodes_menu_mode_off' });
  // its own switch wins over a collection's: off is what a press can change
  assert.deepEqual(menuItems('place', { ...ALL, mode: { own: true, via: ['Core'] } })[1], { act: 'mode-off', key: 'nodes_menu_mode_off' });
});

test('a place in maintenance mode through a collection says so, and has no switch', () => {
  const items = menuItems('place', { ...ALL, mode: { via: ['Core', 'Lab'] } });
  assert.deepEqual(items[1], { act: '', key: 'nodes_menu_mode_via', vars: { name: 'Core, Lab' } });
  assert.deepEqual(acts('place', { ...ALL, mode: { via: ['Core'] } }),
    ['schedule', '(nodes_menu_mode_via)', 'unmanaged-on', 'alerts', 'edit', 'remove']);
});

test('a place marked unmanaged offers to watch it again', () => {
  assert.deepEqual(menuItems('place', { ...ALL, unmanaged: { own: true } })[2], { act: 'unmanaged-off', key: 'nodes_menu_unmanaged_off' });
  assert.deepEqual(menuItems('place', { ...ALL, unmanaged: { own: true, via: ['Core'] } })[2], { act: 'unmanaged-off', key: 'nodes_menu_unmanaged_off' });
});

test('a place unmanaged through a collection says so, and has no switch', () => {
  assert.deepEqual(menuItems('place', { ...ALL, unmanaged: { via: ['Guests'] } })[2],
    { act: '', key: 'nodes_menu_unmanaged_via', vars: { name: 'Guests' } });
});

test('a place has no "with its place" line, whatever it is told', () => {
  assert.deepEqual(acts('place', { ...ALL, mode: { place: true }, unmanaged: { place: true } }),
    ['schedule', 'mode-on', 'unmanaged-on', 'alerts', 'edit', 'remove']);
});

test('a place: alerts only for a viewer who may set them', () => {
  assert.deepEqual(acts('place', { edit: true, remove: true }), ['schedule', 'mode-on', 'unmanaged-on', 'edit', 'remove']);
});

test('a place with no edit rights lists neither Edit nor Remove', () => {
  assert.deepEqual(acts('place', { alerts: true }), ['schedule', 'mode-on', 'unmanaged-on', 'alerts']);
  assert.deepEqual(acts('place', { alerts: true, edit: true }), ['schedule', 'mode-on', 'unmanaged-on', 'alerts', 'edit']);
  assert.deepEqual(acts('place', { alerts: true, remove: true }), ['schedule', 'mode-on', 'unmanaged-on', 'alerts', 'remove']);
  assert.deepEqual(acts('place', {}), ['schedule', 'mode-on', 'unmanaged-on']);
  assert.deepEqual(acts('place'), ['schedule', 'mode-on', 'unmanaged-on']);
});

/* ── a service (a container is a service link) ───────────────────────────── */

test('a service, plain: schedule, both switches on, collections, alerts', () => {
  assert.deepEqual(menuItems('service', { alerts: true }), [
    { act: 'schedule', key: 'nodes_menu_schedule' },
    { act: 'mode-on', key: 'nodes_menu_mode_on' },
    { act: 'unmanaged-on', key: 'nodes_menu_unmanaged_on' },
    { act: 'collections', key: 'nodes_menu_collections' },
    { act: 'alerts', key: 'nodes_menu_alerts' },
  ]);
});

test('a service never lists Edit, Rename or Remove', () => {
  assert.deepEqual(acts('service', ALL), ['schedule', 'mode-on', 'unmanaged-on', 'collections', 'alerts']);
});

test('a service without alerts still lists Collections', () => {
  assert.deepEqual(acts('service', {}), ['schedule', 'mode-on', 'unmanaged-on', 'collections']);
});

test('a service in maintenance mode: itself, then a collection, then its place', () => {
  assert.deepEqual(menuItems('service', { mode: { own: true, via: ['Core'], place: true } })[1],
    { act: 'mode-off', key: 'nodes_menu_mode_off' });
  assert.deepEqual(menuItems('service', { mode: { via: ['Core', 'Lab'], place: true } })[1],
    { act: '', key: 'nodes_menu_mode_via', vars: { name: 'Core, Lab' } });
  assert.deepEqual(menuItems('service', { mode: { place: true } })[1], { act: '', key: 'nodes_svc_mode_place' });
  assert.deepEqual(menuItems('service', { mode: { via: [] } })[1], { act: 'mode-on', key: 'nodes_menu_mode_on' });
});

test('a service unmanaged: itself, then its place, then a collection', () => {
  assert.deepEqual(menuItems('service', { unmanaged: { own: true, via: ['Guests'], place: true } })[2],
    { act: 'unmanaged-off', key: 'nodes_menu_unmanaged_off' });
  assert.deepEqual(menuItems('service', { unmanaged: { via: ['Guests'], place: true } })[2],
    { act: '', key: 'nodes_svc_unmanaged_place' });
  assert.deepEqual(menuItems('service', { unmanaged: { via: ['Guests', 'Old'] } })[2],
    { act: '', key: 'nodes_menu_unmanaged_via', vars: { name: 'Guests, Old' } });
  assert.deepEqual(menuItems('service', { unmanaged: {} })[2], { act: 'unmanaged-on', key: 'nodes_menu_unmanaged_on' });
});

test('a service: each switch reads on its own', () => {
  assert.deepEqual(acts('service', { alerts: true, mode: { place: true }, unmanaged: { via: ['Guests'] } }),
    ['schedule', '(nodes_svc_mode_place)', '(nodes_menu_unmanaged_via)', 'collections', 'alerts']);
  assert.deepEqual(acts('service', { alerts: true, mode: { own: true }, unmanaged: { place: true } }),
    ['schedule', 'mode-off', '(nodes_svc_unmanaged_place)', 'collections', 'alerts']);
});

/* ── a collection ────────────────────────────────────────────────────────── */

test('a collection, plain: the rail\'s five, in the order its buttons had', () => {
  assert.deepEqual(menuItems('collection', { edit: true, remove: true }), [
    { act: 'schedule', key: 'nodes_rail_schedule' },
    { act: 'mode-on', key: 'nodes_rail_mode_on' },
    { act: 'unmanaged-on', key: 'nodes_rail_unmanaged_on' },
    { act: 'rename', key: 'nodes_rail_rename' },
    { act: 'remove', key: 'nodes_rail_remove' },
  ]);
});

test('a collection in maintenance mode, or unmanaged, offers the way back', () => {
  assert.deepEqual(keys('collection', { edit: true, remove: true, mode: { own: true } }),
    ['nodes_rail_schedule', 'nodes_rail_mode_off', 'nodes_rail_unmanaged_on', 'nodes_rail_rename', 'nodes_rail_remove']);
  assert.deepEqual(keys('collection', { edit: true, remove: true, unmanaged: { own: true } }),
    ['nodes_rail_schedule', 'nodes_rail_mode_on', 'nodes_rail_unmanaged_off', 'nodes_rail_rename', 'nodes_rail_remove']);
  assert.deepEqual(acts('collection', { edit: true, remove: true, mode: { own: true }, unmanaged: { own: true } }),
    ['schedule', 'mode-off', 'unmanaged-off', 'rename', 'remove']);
});

test('a collection is through nothing: it has switches, never a note', () => {
  assert.deepEqual(acts('collection', { edit: true, remove: true, mode: { via: ['Core'], place: true }, unmanaged: { via: ['Core'], place: true } }),
    ['schedule', 'mode-on', 'unmanaged-on', 'rename', 'remove']);
});

test('a collection has no Alerts line (its bell is in the rail) and no Collections', () => {
  assert.deepEqual(acts('collection', ALL), ['schedule', 'mode-on', 'unmanaged-on', 'rename', 'remove']);
});

test('a collection with no edit rights keeps only the ways out', () => {
  assert.deepEqual(acts('collection', {}), ['schedule', 'mode-on', 'unmanaged-on']);
  assert.deepEqual(acts('collection', { edit: true }), ['schedule', 'mode-on', 'unmanaged-on', 'rename']);
  assert.deepEqual(acts('collection', { remove: true }), ['schedule', 'mode-on', 'unmanaged-on', 'remove']);
});

/* ── the read-only way: a phone's sheet (2026-11-16) ─────────────────────── */

const RO = { readonly: true };
const EVERY = { ...ALL, readonly: true, mode: { own: true, via: ['Core'], place: true }, unmanaged: { own: true, via: ['Guests'], place: true } };

test('a phone, a place: its state, then Open its card', () => {
  assert.deepEqual(menuItems('place', { ...RO, state: 'down' }), [
    { act: '', key: 'nodes_state_down' },
    { act: 'open', key: 'nodes_open' },
  ]);
});

test('a phone, a place in each state: the state line names it, and nothing writes', () => {
  for (const state of STATES) {
    const items = menuItems('place', { ...RO, ...ALL, state });
    assert.deepEqual(items[0], { act: '', key: `nodes_state_${state}` }, state);
    assert.deepEqual(items.map((i) => i.act), ['', 'open'], state);
  }
  // a state the model does not know reads as not known
  for (const odd of [undefined, '', 'on fire', 7, null]) {
    assert.equal(menuItems('place', { ...RO, state: odd })[0].key, 'nodes_state_unknown', String(odd));
  }
});

test('a phone, a place someone watches: the state, then the column\'s "Watched by" and who', () => {
  assert.deepEqual(menuItems('place', { ...RO, state: 'healthy', watched: 'Kuma' })[0], {
    act: '', key: 'nodes_menu_seen', vars: { by: 'Kuma' },
    words: { state: 'nodes_state_healthy', watched: 'nodes_col_confirmed' },
  });
  // no one (2026-11-17): the state, then "Not watched"
  for (const watched of ['', '   ']) {
    assert.deepEqual(menuItems('place', { ...RO, state: 'healthy', watched })[0], {
      act: '', key: 'nodes_menu_seen_none', words: { state: 'nodes_state_healthy', watched: 'nodes_menu_unwatched' },
    }, JSON.stringify(watched));
  }
  // not said at all, or not words: the state alone
  for (const watched of [undefined, null, 3]) {
    assert.deepEqual(menuItems('place', { ...RO, state: 'healthy', watched })[0], { act: '', key: 'nodes_state_healthy' }, String(watched));
  }
});

test('a phone, a place whose check has answered: its last answer under the first line, nothing else new', () => {
  const items = menuItems('place', { ...RO, state: 'down', watched: 'Atlas', last: { state: 'down', secs: 125 } });
  assert.deepEqual(items[1], { act: '', key: 'nodes_menu_last', vars: { n: 2 }, words: { state: 'nodes_state_down', ago: 'nodes_ago_mins' } });
  assert.deepEqual(items.map((i) => i.act), ['', '', 'open']);
  // a phone writes nothing, and asks nothing: no Check…, no Check now, whatever it is told
  assert.deepEqual(acts('place', { ...RO, check: true, ask: true, silent: 'off', alerts: true }), ['(nodes_state_unknown)', 'open']);
});

test('a phone, a place in mode or unmanaged through a collection: the same quiet notes, never a switch', () => {
  assert.deepEqual(acts('place', { ...RO, state: 'maintenance', mode: { via: ['Core'] } }),
    ['(nodes_state_maintenance)', '(nodes_menu_mode_via)', 'open']);
  assert.deepEqual(acts('place', { ...RO, state: 'unmanaged', unmanaged: { via: ['Guests'] } }),
    ['(nodes_state_unmanaged)', '(nodes_menu_unmanaged_via)', 'open']);
  assert.deepEqual(menuItems('place', { ...RO, mode: { via: ['Core', 'Lab'] } })[1],
    { act: '', key: 'nodes_menu_mode_via', vars: { name: 'Core, Lab' } });
  // its own mode or unmanaged is its state, said already: no line, no switch
  assert.deepEqual(acts('place', { ...RO, state: 'unmanaged', mode: { own: true }, unmanaged: { own: true } }),
    ['(nodes_state_unmanaged)', 'open']);
  // own and through a collection: the note stays (the switch would have won it)
  assert.deepEqual(acts('place', { ...RO, mode: { own: true, via: ['Core'] } }),
    ['(nodes_state_unknown)', '(nodes_menu_mode_via)', 'open']);
});

test('a phone: every fact true, still only notes and Open its card, whoever asks', () => {
  const items = menuItems('place', { ...EVERY, state: 'down', watched: 'Atlas' });
  assert.deepEqual(items.map((i) => i.act), ['', '', '', 'open']);
  for (const item of items) if (item.act) assert.equal(item.act, 'open');
  assert.equal(items.at(-1).key, 'nodes_open');
});

test('a phone: a service and a collection have no menu (their lines are not drawn there)', () => {
  assert.deepEqual(menuItems('service', EVERY), []);
  assert.deepEqual(menuItems('collection', EVERY), []);
  assert.deepEqual(menuItems('service', RO), []);
});

test('only `readonly: true` is the read-only way', () => {
  for (const odd of ['yes', 1, {}, false]) {
    assert.deepEqual(acts('place', { ...ALL, readonly: odd }), ['schedule', 'mode-on', 'unmanaged-on', 'alerts', 'edit', 'remove'], String(odd));
  }
});

test('the states are the view\'s own (nodes-state.js STATES)', () => {
  const src = readFileSync(new URL('../static/js/nodes-state.js', import.meta.url), 'utf8');
  const list = Function(`return ${src.match(/export const STATES = (\[[^\]]*\]);/)[1]}`)();
  assert.deepEqual(STATES, list);
});

/* ── the table ───────────────────────────────────────────────────────────── */

test('an unknown kind has no menu, and odd facts read as no', () => {
  assert.deepEqual(menuItems('network', ALL), []);
  assert.deepEqual(menuItems('', ALL), []);
  assert.deepEqual(menuItems(undefined), []);
  for (const odd of [null, 7, 'yes', []]) {
    assert.deepEqual(acts('place', odd), ['schedule', 'mode-on', 'unmanaged-on'], String(odd));
    assert.deepEqual(acts('service', { mode: odd, unmanaged: odd }), ['schedule', 'mode-on', 'unmanaged-on', 'collections'], String(odd));
  }
  // names that are not names are not a reason
  assert.deepEqual(menuItems('place', { mode: { via: ['', null, 3] } })[1], { act: 'mode-on', key: 'nodes_menu_mode_on' });
  assert.deepEqual(menuItems('place', { mode: { via: 'Core' } })[1], { act: 'mode-on', key: 'nodes_menu_mode_on' });
});

test('every kind lists the three ways out first, in one order', () => {
  for (const kind of KINDS) {
    assert.deepEqual(acts(kind, ALL).slice(0, 3), ['schedule', 'mode-on', 'unmanaged-on'], kind);
  }
});

test('a note is never a press, and a press always has its words', () => {
  const states = [{}, { own: true }, { via: ['A'] }, { place: true }, { via: ['A'], place: true }];
  for (const kind of KINDS) {
    for (const mode of states) {
      for (const unmanaged of states) {
        const items = menuItems(kind, { ...ALL, mode, unmanaged });
        for (const item of items) {
          assert.equal(typeof item.key, 'string');
          assert.ok(item.key.startsWith('nodes_'), item.key);
          if (!item.act) assert.match(item.key, /_via$|_place$|_watched$|_unwatched$|_last$/, item.key);
        }
        const presses = items.map((i) => i.act).filter(Boolean);
        assert.equal(new Set(presses).size, presses.length, `${kind}: no act twice`);
      }
    }
  }
});

test('the table is one list: no action twice, and each names a kind', () => {
  const ids = ACTIONS.map((a) => a.act);
  assert.equal(new Set(ids).size, ids.length);
  for (const a of ACTIONS) {
    const words = a.way ? a.on : a.words;
    assert.ok(Object.keys(words).length > 0 && Object.keys(words).every((k) => KINDS.includes(k)), a.act);
    if (a.way) assert.deepEqual(Object.keys(a.off), Object.keys(a.on), a.act);
  }
});

test("the menu's words: every key has its plain words in NODES_TEXT", () => {
  const src = readFileSync(new URL('../static/js/nodes-text.js', import.meta.url), 'utf8');
  const body = src.match(/export const NODES_TEXT = \{([\s\S]*?)\n\};/)[1];
  const words = Function(`return {${body}}`)();
  const all = menuKeys();
  assert.ok(all.length >= 18, String(all.length));
  for (const key of all) assert.ok(typeof words[key] === 'string' && words[key], key);
  // a note that names its collections has somewhere to put the names
  for (const key of ['nodes_menu_mode_via', 'nodes_menu_unmanaged_via']) assert.match(words[key], /\{name\}/, key);
  // a phone's first line takes all its words from other keys
  for (const v of ['{state}', '{watched}', '{by}']) assert.ok(words.nodes_menu_seen.includes(v), v);
  assert.equal(words.nodes_menu_seen.replace(/\{\w+\}/g, '').replace(/[\s·]/g, ''), '');
  for (const v of ['{state}', '{watched}']) assert.ok(words.nodes_menu_seen_none.includes(v), v);
  assert.equal(words.nodes_menu_seen_none.replace(/\{\w+\}/g, '').replace(/[\s·]/g, ''), '');
  // the wide menu's first line is the column's words and who (2026-11-17)
  assert.equal(words.nodes_menu_watched.replace(/\{\w+\}/g, '').trim(), '');
  for (const v of ['{state}', '{ago}']) assert.ok(words.nodes_menu_last.includes(v), v);
  for (const key of ['nodes_ago_mins', 'nodes_ago_hours', 'nodes_ago_days']) assert.match(words[key], /\{n\}/, key);
});

/* ── the engines in the menu (2026-11-17) ────────────────────────────────── */

test('a place: who watches it first, then its last answer, then what it had', () => {
  assert.deepEqual(menuItems('place', { ...ALL, watched: 'Kuma', last: { state: 'healthy', secs: 30 } }).slice(0, 3), [
    { act: '', key: 'nodes_menu_watched', vars: { by: 'Kuma' }, words: { watched: 'nodes_col_confirmed' } },
    { act: '', key: 'nodes_menu_last', vars: { n: 0 }, words: { state: 'nodes_state_healthy', ago: 'nodes_ago_now' } },
    { act: 'schedule', key: 'nodes_menu_schedule' },
  ]);
  // nothing watches it: "Not watched"; not said: no line
  assert.deepEqual(menuItems('place', { watched: '' })[0], { act: '', key: 'nodes_menu_unwatched' });
  assert.deepEqual(menuItems('place', { watched: '  ' })[0], { act: '', key: 'nodes_menu_unwatched' });
  assert.deepEqual(acts('place', {}), ['schedule', 'mode-on', 'unmanaged-on']);
  assert.deepEqual(acts('place', { watched: 7 }), ['schedule', 'mode-on', 'unmanaged-on']);
});

test('a service: the same two lines; a collection has neither', () => {
  assert.deepEqual(keys('service', { watched: 'Atlas', last: { state: 'down', secs: 7200 } }).slice(0, 2),
    ['nodes_menu_watched', 'nodes_menu_last']);
  assert.deepEqual(acts('collection', { edit: true, remove: true, watched: 'Kuma', last: { state: 'down', secs: 1 }, check: true, ask: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'rename', 'remove']);
});

test('the last answer: only a state it knows and a number of seconds', () => {
  for (const last of [null, {}, { state: 'down' }, { secs: 3 }, { state: 'on fire', secs: 3 }, { state: 'down', secs: '3' },
    { state: 'down', secs: NaN }, { state: 'down', secs: Infinity }, 'down']) {
    assert.deepEqual(acts('place', { last }), ['schedule', 'mode-on', 'unmanaged-on'], JSON.stringify(last));
  }
});

test('how long ago: just now, minutes, hours, days, each with its one', () => {
  const cases = [[-5, 'nodes_ago_now', 0], [0, 'nodes_ago_now', 0], [59.9, 'nodes_ago_now', 0], [60, 'nodes_ago_min', 1],
    [119, 'nodes_ago_min', 1], [120, 'nodes_ago_mins', 2], [3599, 'nodes_ago_mins', 59], [3600, 'nodes_ago_hour', 1],
    [7200, 'nodes_ago_hours', 2], [86399, 'nodes_ago_hours', 23], [86400, 'nodes_ago_day', 1], [86400 * 9, 'nodes_ago_days', 9]];
  for (const [secs, key, n] of cases) assert.deepEqual(agoWords(secs), { key, n }, String(secs));
  assert.deepEqual(agoWords('x'), { key: 'nodes_ago_now', n: 0 });
});

test('Check… and Check now: after the ways out and Collections, before Alerts, Edit and Remove', () => {
  assert.deepEqual(acts('place', { ...ALL, check: true, ask: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'check', 'check-now', 'alerts', 'edit', 'remove']);
  assert.deepEqual(acts('service', { alerts: true, check: true, ask: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'collections', 'check', 'check-now', 'alerts']);
  assert.deepEqual(menuItems('place', { check: true, ask: true }).slice(3),
    [{ act: 'check', key: 'nodes_menu_check' }, { act: 'check-now', key: 'nodes_menu_check_now' }]);
  // Check… alone: a thing with no check Atlas asks has no Check now
  assert.deepEqual(acts('place', { check: true }), ['schedule', 'mode-on', 'unmanaged-on', 'check']);
  for (const odd of ['', 'yes', 'none', 1, {}, null]) {
    assert.deepEqual(acts('place', { check: true, ask: odd }), ['schedule', 'mode-on', 'unmanaged-on', 'check'], String(odd));
  }
});

test('Check now held: shown, with the reason in words, never a press', () => {
  for (const why of ['kuma', 'unmanaged', 'off']) {
    for (const kind of ['place', 'service']) {
      const item = menuItems(kind, { ask: why }).find((i) => i.act === 'check-now');
      assert.deepEqual(item, { act: 'check-now', key: `nodes_menu_check_now_${why}`, held: true }, `${kind} ${why}`);
    }
  }
  // the table's own keys only: an inherited name is no reason
  assert.ok(!menuItems('place', { ask: 'toString' }).some((i) => i.act === 'check-now'));
});

test('Alerts says when nothing can send, and is still the press that opens the panel', () => {
  assert.deepEqual(menuItems('place', { alerts: true, silent: 'off' }).at(-1), { act: 'alerts', key: 'nodes_menu_alerts_off' });
  assert.deepEqual(menuItems('service', { alerts: true, silent: 'nowhere' }).at(-1), { act: 'alerts', key: 'nodes_menu_alerts_nowhere' });
  for (const odd of ['', 'later', 'toString', 1, null]) {
    assert.deepEqual(menuItems('place', { alerts: true, silent: odd }).at(-1), { act: 'alerts', key: 'nodes_menu_alerts' }, String(odd));
  }
  // no alerts for this viewer: nothing to say about them
  assert.ok(!menuItems('place', { silent: 'off' }).some((i) => i.act === 'alerts'));
});

test('everything at once keeps the order, and Remove is last', () => {
  const items = menuItems('place', { ...ALL, watched: 'Kuma', last: { state: 'down', secs: 90 }, check: true, ask: 'kuma', silent: 'nowhere' });
  assert.deepEqual(items.map((i) => i.act || i.key),
    ['nodes_menu_watched', 'nodes_menu_last', 'schedule', 'mode-on', 'unmanaged-on', 'check', 'check-now', 'alerts', 'edit', 'remove']);
});

/* ── may Atlas ask it now (checkAsk), as the server's refusals ───────────── */

const MAP = {
  meta: {},
  signals: { kuma: { 'Gate monitor': 'gate' } },
  nodes: [
    { id: 'gate', check: 'tcp', links: [{ label: 'UI', url: 'https://gate.example/' }] },
    { id: 'tower', check: 'http', monitors: ['Tower ping'], links: [] },
    { id: 'well', links: [
      { label: 'DB', check: 'tcp', check_port: 5432 },
      { label: 'Web', url: 'http://well.example/' },
      { label: 'Quiet', url: 'http://well.example/q', check: 'off' },
      { label: 'Bare' },
      { label: 'Named', kuma: 'Well web', url: 'http://well.example/w' },
      { label: 'Tied', kuma: 'Tower ping', url: 'http://tower.example/' },
      { label: 'Later', url: 'http://well.example/l', planned: true },
    ] },
    { id: 'plain' },
    { id: 'plan', check: 'http', planned: true },
  ],
};

test('checkAsk, a place: its own check, a monitor speaking for it, none', () => {
  assert.equal(checkAsk('place', MAP, 'plain'), '');
  assert.equal(checkAsk('place', MAP, 'plan'), '', 'planned: not built, nothing to ask');
  assert.equal(checkAsk('place', MAP, 'nowhere'), '');
  // a monitor tied to it (signals.kuma, or its own `monitors`): Kuma speaks
  assert.equal(checkAsk('place', MAP, 'gate'), 'kuma');
  assert.equal(checkAsk('place', MAP, 'tower'), 'kuma');
  // beside Kuma: asked when it has a check of its own
  const shadow = { ...MAP, meta: { shadow_kuma: true } };
  assert.equal(checkAsk('place', shadow, 'gate'), true);
  assert.equal(checkAsk('place', { ...shadow, nodes: [{ id: 'gate' }] }, 'gate'), 'kuma');
  // no monitor, a check: asked
  assert.equal(checkAsk('place', { nodes: [{ id: 'gate', check: 'dns' }] }, 'gate'), true);
  assert.equal(checkAsk('place', { nodes: [{ id: 'gate', check: 'off' }] }, 'gate'), '');
});

test('checkAsk, a service: its check, its address, off, a named monitor', () => {
  assert.equal(checkAsk('service', MAP, 'well/DB'), true);
  assert.equal(checkAsk('service', MAP, 'well/Web'), true, 'an http address is asked by GET');
  assert.equal(checkAsk('service', MAP, 'well/Quiet'), '');
  assert.equal(checkAsk('service', MAP, 'well/Bare'), '');
  assert.equal(checkAsk('service', MAP, 'well/Later'), '');
  assert.equal(checkAsk('service', MAP, 'gate/UI'), true);
  // its key is the monitor it names
  assert.equal(checkAsk('service', MAP, 'Well web'), 'kuma');
  assert.equal(checkAsk('service', MAP, 'well/Named'), '', 'a named monitor is its key');
  const shadow = { ...MAP, meta: { shadow_kuma: true } };
  assert.equal(checkAsk('service', shadow, 'Well web'), true);
  // a monitor tied to a place has no answer of its own to set beside
  assert.equal(checkAsk('service', shadow, 'Tower ping'), 'kuma');
});

test('checkAsk: unmanaged first, then the checks source', () => {
  assert.equal(checkAsk('place', MAP, 'plain', { unmanaged: true }), 'unmanaged');
  assert.equal(checkAsk('service', MAP, 'Well web', { unmanaged: true }), 'unmanaged');
  assert.equal(checkAsk('service', MAP, 'well/DB', { on: false }), 'off');
  assert.equal(checkAsk('service', MAP, 'well/DB', { on: true }), true);
  assert.equal(checkAsk('service', MAP, 'well/DB', { on: undefined }), true, 'not known is not off');
  // the server answers a monitor before the source
  assert.equal(checkAsk('place', MAP, 'gate', { on: false }), 'kuma');
  assert.equal(checkAsk('place', MAP, 'plain', { on: false }), '');
  assert.equal(checkAsk('collection', MAP, 'gate'), '');
  for (const odd of [null, {}, { nodes: 'x' }, { nodes: [null, 3, { id: 7 }] }]) assert.equal(checkAsk('place', odd, 'gate'), '');
});

test('monitorMap: a place\'s own monitors, then signals.kuma, which wins', () => {
  assert.deepEqual(monitorMap({ nodes: [{ id: 'a', monitors: ['m', '', 3] }, { id: 'b', monitors: ['m'] }] }), { m: 'a' });
  assert.deepEqual(monitorMap({ nodes: [{ id: 'a', monitors: ['m'] }], signals: { kuma: { m: 'b', n: 4 } } }), { m: 'b' });
  assert.deepEqual(monitorMap(null), {});
});

/* ── what Check now answered, and why it was refused ─────────────────────── */

const NOW = Date.parse('2026-11-17T12:00:00Z');

test('answerLine: up, in how long', () => {
  assert.deepEqual(answerLine({ said: 'healthy', ms: 42, error: null, tls: null }, NOW), {
    tone: 'up', parts: [{ key: 'nodes_state_healthy' }, { key: 'nodes_asked_ms', vars: { ms: 42 } }],
  });
});

test('answerLine: down, with the error in words and the status', () => {
  assert.deepEqual(answerLine({ said: 'down', ms: 9, error: 'answered with a server error', status: 503 }, NOW), {
    tone: 'down',
    parts: [{ key: 'nodes_state_down' }, { key: 'nodes_asked_ms', vars: { ms: 9 } },
      { key: 'nodes_asked_error', vars: { why: 'answered with a server error' } }, { key: 'nodes_asked_status', vars: { status: 503 } }],
  });
  // no answer at all: not known, and why
  assert.deepEqual(answerLine({ said: null, ms: 3000, error: 'no answer: the check could not be asked, or did not finish in time' }, NOW).parts,
    [{ key: 'nodes_state_unknown' }, { key: 'nodes_asked_error', vars: { why: 'no answer: the check could not be asked, or did not finish in time' } }]);
  assert.equal(answerLine({ said: 'degraded' }, NOW).tone, 'warn');
  // asked now, no answer: an older answer's word and time are not this one's
  const NO = 'no answer: the check could not be asked, or did not finish in time';
  const stale = answerLine({ said: 'healthy', ms: 42, error: NO, asked_at: '2026-11-17T12:00:00Z', heard_at: '2026-11-17T11:50:00Z' }, NOW);
  assert.deepEqual(stale, { tone: '', parts: [{ key: 'nodes_state_unknown' }, { key: 'nodes_asked_error', vars: { why: NO } }] });
  assert.equal(answerLine({ said: 'healthy', ms: 42, asked_at: '2026-11-17T12:00:00Z', heard_at: null }, NOW).parts[0].key, 'nodes_state_unknown');
  // heard after it was asked: the answer it gave
  assert.deepEqual(answerLine({ said: 'healthy', ms: 42, asked_at: '2026-11-17T12:00:00Z', heard_at: '2026-11-17T12:00:00Z' }, NOW),
    { tone: 'up', parts: [{ key: 'nodes_state_healthy' }, { key: 'nodes_asked_ms', vars: { ms: 42 } }] });
});

test("answerLine: the certificate's days left, one day, lapsed", () => {
  const cert = (expires) => answerLine({ said: 'healthy', tls: { expires, issuer: 'X' } }, NOW).parts.at(-1);
  assert.deepEqual(cert('2026-12-17'), { key: 'nodes_asked_cert_days', vars: { n: 30 } });
  assert.deepEqual(cert('2026-11-18'), { key: 'nodes_asked_cert_1day' });
  assert.deepEqual(cert('2026-11-17'), { key: 'nodes_asked_cert_days', vars: { n: 0 } });
  assert.deepEqual(cert('2026-11-16'), { key: 'nodes_asked_cert_lapsed' });
  assert.equal(answerLine({ said: 'healthy', tls: { expires: 'soon' } }, NOW).parts.length, 1);
});

test('answerLine: the stored answer, when another worker held the store', () => {
  assert.deepEqual(answerLine({ said: 'healthy', asked: false, stored: true }, NOW).parts.at(-1), { key: 'nodes_asked_held' });
  assert.equal(answerLine({ said: 'healthy', asked: true }, NOW).parts.length, 1);
  assert.deepEqual(answerLine(null, NOW), { tone: '', parts: [{ key: 'nodes_state_unknown' }] });
});

test('refusalLine: each refusal in words', () => {
  assert.deepEqual(refusalLine(403, { error: 'admins only' }), { key: 'nodes_asked_403' });
  assert.deepEqual(refusalLine(404, { error: 'no such check' }), { key: 'nodes_asked_404' });
  for (const why of ['kuma', 'unmanaged', 'off']) assert.deepEqual(refusalLine(409, { why }), { key: `nodes_asked_${why}` });
  assert.deepEqual(refusalLine(429, { why: 'soon', retry_after: 12 }), { key: 'nodes_asked_soon', vars: { n: 12 } });
  assert.deepEqual(refusalLine(429, { why: 'spent', retry_after: 1 }), { key: 'nodes_asked_spent_one', vars: { n: 1 } });
  assert.deepEqual(refusalLine(429, { why: 'spent', retry_after: 2.2 }), { key: 'nodes_asked_spent', vars: { n: 3 } });
  assert.deepEqual(refusalLine(429, {}), { key: 'nodes_asked_soon_one', vars: { n: 1 } });
  assert.deepEqual(refusalLine(409, { why: 'other', error: 'odd' }), { key: 'nodes_asked_failed', vars: { why: 'odd' } });
  assert.deepEqual(refusalLine(500, null), { key: 'nodes_asked_failed', vars: { why: '500' } });
  assert.deepEqual(refusalLine(0, null), { key: 'nodes_asked_failed', vars: { why: 'no answer' } });
});

test('refusals and answers: every key they give has its words', () => {
  const src = readFileSync(new URL('../static/js/nodes-text.js', import.meta.url), 'utf8');
  const words = Function(`return {${src.match(/export const NODES_TEXT = \{([\s\S]*?)\n\};/)[1]}}`)();
  const given = [
    ...[403, 404, 500].map((s) => refusalLine(s, {})),
    ...['kuma', 'unmanaged', 'off'].map((why) => refusalLine(409, { why })),
    ...['soon', 'spent'].flatMap((why) => [refusalLine(429, { why, retry_after: 1 }), refusalLine(429, { why, retry_after: 5 })]),
    ...answerLine({ said: 'down', ms: 1, error: 'x', status: 500, asked: false, stored: true, tls: { expires: '2026-11-16' } }, NOW).parts,
    ...answerLine({ said: 'healthy', tls: { expires: '2026-11-18' } }, NOW).parts,
    ...answerLine({ said: 'healthy', tls: { expires: '2027-11-18' } }, NOW).parts,
  ];
  for (const { key } of given) assert.ok(typeof words[key] === 'string' && words[key], key);
  for (const key of ['nodes_asking', 'nodes_scope_check', 'nodes_check_go', 'nodes_check_saved', 'nodes_check_default',
    'nodes_check_none', 'nodes_check_gone']) assert.ok(words[key], key);
  // plain words: no em dash anywhere in what this stage added
  for (const [k, v] of Object.entries(words)) if (/^nodes_(asked|asking|check|ago|menu_(check|alerts_|watched|unwatched|last|seen_none))/.test(k)) assert.doesNotMatch(v, /—/, k);
});

/* ── what Check… saves ───────────────────────────────────────────────────── */

test('checkPatch: only what changed, null for what was cleared, only the check fields', () => {
  const was = { id: 'gate', check: 'tcp', check_host: '10.0.0.1', check_port: 22, name: 'Gate' };
  assert.deepEqual(checkPatch(was, { check: 'tcp', check_host: '10.0.0.1', check_port: 22, check_expect: '', check_every: '' }), {});
  assert.deepEqual(checkPatch(was, { check: 'http', check_host: ' https://gate.example/ ', check_port: '', check_every: 60 }),
    { check: 'http', check_host: 'https://gate.example/', check_port: null, check_every: 60 });
  // a field the form does not hold is left alone; a name is never a check field
  assert.deepEqual(checkPatch(was, { name: 'Other', check_port: 23 }), { check_port: 23 });
  // blank to blank is nothing, whatever blank was
  assert.deepEqual(checkPatch({ check: '', check_expect: null }, { check: '', check_expect: '' }), {});
  assert.deepEqual(checkPatch(null, { check: 'dns' }), { check: 'dns' });
  assert.deepEqual(checkPatch(was, null), {});
});

test('patched: a link with the patch laid on it, never a null inside', () => {
  const link = { label: 'DB', check: 'tcp', check_port: 5432, url: '' };
  assert.deepEqual(patched(link, { check_port: null, check_host: 'db.example' }), { label: 'DB', check: 'tcp', url: '', check_host: 'db.example' });
  assert.deepEqual(link, { label: 'DB', check: 'tcp', check_port: 5432, url: '' }, 'the link on disk is not changed');
  assert.deepEqual(patched(null, { check: 'dns' }), { check: 'dns' });
});

test("the check's fields are the schema's, in the Desk form's order", () => {
  const src = readFileSync(new URL('../schema.py', import.meta.url), 'utf8');
  const body = src.match(/def _check_fields\(on_place\):([\s\S]*?)\n\n\n/)[1];
  const order = [...body.matchAll(/f\("(check\w*)"/g)].map((m) => m[1]);
  assert.deepEqual(CHECK_FIELDS, order.filter((n) => CHECK_FIELDS.includes(n)), 'the same order');
  for (const name of CHECK_FIELDS) assert.ok(order.includes(name), name);
  const types = src.match(/CHECK_TYPES = \[([^\]]*)\]/)[1].match(/"(\w*)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual(CHECK_TYPES, types.filter((x) => x && x !== 'off'));
});

/* ── where does it break, and the place on the canvas (2026-11-17) ───────── */

const WORDS = (() => {
  const src = readFileSync(new URL('../static/js/nodes-text.js', import.meta.url), 'utf8');
  return Function(`return {${src.match(/export const NODES_TEXT = \{([\s\S]*?)\n\};/)[1]}}`)();
})();

test('Where does it break? and Show in wiring: after Check now, before Alerts, Edit and Remove', () => {
  assert.deepEqual(acts('place', { ...ALL, check: true, ask: true, diagnose: true, topology: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'check', 'check-now', 'diagnose', 'topology', 'alerts', 'edit', 'remove']);
  assert.deepEqual(menuItems('place', { diagnose: true, topology: true }).slice(3), [
    { act: 'diagnose', key: 'nodes_menu_diagnose' },
    { act: 'topology', key: 'nodes_menu_topology' },
  ]);
  // a service has no chain of its own (it is its place's), but shows its place
  assert.deepEqual(acts('service', { alerts: true, diagnose: true, topology: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'collections', 'topology', 'alerts']);
  // a collection has neither
  assert.deepEqual(acts('collection', { edit: true, remove: true, diagnose: true, topology: true }),
    ['schedule', 'mode-on', 'unmanaged-on', 'rename', 'remove']);
  // left out, neither is listed
  assert.deepEqual(acts('place', ALL), ['schedule', 'mode-on', 'unmanaged-on', 'alerts', 'edit', 'remove']);
});

test('Where does it break? held: shown with the reason in words, as the route would refuse', () => {
  for (const why of ['off', 'unmanaged', 'planned']) {
    const item = menuItems('place', { diagnose: why }).find((i) => i.act === 'diagnose');
    assert.deepEqual(item, { act: 'diagnose', key: `nodes_menu_diagnose_${why}`, held: true }, why);
  }
  // a Kuma monitor is no refusal of the chain, and an odd reason is no reason
  for (const odd of ['kuma', 'toString', '', 'yes', 1, null, {}]) {
    assert.ok(!menuItems('place', { diagnose: odd }).some((i) => i.act === 'diagnose'), String(odd));
  }
});

test('a phone: Show in wiring after Open its card; never Where does it break?', () => {
  assert.deepEqual(acts('place', { ...RO, state: 'down', topology: true }), ['(nodes_state_down)', 'open', 'topology']);
  assert.deepEqual(menuItems('place', { ...RO, topology: true }).at(-1), { act: 'topology', key: 'nodes_menu_topology' });
  assert.deepEqual(acts('place', { ...RO, diagnose: true, check: true, ask: true }), ['(nodes_state_unknown)', 'open']);
  // a phone's service has no line, so no sheet
  assert.deepEqual(menuItems('service', { ...RO, topology: true }), []);
});

test('diagnoseAsk: off first, then unmanaged, then planned, as the route answers', () => {
  const data = { nodes: [{ id: 'a' }, { id: 'u', unmanaged: true }, { id: 'p', planned: true }, { id: 'k', check: 'tcp', monitors: ['K'] }] };
  assert.equal(diagnoseAsk(data, 'a'), true);
  assert.equal(diagnoseAsk(data, 'k'), true, 'a Kuma monitor: the chain is still asked');
  assert.equal(diagnoseAsk(data, 'u'), 'unmanaged');
  assert.equal(diagnoseAsk(data, 'a', { unmanaged: true }), 'unmanaged', 'through a collection');
  assert.equal(diagnoseAsk(data, 'p'), 'planned');
  assert.equal(diagnoseAsk(data, 'p', { unmanaged: true }), 'unmanaged');
  for (const id of ['a', 'u', 'p']) assert.equal(diagnoseAsk(data, id, { on: false }), 'off', id);
  assert.equal(diagnoseAsk(data, 'a', { on: undefined }), true, 'not known is not off');
  assert.equal(diagnoseAsk(data, 'a', { on: true }), true);
  for (const id of ['nowhere', '', null, 7]) assert.equal(diagnoseAsk(data, id), '', String(id));
  for (const odd of [null, {}, { nodes: 'x' }, { nodes: [null, 3, { id: 7 }] }]) assert.equal(diagnoseAsk(odd, 'a'), '');
  assert.equal(diagnoseAsk(data, 'a', null), true);
});

/** The route's answer: the chain from the gateway down to the store, a
    hidden hop between, broken at the core switch. */
const DX = {
  id: 'store', name: 'STORE', asked: true,
  steps: [
    { step: 'hop', thing: 'gw', name: 'GATEWAY', asks: '192.0.2.1 port 22', state: 'up', why: null, ms: 3, error: null },
    { step: 'hop', thing: 'core', name: 'CORE SWITCH', asks: '192.0.2.2 port 443', state: 'down', why: null, ms: 2000,
      error: 'no answer: the check could not be asked, or did not finish in time' },
    { step: 'hop', thing: null, name: null, asks: null, state: 'skipped', why: 'hidden', ms: null, error: null },
    { step: 'dns', thing: 'store', name: 'STORE', asks: 'the name store.example', state: 'skipped', why: 'stopped', ms: null, error: null },
    { step: 'place', thing: 'store', name: 'STORE', asks: 'https://store.example/', state: 'skipped', why: 'stopped', ms: null, error: null },
  ],
  broke_at: 1,
  path: { things: ['gw', 'core', null, 'store'], links: ['c1', null, null] },
};
const up = (step, extra = {}) => ({ step, thing: 'store', name: 'STORE', asks: 'x', state: 'up', why: null, ms: 1, error: null, ...extra });
const skip = (step, why, extra = {}) => ({ step, thing: 'store', name: 'STORE', asks: null, state: 'skipped', why, ms: null, error: null, ...extra });

test('diagnoseLines: one line per step, in order, the broken one marked, a hidden hop kept in its place', () => {
  const lines = diagnoseLines(DX);
  assert.equal(lines.length, 5);
  assert.deepEqual(lines.map((l) => [l.step, l.tone, l.broke]),
    [['hop', 'up', false], ['hop', 'down', true], ['hop', '', false], ['dns', '', false], ['place', '', false]]);
  assert.deepEqual(lines[0].parts, [
    { key: 'nodes_dx_thing', vars: { name: 'GATEWAY' } }, { key: 'nodes_dx_asks', vars: { asks: '192.0.2.1 port 22' } },
    { key: 'nodes_dx_up' }, { key: 'nodes_asked_ms', vars: { ms: 3 } },
  ]);
  assert.deepEqual(lines[1].parts.slice(2), [
    { key: 'nodes_dx_down' }, { key: 'nodes_asked_ms', vars: { ms: 2000 } },
    { key: 'nodes_asked_error', vars: { why: 'no answer: the check could not be asked, or did not finish in time' } },
  ]);
  // a place this viewer may not see: no name, nothing it asked, why in words
  assert.deepEqual(lines[2].parts, [{ key: 'nodes_dx_hidden' }, { key: 'nodes_dx_skipped', words: { why: 'nodes_dx_why_hidden' } }]);
  assert.deepEqual(lines[3].parts[0], { key: 'nodes_dx_dns', vars: { name: 'STORE' } });
  assert.deepEqual(lines[4].parts.at(-1), { key: 'nodes_dx_skipped', words: { why: 'nodes_dx_why_stopped' } });
});

test('diagnoseLines: every reason a step was not asked has its words; anything else reads as no reason', () => {
  for (const why of DIAGNOSE_WHYS) {
    const [line] = diagnoseLines({ steps: [skip('place', why)], broke_at: null });
    const key = line.parts.at(-1).words.why;
    assert.equal(key, `nodes_dx_why_${why.replace(/-/g, '_')}`, why);
    assert.ok(WORDS[key], key);
  }
  for (const odd of [null, 'later', 'toString', 3]) {
    assert.equal(diagnoseLines({ steps: [skip('place', odd)] })[0].parts.at(-1).words.why, 'nodes_dx_why_other', String(odd));
  }
  // a state it does not know reads as not asked
  assert.equal(diagnoseLines({ steps: [up('hop', { state: 'sideways', why: 'busy' })] })[0].tone, '');
});

test('diagnoseLines: the outside address, a thing with no name, odd numbers and errors', () => {
  const [outside] = diagnoseLines({ steps: [{ step: 'internet', thing: null, name: 'outside', asks: '198.51.100.7 port 443', state: 'up', ms: 12 }] });
  assert.deepEqual(outside.parts[0], { key: 'nodes_dx_internet' });
  assert.equal(outside.step, 'internet');
  // a thing with an id and no name is named by its id
  assert.deepEqual(diagnoseLines({ steps: [up('hop', { thing: 'sw', name: '' })] })[0].parts[0], { key: 'nodes_dx_thing', vars: { name: 'sw' } });
  // ms only when a whole number; an error only when down; nothing asked, no "asked"
  const parts = diagnoseLines({ steps: [up('hop', { ms: 1.5, error: 'x', asks: '' })] })[0].parts.map((p) => p.key);
  assert.deepEqual(parts, ['nodes_dx_thing', 'nodes_dx_up']);
  assert.deepEqual(diagnoseLines({ steps: [up('place', { state: 'down', ms: null, error: '' })] })[0].parts.map((p) => p.key),
    ['nodes_dx_thing', 'nodes_dx_asks', 'nodes_dx_down']);
  assert.equal(diagnoseLines({ steps: [up('nonsense')] })[0].step, '');
  for (const odd of [null, {}, { steps: 'x' }, 7]) assert.deepEqual(diagnoseLines(odd), []);
  assert.equal(diagnoseLines({ steps: [null] }).length, 1, 'an odd step still has its line');
});

test('diagnoseSummary: where it breaks, by the kind of step', () => {
  assert.deepEqual(diagnoseSummary(DX), { key: 'nodes_dx_breaks', vars: { name: 'CORE SWITCH' }, tone: 'down' });
  const at = (steps, broke) => diagnoseSummary({ steps, broke_at: broke });
  assert.deepEqual(at([up('hop'), skip('dns', null, { state: 'down' })], 1), { key: 'nodes_dx_breaks_dns', vars: { name: 'STORE' }, tone: 'down' });
  assert.deepEqual(at([up('hop'), up('place', { state: 'down' })], 1), { key: 'nodes_dx_breaks', vars: { name: 'STORE' }, tone: 'down' });
  assert.deepEqual(at([up('hop'), up('place'), up('internet', { state: 'down', thing: null, name: 'outside' })], 2),
    { key: 'nodes_dx_breaks_outside', tone: 'down' });
  assert.deepEqual(at([up('hop', { thing: null, name: null, state: 'down' })], 0), { key: 'nodes_dx_breaks_hidden', tone: 'down' });
});

test('diagnoseSummary: every step answered, some not asked, or nothing could be asked', () => {
  assert.deepEqual(diagnoseSummary({ steps: [up('hop'), up('dns'), up('place')], broke_at: null }), { key: 'nodes_dx_clear', tone: 'up' });
  // nothing down, but not every step was asked: never "every step answered"
  assert.deepEqual(diagnoseSummary({ steps: [skip('hop', 'stub'), up('place')], broke_at: null }),
    { key: 'nodes_dx_clear_some_one', vars: { n: 1 }, tone: 'up' });
  assert.deepEqual(diagnoseSummary({ steps: [skip('hop', 'stub'), skip('hop', 'hidden'), up('place')], broke_at: null }),
    { key: 'nodes_dx_clear_some', vars: { n: 2 }, tone: 'up' });
  assert.deepEqual(diagnoseSummary({ steps: [skip('hop', 'stub'), skip('place', 'kuma')], broke_at: null }), { key: 'nodes_dx_none', tone: '' });
  assert.deepEqual(diagnoseSummary({ steps: [], broke_at: null }), { key: 'nodes_dx_none', tone: '' });
  // broke_at that is no step's index is no break
  for (const odd of [5, -1, 1.5, '0', null]) {
    assert.equal(diagnoseSummary({ steps: [up('place')], broke_at: odd }).key, 'nodes_dx_clear', String(odd));
  }
  for (const odd of [null, 7, {}]) assert.deepEqual(diagnoseSummary(odd), { key: 'nodes_dx_none', tone: '' });
});

test('diagnoseLight: broke_at is an index into the steps, the light an index into the path', () => {
  // a hop: that thing's place on the path (a hidden hop before it is no step of the path's count)
  assert.deepEqual(diagnoseLight(DX), { things: ['gw', 'core', null, 'store'], links: ['c1', null, null], failedAt: 1 });
  const path = { things: ['gw', 'core', 'store'], links: ['c1', 'c2'] };
  const light = (steps, broke) => diagnoseLight({ id: 'store', steps, broke_at: broke, path });
  // its DNS name: the place's own, the last
  assert.equal(light([up('hop', { thing: 'gw' }), up('hop', { thing: 'core' }), up('dns', { state: 'down' })], 2).failedAt, 2);
  // the place itself
  assert.equal(light([up('hop', { thing: 'gw' }), up('hop', { thing: 'core' }), up('place', { state: 'down' })], 2).failedAt, 2);
  // the outside address: no thing on the path, the whole path lit as good
  assert.deepEqual(light([up('place'), up('internet', { thing: null, state: 'down' })], 1), { ...path, failedAt: null });
  // nothing broke: the whole path
  assert.deepEqual(light([up('place')], null), { ...path, failedAt: null });
  // a hop with an id the path does not hold, or with none (a place the viewer
  // may not see), is found by its turn among the hops: the light stops there
  assert.equal(light([up('hop', { thing: 'elsewhere', state: 'down' })], 0).failedAt, 0);
  const cut = { things: ['gw', null, 'store'], links: [null, null] };
  assert.equal(diagnoseLight({ id: 'store', broke_at: 1, path: cut,
    steps: [up('hop', { thing: 'gw' }), up('hop', { thing: null, state: 'down' }), up('place', { state: 'skipped' })] }).failedAt, 1);
  // more hops than the path holds: nothing to point at, lit whole
  assert.equal(diagnoseLight({ id: 'store', broke_at: 3, path: { things: ['gw', 'store'], links: ['c1'] },
    steps: [up('hop'), up('hop'), up('hop'), up('hop', { thing: null, state: 'down' })] }).failedAt, null);
  // the place: the last
  assert.equal(light([up('place', { thing: 'elsewhere', state: 'down' })], 0).failedAt, 2);
});

test('diagnoseLight: a place nothing reaches is lit alone; odd entries are not ids', () => {
  assert.deepEqual(diagnoseLight({ id: 'lone', steps: [up('place', { thing: 'lone', state: 'down' })], broke_at: 0, path: { things: [], links: [] } }),
    { things: ['lone'], links: [], failedAt: 0 });
  assert.deepEqual(diagnoseLight({ id: 'lone', steps: [], broke_at: null }), { things: ['lone'], links: [], failedAt: null });
  assert.deepEqual(diagnoseLight({ id: 'x', path: { things: ['a', 3, '', null, 'x'], links: [{}, 'l', ''] } }),
    { things: ['a', null, null, null, 'x'], links: [null, 'l', null], failedAt: null });
  for (const odd of [null, 7, {}]) assert.deepEqual(diagnoseLight(odd), { things: [], links: [], failedAt: null });
});

test('diagnoseRefusal: each refusal in words', () => {
  assert.deepEqual(diagnoseRefusal(403, { error: 'admins only' }), { key: 'nodes_dx_403' });
  assert.deepEqual(diagnoseRefusal(404, { error: 'no such place' }), { key: 'nodes_dx_404' });
  for (const why of ['off', 'unmanaged', 'planned']) assert.deepEqual(diagnoseRefusal(409, { why }), { key: `nodes_dx_${why}` });
  // a Kuma refusal is Check now's, not this route's
  assert.deepEqual(diagnoseRefusal(409, { why: 'kuma', error: 'odd' }), { key: 'nodes_dx_failed', vars: { why: 'odd' } });
  assert.deepEqual(diagnoseRefusal(429, { why: 'soon', retry_after: 12 }), { key: 'nodes_dx_soon', vars: { n: 12 } });
  assert.deepEqual(diagnoseRefusal(429, { why: 'spent', retry_after: 60 }), { key: 'nodes_dx_spent', vars: { n: 60 } });
  assert.deepEqual(diagnoseRefusal(429, { why: 'spent', retry_after: 0.4 }), { key: 'nodes_dx_spent_one', vars: { n: 1 } });
  assert.deepEqual(diagnoseRefusal(429, {}), { key: 'nodes_dx_soon_one', vars: { n: 1 } });
  assert.deepEqual(diagnoseRefusal(400, { error: 'expected an id' }), { key: 'nodes_dx_failed', vars: { why: 'expected an id' } });
  assert.deepEqual(diagnoseRefusal(500, null), { key: 'nodes_dx_failed', vars: { why: '500' } });
  assert.deepEqual(diagnoseRefusal(0, null), { key: 'nodes_dx_failed', vars: { why: 'no answer' } });
  // Check now's refusals are as they were
  assert.deepEqual(refusalLine(409, { why: 'planned' }), { key: 'nodes_asked_failed', vars: { why: '409' } });
});

test('wordsOf: the words a line names are filled in first, then the line', () => {
  const tt = (key, vars = {}) => ({ a: 'Not asked: {why}', b: 'hidden from {who}', c: '{n} ms' }[key] || key)
    .replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  assert.equal(wordsOf({ key: 'a', vars: { who: 'you' }, words: { why: 'b' } }, tt), 'Not asked: hidden from you');
  assert.equal(wordsOf({ key: 'c', vars: { n: 4 } }, tt), '4 ms');
  assert.equal(wordsOf({ key: 'c' }, tt), '{n} ms', 'a var not given stays as it was');
  assert.equal(wordsOf({ key: 'a', words: 'b' }, tt), 'Not asked: {why}', 'words that are not an object are none');
});

test("where it breaks: every key it can give has its plain words, in plain English", () => {
  const keys = new Set([...diagnoseKeys(), ...menuKeys(), 'nodes_dx_label', 'nodes_dx_show', 'nodes_dx_close']);
  for (const k of ['nodes_menu_diagnose', 'nodes_menu_diagnose_off', 'nodes_menu_diagnose_unmanaged',
    'nodes_menu_diagnose_planned', 'nodes_menu_topology']) assert.ok(keys.has(k), k);
  for (const key of keys) assert.ok(typeof WORDS[key] === 'string' && WORDS[key], key);
  // every key the functions hand back is in the list
  const given = [
    ...diagnoseLines(DX).flatMap((l) => l.parts.flatMap((p) => [p.key, ...Object.values(p.words || {})])),
    ...diagnoseLines({ steps: [up('internet', { state: 'down', error: 'x' })] }).flatMap((l) => l.parts.map((p) => p.key)),
    diagnoseSummary(DX).key,
    ...[403, 404, 500].map((s) => diagnoseRefusal(s, {}).key),
    ...['off', 'unmanaged', 'planned'].map((why) => diagnoseRefusal(409, { why }).key),
    ...['soon', 'spent'].flatMap((why) => [1, 5].map((n) => diagnoseRefusal(429, { why, retry_after: n }).key)),
  ];
  for (const key of given) assert.ok(diagnoseKeys().includes(key), key);
  for (const key of keys) if (/^nodes_(dx_|menu_diagnose|menu_topology)/.test(key)) assert.doesNotMatch(WORDS[key], /—/, key);
  assert.match(WORDS.nodes_dx_skipped, /\{why\}/);
  for (const k of ['nodes_dx_breaks', 'nodes_dx_breaks_dns', 'nodes_dx_thing', 'nodes_dx_dns', 'nodes_dx_label']) assert.match(WORDS[k], /\{name\}/, k);
  for (const k of ['nodes_dx_soon', 'nodes_dx_spent', 'nodes_dx_clear_some']) assert.match(WORDS[k], /\{n\}/, k);
  assert.equal(WORDS.nodes_dx_breaks.replace('{name}', 'CORE SWITCH'), 'Breaks at CORE SWITCH');
  assert.equal(WORDS.nodes_dx_clear, 'Every step answered');
  assert.equal(WORDS.nodes_dx_none, 'Nothing could be asked');
  assert.deepEqual(DIAGNOSE_STEPS, ['hop', 'dns', 'place', 'internet']);
});

test("the server's reasons are the ones the lines know (diagnose.py WHY, STEPS)", () => {
  const src = readFileSync(new URL('../diagnose.py', import.meta.url), 'utf8');
  const why = src.match(/^WHY = \{([\s\S]*?)^\}/m)[1];
  assert.deepEqual([...why.matchAll(/^\s+"([\w-]+)":/gm)].map((m) => m[1]).sort(), [...DIAGNOSE_WHYS].sort());
  const steps = src.match(/^STEPS = \(([^)]*)\)/m)[1].match(/"(\w+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual(steps, DIAGNOSE_STEPS);
});

test('the held Check now says what is true when a Kuma monitor is named but Kuma is not connected', () => {
  // the line above it may say "Not watched": the held words must not say Kuma watches it
  assert.equal(WORDS.nodes_menu_check_now_kuma, 'Check now: a Kuma monitor is named for this, so Atlas does not ask it');
  assert.doesNotMatch(WORDS.nodes_menu_check_now_kuma, /Kuma watches/);
});

console.log(`\n${passed} passed`);
