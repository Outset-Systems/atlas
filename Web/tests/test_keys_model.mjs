// What a key on the map means (static/js/keys-model.js), with no DOM: the
// 11-12 audit's Map 1, 4, 5, 8 and 9, each a case below. The browser pane
// cannot open a region, so these are where the region's keys are proved.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mapKey, regionKey, describe } from '../static/js/keys-model.js';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const JS = join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'js');

const key = (k, extra = {}) => ({ key: k, tag: 'BODY', editable: false, ctrl: false, meta: false, alt: false, ...extra });
const MAP = { region: false, scene: false, glass: false, card: false, away: false };
const REGION = { ...MAP, region: true };

test('Map 1: Escape in a region with a scene open goes to the scene, not the region', () => {
  assert.equal(regionKey(key('Escape'), { ...REGION, scene: true }), null);
  assert.equal(mapKey(key('Escape'), { ...REGION, scene: true }), 'escape');
  // with nothing over it, Escape closes the card first, then leaves the region
  assert.equal(regionKey(key('Escape'), { ...REGION, card: true }), 'close-card');
  assert.equal(regionKey(key('Escape'), REGION), 'leave-region');
  // the glass swallows the first Escape alone, through the camera's handler
  assert.equal(regionKey(key('Escape'), { ...REGION, glass: true, card: true }), null);
});

test('Map 4: in a region a chord is the browser\'s, not s, d or h', () => {
  for (const k of ['s', 'd', 'h']) {
    for (const mod of ['ctrl', 'meta', 'alt']) {
      assert.equal(regionKey(key(k, { [mod]: true }), REGION), null, `${mod}+${k}`);
    }
  }
  assert.equal(regionKey(key('h'), REGION), 'leave-to-map');
  assert.equal(regionKey(key('d'), REGION), 'swallow');
});

test('Map 5: the minus key zooms through the zoom that knows a region\'s floor', () => {
  assert.equal(mapKey(key('-'), MAP), 'zoom-out');
  assert.equal(regionKey(key('-'), REGION), null);   // the camera's handler takes it
});

test('Map 8: nothing steers the camera behind an open scene', () => {
  for (const k of ['ArrowLeft', 'ArrowUp', '+', '-', 'h', 'd', 's', 'n', 'g']) {
    assert.equal(mapKey(key(k), { ...MAP, scene: true }), null, k);
  }
  // the Index still opens over a scene, as it does over a view
  assert.equal(mapKey(key('m'), { ...MAP, scene: true }), 'drawer');
  // nor does the region take a key from the scene in the capture phase
  for (const k of ['h', 'Home', 'd', 's']) {
    assert.equal(regionKey(key(k), { ...REGION, scene: true }), null, k);
  }
  assert.equal(mapKey(key('Escape'), { ...MAP, scene: true }), 'escape');
});

test('Map 9: the palette opens on a bare / from the map, not from a dropdown or with a modifier', () => {
  assert.equal(mapKey(key('/'), MAP), 'palette');
  assert.equal(mapKey(key('/', { tag: 'SELECT' }), MAP), null);
  assert.equal(mapKey(key('/', { tag: 'INPUT' }), MAP), null);
  assert.equal(mapKey(key('/', { ctrl: true }), MAP), null);
  assert.equal(mapKey(key('/', { alt: true }), MAP), null);
});

test('a view over the map keeps the Index key and Escape, and nothing else', () => {
  const away = { ...MAP, away: true };
  assert.equal(mapKey(key('m'), away), 'drawer');
  assert.equal(mapKey(key('Escape'), away), 'escape');
  assert.equal(mapKey(key('ArrowLeft'), away), null);
  assert.equal(mapKey(key('/'), away), 'palette');
});

test('a field keeps its own keys, Escape included', () => {
  for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
    assert.equal(mapKey(key('Escape', { tag }), MAP), null, tag);
    assert.equal(mapKey(key('h', { tag }), MAP), null, tag);
    assert.equal(regionKey(key('Escape', { tag }), REGION), null, tag);
  }
  assert.equal(mapKey(key('h', { editable: true }), MAP), null);
});

test('the map keys still do what they did', () => {
  const want = { ArrowLeft: 'pan-left', ArrowRight: 'pan-right', ArrowUp: 'pan-up', ArrowDown: 'pan-down',
                 '+': 'zoom-in', '=': 'zoom-in', '-': 'zoom-out', Home: 'home', h: 'home', m: 'drawer',
                 d: 'descend', s: 'ascend', n: 'net', g: 'decoys', q: null };
  for (const [k, action] of Object.entries(want)) assert.equal(mapKey(key(k), MAP), action, k);
  assert.equal(regionKey(key('q'), REGION), null);
  assert.equal(regionKey(key('Escape'), MAP), null);  // no region open: never the region's
});

test('describe reads only what the two functions need', () => {
  const e = { key: 'h', target: { tagName: 'DIV', isContentEditable: false }, ctrlKey: true, metaKey: false, altKey: false };
  assert.deepEqual(describe(e), { key: 'h', tag: 'DIV', editable: false, ctrl: true, meta: false, alt: false });
});

test('every action the model can name has its case in the handler that takes it', () => {
  // the model is proved above; this proves the two handlers act on what it says
  const keys = ['Escape', '/', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-',
                'Home', 'h', 'm', 'd', 's', 'n', 'g', 'q'];
  const flags = ['region', 'scene', 'glass', 'card', 'away'];
  const states = [];
  for (let bits = 0; bits < 1 << flags.length; bits++) {
    states.push(Object.fromEntries(flags.map((f, i) => [f, !!(bits & (1 << i))])));
  }
  const named = (fn) => new Set(keys.flatMap((k) => states.map((st) => fn(key(k), st))).filter(Boolean));
  for (const [file, fn] of [['camera.js', mapKey], ['regions.js', regionKey]]) {
    const src = readFileSync(join(JS, file), 'utf8');
    for (const action of named(fn)) {
      assert.ok(src.includes(`case '${action}'`), `${file} has no case for '${action}'`);
    }
  }
});
