/* The save contract of a form, in plain node.

   editor/form-model.js decides what a form's values become in the body that is
   sent: blank is absent, cleared is `null`, an unticked checkbox is `null` only
   if it was ticked, and a required blank is an error. The server removes a key
   on `null` and merges around an absent one, so each of these is a promise.

   Run:  node tests/test_form_model.mjs        (from Web/) */

import assert from 'node:assert/strict';
import {
  inputToIso, isoToInput, numberValue, readEntry, readSub, scalarValue,
} from '../static/js/editor/form-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

const FIELDS = [
  { name: 'id', label: 'Id', type: 'slug', required: true },
  { name: 'name', label: 'Name', type: 'text', required: true },
  { name: 'hue', label: 'Colour', type: 'color' },
  { name: 'off_map', label: 'Off the map', type: 'bool' },
  { name: 'tags', label: 'Tags', type: 'strings' },
  { name: 'vlan', label: 'VLAN', type: 'scalar' },
];

test('blank that was blank is absent; blank that had a value is null', () => {
  const out = readEntry(FIELDS, { id: 'a', name: 'A', hue: '#C49A52' },
    { id: 'a', name: 'A', hue: '', off_map: false, tags: [], vlan: '' });
  assert.deepEqual(out, { id: 'a', name: 'A', hue: null });
  assert.ok(!('tags' in out) && !('vlan' in out) && !('off_map' in out));
});

test('a cleared list and a missing widget value are blank too', () => {
  const out = readEntry(FIELDS, { id: 'a', name: 'A', tags: ['x'], vlan: 4 },
    { id: 'a', name: 'A', tags: [] });
  assert.deepEqual(out, { id: 'a', name: 'A', tags: null, vlan: null });
});

test('a key present but empty before still counts as had', () => {
  const out = readEntry(FIELDS, { id: 'a', name: 'A', hue: '' }, { id: 'a', name: 'A', hue: '' });
  assert.deepEqual(out, { id: 'a', name: 'A', hue: null });
});

test('a checkbox is true or nothing; unticking a ticked one is null', () => {
  const base = { id: 'a', name: 'A' };
  assert.deepEqual(readEntry(FIELDS, base, { ...base, off_map: true }), { ...base, off_map: true });
  assert.deepEqual(readEntry(FIELDS, base, { ...base, off_map: false }), base);
  assert.deepEqual(readEntry(FIELDS, { ...base, off_map: false }, { ...base, off_map: false }), base);
  assert.deepEqual(readEntry(FIELDS, { ...base, off_map: true }, { ...base, off_map: false }),
    { ...base, off_map: null });
  // only `true` ticks it: a truthy string does not
  assert.deepEqual(readEntry(FIELDS, base, { ...base, off_map: 'yes' }), base);
});

test('zero and false-looking values are values, not blanks', () => {
  const out = readEntry(FIELDS, {}, { id: 'a', name: 'A', vlan: 0, hue: '0' });
  assert.deepEqual(out, { id: 'a', name: 'A', hue: '0', vlan: 0 });
});

test('a required blank is an error naming every one, by label', () => {
  assert.throws(() => readEntry(FIELDS, {}, { id: 'a', name: '' }), { message: 'Name is required' });
  assert.throws(() => readEntry(FIELDS, {}, { id: '', name: '' }), { message: 'Id, Name are required' });
  // a required field is never written as null, even when it had a value
  assert.throws(() => readEntry(FIELDS, { id: 'a', name: 'A' }, { id: 'a', name: '' }),
    { message: 'Name is required' });
});

test('the body keeps the order the form shows its fields in', () => {
  const out = readEntry(FIELDS, {}, { vlan: 4, tags: ['x'], name: 'A', id: 'a' });
  assert.deepEqual(Object.keys(out), ['id', 'name', 'tags', 'vlan']);
});

test('only the fields shown are read: a trimmed form never mentions the rest', () => {
  const out = readEntry(FIELDS.slice(0, 2), { id: 'a', name: 'A', hue: '#C49A52' },
    { id: 'a', name: 'B', hue: '' });
  assert.deepEqual(out, { id: 'a', name: 'B' });
});

test('a sub-object leaves blanks out, has no nulls and requires nothing', () => {
  const subs = [
    { name: 'label', label: 'Label', type: 'text', required: true },
    { name: 'url', label: 'URL', type: 'url' },
    { name: 'primary', label: 'Primary', type: 'bool' },
    { name: 'path', label: 'Path', type: 'strings' },
    { name: 'port', label: 'Port', type: 'int' },
  ];
  assert.deepEqual(readSub(subs, { label: '', url: '', primary: false, path: [], port: '' }), {});
  assert.deepEqual(readSub(subs, { label: 'Web', url: undefined, primary: true, path: ['a'], port: 0 }),
    { label: 'Web', primary: true, path: ['a'], port: 0 });
  // false is only dropped for a checkbox
  assert.deepEqual(readSub([{ name: 'x', type: 'json' }], { x: false }), { x: false });
});

test('a number box: blank, a number, or the text as typed', () => {
  assert.equal(numberValue(''), '');
  assert.equal(numberValue('   '), '');
  assert.equal(numberValue('42'), 42);
  assert.equal(numberValue('-1.5'), -1.5);
  assert.equal(numberValue('1e3'), 1000);
  assert.equal(numberValue('4x'), '4x');
});

test('a scalar: a whole number goes back as a number, anything else as text', () => {
  assert.equal(scalarValue(' 4 '), 4);
  assert.equal(scalarValue('-12'), -12);
  assert.equal(scalarValue('4.5'), '4.5');
  assert.equal(scalarValue('—'), '—');
  assert.equal(scalarValue('  '), '');
  assert.equal(scalarValue('007'), 7);
});

test('a timestamp goes to the box and back in UTC', () => {
  assert.equal(isoToInput('2026-09-12T07:30:00Z'), '2026-09-12T07:30');
  assert.equal(isoToInput('2026-09-12T07:30:00+02:00'), '2026-09-12T05:30');
  assert.equal(isoToInput('not a date'), '');
  assert.equal(inputToIso('2026-09-12T07:30'), '2026-09-12T07:30:00Z');
  assert.equal(inputToIso(''), '');
});

console.log(`\n${passed} passed`);
