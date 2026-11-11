/* Where a network's name stands, from where its places are. `node tests/test_label_model.mjs` */

import assert from 'node:assert/strict';
import { placeLabels, toSegment } from '../static/js/label-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}
const box = { hw: 6, hh: 2 };

test('a name stands above the middle of its places when nothing is in the way', () => {
  const at = placeLabels([{ id: 'srv', ids: ['a', 'b'], ...box }],
    { a: { x: 46, y: 50 }, b: { x: 54, y: 54 } });
  assert.equal(at.srv.x, 50);
  assert.ok(at.srv.y < 50 - 2, 'above the topmost place, clear of its marker');
});

test('a network with no place drawn here is not named here', () => {
  const at = placeLabels([{ id: 'srv', ids: ['a'], ...box }, { id: 'iot', ids: ['gone'], ...box }],
    { a: { x: 50, y: 50 } });
  assert.deepEqual(Object.keys(at), ['srv']);
});

test('it moves to another side rather than sit on another place', () => {
  // a stranger stands exactly where "above" would put the name
  const places = { a: { x: 50, y: 50 }, stranger: { x: 50, y: 44.5 } };
  const at = placeLabels([{ id: 'srv', ids: ['a'], ...box }], places);
  assert.ok(at.srv.y > 50, 'below instead');
});

test('two names do not land on each other', () => {
  const places = { a: { x: 50, y: 50 }, b: { x: 52, y: 50.5 } };
  const at = placeLabels([{ id: 'one', ids: ['a'], ...box }, { id: 'two', ids: ['b'], ...box }], places);
  const apart = Math.abs(at.one.x - at.two.x) >= 12 || Math.abs(at.one.y - at.two.y) >= 4;
  assert.ok(apart, JSON.stringify(at));
});

test('a road through the best spot sends the name to the next one', () => {
  const places = { a: { x: 50, y: 50 }, up: { x: 50, y: 20 } };
  const free = placeLabels([{ id: 'srv', ids: ['a'], ...box }], places);
  const roaded = placeLabels([{ id: 'srv', ids: ['a'], ...box }], places, [['a', 'up']]);
  assert.ok(free.srv.y < 50, 'above, with no road');
  assert.ok(roaded.srv.y > 50, 'below, once a road runs up through "above"');
});

test('a name stays on the picture, and the biggest group is set down first', () => {
  const at = placeLabels([{ id: 'edge', ids: ['a'], ...box }], { a: { x: 3, y: 2 } });
  assert.ok(at.edge.x >= 7 && at.edge.y >= 3, JSON.stringify(at));
  const places = { a: { x: 50, y: 50 }, b: { x: 51, y: 50 }, c: { x: 52, y: 50 }, d: { x: 51, y: 49 } };
  const both = placeLabels([{ id: 'small', ids: ['d'], ...box }, { id: 'big', ids: ['a', 'b', 'c'], ...box }], places);
  assert.equal(both.big.x, 51);                  // the big one got the clean spot over its own middle
});

test('a scattered network is named at its heart, not over the whole spread', () => {
  const places = { a: { x: 70, y: 70 }, b: { x: 74, y: 74 }, c: { x: 66, y: 78 }, far: { x: 68, y: 10 } };
  const at = placeLabels([{ id: 'dmz', ids: ['a', 'b', 'c', 'far'], ...box }], places);
  assert.ok(at.dmz.y > 55, `beside the three that stand together, not up by the far one: ${JSON.stringify(at)}`);
});

test('distance to a segment', () => {
  assert.equal(toSegment({ x: 5, y: 5 }, { x: 0, y: 0 }, { x: 10, y: 0 }), 5);
  assert.equal(toSegment({ x: -3, y: 4 }, { x: 0, y: 0 }, { x: 10, y: 0 }), 5);
  assert.equal(toSegment({ x: 1, y: 1 }, { x: 1, y: 1 }, { x: 1, y: 1 }), 0);
});

console.log(`\nlabel-model: ${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');
