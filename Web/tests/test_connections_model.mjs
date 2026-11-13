/* CONNECTIONS' rules, in plain node.

   connections-model.js holds what Settings shows about a token and what the
   review lets an admin tick: the setup lines for each harness, the sentence
   for each kind of token, which rows can be ticked, what a tick brings with
   it, and what ignoring a host does to what stands on it.

   Run:  node tests/test_connections_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  follow, groupsOf, ignoreLocally, kindNote, setups, standsOn, tickable,
} from '../static/js/connections-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const MCP = 'https://atlas.example/api/v2/mcp';
const READ = 'https://atlas.example/api/v2/signals';

test('a full token gets the local and REST lines, and only those', () => {
  const all = setups('tok_abc', 'full', MCP, READ);
  assert.deepEqual(Object.keys(all), ['local', 'rest']);
  assert.equal(all.local.text, `URL:    ${MCP}\nHeader: Authorization: Bearer tok_abc`);
  assert.equal(all.rest.text, `curl -H "Authorization: Bearer tok_abc" ${READ}`);
  assert.equal(all.local.name, 'Local model');
  assert.equal(all.rest.lang, 'shell');
});

test('a cloud token gets the four cloud tools, each naming its vendor', () => {
  const all = setups('tok_abc', 'cloud', MCP, READ);
  assert.deepEqual(Object.keys(all), ['claude', 'codex', 'gemini', 'other']);
  assert.equal(all.claude.text,
    `export ATLAS_TOKEN="tok_abc"\nclaude mcp add --transport http --scope user atlas ${MCP} --header "Authorization: Bearer $ATLAS_TOKEN"`);
  assert.equal(all.codex.text, `[mcp_servers.atlas]\nurl = "${MCP}"\nbearer_token_env_var = "ATLAS_TOKEN"`);
  assert.ok(!all.codex.text.includes('tok_abc'), 'the Codex file names the variable, never the token');
  assert.deepEqual(JSON.parse(all.gemini.text),
    { mcpServers: { atlas: { httpUrl: MCP, headers: { Authorization: 'Bearer tok_abc' } } } });
  assert.equal(all.gemini.text.split('\n')[1], '  "mcpServers": {', 'two-space JSON');
  assert.ok(all.claude.note.startsWith('Cloud model: what this token reads is sent to Anthropic. '));
  assert.ok(all.codex.note.startsWith('Cloud model: what this token reads is sent to OpenAI. '));
  assert.ok(all.gemini.note.startsWith('Cloud model: what this token reads is sent to Google. '));
  assert.equal(all.other.text, `URL:    ${MCP}\nHeader: Authorization: Bearer tok_abc`);
});

test('with no token the lines carry a placeholder', () => {
  assert.ok(setups('', 'full', MCP, READ).rest.text.includes('Bearer PASTE_YOUR_TOKEN'));
  assert.ok(setups('', 'cloud', MCP, READ).claude.text.includes('ATLAS_TOKEN="PASTE_YOUR_TOKEN"'));
  // anything that is not `cloud` is the full set
  assert.deepEqual(Object.keys(setups('', undefined, MCP, READ)), ['local', 'rest']);
});

test('the kind note: full says everything, cloud carries the map\'s own numbers', () => {
  assert.equal(kindNote({}, 'full'),
    'Reads everything on the map a viewer with no groups could, addresses included, on every '
    + 'route. For a model or a script that runs on your own network.');
  const tail = ' No addresses, MAC addresses, URLs, hardware or notes, and through the MCP address only.'
    + ' The names of those places, what they are for and how they connect still go to the tool\u2019s vendor.';
  const head = 'Reads only places a person has checked and nothing has changed since.';
  assert.equal(kindNote({}, 'cloud'), head + tail);
  assert.equal(kindNote({ cloud_view: { readable: 3, withheld: 9 } }, 'cloud'),
    `${head} That is 3 of 12 places on this map.${tail}`);
  assert.equal(kindNote({ cloud_view: { readable: 0, withheld: 5 } }, 'cloud'),
    `${head} That is 0 of 5 places on this map. Check places in the Desk first, or the tool reads an empty map.${tail}`);
  assert.equal(kindNote({ cloud_view: { readable: 0, withheld: 0 } }, 'cloud'), head + tail);
});

const ROWS = () => [
  { key: 'h1', type: 'node', status: 'new', group: 'Machines', name: 'alpha' },
  { key: 'h2', type: 'node', status: 'charted', group: 'Machines', name: 'beta' },
  { key: 's1', type: 'service', status: 'new', group: 'Services', name: 'web', parent: 'h1' },
  { key: 'p1', type: 'port', status: 'clash', group: 'Ports', name: 'eth0', parent: 'h1' },
  { key: 'r1', type: 'route', status: 'new', group: 'Links', name: 'alpha to beta', parent: 'h2', peer: 'h1' },
  { key: 'g1', type: 'guest', status: 'new', group: 'Machines', name: 'guest', parent: 'h1' },
  { key: 'c1', type: 'service', status: 'charted', group: 'Services', name: 'old', parent: 'h1' },
];

test('new and clashing rows can be ticked, unless blocked', () => {
  assert.ok(tickable({ status: 'new' }));
  assert.ok(tickable({ status: 'clash' }));
  assert.ok(!tickable({ status: 'new', blocked: true }));
  assert.ok(!tickable({ status: 'charted' }));
  assert.ok(!tickable({ status: 'ignored' }));
});

test('rows group under their heading, in first-seen order', () => {
  const groups = groupsOf(ROWS());
  assert.deepEqual([...groups.keys()], ['Machines', 'Services', 'Ports', 'Links']);
  assert.deepEqual(groups.get('Machines').map((r) => r.key), ['h1', 'h2', 'g1']);
  assert.equal(groupsOf([]).size, 0);
});

test('a service, a port and a link stand on a host; a guest does not', () => {
  const rows = ROWS();
  const on = (key) => rows.filter((r) => standsOn(r, key)).map((r) => r.key);
  assert.deepEqual(on('h1'), ['s1', 'p1', 'r1', 'c1']);
  assert.deepEqual(on('h2'), ['r1'], 'a link stands on both of its ends');
  assert.deepEqual(on('s1'), []);
});

test('ticking what stands on a host ticks the host; ticking a host ticks nothing', () => {
  const rows = ROWS();
  assert.deepEqual(follow(rows, 's1', true), { tick: ['h1'], untick: [] });
  assert.deepEqual(follow(rows, 'r1', true), { tick: ['h2', 'h1'], untick: [] }, 'parent first, then peer');
  assert.deepEqual(follow(rows, 'h1', true), { tick: [], untick: [] });
  assert.deepEqual(follow(rows, 'g1', true), { tick: [], untick: [] });
});

test('unticking a host unticks what stood on it, and nothing else', () => {
  const rows = ROWS();
  assert.deepEqual(follow(rows, 'h1', false), { tick: [], untick: ['s1', 'p1', 'r1', 'c1'] });
  assert.deepEqual(follow(rows, 's1', false), { tick: [], untick: [] });
  // unticking never looks the row up, so a key that is not listed is harmless
  assert.deepEqual(follow(rows, 'nobody', false), { tick: [], untick: [] });
});

test('ignoring a host blocks what stands on it and says why; bringing it back undoes both', () => {
  const view = { rows: ROWS() };
  const by = (key) => view.rows.find((r) => r.key === key);
  ignoreLocally(view, 'h1', true);
  assert.equal(by('h1').status, 'ignored');
  assert.equal(by('h1').was, 'new');
  for (const key of ['s1', 'p1', 'r1']) {
    assert.equal(by(key).blocked, true, key);
    assert.equal(by(key).note, 'alpha is ignored.');
    assert.ok(!tickable(by(key)));
  }
  assert.equal(by('c1').blocked, undefined, 'a charted row is left alone');
  assert.equal(by('g1').blocked, undefined, 'a guest can land without its host');

  ignoreLocally(view, 'h1', false);
  assert.equal(by('h1').status, 'new');
  for (const key of ['s1', 'p1', 'r1']) {
    assert.equal(by(key).blocked, false, key);
    assert.equal(by(key).note, '');
  }
  assert.ok(tickable(by('s1')));
});

test('a row that arrived ignored comes back as new', () => {
  const view = { rows: [{ key: 'x', type: 'node', status: 'ignored', name: 'x' }] };
  ignoreLocally(view, 'x', false);
  assert.equal(view.rows[0].status, 'new');
});

console.log(`\n${passed} passed`);
