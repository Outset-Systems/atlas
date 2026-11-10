/* What the Desk says about a place's stamp, in plain node.

   Run:  node tests/test_standing.mjs        (from Web/) */

import assert from 'node:assert/strict';
import { sentence, standing, waiting } from '../static/js/editor/standing.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const OLD = { id: 'old' };
const IMPORTED = { id: 'ap', provenance: { charted_by: 'ada', charted_at: '2026-11-09T21:14:03Z', source: 'unifi', reviewed: false } };
const CHECKED = { id: 'gw', provenance: { charted_by: 'ada', charted_at: '2026-11-09T21:14:03Z', source: 'hand',
  reviewed: true, reviewed_by: 'ada', reviewed_at: '2026-11-10T08:00:00Z' } };
const CHECKED_OLD = { id: 'nas', provenance: { reviewed: true, reviewed_by: 'ada', reviewed_at: '2026-11-10T08:00:00Z' } };

test('three standings, and a stamp of the wrong shape is unknown', () => {
  assert.equal(standing(OLD), 'unknown');
  assert.equal(standing(IMPORTED), 'unchecked');
  assert.equal(standing(CHECKED), 'checked');
  assert.equal(standing({ provenance: 'yes' }), 'unknown');
  assert.equal(standing({ provenance: { reviewed: 'true' } }), 'unknown');
  assert.equal(standing(null), 'unknown');
});

test('an import says where it came from and that nobody has looked', () => {
  assert.equal(sentence(IMPORTED), 'Charted by ada on 2026-11-09, from unifi. Not yet checked by a person.');
});

test('a hand-charted, checked place names no source', () => {
  assert.equal(sentence(CHECKED), 'Charted by ada on 2026-11-09. Checked by ada on 2026-11-10.');
});

test('an old place invents no date, checked or not', () => {
  assert.equal(sentence(OLD), 'Charted before the map kept a record of who and when. Not yet checked by a person.');
  assert.equal(sentence(CHECKED_OLD), 'Charted before the map kept a record of who and when. Checked by ada on 2026-11-10.');
});

test('the waiting line counts both reasons and is silent when all are checked', () => {
  assert.equal(waiting([CHECKED, CHECKED_OLD]), '');
  assert.equal(waiting([CHECKED, IMPORTED, OLD, OLD]),
    '3 of 4 places have not been checked by a person. 1 came from an import, 2 were charted before the map kept this record.');
  assert.equal(waiting([OLD], 'holds'),
    'The one entry here has not been checked by a person. 1 was charted before the map kept this record.');
  assert.equal(waiting([OLD, IMPORTED], 'holds'),
    'None of the 2 holds here has been checked by a person. 1 came from an import, 1 was charted before the map kept this record.');
  assert.equal(waiting([CHECKED, IMPORTED]),
    '1 of 2 places has not been checked by a person. 1 came from an import.');
});

console.log(`\n${passed} passed`);
