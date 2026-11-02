import test from 'node:test';
import assert from 'node:assert/strict';
import { STANDARD, cleanWords, makeSay, readMode, writeMode } from '../static/js/words-model.js';

const say = makeSay(STANDARD);

test('standard words replace lore in the case they were found', () => {
  assert.equal(say('reading the annals…'), 'reading the history…');
  assert.equal(say('THE DAILY RITES'), 'THE DAILY JOBS');
  assert.equal(say('Realm'), 'Zone');
  assert.equal(say('3 rites fall on this day'), '3 jobs fall on this day');
});

test('a phrase wins over the words inside it', () => {
  assert.equal(say('Enter the realm'), 'Sign in');
  assert.equal(say('the deep would not answer'), 'the registry would not answer');
  assert.equal(say('vlan 33 · the realm above the realm'), 'vlan 33 · the zone above the map');
});

test('only whole words change', () => {
  assert.equal(say('sealed tributary forgery'), 'sealed tributary forgery');
});

test('no words means the text comes back untouched', () => {
  assert.equal(makeSay({})('the realm'), 'the realm');
});

test('a style can rename a word the plain theme uses', () => {
  const style = makeSay(cleanWords({ tripwires: 'little birds', realm: 'kingdom' }));
  assert.equal(style('TRIPWIRES'), 'LITTLE BIRDS');
  assert.equal(style('Edit realm'), 'Edit kingdom');
});

test('anything that is not a plain word stays out of the table', () => {
  assert.deepEqual(cleanWords({ realm: '<img src=x>', rite: 'a'.repeat(31), ok: 'fine', x: 'short key' }),
                   { ok: 'fine' });
  assert.deepEqual(cleanWords(null), {});
  assert.deepEqual(cleanWords('realm'), {});
});

test('the choice is lore unless standard was stored', () => {
  const box = { v: null, getItem() { return this.v; }, setItem(_, v) { this.v = v; } };
  assert.equal(readMode(box), 'lore');
  writeMode(box, 'standard');
  assert.equal(readMode(box), 'standard');
  assert.equal(readMode(null), 'lore');
  assert.equal(readMode({ getItem() { throw new Error('blocked'); } }), 'lore');
});
