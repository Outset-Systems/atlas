// The browser's half of the roster's shared cases (2026-11-15, stage 5): the
// server's port (roster_query.py, tests/test_roster_query.py) is held to the
// same answers, so a change to either rule shows up as a broken case.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { filterRows, sortRows } from '../static/js/roster-model.js';

const CASES = JSON.parse(readFileSync(new URL('./roster_query_cases.json', import.meta.url), 'utf8'));
const NOW = Date.parse(CASES.now);

test('the browser model gives every shared case its answer', () => {
  for (const c of CASES.cases) {
    const got = sortRows(filterRows(CASES.rows, c.filter, NOW), c.sort, c.dir, CASES.collections).map((r) => r.id);
    assert.deepEqual(got, c.expect, JSON.stringify({ filter: c.filter, sort: c.sort, dir: c.dir }));
  }
});
