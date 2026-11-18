/* A visit to the demo starts clean (2026-11-17): visit-model.js, and the two
   facts about the page that make it true (visit.js runs first, and only on
   the demo). Run: node --test Web/tests/test_visit_model.mjs */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

import { beginVisit, OURS, VISIT_KEY } from '../static/js/visit-model.js';

const here = (path) => new URL(path, import.meta.url);

/** A Storage, as a browser gives one. */
function store(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    get length() { return map.size; },
    key: (i) => [...map.keys()][i] ?? null,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    keys: () => [...map.keys()],
  };
}

const KEPT = {
  'atlas.view': 'topology', 'atlas.scheme': 'light', 'atlas-pos-overrides': '{"gateway":[1,2]}',
  'atlas.nodes.saved': '[]', 'atlas.fold.accounts': '{}', 'atlas-pins': '["nas"]', 'atlas.topology': '{"mode":"infra"}',
};

test('the first page of a visit forgets what earlier visits left, and nothing else', () => {
  const local = store({ ...KEPT, 'other-app': 'theirs', atlasish: 'not ours', 'my.atlas.view': 'no' });
  const session = store();
  const gone = beginVisit(local, session);
  assert.deepEqual(gone.sort(), Object.keys(KEPT).sort());
  assert.deepEqual(local.keys().sort(), ['atlasish', 'my.atlas.view', 'other-app']);
  assert.equal(session.getItem(VISIT_KEY), '1');
});

test('a reload, or a link inside the demo, is the same visit and keeps what was chosen in it', () => {
  const local = store(KEPT);
  const session = store();
  beginVisit(local, session);
  local.setItem('atlas.view', 'nodes');           // chosen during this visit
  local.setItem('atlas.scheme', 'dark');
  assert.deepEqual(beginVisit(local, session), []);
  assert.equal(local.getItem('atlas.view'), 'nodes');
  assert.equal(local.getItem('atlas.scheme'), 'dark');
});

test('a new tab is a new visit', () => {
  const local = store();
  beginVisit(local, store());
  local.setItem('atlas.view', 'nodes');
  assert.deepEqual(beginVisit(local, store()), ['atlas.view']);
  assert.equal(local.getItem('atlas.view'), null);
});

test('the session mark is the session\'s own and is never what gets forgotten', () => {
  const session = store({ [VISIT_KEY]: '1', 'atlas-region-hinted': '1' });
  const local = store(KEPT);
  assert.deepEqual(beginVisit(local, session), []);
  assert.equal(local.keys().length, Object.keys(KEPT).length);
  assert.equal(session.getItem('atlas-region-hinted'), '1');
});

test('storage that is missing or throws never stops the page', () => {
  const thrower = { get length() { throw new Error('denied'); }, key() { throw new Error('denied'); },
    getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } };
  assert.deepEqual(beginVisit(null, null), []);
  assert.deepEqual(beginVisit(thrower, thrower), []);
  // a session that cannot hold the mark: every page forgets, the safe way round
  const local = store(KEPT);
  assert.equal(beginVisit(local, thrower).length, Object.keys(KEPT).length);
  local.setItem('atlas.view', 'nodes');
  assert.deepEqual(beginVisit(local, thrower), ['atlas.view']);
});

test('every key the page stores is one a visit forgets', () => {
  // each storage key in the page's own scripts is a string that begins
  // `atlas-` or `atlas.`: a new one that does not would outlive a visit
  const dir = here('../static/js/');
  const files = readdirSync(dir).filter((f) => f.endsWith('.js'));
  const named = new Set();
  for (const f of files) {
    const text = readFileSync(new URL(f, dir), 'utf8');
    for (const m of text.matchAll(/_KEY\s*=\s*['"`]([^'"`]+)['"`]/g)) {
      if (/Storage|storage|store\b/.test(text)) named.add(`${f}: ${m[1]}`);
    }
    for (const m of text.matchAll(/(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)\(\s*['"`]([^'"`]+)['"`]/g)) {
      named.add(`${f}: ${m[1]}`);
    }
  }
  assert.ok(named.size >= 15, `found only ${named.size} keys: the scan has gone blind`);
  const strays = [...named].filter((n) => {
    const key = n.split(': ')[1];
    return !OURS.test(key) && key !== 'region';       // region-model's HASH_KEY is the address's, not storage
  });
  assert.deepEqual(strays, []);
});

test('the page begins a visit before anything else, and only on the demo', () => {
  const atlas = readFileSync(here('../static/js/atlas.js'), 'utf8');
  const first = atlas.match(/^import\s[^\n]*$/m)[0];
  assert.match(first, /^import '\.\/visit\.js';/, 'visit.js is the first import of the page');
  const visit = readFileSync(here('../static/js/visit.js'), 'utf8');
  assert.match(visit, /dataset\.demo === '1'/);
  assert.deepEqual([...visit.matchAll(/^import .* from '([^']+)';$/gm)].map((m) => m[1]), ['./visit-model.js']);
  const model = readFileSync(here('../static/js/visit-model.js'), 'utf8');
  assert.ok(!/^import /m.test(model), 'the model imports nothing');
});
